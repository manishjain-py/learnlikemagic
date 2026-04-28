# Topic Pipeline DAG — Architecture & Plan

**Date:** 2026-04-28
**Status:** Planning — research complete, no code yet
**Purpose:** Replace the implicit "many stages, many launchers, many dashboards" topic-processing pipeline with one explicit workflow DAG + per-topic UI showing every node's state.

## 1. TL;DR

Most of what we want already exists in fragments. The codebase already has a stage taxonomy (`StageId`), a launcher map (`LAUNCHER_BY_STAGE`), a per-topic status reconstructor (`TopicPipelineStatusService`), an 8-row stage ladder UI (`TopicPipelineDashboard.tsx`), and a sequential orchestrator (`topic_pipeline_orchestrator.py`) — but they cover only the 8 topic-scope stages, miss the chapter/book upstream, recompute state on every page load, and render as a list, not a graph.

The plan: declare every stage in one explicit DAG definition file (book + chapter + topic scopes unified), swap the stage-ladder UI for the React Flow visualization pattern from your reference orchestrator, persist a durable per-(topic, stage) state row, and add per-stage re-run that invalidates downstream stages by content hash.

We don't need to rebuild the orchestration layer — the DAG walker, layered execution, locks, and launchers already work. We need to: **(a) make the DAG explicit, (b) add chapter-scope nodes, (c) persist state, (d) add staleness propagation, (e) replace the UI.**

## 2. The problem

There are 13+ stages across book / chapter / topic scopes. Adding a stage means editing 5+ files. The dashboard surfaces 8 of them; OCR / topic-extraction / refinalize / refresher live elsewhere; baatcheet_audio_review is in the codebase but not in the DAG. State is reconstructed from artifact presence + `chapter_processing_jobs` rows on every page load. There is no "this topic is stale because the chapter was re-extracted" signal — the user sees zero rows and assumes nothing was ever done. There is no per-stage re-run from the dashboard.

## 3. Where we are today

### Stages that exist (research output — full table in §6)

- **Book scope (2):** `toc_extraction` (synchronous tool, not tracked), `toc_save` (sets `BookChapter.status='toc_defined'`).
- **Chapter scope (5):** `page_upload + inline OCR`, `bulk_ocr / ocr_retry / ocr_rerun`, `topic_extraction` (does planning + chunks + finalization in one job), `topic_sync` (synchronous; mints `teaching_guidelines.id`), `refresher_generation` (chapter-scope but produces a single-topic `get-ready` guideline).
- **Topic scope (10):** `explanations` (Stage 5), `baatcheet_dialogue` (5b, V2), `baatcheet_visuals` (5c), `visuals` (Stage 6 PixiJS for variant A), `check_ins` (7), `practice_bank` (8), `audio_review` (9), `audio_synthesis` (10), `baatcheet_audio_review` (9b, opt-in side branch — defined but not in `LAUNCHER_BY_STAGE`).

### What's already orchestrator-shaped

- `book_ingestion_v2/services/topic_pipeline_orchestrator.py` — `PIPELINE_LAYERS` defines a layered DAG; `run_topic_pipeline()` drives it; halt-on-failure + parallel-within-layer for cross-topic.
- `book_ingestion_v2/services/stage_launchers.py` — `LAUNCHER_BY_STAGE: dict[StageId, LauncherFn]`. Each launcher returns a `ChapterProcessingJob`. This is the registry.
- `book_ingestion_v2/services/topic_pipeline_status_service.py` (~730 lines) — reconstructs `StageStatus{state, summary, warnings, is_stale, last_job_*}` per stage from artifacts + jobs. Already handles staleness anchored to `max(topic_explanations.created_at)` for downstream stages, and content-hash for `baatcheet_dialogue`.
- `book_ingestion_v2/models/database.py:132–164` — `ChapterProcessingJob` is the central state row. Two indexed invariants: at most one active job per chapter (chapter-scope), at most one per `(chapter_id, guideline_id)` pair (topic-scope). Locks + heartbeat + stale reaping already work.
- `llm-frontend/.../TopicPipelineDashboard.tsx` + `StageLadderRow.tsx` — 8-row stage ladder per topic with admin deep-links. Already calls `GET /admin/v2/.../topics/{topic_key}/pipeline`.

### What's missing

