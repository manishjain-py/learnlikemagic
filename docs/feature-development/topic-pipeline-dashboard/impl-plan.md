# Tech Implementation Plan: Topic Pipeline Dashboard

**PRD:** `docs/feature-development/topic-pipeline-dashboard/PRD.md`
**Review:** `docs/feature-development/topic-pipeline-dashboard/impl-plan-review.md` (v1 review applied — all Tier 1/2/3 items addressed)

**Patterns mirrored from:**
- `ExplanationGeneratorService` + route pattern (`llm-backend/book_ingestion_v2/services/explanation_generator_service.py`, `api/sync_routes.py:117`)
- Background job pattern (`llm-backend/book_ingestion_v2/api/processing_routes.py:438 run_in_background_v2`)
- Job service (`llm-backend/book_ingestion_v2/services/chapter_job_service.py`)
- Existing per-stage admin pages (`llm-frontend/src/features/admin/pages/ExplanationAdmin.tsx`, `VisualsAdmin.tsx`, etc.)
- Admin API client (`llm-frontend/src/features/admin/api/adminApiV2.ts`)

---

## 1. Overview

A topic-scoped admin hub + an optional chapter-level runner. No new student-facing surfaces. Shipped in 3 phases:

- **Phase 1** — Read-only hub + consolidated GET endpoint. No DB changes, no write-path risk.
- **Phase 2** — Super-button orchestration + `ChapterJobService` data-model cleanup + staleness tracking. Requires a DB migration and a call-site audit.
- **Phase 3** — Chapter-level runner + aggregate summary endpoint + prev/next nav + inline error UX.

Each phase is independently shippable and rollbackable.

### A critical clarification about the current system

Two topics in the same chapter **already run concurrently today**. Every post-sync route in `sync_routes.py` does `lock_chapter_id = guideline_id` and passes that into `acquire_lock` as the `chapter_id` — for example `sync_routes.py:150` for explanation generation. The `chapter_processing_jobs.chapter_id` column is overloaded — for post-sync jobs it stores a guideline UUID, not a real chapter UUID.

