# Tech Implementation Plan: Improve Chapter-to-Topic Breakdown Quality

**Date:** 2026-03-16
**Status:** Draft
**PRD:** `docs/feature-development/topic-quality-improvement/PRD.md`
**Author:** Tech Impl Plan Generator + Manish

---

## 1. Overview

This plan adds a chapter-level topic planning phase before chunk extraction, modifies chunk extraction to assign content to planned topics rather than discovering freely, upgrades consolidation to validate the plan and reconcile unplanned topics, and threads a new `prior_topics_context` field from ingestion through to the tutor's system prompt. The overall pipeline becomes: **Plan → Extract (guided) → Consolidate (plan-aware) → Generate curriculum context → Sync → Tutor reads context**.

No new API endpoints, no frontend changes, no new routers. All changes are internal to the book ingestion pipeline and the tutor's data path.

---

## 2. Architecture Changes

### Pipeline flow (before → after)

```
BEFORE:
  Upload Pages → Chunk Extraction → Finalization → Sync → Tutor

AFTER:
  Upload Pages → [NEW] Topic Planning → Guided Extraction → Plan-Aware Consolidation
                                                              → [NEW] Curriculum Context Gen
                                                              → Sync → Tutor (with context)
```

### New modules
- `book_ingestion_v2/services/chapter_topic_planner_service.py` — Chapter-level planning service
- `book_ingestion_v2/prompts/chapter_topic_planning.txt` — Planning prompt
- `book_ingestion_v2/prompts/curriculum_context_generation.txt` — Curriculum context generation prompt

### Significantly modified modules
- `book_ingestion_v2/services/topic_extraction_orchestrator.py` — Calls planner before extraction, initializes state from plan
- `book_ingestion_v2/services/chunk_processor_service.py` — Accepts planned topic skeleton as prompt context
- `book_ingestion_v2/services/chapter_finalization_service.py` — Plan validation, deviation detection, context generation
- `book_ingestion_v2/prompts/chunk_topic_extraction.txt` — Shifts from "discover" to "assign"
- `book_ingestion_v2/prompts/chapter_consolidation.txt` — Shifts from "merge discovery" to "plan validation"
- `tutor/prompts/master_tutor_prompts.py` — Adds curriculum context section

---

## 3. Database Changes

### Modified tables

| Table | Change | Details |
|-------|--------|---------|
| `chapter_processing_jobs` | Add column | `planned_topics_json TEXT` — Stores the planner's output as JSON. Nullable (null for legacy jobs). |
| `chapter_topics` | Add columns | `prior_topics_context TEXT` — Curriculum context for tutor. Nullable. |
| | | `topic_assignment VARCHAR` — "planned" or "unplanned". Nullable (null for legacy topics). |
| `teaching_guidelines` | Add column | `prior_topics_context TEXT` — Synced from `chapter_topics`. Nullable. |

**Decision:** Store planned topics as a JSON field on `ChapterProcessingJob` rather than a separate table. The plan is coupled to the job and doesn't need independent querying. Matches PRD recommendation and avoids a new table.

### Relationships

No new relationships. `planned_topics_json` is denormalized on the job for simplicity.

### Migration plan

Add a new migration function `_apply_topic_planning_columns()` in `db.py`:

```python
def _apply_topic_planning_columns(engine):
    """Add columns for topic quality improvement feature."""
    inspector = inspect(engine)

    # chapter_processing_jobs.planned_topics_json
    if "planned_topics_json" not in [c["name"] for c in inspector.get_columns("chapter_processing_jobs")]:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chapter_processing_jobs ADD COLUMN planned_topics_json TEXT"))

    # chapter_topics.prior_topics_context
    if "prior_topics_context" not in [c["name"] for c in inspector.get_columns("chapter_topics")]:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chapter_topics ADD COLUMN prior_topics_context TEXT"))

    # chapter_topics.topic_assignment
    if "topic_assignment" not in [c["name"] for c in inspector.get_columns("chapter_topics")]:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chapter_topics ADD COLUMN topic_assignment VARCHAR"))

    # teaching_guidelines.prior_topics_context
    if "prior_topics_context" not in [c["name"] for c in inspector.get_columns("teaching_guidelines")]:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE teaching_guidelines ADD COLUMN prior_topics_context TEXT"))
```

