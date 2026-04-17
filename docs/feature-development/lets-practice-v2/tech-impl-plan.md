# Tech Implementation Plan: Let's Practice (v2 — Batch Drill Redesign)

**Date:** 2026-04-17
**Status:** Draft
**PRD:** `docs/feature-development/lets-practice-v2/prd.md`

---

## 1. Overview

Let's Practice v2 replaces the existing Exam mode with an offline-first batch drill: a pre-generated question bank per topic, silent answering, one-tap submit, background LLM grading, per-question evaluation cards, and persistent attempt history.

Build order:

1. **Schema + repositories** — two new tables (`practice_questions`, `practice_attempts`).
2. **Ingestion stage** — question-bank generator as a new last stage in the V2 pipeline, reusing the review/refine pattern from `check_in_enrichment_service`.
3. **Runtime services** — set selection/locking, auto-save, submit, background grading (deterministic for structured formats; LLM for free-form and per-pick rationales).
4. **API** — new `/practice` router (REST only — no WebSocket, no agent turn loop).
5. **Frontend** — new Practice landing, question-card renderer (reusing all 11 existing activity components), submit/review flow, results, banner, history.
6. **Deletion** — remove Exam mode code + `practice_prompts.py` + exam review page + exam session paths.
7. **Scorecard + docs cleanup.**

Practice is deliberately **outside the chat-based tutor orchestrator**. It has no conversation, no streaming, no agent — it is REST CRUD plus a threaded grading worker. Treating it as a tutor mode would force it through machinery designed for turn-by-turn conversation.

---

## 2. Architecture Changes

### System diagram

```
┌─────────────────────── Frontend ────────────────────────┐
│ ModeSelection → PracticeLanding → PracticeRunner        │
│                                      ↓                  │
│                              ReviewScreen → Submit      │
│                                                         │
│ TopBanner (poll /practice/attempts/recent)              │
│         ↓ tap                                           │
│ PracticeResults → PracticeReview (card-by-card)         │
│                                                         │
│ PracticeHistory (list of past attempts)                 │
└────────────────────────────┬────────────────────────────┘
                             │ REST
┌────────────────────────────▼────────────────────────────┐
│ Backend — NEW /practice router                          │
│   ├─ attempts CRUD + submit + retry-grading             │
│   ├─ availability + history                             │
│   └─ admin bank viewer (under /admin/v2/books/…)        │
│                                                         │
│ tutor/services/practice_service.py                      │
│   ├─ start_or_resume_attempt(user, guideline_id)        │
│   ├─ save_answer(attempt_id, q_idx, answer)             │
│   └─ submit_attempt(attempt_id) → spawns grading thread │
│                                                         │
│ tutor/services/practice_grading_service.py              │
│   ├─ grade_structured(question, answer) [deterministic] │
│   ├─ grade_freeform(question, answer) [LLM]             │
│   └─ explain_wrong_pick(question, pick) [LLM]           │
│                                                         │
│ book_ingestion_v2/services/                             │
│   └─ practice_bank_generator_service.py                 │
│       (generate → review/refine N rounds → validate     │
│        → top-up if count < 30 → store)                  │
└────────────────────────────┬────────────────────────────┘
                             │ SQLAlchemy
┌────────────────────────────▼────────────────────────────┐
│ DB — NEW tables                                         │
│   practice_questions (30–40 rows per guideline)         │
│   practice_attempts  (1 row per submitted attempt)      │
└─────────────────────────────────────────────────────────┘
```

### New modules and major changes

**New backend files:**
- `tutor/api/practice.py` — REST router (mounted under `/practice`).
- `tutor/services/practice_service.py` — attempt lifecycle: set creation, auto-save, submit.
- `tutor/services/practice_grading_service.py` — grading (deterministic + LLM).
- `tutor/prompts/practice_grading.py` — LLM prompt templates (freeform grading, wrong-pick rationale).
- `shared/repositories/practice_question_repository.py` — bank CRUD.
- `shared/repositories/practice_attempt_repository.py` — attempt CRUD.
- `book_ingestion_v2/services/practice_bank_generator_service.py` — offline bank generation.
- `book_ingestion_v2/prompts/practice_bank_generation.txt` — bank generation prompt.
- `book_ingestion_v2/prompts/practice_bank_review_refine.txt` — correctness-review prompt.

**Modified backend files:**
- `shared/models/entities.py` — add `PracticeQuestion`, `PracticeAttempt` models.
- `db.py` — add migration hook `_apply_practice_tables()`; add LLM config seeds for `practice_bank_generator`, `practice_grader`; **delete** V1 `book_ingestion` config (already done) and remove exam-mode-specific code.
- `book_ingestion_v2/constants.py` — add `V2JobType.PRACTICE_BANK_GENERATION`.
- `book_ingestion_v2/api/sync_routes.py` — add `POST /generate-practice-banks`, `GET /practice-bank-status`, `GET /practice-banks/{guideline_id}` (admin viewer).
- `main.py` — register `practice` router; stop importing exam-specific pieces after deletion.
- `tutor/api/sessions.py` — remove `/sessions/{id}/end-exam`, `/sessions/{id}/exam-review`, `ResumableSessionResponse` exam paths; remove exam references from `_save_session_to_db`.
- `tutor/orchestration/orchestrator.py` — delete `_process_exam_turn`, `generate_exam_welcome`, `_build_exam_feedback`; remove `"exam"` from the mode dispatch.
- `tutor/services/session_service.py` — delete exam branches in `create_new_session`, `_find_incomplete_session`, `end_exam`.
- `tutor/services/report_card_service.py` — rename exam-score accumulator to practice-score; read from `practice_attempts` instead of `sessions`.
- `tutor/models/session_state.py` — delete `ExamQuestion`, `ExamFeedback`, all `exam_*` fields on `SessionState`; simplify `is_complete` by removing the exam branch.
- `tutor/models/messages.py` + `shared/models/schemas.py` — delete `EndExamResponse`, `ExamReviewResponse`, `ExamReviewQuestion`.

**Deleted backend files:**
- `tutor/services/exam_service.py`
- `tutor/prompts/exam_prompts.py`
- `tutor/prompts/practice_prompts.py` (old teacher-in-the-loop prompts).

**New frontend files:**
- `llm-frontend/src/pages/PracticeLandingPage.tsx` — entry after tapping Let's Practice tile.
- `llm-frontend/src/pages/PracticeRunner.tsx` — question card sequencer + review screen + submit.
- `llm-frontend/src/pages/PracticeResultsPage.tsx` — score + Reteach / Practice again / drill-down.
- `llm-frontend/src/pages/PracticeReviewPage.tsx` — per-question evaluation cards.
- `llm-frontend/src/pages/PracticeHistoryPage.tsx` — past attempts list for a topic.
- `llm-frontend/src/components/practice/FreeFormQuestion.tsx` — text-input question.
- `llm-frontend/src/components/practice/PracticeBanner.tsx` — top banner for grading-complete notifications.
- `llm-frontend/src/components/practice/QuestionRenderer.tsx` — maps `practice_questions.format` to the right activity component (answer-capture mode, not auto-submit).

