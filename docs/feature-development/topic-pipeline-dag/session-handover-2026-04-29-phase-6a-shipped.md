# Session Handover — 2026-04-29 (Phase 6a shipped)

This is the handover from the implementation session that shipped Phase 6a — the cross-DAG warning backend (hash store, capture, endpoint, integration tests). Pairs with the prior handovers in this directory:
- `session-handover-2026-04-28-phase-1-shipped.md`
- `session-handover-2026-04-28-phase-2-shipped.md`
- `session-handover-2026-04-28-phase-3-shipped.md`
- `session-handover-2026-04-28-phase-3-5-and-4-shipped.md`
- `session-handover-2026-04-29-phase-5-shipped.md`

## TL;DR

Phase 6a is shipped, **squash-merged to main as commit `3158574`** (PR #132). Phases 1+2+3+3.5+4+5+6a of the DAG plan are now done. Next is Phase 6b — frontend banner + E2E + docs polish. Branch `feat/topic-pipeline-dag-phase-6b` already created from main this session.

## What shipped this session

**PR:** https://github.com/manishjain-py/learnlikemagic/pull/132
**Squash commit:** `3158574` on main
**Branch:** `feat/topic-pipeline-dag-phase-6` (deleted on merge)
**Diff:** ~1525 insertions / ~5 deletions across two pre-merge commits — initial `f8f2d6a` (the broken-by-design v1 implementation) + `66136a0` (the rework that addresses reviewer P0/P1/P2 and is what actually shipped).

### Final architecture

The cross-DAG warning detects upstream-DAG events that may have invalidated the cached `explanations` artefacts, surfacing a `chapter_resynced` banner on `TopicDAGView`. Backend ships in 6a; the banner UI lands in 6b.

**Hash store — `topic_content_hashes` table** (`book_ingestion_v2/models/database.py`).
- Composite PK: `(book_id, chapter_key, topic_key)` — the **stable curriculum tuple** that survives `topic_sync`'s delete-recreate of `teaching_guidelines` rows.
- Columns: `explanations_input_hash VARCHAR(64)`, `last_explanations_at DATETIME`, `updated_at DATETIME`.
- No FK to `teaching_guidelines` by design: the row outlives the guideline.

**Hash function** (`book_ingestion_v2/dag/cross_dag_warnings.py`).
- SHA-256 hex over `\x1f`-joined `(effective_guideline_text, prior_topics_context, effective_topic_title)`.
- `effective_guideline_text = guideline.guideline OR guideline.description OR ""` — mirrors `explanation_generator_service.py:299/373`.
- `effective_topic_title = guideline.topic_title OR guideline.topic OR ""` — mirrors `explanation_generator_service.py:161/230/etc`.
- NULL coerced to `""`; `\x1f` separator avoids field-boundary collisions.

**Capture** (terminal hook in `processing_routes.py`).
- Fires inside `_write_topic_stage_run_terminal` when `stage_id == "explanations"` and `terminal_state == "done"`.
- Resolves the guideline → stable tuple → upserts the hash row. Passes the stage's `completed_at` so `last_explanations_at` aligns with `topic_stage_runs.completed_at`.
- Wrapped in its own try/except so a hash-write hiccup never breaks the durable terminal write.

**Endpoint** — `GET /admin/v2/topics/{guideline_id}/cross-dag-warnings` (`book_ingestion_v2/api/dag_routes.py`).
- 404 on unknown guideline.
- Empty `{warnings: []}` when the stable tuple is incomplete (legacy rows missing chapter_key/topic_key) OR no hash has been captured yet OR the live hash matches stored.
- `chapter_resynced` warning when stored ≠ live, with `last_explanations_at` from the hash row.

### Pre-merge story (worth remembering — informs Phase 7)

Initial commit `f8f2d6a` keyed the hash on a new column `teaching_guidelines.explanations_input_hash`. Reviewer P0 caught that this would silently fail on every `topic_sync` resync because:
- `topic_sync_service._delete_chapter_guidelines` (line 167-174) deletes by `(book_id, chapter_key)`.
- `_sync_topic` (line 124-165) re-creates with `id=str(uuid.uuid4())`.
- `topic_stage_runs.guideline_id FK` is `ondelete="CASCADE"` (`models/database.py:294`), so the per-stage history dies too.
- Result: post-resync, the new guideline's column is NULL, the endpoint hits the "if not stored: return empty" branch, no banner.

The integration test in `f8f2d6a` simulated `topic_sync` as `guideline.guideline = "rewritten"` — an **in-place edit**, not the actual delete-recreate. Gave false confidence.

Rework commit `66136a0` replaced the column with the side table keyed on the stable tuple, fixed P1 (fallback fields) + P2 (`last_explanations_at` semantics), and rewrote the integration test to actually `DELETE` the guideline + insert a fresh uuid. Migration on prod dropped the dead column + created the new table.

**Lesson for Phase 7's chapter DAG.** Anything you key on `guideline_id` dies on every chapter resync. Anchor durable per-topic state on `(book_id, chapter_key, topic_key)` (or whatever curriculum-stable tuple the chapter scope uses).

### Reviewer findings (all addressed pre-merge)

| Finding | Where it landed |
|---|---|
| **P0** — banner silent on `topic_sync` (whole point of the PR) | New `topic_content_hashes` table; `66136a0` |
| **P1** — hash misses `description`/`topic` fallback fields | `compute_input_hash_for_guideline` chains both fields; `66136a0` |
| **P2** — `last_explanations_at` wrong during rerun + after failure | Lives on the hash row, written only on `done`; `66136a0` |
| **Misleading test** | Integration test rewritten to actually exercise delete-recreate; `66136a0` |

## Prod migration applied this session

`python db.py --migrate` was run twice against prod RDS:

1. After the initial commit: added `teaching_guidelines.explanations_input_hash VARCHAR(64)`. Idempotent CREATE; column was never populated beyond the smoke test (which I reset to NULL).
2. After the rework: idempotent `DROP COLUMN explanations_input_hash` + `CREATE TABLE topic_content_hashes`. Verified post-run via `inspect()`.

The dropped column never carried real production data — its only writes were the brief smoke test that I cleaned up before merge.

## Test results

- Unit + integration: **166 passing** across `tests/unit/test_cross_dag_warnings.py` (34, was 21 in v1), `test_cascade_orchestrator.py` (45), `test_topic_pipeline_dag.py` (20), `test_topic_pipeline_orchestrator.py` (8), `test_topic_pipeline_status.py` (14), `test_topic_stage_runs.py` (41), `tests/integration/test_topic_pipeline_dag.py` (4).
- Live prod smoke against the endpoint: empty when no hash captured; `chapter_resynced` warning when fake hash injected; 404 on unknown guideline; cleanup left no test residue.

## Plan deviations worth remembering

- **Two pre-merge commits, not one.** v1 implementation merged would have shipped a banner that didn't fire on its headline use case; the rework lived in `66136a0` and is what actually merged. PR description still describes the v1 design — read commit `66136a0` for the final architecture.
- **`topic_content_hashes` has no FK to anything.** The composite PK is the stable tuple itself. The whole point is to outlive `teaching_guidelines` rows.
- **Hash function moved fallback chains into `compute_input_hash_for_guideline` (the ORM helper), not `compute_input_hash` (the raw helper).** `compute_input_hash` stays simple (3 strings → hex) so unit tests don't need a guideline fixture.

## Phase 6b — starter checklist (next session)

Per plan §7 Phase 6b. Bound: ~0.5-1 day.

**Build steps:**

1. **API client** in `llm-frontend/src/features/admin/api/adminApiV2.ts`. Add types + a `getCrossDagWarnings(guidelineId)` function that mirrors the existing `getTopicDAG` shape:
   ```ts
   export interface CrossDagWarning {
     kind: "chapter_resynced";
     message: string;
     last_explanations_at: string | null;
   }
   export interface CrossDagWarningsResponse {
     warnings: CrossDagWarning[];
   }
   ```

2. **Wire the banner area** in `TopicDAGView.tsx:728-763`. The top-bar layout already has a slot — see the comment "banner area for cross-DAG warnings (Phase 6 populates)". Banner copy: use `warning.message` directly (already operator-friendly); show formatted `last_explanations_at` (use the existing `parseBackendDatetime` helper for the naive-UTC coercion). Stack above the cascade halo banner; same yellow/orange visual weight as STALE.

3. **Polling.** Fold the warning fetch into the existing `tick()` polling function — same cadence (2s active / 30s idle), same visibility-pause behaviour. Avoids a second timer + duplicates the visibility-hide logic that `R2.5` already fixed in Phase 5.

4. **No dismiss button.** Banner clears when `warnings: []` returns (i.e., when admin reruns explanations and the stored hash matches live again). This was the locked design decision per `plan.md` §7 Phase 6.

5. **E2E test.** Use the e2e harness; check `e2e/scenarios.json`. Scenario: open dashboard → no banner → trigger upstream mutation → banner appears → rerun explanations → banner clears.

6. **Documentation.** Update `docs/technical/architecture-overview.md` with a pointer to `book_ingestion_v2/dag/topic_pipeline_dag.py` (the DAG declaration) and `book_ingestion_v2/dag/cross_dag_warnings.py` (the cross-DAG signal).

**Acceptance** per plan §7 Phase 6: banner appears when chapter is re-synced; banner clears on next successful explanations; docs reference the DAG file.

### Useful pointers

- `book_ingestion_v2/api/dag_routes.py:325-385` — endpoint implementation. Returns `CrossDagWarningsResponse`.
- `book_ingestion_v2/models/schemas.py:543-560` — `CrossDagWarning`, `CrossDagWarningsResponse` Pydantic types (the frontend types should mirror these).
- `llm-frontend/src/features/admin/components/TopicDAGView.tsx` — page component. The polling tick is around line 470; the banner-area slot is in the top-bar (line 728-763 region).
- `llm-frontend/src/features/admin/api/adminApiV2.ts:1119+` — existing DAG API client, the pattern to follow for `getCrossDagWarnings`.
- `book_ingestion_v2/dag/cross_dag_warnings.py` — backend module. Useful for understanding what `chapter_resynced` actually means when writing the banner copy.

## Open follow-ups inherited (not gating Phase 6b)

| What | Where | When |
|---|---|---|
| R2.6 — per-effect `cancelled` flags vs shared `aliveRef` | `TopicDAGView.tsx:323-422` | Cleanup; not gating |
| R2.7 — tighten `is_stale?: boolean` to required | `adminApiV2.ts` `TopicDAGStageRow` | Cleanup |
| R2.8 — lightweight `topics/.../resolve` endpoint | `book_ingestion_v2/api/dag_routes.py` + `TopicDAGView.tsx:334` | Phase 6b polish or later |
| `scripts/baatcheet_v2_visualize.py` harness — call PixiCodeGenerator OR keep an SVG-flavoured prompt | `llm-backend/scripts/baatcheet_v2_visualize.py` | Standalone task |
| `pipeline_run_id` / `cascade_id` tagging on cascade-launched jobs (observability) | `dag/cascade.py:_launch_next` | Observability sweep |
| Move per-stage kwargs onto `Stage` | `dag/types.py` + 8 stage modules | Phase 1 follow-up; not gating |
| Read-time content-hash staleness for `baatcheet_visuals` | `stages/baatcheet_visuals.py` | If admins flag it |
| Eval rubric hardening for Baatcheet (V2 working doc Phase 5) | `llm-backend/services/baatcheet_eval_service.py` (new) | Separate workstream |

## Open questions for the next session

- **Banner stacking with cascade halo.** When a cascade is mid-flight AND the cross-DAG warning fires (rare but possible — admin started a non-explanations stage cascade after upstream changed), do we show both banners stacked? Recommendation: yes, top-down: cross-DAG warning above cascade halo, since the warning is durable while the cascade is ephemeral.
- **`last_explanations_at` formatting.** Use the same relative-time helper that the StageNode footer uses (e.g., "1h ago"), or absolute date ("2026-04-29 10:30")? Lean toward relative-time since the operator's mental model is "how stale is this."

## Quick commands for the next session

```bash
# Sync + branch
cd /Users/manishjain/repos/learnlikemagic
git checkout main && git pull
git checkout feat/topic-pipeline-dag-phase-6b  # already created from main this session

# Run the DAG-scope tests (sanity)
cd llm-backend && ./venv/bin/python -m pytest \
  tests/unit/test_cross_dag_warnings.py \
  tests/unit/test_cascade_orchestrator.py \
  tests/unit/test_topic_pipeline_dag.py \
  tests/integration/test_topic_pipeline_dag.py \
  -q --no-cov

# Start backend + frontend for Phase 6b dev
cd llm-backend && source venv/bin/activate && make run     # :8000
cd llm-frontend && npm run dev                              # :3000

# Hit the endpoint manually for quick iteration:
# curl http://localhost:8000/admin/v2/topics/{guideline_id}/cross-dag-warnings
```

## State at handover

- Local repo: branch `feat/topic-pipeline-dag-phase-6b`, clean working tree (after this handover commit lands).
- Main fully synced with origin; latest commit `3158574 feat(topic-pipeline): Phase 6a — cross-DAG warning backend + tests (#132)`.
- Prod RDS: `topic_content_hashes` table exists, empty (no production explanations have run since the migration). Old `teaching_guidelines.explanations_input_hash` column dropped.
- No active cascades.

A fresh session reading this picks up clean. The two memory files (`MEMORY.md` + `project_topic_pipeline_dag.md`) auto-load and reflect this state.