No data backfills needed. Existing topics will have null values for new columns, which is the correct behavior (pre-feature topics simply omit curriculum context).

---

## 4. Backend Changes

### 4.1 Models (`book_ingestion_v2/models/`)

#### `processing_models.py` — New and modified models

**New model: `PlannedTopic`**

```python
class PlannedTopic(BaseModel):
    """A single topic from the chapter-level planning phase."""
    topic_key: str                    # kebab-case slug
    title: str                        # Human-readable title
    description: str                  # 1-sentence description
    page_start: int                   # Primary page range start
    page_end: int                     # Primary page range end
    sequence_order: int               # Teaching sequence (1-based)
    grouping_rationale: str           # Why these pages form one unit
    dependency_notes: str = ""        # What prior topics this builds on
```

**New model: `ChapterTopicPlan`**

```python
class ChapterTopicPlan(BaseModel):
    """Full output from the chapter-level planning phase."""
    topics: List[PlannedTopic]
    chapter_overview: str             # 2-3 sentence chapter teaching narrative
    planning_rationale: str           # Why this breakdown was chosen
```

**Modified model: `TopicUpdate`** — Replace `is_new` with `topic_assignment`

```python
class TopicUpdate(BaseModel):
    """Single topic detected/updated in a chunk."""
    topic_key: str
    topic_title: str
    topic_assignment: str             # "planned" or "unplanned"
    guidelines_for_this_chunk: str
    reasoning: str
    unplanned_justification: str = "" # Required when topic_assignment == "unplanned"
```

**New model: `ConsolidationDeviation`**

```python
class ConsolidationDeviation(BaseModel):
    """Tracks a deviation from the planned topic structure."""
    deviation_type: str               # "split", "merge", "unplanned_ratified", "unplanned_merged"
    topic_key: str
    reasoning: str
```

**Modified model: `ConsolidationOutput`** — Add deviation tracking

```python
class ConsolidationOutput(BaseModel):
    """LLM output for chapter finalization."""
    chapter_display_name: str
    final_chapter_summary: str
    merge_actions: List[MergeAction]
    topic_updates: List[TopicFinalUpdate]
    deviations: List[ConsolidationDeviation] = []  # NEW
```

**New model: `TopicCurriculumContext`**

```python
class TopicCurriculumContext(BaseModel):
    """Curriculum context for a single topic."""
    topic_key: str
    prior_topics_context: str         # Full context text for tutor prompt
```

**New model: `CurriculumContextOutput`**

```python
class CurriculumContextOutput(BaseModel):
    """LLM output for curriculum context generation."""
    contexts: List[TopicCurriculumContext]
```

#### `database.py` — Add columns to ORM models

```python
# ChapterProcessingJob — add:
planned_topics_json = Column(Text, nullable=True)

# ChapterTopic — add:
prior_topics_context = Column(Text, nullable=True)
topic_assignment = Column(String, nullable=True)  # "planned" or "unplanned"
```

#### `schemas.py` — Add fields to API response schemas

```python
# ChapterTopicResponse — add:
prior_topics_context: Optional[str] = None
topic_assignment: Optional[str] = None
```

### 4.2 Constants (`book_ingestion_v2/constants.py`)

**Add `NEEDS_REVIEW` chapter status:**

```python
class ChapterStatus(str, Enum):
    # ... existing values ...
    NEEDS_REVIEW = "needs_review"      # Planning failure — >30% deviation
```

**Add planning deviation threshold:**

```python
PLANNING_DEVIATION_THRESHOLD = 0.30  # 30% deviation triggers needs_review
```

### 4.3 Chapter Topic Planner Service (NEW)

**File:** `book_ingestion_v2/services/chapter_topic_planner_service.py`

```python
class ChapterTopicPlannerService:
    """Plans chapter-level topic structure before chunk extraction."""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    def plan_chapter(
        self,
        book_metadata: dict,
        chapter_metadata: dict,
        page_texts: List[dict],   # [{page_number, text}]
    ) -> ChapterTopicPlan:
        """
        Analyze full chapter content and produce a topic skeleton.

        Uses higher reasoning effort than chunk extraction since this
        makes structural decisions for the entire chapter.
        """
```

