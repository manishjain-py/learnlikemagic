# Tech Implementation Plan: Chapter Prerequisites (Refresher Topics)

**Date:** 2026-04-03 | **Status:** Draft | **PRD:** `docs/feature-development/chapter-prerequisites/prd.md`

---

## 1. Overview

Single pipeline step after explanation generation: identify prerequisites + generate refresher guideline + explanation cards (1 variant). Stored as a `TeachingGuideline` at `topic_sequence = 0`. Cards-only session — no interactive phase, no mastery, no scoring. Chapter landing page shows prerequisites to students.

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
| `tutor/models/session_state.py` | Add `is_refresher: bool = False` to `SessionState` |
| `tutor/services/session_service.py` | Persist `is_refresher` on session state, skip study plan, short-circuit `complete_card_phase()` |
| `tutor/services/topic_adapter.py` | Return 0-step `StudyPlan` for refresher (avoid default 5-step fallback) |
| `tutor/orchestration/orchestrator.py` | End session after cards for refresher |
| `shared/models/domain.py` | Add `is_refresher` field to `GuidelineMetadata` (or read raw JSON) |
| `llm-frontend/src/pages/ChatSession.tsx` | Hide "Explain differently" for single variant, change "Start practice" to "Done", handle `session_complete` action |
| `llm-frontend/src/pages/ChapterSelect.tsx` | Exclude refresher from chapter completion % |
| `llm-frontend/src/pages/ReportCardPage.tsx` | Exclude refresher from scorecard display |
| `llm-frontend/src/components/ModeSelection.tsx` | Hide Exam/Clarify Doubts for refresher topics |
| `llm-frontend/src/` | New chapter landing page component |

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

### 4.4 Session State — Persisting `is_refresher`

**Problem:** `create_new_session()` and `complete_card_phase()` are separate stateless API calls. If `is_refresher` is only read during creation but not persisted, the card-completion call won't know it's a refresher.

**Fix:** Add `is_refresher: bool = False` to `SessionState` model (`tutor/models/session_state.py`). Set it in `create_new_session()` by reading `guideline.metadata_json`. The flag survives serialization to `sessions.state_json` and is available in all subsequent API calls.

### 4.5 Session Creation — Refresher-Specific Behavior

**`session_service.py` — `create_new_session()`:**

- Read `metadata_json.is_refresher` from guideline → set `session.is_refresher = True`
- Reject `exam` and `clarify_doubts` modes (400 error)
- Skip `_generate_personalized_plan()` — no study plan needed

**`topic_adapter.py` — `_convert_study_plan()`:**

**Problem:** When `study_plan_record` is None, `_generate_default_plan()` creates a hardcoded 5-step plan (explain → check → practice). A refresher with `total_steps=5` would break the cards-only flow.

**Fix:** When `is_refresher`, return `StudyPlan(steps=[])` (0 steps). This avoids the default fallback. Pass `is_refresher` to `convert_guideline_to_topic()`.

### 4.6 Card Phase Completion — Short-Circuit for Refresher

**`session_service.py` — `complete_card_phase()`:**

**Problem:** This method unconditionally generates a v2 session plan (line ~976), generates a bridge turn (line ~979), and returns `{"action": "transition_to_interactive"}`. For refresher, this would launch an interactive phase that should never exist.

**Fix:** Add `is_refresher` branch at the top of `complete_card_phase()`:

```python
if session.is_refresher:
    session.is_paused = False
    # Mark session complete — no mastery, no scores
    return {
        "action": "session_complete",
        "message": "You've refreshed the basics and are ready to dive into the chapter!",
        "audio_text": "You've refreshed the basics and are ready to dive into the chapter!",
        "is_complete": True,
    }
```

Skip v2 plan generation, skip bridge turn, skip transition to interactive.

### 4.7 Backend Guard — "Explain Differently" for Single Variant

**Problem:** Even if frontend hides the button, an out-of-date client could send `explain_differently` action. With 1 variant, the code treats all-variants-exhausted as "student is confused" → generates a study plan + forces interactive mode.

**Fix:** In `complete_card_phase()`, when `is_refresher` and action is `explain_differently`: return the same variant again (or return the `session_complete` response). Never generate a study plan for a refresher.

### 4.8 `is_complete` Property — Zero Study Plan Steps

**Problem:** `SessionState.is_complete` returns `current_step > total_steps`. With `current_step=1` (default) and `total_steps=0`, this is immediately `True`, potentially short-circuiting before card phase begins.

**Fix:** For refresher sessions, `is_complete` should be driven by card phase completion, not study plan step count. Options:
- Check `is_refresher` in `is_complete` property: refresher is complete when card phase is done (tracked by existing `card_phase.phase == "complete"`)
- Or: set `current_step=0` at creation so `0 > 0` is False until explicitly advanced

