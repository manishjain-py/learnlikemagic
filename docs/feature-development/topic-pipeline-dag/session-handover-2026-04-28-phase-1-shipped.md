# Session Handover — 2026-04-28 (Phase 1 shipped)

This is the handover from the implementation session that shipped Phase 1.
Pairs with `session-handover-2026-04-28.md` (the planning session that
preceded it).

## TL;DR

Phase 1 of the Topic Pipeline DAG is implemented, reviewed, fix-pass
applied, and **PR #127** is open. Memory tracker updated. Phase 2 is
ready to start; no further user input needed.

## What shipped this session

**PR:** https://github.com/manishjain-py/learnlikemagic/pull/127
**Branch:** `feat/topic-pipeline-dag-phase-1`
**Commit:** `753be74`
**Diff:** 22 files, +2272 / -604

**New code:**
- `llm-backend/book_ingestion_v2/dag/` — types.py, status_helpers.py, topic_pipeline_dag.py, launcher_map.py
- `llm-backend/book_ingestion_v2/stages/` — 8 stage modules (one per stage)
- `llm-backend/tests/unit/test_topic_pipeline_dag.py` — 19 tests

**Refactors:**
- `services/topic_pipeline_orchestrator.py` — `PIPELINE_LAYERS` deleted; `run()` iterates `DAG.topo_sort()`
- `services/topic_pipeline_status_service.py` — shrunk ~730 → ~210 lines (thin coordinator over DAG)
- `services/stage_launchers.py` — `LAUNCHER_BY_STAGE` moved to `dag/launcher_map.py`; PEP 562 `__getattr__` shim preserves the legacy import path

**Doc bundle in PR:** the three `docs/feature-development/topic-pipeline-dag/` files (initial-plan, plan, prior session handover) — committed as part of Phase 1 so plan + code ship together.

**Tests:** 42 passing.

## Reviewer fixes applied (folded into PR #127)

Two cloud reviewers ran; four real fixes:

1. **PEP 562 `__getattr__` shim** in `services/stage_launchers.py` so `from book_ingestion_v2.services.stage_launchers import LAUNCHER_BY_STAGE` still works (legacy path was broken in the initial draft). Same dict object → monkeypatching still works.
2. **`audio_synthesis.depends_on = ("audio_review",)`** only — `baatcheet_dialogue` is documented as a soft join, modelling it as a hard dep would break Phase 3 cascade staleness on dialogue regen. Topo order unchanged because audio_synthesis is last in `STAGES` declaration order.
3. **`Stage.depends_on` coerced to tuple** in `__post_init__` — guards against a future contributor passing a list.
4. **PR description corrected** to not overstate the "add a stage = one file" promise (Phase 1 collapses Python-side identity, but `_launcher_kwargs` + frontend stage list still need touching for now).

## Plan deviations worth remembering

- **`LAUNCHER_BY_STAGE` lives at `dag/launcher_map.py`** (plan said `services/stage_launchers.py`). Cycle was DAG → stages → stage_launchers → DAG. Inverted via launcher_map; back-compat via the shim.
- **`audio_synthesis ← baatcheet_dialogue`** is soft-only (no edge in `depends_on`). Plan §4 listed it as `(soft, joins if dialogue exists)`; we honour the soft semantic by not putting it in the DAG.
- **`StageStatusOutput = StageStatus`** type alias — narrowing deferred to Phase 2/3 once `topic_stage_runs` lands.

## Phase 1 follow-ups inherited by later phases

| What | Where | When |
|---|---|---|
| Move `_launcher_kwargs` + `QUALITY_ROUNDS` into `Stage` (e.g. `kwargs_fn(orch) -> dict`) | `services/topic_pipeline_orchestrator.py:176` + `:48-70` | **Phase 2** |
| Drop `StageId` Literal in favour of runtime DAG check | `models/schemas.py:370` | **Phase 2** |
| Replace `StageStatusOutput = StageStatus` alias with hash-aware shape | `dag/types.py` | **Phase 2/3** |
| Distinguish topo-deps vs data-deps on `Stage` (or accept that `depends_on` is topo-only and add a separate cascade-propagation field) | `dag/types.py` | **Phase 3** (before cascade lands) |
| Rename `halted_at_layer` → `cascade_status` (or similar) | `services/topic_pipeline_orchestrator.py:87` | **Phase 3** |
| Frontend `STAGE_ORDER` / `TopicPipelineDashboard` cleanup | `llm-frontend/src/features/admin/...` | **Phase 5** |

