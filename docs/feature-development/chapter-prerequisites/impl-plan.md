# Tech Implementation Plan: Chapter Prerequisites (Refresher Topics)

**Date:** 2026-04-03 | **Status:** Draft | **PRD:** `docs/feature-development/chapter-prerequisites/prd.md`

---

## 1. Overview

Single pipeline step after explanation generation: identify prerequisites + generate refresher guideline + generate explanation cards (1 variant). Stored as a `TeachingGuideline` at `topic_sequence = 0`. Cards-only session — no interactive phase, no mastery, no scoring. Chapter landing page shows prerequisites to students.

---

## 2. Architecture

```
OFFLINE:
  ... → Sync → Generate Explanations (regular topics)
    → RefresherTopicGeneratorService.generate_for_chapter()
      reads all guidelines + explanation cards
      LLM identifies prerequisites
      generates refresher guideline + cards in one shot
      stores TeachingGuideline (seq 0) + TopicExplanation (1 variant)

ONLINE:
  Chapter Landing Page:
    reads refresher's metadata_json.prerequisite_concepts
    shows "What you'll learn" + "What you'll need"

  Refresher Session (Teach Me only):
    card phase → "clear" → session complete (warm message, no mastery)
```

### New modules

| Module | Purpose |
|--------|---------|
| `book_ingestion_v2/services/refresher_topic_generator_service.py` | Prerequisite analysis + guideline + card generation |
| `book_ingestion_v2/prompts/refresher_topic_generation.txt` | LLM prompt |

### Modified modules

| Module | Change |
|--------|--------|
| `book_ingestion_v2/api/sync_routes.py` | `/refresher/generate` endpoint |
| `book_ingestion_v2/constants.py` | `V2JobType.REFRESHER_GENERATION` |
| `tutor/services/session_service.py` | Detect `is_refresher`: skip study plan generation, skip interactive phase, cards-only flow, no mastery tracking |
| `tutor/orchestration/orchestrator.py` | On card phase complete for refresher: end session with warm message (no transition to interactive) |
| `llm-frontend/` | Chapter landing page component, refresher session handling (no "explain differently", warm completion message) |

---

## 3. Database

**No new tables.** Refresher is a `TeachingGuideline` row:

| Field | Value |
|-------|-------|
| `topic_key` | `"get-ready"` |
| `topic_title` | `"Get Ready for [Chapter Name]"` |
| `topic_sequence` | `0` |
| `metadata_json` | `{"is_refresher": true, "prerequisite_concepts": [{"concept": "...", "why_needed": "..."}]}` |

Its explanation cards stored in `topic_explanations` with `variant_key = "A"` (single variant).

---

## 4. Backend

### 4.1 RefresherTopicGeneratorService

```python
class RefresherTopicGeneratorService:
    def generate_for_chapter(self, book_id, chapter_key) -> Optional[str]:
        guidelines = self._load_chapter_guidelines(book_id, chapter_key)
        explanation_cards = self._load_explanation_cards(guidelines)
        self._delete_existing_refresher(book_id, chapter_key)

        result = self._generate_refresher(guidelines, explanation_cards)
        if result.skip_refresher:
            return None

        guideline_id = self._store_guideline(guidelines[0], result)
        self._store_explanation_cards(guideline_id, result.cards)
        return guideline_id
```

**LLM output model:**

```python
class RefresherOutput(BaseModel):
    skip_refresher: bool
    skip_reason: Optional[str] = None
    prerequisite_concepts: list[PrerequisiteConcept]  # concept + why_needed
    refresher_guideline: str
    topic_summary: str
    cards: list[ExplanationCardOutput]  # single variant, generated in same call
```

### 4.2 Prompt

Receives: subject, grade, chapter title/summary, all topic titles + summaries + guideline excerpts + explanation cards content. Also other chapters' topics for cross-referencing.

