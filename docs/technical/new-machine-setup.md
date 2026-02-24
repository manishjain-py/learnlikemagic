# New Machine Setup

How to get a fully working development environment after cloning the repo on a new machine.

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** and npm
- **AWS CLI** configured with credentials (`aws configure`)
- **Git**

## 1. Clone the Repo

```bash
git clone git@github.com:manishjain-py/learnlikemagic.git
cd learnlikemagic
```

## 2. Copy Secret Files

These files are gitignored and must be copied manually from an existing machine. They are **not** in the repo.

| File | What It Contains |
|------|-----------------|
| `llm-backend/.env` | API keys (OpenAI, Anthropic, Gemini, CCAPI), database URL, Cognito config |
| `llm-frontend/.env` | Cognito pool/client IDs, Google OAuth client ID |
| `e2e/.env` | E2E test account email and password |
| `infra/terraform/terraform.tfvars` | Terraform variables: DB credentials, API keys, domain config, ACM cert ARN |

### Quick copy

On the **source machine**, from the project root:

```bash
tar czf ~/learnlikemagic-secrets.tar.gz \
  llm-backend/.env \
  llm-frontend/.env \
  e2e/.env \
  infra/terraform/terraform.tfvars
```

Transfer `~/learnlikemagic-secrets.tar.gz` to the new machine, then from the project root:

```bash
tar xzf ~/learnlikemagic-secrets.tar.gz
```

### What each file configures

**`llm-backend/.env`** — Core backend configuration:
- `OPENAI_API_KEY` — OpenAI API access
- `ANTHROPIC_API_KEY` — Anthropic API access
- `GEMINI_API_KEY` — Google Gemini API access
- `CCAPI_API_KEY`, `CCAPI_BASE_URL` — CCAPI provider access
- `TUTOR_LLM_PROVIDER`, `GLM_MODEL` — Active LLM provider and model
- `LLM_MODEL` — Default OpenAI model
- `DATABASE_URL` — Production PostgreSQL connection string (RDS)
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT` — Connection pool settings
- `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `COGNITO_REGION` — AWS Cognito auth
- `API_HOST`, `API_PORT`, `LOG_LEVEL`, `ENVIRONMENT` — App settings

**`llm-frontend/.env`** — Frontend configuration:
- `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`, `VITE_COGNITO_REGION` — Auth config
- `VITE_COGNITO_DOMAIN` — Cognito hosted UI domain
- `VITE_GOOGLE_CLIENT_ID` — Google OAuth client ID

**`e2e/.env`** — Playwright test credentials:
- `E2E_TEST_EMAIL` — Test account email
- `E2E_TEST_PASSWORD` — Test account password

**`infra/terraform/terraform.tfvars`** — Infrastructure-as-code variables:
- AWS region, environment name
- GitHub org/repo (for OIDC)
- Database name, user, password
- API keys (OpenAI, Gemini, Anthropic)
- Domain names and ACM certificate ARN

### Alternative: recreate from templates

If you don't have access to an existing machine, use the example files as templates:
- `llm-backend/.env.example` → copy to `llm-backend/.env` and fill in values
- `infra/terraform/terraform.tfvars.example` → copy to `infra/terraform/terraform.tfvars` and fill in values

You'll need to obtain API keys from each provider and database credentials from AWS.

## 3. Backend Setup

```bash
cd llm-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Important:** The venv is at `llm-backend/venv` (not `.venv`). Always activate it before running backend commands.

Run the backend:

```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 4. Frontend Setup

```bash
cd llm-frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:5173` by default.

## 5. E2E Test Setup

```bash
cd e2e
npm install
npx playwright install
```

Run tests:

```bash
npx playwright test
```

## 6. AWS CLI

Ensure your AWS credentials are configured for the `us-east-1` region:

```bash
aws configure
# AWS Access Key ID: <your key>
# AWS Secret Access Key: <your secret>
# Default region name: us-east-1
# Default output format: json
```

This is needed for Cognito auth to work locally and for any Terraform operations.

## 7. Terraform (Optional)

Only needed if you're making infrastructure changes:

```bash
cd infra/terraform
terraform init
terraform plan
```

## Verification Checklist

- [ ] `llm-backend/.env` exists and has API keys
- [ ] `llm-frontend/.env` exists and has Cognito config
- [ ] `e2e/.env` exists and has test credentials
- [ ] Backend starts: `cd llm-backend && source venv/bin/activate && uvicorn app.main:app --reload`
- [ ] Frontend starts: `cd llm-frontend && npm run dev`
- [ ] Can log in via the frontend at `http://localhost:5173`

## Related Docs

- [Dev Workflow](dev-workflow.md) — daily development workflow, testing, deployment
- [Architecture Overview](architecture-overview.md) — full-stack architecture and conventions
- [Deployment](deployment.md) — AWS infrastructure and CI/CD
