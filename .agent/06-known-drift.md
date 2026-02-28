# Known Drift And Risks

Last audited: 2026-02-27
Code baseline: `claude/update-ai-agent-files-ulEgH@212063c`

## Verified Drift
1. `llm-frontend/README.md` is stale.
- Describes older architecture and scripts (`npm run lint`, `npm run type-check`) not present in current `llm-frontend/package.json`.
- Architecture tree only shows original files (`App.tsx`, `api.ts`, `main.tsx`); actual src has pages/, features/, contexts/, components/.
- "Automated Testing (Future)" section is outdated: vitest and @testing-library are installed and `npm run test` works.
- Port `localhost:3000` is correct (vite.config.ts overrides default 5173).

2. ~~Scorecard docs and API docs are inconsistent with runtime routes.~~ **RESOLVED.**
- Technical docs (`scorecard.md`, `architecture-overview.md`) now consistently use `GET /sessions/report-card`.
- Only archive/historical docs (`docs/archive/`) still reference old `GET /sessions/scorecard`, which is expected.

3. Legacy model/repository overlap remains.
- `shared/models/domain.py` has legacy `TutorState` model.
- `shared/repositories/session_repository.py` `create/update` signatures still use `TutorState`, while runtime tutoring path uses `tutor/models/session_state.py` and service-layer persistence.

4. Teaching guideline ORM indicates unresolved migration cleanup.
- `shared/models/entities.py` contains V1/V2 transition comments and fields simultaneously.

5. Startup script message can mislead on model selection.
- `entrypoint.sh` logs `LLM_MODEL`, but operational selection is DB-driven via `llm_config`.

6. Explicit TODO in ingestion cleanup path.
- `book_ingestion/api/routes.py` notes missing `s3_client.delete_prefix()` implementation.

## Operational Risks
1. Admin frontend routes are not protected by auth guard in route config.
2. Some session APIs allow anonymous access for backward compatibility (`get_optional_user`).
3. Ingestion/evaluation pipelines include background and external dependency steps (S3/LLM), so partial-failure handling is important.
4. Repo has many generated/untracked artifacts; source-of-truth review should stay scoped.

## Cleanup Backlog
1. Refresh `llm-frontend/README.md` to current architecture/scripts/routes.
2. ~~Reconcile scorecard/report-card technical docs with actual route set.~~ **Done.**
3. Decide whether to retire or modernize legacy `TutorState` paths in repository layer.
4. Finalize teaching guideline schema migration state in code + docs.
