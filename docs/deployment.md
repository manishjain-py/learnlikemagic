# Learn Like Magic - Deployment Guide

> **Last Updated:** October 23, 2025
> **Status:** Production deployment successful ✅

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Infrastructure Components](#infrastructure-components)
4. [Deployment Process](#deployment-process)
5. [Local Development](#local-development)
6. [CI/CD Pipeline](#cicd-pipeline)
7. [Database Management](#database-management)
8. [Troubleshooting](#troubleshooting)
9. [Architecture Considerations](#architecture-considerations)

---

## Architecture Overview

Learn Like Magic is deployed using a serverless architecture on AWS:

```
┌─────────────────────────────────────────────────────────────────┐
│                         PRODUCTION                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐         ┌──────────────┐                     │
│  │  CloudFront  │────────▶│  S3 Bucket   │  (Frontend)        │
│  │ Distribution │         │   (React)    │                     │
│  └──────────────┘         └──────────────┘                     │
│         │                                                        │
│         │  (API Calls)                                          │
│         ▼                                                        │
│  ┌──────────────┐         ┌──────────────┐                     │
│  │ App Runner   │────────▶│     ECR      │  (Backend)         │
│  │   Service    │         │ (Container   │                     │
│  │  (FastAPI)   │         │  Registry)   │                     │
│  └──────┬───────┘         └──────────────┘                     │
│         │                                                        │
│         │  (Database Connection)                                │
│         ▼                                                        │
│  ┌──────────────┐         ┌──────────────┐                     │
│  │ RDS Aurora   │◀───────▶│   Secrets    │                     │
│  │  Serverless  │         │   Manager    │                     │
│  │ (PostgreSQL) │         │              │                     │
│  └──────────────┘         └──────────────┘                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Technologies

- **Infrastructure as Code:** Terraform
- **Backend:** FastAPI + LangGraph (Python)
- **Frontend:** React + Vite
- **Database:** PostgreSQL (RDS Aurora Serverless v2)
- **Container Runtime:** AWS App Runner
- **Container Registry:** Amazon ECR
- **CDN:** CloudFront + S3
- **CI/CD:** GitHub Actions with OIDC
- **Secrets:** AWS Secrets Manager

---

## Prerequisites

### Required Tools

1. **AWS CLI** (v2+)
   ```bash
   brew install awscli
   aws configure
   ```

2. **Terraform** (v1.5+)
   ```bash
   brew install terraform
   ```

3. **Docker with Buildx** (for multi-architecture builds)
   ```bash
   brew install docker
   docker buildx version  # Should be installed by default
   ```

4. **GitHub CLI** (for secrets management)
   ```bash
   brew install gh
   gh auth login
   ```

5. **Node.js** (v18+) and **Python** (3.11+)
   ```bash
   brew install node python@3.11
   ```

### AWS Account Setup

- AWS Account with appropriate permissions
- Region: `us-east-1` (configurable in `terraform.tfvars`)
- AWS credentials configured locally

---

## Infrastructure Components

### 1. Backend (AWS App Runner)

**Service:** `llm-backend-prod`
**URL:** https://ypwbjbcmbd.us-east-1.awsapprunner.com
**Architecture:** AMD64/x86_64 (⚠️ **IMPORTANT**)

**Resources:**
- CPU: 1 vCPU
- Memory: 2 GB
- Auto-scaling: 1-5 instances
- Health check: HTTP GET `/`

### 2. Frontend (S3 + CloudFront)

**Bucket:** `learnlikemagic-frontend-production`
**CloudFront URL:** https://dlayb9nj2goz.cloudfront.net

**Features:**
- SPA routing with CloudFront Functions
- HTTPS redirect
- Gzip/Brotli compression
- Custom error pages (404 → index.html)

### 3. Database (RDS Aurora Serverless)

**Cluster:** `learnlikemagic-production`
**Endpoint:** `learnlikemagic-production.cluster-cgp4ua06a7ei.us-east-1.rds.amazonaws.com`
**Engine:** PostgreSQL (Aurora Serverless v2)

**Scaling:**
- Min capacity: 0.5 ACU
- Max capacity: 2 ACU
- Auto-pause: After 5 minutes of inactivity

### 4. Secrets (AWS Secrets Manager)

- `learnlikemagic-production-openai-api-key` - OpenAI API key
- `learnlikemagic-production-db-password` - Database password

### 5. Container Registry (ECR)

**Repository:** `learnlikemagic-backend-production`
**Lifecycle:** Keep last 10 images

---

## Deployment Process

### Initial Setup (One-Time)

#### 1. Configure Terraform Variables

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
```

Edit the following:
```hcl
project_name    = "learnlikemagic"
environment     = "production"
aws_region      = "us-east-1"
github_repo     = "manishjain-py/learnlikemagic"
openai_api_key  = "sk-..."  # Your OpenAI API key
db_username     = "llmuser"
db_password     = "..."     # Strong password
```

#### 2. Initialize and Deploy Infrastructure

```bash
cd infra/terraform
make init       # Initialize Terraform
make plan       # Review changes
make apply      # Deploy infrastructure
```

This creates:
- ✅ ECR repository
- ✅ RDS Aurora database
- ✅ Secrets Manager secrets
- ✅ IAM roles (App Runner, GitHub Actions)
- ✅ S3 bucket + CloudFront distribution

#### 3. Initialize Database

```bash
# Build and run migration container
cd llm-backend
docker buildx build --platform linux/amd64 -t llm-backend:migrate .

# Run migrations
docker run --rm \
  -e DATABASE_URL="postgresql://llmuser:PASSWORD@learnlikemagic-production.cluster-cgp4ua06a7ei.us-east-1.rds.amazonaws.com:5432/learnlikemagic" \
  llm-backend:migrate \
  python db.py --migrate

# Seed data
docker run --rm \
  -e DATABASE_URL="..." \
  llm-backend:migrate \
  python db.py --seed-guidelines data/seed_guidelines.json
```

#### 4. Build and Push Initial Image

```bash
cd llm-backend

# IMPORTANT: Build for AMD64 architecture (AWS App Runner requirement)
make build-prod   # Or: docker buildx build --platform linux/amd64 -t learnlikemagic-backend:amd64 .

# Push to ECR
make push
```

#### 5. Deploy App Runner Service

```bash
cd infra/terraform
make apply   # Creates App Runner service with the ECR image
```

Wait 3-5 minutes for deployment. Check status:
```bash
aws apprunner describe-service \
  --service-arn $(terraform output -raw app_runner_service_arn) \
  --region us-east-1 \
  --query 'Service.Status'
```

#### 6. Configure GitHub Secrets

```bash
cd infra/terraform
make gh-secrets  # Exports Terraform outputs to GitHub secrets
```

This configures:
- `AWS_ROLE_ARN` - For OIDC authentication
- `ECR_REGISTRY` - Container registry URL
- `ECR_REPOSITORY` - Repository name
- `APP_RUNNER_SERVICE_ARN` - Service ARN for deployments
- `FRONTEND_BUCKET` - S3 bucket name
- `CLOUDFRONT_DISTRIBUTION_ID` - For cache invalidation
- `VITE_API_URL` - Backend API URL for frontend

---

## Local Development

### Backend

#### Setup
```bash
cd llm-backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

#### Environment Variables
Create `.env`:
```bash
DATABASE_URL=postgresql://llmuser:password@localhost:5432/tutor
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
ENVIRONMENT=development
API_HOST=0.0.0.0
API_PORT=8000
```

#### Run Locally
```bash
# Without Docker
make run

# With Docker (builds for local architecture)
make build-local
make run-docker
```

### Frontend

```bash
cd llm-frontend
npm install
npm run dev
```

Access at: http://localhost:5173

---

## CI/CD Pipeline

### Automated Deployments

**Backend:** Deploys on push to `main` when files in `llm-backend/` change
**Frontend:** Deploys on push to `main` when files in `llm-frontend/` change

### Backend Workflow (`.github/workflows/deploy-backend.yml`)

```yaml
1. Checkout code
2. Configure AWS credentials (OIDC)
3. Login to ECR
4. Build Docker image (--platform linux/amd64) ⚠️ CRITICAL
5. Push to ECR
6. Trigger App Runner deployment
7. Wait for deployment to complete
```

### Frontend Workflow (`.github/workflows/deploy-frontend.yml`)

```yaml
1. Checkout code
2. Install dependencies (npm ci)
3. Build production bundle (VITE_API_URL from secrets)
4. Configure AWS credentials (OIDC)
5. Sync to S3
6. Invalidate CloudFront cache
```

### Manual Deployment

Trigger manually via GitHub Actions:
1. Go to **Actions** tab
2. Select workflow (Deploy Backend / Deploy Frontend)
3. Click **Run workflow**
4. Select branch and run

---

## Database Management

### Migrations

Run migrations manually before deploying new schema changes:

```bash
cd llm-backend

# Build migration container (AMD64 for consistency)
docker buildx build --platform linux/amd64 -t llm-migrate .

# Run migration
docker run --rm \
  -e DATABASE_URL="postgresql://llmuser:PASSWORD@ENDPOINT:5432/learnlikemagic" \
  llm-migrate \
  python db.py --migrate
```

### Seeding Data

```bash
docker run --rm \
  -e DATABASE_URL="..." \
  llm-migrate \
  python db.py --seed-guidelines data/seed_guidelines.json
```

### Connecting to Database

```bash
# Via psql
psql postgresql://llmuser:PASSWORD@learnlikemagic-production.cluster-cgp4ua06a7ei.us-east-1.rds.amazonaws.com:5432/learnlikemagic

# Get connection string from Terraform
cd infra/terraform
terraform output database_url
```

### Backup

Aurora automatically creates backups. Retention: 7 days.

Manual snapshot:
```bash
aws rds create-db-cluster-snapshot \
  --db-cluster-identifier learnlikemagic-production \
  --db-cluster-snapshot-identifier manual-backup-$(date +%Y%m%d-%H%M%S) \
  --region us-east-1
```

---

## Troubleshooting

### Common Issues

#### 1. **App Runner Health Check Failures**

**Symptoms:**
- Service status: `CREATE_FAILED` or `UPDATE_FAILED`
- Health check errors in logs

**Common Causes:**
1. **Architecture mismatch** (ARM64 vs AMD64) ⚠️ **MOST COMMON**
2. Missing environment variables
3. Database connection issues
4. Application startup errors

**Solution:**
```bash
# Check image architecture
docker inspect IMAGE_ID --format='{{.Architecture}}'

# Should be: amd64
# If arm64, rebuild:
cd llm-backend
make build-prod  # Builds for AMD64
make push
```

#### 2. **No Application Logs**

**Symptoms:**
- Only service logs visible
- No `/aws/apprunner/.../application` log group

**Cause:** Container not starting (check architecture first!)

**Debug:**
```bash
# Check service logs
aws logs tail /aws/apprunner/llm-backend-prod/SERVICE_ID/service \
  --region us-east-1 \
  --follow

# Test locally with exact env
docker run --rm \
  -e DATABASE_URL="..." \
  -e OPENAI_API_KEY="..." \
  -e LLM_MODEL="gpt-4o-mini" \
  -e ENVIRONMENT="production" \
  -p 8000:8000 \
  learnlikemagic-backend:amd64
```

#### 3. **Database Connection Errors**

**Check:**
1. Database is running: `aws rds describe-db-clusters --region us-east-1`
2. Security group allows connections
3. Credentials are correct
4. Database URL format: `postgresql://user:pass@host:5432/dbname`

#### 4. **Secrets Manager Access Issues**

**Symptoms:**
- App crashes on startup
- "Access denied" errors

**Solution:**
Verify IAM instance role has permissions:
```bash
# Check role policy
aws iam get-role-policy \
  --role-name learnlikemagic-apprunner-instance-production \
  --policy-name secrets-access
```

Should include:
```json
{
  "Effect": "Allow",
  "Action": ["secretsmanager:GetSecretValue"],
  "Resource": ["arn:aws:secretsmanager:...:secret:learnlikemagic-production-openai-api-key-*"]
}
```

### Viewing Logs

```bash
# App Runner service logs
aws logs tail /aws/apprunner/llm-backend-prod/SERVICE_ID/service \
  --region us-east-1 \
  --follow

# App Runner application logs (once running)
aws logs tail /aws/apprunner/llm-backend-prod/SERVICE_ID/application \
  --region us-east-1 \
  --follow
```

### Health Checks

```bash
# Backend health
curl https://ypwbjbcmbd.us-east-1.awsapprunner.com/

# Database health
curl https://ypwbjbcmbd.us-east-1.awsapprunner.com/health/db

# Frontend
curl https://dlayb9nj2goz.cloudfront.net/
```

---

## Architecture Considerations

### ⚠️ CRITICAL: Docker Image Architecture

**Problem:**
AWS App Runner runs on **AMD64/x86_64** architecture. Building Docker images on Apple Silicon Macs (M1/M2/M3) produces **ARM64** images by default, which **WILL NOT RUN** on App Runner.

**Solution:**
Always build for AMD64:

```bash
# ✅ CORRECT (for production)
docker buildx build --platform linux/amd64 -t image:tag .

# ❌ WRONG (on Mac M-series)
docker build -t image:tag .  # This builds ARM64
```

**How to verify:**
```bash
docker inspect IMAGE_ID --format='{{.Architecture}}'
# Must output: amd64
```

**Built-in safeguards:**
1. `Makefile` has separate targets:
   - `make build-local` - For local dev (native architecture)
   - `make build-prod` - For AWS (AMD64)

2. GitHub Actions explicitly specifies `--platform linux/amd64`

### Environment Variables vs Secrets Manager

**Runtime Environment Variables** (plain text):
- `API_HOST`, `API_PORT`, `DATABASE_URL`, `LLM_MODEL`, `ENVIRONMENT`

**Runtime Environment Secrets** (from Secrets Manager):
- `OPENAI_API_KEY`

App Runner fetches secrets at runtime and injects them as environment variables.

### Configuration Validation

The app validates required configuration **at runtime** (not import time):

```python
# config.py - Field is optional at import
openai_api_key: str = Field(default="", ...)

# main.py - Validates at startup
@app.on_event("startup")
async def startup_event():
    validate_required_settings()  # Raises error if missing
```

This allows the container to start (passing health checks) while still enforcing required configs.

### Cost Optimization

- **RDS Aurora Serverless v2:** Auto-scales to 0 when idle
- **App Runner:** Pay per request + compute time
- **CloudFront:** Free tier covers ~50GB/month
- **S3:** Minimal storage costs

**Estimated monthly cost (low traffic):** ~$10-30

### Scaling

**Backend:**
- Auto-scales: 1-5 instances
- Modify in `infra/terraform/modules/app-runner/main.tf`

**Database:**
- Auto-scales: 0.5-2 ACU
- Modify in `infra/terraform/modules/database/main.tf`

**Frontend:**
- CloudFront scales automatically
- No configuration needed

---

## Useful Commands

### Terraform

```bash
cd infra/terraform

make init         # Initialize
make plan         # Preview changes
make apply        # Deploy
make destroy      # Tear down (⚠️ deletes data)
make outputs      # Show outputs
make summary      # Deployment summary
```

### Backend

```bash
cd llm-backend

make help         # Show all commands
make build-prod   # Build for AWS (AMD64)
make push         # Push to ECR
make deploy       # Build + push + trigger deployment
make check-arch   # Verify image architecture
```

### AWS CLI

```bash
# App Runner status
aws apprunner describe-service \
  --service-arn ARN \
  --region us-east-1

# ECR images
aws ecr describe-images \
  --repository-name learnlikemagic-backend-production \
  --region us-east-1

# RDS clusters
aws rds describe-db-clusters \
  --db-cluster-identifier learnlikemagic-production \
  --region us-east-1
```

---

## Security Best Practices

1. **Secrets:** Never commit to git - use Secrets Manager
2. **IAM:** Follow least-privilege principle
3. **Database:** Not publicly accessible (App Runner connects via AWS network)
4. **HTTPS:** Enforced via CloudFront
5. **CORS:** Configured to allow frontend domain only

---

## Maintenance

### Regular Tasks

- **Weekly:** Review CloudWatch logs for errors
- **Monthly:** Check AWS costs, optimize if needed
- **Quarterly:** Review and rotate secrets
- **Yearly:** Update dependencies (Terraform, Python packages, Node packages)

### Updating Dependencies

**Backend:**
```bash
cd llm-backend
pip install --upgrade -r requirements.txt
pip freeze > requirements.txt
# Test, commit, and deploy
```

**Frontend:**
```bash
cd llm-frontend
npm update
npm audit fix
# Test, commit, and deploy
```

---

## Support & Resources

- **Terraform Docs:** https://registry.terraform.io/providers/hashicorp/aws/latest/docs
- **App Runner Docs:** https://docs.aws.amazon.com/apprunner/
- **FastAPI Docs:** https://fastapi.tiangolo.com/
- **LangGraph Docs:** https://langchain-ai.github.io/langgraph/

---

## Appendix: Full Deployment Checklist

### First-Time Setup
- [ ] Install prerequisites (AWS CLI, Terraform, Docker, etc.)
- [ ] Configure AWS credentials
- [ ] Clone repository
- [ ] Create `terraform.tfvars` with secrets
- [ ] Run `terraform init && terraform apply`
- [ ] Initialize database (migrations + seed)
- [ ] Build Docker image for AMD64
- [ ] Push to ECR
- [ ] Deploy App Runner service
- [ ] Configure GitHub secrets
- [ ] Test endpoints

### Subsequent Deployments
- [ ] Make code changes
- [ ] Test locally
- [ ] Commit to git
- [ ] Push to `main` branch
- [ ] GitHub Actions deploys automatically
- [ ] Verify deployment in AWS console
- [ ] Test production endpoints

---

**Document Version:** 1.0
**Last Verified:** October 23, 2025
**Deployment Status:** ✅ Production Ready