**Phase 2's refactor is about correctness and data-model hygiene, not unlocking parallelism.** Today's column overloading:
- Breaks FK integrity (a "chapter_id" that's actually a guideline_id).
- Makes status queries ambiguous ("latest job for chapter X" silently surfaces topic-level jobs as chapter-level ones).
- Entangles chapter-level vs topic-level locking invariants — nothing prevents a chapter-level stage (OCR, finalization) from starting while per-topic jobs are mid-flight on the same chapter, because their lock rows appear under different `chapter_id` values.

Phase 2 gives every post-sync job its own proper `guideline_id` column, keeps `chapter_id` honest, and puts a reader-writer relationship between chapter-level and topic-level locks.

### Dataflow (end state)

```
admin → topic pipeline hub
      → POST /.../topics/{topic_key}/run-pipeline { quality_level }
      → TopicPipelineOrchestrator picks stages not Done
      → For each layer in [①] → [②, ③, ④] → [⑤] → [⑥]:
          - For each stage in layer (parallel within layer):
              job_id = launch_<stage>_job(db, book_id, chapter_id, guideline_id, rounds, force)
              # launcher owns acquire_lock + run_in_background_v2 + start_job
          - Poll ChapterJobService.get_job(job_id) until terminal for every stage in layer
          - If any failed: halt; do not proceed to next layer
      → pipeline_run_id tagged in each stage job's progress_detail for observability
```

No new LLM prompts, no new agents, one DB column added. Persistence for visuals/check-ins/audio_url stays in the existing `cards_json` JSONB.

---

## 2. Phase 1 — Read-Only Hub

### 2.1 Files changed

#### Backend

| File | Change |
|---|---|
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | **NEW endpoint** — `GET /chapters/{chapter_id}/topics/{topic_key}/pipeline` |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py` | **NEW** — consolidated status computation for one topic |
| `llm-backend/book_ingestion_v2/models/schemas.py` | **NEW schemas** — `TopicPipelineStatusResponse`, `StageStatus`, `StageStateLiteral` (all Pydantic `BaseModel`) |
| `llm-backend/tests/unit/test_topic_pipeline_status.py` | **NEW** — unit tests |

#### Frontend

| File | Change |
|---|---|
| `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` | **NEW** — hub page |
| `llm-frontend/src/features/admin/components/StageLadderRow.tsx` | **NEW** — one ladder row; status badge, summary, deep link |
| `llm-frontend/src/features/admin/hooks/useTopicPipeline.ts` | **NEW** — fetch + smart polling hook |
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | **Add** `getTopicPipeline`, types `TopicPipelineStatus`, `StageStatus` |
| `llm-frontend/src/App.tsx` | **Add route** `books-v2/:bookId/pipeline/:chapterId/:topicKey` |
| `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | **Add** per-topic "Pipeline →" link in each chapter's topic list |

#### Docs

| File | Change |
|---|---|
| `docs/technical/book-guidelines.md` | Add "Topic Pipeline Dashboard" subsection with endpoint + route + status rules |

### 2.2 New service: `topic_pipeline_status_service.py`

Reads the data needed to compute 6-stage status for one topic and returns it in one response. Consolidates queries spread today across `get_explanation_status`, `get_visual_status`, `get_check_in_status`, `get_practice_bank_status`, and two latest-job endpoints.

```python
"""Compute per-topic pipeline status for the admin hub."""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.models.database import ChapterProcessingJob
from shared.models.entities import TeachingGuideline, TopicExplanation, PracticeQuestion

StageId = Literal["explanations", "visuals", "check_ins", "practice_bank", "audio_review", "audio_synthesis"]
StageState = Literal["done", "warning", "running", "ready", "blocked", "failed"]


class StageStatus(BaseModel):
    stage_id: StageId
    state: StageState
    summary: str
    warnings: list[str] = []
    blocked_by: Optional[StageId] = None
    is_stale: bool = False
    last_job_id: Optional[str] = None
    last_job_status: Optional[str] = None
    last_job_error: Optional[str] = None
    last_job_completed_at: Optional[datetime] = None


class TopicPipelineStatusResponse(BaseModel):
    topic_key: str
    topic_title: str
    guideline_id: str
    chapter_id: str
    chapter_preflight_ok: bool
    pipeline_run_id: Optional[str] = None  # populated if a pipeline run is in-flight (Phase 2+)
    stages: list[StageStatus]


# _POST_SYNC_JOB_TYPES — used by status service to handle historical row quirk
_POST_SYNC_JOB_TYPES = {
    V2JobType.EXPLANATION_GENERATION.value,
    V2JobType.VISUAL_ENRICHMENT.value,
    V2JobType.CHECK_IN_ENRICHMENT.value,
    V2JobType.PRACTICE_BANK_GENERATION.value,
    V2JobType.AUDIO_TEXT_REVIEW.value,
    V2JobType.AUDIO_GENERATION.value,
}


class TopicPipelineStatusService:
    def __init__(self, db: Session):
        self.db = db

    def get_pipeline_status(
        self, book_id: str, chapter_id: str, topic_key: str
    ) -> TopicPipelineStatusResponse:
        guideline = self._load_guideline(book_id, chapter_id, topic_key)
        if not guideline:
            raise LookupError(f"No teaching_guideline for {chapter_id}/{topic_key}")

        explanations = self._load_explanations(guideline.id)
        content_anchor = self._content_anchor(explanations)
        stages = [
            self._stage_explanations(explanations, guideline.id),
            self._stage_visuals(explanations, guideline.id, content_anchor),
            self._stage_check_ins(explanations, guideline.id, content_anchor),
            self._stage_practice_bank(guideline.id, content_anchor),
            self._stage_audio_review(guideline.id, content_anchor),
            self._stage_audio_synthesis(explanations, guideline.id),
        ]
        return TopicPipelineStatusResponse(
            topic_key=topic_key,
            topic_title=guideline.topic_title,
            guideline_id=guideline.id,
            chapter_id=chapter_id,
            chapter_preflight_ok=True,
            stages=stages,
        )

    def _content_anchor(self, explanations: list[TopicExplanation]) -> Optional[datetime]:
        """Staleness anchor — latest explanation row's created_at.

        NOT `updated_at` because in-place writes during visuals / check-ins /
        audio synthesis advance `updated_at` without being semantic invalidations.
        Explanation regeneration does delete+insert (sync_routes.py:939), so
        `created_at` only moves forward on actual content regen.
        """
        return max((e.created_at for e in explanations), default=None)

    def _latest_job_for_guideline(
        self, chapter_id: str, guideline_id: str, job_type: str
    ) -> Optional[ChapterProcessingJob]:
        """Find the latest job for a topic.

        Phase 1: handles the historical `chapter_id-holds-guideline_id` overload.
        Post-Phase-2: this method simplifies to query `guideline_id` directly.
        """
        # Phase 1 query path: for post-sync job types, historical rows have
        # chapter_id = guideline_id (column was overloaded).
        if job_type in _POST_SYNC_JOB_TYPES:
            return self.db.query(ChapterProcessingJob).filter(
                ChapterProcessingJob.chapter_id == guideline_id,
                ChapterProcessingJob.job_type == job_type,
            ).order_by(ChapterProcessingJob.created_at.desc()).first()

        # Chapter-level job types use the real chapter_id.
        return self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.job_type == job_type,
        ).order_by(ChapterProcessingJob.created_at.desc()).first()

    # One private method per stage — each reads only what it needs and returns StageStatus.
    # Rules enumerated in §2.3.
```

**Decision — staleness anchor:** `max(topic_explanations.created_at)` for this guideline. This is stable across in-place `cards_json` writes; only advances on explanation regeneration (which deletes + re-inserts rows). If a future "refine-in-place" explanation mode is added that updates rather than replaces rows, we'll introduce a dedicated `content_version` column then.

**Decision — historical-row handling (Phase 1):** the status service reads `chapter_processing_jobs` with awareness of the existing overload: for post-sync job types, `chapter_id` holds the guideline UUID. Method `_latest_job_for_guideline` handles the two query paths cleanly. Post-migration in Phase 2, this method simplifies to a native `guideline_id` query.

### 2.3 Stage-status computation rules (authoritative)

| Stage | Source data | `done` | `warning` | `ready` | `blocked` | `failed` |
|---|---|---|---|---|---|---|
| ① Explanations | `topic_explanations` rows where `guideline_id = X` | ≥1 variant with ≥1 card, last job terminal=completed | — | 0 variants, no in-flight job | never (requires preflight only) | latest explanation job for this guideline status=failed |
| ② Visuals | `topic_explanations.cards_json` cards | ≥1 card has `visual_explanation.pixi_code` AND no card has `layout_warning=true` | any card has `layout_warning=true` | 0 cards have `visual_explanation` | ① not done | latest visual job failed |
| ③ Check-ins | cards with `check_in` field in `cards_json` | ≥1 check-in card | — | 0 check-ins | ① not done | latest check-in job failed |
| ④ Practice bank | `practice_questions` rows for `guideline_id` | ≥30 rows AND not stale | 1–29 rows OR stale | 0 rows | ① not done | latest practice job failed |
| ⑤ Audio review | Latest `v2_audio_text_review` job for this guideline | Latest job `completed` AND not stale | Latest job `completed_with_errors` OR stale | No prior job; or last terminal=failed and newer run not started | ① not done | Latest job `failed` |
| ⑥ Audio synthesis | `audio_url` on every line of every card in `cards_json` | All lines have non-null `audio_url` | Mix of null / non-null | No `audio_url` on any line | ① not done | latest audio job failed |

**Stale:** `artifact_timestamp < content_anchor` where:
- Practice bank artifact_timestamp = `min(practice_questions.created_at for this guideline_id)` (stale means at least one row predates the latest explanation generation).
- Audio review artifact_timestamp = latest review job's `completed_at`.

**Phase 1 historical-rows note:** `_latest_job_for_guideline` treats historical post-sync job rows as topic-level (their `chapter_id` column holds a guideline_id). The chapter-level queries in the hub naturally won't surface them. Post-Phase-2, the query path flips to use the native `guideline_id` column — both paths are tested.

### 2.4 New endpoint

```
GET /admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/pipeline
Response 200: TopicPipelineStatusResponse
Response 404: {"detail": "Guideline not found for topic_key=..."}
```

Registered in `sync_routes.py`. Pure GET, no lock.

### 2.5 Frontend — hub page

`TopicPipelineDashboard.tsx` layout:

- Sticky header: breadcrumb, prev/next placeholders (wired in Phase 3), super-button placeholder ("Coming soon" — wired in Phase 2).
- Body: 6 `<StageLadderRow>` components in DAG order.

`StageLadderRow.tsx` renders: status icon, summary, warnings list, **[Open stage page →]** button that navigates to the existing per-stage admin page (chapter-scoped, no topic pre-selection in Phase 1 — Phase 3 polish if asked).

Route: `books-v2/:bookId/pipeline/:chapterId/:topicKey` — matches existing flat pattern.

**URL encoding note:** `topic_key` is slugified at extraction time (see `shared/models/entities.py:130` + topic extraction service) — lowercase-with-hyphens only — so it's path-safe and no URL encoding is needed.

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
        if (!anyRunning) return;              // stop polling when settled
        timer = window.setTimeout(tick, 3000);
      } catch (e) {
        if (active) setError(e as Error);
      }
    }

    tick();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [bookId, chapterId, topicKey]);

  return { data, error };
}
```

On initial fetch + every 3s **only while `anyRunning`**, stop when all settled. Clean early-return; no recursive timer leaks.

### 2.7 BookV2Detail patch

Add a "Pipeline →" link per topic in the existing topic list (rendered around line 1319 today):

```tsx
<Link to={`/admin/books-v2/${bookId}/pipeline/${ch.id}/${topic.topic_key}`}>
  Pipeline →
