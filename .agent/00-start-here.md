# Agent Start Here

Last audited: 2026-02-26
Code baseline: `main@973d1ea`

This folder is the internal operator manual for fast, reliable work in this repo.

## Session Boot Order
1. `AGENTS.md`
2. `SOUL.md`
3. `USER.md`
4. `memory/YYYY-MM-DD.md` (today + yesterday)
5. `MEMORY.md` (main session only)
6. `.agent/01-repo-map.md`
7. `.agent/02-backend-api-and-flow.md`
8. `.agent/03-frontend-map.md`
9. `.agent/04-ops-and-testing.md`
10. `.agent/06-known-drift.md`

## Reference Pack Contents
- `01-repo-map.md`: layout, module ownership, entrypoints, source footprint
- `02-backend-api-and-flow.md`: full backend endpoint + runtime flow map
- `03-frontend-map.md`: route/auth/admin/devtools map
- `04-ops-and-testing.md`: runbook for local/dev/test/deploy/CI
- `05-change-playbooks.md`: concrete file touchpoints per change type
- `06-known-drift.md`: verified doc/code drift and operational risks
- `07-file-indexes.md`: high-signal file index for fast navigation

## Scope Guardrails
Treat these as generated/dependency artifacts unless task specifically targets them:
- `**/venv/**`
- `**/node_modules/**`
- `**/dist/**`
- `**/htmlcov/**`
- `reports/**`
- `.coverage`, `.pytest_cache`
