# Learn Like Magic - Terraform Infrastructure

This directory contains Terraform configuration for deploying Learn Like Magic to AWS using fully managed services.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                      AWS Cloud                          │
│                                                         │
│  ┌──────────────┐      ┌──────────────┐               │
│  │  CloudFront  │      │  App Runner  │               │
│  │  (Frontend)  │─────▶│  (Backend)   │               │
│  └──────────────┘      └──────┬───────┘               │
│         │                      │                        │
│         ▼                      ▼                        │
│  ┌──────────────┐      ┌──────────────┐               │
│  │  S3 Bucket   │      │    Aurora    │               │
│  │  (Static)    │      │  PostgreSQL  │               │
│  └──────────────┘      └──────────────┘               │
│                                                         │
│  ┌──────────────┐      ┌──────────────┐               │
│  │     ECR      │      │   Secrets    │               │
│  │  (Docker)    │      │   Manager    │               │
│  └──────────────┘      └──────────────┘               │
│                                                         │
│  ┌─────────────────────────────────────┐               │
│  │      GitHub OIDC (CI/CD)            │               │
│  └─────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

## Components

| Service | Purpose | Approximate Cost/Month |
|---------|---------|----------------------|
| **Aurora Serverless v2** | PostgreSQL database | $10-20 |
| **App Runner** | Backend container service | $15-25 |
| **S3** | Frontend static hosting | < $1 |
| **CloudFront** | CDN for frontend | $1-5 |
| **ECR** | Docker image registry | < $1 |
| **Secrets Manager** | Secure secret storage | < $1 |
| **GitHub OIDC** | CI/CD authentication | Free |
| **Total** | | **~$30-50/month** |

## Prerequisites

### 1. Install Tools

```bash
# Terraform
brew install terraform  # macOS
# or download from https://www.terraform.io/downloads

# AWS CLI
brew install awscli
# or pip install awscli

# jq (for JSON parsing)
brew install jq
```

### 2. Configure AWS Credentials

```bash
aws configure
# Enter your AWS Access Key ID
# Enter your AWS Secret Access Key
# Enter your default region (e.g., us-east-1)
```

### 3. Prepare Configuration

```bash
cd infra/terraform

# Copy example configuration
cp terraform.tfvars.example terraform.tfvars

# Edit terraform.tfvars with your values
nano terraform.tfvars
```

**Required values in `terraform.tfvars`:**
```hcl
aws_region      = "us-east-1"
github_org      = "your-github-username"
github_repo     = "learnlikemagic"
db_password     = "STRONG_PASSWORD_HERE"
openai_api_key  = "sk-your-openai-api-key"
```

## Deployment Steps

### Step 1: Initialize Terraform

```bash
terraform init
```

This downloads AWS provider and initializes modules.

### Step 2: Plan Infrastructure

```bash
terraform plan
```

Review the resources that will be created (~40 resources).

### Step 3: Apply Configuration

```bash
terraform apply
```

Type `yes` to confirm. This takes **10-15 minutes** to provision:
- Aurora cluster initialization: ~5 min
- App Runner service: ~3 min
- CloudFront distribution: ~5 min
- Other resources: ~2 min

### Step 4: Get Outputs

```bash
terraform output
```

You'll see:
- Frontend URL (CloudFront domain)
- Backend API URL (App Runner)
- Database endpoint
- GitHub Actions role ARN
- All environment variables for GitHub secrets

### Step 5: Export GitHub Secrets