**Modified frontend files:**
- `llm-frontend/src/App.tsx` — add `/learn/.../practice-landing`, `/learn/.../practice/:attemptId`, `/learn/.../practice-review/:attemptId`, `/learn/.../practice-history` routes; delete `/learn/.../exam/:sessionId` and `/learn/.../exam-review/:sessionId` routes.
- `llm-frontend/src/components/ModeSelection.tsx` — delete Exam tile + all past-exams UI + resume-exam / resume-practice tiles; rename Let's Practice tile so it routes to the new landing page. **No badges, no metadata** (per FR-22).
- `llm-frontend/src/components/AppShell.tsx` — mount `PracticeBanner` so it appears on every authenticated screen.
- `llm-frontend/src/api.ts` — add practice-attempt types + API functions; delete exam types/functions.
- `llm-frontend/src/pages/ReportCardPage.tsx` — rename "Exam scores" to "Practice scores"; show latest score + attempt count.

**Deleted frontend files:**
- `llm-frontend/src/pages/ExamReviewPage.tsx`.

---

## 3. Database Changes

### New tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `practice_questions` | Offline question bank per topic (30–40 rows per guideline) | `id` (VARCHAR PK), `guideline_id` (VARCHAR FK, cascade), `format` (VARCHAR — one of 12), `difficulty` (VARCHAR — easy/medium/hard), `concept_tag` (VARCHAR), `question_json` (JSONB — format-specific payload + `correct_answer` + `explanation_why` + FF: `expected_answer`, `grading_rubric`), `generator_model` (VARCHAR), `created_at` (DATETIME) |
| `practice_attempts` | One row per practice attempt (in-progress or submitted) | `id` (VARCHAR PK), `user_id` (VARCHAR FK, cascade), `guideline_id` (VARCHAR FK, cascade), `question_ids` (JSONB — ordered array of 10), `answers_json` (JSONB — `{q_idx: <answer>}` partial/final), `grading_json` (JSONB — `{q_idx: {score, correct, rationale, wrong_pick_explanation}}`), `total_score` (FLOAT, nullable), `total_possible` (INT, default 10), `status` (VARCHAR — `in_progress`, `grading`, `graded`, `grading_failed`), `grading_error` (TEXT, nullable), `grading_attempts` (INT, default 0), `results_viewed_at` (DATETIME, nullable), `created_at` (DATETIME), `submitted_at` (DATETIME, nullable), `graded_at` (DATETIME, nullable) |

### Key indexes / constraints

- `practice_questions`: `Index("idx_practice_questions_guideline", "guideline_id")`.
- `practice_attempts`:
  - `Index("idx_practice_attempts_user_guideline", "user_id", "guideline_id")` — history lookup.
  - `Index("idx_practice_attempts_user_status", "user_id", "status")` — unread-banner query.
  - Partial unique index `uq_practice_attempts_one_inprogress_per_topic` on `(user_id, guideline_id)` WHERE `status = 'in_progress'` — enforces FR-33 (one resumable attempt per topic).

### Relationships

```
teaching_guidelines ──1:N──► practice_questions  (CASCADE delete; re-sync drops old bank)
teaching_guidelines ──1:N──► practice_attempts    (CASCADE delete)
users               ──1:N──► practice_attempts    (CASCADE delete)
```

### Migration plan (`db.py`)

1. `Base.metadata.create_all()` creates both tables (SQLAlchemy declarative models).
2. New migration function `_apply_practice_tables(db_manager)`:
   - Idempotently create the partial unique index on `practice_attempts`.
   - Ensure `practice_bank_generator` and `practice_grader` rows exist in `llm_config` (via `_ensure_llm_config()` helper — existing pattern used for `explanation_generator`).
3. New migration function `_cleanup_exam_data(db_manager)`:
   - `DELETE FROM sessions WHERE mode = 'exam'` — discards all exam session history (FR-1).
   - Drop columns `exam_score`, `exam_total` from `sessions` (no longer used after deletion).
4. Update `_LLM_CONFIG_SEEDS` with two new rows:

| Component Key | Provider | Model | Purpose |
|---------------|----------|-------|---------|
| `practice_bank_generator` | openai | gpt-5.2 | Practice question bank generation + correctness review (review/refine pattern) |
| `practice_grader` | openai | gpt-4o-mini | Free-form grading + per-pick wrong-answer rationale. gpt-4o-mini for latency — grading runs 1× per wrong/blank answer per attempt (up to 10). Admin can override if quality is off. |

**Decision — why a dedicated `practice_attempts` table (not reuse `sessions`):** Exam mode shoehorned a batch drill into `sessions` by storing `exam_questions[]` inside `state_json`. That forced every batch-drill concern through session serialization, the `state_version` CAS loop, and tutor-centric ownership checks. Let's Practice has no conversation history and no LLM turn — a purpose-built table is cleaner, smaller (no 100kb `state_json` per attempt), and makes "history of attempts" a trivial indexed query.

**Decision — why `question_json` is JSONB (not per-format columns):** the 11 activity types already use heterogeneous per-activity fields in `check_in_enrichment_service.CheckInDecision` + `ExplanationRepository.CheckInActivity`. Reusing the same shape keeps the frontend `CheckInDispatcher` renderer unchanged and avoids a 30-column table. Pydantic `PracticeQuestionContent` (see §4) validates the JSON on write.

---

## 4. Backend Changes

### 4.1 `tutor/` module — runtime

#### API Layer (`tutor/api/practice.py`)

Mount as a new router with prefix `/practice` in `main.py`.

| Endpoint | Method | Path | Purpose |
|----------|--------|------|---------|
| `availability` | GET | `/practice/topics/{guideline_id}/availability` | `{has_bank, bank_size}` — used by topic list for greyed-out state (FR-5) |
| `start_or_resume` | POST | `/practice/attempts` | Body `{guideline_id}`. Returns existing `in_progress` attempt if one exists (FR-33), else creates a new 10-question set. |
| `get_attempt` | GET | `/practice/attempts/{attempt_id}` | Full attempt: questions + current answers + status + grading_json if graded. Used by PracticeRunner (resume), Results, and Review pages. |
| `save_answer` | PATCH | `/practice/attempts/{attempt_id}/answer` | Body `{q_idx, answer}`. Idempotent auto-save as student moves through set. No-op once `status != in_progress`. |
| `submit` | POST | `/practice/attempts/{attempt_id}/submit` | Flip status `in_progress → grading`, spawn background grading thread, return immediately. |
| `retry_grading` | POST | `/practice/attempts/{attempt_id}/retry-grading` | Only valid when `status == grading_failed`. Re-enqueues grading. |
| `list_attempts` | GET | `/practice/attempts?guideline_id=X` | History for a topic, newest first (FR-45). |
| `recent_graded` | GET | `/practice/attempts/recent?since=<ts>` | Returns attempts where `graded_at IS NOT NULL AND results_viewed_at IS NULL` for the current user — drives the banner (FR-35). Polled every 30s by the banner component. |
| `mark_viewed` | POST | `/practice/attempts/{attempt_id}/mark-viewed` | Sets `results_viewed_at` — clears banner for that attempt. |