### 4.9 Progress and Scorecard Exclusion

**Chapter completion %** (`ChapterSelect.tsx`): Exclude guidelines where `is_refresher = true` from the coverage average. Otherwise a chapter with 5 regular topics at 100% would show ~83%.

**Scorecard** (`ReportCardPage.tsx`): Filter out refresher topics. No mastery data exists, so showing them creates confusion.

**API:** The chapter/topic listing endpoints should include `is_refresher` in the response so the frontend can filter.

### 4.10 Re-Sync Behavior

Re-sync deletes ALL guidelines for a chapter including the refresher (existing cascade in `_delete_chapter_guidelines()`). This is by design — chapter content may have changed, making the old refresher stale.

**Operational note:** After re-sync, refresher must be regenerated (step 4 in pipeline). Sync response should include a warning: `"refresher_deleted": true` if a refresher existed. Documented in pipeline workflow below.

### 4.11 Chapter Landing Page Data

```python
@router.get("/chapters/{chapter_id}/landing")
def get_chapter_landing(book_id, chapter_id, db=Depends(get_db)):
    # Returns: chapter_summary, prerequisite_concepts (from refresher metadata),
    #          topic_list, refresher_guideline_id (if exists)
```

---

## 5. Frontend

### Chapter Landing Page
- New component shown when student visits a chapter
- **"What you'll learn"** section from `chapter_summary`
- **"What you'll need"** section from refresher's `prerequisite_concepts`
- Topic list below with refresher as first item

### Refresher Session
- Hide "Explain differently" button (single variant — `variantsShown >= available_variants` is immediately true, would show "I still need help" otherwise)
- Change "Start practice" button to "Done" or "I'm ready"
- Handle `"action": "session_complete"` response from backend — show warm closing message, no transition to interactive view
- No mastery/score display

### Mode Selection
- Hide Exam and Clarify Doubts for refresher topics (check `is_refresher` from topic metadata)

### Progress Display
- Exclude refresher from chapter completion percentage
- Exclude refresher from scorecard/report card

---

## 6. Pipeline Workflow

```
1. POST .../process                    (extract + finalize)
2. POST .../sync                       (teaching_guidelines — WARNING: deletes existing refresher)
3. POST .../generate-explanations      (cards for regular topics)
4. POST .../refresher/generate         (prerequisite analysis + refresher guideline + cards)
```

**Re-sync:** Steps 2-4 must all re-run. Step 2 deletes the refresher. Step 3 regenerates regular cards. Step 4 regenerates refresher.

---

## 7. Testing

| Test | Validates |
|------|-----------|
| `test_generate_refresher_with_cards` | Creates TeachingGuideline + TopicExplanation in one step |
| `test_generate_refresher_uses_explanation_cards` | Service loads existing cards as LLM input |
| `test_generate_refresher_idempotent` | Running twice replaces, doesn't duplicate |
| `test_generate_refresher_skips_introductory` | No refresher for chapters without prerequisites |
| `test_refresher_session_cards_only` | `complete_card_phase` returns `session_complete`, no interactive transition |
| `test_refresher_session_no_mastery` | No mastery scores recorded |
| `test_refresher_reject_exam_mode` | 400 on exam/clarify_doubts mode |
| `test_refresher_explain_differently_guard` | Backend rejects or ignores explain_differently for refresher |
| `test_refresher_is_complete_semantics` | Session not marked complete before cards are done |
| `test_refresher_state_persisted` | `is_refresher` survives session state serialization/deserialization |
| `test_refresher_excluded_from_progress` | Chapter completion % excludes refresher |
| `test_resync_deletes_refresher` | Sync cascade works, warning returned |
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
| `tutor/models/session_state.py` | MODIFY | Add `is_refresher` to SessionState |
| `tutor/services/session_service.py` | MODIFY | Persist `is_refresher`, short-circuit `complete_card_phase()` |
| `tutor/services/topic_adapter.py` | MODIFY | 0-step plan for refresher (avoid default fallback) |
| `shared/models/domain.py` | MODIFY | Add `is_refresher` to GuidelineMetadata |
| `llm-frontend/src/pages/ChatSession.tsx` | MODIFY | Hide buttons, handle `session_complete` action |
| `llm-frontend/src/pages/ChapterSelect.tsx` | MODIFY | Exclude refresher from progress % |
| `llm-frontend/src/pages/ReportCardPage.tsx` | MODIFY | Exclude refresher from scorecard |
| `llm-frontend/src/components/ModeSelection.tsx` | MODIFY | Hide non-teach_me modes |
| `llm-frontend/src/` | NEW | Chapter landing page component |
