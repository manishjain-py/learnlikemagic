# Topic Pipeline DAG — Implementation Plan (v1)

**Created:** 2026-04-28 (after Q&A interview locking design decisions)
**Status:** Plan locked, ready for Phase 1
**Research history:** `initial-plan.md` in this directory — contains the codebase inventory, reference orchestrator architecture summary, and the original open decisions before the interview.

## §0 — Quick state / resume guide

**What we're building:** an explicit topic-pipeline DAG with per-topic state tracking, auto-cascade on rerun, and a React Flow UI replacing today's stage-ladder dashboard. Same per-topic semantics as the user's reference fraud-investigation orchestrator, with the addition of durable per-stage state, content-hash staleness, and per-stage rerun.

**Scope of v1:** topic-scope DAG only (8 stages). Chapter-scope DAG follows in Phase 7 with the same architecture. One real refactor folded into v1: `baatcheet_visuals` is rewritten to do V2 visual-pass behaviour so every stage in the DAG does meaningful work (no "conditional auto-no-op" stages).

**Single source of truth:** `book_ingestion_v2/dag/topic_pipeline_dag.py` (Python module), with one `book_ingestion_v2/stages/{stage_id}.py` file per stage exporting a `Stage` object. Adding a stage = create one file + add one line to the DAG.

