# Repo Map

Last audited: 2026-03-14
Code baseline: `claude/update-agent-docs-6CPuT@d2e797a`

## Product Summary
LearnLikeMagic is an AI tutoring platform with:
- FastAPI backend (`llm-backend`)
- React + TypeScript frontend (`llm-frontend`)
- Playwright E2E stack (`e2e`)
- Terraform infra (`infra/terraform`)
- Functional + technical documentation (`docs`)

## Source Footprint
- Backend Python files: `195`
- Backend Python lines: `36,009`
- Frontend TS/TSX files: `54`
- Frontend TS/TSX lines: `12,858`
- Docs markdown files: `37`
- Backend unit tests: `38`
- Backend integration tests: `7`

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
- `evaluation/`: session simulation + transcript judging + reports
- `auth/`: Cognito token verification, user sync, profile
- `shared/`: entities/schemas, repositories, LLM abstraction, health/config

## Frontend Domain Map
- `src/pages/`: auth, onboarding, profile, history, report card, learning flow, enrichment, exam review
- `src/features/admin/`: books (v2), evaluation, docs, model config, test scenarios, pixi PoC
- `src/features/devtools/`: session state + agent logs + guidelines + study plan views
- `src/contexts/AuthContext.tsx`: Cognito + backend profile sync

## Infra Module Map
`infra/terraform/modules`:
- `database`
- `app-runner`
- `ecr`
- `frontend`
- `secrets`
- `github-oidc`