</Link>
```

### 2.8 Phase 1 testing plan

| Test | Verifies |
|---|---|
| Unit: `test_status_fresh_topic` | Topic with no artifacts → ①=ready, ②–⑥=blocked |
| Unit: `test_status_full_done` | Every artifact present, no warnings → all stages `done` |
| Unit: `test_status_layout_warning` | `layout_warning=true` on one card → ② `warning` |
| Unit: `test_status_partial_practice` | 15 practice questions → ④ `warning` |
| Unit: `test_status_stale_practice_via_content_anchor` | `min(practice_questions.created_at) < max(topic_explanations.created_at)` → ④ `is_stale=true` |
| Unit: `test_status_not_stale_on_inplace_cards_write` | Writing `cards_json` in-place (simulating visuals/audio runs) does NOT flip ④ stale | 
| Unit: `test_status_running_stage` | Latest explanation job `running` → ① `running` |
| Unit: `test_status_failed_stage` | Latest visual job `failed` → ② `failed`, `last_job_error` populated |
| Unit: `test_status_historical_row_overload` | Historical post-sync row with `chapter_id=guideline_id` is correctly attributed to the topic |
| Integration: GET `/pipeline` on a seeded topic | End-to-end JSON shape |
| Manual: navigate from `BookV2Detail` → topic → Pipeline → back to per-stage pages | Link wiring |
| Manual: run a stage from per-stage page → hub shows `running` within one poll tick | Polling wiring |

**Phase 1 exit criteria:** hub renders accurate status for a fully populated topic, correctly handles historical rows, reflects state changes within one poll tick, and does NOT flash "stale" when downstream jobs mutate `cards_json` in-place.

---

## 3. Phase 2 — Super-Button + Data-Model Cleanup + Staleness

### 3.1 Files changed

#### Backend

| File | Change |
|---|---|
| `llm-backend/book_ingestion_v2/models/database.py` | **Add column** `guideline_id: Column(String, nullable=True, index=True)` to `ChapterProcessingJob`; **replace index** `idx_chapter_active_job` with two partial unique indexes (see 3.2) |
| `llm-backend/db.py` (or migration runner) | **NEW migration** — ADD COLUMN + indexes + backfill |
| `llm-backend/book_ingestion_v2/services/chapter_job_service.py` | **Refactor** `acquire_lock` to accept `guideline_id: Optional[str]` with reader-writer semantics; **extend** `get_latest_job` with an optional `guideline_id` parameter |
| `llm-backend/book_ingestion_v2/services/stage_launchers.py` | **NEW** — one helper per post-sync stage: `launch_explanation_job`, `launch_visual_job`, `launch_check_in_job`, `launch_practice_bank_job`, `launch_audio_review_job`, `launch_audio_generation_job`. Each owns `acquire_lock` + `run_in_background_v2(_run_<stage>, job_id, ...)` and returns `job_id`. |
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | **Refactor** every post-sync route to call the new launcher. **Fan-out behavior** when `guideline_id` is not passed: the route resolves approved guidelines in scope and calls the launcher once per guideline. Route returns `{ launched: N, job_ids: [...] }`. |
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | **Update** all `get_latest_*_job` endpoints (explanations, audio-review, visuals, check-ins, practice-bank) to accept `guideline_id` and pass it to `get_latest_job`; update audio-synth soft-guardrail at `sync_routes.py:572-574` similarly |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py` | **NEW** — per-topic DAG runner; uses launchers + polls `get_job(job_id)` (NOT `get_latest_job`) for completion |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py` | **Update** `_latest_job_for_guideline` to use the native `guideline_id` column; drop the historical-overload branch (historical rows are backfilled in the migration) |
| `llm-backend/tests/unit/test_topic_pipeline_orchestrator.py` | **NEW** |
| `llm-backend/tests/unit/test_chapter_job_service_scoped_lock.py` | **NEW** — covers new lock semantics |
| `llm-backend/tests/unit/test_stage_launchers.py` | **NEW** |

#### Frontend

| File | Change |
|---|---|
| `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` | **Wire super-button** — Quality popover + POST + optimistic state flip |
| `llm-frontend/src/features/admin/components/QualitySelector.tsx` | **NEW** |
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | **Add** `runTopicPipeline`, type `TopicPipelineRunRequest`; update existing `generate-*` return types to `{ launched, job_ids[] }` where relevant |
| `llm-frontend/src/features/admin/pages/ExplanationAdmin.tsx`, `VisualsAdmin.tsx`, `CheckInAdmin.tsx`, `PracticeBankAdmin.tsx` | **Minor** — handle the new `{ launched, job_ids[] }` response; poll all returned job ids (or pick the first) |

### 3.2 DB migration (Phase 2)

```sql
-- UP
BEGIN;

