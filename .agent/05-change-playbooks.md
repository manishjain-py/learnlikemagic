# Change Playbooks

Last audited: 2026-03-15
Code baseline: `main@3814fb5`

## Add Or Change Backend Endpoint
1. Schema/model update (`shared/models/schemas.py` or module-specific model)
2. Service logic in module `services/`
3. Route in module `api/`
4. Router registration check in `main.py` (if new router)
5. Unit tests in `tests/unit/`
6. Integration tests in `tests/integration/` where behavior crosses module boundaries

## Change Tutoring Behavior
Touchpoints:
- Prompt behavior: `tutor/prompts/*`
- State transitions and flow: `tutor/orchestration/orchestrator.py`
- Session lifecycle: `tutor/services/session_service.py`
- Output/state schemas: `tutor/agents/master_tutor.py`, `tutor/models/session_state.py`

Validation:
- Verify all modes: `teach_me`, `clarify_doubts`, `exam`
- Re-run tutor-centric tests (`test_orchestrator.py`, `test_session_service.py`, `test_learning_modes.py`, etc.)

## Change Auth Flow
- Frontend: `contexts/AuthContext.tsx`, auth pages
- Backend: `auth/api/*`, `auth/services/*`, `auth/middleware/auth_middleware.py`
- Preserve token contract: ID token for `/auth/sync`, access token for protected APIs

## Change Ingestion Or Guideline Pipeline
- API: `book_ingestion_v2/api/book_routes.py`, `book_ingestion_v2/api/toc_routes.py`, `book_ingestion_v2/api/page_routes.py`, `book_ingestion_v2/api/processing_routes.py`, `book_ingestion_v2/api/sync_routes.py`
- Core flow: `book_ingestion_v2/services/*`
- Sync/review behavior: `book_ingestion_v2/api/sync_routes.py`, DB sync services
- Validate S3 pathing + index writes + review status effects

## Change Tutor Evaluation Pipeline
- API: `autoresearch/tutor_teaching_quality/evaluation/api.py`
- Simulator/session execution: `autoresearch/tutor_teaching_quality/evaluation/student_simulator.py`, `autoresearch/tutor_teaching_quality/evaluation/session_runner.py`
- Judge behavior: `autoresearch/tutor_teaching_quality/evaluation/evaluator.py`
- Report artifacts: `autoresearch/tutor_teaching_quality/evaluation/report_generator.py`
- Experiment runner: `autoresearch/tutor_teaching_quality/run_experiment.py`

## Change Book Ingestion Evaluation Pipeline
- Evaluator: `autoresearch/book_ingestion_quality/evaluation/evaluator.py`
- Pipeline runner: `autoresearch/book_ingestion_quality/evaluation/pipeline_runner.py`
- Report artifacts: `autoresearch/book_ingestion_quality/evaluation/report_generator.py`
- Experiment runner: `autoresearch/book_ingestion_quality/run_experiment.py`

## Change Frontend Route Or User Flow
- Route table: `src/App.tsx`
- UI page/component under `src/pages/` or `src/features/admin/pages/`
- Keep `e2e/scenarios.json` aligned with route/test-id changes
- Re-run impacted E2E scenarios

## Change Deploy Or Infra
- Terraform module + root wiring under `infra/terraform/`
- Workflow alignment under `.github/workflows/`
- Preserve amd64 backend image build for App Runner

## Documentation Sync Rule
For behavior or API changes, update:
- Functional docs (`docs/functional/*`)
- Technical docs (`docs/technical/*`)
