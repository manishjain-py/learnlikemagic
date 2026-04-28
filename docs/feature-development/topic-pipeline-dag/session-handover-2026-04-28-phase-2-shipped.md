# Session Handover — 2026-04-28 (Phase 2 shipped)

This is the handover from the implementation session that shipped Phase 2.
Pairs with `session-handover-2026-04-28-phase-1-shipped.md`.

## TL;DR

Phase 2 of the Topic Pipeline DAG is implemented, two-reviewer feedback
is addressed, and **PR #128** is squash-merged to main as commit
`8a5d5ed`. Memory tracker updated. Phase 3 is ready to start; no further
user input needed.

## What shipped this session

**PR:** https://github.com/manishjain-py/learnlikemagic/pull/128
**Squash commit:** `8a5d5ed` on main
**Branch:** `feat/topic-pipeline-dag-phase-2` (deleted on merge)
**Diff:** 9 files, +1559 / −8 (across both commits)

**New code:**
- `llm-backend/book_ingestion_v2/repositories/topic_stage_run_repository.py` — `upsert_running` / `upsert_terminal` / `upsert_backfill` / `mark_stale` / `get` / `list_for_topic`. State validation on terminal + backfill writes.
- `llm-backend/tests/unit/test_topic_stage_runs.py` — 41 tests across repo semantics, hook helpers, lazy backfill, stuck-running reconciliation, Baatcheet capture, observability isolation.

**Schema:**
- `TopicStageRun` ORM model in `book_ingestion_v2/models/database.py` — PK (guideline_id, stage_id), state/is_stale/started_at/completed_at/duration_ms/last_job_id/content_anchor/summary_json/updated_at. FK to `teaching_guidelines.id` (CASCADE) and `chapter_processing_jobs.id`. Partial index on `is_stale = TRUE`.
- `_apply_topic_stage_runs_table()` migration helper in `db.py` — verifies table + ensures partial index.

**Hook:**
- `_write_topic_stage_run_started` and `_write_topic_stage_run_terminal` in `book_ingestion_v2/api/processing_routes.py`. Single point of capture in `run_in_background_v2`. Writes `running` on stage entry; `done`/`failed` on terminal with computed `duration_ms`. Wrapped in broad except + rollback so observability writes can't break the actual stage execution. Started-write uses a fresh session (mirrors terminal-write) to isolate from `target_fn`'s session.

**Lazy backfill + reconciliation:**
- `_backfill_topic_stage_runs` in `topic_pipeline_status_service.py` runs on every `get_pipeline_status` call. Two passes: (1) reconcile stuck-running rows whose `last_job_id` is now terminal; (2) backfill missing rows for terminal stages. Write-only side effect — response shape unchanged.

**Refactors:**
- `POST_SYNC_JOB_TYPES` in `chapter_job_service.py` — added `BAATCHEET_DIALOGUE_GENERATION`, `BAATCHEET_VISUAL_ENRICHMENT`, `BAATCHEET_AUDIO_REVIEW`. Pre-fix, all three were treated as chapter-level (guideline_id forced to NULL) — a long-standing bug Phase 2 had to fix.
- Migration `_apply_chapter_jobs_guideline_id` updated to backfill the same Baatcheet types from historical rows.
- `dag/launcher_map.py` — added `JOB_TYPE_TO_STAGE_ID` dict + import-time cross-check against the DAG.

**Tests:** 41 new + 62 existing topic-pipeline = 103 passing.

## Reviewer fixes folded in (commit `b53fd8e`)

Two cloud reviewers ran on the initial Phase 2 commit (`bf4ec55`).
Five real fixes baked into the merged PR:

1. **P1 — Baatcheet capture gap.** `BAATCHEET_DIALOGUE_GENERATION` and `BAATCHEET_VISUAL_ENRICHMENT` were missing from `POST_SYNC_JOB_TYPES`, so `acquire_lock` forced `guideline_id=NULL` and the Phase 2 hook silently skipped them. Added all three Baatcheet types to the frozenset; updated migration backfill list. Parameterized integration test goes through `acquire_lock`.
2. **P1 — Session poisoning.** Broad excepts around the observability writes didn't roll back the SQLAlchemy session; a transient commit failure put `target_fn`'s session into `PendingRollbackError`. Started-write now uses a fresh session (mirrors terminal-write); all three broad excepts rollback for hygiene. Two simulated-IntegrityError tests verify the session stays usable.
3. **P2 — Stuck-running reconciliation.** Heartbeat reaping marks the chapter job failed but doesn't touch `topic_stage_runs`, so a dead worker leaves a stuck `running` row that Phase 3 cascade would read as live. Added `_reconcile_stuck_running_rows` (single batched job lookup, runs on every dashboard read). Four tests cover failed/completed/still-running/deleted-job cases.
4. **Reviewer2 #1 — Error-path ordering.** Exception path in `run_in_background_v2` now writes the observability terminal row BEFORE `release_lock` so a failing `release_lock` can't drop the row.
5. **Reviewer2 #2 — `upsert_backfill` validation.** Now rejects non-terminal states (matches `upsert_terminal`).

## Plan deviations worth remembering

