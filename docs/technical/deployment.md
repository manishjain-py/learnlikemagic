# Deployment

AWS infrastructure, Terraform, CI/CD, and production operations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  CloudFront → S3 (React)                      [Frontend]   │
│       │                                                     │
│       v                                                     │
│  App Runner → ECR (FastAPI container)         [Backend]    │
│       │                                                     │
│       v                                                     │
│  RDS Aurora Serverless (PostgreSQL)           [Database]   │
│                                                             │
│  Secrets Manager (API keys)                                │
│  Cognito (Authentication)                                  │
└─────────────────────────────────────────────────────────────┘
```

**Stack:** Terraform, FastAPI, React+Vite, Aurora Serverless v2, App Runner, GitHub Actions (OIDC)

---

## Production URLs

| Component | URL |
|-----------|-----|
| Backend | https://ypwbjbcmbd.us-east-1.awsapprunner.com |
| Frontend | https://dlayb9nj2goz.cloudfront.net |
| Database | `learnlikemagic-production.cluster-cgp4ua06a7ei.us-east-1.rds.amazonaws.com` |

---

## Critical: Docker Architecture

App Runner requires **AMD64**. Mac M-series builds ARM64 by default.

```bash
# Always build for production with:
docker buildx build --platform linux/amd64 -t image:tag .

# Verify architecture:
docker inspect IMAGE_ID --format='{{.Architecture}}'  # must be: amd64
```

Use `make build-prod` (not `make build-local`) for AWS deployments.

---

## Initial Setup

### 1. Configure Terraform

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit: project_name, environment, aws_region, github_repo, openai_api_key, db credentials
```

### 2. Deploy Infrastructure

```bash
make init && make plan && make apply
```

Creates: ECR, RDS Aurora, Secrets Manager, IAM roles, S3 + CloudFront

### 3. Initialize Database

```bash
cd llm-backend
docker buildx build --platform linux/amd64 -t llm-backend:migrate .

# Migrate
docker run --rm -e DATABASE_URL="postgresql://user:pass@endpoint:5432/learnlikemagic" \
  llm-backend:migrate python db.py --migrate
```

### 4. Deploy Backend

```bash
cd llm-backend
make build-prod && make push
cd ../infra/terraform && make apply
```

### 5. Configure GitHub Secrets

```bash
cd infra/terraform
make gh-secrets
```

Sets: `AWS_ROLE_ARN`, `ECR_REGISTRY`, `ECR_REPOSITORY`, `APP_RUNNER_SERVICE_ARN`, `FRONTEND_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`, `VITE_API_URL`

---

## CI/CD

Automatic deployment on push to `main`:
- **Backend:** Changes in `llm-backend/` → Build AMD64 image → Push ECR → Deploy App Runner
- **Frontend:** Changes in `llm-frontend/` → Build → Sync S3 → Invalidate CloudFront

Manual trigger: GitHub Actions → Select workflow → Run workflow

---

## Quick Commands

### Terraform
```bash
cd infra/terraform
make plan      # Preview
make apply     # Deploy
make outputs   # Show URLs/ARNs
make destroy   # Tear down
```

### Backend
```bash
cd llm-backend
make build-prod   # Build AMD64 for AWS
make push         # Push to ECR
make deploy       # Build + push + trigger
make check-arch   # Verify image is AMD64
```

### Database
```bash
# Connect
psql postgresql://user:pass@endpoint:5432/learnlikemagic

# Backup
aws rds create-db-cluster-snapshot \
  --db-cluster-identifier learnlikemagic-production \
  --db-cluster-snapshot-identifier backup-$(date +%Y%m%d)
```

### Logs
```bash
# Service logs
aws logs tail /aws/apprunner/llm-backend-prod/SERVICE_ID/service --follow

# Application logs
aws logs tail /aws/apprunner/llm-backend-prod/SERVICE_ID/application --follow
```

### Health Checks
```bash
curl https://ypwbjbcmbd.us-east-1.awsapprunner.com/
curl https://ypwbjbcmbd.us-east-1.awsapprunner.com/health/db
```

---

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| App Runner `CREATE_FAILED` | ARM64 image | Rebuild with `--platform linux/amd64` |
| No application logs | Container not starting | Check architecture, then env vars |
| DB connection error | Security group / credentials | Verify RDS is running, check connection string |
| Secrets access denied | IAM permissions | Check App Runner instance role policy |

---

## Infrastructure Details

| Component | Config |
|-----------|--------|
| App Runner | 1 vCPU, 2GB RAM, 1-5 instances |
| Aurora | 0.5-2 ACU, auto-pause after 5min |
| ECR | Keep last 10 images |
| CloudFront | HTTPS redirect, gzip, SPA routing |

**Estimated cost (low traffic):** ~$10-30/month