## Status of memory + tracker

Updated this session:
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/project_topic_pipeline_dag.md` — `Status` block records Phase 1 shipped + deviations + follow-ups.
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/MEMORY.md` — pointer rewritten from "Phase 1 ready to start" to "Phase 1 shipped 2026-04-28 (PR #127); Phases 2-6 pending."

A fresh session will auto-load both via the memory subsystem.

## Phase 2 — starter checklist (next session)

Per plan §7 Phase 2:

1. **New table `topic_stage_runs`** — schema in plan §3:
   ```sql
   CREATE TABLE topic_stage_runs (
       guideline_id   VARCHAR NOT NULL REFERENCES teaching_guidelines(id) ON DELETE CASCADE,
       stage_id       VARCHAR NOT NULL,
       state          VARCHAR NOT NULL,        -- pending|running|done|failed
       is_stale       BOOLEAN NOT NULL DEFAULT FALSE,
       started_at     TIMESTAMP NULL,
       completed_at   TIMESTAMP NULL,
       duration_ms    INTEGER NULL,
       last_job_id    VARCHAR NULL REFERENCES chapter_processing_jobs(id),
       content_anchor VARCHAR NULL,
       summary_json   JSONB NULL,
       updated_at     TIMESTAMP NOT NULL DEFAULT NOW(),
       PRIMARY KEY (guideline_id, stage_id)
   );
   ```
   + indexes on `state` and partial on `is_stale = TRUE`.
   + idempotent migration in `db.py:_apply_topic_stage_runs_table()`.

2. **`TopicStageRunRepository`** — methods: `upsert_running`, `upsert_terminal`, `mark_stale`, `get`, `list_for_topic`.

3. **Hook into `run_in_background_v2`** (the wrapper for `_run_*` background tasks): on entry → `upsert_running`; on completion → `upsert_terminal`. Single point of capture.

4. **Lazy backfill in `TopicPipelineStatusService`** — read `topic_stage_runs` first, fall back to existing artefact-reconstruction logic when row missing. The existing per-stage `_status` functions in `book_ingestion_v2/stages/` already do the reconstruction; the service just needs a "row exists?" check first.

5. **Tests:** stage start writes `running`; stage complete writes terminal + duration; stage failure writes `failed`; reconstruction fallback still works.

**Acceptance:** existing dashboards render identically (lazy backfill on first read). `SELECT state, count(*) FROM topic_stage_runs GROUP BY state` returns reasonable numbers after a few runs. `duration_ms` captured.

**Bound:** ~1 day.

**Recommended starter sequence:**
1. Read `docs/feature-development/topic-pipeline-dag/plan.md` §3 (schema) + §7 Phase 2.
2. Confirm PR #127 has merged; rebase if needed.
3. Branch from main: `feat/topic-pipeline-dag-phase-2`.
4. Schema + migration first, then repository, then hook, then backfill, then tests.

## Key references for Phase 2

- **Plan:** `docs/feature-development/topic-pipeline-dag/plan.md` (decisions in §2 are immutable; phase boundaries in §7)
- **Existing migration helpers:** `llm-backend/book_ingestion_v2/models/database.py` — look for other `_apply_*_table()` functions to match style
- **`run_in_background_v2`:** `llm-backend/book_ingestion_v2/api/processing_routes.py` — this is the hook point
- **Existing reconstruction logic:** every `_status(ctx)` function under `llm-backend/book_ingestion_v2/stages/` — Phase 2's lazy backfill calls these unchanged
- **Phase 1 PR for context:** #127 (closed/merged or open at session start — check first)

## Open questions for the next session

None blocking. The Phase 2 design is fully specified by the plan + the deviations list above.

If PR #127 receives further reviewer comments before merging, address them before starting Phase 2 work.