- **No chapter-scope stages in `StageId`.** The DAG dashboard knows about 8 topic-scope stages. OCR, topic extraction, refinalize, refresher live on `BookChapter.status` and per-chapter buttons elsewhere — invisible from the topic view.
- **No durable per-stage `done` flag.** State is recomputed on every page load (load all explanations + practice rows + dialogue + jobs for every topic). Fine today, expensive at scale, can't be queried for "show me all stale topics across the book."
- **No upstream-invalidation signal.** Re-running OCR or `topic_extraction` cascades a delete of downstream artifacts (`teaching_guidelines` cascade-delete `topic_explanations`, etc.), so re-running upstream → child stages return to "ready". But there's no "this topic was reset by the chapter re-running OCR" surfaced to the admin.
- **No per-stage re-run from the dashboard.** Admin re-runs a stage by navigating to the corresponding admin page and pressing its button. The unified dashboard has no "rerun" affordance.
- **No persisted `pipeline_run_id`.** Super-button generates one per press (`record_pipeline_run_id`), recorded in `progress_detail`, but `_detect_pipeline_run_id` returns `None` after the run completes. No `pipeline_runs` table.
- **`baatcheet_audio_review` is in `V2JobType` but not in the DAG.** Will surprise anyone reading the enum.
- **The chapter `topic_extraction` job conflates 4 conceptual stages** (planning, chunks, draft topics, finalization) into one row. For a DAG view, these probably want to be separate nodes — the user already wants to know e.g. "did finalization succeed?" separate from "did chunks succeed?"

## 4. Reference orchestrator — what to take, what to leave

`/Users/manishjain/Downloads/workflow-dag-reference.zip` (extracted to `/tmp/workflow-dag-reference/`) is your fraud-investigation orchestrator. Single JSON workflow file as source of truth for both UI and runtime; React Flow + auto-layout for the DAG; a 40-line stateless walker.

### Take verbatim (domain-agnostic, high leverage)

- **DAG walker** — ~40 lines, pure: build prereq map → "wave" of ready nodes → `Promise.all` → advance. Maps cleanly onto our existing `PIPELINE_LAYERS` semantics.
- **React Flow rendering layer** — `StepNode.jsx` (single dual-mode component), `WorkflowRunner.jsx` (live polling overlay), `mockData.js` BFS-depth auto-layout (~50 lines, no dagre/elk needed). State encoded as border + bg tint + edge animation.
- **Auto-layout algorithm** — BFS depth → row-grouped layout, centered. Hand-set `position` overrides preserved.
- **ETag-based polling** — `mtimeMs-size` ETag on the JSON file → 304 on no change. Adapt to a DB query result hash.
- **Schema-as-source-of-truth** — one workflow definition file used by both UI rendering and runtime.

### Take with adaptation

- **State model** — reference has only `pending|running|completed|failed` per-instance, ephemeral. Our needs add `stale|blocked|skipped` and durable persistence keyed by `(guideline_id, stage_id)`.
- **Per-step output panel** — adapt the right-side detail panel to show stage-specific fields: card count, content_hash, last_job, error, validator issues.

### Don't take

- **JSON-file persistence** — racy on concurrent writes; we already have Postgres + `chapter_processing_jobs`.
- **Domain-specific decision policy** (`decision.mjs`, `signals.mjs` PIM strength taxonomy) — irrelevant; our domain has no signals/decisions.
- **Subprocess-per-step orchestrator** — we're staying in-process Python.

### What the reference is missing (and we need to add)

1. **Per-step rerun endpoint** — reference has the button, no handler. Critical for our use case.
2. **Content-hash staleness** — reference assumes one run per case, never stale. Our staleness model is core.
3. **Instance vs. template separation** — reference has flat per-run rows. We need stages keyed by `(topicId, stageId)` with their own state machine across multiple runs.
4. **DAG cycle/shape validation** — reference invalid DAG silently deadlocks. Add a load-time check.

## 5. Proposed architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  topic_pipeline_dag.json (NEW — single source of truth)              │
│    { id, version, stages: [{id, scope, deps, launcher, …}], edges }  │
└─────────────────────────┬────────────────────────────────────────────┘
                          │ loaded once at startup, validated
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  TopicPipelineDAG  (NEW — book_ingestion_v2/dag/)                    │
│    - stages[], edges[], adjacency, topo-sort                         │
│    - validate_acyclic(), ready_nodes(state), staleness_propagation() │
└─────────────────────────┬────────────────────────────────────────────┘
                          │
        ┌─────────────────┼──────────────────────────────────────┐
        ▼                 ▼                                      ▼
