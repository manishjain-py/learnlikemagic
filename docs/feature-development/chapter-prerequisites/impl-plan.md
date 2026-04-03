# Tech Implementation Plan: Chapter Prerequisites (Refresher Topics)

**Date:** 2026-04-03 | **Status:** Draft | **PRD:** `docs/feature-development/chapter-prerequisites/prd.md`

---

## 1. Overview

Generate a refresher `TeachingGuideline` at `topic_sequence = 0` per chapter. No new tables. Downstream systems (study plan generator, tutor prompts) recognize `is_refresher` flag for lighter behavior.

**Pipeline:** Sync → Generate Refresher → Generate Explanations (all topics incl. refresher)

---

## 2. Architecture

```
OFFLINE: Sync → RefresherTopicGeneratorService → TeachingGuideline (seq 0)
         → ExplanationGeneratorService (cards for refresher like any topic)

ONLINE:  SessionService reads is_refresher from metadata_json
         → StudyPlanGenerator: check-only steps, no practice
         → MasterTutor: refresher-mode rules (quick pace, low mastery bar)
         → Same session flow: cards → interactive → scorecard
```

### New modules

| Module | Purpose |
|--------|---------|
| `book_ingestion_v2/services/refresher_topic_generator_service.py` | Prerequisite analysis + guideline generation |
| `book_ingestion_v2/prompts/refresher_topic_generation.txt` | LLM prompt |

### Modified modules

| Module | Change |
|--------|--------|
| `book_ingestion_v2/api/sync_routes.py` | `/refresher/generate` endpoint |
| `book_ingestion_v2/constants.py` | `V2JobType.REFRESHER_GENERATION` |
| `study_plans/services/generator_service.py` | Lighter plan when `is_refresher` |
| `study_plans/prompts/session_plan_v2.txt` | Refresher planning instructions |
| `tutor/prompts/master_tutor_prompts.py` | REFRESHER MODE tutor rules |
| `tutor/services/session_service.py` | Read `is_refresher`, pass downstream |

---

## 3. Database

**No new tables.** Refresher is a `TeachingGuideline` row:

| Field | Value |
|-------|-------|
| `topic_key` | `"get-ready"` |
| `topic_title` | `"Get Ready for [Chapter Name]"` |
| `topic_sequence` | `0` |
| `metadata_json` | `{"is_refresher": true, "prerequisite_concepts": [...]}` |

Re-sync cascade deletes refresher (correct — content may have changed).

---

## 4. Backend

### 4.1 RefresherTopicGeneratorService

```python
class RefresherTopicGeneratorService:
    def generate_for_chapter(self, book_id, chapter_key) -> Optional[str]:
        guidelines = self._load_chapter_guidelines(book_id, chapter_key)  # excludes existing refresher
        self._delete_existing_refresher(book_id, chapter_key)  # idempotent
        chapter_context = self._build_chapter_context(guidelines)
        cross_chapter = self._build_cross_chapter_context(book_id, chapter_key)
        result = self._generate_refresher(chapter_context, cross_chapter)
        if result.skip_refresher:
            return None
        return self._store_refresher(guidelines[0], result)  # creates TeachingGuideline
```

**LLM output model:**

```python
class RefresherOutput(BaseModel):
    skip_refresher: bool
    skip_reason: Optional[str] = None
    prerequisite_concepts: list[PrerequisiteConcept]  # 3-5 items
    refresher_guideline: str   # full teaching guideline text
    topic_summary: str         # 15-30 words
```

### 4.2 Prompt

Receives: subject, grade, chapter title/summary, all topic titles+summaries+guideline excerpts, other chapters' topics for cross-referencing.

Tasks: identify assumed knowledge → filter out what's covered elsewhere in book → pick 3-5 critical prerequisites → generate guideline (warm-up framing, brief per concept, bridge to chapter) → skip if introductory chapter.

### 4.3 API

```python
@router.post("/refresher/generate", response_model=ProcessingJobResponse, status_code=202)
def generate_refresher(book_id, chapter_id, db=Depends(get_db)):
    # Validates chapter is synced, has topics. Background job, same pattern as explanation generation.
```

Also: `POST .../refresher/generate-all` for book-level batch.

### 4.4 Study Plan — Refresher Mode

`generate_session_plan()` receives `is_refresher` flag. When true, injects into prompt:

```
REFRESHER TOPIC MODE — prerequisite warm-up, not a regular lesson.
- One check_understanding step per prerequisite concept (3-5 total)
- NO guided_practice, independent_practice, or extend steps
- Correct → advance immediately. Wrong → brief hint + retry, then advance.
- Mastery bar: ~60%. Session target: 5-10 min.
```

### 4.5 Tutor Prompts — Refresher Mode

When `is_refresher = true`, inject into master tutor system prompt:

```
REFRESHER MODE — prerequisite warm-up, not a regular lesson.
PACE: One question per concept. Correct → advance. Don't linger.
DEPTH: Roughly right is good enough. Don't probe edge cases.
WRONG ANSWERS: 1st wrong → 1-sentence hint. 2nd wrong → brief re-explain + move on. No spiraling.
TRANSITIONS: "Next building block..." — clean breaks between concepts.
COMPLETION: Done once each concept is checked. Don't extend with practice.
```

### 4.6 Session Service — Flag Propagation

In `create_new_session()`, read `metadata_json.is_refresher` from guideline. Pass to study plan generation and store on session state for tutor prompt builder.

---

## 5. Frontend

No changes. Refresher appears in topic list automatically via `topic_sequence` ordering.

---

## 6. Pipeline Workflow

```
1. POST .../process          (extract + finalize)
2. POST .../sync             (teaching_guidelines)
3. POST .../refresher/generate
4. POST .../generate-explanations  (all topics incl. refresher)
```

---

## 7. Testing

| Test | Validates |
|------|-----------|
| `test_generate_refresher_creates_guideline` | Correct topic_key, sequence, metadata |
| `test_generate_refresher_idempotent` | Running twice replaces, doesn't duplicate |
| `test_generate_refresher_skips_introductory` | No refresher for chapters without prerequisites |
| `test_resync_clears_refresher` | Cascade delete works |
| `test_refresher_study_plan_lighter` | Check-only steps, no practice |
| `test_session_with_refresher` | Full session works: cards → interactive → scorecard |

---

## 8. Rollout

1. **Pilot:** One chapter, review quality, validate student experience
2. **Book-level:** All chapters of pilot book, iterate on prompt
3. **All books:** Standard pipeline step
