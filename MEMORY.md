# MEMORY.md

Curated long-term memory for this workspace.

## Workspace Identity
- Project: LearnLikeMagic
- Stack: FastAPI backend, React/Vite frontend, Playwright E2E, AWS Terraform infra
- Dominant backend pattern: API -> service -> orchestration/agent -> repository

## Stable System Facts
- Tutoring runtime is mode-based (`teach_me`, `clarify_doubts`, `exam`) and persists canonical state in `sessions.state_json`.
- LLM selection is DB-backed via `llm_config` per component (tutor/ingestion/evaluation/study-plan roles).
- Backend production images must be built for `linux/amd64` for App Runner.
- E2E scenarios are data-driven from `e2e/scenarios.json`; backend serves them via `api/test_scenarios.py`.

## Operational Memory
- Internal reference pack lives in `.agent/`; refresh after API/route/architecture shifts.
- Current baseline for references: `claude/update-ai-agent-files-ulEgH@212063c` (audited 2026-02-27).
- Known doc/code drift exists; check `.agent/06-known-drift.md` before trusting docs as source of truth.
