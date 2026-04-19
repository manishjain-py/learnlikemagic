# Tech Implementation Plan: Topic Pipeline Dashboard

**PRD:** `docs/feature-development/topic-pipeline-dashboard/PRD.md`
**Patterns mirrored from:**
- `ExplanationGeneratorService` + route pattern (`llm-backend/book_ingestion_v2/services/explanation_generator_service.py`, `api/sync_routes.py:117`)
- Background job pattern (`llm-backend/book_ingestion_v2/api/processing_routes.py:438 run_in_background_v2`)
- Job service (`llm-backend/book_ingestion_v2/services/chapter_job_service.py`)
- Existing per-stage admin pages (`llm-frontend/src/features/admin/pages/ExplanationAdmin.tsx`, `VisualsAdmin.tsx`, etc.)
- Admin API client (`llm-frontend/src/features/admin/api/adminApiV2.ts`)

---

## 1. Overview

A topic-scoped admin hub plus an optional chapter-level runner. No new student-facing surfaces. Shipped in 3 phases:

- **Phase 1** — Read-only hub + consolidated GET endpoint. Zero backend risk. Ships the UX win.
- **Phase 2** — Super-button orchestration + `ChapterJobService` lock refactor + staleness tracking. Requires a DB migration.
- **Phase 3** — Chapter-level runner + prev/next nav + inline error UX.

Each phase is independently rollbackable and shippable.

### Dataflow (end state)

```
[today]
admin → per-stage page (explanations/visuals/check-ins/practice/audio-review/audio)
      → POST /generate-<stage>?guideline_id=X
      → ChapterJobService.acquire_lock(chapter_id)  — blocks any other job in this chapter
      → run_in_background_v2(daemon thread)

[after Phase 2]
admin → topic pipeline hub
      → POST /.../topics/{topic_key}/run-pipeline { quality_level }
      → TopicPipelineOrchestrator picks stages not Done
      → For each stage (in DAG order, with ②③④ in parallel):
          - ChapterJobService.acquire_lock(chapter_id, guideline_id)
            # post-sync lock scoped to (chapter_id, guideline_id) — allows other topics to run
          - run_in_background_v2
          - await terminal status
          - hard-stop on failure
      → records pipeline_run_id for hub polling
```

The orchestrator calls the same per-stage services the existing routes call. No new LLM prompts, no new agents, no new DB tables (only a column added).

---

## 2. Phase 1 — Read-Only Hub

### 2.1 Files changed

#### Backend

| File | Change |
|---|---|
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | **NEW endpoint** — `GET /chapters/{chapter_id}/topics/{topic_key}/pipeline` |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py` | **NEW** — consolidated status computation for one topic |
| `llm-backend/book_ingestion_v2/models/schemas.py` | **NEW schemas** — `TopicPipelineStatusResponse`, `StageStatus`, `StageStatusEnum` |
| `llm-backend/tests/unit/test_topic_pipeline_status.py` | **NEW** — unit tests |

#### Frontend

| File | Change |
|---|---|
| `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` | **NEW** — hub page |
| `llm-frontend/src/features/admin/components/StageLadderRow.tsx` | **NEW** — one ladder row; status badge, summary, deep links |
| `llm-frontend/src/features/admin/hooks/useTopicPipeline.ts` | **NEW** — fetch + smart polling hook |
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | **Add** `getTopicPipeline`, `TopicPipelineStatus`, `StageStatus` types |
| `llm-frontend/src/App.tsx` | **Add route** `books-v2/:bookId/pipeline/:chapterId/:topicKey` |
| `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | **Add** per-topic "Pipeline →" link in each chapter's topic list |

#### Docs

| File | Change |
|---|---|
| `docs/technical/book-guidelines.md` | Add "Topic Pipeline Dashboard" subsection with endpoint + route + status-computation rules |

### 2.2 New service: `topic_pipeline_status_service.py`

One function: read everything needed to compute the 6-stage status for one topic. Consolidates queries that are currently spread across `get_explanation_status`, `get_visual_status`, `get_check_in_status`, `get_practice_bank_status`, plus two latest-job endpoints.