-- 1. Add guideline_id column
ALTER TABLE chapter_processing_jobs
  ADD COLUMN guideline_id VARCHAR NULL;

-- 2. Backfill guideline_id for historical post-sync job rows.
--    For these rows, chapter_id was overloaded to hold a guideline UUID.
--    Recover via a join to teaching_guidelines.
UPDATE chapter_processing_jobs
SET guideline_id = chapter_id
WHERE job_type IN (
  'v2_explanation_generation',
  'v2_visual_enrichment',
  'v2_check_in_enrichment',
  'v2_practice_bank_generation',
  'v2_audio_text_review',
  'v2_audio_generation'
)
AND EXISTS (
  SELECT 1 FROM teaching_guidelines tg WHERE tg.id = chapter_processing_jobs.chapter_id
);

-- NOTE: historical rows' chapter_id column still holds the guideline UUID.
-- We do NOT rewrite chapter_id — the recovery join (teaching_guidelines →
-- chapter_key → book_chapters) is brittle and historical jobs are terminal.
-- The status service's chapter-scoped queries filter by `guideline_id IS NOT NULL`
-- to exclude these historical rows from chapter-level status (they're still
-- queryable by topic via guideline_id).

-- 3. Replace the single active-job index with a split (chapter-level + topic-level)
DROP INDEX IF EXISTS idx_chapter_active_job;

CREATE UNIQUE INDEX idx_chapter_active_chapter_job
  ON chapter_processing_jobs (chapter_id)
  WHERE status IN ('pending', 'running') AND guideline_id IS NULL;

CREATE UNIQUE INDEX idx_chapter_active_topic_job
  ON chapter_processing_jobs (chapter_id, guideline_id)
  WHERE status IN ('pending', 'running') AND guideline_id IS NOT NULL;

-- 4. Add an index on guideline_id for status queries
CREATE INDEX idx_chapter_jobs_guideline ON chapter_processing_jobs (guideline_id);

COMMIT;
```

**Decision — backfill scope:** backfill `guideline_id` only. Do NOT rewrite historical `chapter_id` (the `teaching_guideline` → `chapter_key` → `book_chapters.id` recovery is a 3-way join with non-unique keys; not worth the risk for terminal rows). The status service query path (§3.3) handles the residual noise.

**Decision — two partial indexes vs one COALESCE index:** two partial indexes. Simpler semantics, DB enforces both invariants independently (one chapter-level job per chapter, one topic-level job per `(chapter_id, guideline_id)`).

### 3.3 Lock refactor — `ChapterJobService.acquire_lock`

Reader-writer semantics between chapter-level and topic-level jobs: a chapter-level job (OCR, extraction, finalization, refresher) is mutually exclusive with any post-sync topic-level jobs in the same chapter, but two topic-level jobs with different `guideline_id`s in the same chapter can coexist.

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
        raise ChapterJobLockError(f"Post-sync job {job_type} requires guideline_id")
    if not is_post_sync:
        # Chapter-level jobs must have NULL guideline_id (index enforces this).
        guideline_id = None

    # Application-level cross-scope check (DB indexes enforce same-scope):
    #   post-sync wants to start → no active chapter-level job in this chapter
    #   chapter-level wants to start → no active post-sync jobs in this chapter
    if is_post_sync:
        active_chapter_job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.guideline_id.is_(None),
            ChapterProcessingJob.status.in_(["pending", "running"]),
        ).first()
        if active_chapter_job and not self._stale_or_abandoned(active_chapter_job):
            raise ChapterJobLockError(
                f"Chapter-level {active_chapter_job.job_type} is active for chapter "
                f"{chapter_id}; cannot start {job_type} for guideline {guideline_id}"
            )
    else:
        active_topic_jobs = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.guideline_id.isnot(None),
            ChapterProcessingJob.status.in_(["pending", "running"]),
        ).all()
        live = [j for j in active_topic_jobs if not self._stale_or_abandoned(j)]
        if live:
            raise ChapterJobLockError(
                f"{len(live)} post-sync job(s) active in chapter {chapter_id}; "
                f"cannot start chapter-level {job_type}"
            )

    # Same-scope duplicate check (with stale auto-recovery), as before.
    existing = self.db.query(ChapterProcessingJob).filter(
        ChapterProcessingJob.chapter_id == chapter_id,
        ChapterProcessingJob.guideline_id == guideline_id,  # NULL == NULL works for the in-memory filter
        ChapterProcessingJob.status.in_(["pending", "running"]),
    ).first()
    if existing:
        if existing.status == "running" and self._is_stale(existing):
            self._mark_stale(existing)
        elif existing.status == "pending" and self._is_pending_stale(existing):
            self._mark_pending_abandoned(existing)
        else:
            raise ChapterJobLockError(
                f"Job already {existing.status} for chapter={chapter_id} "
                f"guideline={guideline_id}: {existing.job_type}"
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
            f"Another job was just created for chapter={chapter_id} guideline={guideline_id}"
        )


def get_latest_job(
    self,
    chapter_id: str,
    job_type: Optional[str] = None,
    guideline_id: Optional[str] = None,
) -> Optional[ProcessingJobResponse]:
    query = self.db.query(ChapterProcessingJob).filter(
        ChapterProcessingJob.chapter_id == chapter_id
    )
    if job_type:
        query = query.filter(ChapterProcessingJob.job_type == job_type)
    if guideline_id is not None:
        query = query.filter(ChapterProcessingJob.guideline_id == guideline_id)
    # ... existing stale-detection + response mapping unchanged
```

### 3.4 New module: `stage_launchers.py`

Extracts the lock-and-launch sequence into a per-stage helper. Routes and the orchestrator both call these.

