# Repo Map

Last audited: 2026-03-21
Code baseline: `main@e0c0338`

## Product Summary
LearnLikeMagic is an AI tutoring platform with:
- FastAPI backend (`llm-backend`)
- React + TypeScript frontend (`llm-frontend`)
- Playwright E2E stack (`e2e`)
- Terraform infra (`infra/terraform`)
- Functional + technical documentation (`docs`)

## Source Footprint
- Backend Python files: `234`
- Backend Python lines: `46,911`
- Frontend TS/TSX files: `58`
- Frontend TS/TSX lines: `14,057`
- Docs markdown files: `55`
- Backend unit tests: `42`
- Backend integration tests: `5`

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
- `tutor/`: live tutoring (teach_me / clarify_doubts / exam), ws chat, report card
- `book_ingestion_v2/`: book/chapter/page CRUD, OCR, TOC extraction, topic extraction/sync
- `study_plans/`: study plan generation + review orchestration
- `autoresearch/`: autonomous prompt optimization with four sub-domains:
  - `tutor_teaching_quality/`: session simulation + transcript judging + reports
  - `book_ingestion_quality/`: ingestion pipeline evaluation + coverage scoring
  - `explanation_quality/`: explanation card evaluation + report generation
  - `session_experience/`: session experience evaluation + prompt analysis
- `auth/`: Cognito token verification, user sync, profile
- `shared/`: entities/schemas, repositories, LLM abstraction, health/config, feature flags

## Frontend Domain Map
- `src/pages/`: auth (email/phone/OAuth login, signup, verify, forgot-password), onboarding, profile, history, report card, learning flow (subject/chapter/topic select, chat, mode select), enrichment, exam review
- `src/features/admin/`: books (v2), evaluation, docs, model config, feature flags, test scenarios, pixi PoC
- `src/features/devtools/`: agent logs + guidelines + study plan panels via drawer
- `src/contexts/AuthContext.tsx`: Cognito + backend profile sync

## Infra Module Map
`infra/terraform/modules`:
- `database`
- `app-runner`
- `ecr`
- `frontend`
- `secrets`
- `github-oidc`
