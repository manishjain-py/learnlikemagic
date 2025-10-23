# Learn Like Magic - Development Workflow

> **Guide for developers working on Learn Like Magic**
> **Last Updated:** October 23, 2025
> **Version:** 1.1 - Updated with refactored architecture and testing guide

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

**Requirements:**
- Python 3.10+ (Python 3.11+ recommended to match production)

```bash
cd llm-backend

# Check Python version
python3 --version  # Should be 3.10 or higher

# Create virtual environment (use python3.11 or python3.13 if available)
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Verify venv Python version
python --version

# Install production dependencies
pip install -r requirements.txt

# Install development dependencies (testing, linting, etc.)
pip install -r requirements-dev.txt

# Create .env file - Option 1: Automated (recommended)
./scripts/setup-env.sh

# Or Option 2: Manual setup
cp .env.example .env
# Then edit .env with your credentials

# Note: .env is gitignored - never committed to repo
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
├── api/                         # API layer
│   └── routes/                 # FastAPI route handlers
│       ├── health.py           # Health check endpoints
│       ├── curriculum.py       # Curriculum discovery
│       └── sessions.py         # Session management
├── services/                    # Business logic layer
│   ├── session_service.py      # Session orchestration
│   └── graph_service.py        # Graph execution
├── repositories/                # Data access layer
│   ├── session_repository.py   # Session CRUD
│   ├── event_repository.py     # Event logging
│   └── guideline_repository.py # Guideline queries
├── graph/                       # LangGraph agent
│   ├── state.py                # State definitions
│   ├── nodes.py                # Node implementations (pure functions)
│   └── build_graph.py          # Graph compilation
├── prompts/                     # LLM prompt templates
│   ├── templates/              # Template files
│   │   ├── teaching_prompt.txt
│   │   ├── grading_prompt.txt
│   │   └── remediation_prompt.txt
│   └── loader.py               # PromptLoader class
├── models/                      # Data models (separated by concern)
│   ├── database.py             # SQLAlchemy ORM models
│   ├── domain.py               # Business logic models (Pydantic)
│   └── schemas.py              # API request/response schemas
├── utils/                       # Shared utilities
│   ├── formatting.py           # History & response formatting
│   ├── constants.py            # Centralized constants
│   └── exceptions.py           # Custom exceptions
├── tests/                       # Test suite
│   ├── conftest.py             # Pytest fixtures
│   ├── unit/                   # Unit tests
│   └── integration/            # Integration tests
├── main.py                      # FastAPI app (66 lines, clean!)
├── config.py                    # Configuration/settings
├── database.py                  # Database manager
├── db.py                        # Database operations CLI
├── llm.py                       # OpenAI LLM abstraction
├── requirements.txt             # Production dependencies
├── requirements-dev.txt         # Development dependencies
├── pytest.ini                   # Pytest configuration
├── Dockerfile                   # Container definition (Python 3.11)
├── entrypoint.sh               # Container startup script
└── Makefile                    # Build automation
```

**Key principles:**
- **SRP (Single Responsibility)**: Each module has one clear purpose
- **Layered architecture**: API → Services → Repositories → Database
- **DRY**: No code duplication, shared utilities
- **Testability**: Pure functions, dependency injection

#### Adding a New API Endpoint

Follow the layered architecture: API → Services → Repositories → Database

1. **Define request/response schemas in `models/schemas.py`:**

```python
from pydantic import BaseModel

class NewFeatureRequest(BaseModel):
    param1: str
    param2: int

class NewFeatureResponse(BaseModel):
    result: str
    status: str
```

2. **Add business logic in `services/` (if needed):**

```python
# services/new_feature_service.py
from sqlalchemy.orm import Session
from models.schemas import NewFeatureRequest, NewFeatureResponse

class NewFeatureService:
    def __init__(self, db: Session):
        self.db = db

    def process_feature(self, request: NewFeatureRequest) -> NewFeatureResponse:
        """Process the feature request."""
        # Business logic here
        return NewFeatureResponse(result="success", status="completed")
```

3. **Add endpoint in `api/routes/`:**

```python
# api/routes/new_feature.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.schemas import NewFeatureRequest, NewFeatureResponse
from services.new_feature_service import NewFeatureService

router = APIRouter(prefix="/new-feature", tags=["new-feature"])

@router.post("", response_model=NewFeatureResponse)
def create_new_feature(
    request: NewFeatureRequest,
    db: Session = Depends(get_db)
):
    """
    Process new feature request.

    Args:
        request: Feature parameters
        db: Database session

    Returns:
        NewFeatureResponse with result
    """
    try:
        service = NewFeatureService(db)
        return service.process_feature(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

4. **Register router in `main.py`:**

```python
from api.routes import health, curriculum, sessions, new_feature