**Ownership checks:** every endpoint verifies `attempt.user_id == current_user.id` before returning or mutating, mirroring `_check_session_ownership` in `tutor/api/sessions.py`.

**Pydantic request/response models** (in `tutor/models/practice.py` — new file):

```python
class PracticeQuestionContent(BaseModel):
    """Shape stored in PracticeQuestion.question_json. Flat model — fill only
    the fields relevant to the chosen format (mirrors CheckInDecision)."""
    question_text: str
    explanation_why: str  # Short "why the correct answer is correct"
    # Structured formats: correct_answer is the canonical answer value
    # Free-form only: expected_answer + grading_rubric
    expected_answer: Optional[str] = None
    grading_rubric: Optional[str] = None
    # pick_one / fill_blank / predict_then_reveal / tap_to_eliminate
    options: list[str] = Field(default_factory=list)
    correct_index: Optional[int] = None
    # true_false
    statement: Optional[str] = None
    correct_answer_bool: Optional[bool] = None
    # match_pairs
    pairs: list[MatchPairOutput] = Field(default_factory=list)
    # sort_buckets / swipe_classify
    bucket_names: list[str] = Field(default_factory=list)
    bucket_items: list[BucketItemOutput] = Field(default_factory=list)
    # sequence
    sequence_items: list[str] = Field(default_factory=list)
    # spot_the_error
    error_steps: list[str] = Field(default_factory=list)
    error_index: Optional[int] = None
    # odd_one_out
    odd_items: list[str] = Field(default_factory=list)
    odd_index: Optional[int] = None
    # predict_then_reveal
    reveal_text: Optional[str] = None
    # free_form — only expected_answer + grading_rubric

class PracticeQuestionDTO(BaseModel):
    id: str
    format: str
    difficulty: str
    concept_tag: str
    content: PracticeQuestionContent  # Sent to frontend WITHOUT correct_answer/explanation_why
    # Frontend-safe redaction handled by a separate serializer in practice_service

class StartAttemptRequest(BaseModel):
    guideline_id: str

class StartAttemptResponse(BaseModel):
    attempt_id: str
    guideline_id: str
    questions: list[PracticeQuestionDTO]  # 10 — correct answers stripped
    existing_answers: dict[int, Any]  # For resume
    status: Literal["in_progress", "grading", "graded", "grading_failed"]

class SaveAnswerRequest(BaseModel):
    q_idx: int
    answer: Any  # Shape depends on format — validated in service

class GradedQuestion(BaseModel):
    q_idx: int
    question_id: str
    student_answer: Optional[Any]
    correct_answer: Any  # Revealed only in results
    explanation_why: str
    score: float  # 0.0 or 1.0 for structured; 0.0–1.0 for FF
    correct: bool  # score >= 0.5 for display
    wrong_pick_explanation: Optional[str]  # LLM-generated per FR-39

class AttemptResultResponse(BaseModel):
    attempt_id: str
    guideline_id: str
    status: str
    total_score: float
    total_possible: int
    graded_questions: list[GradedQuestion]
    submitted_at: datetime
    graded_at: Optional[datetime]
    grading_error: Optional[str]
```

#### Service Layer (`tutor/services/practice_service.py`)

```python
class PracticeService:
    def __init__(self, db: DBSession):
        self.db = db
        self.question_repo = PracticeQuestionRepository(db)
        self.attempt_repo = PracticeAttemptRepository(db)

    def start_or_resume(self, user_id: str, guideline_id: str) -> PracticeAttempt:
        """FR-15..FR-20, FR-33 — return in-progress attempt if any, else new set."""
        existing = self.attempt_repo.get_in_progress(user_id, guideline_id)
        if existing:
            return existing
        questions = self._select_set(guideline_id)
        return self.attempt_repo.create(user_id, guideline_id, [q.id for q in questions])

    def _select_set(self, guideline_id: str) -> list[PracticeQuestion]:
        """FR-15..FR-19 — 10 questions, 3/5/2 mix, all FF absorbed, format variety."""
        bank = self.question_repo.list_by_guideline(guideline_id)
        if len(bank) < 10:
            raise PracticeUnavailableError(guideline_id)
        free_form = [q for q in bank if q.format == "free_form"]  # FR-17: all FFs included
        structured = [q for q in bank if q.format != "free_form"]
        # FR-16: 3 easy / 5 medium / 2 hard minus FFs, filled from structured
        quota = {"easy": 3, "medium": 5, "hard": 2}
        for q in free_form:
            quota[q.difficulty] = max(0, quota[q.difficulty] - 1)
        # Random fill, then shuffle; enforce format-variety per FR-19
        picked = self._pick_with_variety(structured, quota)
        chosen = free_form + picked
        random.shuffle(chosen)
        return self._enforce_no_consecutive_same_format(chosen)

    def save_answer(self, attempt_id: str, q_idx: int, answer) -> None: ...

    def submit(self, attempt_id: str, user_id: str) -> PracticeAttempt:
        """Flip to 'grading', spawn grading_service.run_grading() in a thread.
        Mirrors run_in_background_v2's wrapper pattern (fresh DB session).
        """
        attempt = self.attempt_repo.mark_submitted(attempt_id)
        self._spawn_grading_worker(attempt_id, user_id)
        return attempt

    def redact_for_student(self, q: PracticeQuestion) -> PracticeQuestionDTO:
        """Strip correct_answer / correct_index / explanation_why before sending
        to student during the set (FR-26)."""
        ...
```

**Decision — grading worker mechanism:** use the exact threading pattern from `book_ingestion_v2/api/processing_routes.py::run_in_background_v2` — a fresh DB session, try/except, separate session for error handling after long LLM calls. The existing pattern is proven, handles DB-connection-after-long-LLM-call correctly, and doesn't require a task queue. We don't need App Runner to survive a worker restart — if it does, we fail the attempt to `grading_failed` via the existing stale-heartbeat pattern and the student uses the manual retry (FR-40).

#### Grading Service (`tutor/services/practice_grading_service.py`)