```python
"""Per-stage launchers — one function per post-sync stage.

Each launcher:
  1. Calls ChapterJobService.acquire_lock(..., guideline_id=...)
  2. Spawns run_in_background_v2(_run_<stage>, job_id, ...) — run_in_background_v2
     calls start_job(job_id) internally before invoking the target.
  3. Returns the job_id for callers to poll via get_job(job_id).

Extracted so that both admin routes and TopicPipelineOrchestrator use
the same code path for starting a stage.
"""
from typing import Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.services.chapter_job_service import ChapterJobService


def launch_explanation_job(
    db: Session, *, book_id: str, chapter_id: str, guideline_id: str,
    force: bool, mode: str, review_rounds: int, total_items: int = 1,
) -> str:
    """Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_explanation_generation
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.EXPLANATION_GENERATION.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_explanation_generation, job_id, book_id,
        chapter_id, guideline_id, str(force), mode, str(review_rounds),
    )
    return job_id


def launch_visual_job(...) -> str: ...
def launch_check_in_job(...) -> str: ...
def launch_practice_bank_job(...) -> str: ...
def launch_audio_review_job(...) -> str: ...
def launch_audio_generation_job(..., confirm_skip_review: bool = False) -> str: ...
```

**Decision — extraction level:** launchers (not `_run_*` helpers) are the extraction point. `_run_*` stay inside `sync_routes.py` as the background task bodies — their signatures take `job_id` as a parameter, assuming the caller has already created the job. Extracting them alone wouldn't fix the orchestrator (reviewer's #2).

### 3.5 Fan-out behavior for chapter/book-wide invocations

When a caller invokes `POST /generate-explanations?chapter_id=X` (no `guideline_id`), the route today iterates approved guidelines in scope and creates one aggregate job. Post-Phase-2:

```python
# sync_routes.py generate_explanations — post-refactor shape
if guideline_id:
    # Single-topic launch
    job_id = launch_explanation_job(db, guideline_id=guideline_id, ...)
    return {"launched": 1, "job_ids": [job_id]}
else:
    # Chapter or book-wide fan-out
    guidelines = <resolve approved guidelines in scope>
    job_ids = []
    for g in guidelines:
        try:
            job_ids.append(launch_explanation_job(db, guideline_id=g.id, ...))
        except ChapterJobLockError:
            continue  # topic already has a job in flight; skip
    return {"launched": len(job_ids), "job_ids": job_ids}
```

Same fan-out pattern for visuals, check-ins, practice bank, audio review, audio synthesis. The chapter-level runner in Phase 3 reuses this exact pattern at the orchestrator level.

**API shape change:** existing `ProcessingJobResponse` return from these endpoints becomes `{ launched: int, job_ids: list[str] }`. Frontend callers poll the first job_id (or all) instead of the single job. Breaking for external callers but internal-only.

### 3.6 New orchestration service: `TopicPipelineOrchestrator`

Lives at `book_ingestion_v2/services/topic_pipeline_orchestrator.py`.

```python
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from book_ingestion_v2.services import stage_launchers
from book_ingestion_v2.services.chapter_job_service import ChapterJobService

logger = logging.getLogger(__name__)

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

_POLL_INTERVAL_SEC = 5
_TERMINAL_STATES = {"completed", "completed_with_errors", "failed"}


class TopicPipelineOrchestrator:
    def __init__(self, db_session_factory, *, book_id, chapter_id, guideline_id, quality_level):
        self._session_factory = db_session_factory
        self.book_id = book_id
        self.chapter_id = chapter_id
        self.guideline_id = guideline_id
        self.rounds = _QUALITY_ROUNDS[quality_level]
        self.pipeline_run_id = str(uuid.uuid4())

    def run(self, stages_needed: set[str]) -> dict[str, str]:
        """Run pipeline layers. Halts on any failure. Returns {stage: terminal_state}."""
        results: dict[str, str] = {}
        for layer in _LAYERS:
            to_run = [s for s in layer if s in stages_needed]
            if not to_run:
                continue
            with ThreadPoolExecutor(max_workers=len(to_run)) as ex:
                futs = {ex.submit(self._run_one_stage, s): s for s in to_run}
                for fut in as_completed(futs):
                    stage = futs[fut]
                    results[stage] = fut.result()
            if any(results[s] == "failed" for s in to_run):
                logger.warning(
                    f"Pipeline {self.pipeline_run_id} halted at layer {to_run}"
                )
                return results
        return results

    def _run_one_stage(self, stage: str) -> str:
        """Launch a stage job via the stage_launchers module, poll to terminal."""
        db = self._session_factory()
        try:
            launcher = getattr(stage_launchers, f"launch_{stage}_job")
            launcher_kwargs = self._launcher_kwargs_for(stage)
            job_id = launcher(db, **launcher_kwargs)
            return self._poll_to_terminal(db, job_id)
        finally:
            db.close()

    def _poll_to_terminal(self, db, job_id: str) -> str:
        job_service = ChapterJobService(db)
        while True:
            job = job_service.get_job(job_id)   # poll by job_id, NOT get_latest_job
            if job and job.status in _TERMINAL_STATES:
                return job.status
            time.sleep(_POLL_INTERVAL_SEC)
```

**Decision — polling by `job_id`, not `get_latest_job`:** `get_latest_job(chapter_id, job_type)` orders by `created_at DESC` and returns the most recent row. Between submitting stage N+1 and its job row being committed, this can return the previous (terminal) job — the orchestrator would see "completed" and advance too early. Using `job_id` returned by the launcher eliminates this race.

**Decision — one DB session per stage thread:** each `_run_one_stage` thread opens its own session, mirrors `run_in_background_v2`'s isolation pattern. Orchestrator's outer thread uses a separate session for the initial status read and result recording.

### 3.7 New endpoint: per-topic run-pipeline

```
POST /admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/run-pipeline
Body: {
  "quality_level": "fast" | "balanced" | "thorough",
  "force": false,
  "confirm_skip_review": false
}
Response 202: { "pipeline_run_id": "uuid", "stages_to_run": ["explanations", "visuals", ...] }
Response 409: { "detail": "pipeline_already_running_for_topic", "in_flight_stage": "explanations" }
```

Route handler:
1. Resolve `guideline_id` from `topic_key` + `chapter_id`.
2. Call `TopicPipelineStatusService.get_pipeline_status` — snapshot current state.
3. Decide `stages_needed` (every stage not `done`, skipping any `running`). If `force`, include `done` stages too.
4. Return 200 "nothing to do" if empty.
5. Launch `orchestrator.run(stages_needed)` via a daemon thread (NOT inline — this blocks until done).
6. Return 202 immediately with `pipeline_run_id` and planned stages.

