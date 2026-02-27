# File Indexes

Last audited: 2026-02-26
Code baseline: `main@973d1ea`

## Backend High-Signal Files
- App bootstrap: `llm-backend/main.py`
- Settings: `llm-backend/config.py`
- DB manager: `llm-backend/database.py`
- Migration script: `llm-backend/db.py`
- Session APIs: `llm-backend/tutor/api/sessions.py`
- Curriculum API: `llm-backend/tutor/api/curriculum.py`
- Transcription API: `llm-backend/tutor/api/transcription.py`
- Session service: `llm-backend/tutor/services/session_service.py`
- Orchestrator: `llm-backend/tutor/orchestration/orchestrator.py`
- Master tutor agent: `llm-backend/tutor/agents/master_tutor.py`
- Session state model: `llm-backend/tutor/models/session_state.py`
- Scorecard aggregation: `llm-backend/tutor/services/scorecard_service.py`
- Ingestion routes: `llm-backend/book_ingestion/api/routes.py`
- Ingestion orchestrator: `llm-backend/book_ingestion/services/guideline_extraction_orchestrator.py`
- Study plan admin APIs: `llm-backend/study_plans/api/admin.py`
- Evaluation APIs: `llm-backend/evaluation/api.py`
- Evaluation runner: `llm-backend/evaluation/session_runner.py`
- Evaluation judge: `llm-backend/evaluation/evaluator.py`
- Auth routes: `llm-backend/auth/api/auth_routes.py`
- Profile routes: `llm-backend/auth/api/profile_routes.py`
- Auth middleware: `llm-backend/auth/middleware/auth_middleware.py`
- Shared entities: `llm-backend/shared/models/entities.py`
- LLM abstraction: `llm-backend/shared/services/llm_service.py`
- LLM config service: `llm-backend/shared/services/llm_config_service.py`
- Health API: `llm-backend/shared/api/health.py`
- Docs API: `llm-backend/api/docs.py`
- Test-scenarios API: `llm-backend/api/test_scenarios.py`

## Frontend High-Signal Files
- Route table: `llm-frontend/src/App.tsx`
- Auth session orchestration: `llm-frontend/src/contexts/AuthContext.tsx`
- Student API client: `llm-frontend/src/api.ts`
- Auth config: `llm-frontend/src/config/auth.ts`
- Learning pages: `llm-frontend/src/pages/*`
- Admin pages: `llm-frontend/src/features/admin/pages/*`
- Admin API client: `llm-frontend/src/features/admin/api/adminApi.ts`
- Devtools API client: `llm-frontend/src/features/devtools/api/devToolsApi.ts`

## E2E + QA High-Signal Files
- Playwright config: `e2e/playwright.config.ts`
- Dynamic test runner: `e2e/tests/scenarios.spec.ts`
- Scenario definitions: `e2e/scenarios.json`
- Report builder: `reports/e2e-runner/build_report.py`

## Infra + CI High-Signal Files
- Terraform root: `infra/terraform/main.tf`
- Terraform docs: `infra/terraform/README.md`
- Backend Makefile: `llm-backend/Makefile`
- Workflows: `.github/workflows/*.yml`