- **Input:** All OCR'd pages for the chapter + book/chapter metadata
- **Output:** `ChapterTopicPlan` with ordered list of `PlannedTopic`
- **LLM config:** Same `book_ingestion_v2` config key, but with `reasoning_effort="high"` (chunk extraction uses `reasoning_effort="none"`)
- **Retry:** Same pattern as `ChunkProcessorService` — 3 attempts with exponential backoff
- **Prompt:** `chapter_topic_planning.txt` (see Section 6)

**Decision:** Use `reasoning_effort="high"` (not "medium") because this is a one-per-chapter call making high-stakes structural decisions. The cost increase is negligible since there's only one planning call per chapter vs. many chunk calls.

### 4.4 Modified Chunk Processor Service

**File:** `book_ingestion_v2/services/chunk_processor_service.py`

Changes:
- `process_chunk()` signature adds `planned_topics: Optional[List[PlannedTopic]] = None`
- `_build_prompt()` conditionally includes a `PLANNED TOPIC SKELETON` section when planned topics are provided
- LLM call remains `reasoning_effort="none"` (speed is critical for per-chunk calls)
- Response parsing accepts `topic_assignment` field instead of `is_new`

### 4.5 Modified Extraction Orchestrator

**File:** `book_ingestion_v2/services/topic_extraction_orchestrator.py`

Changes to `extract()`:

1. **After acquiring job lock, before building chunk windows:**
   - Load all OCR'd page texts for the chapter
   - Call `ChapterTopicPlannerService.plan_chapter()`
   - Save planned topics to `ChapterProcessingJob.planned_topics_json`
   - Save planned topics to S3 at `{s3_run_base}/planned_topics.json`
   - Initialize `RunningState.topic_guidelines_map` from planned topics (pre-populate with empty guidelines)

2. **In the chunk processing loop:**
   - Pass `planned_topics` to `chunk_processor.process_chunk()`
   - Change accumulator logic: `topic_assignment == "planned"` → always append (topic already exists in map); `topic_assignment == "unplanned"` → create new entry (with unplanned flag)

3. **When persisting draft topics:**
   - Set `topic_assignment` on each `ChapterTopic` record

4. **Resume support:**
   - When resuming, load planned topics from the previous job's `planned_topics_json`

### 4.6 Modified Chapter Finalization Service

**File:** `book_ingestion_v2/services/chapter_finalization_service.py`

Changes to `finalize()`:

1. **Load planned topics** from the job's `planned_topics_json` (needed for deviation tracking)

2. **Updated consolidation prompt** passes planned topic skeleton as context. Consolidation role shifts from "discover merges" to "validate plan + reconcile unplanned topics"

3. **After consolidation, count deviations:**
   ```python
   deviations = consolidation_output.deviations
   total_planned = len(planned_topics)
   deviation_count = len(deviations)
   deviation_ratio = deviation_count / total_planned if total_planned > 0 else 0

   if deviation_ratio > PLANNING_DEVIATION_THRESHOLD:
       chapter.status = ChapterStatus.NEEDS_REVIEW.value
   ```

4. **New step: Generate curriculum context** — After consolidation and topic updates, run a single LLM call using `curriculum_context_generation.txt` prompt to generate `prior_topics_context` for all topics (except the first). Save to each `ChapterTopic.prior_topics_context`.

5. **Heartbeat updates** during context generation to prevent stale detection.

### 4.7 Topic Sync Service

**File:** `book_ingestion_v2/services/topic_sync_service.py`

Change to `_sync_topic()`:

```python
# Add to TeachingGuideline creation:
guideline = TeachingGuideline(
    # ... existing fields ...
    prior_topics_context=topic.prior_topics_context,  # NEW
)
```

### 4.8 Shared Models

**File:** `shared/models/entities.py`

Add to `TeachingGuideline`:

```python
prior_topics_context = Column(Text, nullable=True)
```

**File:** `shared/models/schemas.py`

Add to `GuidelineResponse`:

```python
prior_topics_context: Optional[str] = None
```

**File:** `shared/repositories/guideline_repository.py`

Update `get_guideline_by_id()` to include the new field:

```python
return GuidelineResponse(
    # ... existing fields ...
    prior_topics_context=guideline.prior_topics_context,
)
```

Also update `get_guideline()` with the same change.

### 4.9 Tutor Data Path