app.include_router(new_feature.router)
```

5. **Add unit tests in `tests/unit/`:**

```python
# tests/unit/test_new_feature.py
import pytest
from services.new_feature_service import NewFeatureService
from models.schemas import NewFeatureRequest

def test_process_feature():
    """Test new feature processing."""
    request = NewFeatureRequest(param1="value", param2=123)
    service = NewFeatureService(db=None)  # Or use db_session fixture
    result = service.process_feature(request)
    assert result.status == "completed"
```

6. **Test locally:**

```bash
# Run unit tests
pytest tests/unit/test_new_feature.py -v

# Test API manually
curl -X POST http://localhost:8000/new-feature \
  -H "Content-Type: application/json" \
  -d '{"param1": "value", "param2": 123}'
```

#### Adding Database Tables/Models

1. **Define ORM model in `models/database.py`:**

```python
from sqlalchemy import Column, String, Integer, DateTime, func
from models.database import Base

class NewTable(Base):
    """New table for storing feature data."""
    __tablename__ = "new_table"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

2. **Create migration in `db.py`:**

```python
from models.database import Base, NewTable

def migrate_new_table():
    """Create new_table."""
    Base.metadata.create_all(bind=engine, tables=[NewTable.__table__])
```

3. **Add repository in `repositories/`:**

```python
# repositories/new_table_repository.py
from typing import Optional, List
from sqlalchemy.orm import Session
from models.database import NewTable

class NewTableRepository:
    """Repository for NewTable data access."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str) -> NewTable:
        """Create a new record."""
        record = NewTable(name=name)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_by_id(self, id: int) -> Optional[NewTable]:
        """Get record by ID."""
        return self.db.query(NewTable).filter(NewTable.id == id).first()

    def get_all(self) -> List[NewTable]:
        """Get all records."""
        return self.db.query(NewTable).all()
```

4. **Run migration:**

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

The backend uses **pytest** for automated testing with coverage reporting.

#### Test Structure

```
llm-backend/tests/
├── conftest.py          # Shared fixtures (db_session, sample data, mocks)
├── unit/                # Fast, isolated tests (no external dependencies)
│   └── test_formatting.py
└── integration/         # Tests with database, external services
```

#### Setting Up for Testing

```bash
cd llm-backend

# Ensure virtual environment is activated
source venv/bin/activate

# Install development dependencies (includes pytest)
pip install -r requirements-dev.txt

# Set dummy API key (required for module imports)
export OPENAI_API_KEY=sk-test-dummy-key
```

#### Running Tests

```bash
# Run all tests with coverage (configured in pytest.ini)
pytest

# Run specific test file
pytest tests/unit/test_formatting.py

# Run with verbose output
pytest -v

# Run only unit tests (fast, no external dependencies)
pytest -m unit

# Run only integration tests
pytest -m integration

# Run tests matching a pattern
pytest -k "test_format"

# Show detailed coverage report
pytest --cov=. --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=. --cov-report=html
# Then open: htmlcov/index.html
```

#### Test Markers

Tests are organized with markers (defined in `pytest.ini`):

- `@pytest.mark.unit` - Fast tests with no external dependencies
- `@pytest.mark.integration` - Tests requiring database or external services
- `@pytest.mark.slow` - Tests taking >1 second
- `@pytest.mark.smoke` - Quick smoke tests for deployment verification

#### Writing Tests

```python
# tests/unit/test_example.py
import pytest
from utils.formatting import format_conversation_history

class TestFormatting:
    """Tests for conversation formatting."""

    def test_format_empty_history(self):
        """Test formatting empty history returns placeholder."""
        result = format_conversation_history([])
        assert result == "(First turn - no history yet)"

    def test_format_multiple_entries(self, sample_tutor_state):
        """Test formatting history with multiple entries."""
        # Use fixtures from conftest.py
        history = sample_tutor_state.history
        result = format_conversation_history(history)
        assert "Teacher:" in result
        assert "Student:" in result
```

#### Available Fixtures

Defined in `tests/conftest.py`:

- `db_session` - In-memory SQLite database session
- `client` - FastAPI TestClient for API testing
- `sample_student` - Student data model
- `sample_goal` - Learning goal data
- `sample_tutor_state` - Complete tutor state with history
- `sample_grading_result` - Grading result data
- `mock_llm_provider` - Mocked LLM provider (no API calls)

#### Test Best Practices

1. **Arrange-Act-Assert**: Structure tests clearly
2. **One assertion per test**: Keep tests focused
3. **Use fixtures**: Leverage shared test data from conftest.py
4. **Mock external services**: Use `mock_llm_provider` for LLM calls
5. **Test edge cases**: Empty inputs, None values, error conditions
6. **Descriptive names**: `test_format_empty_history` not `test1`
7. **Docstrings**: Explain what each test verifies

