import re
import os
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import logging
from fastapi.middleware.cors import CORSMiddleware
from langdetect import detect, LangDetectException
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import pandas as pd
import requests
import uuid
from os import environ

app = FastAPI()

# Set up CORS middleware to allow requests from specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins, change as needed
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# Environment Variable Fetching and Validation
S3_BUCKET_NAME = environ.get('S3_BUCKET_NAME')
IAM_ROLE_ARN = environ.get('IAM_ROLE_ARN')
ALB_DNS_NAME = environ.get('ALB_DNS_NAME')

# Logging the environment variable values
print(f"S3_BUCKET_NAME: {S3_BUCKET_NAME}")
print(f"IAM_ROLE_ARN: {IAM_ROLE_ARN}")
print(f"ALB_DNS_NAME: {ALB_DNS_NAME}")

# Verify the necessary environment variables
if not all([S3_BUCKET_NAME, IAM_ROLE_ARN, ALB_DNS_NAME]):
    raise EnvironmentError("One or more required environment variables are not set.")

# Set up logging
logging.basicConfig(level=logging.INFO)

# S3 folder configuration
S3_INPUT_FOLDER = "input/"
S3_SSML_FOLDER = "ssml/"
S3_AUDIO_FOLDER = "audio/"

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Homepage endpoint
@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Clean text function to remove placeholder text
def clean_text(text):
    return re.sub(r'\[.*?\]', '', text)

# Convert timestamp function
def convert_timestamp_to_seconds(timestamp):
    try:
        minutes, seconds = map(int, timestamp.split(':'))
        return minutes * 60 + seconds
    except ValueError:
        return 0  # Default to 0 if timestamp is not in the correct format

# Function to assume IAM role
def assume_role(role_arn=IAM_ROLE_ARN, session_name="MySession"):
    try:
        sts_client = boto3.client('sts')
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name
        )
        credentials = assumed_role['Credentials']
        session = boto3.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        return session
    except ClientError as e:
        logging.error(f"Failed to assume role: {e}")
        raise e

# Function to upload file to S3
def upload_file_to_s3(file_data, filename, folder):
    try:
        if not S3_BUCKET_NAME:
            raise ValueError("S3_BUCKET_NAME environment variable is not set.")
        
        s3_client = boto3.client('s3')
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=f"{folder}{filename}", Body=file_data)
        logging.info(f"Uploaded {filename} to S3 in folder {folder}")
        return f"s3://{S3_BUCKET_NAME}/{folder}{filename}"
    except NoCredentialsError:
        logging.error("Credentials are not configured correctly for S3.")
        raise
    except ClientError as e:
        logging.error(f"Error uploading file to S3: {e}")
        raise e

# Retrieve Azure secrets from AWS Secrets Manager
def get_azure_secrets(secret_name="azure-secrets", region_name="ap-south-1"):
    try:
        session = assume_role()
        secrets_client = session.client(service_name="secretsmanager", region_name=region_name)
        secret_response = secrets_client.get_secret_value(SecretId=secret_name)
        return eval(secret_response["SecretString"])
    except NoCredentialsError:
        logging.error("Credentials are not configured correctly for Secrets Manager.")
        raise
    except ClientError as e:
        logging.error(f"Error retrieving secret: {e}")
        raise e