See [Setting Up GitHub Secrets](#setting-up-github-secrets) below.

## Module Structure

```
modules/
├── database/        # Aurora Serverless v2 PostgreSQL
├── app-runner/      # Backend container service
├── ecr/             # Docker image registry
├── frontend/        # S3 + CloudFront for static site
├── secrets/         # AWS Secrets Manager
└── github-oidc/     # GitHub Actions IAM role
```

### Database Module

**Resources:**
- Aurora Serverless v2 cluster (PostgreSQL 15)
- Database subnet group
- Security group
- Parameter groups

**Scaling:**
- Min capacity: 0.5 ACU
- Max capacity: 2 ACU
- Auto-scales based on load

### App Runner Module

**Resources:**
- App Runner service
- IAM roles (access + instance)
- Auto-scaling configuration

**Configuration:**
- CPU: 1 vCPU
- Memory: 2 GB
- Min instances: 1
- Max instances: 5
- Max concurrency: 100

### Frontend Module

**Resources:**
- S3 bucket with block public access
- CloudFront distribution with OAI
- CloudFront Function for SPA routing
- Cache policy

**Features:**
- HTTPS only (redirect HTTP)
- Global CDN
- SPA routing support

### Secrets Module

**Resources:**
- OpenAI API key secret
- Database password secret

**Recovery:**
- 7-day recovery window if deleted

### ECR Module

**Resources:**
- ECR repository for backend images
- Lifecycle policy (keep last 10 images)

**Security:**
- Image scanning on push
- Encryption at rest (AES256)

### GitHub OIDC Module

**Resources:**
- OIDC provider for GitHub
- IAM role with web identity
- Policies for ECR, S3, CloudFront, App Runner

**Benefits:**
- No static AWS credentials
- Automatic rotation
- Scoped to specific repository

## Setting Up GitHub Secrets

After `terraform apply`, export outputs to GitHub secrets:

### Manual Method

1. Get the outputs:
```bash
terraform output github_secrets
```

2. Go to GitHub: `https://github.com/YOUR_ORG/learnlikemagic/settings/secrets/actions`

3. Add these secrets:
   - `AWS_REGION`
   - `AWS_ROLE_ARN`
   - `ECR_REPOSITORY`
   - `ECR_REGISTRY`
   - `APP_RUNNER_SERVICE_ARN`
   - `FRONTEND_BUCKET`
   - `CLOUDFRONT_DISTRIBUTION_ID`
   - `VITE_API_URL`

### Automated Method (with gh CLI)

```bash
# Install GitHub CLI
brew install gh
gh auth login

# Export all secrets automatically
for key in $(terraform output -json github_secrets | jq -r 'keys[]'); do
  value=$(terraform output -json github_secrets | jq -r ".[\"$key\"]")
  gh secret set "$key" --body "$value"
done
```

## Post-Deployment Tasks

### 1. Push Initial Backend Image

The App Runner service needs a Docker image in ECR:

```bash
# Get ECR login
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin $(terraform output -raw ecr_repository_url | cut -d'/' -f1)

# Build and push
cd ../../llm-backend
docker build -t backend .
docker tag backend:latest $(terraform output -raw ecr_repository_url):latest
docker push $(terraform output -raw ecr_repository_url):latest
```

### 2. Run Database Migrations

```bash
# Get database endpoint
DB_ENDPOINT=$(terraform output -raw database_endpoint)

# Update your local .env temporarily
DATABASE_URL="postgresql://llmuser:YOUR_PASSWORD@$DB_ENDPOINT:5432/tutor"

# Run migrations
cd ../../llm-backend
source .venv/bin/activate
python db.py --migrate
```

### 3. Deploy Frontend

```bash
cd ../../llm-frontend

# Build with correct API URL
VITE_API_URL=$(terraform output -raw app_runner_service_url) npm run build

# Upload to S3
aws s3 sync dist/ s3://$(terraform output -raw frontend_bucket_name)/

# Invalidate CloudFront cache
aws cloudfront create-invalidation \
  --distribution-id $(terraform output -raw cloudfront_distribution_id) \
  --paths "/*"
```

### 4. Access Your Application

```bash
# Get frontend URL
terraform output frontend_url

# Open in browser
open $(terraform output -raw frontend_url)
```

## CI/CD Integration

After setting up GitHub secrets, your workflows will automatically deploy on push to `main`.

See `.github/workflows/` for:
- `deploy-frontend.yml` - Frontend deployment
- `deploy-backend.yml` - Backend deployment

## Maintenance

### View Logs

```bash
# App Runner logs
aws logs tail /aws/apprunner/$(terraform output -raw app_runner_service_arn | cut -d'/' -f2)/service --follow

# Aurora logs
aws rds describe-db-log-files \
  --db-instance-identifier $(terraform output -raw cluster_id)
```

### Update Infrastructure

```bash
# Modify .tf files or terraform.tfvars
terraform plan
terraform apply
```

### Scale Resources

Edit `modules/app-runner/main.tf`:
```hcl
instance_configuration {
  cpu    = "2 vCPU"  # Increase from 1
  memory = "4 GB"    # Increase from 2
}
```

Then `terraform apply`.

## Troubleshooting

### App Runner Service Failed

```bash
# Check service status
aws apprunner list-operations \
  --service-arn $(terraform output -raw app_runner_service_arn)

# View detailed logs
aws logs tail /aws/apprunner/.../service --follow
```

### Database Connection Failed

1. Check security group allows inbound on port 5432
2. Verify database credentials
3. Ensure App Runner is in same VPC

### Frontend Not Loading

1. Check S3 bucket has files: `aws s3 ls s3://$(terraform output -raw frontend_bucket_name)/`
2. Check CloudFront distribution status: `aws cloudfront get-distribution --id $(terraform output -raw cloudfront_distribution_id)`
3. Try invalidating cache

## Cost Optimization

### Development Environment

To reduce costs for dev:

1. **Aurora**: Set min_capacity to 0.5 ACU (already configured)
2. **App Runner**: Use smaller instance (0.25 vCPU, 0.5 GB)
3. **CloudFront**: Use PriceClass_100 (North America + Europe only)

### Pause Development

```bash
# Stop App Runner (still charges for provisioned instances)
# Better: reduce to min instances = 0

# Aurora automatically scales to 0.5 ACU when idle
```

## Cleanup

To destroy all resources:

```bash
terraform destroy
```

**Warning:** This deletes:
- Database (all data lost)
- S3 bucket (all frontend files)
- ECR images
- All other resources

Make backups first!

## Security Best Practices

### Production Checklist

- [ ] Set `deletion_protection = true` on Aurora cluster
- [ ] Set `skip_final_snapshot = false` on Aurora
- [ ] Enable CloudTrail logging
- [ ] Enable VPC Flow Logs
- [ ] Use ACM certificate for custom domain
- [ ] Restrict database security group to App Runner only
- [ ] Enable AWS Backup for Aurora
- [ ] Set up CloudWatch alarms
- [ ] Enable AWS WAF on CloudFront
- [ ] Rotate secrets regularly

### Secrets Management

Never commit:
- `terraform.tfvars`
- `*.tfstate`
- `.terraform/`

These are already in `.gitignore`.

## Support

For issues:
1. Check logs (App Runner, CloudWatch)
2. Verify all secrets are set
3. Check GitHub Actions run status
4. Review Terraform state: `terraform show`

## Next Steps

After deployment:
1. Set up custom domain (Route 53 + ACM)
2. Configure production database backup schedule
3. Add CloudWatch alarms for monitoring
4. Set up staging environment (separate Terraform workspace)

---

**Infrastructure Version**: 1.0
**Last Updated**: 2025-10-22