**Phases (each independently shippable):**
1. Declare the DAG + refactor stages into modules — no behaviour change ✅ shipped 2026-04-28 (PR #127)
2. Persist `topic_stage_runs` rows + stage timing ✅ shipped 2026-04-28 (PR #128)
3. Cascade orchestrator + rerun APIs ✅ shipped 2026-04-28 (PR #129)
3.5. Cascade codex follow-ups (P1 force-per-stage, P1 defense halt, P2 NULL-topic-key 404, P2 scoped stale-clear) ✅ shipped 2026-04-28 (PR #130, bundled with Phase 4)
4. `baatcheet_visuals` V2 refactor ✅ shipped 2026-04-28 (PR #130, bundled with Phase 3.5)
5. React Flow UI replaces stage ladder ✅ shipped 2026-04-29 (PR #131)
6. Cross-DAG warning + tests + polish ← **next**
7. (Later, not v1) Chapter DAG — same pattern

## §1 — Pains we're solving

From the interview, the user named three top pains:

- **(a) Silent skips** — a stage didn't fire and no one noticed; admin discovered later when downstream artefact was missing.
- **(b) Forgotten cascade** — admin re-ran upstream and didn't realise N downstream stages were now stale; old content shipped.
- **(d) Can't remember what stages exist** — adding a stage means editing 5+ files; reviewing changes is hard; onboarding new contributors is hard.

The plan addresses these structurally:
- (a) and (b) → **auto-cascade on rerun + durable state + halt-on-failure** so cascade either ships everything fresh or stops loudly.
- (d) → **DAG file as single source of truth + stage-as-module pattern** so adding a stage is one new file and one import.

Pains the user explicitly de-prioritised: cost of reruns (e), scattered-state-across-admin-pages (c). The plan keeps existing per-stage admin pages alive — the DAG view is additive UX, not a forced migration of every admin workflow.

## §2 — Decisions locked

Every Q from the interview, mapped to its answer.

| # | Decision | Choice |
|---|---|---|
| 1 | Auto-cascade on upstream rerun | **Yes** — cascade marks downstream stale and auto-runs in dependency order |
| 2 | Topic and chapter scope | **Separate DAGs**, independent orchestration |
| 3 | Cross-DAG signal when chapter changes | **Banner only** on the affected topic DAG; no auto-stale, no auto-rerun |
| 4 | Failure handling inside a cascade | **Halt-on-failure** — failed stage shows red, cascade stops, downstream untouched |
| 5 | DAG definition format | **Python module** (`book_ingestion_v2/dag/topic_pipeline_dag.py`) with `to_json()` for UI |
| 6 | Stage code organisation | **Stage-as-module** — one `book_ingestion_v2/stages/{id}.py` per stage exporting a `Stage` object |
| 7 | State enum | **4 states** (`pending`, `running`, `done`, `failed`) + separate `is_stale: bool` flag |
| 8 | State persistence | **Latest-only** in `topic_stage_runs`; history via existing `chapter_processing_jobs` rows |
| 9 | UI rollout | **Replace** `TopicPipelineDashboard` at the same URL — no parallel page |
| 10 | v1 scope | **Topic DAG only**; chapter DAG = Phase 7 |
| 11 | Cancellable cascade | **Yes**, soft-cancel — running stage finishes, no further launched |
| 12 | Cost preview before rerun | **No** — defer to Phase 2 polish |
| 13 | Optional/conditional stage categories | **None** — every stage in DAG is normal. `baatcheet_audio_review` removed; `baatcheet_visuals` refactored to do real work |
| 14 | Per-stage time logging | **Yes** — `started_at`, `completed_at`, `duration_ms` on `topic_stage_runs`, surfaced on every node |
| 15 | DAG layout | **BFS-depth auto-layout**, port `autoLayoutSteps` (~50 lines) from reference orchestrator |
| 16 | "Run all stages" button | **Yes** — runs every stage that isn't `done` (treats `stale` and `failed` as not-done); cascade does the rest |
| 17 | Lock collision UX | Rerun button **disabled** when state is `running`; race → 409 → toast |
| 18 | Migration / backfill of existing topics | **Lazy** — first dashboard load reconstructs state from artefacts via existing `TopicPipelineStatusService` logic + INSERT |
| 19 | Permissions / audit | Any admin can trigger; **no new audit log** in v1 (job rows already record trigger) |
| 20 | Stage timeouts | Keep existing — `HEARTBEAT_STALE_THRESHOLD = 1800s`, `MAX_POLL_WALL_TIME_SEC = 14400s` |

## §3 — Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│  topic_pipeline_dag.py (Python module — single source of truth)   │
│    STAGES: list[Stage] = [explanations, baatcheet_dialogue, …]    │
│    EDGES:  computed from each stage's depends_on                  │
│    validate_acyclic(): asserts at module import                   │
│    to_json(): serialises for UI consumption                       │
└─────────────────────────────────┬─────────────────────────────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            ▼                     ▼                     ▼
┌───────────────────────┐  ┌───────────────────┐  ┌──────────────────┐
│ stages/explanations.py│  │ stages/visuals.py │  │ stages/audio_*.py│
│   Stage(id="explan…", │  │   Stage(...)      │  │   Stage(...)     │
│         scope=…,      │  │                   │  │                  │
│         depends_on=…, │  │   def launch(...) │  │                  │
│         launch=…,     │  │   def status(...) │  │                  │
│         status=…,     │  │   def stale(...)  │  │                  │
│         stale=…)      │  │                   │  │                  │
└───────────────────────┘  └───────────────────┘  └──────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  TopicPipelineOrchestrator (extends today's; uses DAG)            │
│    run_all(guideline_id) — fires stages-not-done in dep order     │
│    rerun(guideline_id, stage_id) — runs one stage                 │
│    cancel(guideline_id) — soft-cancels running cascade            │
│    on_stage_complete(stage_id) — marks downstream stale + cascades│
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  topic_stage_runs (NEW Postgres table — durable per-stage state)  │
│    PK (guideline_id, stage_id)                                    │
│    state, is_stale, started_at, completed_at, duration_ms,        │
│    last_job_id, summary_json, updated_at                          │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  HTTP API (additive — existing routes stay)                       │
│    GET  /admin/v2/dag/definition                                  │
│    GET  /admin/v2/topics/{guideline_id}/dag                       │
│    POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun   │
│    POST /admin/v2/topics/{guideline_id}/dag/run-all               │
│    POST /admin/v2/topics/{guideline_id}/dag/cancel                │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  TopicDAGView.tsx (React Flow — replaces TopicPipelineDashboard)  │
│    Auto-layout BFS-depth (port autoLayoutSteps from reference)    │
│    Node = StageId · state badge · duration · last-run timestamp   │
│    Click → side panel: state, started, duration, error, deep-link │
│    Top bar: Run all · Cancel cascade · cross-DAG warning banner   │
└───────────────────────────────────────────────────────────────────┘
```

### Stage definition shape (every stage file looks like this)

```python
# book_ingestion_v2/stages/explanations.py
from book_ingestion_v2.dag.types import Stage, StageScope
from book_ingestion_v2.services import explanation_generator_service
from shared.repositories.explanation_repository import ExplanationRepository

def _launch(db, *, guideline_id, force=False, **kwargs) -> JobId:
    return launch_explanation_job(db, guideline_id=guideline_id, force=force)

def _status(db, *, guideline_id) -> StageStatusOutput:
    repo = ExplanationRepository(db)
    has_cards = repo.has_explanations_with_cards(guideline_id)
    return StageStatusOutput(
        done=has_cards,
        summary={"variant_count": repo.count_variants(guideline_id), …},
    )

def _stale(db, *, guideline_id, content_anchor) -> bool:
    return False  # explanations IS the staleness anchor

STAGE = Stage(
    id="explanations",
    scope=StageScope.TOPIC,
    label="Explanations",
    depends_on=[],
    launch=_launch,
    status_check=_status,
    staleness_check=_stale,
)
```

```python
# book_ingestion_v2/dag/topic_pipeline_dag.py
from book_ingestion_v2.stages import (
    explanations, baatcheet_dialogue, baatcheet_visuals,
    visuals, check_ins, practice_bank, audio_review, audio_synthesis,
)

STAGES: list[Stage] = [
    explanations.STAGE,
    baatcheet_dialogue.STAGE,
    baatcheet_visuals.STAGE,
    visuals.STAGE,
    check_ins.STAGE,
    practice_bank.STAGE,
    audio_review.STAGE,
    audio_synthesis.STAGE,
]

DAG = TopicPipelineDAG(STAGES)
DAG.validate_acyclic()  # raises at import if cycle introduced
```

### Persistence schema

```sql
CREATE TABLE topic_stage_runs (
    guideline_id   VARCHAR NOT NULL REFERENCES teaching_guidelines(id) ON DELETE CASCADE,
    stage_id       VARCHAR NOT NULL,
    state          VARCHAR NOT NULL,                -- pending|running|done|failed
    is_stale       BOOLEAN NOT NULL DEFAULT FALSE,
    started_at     TIMESTAMP NULL,
    completed_at   TIMESTAMP NULL,
    duration_ms    INTEGER NULL,
    last_job_id    VARCHAR NULL REFERENCES chapter_processing_jobs(id),
    content_anchor VARCHAR NULL,                    -- hash or timestamp captured at done
    summary_json   JSONB NULL,                      -- card_count, error_count, etc.
    updated_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guideline_id, stage_id)
);
CREATE INDEX idx_topic_stage_runs_state ON topic_stage_runs(state);
CREATE INDEX idx_topic_stage_runs_is_stale ON topic_stage_runs(is_stale) WHERE is_stale = TRUE;
```

## §4 — Stage inventory (final, v1)

Every stage below is a normal stage in the DAG: appears in the UI, runs in cascade, has the same lifecycle. No optional flags, no toggles, no conditional skips.

| Stage ID | Scope | Depends on | Existing launcher | Status check | Staleness signal |
|---|---|---|---|---|---|
| `explanations` | topic | (none) | `_run_explanation_generation` | `topic_explanations` row + non-empty `cards_json` | n/a — this IS the anchor |
| `baatcheet_dialogue` | topic | `explanations` | `_run_baatcheet_dialogue_generation` | `topic_dialogues` row + non-empty `cards_json` | `source_content_hash` mismatch with current variant A hash |
| `baatcheet_visuals` | topic | `baatcheet_dialogue` | **REFACTOR in Phase 4** — currently V1; new behaviour runs visual-pass selector + `PixiCodeGenerator` for ~12-18 cards per dialogue | count of `cards_with_visual_explanation` on dialogue / total visual targets | regen of `baatcheet_dialogue` invalidates |
| `visuals` | topic | `explanations` | `_run_visual_enrichment` | `cards_with_visuals` count on variant A cards_json | regen of `explanations` invalidates |
| `check_ins` | topic | `explanations` | `_run_check_in_enrichment` | `check_in_count` on variant A cards_json | regen of `explanations` invalidates |
| `practice_bank` | topic | `explanations` | `_run_practice_bank_generation` | `count(practice_questions) >= 30` | `min(practice.created_at) < explanations.created_at` |
| `audio_review` | topic | `explanations` | `_run_audio_text_review` | last `v2_audio_text_review` job `completed_at >= explanations.created_at` | review's `completed_at < explanations.created_at` |
| `audio_synthesis` | topic | `audio_review`, `baatcheet_dialogue` (soft, joins if dialogue exists) | `_run_audio_generation` | every `lines[].audio_url` populated across explanations + dialogue | clearing of `audio_url` by `audio_review` |

**Removed from DAG:** `baatcheet_audio_review` — duplicates Stage 5b's validator pass; never finds anything new after the V2 hardening. Manual route stays in case a defect class surfaces in production, but the DAG view doesn't render it.

**Chapter-scope stages** (`toc_save`, `page_ocr`, `chapter_extraction`, `chapter_finalization`, `topic_sync`, `refresher_generation`) — Phase 7 work. Their existing admin pages stay as-is in v1.

## §5 — Dependency graph (topic DAG, v1)

```
explanations
   │
   ├─► baatcheet_dialogue ───► baatcheet_visuals
   │           │
   │           └────► (audio_synthesis pulls dialogue MP3s if dialogue exists)
   │
   ├─► visuals
   │
   ├─► check_ins
   │
   ├─► practice_bank
   │
   └─► audio_review ───► audio_synthesis
```

Hard deps everywhere (every `→` raises `ValueError` if upstream is missing). Soft join only on `audio_synthesis` ← `baatcheet_dialogue`: if the dialogue exists, `audio_synthesis` synthesises its MP3s too; if not, just variant A explanations.

## §6 — Adding a new stage (the developer experience)

This is the test for whether pain (d) is actually solved. Suppose you want to add `kid_personalization` — a new topic-scope stage that uses the kid's interests + personality to tailor variant A's examples.

**Today (5+ files):** add `_run_kid_personalization` to `sync_routes.py`, add `launch_kid_personalization_job` to `stage_launchers.py`, add to `LAUNCHER_BY_STAGE`, add a status helper to `TopicPipelineStatusService`, add to frontend `STAGE_ORDER` + `STAGE_LABELS`, add to `PIPELINE_LAYERS`.

**After v1 (1 new file + 1 line):**

```python
# book_ingestion_v2/stages/kid_personalization.py
from book_ingestion_v2.dag.types import Stage, StageScope
from book_ingestion_v2.services import kid_personalization_service

def _launch(db, *, guideline_id, force=False, **kwargs):
    return kid_personalization_service.launch(db, guideline_id, force=force)

def _status(db, *, guideline_id):
    rows = db.query(StudentTopicCards).filter_by(guideline_id=guideline_id).count()
    return StageStatusOutput(done=(rows > 0), summary={"personalised_cards": rows})

STAGE = Stage(
    id="kid_personalization",
    scope=StageScope.TOPIC,
    label="Kid Personalisation",
    depends_on=["explanations"],
    launch=_launch,
    status_check=_status,
    staleness_check=lambda db, *, guideline_id, content_anchor: …,
)
```

```diff
# book_ingestion_v2/dag/topic_pipeline_dag.py
+from book_ingestion_v2.stages import kid_personalization

 STAGES: list[Stage] = [
     explanations.STAGE,
     baatcheet_dialogue.STAGE,
     …
+    kid_personalization.STAGE,
 ]
```

That's it. The DAG's `validate_acyclic()` catches dependency mistakes at import. The orchestrator picks up the new stage automatically — `run_all` runs it, cascade handles staleness, the UI renders a new node from `to_json()` without code change. No frontend code touches the stage list.

## §7 — Implementation phases

Each phase ships independently, can be reverted cleanly, and validates a separable risk.

### Phase 1 — Declare the DAG (no runtime change)

**Goal:** every existing stage refactored into a self-contained module + a single DAG file. Existing routes/dashboard still work, behaviour identical.

- New `book_ingestion_v2/dag/types.py` with `Stage` dataclass, `StageScope` enum, `StageStatusOutput` model, `TopicPipelineDAG` class with `validate_acyclic()`, `to_json()`, `topo_sort()`, `descendants(stage_id)`, `ready_nodes(state_map)`.
- New `book_ingestion_v2/stages/{id}.py` per stage (8 files for v1 topic scope), each importing the existing service + repository code unchanged.
- New `book_ingestion_v2/dag/topic_pipeline_dag.py` with the `STAGES` list.
- Refactor `LAUNCHER_BY_STAGE` (in `stage_launchers.py`) to be derived from the DAG: `LAUNCHER_BY_STAGE = {s.id: s.launch for s in DAG.stages}`. Keep the constant for backward compat, just compute it.
- Refactor `TopicPipelineStatusService` to call each stage's `status_check()` instead of hard-coded helpers — the existing logic moves into the per-stage modules. The service becomes a thin coordinator.
- Existing super-button (`run_topic_pipeline`) iterates `DAG.topo_sort()` instead of `PIPELINE_LAYERS`. `PIPELINE_LAYERS` constant deleted.
- Unit tests: `tests/unit/test_topic_pipeline_dag.py` — DAG is acyclic, every stage has a launcher + status check, `topo_sort()` matches what `PIPELINE_LAYERS` used to produce.

**Acceptance:** existing per-stage admin pages unchanged. Existing dashboard renders identically. Super-button runs all stages in the same order. `git grep PIPELINE_LAYERS` returns zero.

### Phase 2 — `topic_stage_runs` table + write-on-stage-complete

**Goal:** durable per-stage state, no read-side change yet.

- New table `topic_stage_runs` (schema in §3). Idempotent migration in `db.py:_apply_topic_stage_runs_table()`.
- New `TopicStageRunRepository` with `upsert_running(guideline_id, stage_id, job_id)`, `upsert_terminal(guideline_id, stage_id, state, duration_ms, summary)`, `mark_stale(guideline_id, stage_id)`, `get(guideline_id, stage_id)`, `list_for_topic(guideline_id)`.
- Hook into `run_in_background_v2` (the existing wrapper for `_run_*` background tasks): on entry, `upsert_running`; on completion, `upsert_terminal`. Single point of capture.
- `TopicPipelineStatusService` reads from `topic_stage_runs` first, falls back to artefact reconstruction (existing logic) when row missing — that's the lazy backfill.
- Unit tests: stage start writes `running`; stage complete writes terminal state + duration; stage failure writes `failed`; existing reconstruction logic still works as fallback.

**Acceptance:** existing dashboards render identically (lazy backfill kicks in on first read). `SELECT state, count(*) FROM topic_stage_runs GROUP BY state` returns reasonable numbers after a few stage runs. Duration_ms is captured.

### Phase 3 — Cascade orchestrator + rerun APIs

**Goal:** auto-cascade behaviour + per-stage rerun, headless (no UI change).

- New module `book_ingestion_v2/dag/cascade.py` with `CascadeOrchestrator`:
  - `start_cascade(guideline_id, from_stage_id=None)` — kicks off a cascade. If `from_stage_id` given, runs that stage + descendants; else runs everything not `done`.
  - `on_stage_complete(guideline_id, stage_id)` — called by the `run_in_background_v2` hook on terminal. If `done`, finds direct descendants, marks them `is_stale=true`, schedules them as ready; halts on `failed`.
  - `cancel(guideline_id)` — sets a `cancelled` flag in a small in-memory map keyed by `guideline_id`; cascade scheduler checks it before launching next stage.
- New API endpoints (additive — existing routes unchanged):
  - `POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun` — calls `Stage.launch(force=True)`, marks downstream stale, returns 202 with `cascade_id`.
  - `POST /admin/v2/topics/{guideline_id}/dag/run-all` — runs every not-done stage; cascade fills the rest.
  - `POST /admin/v2/topics/{guideline_id}/dag/cancel` — soft-cancel.
  - `GET  /admin/v2/topics/{guideline_id}/dag` — returns `{stages: [{id, state, is_stale, started_at, completed_at, duration_ms, last_job_id, summary, deps}, …]}`.
  - `GET  /admin/v2/dag/definition` — returns `DAG.to_json()` (topology only, no per-topic state).
- Cascade halt-on-failure: when a stage's terminal state is `failed`, the cascade's pending queue is cleared. Downstream stages stay at whatever state they had. Surface in the response as `{cascade_status: "halted_at_<stage_id>"}`.
- Lock collision: if `Stage.launch` raises `ChapterJobLockError`, the rerun endpoint returns 409 with `{code: "stage_running"}`.
- Tests: cascade runs in topo order; halt-on-failure stops the cascade; cancel works; lock collision returns 409; downstream stale-marking propagates correctly.

**Acceptance:** curl `POST /stages/explanations/rerun` → cascade fires → `topic_stage_runs` rows visible across the topic. Cancel mid-cascade stops. Halt-on-failure stops on a forced failure.

### Phase 4 — `baatcheet_visuals` V2 refactor

**Goal:** `baatcheet_visuals` does meaningful work on every V2 dialogue. Folds Phase 4.6 from the V2 working doc into v1.

- Refactor `BaatcheetVisualEnrichmentService.enrich_for_guideline`:
  - Selection step: call the existing visual-pass prompts (`baatcheet_visual_pass_system.txt` + `baatcheet_visual_pass.txt`) to pick cards based on `visual_required` flags + default-generate logic. Drop the SVG generation from the prompt — production path uses PixiJS.
  - Generation step: for each selected card, call `tutor.services.pixi_code_generator.PixiCodeGenerator.generate(visual_intent)`. Persist `card.visual_explanation = {output_type, title, visual_summary, visual_spec, pixi_code}` on `topic_dialogues.cards_json` via `flag_modified`.
  - Status: `{cards_with_visuals: N, total_cards: M}`. `done` when every `visual_required: true` card has `visual_explanation`.
- Stage's `staleness_check`: stale if the dialogue's `source_content_hash` changed since the visual pass ran.
- Tests: round-trip a V2 plan + dialogue through the refactored stage; assert PixiJS code is present on every `visual_required: true` card and on most concrete-content cards.

**Acceptance:** rerun `baatcheet_visuals` on math G4 ch1 topic 1 (existing in prod DB) → ~12-18 visuals appear in `cards_json`. Dashboard renders the count.

### Phase 5 — React Flow UI replaces stage ladder

**Goal:** the new dashboard.

- New component `llm-frontend/src/features/admin/components/TopicDAGView.tsx`:
  - Fetch `/admin/v2/dag/definition` once (DAG topology), `/admin/v2/topics/{guideline_id}/dag` periodically (state).
  - Render with `@xyflow/react` (dependency may already exist; if not, add it).
  - Auto-layout: port `autoLayoutSteps` from `/tmp/workflow-dag-reference/.../mockData.js` — ~50 lines, BFS depth → row-grouped layout.
  - Node component: id, label, state badge (colours: pending=grey, running=blue+animated, done=green, failed=red, stale-overlay=yellow), duration, last-run timestamp ("4m 12s · 2 hrs ago"). Click → side panel.
  - Side panel: state, started_at, completed_at, duration_ms, last_job_id link (deep-link to existing admin page), error message if failed, **Rerun** button (disabled when `running`), summary fields.
  - Top bar: "Run all" button, "Cancel cascade" button (when cascade is running), banner area for cross-DAG warnings (Phase 6 populates).
- Replace `TopicPipelineDashboard` with `TopicDAGView` at the same URL. Delete the old stage-ladder code.
- Polling cadence: every 2s while any stage is `running`; every 30s otherwise (matches reference's polling pattern, with ETag-based 304s).

**Acceptance:** open a topic → see DAG with all 8 nodes + current state. Click Rerun on a node → cascade fires, UI shows progression. Cancel mid-cascade works. Reload page → state survives (read from `topic_stage_runs`).

### Phase 6 — Cross-DAG warning + tests + polish

**Goal:** ship the warning signal + tighten the v1 test surface.

**Design decisions locked 2026-04-29:**
- **Hash persistence:** single `explanations_input_hash` column on `teaching_guidelines` (not a sibling events table). Table can be added later if Phase 7 chapter DAG needs richer cross-DAG state.
- **Banner UX:** no dismiss button. Banner shows whenever `current_input_hash != explanations_input_hash`; clears automatically when admin reruns `explanations` (which writes the new hash). Avoids the "ignore-and-forget" failure mode the DAG is fighting against.

**Split into two PRs for reviewability:**

**Phase 6a — Backend hash plumbing + integration tests (one PR):**
- Migration: add `explanations_input_hash VARCHAR(64) NULL` to `teaching_guidelines`.
- Hash function over `(guideline_text, prior_topics_context, topic_title)` — SHA-256 hex.
- Capture: write to `explanations_input_hash` in the `explanations` stage's terminal hook on success (alongside the existing `topic_stage_runs` write).
- Compare: new endpoint `GET /admin/v2/topics/{guideline_id}/cross-dag-warnings` → `{warnings: [{kind: "chapter_resynced", message: ..., last_explanations_at: ...}]}` returned when stored hash differs from live hash. Empty list otherwise.
- Integration tests in `tests/integration/test_topic_pipeline_dag.py` (new file):
  - Cascade halt-on-failure end-to-end (mock launchers, assert downstream stays untouched).
  - Cancel mid-cascade.
  - Rerun a stage → downstream marked stale → next rerun runs them.
  - Cross-DAG warning fires when `topic_sync`/`refresher_generation` mutates the guideline after `explanations` ran.

**Phase 6b — Frontend banner + E2E + docs polish (follow-up PR):**
- Wire the existing top-bar banner area in `TopicDAGView.tsx:728-763` to the new endpoint.
- Poll on the same cadence as the DAG (2s active / 30s idle).
- E2E test: open dashboard, click rerun, assert UI updates.
- Documentation: update `docs/technical/architecture-overview.md` with a pointer to the DAG file.

**Acceptance:** reasonable test coverage (the orchestrator behaviours each have a test). Cross-DAG banner appears when chapter is re-synced. Docs reference the DAG file.

### Phase 7 (later, not v1) — Chapter DAG

**Goal:** extend the same pattern to chapter scope.

- Stages: `toc_save`, `page_ocr`, `chapter_extraction`, `chapter_finalization`, `topic_sync`, `refresher_generation`.
- Refactor each into a `book_ingestion_v2/stages/{id}.py` file.
- New `chapter_pipeline_dag.py`.
- New table `chapter_stage_runs`.
- New URL `/admin/v2/books/{book_id}/chapters/{chapter_id}/dag`.
- Same orchestrator semantics (auto-cascade within scope, halt-on-failure, soft-cancel).
- Cross-DAG signal: completing `topic_sync` recomputes topic content hash → topic DAG banner fires automatically.

## §8 — Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `topic_stage_runs` drift from reality (missed write hook → row out of sync) | Medium | Hooks at the lowest layer (`run_in_background_v2` wrapper). Reconstruction fallback in `TopicPipelineStatusService` still works if a row is missing. Add a periodic reconciler job if drift is observed. |
| DAG cycles introduced when adding new stages | Low | `validate_acyclic()` raises at module import. Unit test asserts. CI catches before merge. |
| Auto-cascade triggers during a deploy / migration window and hits a half-deployed service | Low-Medium | Cascade respects existing `ChapterJobLockError`. New stages are added behind imports — old code paths keep working until deploy completes. Existing super-button is the same code path. |
| Stale-marking is too aggressive (every regen of explanations marks 7 downstream stages stale, admin overwhelmed) | Medium | UI dim/yellow not red; admin can still see they're stale and choose to leave them. The cascade auto-runs anyway, so the visual signal is transient. Watch user feedback. |
| `baatcheet_visuals` refactor takes longer than expected | Medium | The experiment harness (`baatcheet_v2_visualize.py`) already proves the prompts; only PixiJS wiring is new. Bound: ~1-2 days. If overrun, ship Phases 1-3 + 5 (UI shows 0 visuals on V2 dialogues, with a warning) and finish Phase 4 separately. |
| React Flow port takes longer than expected | Low | Reference is ~150 lines (`StepNode`, `WorkflowRunner`, `mockData`). Worst case: copy-paste with renames. |
| Lazy backfill is slow for topics with many stages on first dashboard load | Low-Medium | First-load cost is bounded (one read across 8 stages). If pain shows up, add a one-shot backfill script as Phase 6 polish. |

## §9 — References

**Existing code (read first when implementing each phase):**
- `book_ingestion_v2/services/topic_pipeline_orchestrator.py` — current orchestrator (`PIPELINE_LAYERS`, `run_topic_pipeline`).
- `book_ingestion_v2/services/stage_launchers.py` — `LAUNCHER_BY_STAGE` map.
- `book_ingestion_v2/services/topic_pipeline_status_service.py` — per-stage status reconstruction logic; preserve as the fallback.
- `book_ingestion_v2/models/database.py:132–164` — `ChapterProcessingJob` schema + invariants.
- `book_ingestion_v2/models/schemas.py:368–463` — `StageId`, `StageStatus`, `StageState` (will be replaced/repurposed in Phase 1).
- `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` — existing 8-row stage ladder (to be replaced).

**`baatcheet_visuals` V2 refactor (Phase 4):**
- `book_ingestion_v2/services/baatcheet_visual_enrichment_service.py` — existing V1 service (to be refactored).
- `book_ingestion_v2/prompts/baatcheet_visual_pass_system.txt` + `.txt` — V2 prompts (already updated).
- `tutor/services/pixi_code_generator.py` — production PixiJS generator.
- `scripts/baatcheet_v2_visualize.py` — experiment harness; the prompt-feeding pattern that the production service will adopt.

**Reference orchestrator (extracted to `/tmp/workflow-dag-reference/`):**
- `scripts/orchestrate.mjs` — DAG walker (~40 lines).
- `ui/src/components/StepNode.jsx` + `WorkflowRunner.jsx` — UI to port.
- `ui/src/data/mockData.js` `autoLayoutSteps` — BFS-depth layout.
- `ARCHITECTURE.md` — read first when implementing Phase 5.

**Research / context docs:**
- `docs/feature-development/topic-pipeline-dag/initial-plan.md` — original research summary; codebase inventory; reference orchestrator deep-dive.
- `docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md` §7 — V2 state, including Phase 4.6 context that this v1 plan absorbs.

## §10 — Next step

Start Phase 1: declare the DAG with stage-as-module pattern, no runtime behaviour change. It's the lowest-risk, fastest-feedback step and unblocks everything else. Bound: ~1-2 days for the 8 stages + DAG file + tests.