**File:** `tutor/models/study_plan.py`

Add to `TopicGuidelines`:

```python
prior_topics_context: Optional[str] = Field(
    default=None,
    description="Curriculum context: what prior topics in this chapter cover"
)
```

**File:** `tutor/services/topic_adapter.py`

Update `convert_guideline_to_topic()`:

```python
topic_guidelines = TopicGuidelines(
    # ... existing fields ...
    prior_topics_context=guideline.prior_topics_context,
)
```

**File:** `tutor/prompts/master_tutor_prompts.py`

Add curriculum context section to `MASTER_TUTOR_SYSTEM_PROMPT`:

```python
# After "## Topic: {topic_name}" and before "### Curriculum Scope":

{prior_topics_context_section}
### Curriculum Scope
{curriculum_scope}
```

Where `{prior_topics_context_section}` is built by the master tutor agent:

```python
# In MasterTutorAgent._build_system_prompt():
if topic.guidelines.prior_topics_context:
    prior_topics_section = (
        "### Prior Topics in This Chapter\n"
        f"{topic.guidelines.prior_topics_context}"
    )
else:
    prior_topics_section = ""
```

**File:** `tutor/agents/master_tutor.py`

Update `_build_system_prompt()` to pass `prior_topics_context_section` to the template.

### 4.10 Processing Routes

**File:** `book_ingestion_v2/api/processing_routes.py`

Update `start_processing()` and `reprocess()` to allow `NEEDS_REVIEW` status for reprocessing:

```python
# In refinalize():
if chapter.status not in [
    ChapterStatus.CHAPTER_COMPLETED.value,
    ChapterStatus.FAILED.value,
    ChapterStatus.NEEDS_REVIEW.value,  # NEW
]:
```

### 4.11 Other Consumers Assessment

**Study plan generation:** Study plans are generated per-topic from teaching guidelines. The `StudyPlanGeneratorService` receives a single guideline and produces a plan for that topic. Curriculum context could help the generator know what prerequisite knowledge to build on, but the PRD explicitly lists "changing the study plan generation logic" as a non-goal. The data is available on `GuidelineResponse.prior_topics_context` if needed in the future — no code change needed.

**Exam generation:** Exam questions are generated per-topic via `ExamService.generate_questions()`. Cross-topic awareness could improve question design, but is out of scope per PRD. The data is available when needed.

---

## 5. Frontend Changes

**No frontend changes required.** The PRD explicitly lists "Admin UI changes" as a non-goal. The `BookV2Detail` page's topic list and processing flow continue to work as-is. The new `needs_review` status will show in the chapter status display naturally (the frontend renders the status string directly).

---

## 6. LLM Integration

### New: Chapter Topic Planner

**Prompt file:** `book_ingestion_v2/prompts/chapter_topic_planning.txt`

**Purpose:** Analyze full chapter content and produce a topic skeleton.

**Input template variables:**
- `{book_title}`, `{subject}`, `{grade}`, `{board}` — book metadata
- `{chapter_number}`, `{chapter_title}`, `{chapter_page_range}` — chapter metadata
- `{all_pages_text}` — Full OCR text for all chapter pages

**Output schema:**
```json
{
  "chapter_overview": "2-3 sentence teaching narrative...",
  "planning_rationale": "Why this breakdown was chosen...",
  "topics": [
    {
      "topic_key": "kebab-case-slug",
      "title": "Human Readable Title",
      "description": "One sentence describing what this topic covers",
      "page_start": 7,
      "page_end": 9,
      "sequence_order": 1,
      "grouping_rationale": "Why these pages form one unit",
      "dependency_notes": "Builds on: nothing (first topic)"
    }
  ]
}
```

**Key prompt instructions:**
- Reference the 8 principles from `docs/principles/breaking-down-chapters-into-topics.md`
- Each page gets exactly one primary topic assignment
- Meta-skills folded into relevant topics
- Aim for 5-7 topics for most chapters (no floor or ceiling)
- Each topic should be a 20-40 minute lesson
- Output reads like a tutor's lesson plan, not a TOC

**LLM config:** `book_ingestion_v2` component key, `reasoning_effort="high"`, `json_mode=True`

### Modified: Chunk Extraction

**Prompt file:** `book_ingestion_v2/prompts/chunk_topic_extraction.txt`