#### Manual API Testing

```bash
# Test specific endpoint manually
curl http://localhost:8000/health/db

# Test session creation
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "student": {"id": "s1", "grade": 3},
    "goal": {
      "topic": "Fractions",
      "syllabus": "CBSE-G3",
      "learning_objectives": ["Compare fractions"],
      "guideline_id": "g1"
    }
  }'
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
- [ ] All unit tests pass: `pytest -m unit`
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

### Checking Logs

#### Local Development Logs

**Backend Logs:**

```bash
# When running with uvicorn (shows in terminal)
cd llm-backend
uvicorn main:app --reload --log-level debug

# The logs will show:
# - Request/response info
# - LangGraph node execution ([Present], [Check], etc.)
# - Database queries
# - LLM API calls
# - Any errors or exceptions
```

**Frontend Logs:**

```bash
# Browser console (F12 or Cmd+Option+I)
# - Shows React errors
# - API call responses
# - Network tab shows all HTTP requests

# Vite dev server logs (terminal)
cd llm-frontend
npm run dev
# Shows build info and hot reload events
```

**Docker Logs (if running locally):**

```bash
# View logs from running container
docker logs -f llm-backend

# Or if using docker-compose
docker-compose logs -f backend
```

#### Production Logs (AWS)

**Finding the Current Log Group:**

```bash
# 1. Get the service ARN
aws apprunner list-services --region us-east-1

# 2. Extract service ID from ARN (last part after the last /)
# Example: 3681f3cee2884f25842f6b15e9eacbfd

# 3. List log groups
aws logs describe-log-groups \
  --region us-east-1 \
  --log-group-name-prefix "/aws/apprunner" \
  --query 'logGroups[*].logGroupName'
```

**Viewing Application Logs:**

```bash
# Real-time log streaming (last 30 minutes)
aws logs tail /aws/apprunner/llm-backend-prod/YOUR-SERVICE-ID/application \
  --region us-east-1 \
  --since 30m \
  --follow

# Get recent logs (last 1 hour)
aws logs tail /aws/apprunner/llm-backend-prod/YOUR-SERVICE-ID/application \
  --region us-east-1 \
  --since 1h

# Filter logs by pattern
aws logs filter-log-events \
  --log-group-name "/aws/apprunner/llm-backend-prod/YOUR-SERVICE-ID/application" \
  --region us-east-1 \
  --filter-pattern "ERROR" \
  --start-time $(date -v-1H +%s)000  # Last hour (macOS)

# Search for specific session or endpoint
aws logs filter-log-events \
  --log-group-name "/aws/apprunner/llm-backend-prod/YOUR-SERVICE-ID/application" \
  --region us-east-1 \
  --filter-pattern "/sessions" \
  --start-time $(date -v-30M +%s)000
```

**Current Production Service ID:** `3681f3cee2884f25842f6b15e9eacbfd`

**Quick Commands:**

```bash
# View last 50 log entries
aws logs filter-log-events \
  --log-group-name "/aws/apprunner/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd/application" \
  --region us-east-1 \
  --start-time $(($(date +%s) * 1000 - 1800000)) \
  --limit 50 \
  --query 'events[*].message' \
  --output text

# Follow logs in real-time
aws logs tail /aws/apprunner/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd/application \
  --region us-east-1 \
  --follow
```

**Viewing Service Logs (Infrastructure):**

```bash
# Service-level logs (deployments, health checks, etc.)
aws logs tail /aws/apprunner/llm-backend-prod/YOUR-SERVICE-ID/service \
  --region us-east-1 \
  --since 1h
```

**Using CloudWatch Console:**

1. Go to: https://console.aws.amazon.com/cloudwatch/
2. Navigate to: **Logs** → **Log groups**
3. Filter by: `/aws/apprunner/llm-backend-prod`
4. Select the application log group (ends with `/application`)
5. Click "Search log group" to query logs

**Common Log Patterns to Search:**

```bash
# API endpoint calls
/sessions

# Errors
ERROR

# LangGraph execution
[Present]
[Check]
[Remediate]

# Student responses
student_reply

# Database issues
database
psycopg2

# OpenAI API calls
openai
gpt-4o-mini
```

**Frontend Logs (CloudFront/S3):**

```bash
# CloudFront access logs (if enabled)
aws s3 ls s3://your-cloudfront-logs-bucket/

# For debugging frontend issues, use browser DevTools:
# - Console tab: JavaScript errors
# - Network tab: API calls and responses
# - Application tab: Local storage, session data
```

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

**Document Version:** 1.1
**Last Updated:** October 23, 2025 (Updated with refactored architecture and comprehensive testing guide)
**Status:** ✅ Active