**Decision — orchestrator holds no lock:** each sub-stage acquires its own per-stage lock. A concurrent second super-button press on the same topic fails loudly at the sub-stage lock (first to `acquire_lock`, second gets 409). Simpler than orchestrator-level coordination.

### 3.8 Staleness computation (updated)

```python
def _stage_practice_bank(self, guideline_id, content_anchor):
    rows = self.db.query(PracticeQuestion).filter(
        PracticeQuestion.guideline_id == guideline_id
    ).all()
    count = len(rows)
    earliest = min((r.created_at for r in rows), default=None)
    is_stale = (
        content_anchor is not None
        and earliest is not None
        and earliest < content_anchor
    )
    # ... state / summary / warnings based on count + is_stale
```

For ⑤ Audio review: query the latest `v2_audio_text_review` job for this `guideline_id` (using the native column post-Phase-2) and compare `job.completed_at < content_anchor`.

### 3.9 Review-rounds=0 support check

Before Phase 2 ships, verify that each stage service accepts `review_rounds=0`:

```bash
grep -n "review_rounds" llm-backend/book_ingestion_v2/services/*.py
```

Specifically confirm `ExplanationGeneratorService`, `AnimationEnrichmentService`, `CheckInEnrichmentService`, `PracticeBankGeneratorService` tolerate 0 rounds (skip the refine loop). If any service rejects 0, either:
- Patch it to accept 0 (run initial generation only, skip refine), or
- Set that stage's `_QUALITY_ROUNDS["fast"]` value to 1.

Implementation step; not a risk per se.

### 3.10 Phase 2 testing plan

| Test | Verifies |
|---|---|
| Unit: `test_acquire_lock_requires_guideline_for_post_sync` | Post-sync `job_type` without `guideline_id` → `ChapterJobLockError` |
| Unit: `test_acquire_lock_allows_two_topic_jobs_same_chapter` | Two post-sync jobs with different `guideline_id` → both acquire |
| Unit: `test_acquire_lock_blocks_same_topic_twice` | Same `(chapter_id, guideline_id)` → second raises |
| Unit: `test_acquire_lock_chapter_level_blocks_topic_level` | Chapter-level job active → topic-level raises |
| Unit: `test_acquire_lock_topic_level_blocks_chapter_level` | Topic-level job active → chapter-level raises |
| Unit: `test_get_latest_job_with_guideline_id` | Filters correctly by the new column |
| Unit: `test_launch_explanation_job_returns_job_id` | Returns a usable job_id |
| Unit: `test_orchestrator_skips_done_stages` | Done stages excluded from `stages_needed` |
| Unit: `test_orchestrator_parallel_layer` | ②③④ fan out to three threads |
| Unit: `test_orchestrator_polls_by_job_id_not_latest` | Two back-to-back stage runs don't confuse poll-by-id (race cannot be triggered) |
| Unit: `test_orchestrator_halts_on_failure` | Layer ② fails → ⑤⑥ not started |
| Unit: `test_fan_out_chapter_wide` | `generate-explanations?chapter_id=X` launches N topic-level jobs |
| Unit: `test_staleness_practice_bank` | `min(practice_questions.created_at) < max(topic_explanations.created_at)` → stale=true |
| Unit: `test_staleness_not_triggered_by_inplace_cards_write` | Writing `cards_json` in-place does NOT flip stale |
| Integration: super-button on fresh topic runs all 6 stages | End-to-end |
| Integration: two topics in same chapter run concurrently | Lock refactor end-to-end |
| Manual: regenerate ① → ④ and ⑤ flip to ⚠ Stale within one poll | Staleness UI |
| Manual: run ⑥ (audio synth) alone → ④ and ⑤ do NOT flip stale | Confirms fix for reviewer #4 |

**Phase 2 exit criteria:** super-button runs a full pipeline for one topic; two topics run concurrently in one chapter; fan-out works from existing routes; staleness flags correctly and does NOT false-fire on in-place `cards_json` writes.

---

## 4. Phase 3 — Chapter-Level Runner + Aggregate Summary + Polish

### 4.1 Files changed

#### Backend

| File | Change |
|---|---|
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | **NEW endpoints** — `POST /chapters/{chapter_id}/run-pipeline-all`, `GET /chapters/{chapter_id}/pipeline-summary` |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py` | **Add** `run_chapter_all` helper — spawns one `TopicPipelineOrchestrator` per topic with bounded concurrency |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py` | **Add** `get_chapter_summary(book_id, chapter_id) -> ChapterPipelineSummaryResponse` — per-topic state rollups in one DB pass |
| `llm-backend/config.py` (or env) | **Add** `TOPIC_PIPELINE_MAX_PARALLEL_TOPICS = 4` |

#### Frontend