**Changes:**
- Add `{planned_topics_text}` section showing the topic skeleton
- Shift task description from "identify topics" to "assign content to planned topics"
- Add plan deviation protocol instructions
- Change output schema: `is_new` → `topic_assignment` ("planned"/"unplanned")
- Add `unplanned_justification` field (required when unplanned)

**LLM config:** Unchanged — `reasoning_effort="none"`, `json_mode=True`

### Modified: Chapter Consolidation

**Prompt file:** `book_ingestion_v2/prompts/chapter_consolidation.txt`

**Changes:**
- Add `{planned_topics_json}` section showing the original plan
- Shift role from "discover merges" to "validate plan + reconcile unplanned topics"
- Add deviation tracking in output schema
- Consolidation can split over-broad planned topics, merge trivial ones, or ratify unplanned topics — but must justify each deviation

**LLM config:** Unchanged — `json_mode=True`

### New: Curriculum Context Generation

**Prompt file:** `book_ingestion_v2/prompts/curriculum_context_generation.txt`

**Purpose:** Generate `prior_topics_context` for each topic (except first).

**Input:** All final topics in sequence order with their titles, descriptions, and key learning objectives.

**Output schema:**
```json
{
  "contexts": [
    {
      "topic_key": "comparing-ordering-numbers",
      "prior_topics_context": "Prior topics in this chapter cover: ... Key concepts: ... This topic builds on those concepts. Check whether the student is comfortable with them before building on them — don't assume mastery just because they appear earlier in the chapter."
    }
  ]
}
```

**LLM config:** `book_ingestion_v2` component key, `json_mode=True`. No special reasoning effort needed — this is a straightforward summarization task.

### Cost and latency considerations

| Call | Per Chapter | Estimated Tokens | Impact |
|------|-------------|------------------|--------|
| Chapter planner | 1 call | Input: ~5K-20K (all pages), Output: ~1K | +10-30s per chapter, higher reasoning adds cost |
| Chunk extraction | Same count as before | +200-300 tokens input (planned skeleton) | Negligible per-chunk overhead |
| Consolidation | 1 call | +500 tokens input (planned skeleton) | Negligible |
| Curriculum context | 1 call | Input: ~1K (topic list), Output: ~1K | +5-10s per chapter |

**Total additional cost per chapter:** ~2 extra LLM calls (planner + context gen). For a typical 23-page chapter, this adds ~20-40 seconds to the ~5-10 minute total pipeline.

---

## 7. Configuration & Environment

### No new environment variables needed.

The planner uses the existing `book_ingestion_v2` LLM config from the `llm_config` DB table. No new config entries, no new API keys.

### Config changes (`constants.py`)

| Constant | Value | Purpose |
|----------|-------|---------|
| `PLANNING_DEVIATION_THRESHOLD` | `0.30` | Fraction of plan deviations that triggers `needs_review` |

---