Tasks: analyze what knowledge the chapter assumes (using explanation card content for richer signal) → identify critical prerequisites (recommend 3-5, use judgment) → generate refresher guideline (warm-up framing, bridge to chapter) → generate explanation cards (one per prerequisite, ELIF principles) → skip if introductory chapter.

### 4.3 API

```python
@router.post("/refresher/generate", response_model=ProcessingJobResponse, status_code=202)
def generate_refresher(book_id, chapter_id, db=Depends(get_db)):
    # Validates chapter is synced and has explanation cards. Background job.
```

Also: `POST .../refresher/generate-all` for book-level batch.

### 4.4 Session Flow Changes

**`session_service.py`** — In `create_new_session()`:
- Read `metadata_json.is_refresher` from guideline
- If refresher: skip study plan generation, set session mode to cards-only
- Only allow `teach_me` mode (reject `exam` and `clarify_doubts`)

**`orchestrator.py`** — On card phase completion:
- If refresher: end session immediately with warm closing message
- No transition to interactive study plan phase
- Session marked complete, no mastery scores recorded

### 4.5 Chapter Landing Page Data

New API endpoint or extend existing chapter endpoint:

```python
@router.get("/chapters/{chapter_id}/landing")
def get_chapter_landing(book_id, chapter_id, db=Depends(get_db)):
    # Returns: chapter_summary, prerequisite_concepts (from refresher metadata),
    #          topic_list, refresher_guideline_id (if exists)
```

Frontend reads `prerequisite_concepts` from the refresher topic's `metadata_json` to display "What you'll need" section.

---

## 5. Frontend

### Chapter Landing Page
- New component shown when student visits a chapter
- **"What you'll learn"** section from `chapter_summary`
- **"What you'll need"** section from refresher's `prerequisite_concepts`
- Topic list below with refresher as first item

### Refresher Session
- No "explain differently" button (single variant)
- On completion: warm message ("You've refreshed the basics and are ready to dive into the chapter!")
- No mastery/score display

---

## 6. Pipeline Workflow

```
1. POST .../process                    (extract + finalize)
2. POST .../sync                       (teaching_guidelines)
3. POST .../generate-explanations      (cards for regular topics)
4. POST .../refresher/generate         (prerequisite analysis + refresher guideline + cards)
```

---

## 7. Testing

| Test | Validates |
|------|-----------|
| `test_generate_refresher_with_cards` | Creates TeachingGuideline + TopicExplanation in one step |
| `test_generate_refresher_uses_explanation_cards` | Service loads existing cards as LLM input |
| `test_generate_refresher_idempotent` | Running twice replaces, doesn't duplicate |
| `test_generate_refresher_skips_introductory` | No refresher for chapters without prerequisites |
| `test_refresher_session_cards_only` | No interactive phase, session completes after cards |
| `test_refresher_session_no_mastery` | No mastery scores recorded |
| `test_refresher_reject_exam_mode` | Only teach_me allowed |
| `test_chapter_landing_page` | Returns chapter summary + prerequisite concepts |

---

## 8. Rollout

1. **Pilot:** One chapter — review prerequisite identification quality + card quality
2. **Book-level:** All chapters of pilot book, iterate on prompt
3. **All books:** Standard pipeline step

---

## 9. Key Files

| File | Status | Purpose |
|------|--------|---------|
| `book_ingestion_v2/services/refresher_topic_generator_service.py` | NEW | Prerequisite analysis + guideline + card generation |
| `book_ingestion_v2/prompts/refresher_topic_generation.txt` | NEW | LLM prompt |
| `book_ingestion_v2/api/sync_routes.py` | MODIFY | `/refresher/generate` endpoint |
| `book_ingestion_v2/constants.py` | MODIFY | `REFRESHER_GENERATION` job type |
| `tutor/services/session_service.py` | MODIFY | Cards-only flow for refresher, no study plan |
| `tutor/orchestration/orchestrator.py` | MODIFY | End session after cards for refresher |
| `llm-frontend/src/` | MODIFY | Chapter landing page, refresher session UX |
