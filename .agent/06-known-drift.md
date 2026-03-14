# Known Drift And Risks

Last audited: 2026-03-14
Code baseline: `claude/update-agent-docs-6CPuT@d2e797a`

## Verified Drift
1. `llm-frontend/README.md` is stale.
- Describes older architecture and scripts (`npm run lint`, `npm run type-check`) not present in current `llm-frontend/package.json`.
- Port claim (`localhost:3000`) is now correct (Vite config overrides to 3000), but architecture/script references remain stale.

2. ~~Scorecard docs and API docs are inconsistent with runtime routes.~~ **Resolved.**
- `docs/technical/scorecard.md` now correctly references `GET /sessions/report-card`.
- Only remaining `scorecard` mentions are in the migration implementation plan, which is historical/intentional.

3. Legacy model/repository overlap remains.
- `shared/models/domain.py` has legacy `TutorState` model.
- `shared/repositories/session_repository.py` `create/update` signatures still use `TutorState`, while runtime tutoring path uses `tutor/models/session_state.py` and service-layer persistence.

4. Teaching guideline ORM retains legacy fields alongside V2 pipeline.
- `shared/models/entities.py` has a "Legacy fields still used by V2 pipeline" comment on `TeachingGuideline`, indicating the fields are intentionally kept but the cleanup state is ambiguous.

5. Startup script message can mislead on model selection.
- `entrypoint.sh` logs `LLM_MODEL`, but operational selection is DB-driven via `llm_config`.

6. ~~Explicit TODO in ingestion cleanup path.~~ **Resolved.**
- Old `book_ingestion/` directory no longer exists; replaced by `book_ingestion_v2/`. The `delete_prefix` TODO is not present in V2 code.

## Operational Risks
1. Admin frontend routes are not protected by auth guard in route config.
2. Some session APIs allow anonymous access for backward compatibility (`get_optional_user`).
3. Ingestion/evaluation pipelines include background and external dependency steps (S3/LLM), so partial-failure handling is important.
4. Repo has many generated/untracked artifacts; source-of-truth review should stay scoped.

## Cleanup Backlog
1. Refresh `llm-frontend/README.md` to current architecture/scripts/routes.
2. ~~Reconcile scorecard/report-card technical docs with actual route set.~~ Done — docs now use `report-card`.
3. Decide whether to retire or modernize legacy `TutorState` paths in repository layer.
4. Clarify whether teaching guideline legacy fields (`teaching_description`, `description`) can be dropped or are still needed by V2 pipeline.
