# Change Playbooks

Last audited: 2026-02-26
Code baseline: `main@973d1ea`

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
- API: `book_ingestion/api/routes.py`, `study_plans/api/admin.py`
- Core flow: `book_ingestion/services/*`
- Sync/review behavior: `study_plans/api/admin.py`, DB sync services
- Validate S3 pathing + index writes + review status effects

## Change Evaluation Pipeline
- API: `evaluation/api.py`
- Simulator/session execution: `evaluation/student_simulator.py`, `evaluation/session_runner.py`
- Judge behavior: `evaluation/evaluator.py`
- Report artifacts: `evaluation/report_generator.py`

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
