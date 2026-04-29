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

**Required at runtime** (validated by `entrypoint.sh` + `validate_required_settings()`): `DATABASE_URL`, `OPENAI_API_KEY`.

**Optional `.env` variables:** `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_CLOUD_TTS_API_KEY`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `API_HOST`, `API_PORT`, `LOG_LEVEL`, `LOG_FORMAT`, `ENVIRONMENT`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `COGNITO_REGION`, `AWS_REGION`, `AWS_S3_BUCKET`.

Configuration is managed by `config.py` using pydantic-settings (loads `.env` automatically; case-insensitive; `extra="ignore"`).

### Frontend
```bash
cd llm-frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env
```

### Local Database (Optional)

Either run `postgres:15-alpine` directly or use the repo-root `docker-compose.yml` (which also wires `api` + `frontend` services):

```bash
docker run -d --name llm-postgres \
  -e POSTGRES_USER=llmuser -e POSTGRES_PASSWORD=dev_password -e POSTGRES_DB=tutor \
  -p 5432:5432 postgres:15-alpine

cd llm-backend
source venv/bin/activate
python db.py --migrate   # or: make db-migrate
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

# 3a. (Optional, only for stage-7 visual rendering review)
#     Install Playwright + Chromium for the ingestion pipeline's overlap check.
#     See "Visual Rendering Review (stage 7)" below.
pip install -r requirements.txt
playwright install chromium

# 4. Run frontend (separate terminal)
cd llm-frontend && npm run dev  # http://localhost:3000

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

**Coverage omissions (pytest.ini):** `tests/`, `__pycache__/`, `venv/`, `migrations/`, `scripts/`, `autoresearch/tutor_teaching_quality/evaluation/run_evaluation.py`, `db.py`.

**Coverage omissions (.coveragerc):** Same as above plus `database.py`. The `.coveragerc` file is used by the daily coverage CI workflow and adds `database.py` to the omit list.

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
| `sample_goal` | `Goal` domain object (chapter: Fractions, syllabus: CBSE Grade 3 Mathematics, guideline_id `g1`) |
| `sample_tutor_state` | `TutorState` with sample student + goal |
| `sample_grading_result` | `GradingResult` with score 0.85 |
| `mock_llm_provider` | Mock LLM provider (no real API calls) |

### Frontend

```bash
cd llm-frontend
npm run test            # Run all tests once (Vitest)
npm run test:watch      # Watch mode (re-runs on file change)
```

**Stack:** Vitest + React Testing Library + jsdom. Tests live alongside components.

### E2E Tests (Playwright)

End-to-end tests live in `e2e/` and use Playwright.

```bash
cd e2e
npm install
npx playwright install chromium

# Run tests (requires the app running at http://localhost:3000)
npm test                 # Headless
npm run test:headed      # With browser UI
npm run test:ui          # Interactive Playwright UI
npm run report           # View HTML report
```

**Configuration:** `e2e/playwright.config.ts` — baseURL `http://localhost:3000`, Chromium only, sequential (workers: 1), 60s timeout, 10s expect/action timeout, 1 retry, screenshots on failure, trace on first retry, viewport 1280×720. Reports output to `reports/e2e-runner/` (HTML + JSON + list). Test output dir `reports/e2e-runner/test-output`. Git metadata (branch, commit) is embedded in report metadata.

**Auth setup:** Tests use a `setup` project (`auth.setup.ts`) that stores auth state in `e2e/.auth/user.json`, reused by the `chromium` project. Test credentials are loaded from `e2e/.env` via dotenv.

**Test files:** `tests/auth.setup.ts`, `tests/scenarios.spec.ts`, `tests/check-in-cards.spec.ts`, `tests/practice-v2.spec.ts`, `tests/cross-dag-warning.spec.ts`.

**Scenarios:** `e2e/scenarios.json` defines test scenarios. This file is also copied into the backend Docker image during CI/CD builds (so the deployed backend can serve scenario metadata).

### Manual API Testing
```bash
curl http://localhost:8000/
curl http://localhost:8000/health/db
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"student":{"id":"s1","grade":3},"goal":{"chapter":"Fractions","syllabus":"CBSE Grade 3 Math","learning_objectives":["Compare fractions"],"guideline_id":"g1"}}'
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

1. **ORM model** (`shared/models/entities.py` for core; `book_ingestion_v2/models/database.py` for V2 pipeline)
2. **Repository** (`repositories/`): Add CRUD operations
3. **Migrate**: `python db.py --migrate` (or `make db-migrate`)

`Base.metadata.create_all()` handles new tables. For new columns on existing tables, add an `ALTER TABLE` migration helper in `db.py` with a column-existence check via `inspect()`, register it in `migrate()`, and document it in `docs/technical/database.md`. See `_apply_learning_modes_columns()` for the pattern, and `_ensure_llm_config()` for the seed-if-missing helper.

See `docs/technical/architecture-overview.md` for detailed file structure and conventions.

---

## Visual Rendering Review (stage 7)

Stage 7 of the book ingestion pipeline runs a programmatic overlap check on generated pixi visuals. The check uses Playwright + headless Chromium to render the pixi code against the live frontend's admin preview page, then walks the Pixi display tree to compute bounding-box overlaps.

**Local prerequisites (admin-only, needed when running stage-7 jobs):**

```bash
# 1. Install the Python library (already in requirements.txt)
cd llm-backend && source venv/bin/activate
pip install -r requirements.txt

# 2. Install the Chromium driver that Playwright controls
playwright install chromium

# 3. Make sure the frontend dev server is running (stage-7 navigates to
#    http://localhost:3000/admin/visual-render-preview/{id})
cd llm-frontend && npm run dev
```

If the frontend isn't running when you trigger stage 7, the job fails fast with a clear error message (`VisualRenderHarness.preflight()`) rather than silently passing cards through an unrunning overlap check.

**Skipping the dependency:** Developers who don't touch the ingestion pipeline can safely skip the Playwright install — the render harness returns `ok=False, error="playwright not installed"` when the library is missing, and every other part of the codebase runs fine without it.

**Runtime expectations:** every enriched visual card costs one Playwright render; cards that trigger the overlap gate cost a second render after the targeted refine. A 20-card chapter where half overlap is therefore ~30 renders × a few seconds of Chromium cold-boot each — a few minutes of pure harness time *in addition to* the LLM work. Jobs that look stalled during stage 7 are usually mid-render, not hung.

---

## Deployment

**Automatic:** Push to `main` triggers GitHub Actions
- Backend changes (`llm-backend/**`, `docs/**`, or `e2e/scenarios.json`) --> ECR --> App Runner
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
| Run backend tests | `pytest` |
| Run frontend tests | `cd llm-frontend && npm run test` |
| Run E2E tests | `cd e2e && npm test` |
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
| `llm-backend/.coveragerc` | Coverage configuration used by daily CI workflow (adds `database.py` to omissions) |
| `llm-backend/tests/conftest.py` | Shared test fixtures |
| `llm-backend/db.py` | Database migration CLI + helpers |
| `llm-backend/database.py` | DatabaseManager, connection pooling |
| `docker-compose.yml` (repo root) | Local Postgres + api + frontend services |
| `e2e/playwright.config.ts` | E2E test configuration (Playwright) |
| `e2e/scenarios.json` | E2E test scenarios (also bundled into backend Docker image) |