```python
class PracticeGradingService:
    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service  # Configured with practice_grader model

    def grade_attempt(self, attempt_id: str) -> None:
        """Entry point. Loads attempt + questions. For each question:
           - structured format: deterministic comparison (FR-37)
           - free_form:         LLM call for 0.0–1.0 score + rationale (FR-38)
           - any wrong/blank:   LLM call for 'wrong_pick_explanation' (FR-39)
        Writes grading_json + total_score + graded_at. Retry 3× exponential
        backoff on LLM failure; after 3 failures → status='grading_failed'.
        """

    def _grade_structured(self, q: PracticeQuestion, answer) -> tuple[float, bool]:
        """Deterministic: compare answer against q.content.correct_index /
        correct_answer_bool / pairs / sequence_items / bucket_items / ...
        Blank → (0.0, False). No LLM call."""

    def _grade_freeform(self, q: PracticeQuestion, answer) -> tuple[float, str]:
        """LLM: returns (fractional 0.0–1.0, 1-sentence rationale).
        Structured output schema enforces bounds."""

    def _explain_wrong_pick(self, q: PracticeQuestion, student_answer) -> str:
        """LLM: 'The student picked X but the correct answer is Y because ...'
        Generates per FR-39 for every wrong/blank structured answer."""
```

**Decision — one LLM call per wrong answer (not batched):** per-pick rationale depends on the student's specific answer, which the LLM cannot accurately analyze in a batch without leaking cross-question context. 10 parallel small calls finish in ≲10s with gpt-4o-mini. If latency becomes a complaint, revisit after measurement. This matches the existing "one LLM call per remedial card" pattern in `master_tutor.generate_simplified_card`.

**Retry pattern:** 3 attempts with 10s / 20s / 40s backoff. On final failure: `attempt.status = "grading_failed"`, `attempt.grading_error = "..."`, banner shows the attempt with a Retry-grading action.

#### Repositories (`shared/repositories/`)

- **`PracticeQuestionRepository`**
  - `list_by_guideline(guideline_id) -> list[PracticeQuestion]`
  - `count_by_guideline(guideline_id) -> int`
  - `bulk_insert(guideline_id, questions: list[PracticeQuestionContent]) -> None`
  - `delete_by_guideline(guideline_id) -> int`  # used by force-regenerate

- **`PracticeAttemptRepository`**
  - `create(user_id, guideline_id, question_ids) -> PracticeAttempt`
  - `get(attempt_id) -> Optional[PracticeAttempt]`
  - `get_in_progress(user_id, guideline_id) -> Optional[PracticeAttempt]`
  - `list_for_user_topic(user_id, guideline_id) -> list[PracticeAttempt]`  # newest first
  - `list_recent_graded_unread(user_id) -> list[PracticeAttempt]`
  - `save_answer(attempt_id, q_idx, answer) -> None`  # merges into answers_json
  - `mark_submitted(attempt_id) -> PracticeAttempt`  # atomic status + submitted_at update
  - `mark_grading(attempt_id) -> None`
  - `save_grading(attempt_id, grading_json, total_score) -> None`
  - `mark_grading_failed(attempt_id, error) -> None`
  - `mark_viewed(attempt_id) -> None`
  - `count_by_user_guideline(user_id, guideline_id) -> int`  # for scorecard "(3 attempts)"
  - `latest_graded(user_id, guideline_id) -> Optional[PracticeAttempt]`  # for scorecard "7/10"

### 4.2 `book_ingestion_v2/` module — offline bank generation

#### API Layer — extend `book_ingestion_v2/api/sync_routes.py`

| Endpoint | Method | Path | Purpose |
|----------|--------|------|---------|
| `generate_practice_banks` | POST | `/admin/v2/books/{book_id}/generate-practice-banks?chapter_id&guideline_id&force&review_rounds` | Launch background bank generation. Mirrors `generate_check_ins` exactly. |
| `get_latest_practice_bank_job` | GET | `/admin/v2/books/{book_id}/practice-bank-jobs/latest?chapter_id&guideline_id` | Job status tracking. |
| `get_practice_bank_status` | GET | `/admin/v2/books/{book_id}/practice-bank-status?chapter_id` | Per-topic bank counts for a chapter. |
| `get_practice_bank` | GET | `/admin/v2/books/{book_id}/practice-banks/{guideline_id}` | Read-only bank viewer (FR-50). |

All endpoints acquire a `ChapterJobService` lock with `V2JobType.PRACTICE_BANK_GENERATION.value` (new enum value).

#### Generator Service (`book_ingestion_v2/services/practice_bank_generator_service.py`)

```python
class PracticeBankGeneratorService:
    """Pipeline per guideline:
    1. _generate_bank()  → LLM call → 30–40 PracticeQuestionOutput items (FR-7, FR-8, FR-9)
    2. for r in range(review_rounds): _review_and_refine(bank)   (FR-12)
    3. _validate_bank(bank)                                       (FR-12)
    4. if count < 30: _top_up(bank, target=30)                    (FR-12)
    5. repo.bulk_insert(guideline_id, valid_bank)
    """

    def enrich_guideline(self, guideline, force=False, review_rounds=1, heartbeat_fn=None) -> dict:
        """Returns {"generated": N, "skipped": 0|1, "failed": 0|1, "errors": [...]}"""

    def enrich_chapter(self, book_id, chapter_id=None, force=False, review_rounds=1,
                       job_service=None, job_id=None) -> dict:
        ...

    def _generate_bank(self, guideline) -> PracticeBankOutput: ...
    def _review_and_refine(self, bank, guideline) -> Optional[PracticeBankOutput]: ...
    def _top_up(self, bank, target, guideline) -> PracticeBankOutput: ...
    def _validate_bank(self, bank) -> list[PracticeQuestionOutput]: ...
```

The structural validation mirrors `check_in_enrichment_service._validate_activity_content` — per-format constraints (option counts, bucket items, sequence lengths, etc.) — and **drops** questions that fail. The correctness review is an LLM pass with a narrow prompt (scope: `marked correct answer is actually correct + distractors are actually wrong + bucket assignments/sequence order/match pairs are right`; does NOT rewrite for tone/clarity).

**Decision — refine/review pattern matches existing services.** `check_in_enrichment_service.py` is the template: fail-open on LLM error (keep prior output and continue), `_refresh_db_session()` between long LLM calls, structural validation on post-refine output, validate_*_content() per activity type.

**Decision — one LLM call per bank, not per question.** The LLM handles full-bank planning (difficulty distribution, format variety, concept coverage across the topic). Per-question calls would 30× the latency and lose global balance. Matches how `_generate_check_ins` handles a full card sequence in one call.