┌─────────────┐  ┌─────────────────────┐  ┌────────────────────────────┐
│ Orchestrator│  │ Status reconstructor│  │ topic_stage_runs table     │
│ (extends    │  │ (extends            │  │ (NEW — durable state)      │
│  existing   │  │  TopicPipeline-     │  │   guideline_id, stage_id,  │
│  topic_     │  │  StatusService)     │  │   state, content_anchor,   │
│  pipeline_  │  │  - per stage        │  │   last_run_at, last_job_id │
│  orchestr.) │  │    {state, stale,  │  │   one row per (g,s)        │
│  - run all  │  │    summary, errs}  │  └────────────────────────────┘
│  - run one  │  │                     │
│  - dry-run  │  └─────────────────────┘
└─────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ HTTP API                                                              │
│   GET  /admin/v2/topics/{guideline_id}/dag                            │
│   POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun        │
│   POST /admin/v2/topics/{guideline_id}/dag/run-all                    │
│   GET  /admin/v2/dag/definition  (the DAG file itself, for UI render) │
│   GET  /admin/v2/chapters/{chapter_id}/dag-summary  (rollup)          │
└──────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Frontend  (replaces TopicPipelineDashboard's stage-ladder)            │
│   <TopicDAGView guideline_id={…}>                                     │
│     React Flow canvas + auto-layout (BFS depth)                       │
│     Node: stage_id, state badge color, last_job time, stale flag      │
│     Click → side panel: summary, warnings, last_job_id, output preview│
│     Buttons: Re-run · Open admin page · View output                   │
│     Top bar: "Run all stages" · "Run from here" · staleness toggle    │
└──────────────────────────────────────────────────────────────────────┘
```

### Key abstractions

```python
# DAG definition (pseudo-code; final shape TBD: JSON or Python module)
@dataclass
class StageDef:
    id: str                              # canonical stage id (matches StageId today)
    scope: Literal["book", "chapter", "topic"]
    label: str                           # human-readable
    depends_on: list[str]                # stage ids that must be done
    launcher: str                        # dotted path → fn(db, *, guideline_id|chapter_id, force, …)
    status_check: str                    # dotted path → fn(db, scope_id) → StageStatus
    staleness_check: str | None          # dotted path → fn(db, scope_id, content_anchor) → bool
    is_optional: bool = False            # baatcheet_audio_review etc.
    locks_with: list[str] = []           # stages that share a lock (rare; today none)

@dataclass
class StageState:
    NOT_READY = "not_ready"   # upstream stages not done
    READY = "ready"           # can be run now
    RUNNING = "running"
    DONE = "done"
    DONE_WITH_ERRORS = "done_with_errors"
    FAILED = "failed"
    STALE = "stale"           # was done, upstream changed; needs re-run
```

### Persistence model

Add **one** new table:

```sql
CREATE TABLE topic_stage_runs (
    guideline_id   VARCHAR FK → teaching_guidelines.id ON DELETE CASCADE,
    stage_id       VARCHAR NOT NULL,
    state          VARCHAR NOT NULL,             -- StageState enum
    last_run_at    TIMESTAMP NULL,
    last_job_id    VARCHAR FK → chapter_processing_jobs.id NULL,
    content_anchor VARCHAR NULL,                 -- hash or timestamp captured at done time
    summary_json   JSONB NULL,                   -- card_count, error_count, etc.
    updated_at     TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (guideline_id, stage_id)
);
```

Idempotently maintained by hooks in each `_run_*` background task: `start` → write `running`; `complete` → write `done` + `content_anchor` + `last_job_id`. The current `TopicPipelineStatusService` reconstruction logic stays as the read path (and as the migration backfill source). This is **additive** — old code keeps working.

For chapter-scope stages, use `chapter_stage_runs` with `chapter_id` PK. Same shape.

### Why we keep `chapter_processing_jobs`

That table is the in-flight job log (lock, heartbeat, progress, error). `topic_stage_runs` is the most-recent terminal state. Both are useful: the job table is the audit trail, the stage table is the dashboard read.

## 6. Stage inventory mapped to DAG nodes

| Stage ID (DAG) | Scope | Existing launcher | Status check | Staleness anchor | In current `StageId`? |
|---|---|---|---|---|---|
| `toc_save` | book | `TOCService.save_toc` (sync) | row presence on `book_chapters` | none | no |
| `page_ocr` | chapter (per page or bulk) | `_run page_service.bulk_ocr` (`v2_ocr` job) | `chapter_pages.ocr_status='completed'` for all pages in range | none | no |
| `chapter_extraction` | chapter | `start_processing` → `topic_extraction_orchestrator.extract` (`v2_topic_extraction`) | `book_chapters.status ∈ {chapter_completed, needs_review}` | none | no |
| `chapter_finalization` | chapter | sub-step of above; can also re-run via `refinalize` (`v2_refinalization`) | same chapter status | none | no |
| `topic_sync` | chapter | `TopicSyncService.sync_chapter` (sync) | presence of `teaching_guidelines` rows for the chapter | none | no |
| `refresher_generation` | chapter (writes one topic) | `_run_refresher_generation` (`v2_refresher_generation`) | presence of `get-ready` guideline + variant A | none | no |
| `explanations` | topic | `_run_explanation_generation` (`v2_explanation_generation`) | `topic_explanations` row + `cards_json` non-empty | n/a (this IS the staleness anchor) | yes |
| `baatcheet_dialogue` | topic | `_run_baatcheet_dialogue_generation` | `topic_dialogues` row + `cards_json` non-empty | `source_content_hash` vs current variant A hash | yes |
| `baatcheet_visuals` | topic | `_run_baatcheet_visual_enrichment` | `cards_with_visuals/total_visual_cards` count on dialogue cards | implicit (regen of 5b drops these) | yes |
| `visuals` | topic | `_run_visual_enrichment` | `cards_with_visuals` count on variant A | rerun of explanations resets | yes |
| `check_ins` | topic | `_run_check_in_enrichment` | `check_in_count` on variant A | rerun of explanations resets | yes |
| `practice_bank` | topic | `_run_practice_bank_generation` | `count(practice_questions) ≥ 30` | `min(practice.created_at) < explanations.created_at` | yes |
| `audio_review` | topic | `_run_audio_text_review` | last `v2_audio_text_review` job completed AND `completed_at >= content_anchor` | `completed_at < explanations.created_at` | yes |
| `audio_synthesis` | topic | `_run_audio_generation` | all `lines[].audio_url` populated across explanations + dialogue | clearing of `audio_url` by `audio_review` | yes |
| `baatcheet_audio_review` | topic (opt-in) | `_run_baatcheet_audio_review` | last job completed | none | not in `LAUNCHER_BY_STAGE` today |

15 nodes if we keep `chapter_extraction` and `chapter_finalization` as separate DAG nodes (recommended — they have distinct re-run paths via `refinalize`). 14 if we merge them.

## 7. Dependency graph

```
toc_save                                                 [book]
   │
   ▼
page_ocr  (per chapter — fans out to N pages but is one DAG node)   [chapter]
   │
   ▼
chapter_extraction  (planning + chunks + draft topics)              [chapter]
   │
   ▼
chapter_finalization  (merge + consolidate + curriculum context)    [chapter]
   │
   ▼
topic_sync  (mints teaching_guidelines.id; downstream pivots here)  [chapter]
   │
   ├──> refresher_generation  (chapter-scope, opt-in)              [chapter]
   │
   ▼
[topic-scope DAG below — runs once per teaching_guideline]
   │
   ▼
explanations
   │
   ├─> baatcheet_dialogue  ──> baatcheet_visuals
   │                            │
   │                            └─> [folds into audio_synthesis]
   │
   ├─> visuals
   │
   ├─> check_ins
   │
   ├─> practice_bank
   │
   └─> audio_review  ──> audio_synthesis  (also synthesises dialogue MP3s if dialogue exists)
                          │
                          └── (done)

   [opt-in side branch]
   baatcheet_audio_review  (deps: baatcheet_dialogue; not in main flow)
```

Hard-vs-soft deps from research:
- All topic-scope deps on `explanations` are **hard** (raise if missing).
- `baatcheet_dialogue` hard-deps on **variant A specifically**, not just any variant.
- `audio_synthesis` has a **soft** dep on `audio_review` — route 409s with `requires_confirmation=true` unless explicitly skipped.
- `topic_sync` hard-deps on `chapter.status ∈ {chapter_completed, needs_review}`.

## 8. Phased implementation plan

Each phase is independently shippable and reverts cleanly if it doesn't move the needle.

### Phase 1 — Declare the DAG (no behavior change)

**Goal:** make the implicit DAG explicit; no runtime change.

- Create `llm-backend/book_ingestion_v2/dag/topic_pipeline_dag.py` (Python module — easier to reference launcher functions by import than dotted-path resolution from JSON).
- Define `StageDef` dataclass + the 14-15 stage instances pointing at existing launchers and status checks.
- Add `validate_acyclic()` at module load.
- Generate the dependency graph from the DAG (replaces hardcoded `PIPELINE_LAYERS`).
- **Acceptance:** existing super-button still runs all stages in the same order; one-stage launches behave identically; unit test asserts DAG is acyclic and every `StageId` has a launcher.

### Phase 2 — Persist per-stage state (additive)

**Goal:** durable read-side for the dashboard.

- Add `topic_stage_runs` + `chapter_stage_runs` tables (idempotent ALTER pattern in `db.py`, mirror `_apply_topic_dialogues_table`).
- Hook into each `_run_*` background task: `start` writes `running`; `complete` writes terminal state with `content_anchor`. Backfill from existing artifacts the first time the dashboard loads a topic (lazy migration via `TopicPipelineStatusService`'s existing reconstruction).
- Keep `TopicPipelineStatusService` as the read API for the dashboard during this phase — it now reads `topic_stage_runs` first, falls back to reconstruction if missing.
- **Acceptance:** every existing dashboard renders identically; SQL `SELECT state, count(*) FROM topic_stage_runs GROUP BY state` returns sensible numbers; running a stage updates the row.

### Phase 3 — Add staleness propagation + per-stage rerun

**Goal:** the actual user-visible value.

- New API: `POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun?force=true`. Calls `LAUNCHER_BY_STAGE[stage_id]`. Marks the stage `running`. On terminal, recomputes downstream stages' staleness and updates their rows to `stale` if their `content_anchor` no longer matches.
- New API: `GET /admin/v2/topics/{guideline_id}/dag` returns full DAG state for one topic. Plus `GET /admin/v2/dag/definition` returns the DAG shape for the UI to render.
- Extend status semantics: `StageState` adds `STALE` (was done, upstream changed) and `BLOCKED` (deps not done, can't run yet). Existing `is_stale: bool` becomes a redundant projection of state.
- **Acceptance:** rerun a stage from an HTTP client; downstream stages flip to `stale`; admin can rerun those individually.

### Phase 4 — React Flow UI replaces the stage ladder

**Goal:** the visualization the user actually wants.

- New component `TopicDAGView.tsx` using `@xyflow/react` (matching the reference's stack). Auto-layout via BFS-depth from the reference (~50 lines, drop-in port).
- Nodes: stage label + state badge + last-run time + stale flag. Click → right-side detail panel with summary/warnings/last_job_id + Rerun button.
- Top bar: "Run all" / "Run from here" / staleness toggle / show-optional toggle (for `baatcheet_audio_review`).
- Replace the `TopicPipelineDashboard` stage ladder with this view; keep deep-links to per-stage admin pages from the detail panel.
- Backwards-compatible: the same page route, new component.
- **Acceptance:** user opens a topic, sees the full DAG (all 15 nodes) with current state, can rerun any stage from the panel. Looks like the fraud-investigation reference but for our domain.

### Phase 5 — Chapter & book rollups + cross-topic views

**Goal:** scale the view up.

- `GET /admin/v2/chapters/{chapter_id}/dag-summary` — for each topic in the chapter, the per-stage state matrix. UI: a heatmap or a small DAG per topic, side-by-side.
- "All stale topics in this book" query (now cheap because `topic_stage_runs` is indexed).
- Optional: a "pipeline_runs" table to track super-button orchestrations. Populated via existing `record_pipeline_run_id`. Lets admin filter the dashboard by run.

### Phase 6 (later) — Cleanup + quality

- Move chapter-scope stages into the DAG dashboard (Phase 1 already declared them; Phase 4 already showed them; Phase 6 makes their UI affordances first-class — currently they live on per-chapter buttons).
- Promote `baatcheet_audio_review` to a first-class optional stage (or remove it).
- Consider splitting `chapter_extraction` and `chapter_finalization` into more granular nodes if the user wants visibility into chunks vs. consolidation separately (the underlying job already snapshots both).

## 9. Open decisions for the user

1. **DAG definition: Python module vs. JSON file?** The reference uses JSON (one file is the source of truth for both runtime and UI). A Python module is more natural for us because launchers and status checks are functions; JSON would need a dotted-path resolver. **Recommendation: Python module, with a `to_json()` method that the UI fetches via `GET /admin/v2/dag/definition`.** Best of both — single source for runtime + UI rendering, no string-based imports.

2. **Should chapter_extraction stay one node or split?** Today it does planning + chunks + finalization in one job. Splitting gives finer-grained state but changes the orchestration. **Recommendation: Phase 1 keeps it as 2 nodes (extraction + finalization, since `refinalize` already exists), Phase 6 considers further splits if the user asks for chunk-level visibility.**

3. **Should `topic_stage_runs` go in or stay reconstructed-on-read?** Reconstruction is fine today; durable rows scale better and unlock cross-topic queries. **Recommendation: Phase 2 adds the table additively; reconstruction stays as the fallback / migration source.** Low risk, high future leverage.

4. **What does "rerun" do to downstream stages?** Three options: (a) automatically rerun them, (b) mark them `stale` and let admin click to rerun each, (c) mark `stale` + offer "Rerun stage X and everything downstream" button. **Recommendation: (b) with the (c) button as a convenience.** Matches admin's mental model; doesn't surprise them with cascading work.

5. **UI library — keep React Flow from the reference, or use Mermaid/SVG?** Reference is React Flow + 50-line auto-layout. **Recommendation: React Flow (`@xyflow/react`)** — matches the reference, stable, supports interactive nodes, panning, fit-view. Already chosen for the kind of visualization we want.

6. **Do we wire `baatcheet_audio_review` into the DAG?** It's been intentionally excluded as a manual safety valve. **Recommendation: include as an optional stage with a flag** — show it in the DAG behind a "show optional stages" toggle. Keeps the default view clean, doesn't lose the affordance.

## 10. Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `topic_stage_runs` divergence from `chapter_processing_jobs` (missed write hook → row out of sync) | Medium | Phase 2 hooks at the lowest level (`run_in_background_v2` wrapper). Reconstruction fallback in `TopicPipelineStatusService` catches drift. Add a periodic reconciler if drift shows up. |
| DAG cycles introduced when adding new stages | Low | `validate_acyclic()` at module-load; unit test asserts. |
| Rerun a stage while it's already running (lock collision) | High | Existing `ChapterJobLockError` handles this. UI disables Rerun button when state is `running`. |
| Stale-detection is too aggressive (every regen of explanations marks 7 downstream stages stale, admin overwhelmed) | Medium | Stale ≠ broken — UI dim/yellow not red. Provide "Rerun all stale" convenience. Watch user feedback. |
| Frontend port of React Flow + auto-layout takes longer than expected | Low | Reference is 50 lines + 1 component file. Worst case, copy-paste with renames. |
| Chapter-scope stages don't fit the per-topic dashboard model cleanly (one OCR run per chapter feeds many topics) | Medium | Render chapter-scope nodes as "fan-out" nodes that share state across all topics in the chapter. State is read from the chapter row, not per-topic. UI shows them at the top of the per-topic DAG with a "this is shared with N other topics" hint. |

## 11. References

**Existing code (read first when implementing):**
- `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py` — current orchestrator (`PIPELINE_LAYERS`, `run_topic_pipeline`).
- `llm-backend/book_ingestion_v2/services/stage_launchers.py` — `LAUNCHER_BY_STAGE` map; the registry.
- `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py` — per-stage status reconstruction logic; preserve as the read fallback.
- `llm-backend/book_ingestion_v2/models/database.py:132–164` — `ChapterProcessingJob` schema + invariants.
- `llm-backend/book_ingestion_v2/models/schemas.py:368–463` — `StageId`, `StageStatus`, `StageState`.
- `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` — existing 8-row stage ladder.

**Reference orchestrator (extracted):**
- `/tmp/workflow-dag-reference/workflow-dag-reference/scripts/orchestrate.mjs` — DAG walker.
- `/tmp/workflow-dag-reference/workflow-dag-reference/ui/src/components/StepNode.jsx` + `WorkflowRunner.jsx` — UI to port.
- `/tmp/workflow-dag-reference/workflow-dag-reference/ui/src/data/mockData.js` — `autoLayoutSteps` BFS-depth layout.
- `/tmp/workflow-dag-reference/workflow-dag-reference/ARCHITECTURE.md` — read this first when implementing the UI.

**Research outputs (raw, captured for the next session):**
- This document.
- `docs/feature-development/topic-pipeline-dag/` will be the working dir for implementation notes (pattern matches `docs/feature-development/baatcheet/` from the V2 effort).

## 12. Next step

Review this plan with the user. Lock decisions on §9 (Python-vs-JSON DAG, chapter_extraction split, topic_stage_runs scope, rerun semantics, optional-stage handling). Then start Phase 1 (declare the DAG, no behavior change) — it's the lowest-risk, fastest-feedback step and unblocks everything else.
