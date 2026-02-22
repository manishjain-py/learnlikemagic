# Development Workflow

Local setup, daily workflow, testing, and making changes.

---

## Setup

### Backend
```bash
cd llm-backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env  # Edit with your credentials
```

**Required `.env` variables:** `OPENAI_API_KEY`, `DATABASE_URL`

**Optional `.env` variables:** `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `LOG_LEVEL`, `LOG_FORMAT`, `ENVIRONMENT`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `COGNITO_REGION`, `AWS_REGION`, `AWS_S3_BUCKET`

Configuration is managed by `config.py` using pydantic-settings, which loads from the `.env` file automatically.

### Frontend
```bash
cd llm-frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env
```

### Local Database (Optional)
```bash
docker run -d --name llm-postgres \
  -e POSTGRES_USER=llmuser -e POSTGRES_PASSWORD=dev_password -e POSTGRES_DB=tutor \
  -p 5432:5432 postgres:15-alpine

cd llm-backend
source venv/bin/activate
python db.py --migrate
```

The default `DATABASE_URL` in `.env.example` is `postgresql://llmuser:dev_password@localhost:5432/tutor`, matching the Docker container above.

---

## Daily Workflow

```bash
# 1. Pull latest
git checkout main && git pull

# 2. Create branch
git checkout -b feature/your-feature

# 3. Run backend
cd llm-backend && source venv/bin/activate
make run  # http://localhost:8000, docs at /docs

# 4. Run frontend (separate terminal)
cd llm-frontend && npm run dev  # http://localhost:5173

# 5. Make changes, test locally

# 6. Commit & push
git add . && git commit -m "Add feature: description"
git push origin feature/your-feature

# 7. Create PR on GitHub, merge after review

# 8. Auto-deploys on merge to main
```

---

## Testing

### Backend
```bash
cd llm-backend
source venv/bin/activate
export OPENAI_API_KEY=sk-test-dummy  # Required for imports

pytest                    # All tests with coverage
pytest -m unit            # Fast unit tests only
pytest -m integration     # Integration tests
pytest -v -k "test_name"  # Specific test
pytest --cov-report=html  # HTML coverage report -> htmlcov/
```

**pytest.ini defaults:** Coverage is enabled by default (`--cov=.`, `--cov-report=term-missing`, `--cov-report=html`), strict markers, short tracebacks, warnings disabled.

**Markers:**

| Marker | Purpose |
|--------|---------|
| `@pytest.mark.unit` | Fast unit tests, no external dependencies |
| `@pytest.mark.integration` | Integration tests using production resources |
| `@pytest.mark.slow` | Tests taking >5 seconds (e.g., LLM calls) |
| `@pytest.mark.smoke` | Quick smoke tests for deployment verification |
| `@pytest.mark.critical` | Critical path tests that must pass |
| `@pytest.mark.s3` | Tests requiring S3 access |
| `@pytest.mark.db` | Tests requiring database access |
| `@pytest.mark.llm` | Tests requiring LLM API calls |
| `@pytest.mark.phase6` | Tests for Phase 6 guideline extraction |

**Fixtures (conftest.py):**

| Fixture | Description |
|---------|-------------|
| `db_session` | In-memory SQLite session, fresh per test function |
| `client` | FastAPI `TestClient` |
| `sample_student` | `Student` domain object (grade 3, standard style, English) |
| `sample_goal` | `Goal` domain object (Fractions, CBSE Grade 3) |
| `sample_tutor_state` | `TutorState` with sample student + goal |
| `sample_grading_result` | `GradingResult` with score 0.85 |
| `mock_llm_provider` | Mock LLM provider (no real API calls) |

### Frontend
```bash
cd llm-frontend
npm test          # Unit tests
npm run lint      # Linting
npm run type-check
```

### Manual API Testing
```bash
curl http://localhost:8000/
curl http://localhost:8000/health/db
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"student":{"id":"s1","grade":3},"goal":{"topic":"Fractions","guideline_id":"g1"}}'
```

---

## Making Changes

### Adding an API Endpoint

1. **Schema** (`models/`): Define request/response models
2. **Service** (`services/`): Add business logic
3. **Route** (`api/`): Create endpoint
4. **Register** (`main.py`): `app.include_router(new_router)`
5. **Test** (`tests/unit/`): Add unit tests

### Adding Database Models

1. **ORM model** (`shared/models/entities.py` or `book_ingestion/models/database.py`): Define table
2. **Repository** (`repositories/`): Add CRUD operations
3. **Migrate**: `python db.py --migrate` (or `make db-migrate`)

If adding columns to an existing table, you must also add an `ALTER TABLE` migration in `db.py` with a column existence check. See `_apply_learning_modes_columns()` for the pattern.

See `docs/technical/architecture-overview.md` for detailed file structure and conventions.

---

## Deployment

**Automatic:** Push to `main` triggers GitHub Actions
- Backend changes (`llm-backend/**` or `docs/**`) --> ECR --> App Runner
- Frontend changes (`llm-frontend/**`) --> S3 --> CloudFront

**Manual:**
```bash
# Backend
cd llm-backend && make deploy

# Frontend
cd llm-frontend && npm run build
aws s3 sync dist/ s3://learnlikemagic-frontend-production --delete
aws cloudfront create-invalidation --distribution-id E19EYV4ZGTL1L9 --paths "/*"
```

See `docs/technical/deployment.md` for the full deployment guide.

---

## Logs

### Local
- Backend: Terminal output from `make run`
- Frontend: Browser DevTools console

### Production
```bash
# Application logs
aws logs tail /aws/apprunner/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd/application \
  --region us-east-1 --follow

# Service logs
aws logs tail /aws/apprunner/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd/service \
  --region us-east-1 --follow
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Run backend | `cd llm-backend && make run` |
| Run frontend | `cd llm-frontend && npm run dev` |
| Run tests | `pytest` / `npm test` |
| Run in Docker locally | `make build-local && make run-docker` |
| Check architecture | `make check-arch` |
| Run migrations | `make db-migrate` |
| Build for prod | `make build-prod` (AMD64) |
| Deploy backend | `make deploy` |
| Clean build artifacts | `make clean` |
| View prod logs | `aws logs tail .../application --follow` |
| Create branch | `git checkout -b feature/name` |
| Push changes | `git push origin feature/name` |

---

## Key Files

| File | Purpose |
|------|---------|
| `llm-backend/Makefile` | All backend build/run/deploy commands |
| `llm-backend/config.py` | Settings loaded from `.env` via pydantic-settings |
| `llm-backend/.env.example` | Template for local environment variables |
| `llm-backend/Dockerfile` | Container definition (python:3.11-slim + entrypoint.sh) |
| `llm-backend/entrypoint.sh` | Container startup: env var checks then uvicorn |
| `llm-backend/pytest.ini` | Pytest configuration, markers, coverage settings |
| `llm-backend/tests/conftest.py` | Shared test fixtures |
| `llm-backend/db.py` | Database migration CLI |
| `llm-backend/database.py` | DatabaseManager, connection pooling |
