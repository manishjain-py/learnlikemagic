# Deployment

AWS infrastructure, Terraform, CI/CD, and production operations.

---

## Architecture

```
+-------------------------------------------------------------+
|  CloudFront --> S3 (React+Vite)                  [Frontend]  |
|       |                                                      |
|       v                                                      |
|  App Runner --> ECR (FastAPI container)           [Backend]   |
|       |                                                      |
|       v                                                      |
|  RDS Aurora Serverless v2 (PostgreSQL 15.10)     [Database]  |
|                                                              |
|  Secrets Manager (OpenAI, Gemini, Anthropic, DB password)    |
|  Cognito (Authentication)                                    |
|  S3 Books Bucket (Book ingestion storage)                    |
+-------------------------------------------------------------+
```

**Stack:** Terraform (AWS provider ~5.0), FastAPI, React+Vite, Aurora Serverless v2, App Runner, GitHub Actions (OIDC)

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

**Dockerfile:** Uses `python:3.11-slim`, copies `entrypoint.sh` as CMD. The entrypoint script checks for required env vars (`DATABASE_URL`, `OPENAI_API_KEY`) before starting Uvicorn.

**Build note:** `make build-prod` copies `docs/` into the backend build context before building, then removes it after. The CI/CD pipeline does the same via `cp -r docs/ llm-backend/docs/` and also copies `e2e/scenarios.json` into `llm-backend/e2e/`.

---

## Initial Setup

### 1. Configure Terraform

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit with your values:
#   project_name, environment, aws_region
#   github_org, github_repo
#   db_name, db_user, db_password
#   openai_api_key, gemini_api_key, anthropic_api_key
#   tutor_llm_provider, llm_model
#   domain_names (optional), acm_certificate_arn (optional)
```

### 2. Deploy Infrastructure

```bash
make init && make plan && make apply
```

Creates: ECR, RDS Aurora Serverless v2, Secrets Manager (3-4 secrets; Anthropic is conditional), IAM roles, S3 + CloudFront, GitHub OIDC provider

### 3. Initialize Database

```bash
cd llm-backend
docker buildx build --platform linux/amd64 -t llm-backend:migrate .

# Migrate
docker run --rm -e DATABASE_URL="postgresql://user:pass@endpoint:5432/tutor" \
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

Sets (via Terraform outputs): `AWS_REGION`, `AWS_ROLE_ARN`, `ECR_REGISTRY`, `ECR_REPOSITORY`, `APP_RUNNER_SERVICE_ARN`, `FRONTEND_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`, `VITE_API_URL`

