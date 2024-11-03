
# FastAPI Deployment Pipeline with AWS and GitHub Actions

This repository contains a FastAPI app that deploys on AWS ECS using GitHub Actions with OIDC for secure access.

## Prerequisites

1. **GitHub Secrets**:
   - `AWS_ACCOUNT_ID`: Your AWS Account ID.
   - `OIDC_ROLE`: IAM role name for GitHub Actions.
   - `AWS_REGION`: AWS region for deployment (e.g., `ap-south-1`).

2. **Environment Variable Adjustments**:
   - Replace `121263836368` with your AWS Account ID in ARNs.
   - Update `ap-south-1` if deploying to another region.
   - Rename S3 bucket to ensure uniqueness.

## Steps to Deploy

1. **Set up GitHub Secrets** as above.
2. **Modify Resource Names** as needed in `.github/workflows/deploy.yml`:
   - Update `REPO_NAME`, `ROLE_NAME`, and `stack-name` as per your setup.
3. **Run Tests** to confirm successful deployment.

## Testing with `curl`

Once deployed, use `curl` to upload a CSV file:

```bash
curl -X POST <your-alb-dns-link>/upload-csv/ -F "file=@sample_hi-IN.csv" -F "source=hi-IN"
```

Replace `<your-alb-dns-link>` with your ALB DNS name.

## Key Files

- **Dockerfile**: Docker configuration for FastAPI app.
- **deploy.yml**: GitHub Actions workflow for CI/CD.
- **cloudformation/deploy.yml**: CloudFormation template for AWS resources.

## Note
Ensure IAM roles and permissions are properly set up to avoid permission errors.