**Decision — FF count is LLM-decided (FR-9).** The generator prompt says "1–3 free-form questions" and lets the LLM pick; we constrain at validate-time to `1 ≤ FF count ≤ 3`, drop excess, top-up if short. No hard-coded rule on exact FF count per topic.

#### Pydantic output schemas

Reuse `CheckInDecision`-style flat model:

```python
class PracticeQuestionOutput(BaseModel):
    """Mirrors CheckInDecision's flat structure — fill only fields for the chosen format."""
    format: Literal["pick_one","true_false","fill_blank","match_pairs",
                    "sort_buckets","sequence","spot_the_error","odd_one_out",
                    "predict_then_reveal","swipe_classify","tap_to_eliminate",
                    "free_form"]
    difficulty: Literal["easy", "medium", "hard"]
    concept_tag: str
    question_text: str
    explanation_why: str  # Short "why the correct answer is correct"
    # Structured fields (same as CheckInDecision — reused verbatim)
    options: list[str] = Field(default_factory=list)
    correct_index: int = 0
    statement: str = ""
    correct_answer_bool: bool = True
    pairs: list[MatchPairOutput] = Field(default_factory=list)
    bucket_names: list[str] = Field(default_factory=list)
    bucket_items: list[BucketItemOutput] = Field(default_factory=list)
    sequence_items: list[str] = Field(default_factory=list)
    error_steps: list[str] = Field(default_factory=list)
    error_index: int = 0
    odd_items: list[str] = Field(default_factory=list)
    odd_index: int = 0
    reveal_text: str = ""
    # Free-form
    expected_answer: str = ""
    grading_rubric: str = ""


class PracticeBankOutput(BaseModel):
    questions: list[PracticeQuestionOutput]
```

#### Admin UI page

Extend `BookV2Detail.tsx` with a "Practice Banks" section that links to a new `PracticeBankAdmin.tsx` page per chapter. That page lists all topics + bank counts and a per-topic drill-in to view all questions (read-only). No regenerate-per-question, no delete-per-question, no analytics (per PRD out-of-scope).

Routes:
- `/admin/books-v2/:bookId/practice-banks/:chapterId` → `PracticeBankAdmin.tsx`

---

## 5. Frontend Changes

### 5.1 New routes (`App.tsx`)

| Route | Component | Purpose |
|-------|-----------|---------|
| `/learn/:subject/:chapter/:topic/practice-landing` | `PracticeLandingPage` | Start / Resume / History |
| `/learn/:subject/:chapter/:topic/practice/:attemptId` | `PracticeRunner` | Questions + review + submit |
| `/learn/:subject/:chapter/:topic/practice-results/:attemptId` | `PracticeResultsPage` | Score + Reteach / Practice again |
| `/learn/:subject/:chapter/:topic/practice-review/:attemptId` | `PracticeReviewPage` | Card-by-card evaluation cards |
| `/learn/:subject/:chapter/:topic/practice-history` | `PracticeHistoryPage` | Past attempts list |

**Deleted routes:**
- `/learn/:subject/:chapter/:topic/exam/:sessionId`
- `/learn/:subject/:chapter/:topic/exam-review/:sessionId`
- `/learn/:subject/:chapter/:topic/practice/:sessionId` (old live-tutor practice path — replaced)

### 5.2 Modified: `ModeSelection.tsx`

Replace all `isRefresher ? ... : ...` practice/exam logic with:

```tsx
{!isRefresher && (
  <button
    className={`selection-card ${!practiceAvailable ? 'disabled' : ''}`}
    disabled={!practiceAvailable}
    onClick={() => navigate(`/learn/.../practice-landing`)}
    data-testid="mode-practice"
  >
    <strong>Let's Practice</strong>
    <span className="mode-card-sub">
      {practiceAvailable ? 'Try some questions' : 'Not available yet'}
    </span>
  </button>
)}
```

**No badges, no in-progress indicators, no "last practiced N days ago", no past-exams list** (FR-22). Delete all `completedExams` / `incompleteExam` state and logic. Delete `incompletePractice` (the old mid-lesson resume is gone — resume now happens on the landing page).

`practiceAvailable` comes from a new `getPracticeAvailability(guideline_id)` API call in the page-load `Promise.all`. Fallback: if the call fails, show the tile enabled — error on the landing page (not the mode picker) is better UX than a broken-looking tile.

### 5.3 New: `PracticeLandingPage.tsx`

Three buttons, conditional "Resume":

```
┌──────────────────────┐
│  Let's Practice      │
│  {topic}             │
│                      │
│  [ Start practice ]  │   ← POST /practice/attempts (new set)
│  [ Resume          ] │   ← conditional; POST /practice/attempts returns existing in-progress
│  [ See past evals  ] │
└──────────────────────┘
```

Fetches history count + in-progress status on mount.

### 5.4 New: `PracticeRunner.tsx`

Single page manages:
- **Question-by-question mode**: renders `QuestionRenderer` for `questions[currentIdx]` + progress indicator "5 of 10" + back/next buttons. Back is always enabled; Next moves forward; no correctness shown (FR-26).
- **Auto-save**: on every answer change, debounce 500ms then `PATCH /practice/attempts/{id}/answer`.
- **Review screen**: after Q10 → full-list review of answers with Edit-per-question (tap a row to jump back to it); single **Submit** button (FR-31).
- **Submit**: `POST /submit` → navigate to `/learn/:subject/:chapter/:topic` (ModeSelection) per FR-34. No toast, no confirmation — the banner is the feedback mechanism.

**`QuestionRenderer.tsx`**: dispatches on `question.format` to the existing 11 activity components from `components/`. Key change from check-in usage: in practice mode, activity components must **not** auto-submit on first selection — practice lets students change answers (FR-25). Approach: add an optional `mode` prop (`'check_in'` | `'practice_capture'`) and branch behavior. The 11 components already expose an `onComplete` callback; practice passes an `onAnswerChange` callback instead (the parent decides when to move forward via Next button).

For `free_form` questions, `FreeFormQuestion.tsx` renders a simple `<textarea>`.

### 5.5 New: `PracticeResultsPage.tsx`

```
┌──────────────────────┐
│  Practice Results    │
│                      │
│       7.5 / 10       │
│                      │
│  [ Reteach         ] │   → /learn/:subject/:chapter/:topic with ?mode=teach_me autoselect
│  [ Practice again  ] │   → POST /practice/attempts → /practice/:newId
│  [ Review my picks ] │   → PracticeReviewPage
└──────────────────────┘
```

Also calls `POST /practice/attempts/{id}/mark-viewed` on mount to clear the banner.

### 5.6 New: `PracticeReviewPage.tsx`

One evaluation card per question. Shows:
- question text
- student's answer (or "not answered")
- correct answer
- `explanation_why`
- for wrong/blank: `wrong_pick_explanation`
- optional Pixi visual if present (FR-43 — out-of-scope for v1 of this page, but the data model supports it for later)

