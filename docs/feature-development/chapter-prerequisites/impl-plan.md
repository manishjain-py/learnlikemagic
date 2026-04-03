# Tech Implementation Plan: Chapter Prerequisites (Refresher Topics)

**Date:** 2026-04-03
**Status:** Draft
**PRD:** `docs/feature-development/chapter-prerequisites/prd.md`
**Principles:** `docs/principles/prerequisites.md`

---

## 1. Overview

Generate a "refresher topic" as the first topic (`topic_sequence = 0`) of every chapter. The refresher covers the 3-5 foundational concepts the chapter assumes. It's a `TeachingGuideline` row — no new tables, no new session phases — but downstream systems (study plan generator, tutor prompts) recognize the `is_refresher` flag and adapt their behavior for breadth-over-depth, multi-concept review.

**High-level approach:**
- New `RefresherTopicGeneratorService` — reads all synced guidelines for a chapter, calls LLM to identify prerequisites, creates a new TeachingGuideline
- New prompt: `refresher_topic_generation.txt`
- New API endpoint: `POST .../refresher/generate` (background job, same pattern as explanation generation)
- After refresher is created, existing explanation generation runs for it like any other topic
- Refresher identified by `topic_key = "get-ready"` and `metadata_json.is_refresher = true`
- Study plan generator produces lighter plans (check-only steps, no deep practice)
- Master tutor gets refresher-specific rules (move quickly, don't deep-dive, easier completion bar)

---

## 2. Architecture Changes

### Data flow diagram

```
OFFLINE (ingestion pipeline)
═══════════════════════════════════════════════════════════════

  Finalize Chapter
       ↓
  TopicSyncService.sync_chapter()
       ↓ (creates TeachingGuideline rows — sequence 1, 2, 3...)
  RefresherTopicGeneratorService.generate_for_chapter()
       ↓ (reads all guidelines, LLM identifies prerequisites)
       ↓ (creates TeachingGuideline with sequence 0)
  ExplanationGeneratorService (runs for ALL guidelines incl. refresher)
       ↓ (generates cards for refresher just like any topic)
  topic_explanations table

═══════════════════════════════════════════════════════════════
ONLINE (session time) — REFRESHER-AWARE BEHAVIOR
═══════════════════════════════════════════════════════════════

  Student sees "Get Ready for [Chapter]" as first topic
       ↓
  SessionService reads metadata_json.is_refresher = true
       ↓
  StudyPlanGenerator → lighter plan (check-only steps, no practice)
  MasterTutor → refresher-mode rules (quick pace, low mastery bar)
       ↓
  Same session flow: cards → interactive → scorecard
  (but tutor moves faster, session is 5-10 min not 20-40)
```

### New modules

| Module | Purpose |
|--------|---------|
| `book_ingestion_v2/services/refresher_topic_generator_service.py` | Analyzes chapter content, generates prerequisite-focused TeachingGuideline |
| `book_ingestion_v2/prompts/refresher_topic_generation.txt` | Prompt for identifying prerequisites and writing refresher guidelines |

### Modified modules

| Module | Change |
|--------|--------|
| `book_ingestion_v2/api/sync_routes.py` | New `/refresher/generate` endpoint |
| `book_ingestion_v2/constants.py` | New `V2JobType.REFRESHER_GENERATION` enum value |

### Modified modules (downstream — refresher-aware behavior)

| Module | Change |
|--------|--------|
| `study_plans/services/generator_service.py` | Detect `is_refresher` flag, generate lighter plan (check-only steps, no practice/extend) |
| `study_plans/prompts/session_plan_v2.txt` | Add refresher-specific planning instructions |
| `tutor/prompts/master_tutor_prompts.py` | Inject refresher-mode tutor rules when `is_refresher = true` |
| `tutor/services/session_service.py` | Read `metadata_json.is_refresher` from guideline, pass flag through to study plan generation and tutor prompt context |

### Unchanged (works automatically)

| Module | Why |
|--------|-----|
| `shared/models/entities.py` | Refresher is a standard `TeachingGuideline` row |
| `tutor/orchestration/orchestrator.py` | Orchestration logic unchanged — lighter plan means fewer steps, not different orchestration |
| `book_ingestion_v2/services/explanation_generator_service.py` | Generates cards for refresher guideline normally — guideline text guides card count/depth |
| `llm-frontend/` | Displays refresher in topic list by `topic_sequence` order, no UI changes |

---

## 3. Database Changes

**No new tables.** The refresher is a standard `TeachingGuideline` row with:

| Field | Value |
|-------|-------|
| `topic_key` | `"get-ready"` |
| `topic_title` | `"Get Ready for [Chapter Name]"` |
| `topic_sequence` | `0` (before all content topics which start at 1) |
| `topic_summary` | `"Quick refresher of the building blocks you'll need for this chapter"` |
| `metadata_json` | `{"is_refresher": true, "prerequisite_concepts": ["concept1", "concept2", ...]}` |
| `guideline` | LLM-generated teaching guidelines focused on prerequisites |
| `book_id`, `chapter_key`, etc. | Same as other topics in the chapter |

**Identification query:**
```sql
SELECT * FROM teaching_guidelines
WHERE book_id = :book_id
  AND chapter_key = :chapter_key
  AND topic_key = 'get-ready';
```

**Cascade behavior:** When `TopicSyncService._delete_chapter_guidelines()` runs on re-sync, it deletes ALL guidelines for the chapter including the refresher. This is correct — the refresher should be regenerated after re-sync since the chapter content may have changed.

### New enum value

```python
# book_ingestion_v2/constants.py
class V2JobType(str, Enum):
    OCR = "v2_ocr"
    TOPIC_EXTRACTION = "v2_topic_extraction"
    REFINALIZATION = "v2_refinalization"
    EXPLANATION_GENERATION = "v2_explanation_generation"
    VISUAL_ENRICHMENT = "v2_visual_enrichment"
    REFRESHER_GENERATION = "v2_refresher_generation"  # NEW
```

---

## 4. Backend Changes

### 4.1 RefresherTopicGeneratorService

**File:** `book_ingestion_v2/services/refresher_topic_generator_service.py`

```python
class RefresherTopicGeneratorService:
    """Generates a prerequisite refresher topic for a chapter.

    Reads all synced TeachingGuidelines for the chapter, calls LLM to
    identify prerequisites, and creates a new TeachingGuideline at
    topic_sequence=0.
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service

    def generate_for_chapter(
        self, book_id: str, chapter_key: str
    ) -> Optional[str]:
        """Generate refresher topic. Returns guideline_id or None if skipped."""
        # 1. Load all existing guidelines for the chapter
        guidelines = self._load_chapter_guidelines(book_id, chapter_key)
        if not guidelines:
            return None

        # 2. Delete any existing refresher for this chapter (idempotent)
        self._delete_existing_refresher(book_id, chapter_key)

        # 3. Gather context for LLM: topic titles, summaries, key guideline excerpts
        chapter_context = self._build_chapter_context(guidelines)

        # 4. Also gather other chapters' topics in the same book for cross-referencing
        other_chapters_context = self._build_cross_chapter_context(book_id, chapter_key)

        # 5. Call LLM to identify prerequisites and generate refresher guideline
        result = self._generate_refresher(chapter_context, other_chapters_context)
        if not result or result.skip_refresher:
            return None

        # 6. Create TeachingGuideline row
        guideline_id = self._store_refresher(
            guidelines[0],  # template for book/chapter metadata
            result,
        )
        return guideline_id
```

**Key methods:**

- `_load_chapter_guidelines()` — queries `TeachingGuideline` for the chapter, excludes existing refresher (`topic_key != 'get-ready'`)
- `_delete_existing_refresher()` — deletes any `TeachingGuideline` with `topic_key = 'get-ready'` for this chapter (+ cascades to its explanation cards)
- `_build_chapter_context()` — extracts topic titles, summaries, and first ~300 chars of each guideline. Keeps prompt concise.
- `_build_cross_chapter_context()` — loads topic titles/summaries from OTHER chapters in the same book, so the LLM can identify which prerequisites are covered elsewhere vs. truly external
- `_generate_refresher()` — calls LLM with the prompt, parses structured output
- `_store_refresher()` — creates the TeachingGuideline row with sequence 0

**LLM output model:**

```python
class PrerequisiteConcept(BaseModel):
    concept: str           # e.g., "Place value: tens and ones"
    why_needed: str        # e.g., "Multiplication decomposes numbers by place"
    covered_in_book: bool  # Whether another chapter in the book teaches this

class RefresherOutput(BaseModel):
    skip_refresher: bool = Field(
        description="True if chapter has no meaningful prerequisites"
    )
    skip_reason: Optional[str] = None
    prerequisite_concepts: list[PrerequisiteConcept] = Field(
        default_factory=list,
        description="3-5 critical prerequisites identified"
    )
    refresher_guideline: str = Field(
        default="",
        description="Full teaching guideline text for the refresher topic"
    )
    topic_summary: str = Field(
        default="",
        description="15-30 word summary of what the refresher covers"
    )
```

### 4.2 Prompt: `refresher_topic_generation.txt`

**File:** `book_ingestion_v2/prompts/refresher_topic_generation.txt`

The prompt receives:
- Subject, grade, board
- Chapter title and summary
- All topic titles, summaries, and guideline excerpts for the chapter
- Topic titles/summaries from other chapters in the book (for cross-referencing)

The prompt instructs the LLM to:
1. Read all topics and identify what knowledge they ASSUME the student already has
2. Filter out prerequisites that are covered by earlier chapters in the same book — those aren't gaps (the student would have encountered them)
3. Identify the 3-5 most critical prerequisites that students are most likely to have gaps in
4. For each prerequisite, note the specific aspect needed (not the full topic)
5. Generate a teaching guideline following the same format as regular guidelines, but:
   - Frame as a warm-up: "Get Ready for [Chapter]"
   - Cover each prerequisite briefly (1-2 paragraphs each)
   - Bridge each concept to the chapter: "You'll use this when..."
   - Include a check question per concept
   - Instruct the tutor to move quickly if the student shows prior knowledge
6. If the chapter is introductory (no meaningful prerequisites), set `skip_refresher = true`

**Prompt structure:**
```
You are analyzing a textbook chapter to identify prerequisite knowledge gaps.

## Chapter to Analyze
Subject: {subject}
Grade: {grade}
Chapter: {chapter_title}
Summary: {chapter_summary}

## Topics in This Chapter
{for each topic: title, summary, first 300 chars of guideline}

## Other Chapters in This Book
{for each other chapter: title, topic titles — so you know what's covered elsewhere}

## Your Task
...
```

### 4.3 API Endpoint

**File:** `book_ingestion_v2/api/sync_routes.py` (add to existing router)

```python
@router.post("/refresher/generate",
    response_model=ProcessingJobResponse,
    status_code=status.HTTP_202_ACCEPTED)
def generate_refresher(
    book_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
):
    """Generate a prerequisite refresher topic for a chapter.

    Requires chapter to be synced. Runs as a background job.
    Idempotent — replaces any existing refresher for this chapter.
    """
    # Validate chapter exists, is synced, has guidelines
    _validate_chapter_ownership(book_id, chapter_id, db)
    chapter = ChapterRepository(db).get_by_id(chapter_id)
    chapter_key = f"chapter-{chapter.chapter_number}"

    guidelines_count = db.query(TeachingGuideline).filter(
        TeachingGuideline.book_id == book_id,
        TeachingGuideline.chapter_key == chapter_key,
        TeachingGuideline.topic_key != "get-ready",
    ).count()
    if guidelines_count == 0:
        raise HTTPException(400, "Chapter has no synced topics")

    job_service = ChapterJobService(db)
    job_id = job_service.acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        job_type=V2JobType.REFRESHER_GENERATION.value,
        total_items=1,
    )

    run_in_background_v2(
        _run_refresher_generation, job_id, book_id, chapter_id
    )

    return job_service.get_job(job_id)
```

**Background task function** (`_run_refresher_generation`):
- Creates fresh DB session (same pattern as `_run_explanation_generation`)
- Loads LLM config (uses `"explanation_generator"` config — same quality tier)
- Calls `RefresherTopicGeneratorService.generate_for_chapter()`
- Updates job status on completion/failure

### 4.4 Book-Level Refresher Generation

Add a convenience endpoint to generate refreshers for all chapters in a book:

```python
@router.post("/refresher/generate-all",
    response_model=ProcessingJobResponse,
    status_code=status.HTTP_202_ACCEPTED)
def generate_refreshers_for_book(
    book_id: str,
    db: Session = Depends(get_db),
):
    """Generate refresher topics for all synced chapters in a book."""
    # ...iterates chapters, generates refresher for each
```

### 4.5 Refresher-Aware Study Plan Generation

**File:** `study_plans/services/generator_service.py`

The study plan generator needs to know when it's planning for a refresher topic. A refresher covers 3-5 separate prerequisite concepts at shallow depth — fundamentally different from a regular topic that covers one concept deeply.

**How the flag flows:**

```
TeachingGuideline.metadata_json → {"is_refresher": true}
  ↓
SessionService._generate_personalized_plan()
  ↓ (reads metadata_json, passes is_refresher to generator)
StudyPlanGeneratorService.generate_session_plan()
  ↓ (injects refresher instructions into prompt)
Lighter study plan output
```

**Changes to `generate_session_plan()`:**

```python
def generate_session_plan(
    self, guideline, explanation_summaries, card_titles,
    variants_shown, student_context=None,
    is_refresher: bool = False,  # NEW
) -> Dict[str, Any]:
    # ... existing code ...
    refresher_block = ""
    if is_refresher:
        refresher_block = REFRESHER_PLAN_INSTRUCTIONS
    prompt = self._session_plan_prompt.format(
        ...,
        refresher_instructions=refresher_block,
    )
```

**Refresher plan instructions (injected into prompt):**

```
## REFRESHER TOPIC MODE

This is a prerequisite refresher, NOT a regular lesson. The topic covers
multiple independent concepts at shallow depth. Generate a LIGHTER plan:

- One `check_understanding` step per prerequisite concept (3-5 steps total)
- NO `guided_practice`, `independent_practice`, or `extend` steps
- Each step tests ONE prerequisite concept with a quick question
- If the student gets it right: advance immediately
- If the student gets it wrong: brief re-explanation + one retry, then advance
- Target session length: 5-10 minutes (not 20-40)
- Mastery bar: ~60% (basic recall), not ~80% (deep understanding)
- The plan should feel like a warm-up checklist, not a deep lesson
```

### 4.6 Refresher-Aware Tutor Prompts

**File:** `tutor/prompts/master_tutor_prompts.py`

When `is_refresher = true`, inject a section into the master tutor system prompt:

```
### REFRESHER MODE — ACTIVE

This session is a prerequisite warm-up, not a regular lesson. You are
reviewing multiple independent concepts briefly before the student starts
the chapter. Follow these rules:

PACE: Move quickly. One question per concept. Correct answer → "Great!"
and advance. Don't linger.

DEPTH: Shallow is fine. If a student answers roughly right, accept it.
Don't probe for edge cases or push for deeper understanding — that's the
chapter's job.

WRONG ANSWERS: If the student gets it wrong:
- 1st wrong: Give a 1-sentence hint and let them retry
- 2nd wrong: Give a brief 2-sentence re-explanation and move on
- Do NOT spiral into 3+ attempts or strategy switches on a single concept

TRANSITIONS: You're covering multiple unrelated concepts. Between each:
"Great! Next building block..." — clean break, no need to connect concepts
to each other.

TONE: "Quick warm-up before the fun stuff!" Build excitement for the
chapter ahead. This is pre-game, not the game itself.

COMPLETION: The session is complete once each prerequisite concept has
been checked (even with moderate understanding). Don't extend with extra
practice rounds.
```

**How the flag flows to the tutor:**

```
SessionState.topic.study_plan.metadata
  ↓ (or: session_service reads guideline.metadata_json at session creation)
SessionState stores is_refresher flag
  ↓
master_tutor_prompts.py checks flag when building system prompt
  ↓
Injects REFRESHER MODE block (or omits it for regular topics)
```

**Implementation option:** Add `is_refresher: bool = False` to `SessionState` or `Topic` model. Set it in `SessionService.create_new_session()` by reading `guideline.metadata_json`. The tutor prompt builder checks this flag.

### 4.7 Session Service — Reading the Refresher Flag

**File:** `tutor/services/session_service.py`

In `create_new_session()`, after loading the guideline:

```python
# Detect refresher topic
is_refresher = False
if guideline.metadata_json:
    try:
        meta = json.loads(guideline.metadata_json) if isinstance(guideline.metadata_json, str) else guideline.metadata_json
        is_refresher = meta.get("is_refresher", False)
    except (json.JSONDecodeError, AttributeError):
        pass

# Pass to study plan generation
if not study_plan_record and mode == "teach_me" and user_id:
    study_plan_record = self._generate_personalized_plan(
        guideline, user_id, student_context,
        is_refresher=is_refresher,  # NEW
    )
```

The `is_refresher` flag is also stored on the session state so the tutor prompt builder can access it.

---

## 5. Frontend Changes

**No frontend code changes required.**

The refresher topic appears in the topic list automatically because:
- Topics are queried by `book_id` + `chapter_key` and ordered by `topic_sequence`
- The refresher has `topic_sequence = 0`, so it appears first
- It has a descriptive title ("Get Ready for [Chapter]") and summary
- Clicking it starts a normal session — cards, interactive teaching, scorecard

**Optional future enhancement:** A small visual indicator (icon or badge) to distinguish the warm-up topic from content topics. Not required for v1.

---

## 6. Pipeline Integration

### Recommended workflow (manual)

```
1. Process chapter (extract + finalize)     POST .../process
2. Sync to teaching_guidelines              POST .../sync
3. Generate refresher topic                 POST .../refresher/generate
4. Generate explanations (all topics)       POST .../generate-explanations
```

Step 3 creates the refresher TeachingGuideline. Step 4 generates explanation cards for ALL guidelines including the refresher.

### Future: Automated pipeline

The `/process` endpoint could be extended to auto-trigger steps 2-4 sequentially after extraction completes. Not in scope for v1 — keep the steps explicit until the feature is validated.

---

## 7. Testing Strategy

### Unit tests

| Test | What it validates |
|------|-------------------|
| `test_generate_refresher_creates_guideline` | Service creates a TeachingGuideline with correct topic_key, sequence, metadata |
| `test_generate_refresher_idempotent` | Running twice replaces old refresher, doesn't duplicate |
| `test_generate_refresher_skips_when_no_prerequisites` | Sets `skip_refresher=true` for introductory chapters |
| `test_delete_existing_refresher_cascades` | Deleting refresher also removes its explanation cards |
| `test_cross_chapter_context` | Service correctly loads other chapters' topics for cross-referencing |
| `test_refresher_excluded_from_own_context` | Existing refresher isn't included when analyzing chapter prerequisites |

### Integration tests

| Test | What it validates |
|------|-------------------|
| `test_full_pipeline_with_refresher` | Sync → refresher → explanations generates a complete refresher topic with cards |
| `test_resync_clears_refresher` | Re-syncing a chapter deletes the refresher (cascade), requiring regeneration |
| `test_session_with_refresher_topic` | Student can start a session on the refresher topic, sees cards, does interactive teaching |

### Manual QA

- Process a chapter end-to-end, generate refresher, generate explanations
- Verify refresher appears as first topic in the app
- Start a session on the refresher — confirm cards cover relevant prerequisites
- Confirm regular topics still work identically
- Confirm re-sync + regenerate produces correct results

---

## 8. Rollout Plan

**Phase 1: Single chapter pilot**
- Generate refresher for one chapter of one book
- Review guideline quality and explanation card quality
- Validate student experience (internal testing)

**Phase 2: Book-level rollout**
- Generate refreshers for all chapters of the pilot book
- Monitor: do students who do the refresher perform better on Topic 1?
- Iterate on prompt based on content quality review

**Phase 3: All books**
- Generate refreshers for all synced books
- Add to standard pipeline documentation

---

## 9. Key Files Summary

| File | Status | Purpose |
|------|--------|---------|
| `book_ingestion_v2/services/refresher_topic_generator_service.py` | NEW | Core service — prerequisite analysis + guideline generation |
| `book_ingestion_v2/prompts/refresher_topic_generation.txt` | NEW | LLM prompt for prerequisite identification |
| `book_ingestion_v2/api/sync_routes.py` | MODIFY | Add `/refresher/generate` endpoint |
| `book_ingestion_v2/constants.py` | MODIFY | Add `REFRESHER_GENERATION` job type |
| `study_plans/services/generator_service.py` | MODIFY | Refresher-aware plan generation (lighter steps, lower mastery bar) |
| `study_plans/prompts/session_plan_v2.txt` | MODIFY | Add refresher plan instructions block |
| `tutor/prompts/master_tutor_prompts.py` | MODIFY | Inject REFRESHER MODE tutor rules |
| `tutor/services/session_service.py` | MODIFY | Read `is_refresher` from metadata_json, pass downstream |
| `docs/principles/prerequisites.md` | NEW | Pedagogical principles |
| `docs/feature-development/chapter-prerequisites/prd.md` | NEW | Product requirements |
