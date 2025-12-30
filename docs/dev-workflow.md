# Development Workflow

## Setup

### Backend
```bash
cd llm-backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env  # Edit with your credentials
```

### Frontend
```bash
cd llm-frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env
```

### Local Database (Optional)
```bash
docker run -d --name llm-postgres \
  -e POSTGRES_USER=llmuser -e POSTGRES_PASSWORD=password -e POSTGRES_DB=tutor \
  -p 5432:5432 postgres:15-alpine

cd llm-backend
python db.py --migrate
python db.py --seed-guidelines data/seed_guidelines.json
```

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
pytest --cov-report=html  # HTML coverage report → htmlcov/
```

**Markers:** `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`

**Fixtures (conftest.py):** `db_session`, `client`, `sample_student`, `sample_goal`, `sample_tutor_state`, `mock_llm_provider`

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

1. **Schema** (`models/schemas.py`): Define request/response models
2. **Service** (`services/`): Add business logic
3. **Route** (`api/routes/`): Create endpoint
4. **Register** (`main.py`): `app.include_router(new_router)`
5. **Test** (`tests/unit/`): Add unit tests

### Adding Database Models

1. **ORM model** (`models/database.py`): Define table
2. **Repository** (`repositories/`): Add CRUD operations
3. **Migrate**: `python db.py --migrate`

See `docs/backend-architecture.md` for detailed file structure and conventions.

---

## Deployment

**Automatic:** Push to `main` triggers GitHub Actions
- Backend changes (`llm-backend/**`) → ECR → App Runner
- Frontend changes (`llm-frontend/**`) → S3 → CloudFront

**Manual:**
```bash
# Backend
cd llm-backend && make deploy

# Frontend
cd llm-frontend && npm run build
aws s3 sync dist/ s3://learnlikemagic-frontend-production --delete
aws cloudfront create-invalidation --distribution-id E19EYV4ZGTL1L9 --paths "/*"
```

**Verify:**
```bash
curl https://ypwbjbcmbd.us-east-1.awsapprunner.com/
curl https://dlayb9nj2goz.cloudfront.net/
```

See `docs/deployment.md` for full deployment guide.

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
| Build for prod | `make build-prod` (AMD64) |
| Deploy backend | `make deploy` |
| View prod logs | `aws logs tail .../application --follow` |
| Create branch | `git checkout -b feature/name` |
| Push changes | `git push origin feature/name` |