Renders as vertical scroll list — no Next/Prev nav.

### 5.7 New: `PracticeHistoryPage.tsx`

```
┌──────────────────────┐
│  Past attempts       │
│  ─────────────────── │
│  Apr 16 · 8/10       │   ← tap opens PracticeReviewPage for that attempt
│  Apr 14 · 6/10       │
│  Apr 10 · 4/10       │
└──────────────────────┘
```

### 5.8 New: `PracticeBanner.tsx`

Mounted in `AppShell.tsx` (sits above all authenticated routes). Polls `GET /practice/attempts/recent` every 30s. If any attempt has `graded_at` but no `results_viewed_at`, renders:

```
┌────────────────────────────────────────────────┐
│ ✓ Your Practice results are ready  →           │
└────────────────────────────────────────────────┘
```

Tap → navigate to `PracticeResultsPage` for that attempt. Silent when no unread attempts.

For `status == grading_failed`: banner reads `⚠ Grading failed. Retry?` — tap → `POST /retry-grading` and reload banner state.

**Decision — poll, not push.** No WebSocket infra for banners exists; introducing one adds complexity. 30s polling at ~50 bytes per response is negligible and matches the PRD's "in-app banner only" (FR-35, §10 out-of-scope: no browser push). If poll cost becomes a problem later, switch to Server-Sent Events.

### 5.9 Modified: `api.ts`

Add:
```ts
export interface PracticeQuestion { id: string; format: string; difficulty: string;
  concept_tag: string; content: any; }

export interface PracticeAttempt {
  attempt_id: string; guideline_id: string; questions: PracticeQuestion[];
  existing_answers: Record<number, any>; status: 'in_progress'|'grading'|'graded'|'grading_failed';
  total_score?: number; total_possible?: number; graded_questions?: GradedQuestion[];
  submitted_at?: string; graded_at?: string; grading_error?: string;
}

export async function getPracticeAvailability(guidelineId: string): Promise<{has_bank: boolean; bank_size: number}>;
export async function startPracticeAttempt(guidelineId: string): Promise<PracticeAttempt>;
export async function getPracticeAttempt(attemptId: string): Promise<PracticeAttempt>;
export async function savePracticeAnswer(attemptId: string, qIdx: number, answer: any): Promise<void>;
export async function submitPracticeAttempt(attemptId: string): Promise<void>;
export async function retryPracticeGrading(attemptId: string): Promise<void>;
export async function listPracticeAttempts(guidelineId: string): Promise<PracticeAttempt[]>;
export async function recentGradedPracticeAttempts(): Promise<PracticeAttempt[]>;
export async function markPracticeViewed(attemptId: string): Promise<void>;
```

Delete: `ExamReviewResponse`, `ExamReviewQuestion`, `getExamReview`, all exam-related types.

### 5.10 Modified: `ReportCardPage.tsx` + `ReportCardSubject` types

- Rename on-screen label "Exam scores" → "Practice scores" (FR-48).
- Per-topic display: show `latest_practice_score / total (N attempts)` instead of `latest_exam_score / latest_exam_total` (FR-49).
- Backend: `report_card_service.py` replaces `exam_finished` query with `PracticeAttemptRepository.latest_graded()` + `count_by_user_guideline()`.

---

## 6. LLM Integration

### 6.1 Bank generation prompt (`book_ingestion_v2/prompts/practice_bank_generation.txt`)

Inputs: topic title + subject + grade + guideline text + concept list + existing explanation cards (for concept-grounding). Key instructions:
- Generate 30–40 questions in one call.
- Difficulty mix inside the bank: ~30% easy, ~50% medium, ~20% hard (aligned with the 10-question selection quota, so selection has healthy supply at every difficulty).
- 1–3 questions MUST be `free_form`; count decided by topic nature.
- Every question: `explanation_why` is REQUIRED, short ("one sentence, no jargon").
- Free-form: `expected_answer` + `grading_rubric` REQUIRED.
- Follow `docs/principles/easy-english.md` (FR-13).
- No personalization (FR-14).
- English-only.

Provider: `practice_bank_generator` (seeded `openai/gpt-5.2`). Reasoning effort: `medium`. Structured output: `PracticeBankOutput` strict JSON schema.

### 6.2 Bank review-refine prompt (`practice_bank_review_refine.txt`)

Same shape as `check_in_review_refine.txt`: narrow scope — correctness ONLY. The reviewer verifies:
- marked `correct_index` / `correct_answer_bool` is actually correct
- distractors are actually wrong
- match pairs / sequence order / bucket assignments / spot-the-error index are correct
- `expected_answer` is a reasonable correct answer for free-form

Does NOT rewrite for tone, clarity, or distractor quality. Output is the full bank (may modify existing questions in place). Fail-open: error → keep prior bank.

### 6.3 Free-form grading prompt (`tutor/prompts/practice_grading.py`)

Inputs: question text + student answer + expected_answer + grading_rubric. Output: strict JSON `{score: float[0,1], rationale: string}`. Provider: `practice_grader` (seeded `openai/gpt-4o-mini`). Reasoning effort: `none` (kept fast).

### 6.4 Wrong-pick rationale prompt (same file)

Inputs: question text + student's specific selection (text or value) + correct answer + `explanation_why`. Output: one-sentence explanation "You picked X, but that's not right because ... The correct answer is Y because ...". Provider: `practice_grader`. Reasoning effort: `none`.

### 6.5 Cost and latency

- **Bank generation** — one call per topic at ingestion. ~4K input / ~8K output tokens; gpt-5.2 medium reasoning. Plus 1 review-refine round ≈ 2× cost. Happens once per topic; not in the student path.
- **Student path — structured grading**: zero LLM calls.
- **Student path — per-pick rationale**: one call per wrong/blank structured answer. gpt-4o-mini, ~500 in / ~100 out. Worst case (10 wrongs): ~10 calls, ~5–8s end-to-end if sequential. **Optimization**: grade all 10 questions in parallel (`asyncio.gather`) to compress to ~1s wall-clock.
- **Student path — free-form grading**: 1–3 calls per attempt. ~1K in / ~200 out each. Parallel with rationale calls.

No caching needed for v1 — every call's input is attempt-specific.

---

## 7. Configuration & Environment

### New LLM config seeds (added to `_LLM_CONFIG_SEEDS` in `db.py`)

| Variable | Purpose | Default |
|----------|---------|---------|
| `practice_bank_generator` | Offline bank generation + correctness review | `openai` / `gpt-5.2` |
| `practice_grader` | FF grading + per-pick rationale | `openai` / `gpt-4o-mini` |

No new environment variables. No new config.py fields — all model selection is DB-backed (existing pattern).

---

## 8. Implementation Order