# Retrieve supported voices from Azure Speech API
def get_supported_voices():
    azure_secrets = get_azure_secrets()
    AZURE_API_KEY = azure_secrets["AZURE_API_KEY"]
    AZURE_REGION = azure_secrets["AZURE_REGION"]
    headers = {"Ocp-Apim-Subscription-Key": AZURE_API_KEY}
    response = requests.get(f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/voices/list", headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"Failed to fetch Azure voices: {response.status_code} {response.text}")
        raise Exception("Unable to retrieve supported voices from Azure.")

# Generate SSML and upload to S3
def generate_ssml(df, lang_column, male_voice, female_voice, xml_lang):
    if lang_column not in df.columns:
        raise ValueError(f"Column '{lang_column}' not found in CSV.")
    
    ssml_filename = f"{uuid.uuid4()}.ssml"
    ssml_content = f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{xml_lang}'>\n"
    last_timestamp = 0

    for _, row in df.iterrows():
        speaker = row.get('Speaker', 'spk_0')
        transcription = clean_text(row.get(lang_column, ''))
        if not transcription:
            continue

        timestamp_seconds = convert_timestamp_to_seconds(row.get('Time Markers', '0:00'))
        delay = max(0, timestamp_seconds - last_timestamp)
        last_timestamp = timestamp_seconds

        if delay > 0:
            ssml_content += f"<break time='{delay}s' />\n"
        
        voice = male_voice if speaker == 'spk_0' else female_voice
        ssml_content += f"<voice name='{voice}'>{transcription}</voice>\n"

    ssml_content += "</speak>"
    ssml_s3_path = upload_file_to_s3(ssml_content.encode('utf-8'), ssml_filename, S3_SSML_FOLDER)
    return ssml_s3_path

# Convert SSML to audio and upload to S3
async def convert_ssml_to_audio(ssml_s3_path):
    azure_secrets = get_azure_secrets()
    AZURE_API_KEY = azure_secrets["AZURE_API_KEY"]
    AZURE_REGION = azure_secrets["AZURE_REGION"]

    s3_key = ssml_s3_path.split(f"s3://{S3_BUCKET_NAME}/")[1]
    s3_client = boto3.client('s3')
    ssml_object = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
    ssml_data = ssml_object['Body'].read().decode('utf-8')

    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_API_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"
    }
    response = requests.post(f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1", headers=headers, data=ssml_data)
    
    if response.status_code == 200:
        audio_filename = f"{uuid.uuid4()}.wav"
        audio_s3_path = upload_file_to_s3(response.content, audio_filename, S3_AUDIO_FOLDER)
        return audio_s3_path
    else:
        logging.error(f"Error from Azure API: {response.text}")
        raise Exception(f"Error from Azure API: {response.text}")

# Detect language
def detect_language(text):
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"

# Find transcription column
def find_transcription_column(df, locale_code):
    for column in df.columns:
        if locale_code in column and column.endswith('--Transcription'):
            return column
    return None

# Upload CSV endpoint
@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...), source: str = Form(...)):
    try:
        source_cleaned = source.strip().replace("\\", "").replace("\n", "").replace("\t", "")
        contents = await file.read()
        
        try:
            df = pd.read_csv(pd.io.common.StringIO(contents.decode("utf-8")), encoding="utf-8")
        except UnicodeDecodeError:
            return {"error": "File encoding is not supported. Ensure it is UTF-8."}

        input_filename = f"{uuid.uuid4()}.csv"
        upload_file_to_s3(contents, input_filename, S3_INPUT_FOLDER)

        supported_voices = get_supported_voices()
        source_voices = [v for v in supported_voices if source_cleaned == v['Locale']]

        if not source_voices:
            return {"error": "Invalid locale or unsupported locale specified."}

        male_voice = next((v['ShortName'] for v in source_voices if "Male" in v['Gender']), None)
        female_voice = next((v['ShortName'] for v in source_voices if "Female" in v['Gender']), None)

        if not male_voice or not female_voice:
            return {"error": f"Missing male or female voice for {source_cleaned}."}

        ssml_file_path_en = generate_ssml(df, 'EN--Transcription', 'en-US-GuyNeural', 'en-US-JennyNeural', 'en-US')
        audio_file_en = await convert_ssml_to_audio(ssml_file_path_en)

        locale_code = source_cleaned.split('-')[-1]
        transcription_column = find_transcription_column(df, locale_code)

        if not transcription_column:
            return {"error": f"CSV missing column '{locale_code}--Transcription'."}

        first_transcription = df[transcription_column].dropna().iloc[0]
        detected_language = detect_language(first_transcription)

        if locale_code == "IN" and detected_language != "hi":
            return {"error": f"Expected Hindi but detected {detected_language} in 'IN--Transcription'."}

        ssml_file_path_source = generate_ssml(df, transcription_column, male_voice, female_voice, source_cleaned)
        audio_file_source = await convert_ssml_to_audio(ssml_file_path_source)

        return {
            "message": "Audio files generated successfully",
            "english_audio_link": audio_file_en,
            "language_audio_link": audio_file_source
        }
    except Exception as e:
        logging.error(f"Error processing file: {e}")
        return {"error": f"Error processing file: {e}"}