- **`JOB_TYPE_TO_STAGE_ID` lives in `dag/launcher_map.py`** as a hard-coded dict. Plan didn't specify a location. Phase 2 deliberately did NOT add `job_type` to the `Stage` dataclass — minimum-touch. Phase 3 may revisit if cascade needs richer mapping.
- **Backfill writes only `done`/`failed` rows.** `topic_stage_runs` has 4 states (pending/running/done/failed) vs `StageStatus`'s 6 (adds `warning`/`ready`/`blocked`). The 4-state vocabulary models "stage-as-task" execution; "warning" models "artifact partially OK" which is a read-time concept. Phase 3 will need a story for `warning` once reads start preferring rows.
- **Read path is unchanged in Phase 2.** Lazy backfill is write-only. The plan said "reads from topic_stage_runs first, falls back to artifact reconstruction"; we deferred that read-order flip to Phase 3 (when cascade staleness needs it).

## Phase 2 follow-ups inherited by later phases

| What | Where | When |
|---|---|---|
| Read-order flip — prefer `topic_stage_runs` rows when present, fall back to artifact reconstruction | `services/topic_pipeline_status_service.py` | **Phase 3** |
| `warning` state mapping in `topic_stage_runs` (bool flag vs separate column vs reconstruction-only) | `dag/types.py` + service | **Phase 3** |
| Move `job_type` onto `Stage` dataclass and derive `JOB_TYPE_TO_STAGE_ID` from DAG | `dag/types.py` + 8 stage modules | **Phase 3** (if cascade needs it) |

## Status of memory + tracker

Updated this session:
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/project_topic_pipeline_dag.md` — Phase 2 → shipped, deviations + follow-ups + Phase 3 starter checklist.
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/MEMORY.md` — pointer rewritten to "Phases 1+2 shipped 2026-04-28; Phase 3 next".
- `docs/feature-development/topic-pipeline-dag/plan.md` §0 — phase list now shows ✅ tags on phases 1+2.

A fresh session will auto-load both memory files via the memory subsystem.

## Phase 3 — starter checklist (next session)

Per plan §7 Phase 3:

1. **New module `book_ingestion_v2/dag/cascade.py`** with `CascadeOrchestrator`:
   - `start_cascade(guideline_id, from_stage_id=None)` — kicks off cascade; if `from_stage_id` given runs that stage + descendants, else runs everything not `done`.
   - `on_stage_complete(guideline_id, stage_id)` — called by the `run_in_background_v2` hook on terminal. If `done`, marks descendants `is_stale=true`, schedules ready ones; halts on `failed`.
   - `cancel(guideline_id)` — soft-cancel via in-memory map keyed by guideline_id; cascade scheduler checks before launching next stage.

2. **New API endpoints** (additive — existing routes unchanged):
   - `POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun`
   - `POST /admin/v2/topics/{guideline_id}/dag/run-all`
   - `POST /admin/v2/topics/{guideline_id}/dag/cancel`
   - `GET  /admin/v2/topics/{guideline_id}/dag` (returns `{stages: [...]}`)
   - `GET  /admin/v2/dag/definition` (returns `DAG.to_json()`)

3. **Cascade halt-on-failure** — when a stage's terminal state is `failed`, clear the cascade's pending queue. Surface in response as `{cascade_status: "halted_at_<stage_id>"}`.

4. **Lock collision** — if `Stage.launch` raises `ChapterJobLockError`, rerun endpoint returns 409 with `{code: "stage_running"}`.

5. **Read-order flip + `warning` mapping** (Phase 2 follow-ups): decide how `TopicPipelineStatusService` should prefer `topic_stage_runs` rows and how partial-artifact stages surface in the row vocabulary.

6. **Tests:** cascade runs in topo order; halt-on-failure stops the cascade; cancel works; lock collision returns 409; downstream stale-marking propagates; reconciled rows feed cascade correctly.

**Acceptance:** curl `POST /stages/explanations/rerun` → cascade fires → `topic_stage_runs` rows visible across topic. Cancel mid-cascade stops. Halt-on-failure stops on a forced failure.

**Bound:** ~2-3 days.

**Recommended starter sequence:**
1. Read `docs/feature-development/topic-pipeline-dag/plan.md` §3 + §7 Phase 3.
2. Branch from main: `feat/topic-pipeline-dag-phase-3`.
3. `cascade.py` module first (data structures + topo walking), then read-order flip in status service, then API endpoints, then wire cascade into the existing terminal-write hook, then tests.

## Key references for Phase 3

- **Plan:** `docs/feature-development/topic-pipeline-dag/plan.md` (decisions in §2 immutable; phase boundaries in §7)
- **Phase 2 hook point:** `book_ingestion_v2/api/processing_routes.py` — `_write_topic_stage_run_terminal` is where `on_stage_complete` plugs in
- **DAG primitives:** `book_ingestion_v2/dag/types.py` — `TopicPipelineDAG.descendants(stage_id)`, `ready_nodes(state_map)` already implemented for Phase 3 use
- **Reference orchestrator:** `/tmp/workflow-dag-reference/` — DAG walker (`scripts/orchestrate.mjs`), ~40 lines

## Open questions for the next session

None blocking. Phase 3 is fully specified by plan §7 + Phase 2 follow-ups list above.