Each step is independently testable; earlier steps don't block on later ones landing.

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1 | **DB schema**: models + migration + LLM config seeds | `shared/models/entities.py`, `db.py` | — | `python db.py --migrate` runs clean; tables + indexes + seeds present; unit test for `_apply_practice_tables` |
| 2 | **Repositories**: `PracticeQuestionRepository`, `PracticeAttemptRepository` | `shared/repositories/practice_question_repository.py`, `shared/repositories/practice_attempt_repository.py` | 1 | Unit tests with in-memory DB |
| 3 | **Bank generator service** + prompts + `V2JobType.PRACTICE_BANK_GENERATION` | `book_ingestion_v2/services/practice_bank_generator_service.py`, `book_ingestion_v2/prompts/practice_bank_generation.txt`, `practice_bank_review_refine.txt`, `book_ingestion_v2/constants.py` | 1, 2 | Unit tests with mocked LLM; end-to-end against a real topic |
| 4 | **Ingestion API**: generate-practice-banks + status + bank-viewer endpoints | `book_ingestion_v2/api/sync_routes.py` | 3 | curl against local backend; job status transitions |
| 5 | **Admin UI**: `PracticeBankAdmin.tsx` page + hook in `BookV2Detail.tsx` | frontend admin | 4 | Manual — generate bank for one topic, view it |
| 6 | **Runtime grading service** | `tutor/services/practice_grading_service.py`, `tutor/prompts/practice_grading.py` | 2 | Unit tests with mocked LLM for deterministic + FF paths |
| 7 | **Runtime practice service** (set selection + auto-save + submit + threaded grading worker) | `tutor/services/practice_service.py`, `tutor/models/practice.py` | 2, 6 | Unit tests for `_select_set` (difficulty mix, FF absorption, variety); integration test: create attempt → save answers → submit → assert grading thread completes and grading_json populated |
| 8 | **Runtime API**: `/practice` router | `tutor/api/practice.py`, `main.py` | 7 | curl full flow locally: start → save → submit → poll /recent → mark-viewed |
| 9 | **Frontend runtime**: landing + runner + results + review + history + banner | `llm-frontend/src/pages/Practice*.tsx`, `components/practice/*`, `api.ts` | 8 | Manual browser test — full student flow on a topic with a seeded bank |
| 10 | **ModeSelection refactor**: tile simplification + landing routing + disabled-when-no-bank | `llm-frontend/src/components/ModeSelection.tsx`, `pages/ModeSelectPage.tsx` | 9 | Manual — tap Let's Practice → landing |
| 11 | **Scorecard**: rename + practice-score sourcing | `tutor/services/report_card_service.py`, `llm-frontend/src/pages/ReportCardPage.tsx`, `api.ts` types | 2 | Unit test on `get_report_card` with mixed teach_me + practice data |
| 12 | **Exam deletion (backend)**: delete exam_service, exam_prompts, practice_prompts, exam dispatch in orchestrator, exam REST endpoints, exam session state fields + DB cleanup migration | many (see §2 Modified/Deleted) | 11 (replacement flow live first) | Backend unit + integration tests all pass; no references to `"exam"` mode remain; `grep -r 'ExamService\|exam_prompts\|practice_prompts' llm-backend/` returns 0 |
| 13 | **Exam deletion (frontend)**: delete `ExamReviewPage`, exam routes, exam types in `api.ts` | `llm-frontend/**/Exam*`, `App.tsx`, `api.ts` | 12 | `grep -r 'exam' llm-frontend/src` returns only legal uses (none expected) |
| 14 | **Docs**: new principles/functional/technical docs for practice; update scorecard + architecture-overview + database + ai-agent-files; delete stale exam docs | `docs/principles/practice-mode.md`, `docs/functional/practice-mode.md`, `docs/technical/practice-mode.md`, updates to existing docs | 13 | `/update-all-docs` skill passes |

**Order rationale:** schema → repos → offline bank generation → offline admin UI (so QA can review banks) → runtime grading → runtime service → runtime API → runtime frontend → mode-picker wiring → scorecard. Exam deletion comes AFTER the replacement runtime is live so prod never has a window with neither feature. Docs last.

---

## 9. Testing Plan

### Unit tests

| Test | What It Verifies | Key Mocks |
|------|------------------|-----------|
| `test_practice_service_select_set_difficulty_mix` | 3 easy / 5 medium / 2 hard quota (FR-16) | Seeded `practice_questions` via fixture |
| `test_practice_service_select_set_absorbs_all_ff` | All free-form included, structured fills remainder (FR-17) | Seeded bank with 2 FFs |
| `test_practice_service_select_set_no_consecutive_same_format` | FR-19 | Seeded bank heavy on one format |
| `test_practice_service_select_set_errors_if_too_few` | Raises `PracticeUnavailableError` when bank < 10 | Seeded bank with 5 |
| `test_practice_service_locks_set_on_resume` | Resume returns same 10 question IDs in same order (FR-20) | Create attempt → mutate bank → resume |
| `test_grading_service_grades_pick_one_correct` | Deterministic correct path, score=1.0 | None |
| `test_grading_service_grades_pick_one_wrong_includes_rationale` | Deterministic wrong + LLM wrong-pick explanation (FR-39) | Mock `LLMService.call` |
| `test_grading_service_grades_blank_as_wrong` | FR-32 — blank → 0.0 + rationale | Mock LLM |
| `test_grading_service_grades_freeform_fractional` | FR-38 — LLM returns 0.5, service stores 0.5 | Mock LLM JSON output |
| `test_grading_service_retries_3x_then_fails` | FR-40 | Mock LLM that always raises |
| `test_practice_attempt_repo_in_progress_uniqueness` | Partial unique index prevents two in-progress attempts | Attempt to create two — second should fail |
| `test_practice_bank_generator_top_up_runs_when_short` | If validate drops count < 30, top-up runs (FR-12) | Mock LLM that returns 35 then 28 valid |
| `test_practice_bank_generator_review_refine_fail_open` | Review round error → keep prior output | Mock LLM that raises on 2nd call |
| `test_report_card_practice_score` | Latest score + attempt count shown per topic (FR-49) | Seeded `practice_attempts` |

### Integration tests

| Test | What It Verifies |
|------|------------------|
| `test_practice_full_flow` | POST /attempts → PATCH answers → POST submit → poll grading → GET attempt shows `status=graded` + grading_json |
| `test_practice_parallel_attempts_across_topics` | Submit on topic A, start attempt on topic B before A finishes grading (FR-36) |
| `test_practice_multiple_history_attempts` | 3 submitted attempts on same topic → GET /attempts?guideline_id returns all 3 newest-first |
| `test_practice_resume_on_landing` | Create attempt, disconnect, hit landing again → in-progress attempt surfaces |
| `test_exam_mode_404_after_deletion` | POST /sessions {mode: "exam"} returns 400 "Mode not supported" |