| File | Change |
|---|---|
| `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | **Add** topic summary chip + "Run pipeline for all topics" button per chapter. Chip reads `/pipeline-summary` (one request per chapter, not N) |
| `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` | **Add** prev/next topic nav, inline error summary, [Retry] buttons on Failed rows |
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | **Add** `runChapterPipelineAll`, `getChapterPipelineSummary` |

### 4.2 Chapter pipeline summary endpoint

```
GET /admin/v2/books/{book_id}/chapters/{chapter_id}/pipeline-summary
Response 200: {
  "chapter_id": "...",
  "topics": [
    {
      "topic_key": "...",
      "topic_title": "...",
      "guideline_id": "...",
      "stage_counts": { "done": 4, "warning": 1, "ready": 1, "blocked": 0, "running": 0, "failed": 0 },
      "is_fully_done": false
    },
    ...
  ],
  "chapter_totals": {
    "topics_total": 12,
    "topics_fully_done": 8,
    "topics_partial": 3,
    "topics_not_started": 1
  }
}
```

Handled by `TopicPipelineStatusService.get_chapter_summary` — issues aggregate queries (counts, joins) rather than N per-topic lookups. Backend does the heavy lifting; frontend chip consumes one response.

**Decision — aggregate endpoint (not client-side fan-out):** the reviewer's Tier-3 concern about N×GETs for the chapter chip is valid. 12-15 topics × ~5 DB queries each on every `BookV2Detail` load would noticeably slow the page. One aggregate endpoint is the correct trade-off.

### 4.3 Chapter-level runner endpoint

```
POST /admin/v2/books/{book_id}/chapters/{chapter_id}/run-pipeline-all
Body: {
  "quality_level": "fast" | "balanced" | "thorough",
  "skip_done": true,
  "max_parallel": 4
}
Response 202: { "chapter_run_id": "uuid", "topics_queued": 12 }
```

Route handler:
1. Load all topics in the chapter.
2. For each topic, get_pipeline_status (or use a lighter-weight "is_fully_done" query derived from `get_chapter_summary`).
3. Skip fully-done topics if `skip_done=true`.
4. Hand list to `run_chapter_all`, which uses `ThreadPoolExecutor(max_workers=max_parallel)` and spawns one orchestrator per topic.
5. Return 202 with queue size.

**Failure mode:** a single topic's pipeline failing does NOT halt the chapter runner. Other topics continue. Per-topic failure surfaces via `get_chapter_summary` on subsequent polls.

### 4.4 Prev/next nav, inline errors + retry

Standard frontend polish. Retry calls the existing per-stage `POST /generate-<stage>?guideline_id=X&force=true` with `review_rounds` from the current Quality setting.

### 4.5 Phase 3 testing plan

| Test | Verifies |
|---|---|
| Unit: `test_get_chapter_summary_aggregation` | One DB pass returns per-topic rollups |
| Unit: `test_run_chapter_all_bounded_parallelism` | 10 topics, `max_parallel=4` → at most 4 active at a time |
| Unit: `test_run_chapter_all_skip_done` | Fully-done topics skipped |
| Unit: `test_run_chapter_all_topic_failure_does_not_halt_others` | One topic fails; others complete |
| Integration: chapter with 10 topics via `run-pipeline-all` completes in wall-clock < 2× the slowest topic | Parallelism works |
| Integration: `BookV2Detail` chapter page loads in <500ms with 15 topics | Summary endpoint performant |
| Manual: click super-button, nav to next topic mid-run | No polling leak; correct state on new topic |
| Manual: Failed → Retry → only that stage re-runs | Retry wiring |

**Phase 3 exit criteria:** chapter-level runner works; `BookV2Detail` page load remains fast; prev/next navigation works; failed stages show inline errors and can be retried.

---

## 5. Implementation Order (per phase)

### Phase 1 sequence

| # | Step | Files | Depends on |
|---|---|---|---|
| 1 | Pydantic schemas for the new GET response | `models/schemas.py` | — |
| 2 | `TopicPipelineStatusService` with historical-row handling, content-anchor staleness + unit tests | `services/topic_pipeline_status_service.py`, tests | 1 |
| 3 | GET endpoint | `api/sync_routes.py` | 2 |
| 4 | Admin API client method + types | `adminApiV2.ts` | 3 |
| 5 | `StageLadderRow` component | `StageLadderRow.tsx` | 4 |
| 6 | `useTopicPipeline` hook (fixed polling) | `useTopicPipeline.ts` | 4 |
| 7 | `TopicPipelineDashboard` page | `TopicPipelineDashboard.tsx` | 5, 6 |
| 8 | Route wiring | `App.tsx` | 7 |
| 9 | `BookV2Detail` per-topic link | `BookV2Detail.tsx` | 8 |
| 10 | Manual QA + docs | — | 9 |

### Phase 2 sequence

| # | Step | Files | Depends on |
|---|---|---|---|
| 1 | Grep-verify `review_rounds=0` support in all 4 LLM stage services | stage services (no code change if OK) | — |
| 2 | DB migration: add column, backfill, split indexes | `db.py` migration | — |
| 3 | Model update: add `guideline_id` to `ChapterProcessingJob` | `models/database.py` | 2 |
| 4 | `ChapterJobService.acquire_lock` + `get_latest_job` refactor + unit tests | `chapter_job_service.py`, tests | 3 |
| 5 | `stage_launchers.py` with 6 helpers + unit tests | new module, tests | 4 |
| 6 | Refactor every post-sync route in `sync_routes.py` to use launchers + implement fan-out when guideline_id is absent | `sync_routes.py` | 5 |
| 7 | Update all `get_latest_*_job` endpoints to accept/pass `guideline_id` | `sync_routes.py` | 4 |
| 8 | Update audio-synth soft-guardrail lookup (sync_routes.py:572-574) | `sync_routes.py` | 4 |
| 9 | Update frontend `adminApiV2.ts` for the new `{launched, job_ids[]}` shape | `adminApiV2.ts` | 6 |
| 10 | Update per-stage admin pages (`ExplanationAdmin`, `VisualsAdmin`, `CheckInAdmin`, `PracticeBankAdmin`) to handle new response shape | those .tsx files | 9 |
| 11 | Update `TopicPipelineStatusService` to use native `guideline_id` column + staleness via content_anchor | `topic_pipeline_status_service.py` | 3 |
| 12 | `TopicPipelineOrchestrator` service + unit tests (including poll-by-job_id test) | `topic_pipeline_orchestrator.py`, tests | 5 |
| 13 | POST `/run-pipeline` endpoint | `sync_routes.py` | 12 |
| 14 | `QualitySelector` component | `QualitySelector.tsx` | — |
| 15 | Wire super-button | `TopicPipelineDashboard.tsx` | 13, 14 |
| 16 | Manual QA + docs | — | 15 |

### Phase 3 sequence

| # | Step | Files | Depends on |
|---|---|---|---|
| 1 | `get_chapter_summary` method + unit tests | `topic_pipeline_status_service.py` | Phase 2 |
| 2 | `GET /pipeline-summary` endpoint | `sync_routes.py` | 1 |
| 3 | `run_chapter_all` helper + unit tests | `topic_pipeline_orchestrator.py` | Phase 2 |
| 4 | `POST /run-pipeline-all` endpoint | `sync_routes.py` | 3 |
| 5 | Chapter topic summary chip + button on `BookV2Detail` | `BookV2Detail.tsx` | 2, 4 |
| 6 | Prev/next topic nav | `TopicPipelineDashboard.tsx` | — |
| 7 | Inline error + [Retry] on Failed rows | `StageLadderRow.tsx` | — |
| 8 | Polling hardening (tab background, unmount) | `useTopicPipeline.ts` | — |
| 9 | Manual QA + docs | — | 8 |

---

## 6. Data Model Summary

| Table | Change |
|---|---|
| `chapter_processing_jobs` | ADD COLUMN `guideline_id VARCHAR NULL`; backfill for historical post-sync rows; split `idx_chapter_active_job` into `idx_chapter_active_chapter_job` + `idx_chapter_active_topic_job`; add `idx_chapter_jobs_guideline` |

No other schema changes.

---

## 7. API Summary

| Method | Path | Phase | Purpose |
|---|---|---|---|
| GET | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/pipeline` | 1 | Consolidated per-topic status |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/run-pipeline` | 2 | Super-button orchestration |
| GET | `/admin/v2/books/{book_id}/chapters/{chapter_id}/pipeline-summary` | 3 | Aggregate per-topic status (chip) |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/run-pipeline-all` | 3 | Chapter-level runner |