## 8. Implementation Order

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1 | **Database migration** — Add 4 new columns | `db.py`, `book_ingestion_v2/models/database.py`, `shared/models/entities.py` | — | Run `python db.py --migrate`, verify columns exist |
| 2 | **Pydantic models** — PlannedTopic, updated TopicUpdate, ConsolidationDeviation, CurriculumContext | `book_ingestion_v2/models/processing_models.py` | — | Instantiate models, verify serialization |
| 3 | **Constants** — NEEDS_REVIEW status, PLANNING_DEVIATION_THRESHOLD | `book_ingestion_v2/constants.py` | — | Import and verify |
| 4 | **Planning prompt** — `chapter_topic_planning.txt` | `book_ingestion_v2/prompts/chapter_topic_planning.txt` | — | Review prompt text |
| 5 | **Chapter Topic Planner Service** — New service | `book_ingestion_v2/services/chapter_topic_planner_service.py` | Steps 2, 4 | Unit test with mocked LLM: verify prompt building, output parsing, retry logic |
| 6 | **Updated chunk extraction prompt** | `book_ingestion_v2/prompts/chunk_topic_extraction.txt` | — | Review prompt text |
| 7 | **Modified Chunk Processor** — Accept planned topics | `book_ingestion_v2/services/chunk_processor_service.py` | Steps 2, 6 | Unit test: verify prompt includes planned topics, response parsing handles `topic_assignment` |
| 8 | **Modified Orchestrator** — Insert planning phase, guided extraction | `book_ingestion_v2/services/topic_extraction_orchestrator.py` | Steps 5, 7 | Integration test: run full pipeline on a test chapter, verify planned topics are stored on job and used in extraction |
| 9 | **Updated consolidation prompt** | `book_ingestion_v2/prompts/chapter_consolidation.txt` | — | Review prompt text |
| 10 | **Curriculum context prompt** | `book_ingestion_v2/prompts/curriculum_context_generation.txt` | — | Review prompt text |
| 11 | **Modified Finalization** — Plan validation, deviation detection, context generation | `book_ingestion_v2/services/chapter_finalization_service.py` | Steps 2, 9, 10 | Unit test: verify deviation counting, needs_review threshold, context generation call |
| 12 | **Topic Sync** — Sync prior_topics_context | `book_ingestion_v2/services/topic_sync_service.py` | Step 1 | Unit test: verify TeachingGuideline gets prior_topics_context |
| 13 | **Shared schemas** — GuidelineResponse, guideline_repository | `shared/models/schemas.py`, `shared/repositories/guideline_repository.py` | Step 1 | Unit test: verify field appears in GuidelineResponse |
| 14 | **Tutor models** — TopicGuidelines.prior_topics_context | `tutor/models/study_plan.py` | — | Instantiate model with field |
| 15 | **Topic adapter** — Pass through prior_topics_context | `tutor/services/topic_adapter.py` | Steps 13, 14 | Unit test: verify field flows from GuidelineResponse to TopicGuidelines |
| 16 | **Master tutor prompt** — Add curriculum context section | `tutor/prompts/master_tutor_prompts.py`, `tutor/agents/master_tutor.py` | Step 14 | Unit test: verify prompt includes context when present, omits when null |
| 17 | **Processing routes** — Allow needs_review for reprocessing | `book_ingestion_v2/api/processing_routes.py` | Step 3 | Manual: verify reprocess works on needs_review chapters |
| 18 | **API response schemas** — Add fields to ChapterTopicResponse | `book_ingestion_v2/models/schemas.py` | Step 1 | Verify API response includes new fields |

**Order rationale:** Database first (foundation), then models (types), then services bottom-up (planner → processor → orchestrator → finalization → sync), then the tutor data path (schemas → adapter → prompt). Each step is independently testable.

---

## 9. Testing Plan

### Unit tests

| Test | What it Verifies | Key Mocks |
|------|------------------|-----------|
| `test_chapter_topic_planner_builds_prompt` | Prompt includes all page texts, book/chapter metadata | `LLMService.call` |
| `test_chapter_topic_planner_parses_output` | Valid JSON response parsed into `ChapterTopicPlan` | `LLMService.call` returns canned JSON |
| `test_chapter_topic_planner_retries_on_failure` | 3 retries with backoff | `LLMService.call` raises then succeeds |
| `test_chunk_processor_includes_planned_topics` | Prompt includes planned topic skeleton when provided | `LLMService.call` |
| `test_chunk_processor_parses_topic_assignment` | Response with `topic_assignment` field parsed correctly | `LLMService.call` returns canned JSON |
| `test_orchestrator_calls_planner_before_extraction` | Planner called before chunk loop, planned topics saved to job | `ChapterTopicPlannerService`, `ChunkProcessorService`, DB session |
| `test_orchestrator_initializes_state_from_plan` | RunningState.topic_guidelines_map pre-populated from plan | Mock planner output |
| `test_orchestrator_handles_unplanned_topics` | Unplanned topics created as new entries in accumulator | Mock chunk output with unplanned topic |
| `test_finalization_counts_deviations` | Deviation ratio calculated correctly from consolidation output | Mock consolidation output |
| `test_finalization_triggers_needs_review` | Chapter status set to `needs_review` when deviation > 30% | Mock consolidation with many deviations |
| `test_finalization_generates_curriculum_context` | `prior_topics_context` set on each topic (except first) | `LLMService.call` returns canned context |
| `test_topic_sync_includes_prior_topics_context` | TeachingGuideline.prior_topics_context populated from ChapterTopic | DB session with test data |
| `test_guideline_response_includes_prior_topics_context` | GuidelineResponse.prior_topics_context populated from DB | DB session with test data |
| `test_topic_adapter_passes_prior_topics_context` | TopicGuidelines.prior_topics_context set from GuidelineResponse | Mock GuidelineResponse |
| `test_master_tutor_prompt_includes_context` | System prompt includes "Prior Topics" section when context exists | Topic with prior_topics_context |
| `test_master_tutor_prompt_omits_context_when_null` | System prompt has no "Prior Topics" section when context is null | Topic without prior_topics_context |