```python
"""Compute per-topic pipeline status for the admin hub.

Reads from teaching_guidelines, topic_explanations, practice_questions,
and chapter_processing_jobs. No mutations. One call returns all 6 stages'
status plus the chapter preflight.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.constants import V2JobType
from shared.models.entities import TeachingGuideline, TopicExplanation, PracticeQuestion
from book_ingestion_v2.models.database import ChapterProcessingJob

StageState = Literal["done", "warning", "running", "ready", "blocked", "failed"]

@dataclass
class StageStatus:
    stage_id: Literal["explanations", "visuals", "check_ins", "practice_bank", "audio_review", "audio_synthesis"]
    state: StageState
    summary: str                        # human-readable ("1 variant · 18 cards")
    warnings: list[str]                 # ["layout_warning on card 3", "stale — explanations updated 5m ago"]
    blocked_by: Optional[str]           # "explanations" if state == "blocked"
    is_stale: bool
    last_job_id: Optional[str]
    last_job_status: Optional[str]
    last_job_error: Optional[str]
    last_job_completed_at: Optional[datetime]


class TopicPipelineStatusService:
    def __init__(self, db: Session):
        self.db = db

    def get_pipeline_status(
        self, book_id: str, chapter_id: str, topic_key: str
    ) -> "TopicPipelineStatusResponse":
        guideline = self._load_guideline(book_id, chapter_id, topic_key)
        if not guideline:
            raise LookupError(f"No teaching_guideline for {chapter_id}/{topic_key}")

        explanations = self._load_explanations(guideline.id)
        exp_updated_at = max((e.updated_at for e in explanations), default=None)

        return TopicPipelineStatusResponse(
            topic_key=topic_key,
            topic_title=guideline.topic_title,
            guideline_id=guideline.id,
            chapter_preflight_ok=True,  # guideline exists → synced
            stages=[
                self._stage_explanations(explanations),
                self._stage_visuals(explanations),
                self._stage_check_ins(explanations),
                self._stage_practice_bank(guideline.id, exp_updated_at),
                self._stage_audio_review(guideline.id, exp_updated_at),
                self._stage_audio_synthesis(explanations),
            ],
        )

    # One private method per stage — each reads only what it needs and returns StageStatus.
    # Staleness for practice_bank/audio_review = artifact timestamp < exp_updated_at.
    # Blocked logic: ② ③ ④ ⑤ ⑥ all blocked when ① is not Done.
```

**Decision:** computed status lives in a single service to keep the consolidated endpoint fast (one trip to the DB, fetch-then-compute). Returning 6 status records in one response removes the 6-endpoint fan-out the frontend would otherwise need.

### 2.3 Stage-status computation rules (authoritative)

| Stage | Source data | `done` | `warning` | `ready` | `blocked` | `failed` |
|---|---|---|---|---|---|---|
| ① Explanations | `topic_explanations` rows where `guideline_id = X` | ≥1 variant with ≥1 card, last job completed | — | 0 variants, last job missing-or-completed | never (requires preflight only) | last explanation job for `(chapter_id, guideline_id)` status=failed |
| ② Visuals | Cards in `topic_explanations.cards_json` | Any card has `visual_explanation.pixi_code` AND no card has `layout_warning=true` | Any card has `layout_warning=true` | 0 cards have `visual_explanation` | ① not done | last visual job failed |
| ③ Check-ins | Cards in `cards_json` with `type=check_in` (or `check_in` field) | ≥1 check-in card | — | 0 check-ins | ① not done | last check-in job failed |
| ④ Practice bank | `practice_questions` rows for `guideline_id` | ≥30 rows AND not stale | 1–29 rows OR stale | 0 rows | ① not done | last practice job failed |
| ⑤ Audio review | Latest `chapter_processing_jobs` row with `job_type=v2_audio_text_review` for this guideline | Latest job `completed` AND not stale | Latest job `completed_with_errors` OR stale | No prior job OR last terminal state was failed and a newer run hasn't started | ① not done | Latest job `failed` |
| ⑥ Audio synthesis | `audio_url` on every line of every card in `cards_json` for all variants | All `audio` lines have non-null `audio_url` | Mix of null / non-null | No `audio_url` on any line | ① not done | last audio job failed |

