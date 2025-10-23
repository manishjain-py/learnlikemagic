# Learn Like Magic - Development Workflow

> **Guide for developers working on Learn Like Magic**
> **Last Updated:** October 23, 2025

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Environment Setup](#development-environment-setup)
3. [Daily Development Workflow](#daily-development-workflow)
4. [Making Changes](#making-changes)
5. [Testing](#testing)
6. [Deployment](#deployment)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## Getting Started

### Prerequisites

- **Git** installed and configured
- **Python 3.11+** for backend
- **Node.js 18+** for frontend
- **Docker** with buildx support
- **AWS CLI** configured (for deployments)
- **GitHub CLI** (optional, for managing secrets)

### Clone Repository

```bash
git clone https://github.com/manishjain-py/learnlikemagic.git
cd learnlikemagic
```

---

## Development Environment Setup

### Backend Setup

```bash
cd llm-backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
DATABASE_URL=postgresql://llmuser:password@localhost:5432/tutor
OPENAI_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4o-mini
ENVIRONMENT=development
API_HOST=0.0.0.0
API_PORT=8000
EOF
```

### Frontend Setup

```bash
cd llm-frontend

# Install dependencies
npm install

# Create .env file
cat > .env << EOF
VITE_API_URL=http://localhost:8000
EOF
```

### Local Database Setup (Optional)

If you want a local PostgreSQL instance:

```bash
# Using Docker
docker run -d \
  --name llm-postgres \
  -e POSTGRES_USER=llmuser \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=tutor \
  -p 5432:5432 \
  postgres:15-alpine

# Run migrations
cd llm-backend
python db.py --migrate
python db.py --seed-guidelines data/seed_guidelines.json
```

Or use the production database (read-only recommended):

```bash
# In .env, use production DB URL (get from Terraform outputs)
DATABASE_URL=postgresql://llmuser:PASSWORD@learnlikemagic-production.cluster-cgp4ua06a7ei.us-east-1.rds.amazonaws.com:5432/learnlikemagic
```

---

## Daily Development Workflow

### 1. Start Your Day

```bash
# Pull latest changes
git checkout main
git pull origin main

# Create a feature branch
git checkout -b feature/your-feature-name
```

### 2. Run Backend Locally

```bash
cd llm-backend
source venv/bin/activate  # Activate venv

# Run with auto-reload
make run
# Or: uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Backend available at: http://localhost:8000
# API docs at: http://localhost:8000/docs
```

### 3. Run Frontend Locally

```bash
cd llm-frontend

# Start dev server with hot reload
npm run dev

# Frontend available at: http://localhost:5173
```

### 4. Make Changes

Edit files, test locally, iterate...

### 5. Commit Changes

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "Add feature: description of what you did"

# Push to your branch
git push origin feature/your-feature-name
```

### 6. Create Pull Request

1. Go to: https://github.com/manishjain-py/learnlikemagic/pulls
2. Click "New pull request"
3. Select your branch
4. Fill in description
5. Request review
6. Merge after approval

### 7. Deploy to Production

After merging to `main`, deployments happen automatically via GitHub Actions.

---

## Making Changes

### Backend Changes

#### File Structure

```
llm-backend/
├── main.py              # FastAPI app entry point
├── models.py            # Pydantic models
├── config.py            # Configuration/settings
├── database.py          # Database manager
├── db.py                # Database operations
├── graph/               # LangGraph implementation
│   ├── build_graph.py
│   ├── nodes.py
│   └── state.py
├── guideline_repository.py  # Teaching guidelines
├── requirements.txt     # Python dependencies
├── Dockerfile          # Container definition
├── entrypoint.sh       # Container startup script
└── Makefile           # Build automation
```

#### Adding a New API Endpoint

1. **Define model in `models.py`:**

```python
from pydantic import BaseModel

class NewFeatureRequest(BaseModel):
    param1: str
    param2: int

class NewFeatureResponse(BaseModel):
    result: str
```

2. **Add endpoint in `main.py`:**

```python
@app.post("/new-feature", response_model=NewFeatureResponse)
def new_feature(request: NewFeatureRequest, db: DBSession = Depends(get_db)):
    """Your endpoint description."""
    try:
        # Your logic here
        return NewFeatureResponse(result="success")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

3. **Test locally:**

```bash
curl -X POST http://localhost:8000/new-feature \
  -H "Content-Type: application/json" \
  -d '{"param1": "value", "param2": 123}'
```

#### Adding Database Tables/Models

1. **Define model in `db.py`:**

```python
from sqlalchemy import Column, String, Integer

class NewTable(Base):
    __tablename__ = "new_table"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
```

2. **Create migration function:**

```python
def migrate_new_table():
    """Create new_table."""
    Base.metadata.create_all(bind=engine, tables=[NewTable.__table__])
```

3. **Run migration:**

```bash
python db.py --migrate
```

### Frontend Changes

#### File Structure

```
llm-frontend/
├── src/
│   ├── components/      # React components
│   ├── pages/          # Page components
│   ├── api/            # API client
│   ├── hooks/          # Custom hooks
│   ├── utils/          # Utility functions
│   ├── App.tsx         # Main app component
│   └── main.tsx        # Entry point
├── public/             # Static assets
├── package.json        # Node dependencies
└── vite.config.ts      # Vite configuration
```

#### Adding a New Component

1. **Create component file:**

```typescript
// src/components/NewComponent.tsx
import React from 'react';

interface NewComponentProps {
  title: string;
  onAction: () => void;
}

export const NewComponent: React.FC<NewComponentProps> = ({ title, onAction }) => {
  return (
    <div>
      <h2>{title}</h2>
      <button onClick={onAction}>Click me</button>
    </div>
  );
};
```

2. **Use in parent component:**

```typescript
import { NewComponent } from '../components/NewComponent';

// In your component
<NewComponent
  title="My Title"
  onAction={() => console.log('Clicked')}
/>
```

#### Calling Backend APIs

```typescript
// src/api/client.ts
const API_URL = import.meta.env.VITE_API_URL;

export async function createSession(data: CreateSessionRequest) {
  const response = await fetch(`${API_URL}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`);
  }

  return response.json();
}
```

---

## Testing

### Backend Testing

```bash
cd llm-backend

# Run all tests
pytest

# Run specific test file
pytest tests/test_api.py

# Run with coverage
pytest --cov=. --cov-report=html

# Test specific endpoint manually
curl http://localhost:8000/health/db
```

### Frontend Testing

```bash
cd llm-frontend

# Run unit tests
npm test

# Run E2E tests (if configured)
npm run test:e2e

# Type checking
npm run type-check

# Linting
npm run lint
```

### Manual Testing Checklist

Before deploying:

- [ ] Backend health endpoint works: `GET /`
- [ ] Database health works: `GET /health/db`
- [ ] Can create session: `POST /sessions`
- [ ] Can submit step: `POST /sessions/{id}/step`
- [ ] Frontend loads and connects to backend
- [ ] Can complete a full tutoring session
- [ ] No console errors in browser
- [ ] No Python exceptions in backend logs

---

## Deployment

### Understanding the Deployment Pipeline

```
Developer Push to main
    ↓
GitHub Actions Triggered
    ↓
├── Backend Workflow (.github/workflows/deploy-backend.yml)
│   1. Build Docker image (AMD64 platform) ⚠️ IMPORTANT
│   2. Push to ECR
│   3. Trigger App Runner deployment
│   └── Backend live at: https://ypwbjbcmbd.us-east-1.awsapprunner.com
│
└── Frontend Workflow (.github/workflows/deploy-frontend.yml)
    1. Build React app with production API URL
    2. Upload to S3
    3. Invalidate CloudFront cache
    └── Frontend live at: https://dlayb9nj2goz.cloudfront.net
```

### Automatic Deployment

**Backend:** Triggers when files in `llm-backend/**` change

```bash
# Make changes in backend
cd llm-backend
# Edit files...

git add .
git commit -m "Backend: add new feature"
git push origin main

# GitHub Actions automatically deploys
# Monitor at: https://github.com/manishjain-py/learnlikemagic/actions
```

**Frontend:** Triggers when files in `llm-frontend/**` change

```bash
# Make changes in frontend
cd llm-frontend
# Edit files...

git add .
git commit -m "Frontend: update UI"
git push origin main

# GitHub Actions automatically deploys
```

### Manual Deployment

#### Option 1: Via GitHub UI

1. Go to: https://github.com/manishjain-py/learnlikemagic/actions
2. Select workflow (Deploy Backend or Deploy Frontend)
3. Click "Run workflow"
4. Select branch: `main`
5. Click "Run workflow"

#### Option 2: Via Command Line

**Backend:**

```bash
cd llm-backend

# Build for production (AMD64 architecture)
make build-prod

# Push to ECR and trigger deployment
make deploy
```

**Frontend:**

```bash
cd llm-frontend

# Build production bundle
npm run build

# Deploy to S3 (requires AWS credentials)
aws s3 sync dist/ s3://learnlikemagic-frontend-production --delete

# Invalidate CloudFront cache
aws cloudfront create-invalidation \
  --distribution-id E19EYV4ZGTL1L9 \
  --paths "/*"
```

### Deployment Verification

After deployment completes:

```bash
# Check backend health
curl https://ypwbjbcmbd.us-east-1.awsapprunner.com/
curl https://ypwbjbcmbd.us-east-1.awsapprunner.com/health/db

# Check frontend
curl https://dlayb9nj2goz.cloudfront.net/

# Check App Runner status
aws apprunner describe-service \
  --service-arn arn:aws:apprunner:us-east-1:926211191776:service/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd \
  --region us-east-1 \
  --query 'Service.Status'
```

Expected: `"RUNNING"`

---

## Troubleshooting

### Common Issues

#### 1. **Backend not starting locally**

**Symptom:** `uvicorn main:app` fails

**Causes & Solutions:**

```bash
# Missing dependencies?
pip install -r requirements.txt

# Wrong Python version?
python --version  # Should be 3.11+

# Missing .env file?
cp .env.example .env  # Then edit with your values

# Database connection issue?
# Check DATABASE_URL in .env
# Verify database is running (if local)
docker ps | grep postgres
```

#### 2. **Frontend can't connect to backend**

**Symptom:** API calls fail with CORS or connection errors

**Causes & Solutions:**

```bash
# Wrong API URL?
# Check llm-frontend/.env
echo $VITE_API_URL  # Should be http://localhost:8000 for dev

# Backend not running?
curl http://localhost:8000/  # Should return {"status":"ok"}

# CORS issue?
# Backend CORS is configured for "*" in development
# Check main.py for CORS middleware
```

#### 3. **Deployment fails with "Health check failed"**

**Symptom:** App Runner deployment fails after ~30s

**Most Common Cause:** Architecture mismatch (ARM64 vs AMD64)

**Solution:**

```bash
# Verify image architecture
docker inspect IMAGE_ID --format='{{.Architecture}}'
# Must be: amd64

# If arm64, rebuild:
cd llm-backend
make build-prod  # Builds for AMD64
make push
```

**Other causes:**
- Missing environment variables (check App Runner configuration)
- Database connection issues (verify DATABASE_URL)
- Application startup errors (check CloudWatch logs)

#### 4. **GitHub Actions workflow doesn't trigger**

**Symptom:** Push to main doesn't trigger deployment

**Cause:** Path filter in workflow

**Solution:**

Backend workflow only triggers when:
- Files in `llm-backend/**` change, OR
- `.github/workflows/deploy-backend.yml` changes

Frontend workflow only triggers when:
- Files in `llm-frontend/**` change, OR
- `.github/workflows/deploy-frontend.yml` changes

To manually trigger:
1. Go to Actions tab
2. Select workflow
3. Click "Run workflow"

#### 5. **Environment variables not available in production**

**Symptom:** App crashes with missing env var error

**Check GitHub Secrets:**

Required secrets:
- `AWS_REGION` = us-east-1
- `AWS_ROLE_ARN` = arn:aws:iam::...
- `ECR_REGISTRY` = 926211191776.dkr.ecr...
- `ECR_REPOSITORY` = learnlikemagic-backend-production
- `APP_RUNNER_SERVICE_ARN` = arn:aws:apprunner:...
- `FRONTEND_BUCKET` = learnlikemagic-frontend-production
- `CLOUDFRONT_DISTRIBUTION_ID` = E19EYV4ZGTL1L9
- `VITE_API_URL` = https://ypwbjbcmbd.us-east-1.awsapprunner.com

**Set/update secrets:**

```bash
# Using script
./scripts/set-github-secrets.sh

# Or manually at:
# https://github.com/manishjain-py/learnlikemagic/settings/secrets/actions
```

### Viewing Logs

**Backend (App Runner):**

```bash
# Service logs (infrastructure)
aws logs tail /aws/apprunner/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd/service \
  --region us-east-1 \
  --follow

# Application logs (your app)
aws logs tail /aws/apprunner/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd/application \
  --region us-east-1 \
  --follow
```

**Frontend (CloudFront/S3):**

```bash
# CloudFront access logs (if enabled)
aws s3 ls s3://your-logs-bucket/

# Browser console
# Open developer tools in browser
```

**GitHub Actions:**

View at: https://github.com/manishjain-py/learnlikemagic/actions

---

## Best Practices

### Code Quality

1. **Type hints in Python:**
   ```python
   def create_session(data: CreateSessionRequest) -> CreateSessionResponse:
       ...
   ```

2. **TypeScript in React:**
   ```typescript
   interface Props {
     title: string;
     count: number;
   }

   const MyComponent: React.FC<Props> = ({ title, count }) => { ... }
   ```

3. **Error handling:**
   ```python
   try:
       result = risky_operation()
   except SpecificException as e:
       logger.error(f"Failed: {e}")
       raise HTTPException(status_code=500, detail=str(e))
   ```

4. **Logging:**
   ```python
   import logging
   logger = logging.getLogger(__name__)

   logger.info("Processing request")
   logger.error(f"Error: {error}")
   ```

### Git Workflow

1. **Branch naming:**
   - `feature/add-user-auth`
   - `fix/session-creation-bug`
   - `docs/update-readme`

2. **Commit messages:**
   ```
   Add user authentication endpoint

   - Implement login/logout API
   - Add JWT token generation
   - Update user model with password hash
   ```

3. **Pull before push:**
   ```bash
   git pull origin main
   git push origin your-branch
   ```

4. **Keep branches small:**
   - One feature per branch
   - Merge frequently
   - Delete merged branches

### Security

1. **Never commit secrets:**
   ```bash
   # Add to .gitignore:
   .env
   *.key
   *.pem
   credentials.json
   ```

2. **Use environment variables:**
   ```python
   # Good
   api_key = os.getenv("OPENAI_API_KEY")

   # Bad
   api_key = "sk-hardcoded-key"
   ```

3. **Validate inputs:**
   ```python
   @app.post("/endpoint")
   def endpoint(request: ValidatedModel):  # Pydantic validates
       ...
   ```

### Performance

1. **Database queries:**
   ```python
   # Use indexes
   # Avoid N+1 queries
   # Use pagination for large results
   ```

2. **API responses:**
   ```python
   # Return only necessary data
   # Use response models to filter
   ```

3. **Frontend:**
   ```typescript
   // Use React.memo for expensive components
   // Lazy load routes
   // Optimize images
   ```

### Documentation

1. **API endpoints:**
   ```python
   @app.get("/sessions/{session_id}")
   def get_session(session_id: str):
       """
       Retrieve session by ID.

       Args:
           session_id: UUID of the session

       Returns:
           Session details with history and state

       Raises:
           404: Session not found
       """
   ```

2. **Code comments:**
   ```python
   # WHY, not WHAT
   # Good: "Validate early to fail fast and provide better errors"
   # Bad:  "Check if valid"
   ```

3. **Update docs when changing:**
   - API endpoints → Update API docs
   - Configuration → Update deployment.md
   - Workflows → Update dev-workflow.md

---

## Quick Reference

### Essential Commands

```bash
# Backend development
cd llm-backend
make run                # Run locally
make build-prod         # Build for production (AMD64)
make deploy            # Build + push + deploy
make db-migrate        # Run migrations
make check-arch        # Verify image architecture

# Frontend development
cd llm-frontend
npm run dev            # Run dev server
npm run build          # Build production
npm run lint           # Check code quality
npm test               # Run tests

# Git workflow
git checkout -b feature/name    # New branch
git add .                       # Stage changes
git commit -m "message"         # Commit
git push origin feature/name    # Push
# Create PR on GitHub
# Merge after review
# Automatic deployment on merge to main

# Deployment
# Automatic: Push to main (if path matches)
# Manual: GitHub Actions → Run workflow
# Local: make deploy (backend) or manual S3 sync (frontend)

# Monitoring
# Logs: AWS CloudWatch
# Actions: https://github.com/manishjain-py/learnlikemagic/actions
# Backend: https://ypwbjbcmbd.us-east-1.awsapprunner.com
# Frontend: https://dlayb9nj2goz.cloudfront.net
```

---

## Support & Resources

- **Deployment Guide:** See `docs/deployment.md`
- **GitHub Repository:** https://github.com/manishjain-py/learnlikemagic
- **GitHub Actions:** https://github.com/manishjain-py/learnlikemagic/actions
- **FastAPI Docs:** https://fastapi.tiangolo.com/
- **React Docs:** https://react.dev/
- **LangGraph Docs:** https://langchain-ai.github.io/langgraph/

---

**Document Version:** 1.0
**Last Updated:** October 23, 2025
**Status:** ✅ Active