**Breaking changes (internal only):** `POST /generate-explanations`, `generate-visuals`, `generate-check-ins`, `generate-practice-banks`, `generate-audio-review`, `generate-audio` return shape changes from `ProcessingJobResponse` to `{ launched: int, job_ids: list[str] }` when `guideline_id` is omitted (fan-out case). Admin frontend is the only consumer and is updated in step 9 of Phase 2.

---

## 8. Configuration & Environment

| Variable | Purpose | Default | Phase |
|---|---|---|---|
| `TOPIC_PIPELINE_MAX_PARALLEL_TOPICS` | Cap on concurrent topics in `run-pipeline-all` | `4` | 3 |

`_QUALITY_ROUNDS` is a constant in the orchestrator. Tuning requires a deploy but not a config change.

---

## 9. Deployment Considerations

- **Phase 1**: pure additive — new endpoint, new frontend route. No migration. Zero backend write-path risk. Deploy any time.
- **Phase 2**: requires migration coordination.
  - Deploy sequence: (1) migration alone; (2) backend with `acquire_lock` + launchers + route refactor; (3) frontend with super-button + updated response-shape handling.
  - The status service's query path flips from Phase-1 (historical overload) to Phase-2 (native `guideline_id`) in the backend deploy step. Test both paths before deploy.
- **Phase 3**: pure additive — new endpoints, new frontend UI. Deploy any time after Phase 2.

**Rollback:**

- Phase 1 — revert frontend + revert new endpoint. No data impact.
- Phase 2 — the cleanest rollback is a coordinated revert:
  - Revert frontend (so it sends old request shapes).
  - Revert `sync_routes.py` routes (so they use old lock pattern, pass `lock_chapter_id = guideline_id or chapter_id or book_id`).
  - Revert `ChapterJobService.acquire_lock` + `get_latest_job` to old signatures.
  - The `guideline_id` column and new indexes are harmless to leave in place. The backfilled `guideline_id` values remain for historical rows but are unused by the reverted code.
  - This is **not** a one-PR revert — it's 3 coordinated reverts. Plan the rollback accordingly.
- Phase 3 — revert frontend + revert new endpoints. No data impact.

---

## 10. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Lock refactor mis-handles a chapter-level + topic-level race | Low-Med | High | Reader-writer pattern enforced at application AND index level; four unit tests cover all cross-scope combinations; integration test verifies end-to-end |
| Orchestrator polls wrong job due to `get_latest_job` race | Mitigated | — | Fixed: orchestrator polls by `job_id` returned from the launcher (not `get_latest_job`). Explicit regression test |
| Staleness false-fires on in-place `cards_json` writes | Mitigated | — | Fixed: anchor is `max(topic_explanations.created_at)`, not `updated_at`. Explicit regression test after ⑥ (audio synth) |
| Historical post-sync rows appear in chapter-scoped queries misattributed | Mitigated | — | Backfill migration populates `guideline_id` for recoverable rows; status service excludes residual non-recoverable rows via `guideline_id IS NOT NULL` filter in chapter-scoped queries |
| Review_rounds=0 rejected by a stage service | Low | Medium (Fast mode broken) | Pre-phase-2 grep audit (step 1 of Phase 2 sequence); if any service rejects 0, patch it or set `_QUALITY_ROUNDS["fast"][stage] = 1` |
| Fan-out behavior changes an existing client contract | Low | Medium | Only internal admin UI consumes these endpoints; updated as part of Phase 2 step 10 |
| Orchestrator leaks daemon threads when super-button page closes | Low | Low | Daemon threads complete regardless of HTTP client; mirrors existing `run_in_background_v2` pattern |
| Chapter-level runner saturates Claude Code subprocess | Med | Med | `TOPIC_PIPELINE_MAX_PARALLEL_TOPICS=4` default; existing adapter retries on rate limit |
| Admin double-presses super-button | Low | Low | Per-stage lock returns 409 on the second concurrent launcher call |

---

## 11. Open Questions

- **Pipeline run records:** persist `pipeline_run_id` rows in a new table for full observability, or tag in `progress_detail`? **Decision for v1:** tag in `progress_detail` JSON; no new table. Revisit if admins ask for a pipeline-run history view.
- **Topic pre-selection on per-stage admin pages:** should "Open stage page →" auto-scroll/highlight the current topic? **Decision for v1:** no; link lands on the chapter-scoped page. Phase 3 polish if demanded.
- **Staleness grace window:** small 60s buffer so stale doesn't flash during the regenerate → auto-wipe window? **Decision for v1:** no grace; flash is informative. Anchor is only `created_at` so this is less of an issue.

---

## 12. References

- PRD: `docs/feature-development/topic-pipeline-dashboard/PRD.md`
- Review: `docs/feature-development/topic-pipeline-dashboard/impl-plan-review.md`
- Pipeline principles: `docs/principles/book-ingestion-pipeline.md`
- Job service: `llm-backend/book_ingestion_v2/services/chapter_job_service.py`
- Background pattern: `llm-backend/book_ingestion_v2/api/processing_routes.py:438`
- Existing per-stage endpoints: `llm-backend/book_ingestion_v2/api/sync_routes.py`
- Admin router: `llm-frontend/src/App.tsx`
- Admin API client: `llm-frontend/src/features/admin/api/adminApiV2.ts`