### Manual verification

**Ingestion side:**
1. `cd llm-backend && source venv/bin/activate && make run`.
2. Admin dashboard → pick a book → pick a chapter → Practice Banks section.
3. Click Generate → wait for job to finish.
4. Click into a topic's bank → verify 30–40 questions, mix of 11 formats + 1–3 free-form, sane `explanation_why` text.
5. Spot-check correctness: pick 3 questions, verify marked-correct answer is actually correct.

**Runtime side:**
1. As a student with a topic that has a generated bank, tap the topic → Let's Practice tile is enabled.
2. Tap → landing page shows Start practice.
3. Tap Start → question 1 of 10 renders. Verify no correctness feedback, no audio, no Pixi visual.
4. Answer Qs 1–3, close the browser tab. Reopen → landing page shows Resume. Resume → same 10 questions in same order, Q1–Q3 answers preserved.
5. Complete all 10, review screen shows all answers, edit one, tap Submit. Return to ModeSelection immediately.
6. Wait ≲30s — banner "Your Practice results are ready →" appears.
7. Tap banner → Results page shows fractional score. Tap Review my picks → evaluation cards for every question, correct answer + why + wrong-pick rationale on every wrong answer.
8. Tap Practice again → new 10-question set starts immediately (different random picks).
9. Return to the topic → Past evaluations shows 2 entries, newest first.
10. ReportCard → the topic shows latest Practice score + "(2 attempts)".

**Grading-failure path:**
1. Temporarily point `practice_grader` LLM config at a broken URL.
2. Submit an attempt → banner eventually shows "⚠ Grading failed. Retry?".
3. Fix config, tap Retry → banner clears, results appear.

---

## 10. Deployment Considerations

- **Migration order:** deploy code and migration together; `python db.py --migrate` is idempotent and safe to run on every deploy (existing pattern). The migration's `DELETE FROM sessions WHERE mode = 'exam'` is destructive — **confirmed acceptable per FR-1** (no exam data preserved). Wrap in a transaction.
- **Feature rollout:** ship to all users at once (PRD §10 out-of-scope: no feature flag, no phased rollout).
- **Ingestion backfill:** after deploy, run `POST /admin/v2/books/{id}/generate-practice-banks` for each existing book to populate banks. Without this step, every topic's Practice tile will be greyed out. Suggest a one-shot script `scripts/backfill_practice_banks.py` that iterates all books and calls the endpoint. Wall-clock ~5 min per chapter at gpt-5.2 medium; parallelize across books.
- **Rollback plan:** if critical bug surfaces post-deploy, revert the backend container image and run a "resurrect exam" migration — this is non-trivial because exam session data was deleted. Mitigation: keep a DB snapshot from the moment before the deploy; restore from snapshot if rollback is needed.
- **Infra:** no new AWS resources. No new secrets. `practice_grader` → gpt-4o-mini will appear in OpenAI cost reports; budget ~$0.0002 per submitted attempt (10 small calls). At 1000 attempts/day, ~$6/month.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Bank generation produces incorrect "correct answers" (distractors marked correct) | Medium | High (student learns wrong) | Review-refine pass is correctness-scoped + admin read-only bank viewer lets a human spot-check before topics go live. Start with `review_rounds=1` default; bump to 2 if audit flags issues. |
| FF grading inconsistent (LLM gives different score to same answer across attempts) | Medium | Medium | Accept it. FF is 1–3 out of 10 per attempt. Rubric in prompt anchors consistency. Log grading rationales so admin can audit patterns later. |
| Background grading thread dies mid-work (App Runner restart, DB connection lost) | Low | Medium | Stuck attempts auto-detected by a stale-heartbeat check (future; not v1). For v1, student manually triggers retry from the banner — FR-40. |
| Parallel grading (N attempts across topics all grading at once) overloads LLM rate limit | Low | Medium | Each attempt is ~10 small calls; OpenAI gpt-4o-mini rate limits are generous. `LLMService.call` already has built-in retry for rate-limit errors. If this becomes real, add a simple semaphore (`asyncio.Semaphore(5)`) in the grading worker. |
| Bank < 10 questions after validate+top-up (LLM can't generate enough valid questions) | Low | Medium | `_top_up` runs until threshold or 3 attempts. If still < 30, log an admin alert and mark the topic as "bank unavailable" — the tile greys out gracefully (FR-5). |
| Frontend activity components break when used in "capture" mode (no auto-submit) | Medium | Medium | Add `mode` prop to each of 11 components. Keep existing check-in behavior as default. Add unit tests per component for both modes. Roll out behind the 11 components one at a time. |
| Deletion of old Exam code breaks a code path we didn't spot | Medium | Low | Step 12 (deletion) runs ONLY after step 9 (new frontend live). Smoke test all modes post-deletion. Grep step in §8 Step 12 catches leftover references. |
| Discarded exam history is a regression for long-tenured students | High (certain) | Low (confirmed by FR-1) | PRD explicitly accepts this. No mitigation needed. |
| Banner polling at 30s is too slow (student sits staring at ModeSelection) | Medium | Low | 30s is a PRD-informed default. If UX testing shows impatience, drop to 10s or migrate to SSE post-ship. |

---

## 12. Open Questions

- **Q1:** FR-41 says "half-point granularity (e.g., 7.5/10)." Does each FR-38 fractional score contribute its raw 0.0–1.0 to the total, or do we bucket to half-points per question? **Proposed:** store raw fractional in `grading_json`, display total rounded to nearest 0.5. Simplest; preserves data for later.
- **Q2:** For FR-19 "at least 4 different formats per set" — does `free_form` count as a format? **Proposed:** yes. 10-question sets will naturally have ≥4 formats when 1–3 are FF and the rest are drawn randomly from 11 structured formats.
- **Q3:** FR-43 says "Pixi.js visuals MAY be included on evaluation cards when they help explain the 'why'." Scope for v1? **Proposed:** out of scope for v1 launch. Data model supports it via a nullable `visual_explanation` field inside `grading_json[q_idx]`; a later PR wires the existing `VisualExplanation` frontend component into `PracticeReviewPage.tsx`. Flag this in the tech plan review.
- **Q4:** FR-34 says student is routed back to topic list after Submit; should the route go to ModeSelection (same topic) or up a level to TopicSelect? **Proposed:** ModeSelection — student is likely to immediately pick another activity on this topic (Teach Me if score was low, Clarify Doubts, or another Practice). One tap back if they want to switch topics.
- **Q5:** Sessions DB column cleanup — drop `exam_score`, `exam_total` columns? **Proposed:** yes, in the same deploy. Safe because no code reads them after step 12, and they're not referenced by any index or foreign key.
