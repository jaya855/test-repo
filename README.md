
# FastAPI Deployment Pipeline

This README provides instructions to set up and deploy the FastAPI application using GitHub Actions and AWS resources.

## Prerequisites

1. **Set up GitHub Secrets**: Configure the following GitHub secrets in your repository:
   - `AWS_ACCOUNT_ID`: Your AWS account ID.
   - `OIDC_ROLE`: The IAM role name created for OpenID Connect (OIDC) access.
   - `AWS_REGION`: The AWS region for deployment (e.g., `ap-south-1`).

2. **AWS Resource Configuration**:
   - Update AWS resource identifiers in the pipeline as needed:
     - `REPO_NAME`: Specify the ECR repository name (default: `my-fastapi-app`).
     - `ROLE_NAME`: Update the IAM role name if needed (default: `tts-role`).
     - CloudFormation `stack-name`: Use a custom stack name if desired.

3. **CloudFormation Setup for OIDC Role**:
   - Before running the pipeline, **create an OIDC role** in your AWS account using the provided CloudFormation template `oidc-role-template.yml` in this repository.
   - Ensure that the created role has sufficient permissions for deploying resources.
   - **Adjustments to make in the OIDC Role Template**:
     - Replace `121263836368` in all ARNs within the `oidc-role-template.yml` file with your own AWS account ID.
     - Change the `ap-south-1` region in the ARNs if deploying in a different AWS region.

4. **Modify Deployment Parameters**:
   - Replace occurrences of `121263836368` in ARNs with your AWS account ID across all templates and files.
   - Replace `ap-south-1` with your AWS region wherever applicable.
   - Ensure S3 bucket name uniqueness by renaming it if necessary to avoid conflicts.

5. **IAM and Security Configuration**:
   - Review and adjust IAM role permissions and policies as needed for your AWS account structure and security requirements.

## Running the Deployment Pipeline

1. Push changes to the `main` branch to trigger the GitHub Actions deployment workflow.
2. The pipeline will:
   - Build and push the Docker image to Amazon ECR.
   - Deploy the CloudFormation stack, creating necessary infrastructure and deploying the application.

## Testing the Application

To test the deployed application, use `curl` to upload a CSV file:

```bash
curl -X POST <your-alb-dns-link>/upload-csv/ -F "file=@sample_hi-IN.csv" -F "source=hi-IN"
```

Replace `<your-alb-dns-link>` with the DNS of your Application Load Balancer.

## Notes

- Run tests to ensure successful deployment in the target environment.
