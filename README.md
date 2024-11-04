
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
     - Define your **GitHub organization and repository name** in the trust policy to enable OpenID Connect (OIDC) access.
     - No need to specify AWS account ID or region, as these are dynamically fetched.
     - Example trust relationship JSON in `oidc-role-template.yml`:
       ```yaml
       AssumeRolePolicyDocument:
         Version: "2012-10-17"
         Statement:
           - Effect: "Allow"
             Principal:
               Federated: "arn:aws:iam::${AWS::AccountId}:oidc-provider/token.actions.githubusercontent.com"
             Action: "sts:AssumeRoleWithWebIdentity"
             Condition:
               StringEquals:
                 "token.actions.githubusercontent.com:sub": "repo:<GitHub_Org>/<Repo_Name>:ref:refs/heads/main"
       ```
     - Replace `<GitHub_Org>` with your GitHub organization name and `<Repo_Name>` with the repository name.
     - Make sure the above configuration grants access to GitHub Actions on the `main` branch.

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

---

This README now includes the updated trust relationship configuration, allowing for dynamic fetching of account details while specifying only the GitHub organization and repository name
