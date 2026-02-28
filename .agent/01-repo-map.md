# Repo Map

Last audited: 2026-02-27
Code baseline: `claude/update-ai-agent-files-ulEgH@212063c`

## Product Summary
LearnLikeMagic is an AI tutoring platform with:
- FastAPI backend (`llm-backend`)
- React + TypeScript frontend (`llm-frontend`)
- Playwright E2E stack (`e2e`)
- Terraform infra (`infra/terraform`)
- Functional + technical documentation (`docs`)

## Source Footprint
- Backend Python files: `202`
- Backend Python lines: `46,974`
- Frontend TS/TSX files: `54`
- Frontend TS/TSX lines: `12,218`
- Docs markdown files: `32`
- Backend unit tests: `50`
- Backend integration tests: `8`

## Top-Level Ownership
- `llm-backend/`: tutoring runtime, auth, ingestion, evaluation, shared infra
- `llm-frontend/`: student and admin web app
- `e2e/`: scenario definitions + dynamic Playwright runner
- `infra/terraform/`: AWS infrastructure modules
- `docs/`: project documentation
- `scripts/`: deployment/support scripts

## Runtime Entrypoints
- Backend app: `llm-backend/main.py`
- Backend config: `llm-backend/config.py`
- Backend migration CLI: `llm-backend/db.py`
- Frontend route tree: `llm-frontend/src/App.tsx`
- Frontend API client: `llm-frontend/src/api.ts`
- E2E config: `e2e/playwright.config.ts`
- E2E scenario source: `e2e/scenarios.json`

## Backend Domain Map
- `tutor/`: live tutoring (teach_me / clarify_doubts / exam), ws chat, scorecard
- `book_ingestion/`: book/page CRUD, OCR, guideline extraction/finalization
- `study_plans/`: guideline review + study plan generation
- `evaluation/`: session simulation + transcript judging + reports
- `auth/`: Cognito token verification, user sync, profile
- `shared/`: entities/schemas, repositories, LLM abstraction, health/config

## Frontend Domain Map
- `src/pages/`: auth, onboarding, profile, history, scorecard, learning flow
- `src/features/admin/`: books, guidelines, evaluation, docs, model config, test scenarios
- `src/features/devtools/`: agent logs, guidelines + study plan inspector
- `src/contexts/AuthContext.tsx`: Cognito + backend profile sync

## Infra Module Map
`infra/terraform/modules`:
- `database`
- `app-runner`
- `ecr`
- `frontend`
- `secrets`
- `github-oidc`