**Stale rule:** `artifact.created_at (or completed_at) < max(topic_explanations.updated_at for this guideline)` → `is_stale=true`. Phase 1 computes `is_stale` but does not yet have the timestamp column wired to ⑤ reliably (audio review job's `completed_at` covers this already).

### 2.4 New endpoint

```
GET /admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/pipeline
Response 200: TopicPipelineStatusResponse
Response 404: {"detail": "Guideline not found for topic_key=..."}
```

Registered in `sync_routes.py`. Signature mirrors existing topic-detail endpoints (pure GET, reads only, no lock).

### 2.5 Frontend — hub page

`TopicPipelineDashboard.tsx` layout:

- Sticky header: breadcrumb (book → chapter → topic), prev/next topic stubs (wired in Phase 3), super-button placeholder that says "Coming soon" (wired in Phase 2).
- Body: 6 `<StageLadderRow>` components in DAG order.

`StageLadderRow.tsx` responsibilities:
- Render status icon (`✓` / `⚠` / `🔄` / `⏳` / `🔒` / `✕`) per `state`.
- Render one-line summary + warnings.
- Render **[Open stage page →]** button that deep-links to the existing per-stage admin page with the topic pre-selected via URL hash or query param (`?topic_key=<key>` — existing pages already read `chapter_id` from path; topic-key as query is a small addition on each page during Phase 1, or the stage page can ignore it and just show the chapter view).

**Decision:** for Phase 1, "Open stage page" navigates to the existing chapter-scoped per-stage page without pre-filtering. This avoids any per-stage page changes in Phase 1. Topic pre-selection is a Phase 3 polish item if admins ask for it.

Route: `books-v2/:bookId/pipeline/:chapterId/:topicKey` — matches the flat existing pattern (`books-v2/:bookId/explanations/:chapterId`).

### 2.6 Smart polling hook

```ts
// useTopicPipeline.ts
export function useTopicPipeline(bookId, chapterId, topicKey) {
  const [data, setData] = useState<TopicPipelineStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let active = true;
    let timer: number | null = null;

    async function tick() {
      try {
        const next = await getTopicPipeline(bookId, chapterId, topicKey);
        if (!active) return;
        setData(next);
        const anyRunning = next.stages.some(s => s.state === "running");
        timer = window.setTimeout(tick, anyRunning ? 3000 : /* idle */ 0 && null);
        if (!anyRunning && timer === null) return; // stop polling
      } catch (e) {
        if (active) setError(e as Error);
      }
    }

    tick();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [bookId, chapterId, topicKey]);

  return { data, error, refresh: /* manual trigger */ };
}
```

Final shape: fetch on mount, re-fetch every 3s **only while `anyRunning`**, stop when all settled. Expose a manual `refresh()` that the hub can call after admin actions.

### 2.7 BookV2Detail patch

Add a small "Pipeline →" link next to each topic row (topic list rendered around line 1319 today). Link `to`:

```tsx
<Link to={`/admin/books-v2/${bookId}/pipeline/${ch.id}/${topic.topic_key}`}>
  Pipeline →
</Link>
```

### 2.8 Phase 1 testing plan

| Test | Verifies |
|---|---|
| Unit: `test_topic_pipeline_status_fresh_topic` | Topic with no artifacts → ①=ready, ②–⑥=blocked |
| Unit: `test_topic_pipeline_status_full_done` | Every artifact present, no warnings → all stages `done` |
| Unit: `test_topic_pipeline_status_layout_warning` | `layout_warning=true` on one card → ② state `warning` |
| Unit: `test_topic_pipeline_status_partial_practice` | 15 practice questions → ④ state `warning` |
| Unit: `test_topic_pipeline_status_stale_practice` | `practice_questions.created_at < topic_explanations.updated_at` → `is_stale=true`, state `warning` |
| Unit: `test_topic_pipeline_status_running_stage` | Latest explanation job `running` → ① state `running` |
| Unit: `test_topic_pipeline_status_failed_stage` | Latest visual job `failed` → ② state `failed`, error populated |
| Integration: GET `/pipeline` on a seeded topic returns the expected response | End-to-end JSON shape |
| Manual: navigate from `BookV2Detail` → topic → Pipeline → back to each per-stage page | Link wiring works |
| Manual: run a stage from per-stage page, hub shows `running` within 3s | Polling wiring works |

**Phase 1 exit criteria:** hub renders status for a fully populated topic, reflects state changes from per-stage pages within one poll tick, and `BookV2Detail` links to it. No super-button.

---

## 3. Phase 2 — Super-Button + Lock Refactor + Staleness

### 3.1 Files changed

#### Backend

| File | Change |
|---|---|
| `llm-backend/book_ingestion_v2/models/database.py` | **Add column** `guideline_id: Column(String, nullable=True)` to `ChapterProcessingJob`; **update index** `idx_chapter_active_job` to split into two partial indexes (see 3.2) |
| `llm-backend/db.py` (or migration file) | **NEW migration** — ADD COLUMN + index changes |
| `llm-backend/book_ingestion_v2/services/chapter_job_service.py` | **Refactor** `acquire_lock` to accept `guideline_id: Optional[str]` and enforce chapter/per-topic locks |
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | **Thread `guideline_id` through** all post-sync `acquire_lock` call sites; **NEW endpoint** `POST /chapters/{chapter_id}/topics/{topic_key}/run-pipeline` |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py` | **NEW** — per-topic DAG runner |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py` | **Extend** — returns `pipeline_run_id` if one is in-flight; surface staleness based on `updated_at` of `topic_explanations` vs. `practice_questions.created_at` and `chapter_processing_jobs.completed_at` for audio review |
| `llm-backend/tests/unit/test_topic_pipeline_orchestrator.py` | **NEW** |
| `llm-backend/tests/unit/test_chapter_job_service_scoped_lock.py` | **NEW** — covers new lock semantics |

#### Frontend

| File | Change |
|---|---|
| `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` | **Wire super-button** — Quality popover + POST call + optimistic state flip |
| `llm-frontend/src/features/admin/components/QualitySelector.tsx` | **NEW** — small 3-option selector |
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | **Add** `runTopicPipeline`, `TopicPipelineRunRequest` type |

### 3.2 DB migration

```sql
-- UP
ALTER TABLE chapter_processing_jobs
  ADD COLUMN guideline_id VARCHAR NULL;

-- Existing rows have guideline_id = NULL which is fine:
--   chapter-level jobs legitimately have NULL (OCR, extraction, finalization, refresher)
--   post-sync jobs written BEFORE this migration also carry NULL — treated as pre-migration
--   (they are terminal anyway; no active rows).

DROP INDEX IF EXISTS idx_chapter_active_job;

-- One active chapter-level job per chapter (guideline_id IS NULL):
CREATE UNIQUE INDEX idx_chapter_active_chapter_job
  ON chapter_processing_jobs (chapter_id)
  WHERE status IN ('pending', 'running') AND guideline_id IS NULL;

-- One active topic-level job per (chapter, guideline):
CREATE UNIQUE INDEX idx_chapter_active_topic_job
  ON chapter_processing_jobs (chapter_id, guideline_id)
  WHERE status IN ('pending', 'running') AND guideline_id IS NOT NULL;
```

**Decision:** two partial unique indexes instead of one COALESCE-based index. Simpler semantics and DB can enforce both invariants independently.

**Backfill:** none. Historical jobs with NULL `guideline_id` are terminal; new post-sync jobs will populate the column.

### 3.3 Lock refactor — `ChapterJobService.acquire_lock`

```python
_POST_SYNC_JOB_TYPES = {
    V2JobType.EXPLANATION_GENERATION.value,
    V2JobType.VISUAL_ENRICHMENT.value,
    V2JobType.CHECK_IN_ENRICHMENT.value,
    V2JobType.PRACTICE_BANK_GENERATION.value,
    V2JobType.AUDIO_TEXT_REVIEW.value,
    V2JobType.AUDIO_GENERATION.value,
}

def acquire_lock(
    self,
    book_id: str,
    chapter_id: str,
    job_type: str,
    total_items: int | None = None,
    guideline_id: str | None = None,
) -> str:
    is_post_sync = job_type in _POST_SYNC_JOB_TYPES

    if is_post_sync and guideline_id is None:
        raise ChapterJobLockError(
            f"Post-sync job {job_type} requires guideline_id"
        )
    if not is_post_sync and guideline_id is not None:
        # Chapter-level jobs must have NULL guideline_id — enforced by index.
        guideline_id = None

    # Application-level checks (DB unique indexes are the backstop):
    # 1. For a post-sync job, ensure no active chapter-level job exists for this chapter.
    if is_post_sync:
        active_chapter_job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.guideline_id.is_(None),
            ChapterProcessingJob.status.in_(["pending", "running"]),
        ).first()
        if active_chapter_job and not self._is_stale_or_abandoned(active_chapter_job):
            raise ChapterJobLockError(
                f"Chapter-level job {active_chapter_job.job_type} is active; "
                f"cannot start {job_type} for guideline {guideline_id}"
            )

    # 2. For a chapter-level job, ensure no active post-sync jobs for any guideline in this chapter.
    if not is_post_sync:
        active_topic_jobs = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.guideline_id.isnot(None),
            ChapterProcessingJob.status.in_(["pending", "running"]),
        ).all()
        live = [j for j in active_topic_jobs if not self._is_stale_or_abandoned(j)]
        if live:
            raise ChapterJobLockError(
                f"{len(live)} post-sync job(s) active in chapter; "
                f"cannot start chapter-level {job_type}"
            )

    # 3. Existing duplicate-key check for same-scope job, with stale auto-recovery.
    existing = self.db.query(ChapterProcessingJob).filter(
        ChapterProcessingJob.chapter_id == chapter_id,
        ChapterProcessingJob.guideline_id == guideline_id,
        ChapterProcessingJob.status.in_(["pending", "running"]),
    ).first()
    if existing:
        if existing.status == "running" and self._is_stale(existing):
            self._mark_stale(existing)
        elif existing.status == "pending" and self._is_pending_stale(existing):
            self._mark_pending_abandoned(existing)
        else:
            raise ChapterJobLockError(
                f"Job already {existing.status} for "
                f"chapter {chapter_id} guideline {guideline_id}: {existing.job_type}"
            )

    job = ChapterProcessingJob(
        id=str(uuid.uuid4()),
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=job_type,
        status="pending",
        total_items=total_items,
    )
    try:
        self.db.add(job)
        self.db.commit()
        return job.id
    except IntegrityError:
        self.db.rollback()
        raise ChapterJobLockError(
            f"Another job was just created for chapter {chapter_id} guideline {guideline_id}"
        )
```

**Decision:** chapter-level and post-sync jobs are mutually exclusive within a chapter (reader-writer style). This preserves safety of `teaching_guidelines` rewrites during sync/finalization while unlocking per-topic parallelism.

**All existing call sites of `acquire_lock` in `sync_routes.py` must pass `guideline_id`.** These are in `generate_explanations`, `generate_visuals`, `generate_check_ins`, `generate_practice_banks`, `generate_audio_review`, `generate_audio`. Each route already resolves a `guideline_id` from request params; threading it to the service is a mechanical change.

### 3.4 New service: `TopicPipelineOrchestrator`

Lives at `book_ingestion_v2/services/topic_pipeline_orchestrator.py`. Responsibilities:

- Compute the set of stages to run for one topic (based on current status).
- Run them in DAG order: `① → (② ∥ ③ ∥ ④) → ⑤ → ⑥`.
- Hard-stop on any stage failure; downstream stages stay untouched.
- Return a `pipeline_run_id` (not the same as individual job IDs — a synthetic ID that ties the whole run together for logging/observability).

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

_QUALITY_ROUNDS = {
    "fast":      {"explanations": 0, "visuals": 0, "check_ins": 0, "practice_bank": 0},
    "balanced":  {"explanations": 2, "visuals": 1, "check_ins": 1, "practice_bank": 2},
    "thorough":  {"explanations": 3, "visuals": 2, "check_ins": 2, "practice_bank": 3},
}

# DAG layers — each layer runs serially; items within a layer run in parallel.
_LAYERS: list[list[str]] = [
    ["explanations"],
    ["visuals", "check_ins", "practice_bank"],
    ["audio_review"],
    ["audio_synthesis"],
]

class TopicPipelineOrchestrator:
    def __init__(self, db_session_factory, book_id, chapter_id, guideline_id, quality_level):
        self._session_factory = db_session_factory
        self.book_id = book_id
        self.chapter_id = chapter_id
        self.guideline_id = guideline_id
        self.rounds = _QUALITY_ROUNDS[quality_level]
        self.pipeline_run_id = str(uuid.uuid4())

    def run(self, initial_status: TopicPipelineStatusResponse) -> None:
        stages_needed = self._decide_stages(initial_status)
        for layer in _LAYERS:
            layer_stages = [s for s in layer if s in stages_needed]
            if not layer_stages:
                continue
            with ThreadPoolExecutor(max_workers=len(layer_stages)) as ex:
                futs = {ex.submit(self._run_stage, s): s for s in layer_stages}
                results = {}
                for fut in as_completed(futs):
                    stage = futs[fut]
                    results[stage] = fut.result()  # may raise
            if any(r == "failed" for r in results.values()):
                logger.warning(f"Pipeline {self.pipeline_run_id} halted at layer {layer}")
                return
```

**Decision on parallelism within a layer:** use `ThreadPoolExecutor`. Each sub-stage fans out to its own daemon thread (reuses `run_in_background_v2`). Orchestrator thread `joins` on each by polling the per-stage `ChapterJobService.get_latest_job` until a terminal state is reached.

**Decision on stage invocation:** the orchestrator calls the same internal `_run_*` helpers that `sync_routes.py` already uses (`_run_explanation_generation`, `_run_visual_enrichment`, `_run_check_in_enrichment`, `_run_practice_bank_generation`, `_run_audio_text_review`, `_run_audio_generation`). These are already defined inside `sync_routes.py` — move them into a new module `book_ingestion_v2/services/stage_runners.py` that both the routes and the orchestrator import, to avoid the orchestrator importing from `api/`.

### 3.5 New endpoint: per-topic run-pipeline

```
POST /admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/run-pipeline
Body: {
  "quality_level": "fast" | "balanced" | "thorough",
  "force": false,            # if true, regenerate even Done stages
  "confirm_skip_review": false   # forwarded to ⑥ stage when ⑤ not done
}
Response 202: { "pipeline_run_id": "uuid", "stages_to_run": ["explanations", "visuals", ...] }
Response 409: { "detail": "pipeline_already_running_for_topic", "pipeline_run_id": "existing" }
```

Route handler:
1. Load topic + guideline.
2. Call `TopicPipelineStatusService.get_pipeline_status` to snapshot current state.
3. Construct `TopicPipelineOrchestrator` and compute `stages_needed`.
4. If empty and not `force`, return 200 with message "nothing to do".
5. Launch `orchestrator.run(initial_status)` via `threading.Thread(daemon=True)`.
6. Return 202 with `pipeline_run_id` and planned stages.

**Decision:** the orchestrator itself does NOT hold a lock — each sub-stage acquires its own per-stage lock. This means a second super-button press against a topic whose stages are already running will fail per-stage (409 from `acquire_lock`) rather than at the orchestrator boundary. Simpler, and matches the behavior admins already expect.

### 3.6 Staleness — status service extension

Straightforward timestamp comparisons in `TopicPipelineStatusService`:

```python
def _stage_practice_bank(self, guideline_id, exp_updated_at):
    rows = self.db.query(PracticeQuestion).filter(
        PracticeQuestion.guideline_id == guideline_id
    ).all()
    count = len(rows)
    created_at = min((r.created_at for r in rows), default=None)  # any row built after latest exp update?
    is_stale = (
        exp_updated_at is not None
        and created_at is not None
        and created_at < exp_updated_at
    )
    ...
```

For ⑤ Audio review, query the latest `v2_audio_text_review` job for this `(chapter_id, guideline_id)` and compare `job.completed_at < exp_updated_at`.

### 3.7 Phase 2 testing plan

| Test | Verifies |
|---|---|
| Unit: `test_acquire_lock_requires_guideline_for_post_sync` | Passing a post-sync job_type without guideline_id → `ChapterJobLockError` |
| Unit: `test_acquire_lock_allows_two_topic_jobs_same_chapter` | Two post-sync jobs with different guideline_ids → both acquire successfully |
| Unit: `test_acquire_lock_blocks_second_job_same_topic` | Two post-sync jobs with same `(chapter_id, guideline_id)` → second raises |
| Unit: `test_acquire_lock_chapter_level_blocks_topic_level` | Chapter-level job active → topic-level `acquire_lock` raises |
| Unit: `test_acquire_lock_topic_level_blocks_chapter_level` | Topic-level job active → chapter-level `acquire_lock` raises |
| Unit: `test_orchestrator_skips_done_stages` | Topic with explanations done, visuals not → orchestrator only runs ② |
| Unit: `test_orchestrator_runs_parallel_layer` | Given ②③④ needed, three daemon threads start |
| Unit: `test_orchestrator_halts_on_failure` | Layer ② fails → ⑤⑥ not started |
| Unit: `test_staleness_practice_bank` | `practice_questions.created_at < topic_explanations.updated_at` → stale=true |
| Integration: super-button on a fresh topic runs all 6 stages in order | End-to-end |
| Integration: two topics in same chapter both run in parallel | Lock refactor works end-to-end |
| Manual: regenerate explanations → hub shows ④ as stale within one poll tick | Staleness UI |

**Phase 2 exit criteria:** super-button runs a full pipeline for one topic. Two topics in one chapter run concurrently without lock errors. Staleness badge appears on ④ when admin regenerates ①.

---

## 4. Phase 3 — Chapter-Level Runner + Polish

### 4.1 Files changed

#### Backend

| File | Change |
|---|---|
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | **NEW endpoint** `POST /chapters/{chapter_id}/run-pipeline-all` |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py` | **Add** `run_chapter_all` helper — spawns one `TopicPipelineOrchestrator` per topic with bounded concurrency |
| `llm-backend/config.py` (or env) | **Add** `TOPIC_PIPELINE_MAX_PARALLEL_TOPICS = 4` |

#### Frontend

| File | Change |
|---|---|
| `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | **Add** topic summary chip + "Run pipeline for all topics" button per chapter |
| `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` | **Add** prev/next topic nav, inline error summary, [Retry] buttons on Failed rows |
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | **Add** `runChapterPipelineAll`, `getChapterTopicStatusSummary` |

### 4.2 Chapter-level runner endpoint

```
POST /admin/v2/books/{book_id}/chapters/{chapter_id}/run-pipeline-all
Body: {
  "quality_level": "fast" | "balanced" | "thorough",
  "skip_done": true,            # default — skip topics already fully Done
  "max_parallel": 4             # optional override of the env default
}
Response 202: { "chapter_run_id": "uuid", "topics_queued": 12 }
```

Route handler:
1. Load all topics for the chapter.
2. For each topic, call `TopicPipelineStatusService.get_pipeline_status` (cheap read).
3. Skip topics where every stage is `done` (if `skip_done`).
4. Hand the list to `run_chapter_all`, which uses `ThreadPoolExecutor(max_workers=max_parallel)` and submits a `TopicPipelineOrchestrator.run()` per topic.
5. Return 202 with the queue size.

**Decision:** bounded parallelism (default 4) to avoid saturating the Claude Code subprocess. Tunable per request; env-default lets ops raise/lower without deploys.

**Failure mode:** one topic's pipeline failing does NOT halt the chapter runner — other topics continue. This matches PRD (other topics' state surfaces on the chapter summary chip).

### 4.3 Chapter summary chip (frontend)

`BookV2Detail.tsx` gains, per chapter row:

```tsx
<TopicSummaryChip bookId={bookId} chapterId={ch.id} />
```

Internally calls `getChapterTopicStatusSummary(bookId, chapterId)` which aggregates per-topic states. For Phase 3, this can be client-side: iterate topics and fetch `/pipeline` for each (concurrently via `Promise.all`). If that proves slow, a backend aggregation endpoint can be added — but defer until measured.

Button next to chip:

```tsx
<button onClick={() => setShowQualityPopover(true)}>
  ▶ Run pipeline for all topics
</button>
```

Opens the `QualitySelector` popover; on confirm, POSTs `run-pipeline-all` and polls for chapter-level status until all topics settle.

### 4.4 Prev/next topic nav

In `TopicPipelineDashboard.tsx`:

- Fetch all topics for the chapter once (new endpoint or reuse `GET /chapters/{chapter_id}/topics`).
- Render `← Prev topic` and `Next topic →` buttons that navigate via `useNavigate()`.
- Disable at list boundaries.

### 4.5 Inline error + retry

On a Failed stage row:

```tsx
<div className="text-red-700">
  ✕ Failed: {stage.last_job_error}
  <span className="text-xs text-gray-500"> · {formatRelative(stage.last_job_completed_at)}</span>
</div>
<button onClick={() => retryStage(stage.stage_id)}>Retry</button>
```

`retryStage` calls the existing per-stage `POST /generate-<stage>?guideline_id=X&force=true` with `review_rounds` from the current Quality setting.

### 4.6 Phase 3 testing plan

| Test | Verifies |
|---|---|
| Unit: `test_run_chapter_all_bounded_parallelism` | 10 topics, `max_parallel=4` → at most 4 active orchestrators at any time |
| Unit: `test_run_chapter_all_skip_done` | Topics fully Done are skipped when `skip_done=true` |
| Unit: `test_run_chapter_all_topic_failure_does_not_halt_others` | One topic's pipeline fails; others complete |
| Integration: chapter with 10 topics completes via `run-pipeline-all` in <(wall clock of 10 sequential runs) / 2 | Parallelism gain is real |
| Manual: click super-button, navigate to next topic before settling | No polling leak, hub correctly reflects the new topic |
| Manual: Failed stage → click Retry → stage re-runs without affecting other stages | Retry wiring |

**Phase 3 exit criteria:** chapter-level runner completes a chapter of 10 topics in parallel. Prev/next navigation works. Failed stages show inline errors and can be retried.

---

## 5. Implementation Order (per phase)

### Phase 1 sequence

| # | Step | Files | Depends on |
|---|---|---|---|
| 1 | Schemas for the new GET response | `models/schemas.py` | — |
| 2 | `TopicPipelineStatusService` with unit tests | `services/topic_pipeline_status_service.py`, tests | 1 |
| 3 | GET endpoint in `sync_routes.py` | `api/sync_routes.py` | 2 |
| 4 | Admin API client types + `getTopicPipeline` | `adminApiV2.ts` | 3 |
| 5 | `StageLadderRow` component | `StageLadderRow.tsx` | 4 |
| 6 | `useTopicPipeline` hook | `useTopicPipeline.ts` | 4 |
| 7 | `TopicPipelineDashboard` page | `TopicPipelineDashboard.tsx` | 5, 6 |
| 8 | Route wiring in `App.tsx` | `App.tsx` | 7 |
| 9 | `BookV2Detail` per-topic link | `BookV2Detail.tsx` | 8 |
| 10 | Manual QA + docs | — | 9 |

### Phase 2 sequence

| # | Step | Files | Depends on |
|---|---|---|---|
| 1 | DB migration (add column, split indexes) | `database.py` migration file | — |
| 2 | Model update: add `guideline_id` to `ChapterProcessingJob` | `models/database.py` | 1 |
| 3 | `ChapterJobService.acquire_lock` refactor + tests | `chapter_job_service.py`, tests | 2 |
| 4 | Thread `guideline_id` through existing `acquire_lock` call sites in `sync_routes.py` | `sync_routes.py` | 3 |
| 5 | Extract `_run_*` helpers from `sync_routes.py` to `stage_runners.py` | new module + imports | 4 |
| 6 | `TopicPipelineOrchestrator` service + tests | `topic_pipeline_orchestrator.py`, tests | 5 |
| 7 | Staleness computation in `TopicPipelineStatusService` | `topic_pipeline_status_service.py` | 2 |
| 8 | POST `/run-pipeline` endpoint | `sync_routes.py` | 6 |
| 9 | `QualitySelector` component | `QualitySelector.tsx` | — |
| 10 | Wire super-button in `TopicPipelineDashboard` | `TopicPipelineDashboard.tsx` | 8, 9 |
| 11 | Manual QA + docs | — | 10 |

### Phase 3 sequence

| # | Step | Files | Depends on |
|---|---|---|---|
| 1 | `run_chapter_all` helper on orchestrator + tests | `topic_pipeline_orchestrator.py` | Phase 2 |
| 2 | POST `/run-pipeline-all` endpoint | `sync_routes.py` | 1 |
| 3 | Chapter topic summary chip in `BookV2Detail` | `BookV2Detail.tsx` | — |
| 4 | "Run for all topics" button + popover | `BookV2Detail.tsx` | 2, 3 |
| 5 | Prev/next topic nav in dashboard | `TopicPipelineDashboard.tsx` | — |
| 6 | Inline error + [Retry] on Failed rows | `StageLadderRow.tsx` | — |
| 7 | Polling edge-case hardening (tab-backgrounding, unmount cleanup) | `useTopicPipeline.ts` | — |
| 8 | Manual QA + docs | — | 7 |

---

## 6. Data Model Summary

| Table | Change |
|---|---|
| `chapter_processing_jobs` | ADD COLUMN `guideline_id VARCHAR NULL`; split `idx_chapter_active_job` into two partial unique indexes (chapter-level jobs + topic-level jobs) |

No other schema changes. All other persistence uses existing JSONB columns.

---

## 7. API Summary

| Method | Path | Phase | Purpose |
|---|---|---|---|
| GET | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/pipeline` | 1 | Consolidated per-topic status |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/run-pipeline` | 2 | Super-button orchestration |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/run-pipeline-all` | 3 | Chapter-level runner |

No changes to existing endpoints' request/response shapes. Existing per-stage `POST /generate-*` calls get `guideline_id` threaded into their `acquire_lock` calls (internal change only).

---

## 8. Configuration & Environment

| Variable | Purpose | Default | Phase |
|---|---|---|---|
| `TOPIC_PIPELINE_MAX_PARALLEL_TOPICS` | Cap on concurrent topics in `run-pipeline-all` | `4` | 3 |

Quality-rounds mapping is a constant in code (`_QUALITY_ROUNDS` in orchestrator). Tuning requires a deploy but not a config change. If that becomes painful, promote to config later.

---

## 9. Deployment Considerations

- **Phase 1**: pure additive — new endpoint, new frontend route. No migration. Deploy any time.
- **Phase 2**: requires the DB migration to land before the refactor deploys. Recommended sequence: (1) deploy migration alone; (2) deploy backend with `acquire_lock` refactor; (3) deploy frontend with super-button.
- **Phase 3**: pure additive — new endpoints, new frontend UI. Deploy any time after Phase 2.

**Rollback:**
- Phase 1 — revert frontend + revert new endpoint. No data impact.
- Phase 2 — revert the refactor in `acquire_lock` to treat post-sync stages with chapter-wide lock; the `guideline_id` column stays (harmless). Revert the split indexes to the original single index (or leave both — the chapter-level index still enforces single chapter-wide job for any status).
- Phase 3 — revert frontend + revert `/run-pipeline-all`. No data impact.

---

## 10. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Lock refactor mis-handles a chapter-level + topic-level race | Medium | High (corrupt guidelines) | Reader-writer pattern enforced at application AND index level; unit tests cover all four combinations |
| Orchestrator leaks daemon threads when super-button page is closed | Low | Medium (orphan work) | Daemon threads complete regardless of HTTP client; existing `run_in_background_v2` already handles this |
| Chapter-level runner saturates Claude Code subprocess | Medium | Medium (rate-limit errors) | `TOPIC_PIPELINE_MAX_PARALLEL_TOPICS` default 4; existing Claude Code adapter retries on rate limit |
| Staleness detection over-flags freshly refined artifacts | Low | Low (UI noise) | `updated_at` only advances when the row is written, not on read; refine-only mode writes → new timestamp → downstream correctly flagged stale |
| Orchestrator's per-stage status polling misses a fast failure | Low | Low (pipeline keeps going when it should halt) | Poll interval ≤5s; per-stage job always transitions to terminal state even on fast failure |
| Extracting `_run_*` helpers out of `sync_routes.py` breaks existing routes | Low | High (regression) | One refactor commit, exhaustive manual QA of each per-stage route before the orchestrator is wired |
| Two admins click super-button on same topic | Low | Low | Per-stage lock returns 409 on the second click; UI shows it |

---

## 11. Open Questions

- **Pipeline run records:** should we persist `pipeline_run_id` rows to a new table for full observability, or rely on each sub-stage's `chapter_processing_jobs` row (with the `pipeline_run_id` tagged in `progress_detail`)? **Decision for v1:** tag in `progress_detail` JSON; no new table. Revisit if admins ask for a pipeline-run history view.
- **Topic pre-selection on per-stage admin pages:** whether "Open stage page →" should auto-scroll/highlight the current topic. **Decision for v1:** no; link lands on the chapter-scoped page as-is. Phase 3 polish if demanded.
- **Staleness threshold:** should there be a small grace period (e.g., 60s) so stale doesn't flash during the window between "regenerate explanations" and "downstream auto-wipe"? **Decision for v1:** no grace period; the flash is informative.

---

## 12. References

- PRD: `docs/feature-development/topic-pipeline-dashboard/PRD.md`
- Pipeline principles: `docs/principles/book-ingestion-pipeline.md`
- Job service: `llm-backend/book_ingestion_v2/services/chapter_job_service.py`
- Background pattern: `llm-backend/book_ingestion_v2/api/processing_routes.py:438`
- Existing per-stage endpoints: `llm-backend/book_ingestion_v2/api/sync_routes.py`
- Admin router: `llm-frontend/src/App.tsx`
- Admin API client: `llm-frontend/src/features/admin/api/adminApiV2.ts`
