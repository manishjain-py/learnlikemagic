# File Indexes

Last audited: 2026-03-21
Code baseline: `main@e0c0338`

## Backend High-Signal Files
- App bootstrap: `llm-backend/main.py`
- Settings: `llm-backend/config.py`
- DB manager: `llm-backend/database.py`
- Migration script: `llm-backend/db.py`
- Session APIs: `llm-backend/tutor/api/sessions.py`
- Curriculum API: `llm-backend/tutor/api/curriculum.py`
- Transcription API: `llm-backend/tutor/api/transcription.py`
- TTS API: `llm-backend/tutor/api/tts.py`
- Session service: `llm-backend/tutor/services/session_service.py`
- Orchestrator: `llm-backend/tutor/orchestration/orchestrator.py`
- Master tutor agent: `llm-backend/tutor/agents/master_tutor.py`
- Session state model: `llm-backend/tutor/models/session_state.py`
- Report card aggregation: `llm-backend/tutor/services/report_card_service.py`
- Ingestion book routes: `llm-backend/book_ingestion_v2/api/book_routes.py`
- Ingestion processing routes: `llm-backend/book_ingestion_v2/api/processing_routes.py`
- Topic extraction orchestrator: `llm-backend/book_ingestion_v2/services/topic_extraction_orchestrator.py`
- Study plan orchestrator: `llm-backend/study_plans/services/orchestrator.py`
- Tutor evaluation APIs: `llm-backend/autoresearch/tutor_teaching_quality/evaluation/api.py`
- Tutor evaluation runner: `llm-backend/autoresearch/tutor_teaching_quality/evaluation/session_runner.py`
- Tutor evaluation judge: `llm-backend/autoresearch/tutor_teaching_quality/evaluation/evaluator.py`
- Book ingestion evaluator: `llm-backend/autoresearch/book_ingestion_quality/evaluation/evaluator.py`
- Book ingestion pipeline runner: `llm-backend/autoresearch/book_ingestion_quality/evaluation/pipeline_runner.py`
- Explanation quality evaluator: `llm-backend/autoresearch/explanation_quality/evaluation/evaluator.py`
- Explanation quality experiment: `llm-backend/autoresearch/explanation_quality/run_experiment.py`
- Session experience evaluator: `llm-backend/autoresearch/session_experience/evaluation/experience_evaluator.py`
- Session experience runner: `llm-backend/autoresearch/session_experience/evaluation/session_runner.py`
- Session experience experiment: `llm-backend/autoresearch/session_experience/run_experiment.py`
- Auth routes: `llm-backend/auth/api/auth_routes.py`
- Enrichment routes: `llm-backend/auth/api/enrichment_routes.py`
- Profile routes: `llm-backend/auth/api/profile_routes.py`
- Auth middleware: `llm-backend/auth/middleware/auth_middleware.py`
- Shared entities: `llm-backend/shared/models/entities.py`
- LLM abstraction: `llm-backend/shared/services/llm_service.py`
- LLM config service: `llm-backend/shared/services/llm_config_service.py`
- Health API: `llm-backend/shared/api/health.py`
- Feature flag routes: `llm-backend/shared/api/feature_flag_routes.py`
- Feature flag service: `llm-backend/shared/services/feature_flag_service.py`
- LLM config routes: `llm-backend/shared/api/llm_config_routes.py`
- Docs API: `llm-backend/api/docs.py`
- Pixi PoC API: `llm-backend/api/pixi_poc.py`
- Pixi code generator: `llm-backend/tutor/services/pixi_code_generator.py`
- Test-scenarios API: `llm-backend/api/test_scenarios.py`

## Frontend High-Signal Files
- Route table: `llm-frontend/src/App.tsx`
- Auth session orchestration: `llm-frontend/src/contexts/AuthContext.tsx`
- Student API client: `llm-frontend/src/api.ts`
- Auth config: `llm-frontend/src/config/auth.ts`
- Learning pages: `llm-frontend/src/pages/*`
- Admin pages: `llm-frontend/src/features/admin/pages/*`
- Visual explanation component: `llm-frontend/src/components/VisualExplanation.tsx`
- Admin API client: `llm-frontend/src/features/admin/api/adminApi.ts`
- Devtools API client: `llm-frontend/src/features/devtools/api/devToolsApi.ts`

## E2E + QA High-Signal Files
- Playwright config: `e2e/playwright.config.ts`
- Dynamic test runner: `e2e/tests/scenarios.spec.ts`
- Scenario definitions: `e2e/scenarios.json`

## Infra + CI High-Signal Files
- Terraform root: `infra/terraform/main.tf`
- Terraform docs: `infra/terraform/README.md`
- Backend Makefile: `llm-backend/Makefile`
- Workflows: `.github/workflows/*.yml`
