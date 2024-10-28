import re
import os
import json
import uuid
import logging
import pandas as pd
import requests
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from langdetect import detect, LangDetectException
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

app = FastAPI()

# Fetch environment variables for AWS resources
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
IAM_ROLE_ARN = os.environ.get('IAM_ROLE_ARN')
ALB_DNS_NAME = os.environ.get('ALB_DNS_NAME')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')

# Set up CORS middleware to allow requests from specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://{ALB_DNS_NAME}/", "http://localhost:8000/"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up logging
logging.basicConfig(level=logging.INFO)

# S3 bucket configuration
S3_INPUT_FOLDER = "input/"
S3_SSML_FOLDER = "ssml/"
S3_AUDIO_FOLDER = "audio/"

# Set up templates folder for serving HTML files
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def clean_text(text):
    return re.sub(r'\[.*?\]', '', text)

def convert_timestamp_to_seconds(timestamp):
    try:
        minutes, seconds = map(int, timestamp.split(':'))
        return minutes * 60 + seconds
    except ValueError:
        return 0

def assume_role(role_arn=IAM_ROLE_ARN, session_name="MySession"):
    try:
        sts_client = boto3.client('sts')
        assumed_role_object = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
        )
        credentials = assumed_role_object['Credentials']
        session = boto3.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken'],
        )
        return session
    except ClientError as e:
        logging.error(f"Failed to assume role: {e}")
        raise e

def upload_file_to_s3(file_data, filename, folder):
    try:
        s3_client = boto3.client('s3')
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=f"{folder}{filename}", Body=file_data)
        logging.info(f"Uploaded {filename} to S3 in folder {folder}")
        return f"s3://{S3_BUCKET_NAME}/{folder}{filename}"
    except NoCredentialsError as e:
        logging.error("IAM role or credentials not set correctly")
        raise e
    except ClientError as e:
        logging.error(f"Failed to upload file to S3: {e}")
        raise e

def get_azure_secrets(secret_name="azure-secrets", region_name="ap-south-1"):
    try:
        session = assume_role()
        client = session.client(service_name="secretsmanager", region_name=region_name)
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret = get_secret_value_response["SecretString"]
        return eval(secret)
    except NoCredentialsError as e:
        logging.error("IAM role or credentials not set correctly")
        raise e
    except ClientError as e:
        logging.error(f"Failed to retrieve secret: {e}")
        raise e