**Additional secrets to set manually** (not in Terraform outputs):
- `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`, `VITE_COGNITO_REGION`, `VITE_COGNITO_DOMAIN` -- Required for frontend auth
- `VITE_GOOGLE_CLIENT_ID` -- Required for Google sign-in
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` -- Required for daily coverage email reports

---

## CI/CD

### Workflows

| Workflow | File | Trigger | What it does |
|----------|------|---------|--------------|
| Deploy Backend | `deploy-backend.yml` | Push to `main` (changes in `llm-backend/**`, `docs/**`, `e2e/scenarios.json`, or the workflow file); manual | Build AMD64 image --> Push ECR --> Deploy App Runner --> Wait for completion |
| Deploy Frontend | `deploy-frontend.yml` | Push to `main` (changes in `llm-frontend/**` or the workflow file); manual | Build with Vite --> Sync S3 (with cache headers) --> Invalidate CloudFront |
| Manual Deploy | `manual-deploy.yml` | Manual only | Deploy frontend, backend, or both (selectable). **Note:** backend build uses native arch (no `--platform linux/amd64`) and does not copy `docs/` or `e2e/` into build context. Frontend build only passes `VITE_API_URL` (missing Cognito/Google env vars). Prefer the main deploy workflows for production |
| Daily Coverage | `daily-coverage.yml` | Daily at 6:00 AM UTC; manual | Run pytest coverage --> Generate HTML report (with priority tier breakdown) --> Email report --> Upload artifacts (30-day retention) --> Check 80% threshold |

All workflows use **GitHub OIDC** for AWS authentication (no long-lived credentials).

### Backend Deploy Details

1. Checkout code
2. Configure AWS via OIDC (`aws-actions/configure-aws-credentials@v4`)
3. Login to ECR (`aws-actions/amazon-ecr-login@v2`)
4. Copy `docs/` and `e2e/scenarios.json` into backend build context
5. Build AMD64 Docker image (tagged with commit SHA + `latest`)
6. Push both tags to ECR
7. Trigger App Runner deployment via `aws apprunner start-deployment`
8. Wait for deployment to complete

### Frontend Deploy Details

1. Checkout, configure AWS, setup Node.js 18
2. `npm ci` and `npm run build` with environment variables:
   - `VITE_API_URL`, `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`
   - `VITE_COGNITO_REGION`, `VITE_COGNITO_DOMAIN`, `VITE_GOOGLE_CLIENT_ID`
3. S3 sync: all assets with `max-age=31536000, immutable`; `index.html` with `no-cache, no-store, must-revalidate`
4. CloudFront cache invalidation (`/*`)

### Daily Coverage Details

1. Checkout, setup Python 3.11, install dependencies
2. Run `pytest tests/unit/` with JSON + HTML coverage reports
3. Generate styled HTML report with priority tier breakdown:
   - **P0 (Critical Runtime, target 90%):** tutor agents/services/orchestration, shared services/repositories
   - **P1 (Business Logic, target 80%):** shared models/utils/prompts, study plans
   - **P2 (Offline Pipeline, target 70%):** book ingestion
   - **P3 (Infrastructure, target 60%):** config, database, API routes, evaluation
4. Email report via SMTP (`scripts/send_coverage_report.py`)
5. Upload artifacts (HTML report, JSON data, coverage output) with 30-day retention
6. Fail if overall coverage < 80%

---

## Terraform Modules

```
infra/terraform/
  main.tf              # Root module: wires all sub-modules together
  variables.tf         # Input variables
  outputs.tf           # Outputs (URLs, ARNs, GitHub secrets map)
  Makefile             # Automation targets
  modules/
    secrets/           # Secrets Manager (OpenAI, Gemini, DB password; Anthropic conditional)
    database/          # Aurora Serverless v2 cluster + instance + security group
    ecr/               # ECR repository + lifecycle policy (keep last 10 images)
    app-runner/        # App Runner service + IAM roles (ECR access, Secrets, S3)
    frontend/          # S3 bucket + CloudFront distribution + SPA routing function
    github-oidc/       # OIDC provider + IAM role for GitHub Actions
```

---

## Quick Commands

### Terraform
```bash
cd infra/terraform
make init          # Initialize Terraform
make plan          # Preview changes
make apply         # Deploy infrastructure
make apply-auto    # Deploy without confirmation prompt
make outputs       # Show all outputs
make gh-secrets    # Export outputs to GitHub secrets
make summary       # Show deployment summary
make urls          # Show frontend + backend URLs
make fe-url        # Show frontend URL only
make be-url        # Show backend API URL only
make db-url        # Show database connection string
make tf-fmt        # Format Terraform files
make tf-validate   # Validate configuration
make destroy       # Tear down (requires confirmation)
make clean         # Remove .terraform, .terraform.lock.hcl, and tfstate backup (keeps terraform.tfstate)
make setup         # Print step-by-step initial setup guide
```

### Backend
```bash
cd llm-backend
make run           # Start locally with uvicorn --reload
make test          # Run pytest
make build-local   # Build Docker image for local dev (native arch)
make build-prod    # Build AMD64 for AWS (copies docs/ into context)
make run-docker    # Run local Docker container with .env file
make push          # Login to ECR + tag + push
make deploy        # build-prod + push + trigger App Runner
make check-arch    # Show system and Docker image architecture
make db-migrate    # Run python db.py --migrate
make clean         # Remove __pycache__, .pytest_cache, etc.
```

### Database
```bash
# Connect
psql postgresql://user:pass@endpoint:5432/tutor

# Backup
aws rds create-db-cluster-snapshot \
  --db-cluster-identifier learnlikemagic-production \
  --db-cluster-snapshot-identifier backup-$(date +%Y%m%d)
```

### Logs
```bash
# Application logs
aws logs tail /aws/apprunner/llm-backend-prod/SERVICE_ID/application --follow

# Service logs
aws logs tail /aws/apprunner/llm-backend-prod/SERVICE_ID/service --follow
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
| Container exits immediately | Missing `DATABASE_URL` or `OPENAI_API_KEY` | `entrypoint.sh` checks these on startup; verify secrets are set |
| DB connection error | Security group / credentials | Verify RDS is running, check connection string |
| Secrets access denied | IAM permissions | Check App Runner instance role policy |
| Frontend auth not working | Missing Cognito secrets | Set `VITE_COGNITO_*` and `VITE_GOOGLE_CLIENT_ID` in GitHub secrets |

---

## Infrastructure Details

| Component | Config |
|-----------|--------|
| App Runner | 1 vCPU, 2GB RAM, 1-5 instances, max 100 concurrent requests |
| Aurora | PostgreSQL 15.10, 0.5-2 ACU, 7-day backup retention |
| ECR | Keep last 10 images, scan on push, AES256 encryption |
| CloudFront | HTTPS redirect, gzip+brotli, SPA routing via CloudFront Function, OAI for S3 access |
| Secrets Manager | 4 secrets (OpenAI, Gemini, Anthropic, DB password), 7-day recovery window |

**Estimated cost (low traffic):** ~$10-30/month

---

## Key Files

| File | Purpose |
|------|---------|
| `infra/terraform/main.tf` | Root Terraform module |
| `infra/terraform/variables.tf` | All input variables |
| `infra/terraform/outputs.tf` | Outputs including GitHub secrets map |
| `infra/terraform/Makefile` | Terraform automation targets |
| `llm-backend/Makefile` | Backend build/deploy automation |
| `llm-backend/Dockerfile` | Backend container definition (python:3.11-slim) |
| `llm-backend/entrypoint.sh` | Container startup script (env var checks + uvicorn) |
| `.github/workflows/deploy-backend.yml` | Backend CI/CD pipeline |
| `.github/workflows/deploy-frontend.yml` | Frontend CI/CD pipeline |
| `.github/workflows/manual-deploy.yml` | Manual deployment workflow |
| `.github/workflows/daily-coverage.yml` | Daily test coverage report + email |
| `llm-backend/scripts/send_coverage_report.py` | SMTP email sender for coverage reports |
| `e2e/scenarios.json` | E2E test scenarios (bundled into backend Docker image during CI/CD) |