### Integration tests

| Test | What it Verifies |
|------|------------------|
| `test_full_pipeline_with_planning` | End-to-end: plan → extract → finalize → context gen produces coherent topics with curriculum context |
| `test_pipeline_resume_restores_plan` | Resuming from a failed job restores planned topics from previous job |

### Manual verification

1. Process a real chapter (e.g., Grade 3 Chapter 1) through the updated pipeline
2. Verify topic count is reasonable (5-7 for a 23-page chapter)
3. Verify no overlapping page ranges
4. Verify `prior_topics_context` on Topic 4 mentions Topics 1-3
5. Sync to teaching_guidelines, start a tutoring session on Topic 4
6. Verify the tutor's system prompt includes the curriculum context
7. Verify the tutor references prior topics naturally (e.g., "You already learned about place value...")

---

## 10. Deployment Considerations

- **Migration order:** Deploy migration (`python db.py --migrate`) before deploying new code. The new columns are nullable, so the migration is backward-compatible — old code will simply ignore them.
- **No infrastructure changes.** No new Terraform resources, secrets, or environment variables.
- **Rollback plan:** If the planning phase produces poor results, the pipeline can be reverted by deploying the previous code version. Existing books are unaffected (PRD: non-goal to re-ingest). The new columns remain in the DB but are harmless (all nullable).
- **Feature flag:** Not needed. The feature is admin-only (book ingestion pipeline) and doesn't affect live tutoring sessions until a chapter is reprocessed and re-synced.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Planning LLM hits token limit on large chapters (40+ pages) | Low | Med | Most primary school chapters are <30 pages. If token limit is hit, fail gracefully and fall back to existing unplanned extraction. Add a page-count check before planning. |
| Planning adds too much latency to pipeline | Low | Low | Planning is one LLM call per chapter (~10-30s). Total pipeline is already ~5-10 min. Acceptable overhead. |
| Consolidation deviation threshold too strict/lenient at 30% | Med | Low | The threshold is a constant (`PLANNING_DEVIATION_THRESHOLD`). Easy to tune after observing real data. |
| `topic_assignment` backward compatibility with existing S3 audit data | Low | Low | Old S3 data uses `is_new`. New data uses `topic_assignment`. These are write-once audit artifacts — no code reads old S3 data during new processing. |
| `needs_review` chapters pile up without resolution UI | Med | Low | Chapters in `needs_review` can be reprocessed via the existing Reprocess button. Add `needs_review` to allowed statuses for reprocess. No new UI needed. |
| Curriculum context generation produces low-quality text | Low | Med | The context generation is a straightforward summarization task. If quality is poor, the tutor prompt simply includes weak context — it doesn't break anything. Can iterate on the prompt. |

---

## 12. Open Questions

1. **Token limit handling for large chapters:** Should we implement page summarization for chapters >40 pages now, or wait until we encounter one? **Recommendation:** Wait. All current books are primary school with short chapters. Add a log warning if page count exceeds 40, and fail gracefully if the LLM call fails due to token limits.

2. **Should the planner use a different LLM config key?** Currently all ingestion uses `book_ingestion_v2`. The planner needs `reasoning_effort="high"` while chunk extraction uses `"none"`. Since reasoning effort is set per-call (not per-config), a single config key works. If we later want to use a different model for planning (e.g., a reasoning model), we'd add a `book_ingestion_planner` config key. **Recommendation:** Use the same config key for now, override reasoning effort at the call site.

3. **Should `needs_review` block sync?** Currently, only `chapter_completed` chapters can be synced. Should `needs_review` also allow sync (since the topics are still finalized, just flagged)? **Recommendation:** Yes — allow sync from `needs_review` status. The topics are complete, just potentially suboptimal. The admin can review and reprocess if needed, but shouldn't be blocked from using them.