def get_supported_voices():
    azure_secrets = get_azure_secrets()
    AZURE_API_KEY = azure_secrets["AZURE_API_KEY"]
    AZURE_REGION = azure_secrets["AZURE_REGION"]
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_API_KEY,
    }
    
    response = requests.get(f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/voices/list", headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"Failed to fetch Azure voices: {response.status_code} {response.text}")
        raise Exception("Unable to retrieve supported voices from Azure.")

def generate_ssml(df, lang_column, male_voice, female_voice, xml_lang):
    if lang_column not in df.columns:
        raise ValueError(f"Column '{lang_column}' not found in the CSV file.")
    
    ssml_filename = f"{uuid.uuid4()}.ssml"
    ssml_content = f"<speak xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{xml_lang}'>\n"
    
    last_timestamp = 0
    
    for index, row in df.iterrows():
        speaker = row.get('Speaker', 'spk_0')
        transcription = clean_text(row.get(lang_column, ''))
        
        if not transcription:
            continue
        
        timestamp_seconds = convert_timestamp_to_seconds(row.get('Time Markers', '0:00'))
        
        delay = max(0, timestamp_seconds - last_timestamp)
        
        last_timestamp = timestamp_seconds
        
        if delay > 0:
            ssml_content += f"<break time='{delay}s'/>"
        
        voice = male_voice if speaker == 'spk_0' else female_voice
        
        ssml_content += f"<voice name='{voice}'>{transcription}</voice>\n"
    
    ssml_content += "</speak>"
    
    # Upload SSML content directly to S3
    ssml_s3_path = upload_file_to_s3(ssml_content.encode('utf-8'), ssml_filename, S3_SSML_FOLDER)
    
    return ssml_s3_path

async def convert_ssml_to_audio(ssml_s3_path):
    azure_secrets = get_azure_secrets()
    AZURE_API_KEY = azure_secrets["AZURE_API_KEY"]
    AZURE_REGION = azure_secrets["AZURE_REGION"]
    
    s3_bucket = S3_BUCKET_NAME
    s3_key = ssml_s3_path.split(f"s3://{S3_BUCKET_NAME}/")[1]
    
    # Initialize S3 client to fetch SSML content
    s3_client = boto3.client('s3')
    
    ssml_object = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
    
    ssml_data = ssml_object['Body'].read().decode('utf-8')
    
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_API_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
    }
    
    response = requests.post(f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1", headers=headers, data=ssml_data)
    
    logging.info(f"Azure API Response Status: {response.status_code}")
    
    if response.status_code == 200:
        audio_filename = f"{uuid.uuid4()}.wav"
        
        # Upload audio content directly to S3
        audio_s3_path = upload_file_to_s3(response.content, audio_filename, S3_AUDIO_FOLDER)
        
        return audio_s3_path
    else:
        logging.error(f"Error from Azure API: {response.text}")
        raise Exception(f"Error from Azure API: {response.text}")

def detect_language(text):
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"

def find_transcription_column(df, locale_code):
    for column in df.columns:
        if locale_code in column and column.endswith('--Transcription'):
            return column
    return None

@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...), source: str = Form(...)):
    try:
        source_cleaned = source.strip().replace("\\", "").replace("\n", "").replace("\t", "")
        
        contents = await file.read()
        
        try:
            df = pd.read_csv(pd.io.common.StringIO(contents.decode("utf-8")), encoding="utf-8")
            
            # Upload the input CSV to S3
            input_filename = f"{uuid.uuid4()}.csv"
            upload_file_to_s3(contents, input_filename, S3_INPUT_FOLDER)
            
            supported_voices = get_supported_voices()
            source_voices = [v for v in supported_voices if source_cleaned == v['Locale']]
            
            if not source_voices:
                logging.error(f"Invalid locale input: {source_cleaned}")
                return {"error": "Invalid locale specified or locale not supported."}
            
            male_voice = next((v['ShortName'] for v in source_voices if "Male" in v['Gender']), None)
            female_voice = next((v['ShortName'] for v in source_voices if "Female" in v['Gender']), None)
            
            if not male_voice or not female_voice:
                logging.error(f"Male or female voice not found for {source_cleaned}")
                return {"error": f"Male or female voice not found for {source_cleaned}."}
            
            # Generate SSML for English and source language
            ssml_file_path_en = generate_ssml(df, 'EN--Transcription', 'en-US-GuyNeural', 'en-US-JennyNeural', 'en-US')
            audio_file_en = await convert_ssml_to_audio(ssml_file_path_en)

            locale_code = source_cleaned.split('-')[-1]
            transcription_column = find_transcription_column(df, locale_code)

            if not transcription_column:
                logging.error(f"CSV is missing a column containing '{locale_code}--Transcription' for the specified language.")
                return {"error": f"CSV must contain a column with '{locale_code}--Transcription' for the specified language."}

            first_transcription = df[transcription_column].dropna().iloc[0]
            detected_language = detect_language(first_transcription)

            if locale_code == "IN" and detected_language != "hi":
                logging.error(f"Detected language '{detected_language}' does not match the expected language 'Hindi' for 'IN--Transcription'")
                return {"error": f"Detected language '{detected_language}' does not match the expected language 'Hindi' in 'IN--Transcription'."}

            ssml_file_path_source = generate_ssml(df, transcription_column, male_voice, female_voice, source_cleaned)
            audio_file_source = await convert_ssml_to_audio(ssml_file_path_source)

            # Return URLs for the generated audio files
            return {
                "message": "Audio files generated successfully",
                "english_audio_link": audio_file_en,
                "language_audio_link": audio_file_source,
            }

        except UnicodeDecodeError:
            logging.error("File encoding is not supported. Please ensure the file is UTF-8 encoded.")
            return {"error": "File encoding is not supported. Please ensure the file is UTF-8 encoded."}

    except ValueError as ve:
        logging.error(f"ValueError: {str(ve)}")
        return {"error": str(ve)}
    
    except Exception as e:
        logging.error(f"Error processing file. {str(e)}")
        return {"error": f"Error processing file. {str(e)}"}

# SQS message processing function (to be triggered by AWS Lambda)
def process_sqs_message(message_body):
   request_id_json=json.loads(message_body) 
   request_id=request_id_json["request_id"]

   # Retrieve metadata from DynamoDB (implement this function based on your needs)

   # Download CSV from S3 using request_id (implement this function based on your needs)

   # Call Azure Speech API (implement this function based on your needs)

   # Save generated audio to S3 (implement this function based on your needs)

   # Update DynamoDB with final status (implement this function based on your needs)
