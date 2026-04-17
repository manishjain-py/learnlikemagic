# Tech Implementation Plan: Let's Practice (v2 — Batch Drill Redesign)

**Date:** 2026-04-17
**Status:** Draft
**PRD:** `docs/feature-development/lets-practice-v2/prd.md`

---

## 1. Overview

Let's Practice v2 replaces the existing Exam mode (and the older chat-based "practice" mode) with an offline-first batch drill: a pre-generated question bank per topic, silent answering, one-tap submit, background LLM grading, per-question evaluation cards, and persistent attempt history.

Build order (additive first, destructive last):

1. **Schema + repositories** — two new tables (`practice_questions`, `practice_attempts`). Self-contained attempts store a full question snapshot so bank regeneration can't orphan history.
2. **Ingestion stage** — question-bank generator as a new last stage in the V2 pipeline (after explanation generation), reusing the review/refine pattern from `check_in_enrichment_service`.
3. **Runtime services** — set selection/locking, auto-save, **atomic submit** (final answers + status flip in one transaction), background grading (deterministic for structured formats; LLM for free-form and per-pick rationales; ThreadPoolExecutor for per-call parallelism).
4. **API** — new `/practice` router (REST only — no WebSocket, no agent turn loop).
5. **Frontend** — **new practice-capture component layer** (11 controlled components, hydrate-from-server, deterministic shuffle via seed). Landing, runner, review/submit flow, results, banner, history. `PracticeBanner` mounted in a new `<AuthenticatedLayout>` above both AppShell and chat-session routes so it fires regardless of where the student navigates post-submit.
6. **Scorecard additive** — new practice-v2 aggregator populates new response fields; legacy exam fields preserved until Step 13.
7. **Destructive deletion (single deploy)** — remove Exam mode + old chat-based Practice mode + `practice_prompts.py` + exam review page + exam/old-practice session paths; run `DELETE FROM sessions WHERE mode IN ('exam', 'practice')` + drop exam columns in one transaction.
8. **Docs cleanup.**

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

**Modified backend files (additive — Steps 1–11):**
- `shared/models/entities.py` — **add** `PracticeQuestion`, `PracticeAttempt` models. (No exam column removal in this step — see §3 "Migration plan" + Step 12.)
- `db.py` — add migration hook `_apply_practice_tables()`; add LLM config seeds for `practice_bank_generator`, `practice_grader`.
- `book_ingestion_v2/constants.py` — add `V2JobType.PRACTICE_BANK_GENERATION`.
- `book_ingestion_v2/api/sync_routes.py` — add `POST /generate-practice-banks`, `GET /practice-bank-status`, `GET /practice-banks/{guideline_id}` (admin viewer).
- `main.py` — register `practice` router.
- `shared/models/schemas.py` — **add** `PracticeAttempt` DTOs; change `ReportCardTopic.latest_exam_score` / `latest_exam_total` type from `Optional[int]` to `Optional[float]` and add `latest_practice_score` / `latest_practice_total` / `practice_attempt_count` fields (kept additive until the frontend migration is live).

**Modified backend files (destructive — Step 12, same deploy as code removal):**
- `shared/models/entities.py` — remove `Session.exam_score`, `Session.exam_total` columns.
- `db.py` — add migration hook `_cleanup_exam_and_old_practice_data()` that runs **only in Step 12**: `DELETE FROM sessions WHERE mode IN ('exam', 'practice')`, `ALTER TABLE sessions DROP COLUMN IF EXISTS exam_score`, `ALTER TABLE sessions DROP COLUMN IF EXISTS exam_total`. Wrap in a single `engine.begin()` transaction.
- `main.py` — stop importing exam/old-practice pieces after deletion.
- `tutor/api/sessions.py` — remove `/sessions/{id}/end-exam`, `/sessions/{id}/exam-review`, and **`/sessions/{id}/end-practice`** (old chat-based practice endpoint at line 421). Remove `_save_session_to_db`'s exam-mode write path.
- `tutor/orchestration/orchestrator.py` — delete **exam** path: `_process_exam_turn`, `generate_exam_welcome`, `_build_exam_feedback`, and `"exam"` dispatch (line ~265, ~473). Delete **old practice** path: `_process_practice_turn` (line ~997), `"practice"` dispatch (line ~266).
- `tutor/services/session_service.py` — delete exam branches (`create_new_session`, `_find_incomplete_session`, `end_exam` at line 938, lines 799–815 that write `exam_score`/`exam_total`). Delete **old-practice** branches (lines 122–130, 299–330, 842–931, `end_practice`-equivalent paths).
- `tutor/services/report_card_service.py` — remove `mode == "exam"` and `mode == "practice"` branches (lines 85, 111, 263, 283 for old practice; 288–296 for exam). Replace with a new practice-v2 aggregator that pulls `latest_graded_attempt` + `attempt_count` from `PracticeAttemptRepository` keyed by `(user_id, guideline_id)` and merges into the grouped structure. **This is a query-path restructure, not a rename** — see §5.10.
- `tutor/models/session_state.py` — delete `ExamQuestion`, `ExamFeedback`, all `exam_*` fields (line 224+), **`practice_questions_answered`** (line 231), and the `self.mode == "practice"` branch in `is_complete` (line 281).
- `tutor/agents/master_tutor.py` — delete `_build_practice_turn_prompt` (line 986), `session.mode == "practice"` branches (lines 712, 833), and any `practice_questions_answered` reads (lines 752, 1043).
- `tutor/models/messages.py` + `shared/models/schemas.py` — delete `EndExamResponse`, `ExamReviewResponse`, `ExamReviewQuestion`, `ResumableSessionResponse.exam_answered`, `ResumableSessionResponse.practice_questions_answered`. Remove the legacy integer `latest_exam_score` / `latest_exam_total` once frontend no longer reads them (Step 13 cleanup).

**Deleted backend files (Step 12):**
- `tutor/services/exam_service.py`
- `tutor/prompts/exam_prompts.py`
- `tutor/prompts/practice_prompts.py` (old teacher-in-the-loop prompts).
- `tests/unit/test_exam_lifecycle.py` (tests the deleted exam lifecycle).
- Any `tests/unit/test_practice*.py` that tests the old chat-based practice flow (grep for references to `_process_practice_turn` or `practice_prompts`).

**Step 12 grep gate (CI-verifiable):**
```
grep -rE '(ExamService|exam_prompts|practice_prompts|_process_practice_turn|_process_exam_turn|_build_practice_turn_prompt|practice_questions_answered|exam_questions|ExamQuestion|ExamFeedback|end-practice|end-exam|exam-review)' llm-backend/ | grep -v docs/ | wc -l
```
must return `0` before Step 12 can be considered complete.

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
| `practice_questions` | Offline question bank per topic (30–40 rows per guideline). **Mutable** — regenerated when admin re-syncs. | `id` (VARCHAR PK), `guideline_id` (VARCHAR FK, cascade), `format` (VARCHAR — one of 12), `difficulty` (VARCHAR — easy/medium/hard), `concept_tag` (VARCHAR), `question_json` (JSONB — format-specific payload + `correct_answer` + `explanation_why` + FF: `expected_answer`, `grading_rubric`), `generator_model` (VARCHAR), `created_at` (DATETIME) |
| `practice_attempts` | One row per practice attempt (in-progress or submitted). **Immutable snapshot** — never references the bank after creation. | `id` (VARCHAR PK), `user_id` (VARCHAR FK, cascade), `guideline_id` (VARCHAR FK, cascade), `question_ids` (JSONB — ordered array of 10; audit/analytics only, not used at render time), `questions_snapshot_json` (JSONB — full question payload copied from `practice_questions.question_json` at attempt creation, including `correct_answer`, `explanation_why`, options/pairs/etc., presentation order seed), `answers_json` (JSONB — `{q_idx: <answer>}` partial/final), `grading_json` (JSONB — `{q_idx: {score, correct, rationale, wrong_pick_explanation, visual_explanation_code}}`), `total_score` (FLOAT, nullable), `total_possible` (INT, default 10), `status` (VARCHAR — `in_progress`, `grading`, `graded`, `grading_failed`), `grading_error` (TEXT, nullable), `grading_attempts` (INT, default 0), `results_viewed_at` (DATETIME, nullable), `created_at` (DATETIME), `submitted_at` (DATETIME, nullable), `graded_at` (DATETIME, nullable) |

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

### Migration plan (`db.py`) — **split additive from destructive**

The migration is intentionally split across two deploys. Step 1 ships **only additive** work so nothing in the live (exam + old-practice) runtime breaks. Destructive cleanup happens in Step 12 alongside the code that stops writing to those tables/columns.

**Additive migration — Step 1 (safe to deploy before any code changes land):**
1. `Base.metadata.create_all()` creates `practice_questions` + `practice_attempts` tables (SQLAlchemy declarative models). Existing `sessions.exam_score` / `sessions.exam_total` columns **remain** for now — live exam code still writes to them.
2. New migration function `_apply_practice_tables(db_manager)`:
   - Idempotently create the partial unique index on `practice_attempts`.
   - Ensure `practice_bank_generator` and `practice_grader` rows exist in `llm_config` (via `_ensure_llm_config()` helper — existing pattern used for `explanation_generator`).
3. Update `_LLM_CONFIG_SEEDS` with two new rows:

| Component Key | Provider | Model | Purpose |
|---------------|----------|-------|---------|
| `practice_bank_generator` | openai | gpt-5.2 | Practice question bank generation + correctness review (review/refine pattern) |
| `practice_grader` | openai | gpt-4o-mini | Free-form grading + per-pick wrong-answer rationale. gpt-4o-mini for latency — grading runs 1× per wrong/blank answer per attempt (up to 10). Admin can override if quality is off. |

**Destructive cleanup — Step 12 (same deploy as backend exam/old-practice removal):**
New migration function `_cleanup_exam_and_old_practice_data(db_manager)`, guarded by an explicit `with engine.begin():` transaction:
   - `DELETE FROM sessions WHERE mode IN ('exam', 'practice')` — discards all exam + old-chat-practice session history (FR-1 + FR-2).
   - `ALTER TABLE sessions DROP COLUMN IF EXISTS exam_score`
   - `ALTER TABLE sessions DROP COLUMN IF EXISTS exam_total`

This ordering guarantees that between Step 1 and Step 12 deploys, the running app continues to find its exam columns and sessions rows. No half-state.

### Self-contained attempts (decoupled from bank mutations)

**Decision — snapshot the question payload into the attempt at creation.** `practice_attempts.questions_snapshot_json` stores the full `question_json` (including `correct_answer`, `explanation_why`, options/pairs/sequence items, FF expected_answer/rubric) at `start_or_resume` time. Rendering, grading, and review read **only from the snapshot**, never from `practice_questions`.

Why: `PracticeQuestionRepository.delete_by_guideline()` + force-regeneration is an admin workflow (FR-50 observability + future re-ingestion). If attempts stored only FK `question_ids[]`, a bank regeneration would orphan every historical attempt — FR-44 ("stored forever") is meaningless if the rendered review is broken. The snapshot also stabilizes in-progress attempts against re-ingestion happening mid-attempt.

Tradeoff: ~10 rows × (~1–3KB per question payload) = ~10–30KB per attempt row. At 1000 attempts/day × 30KB = ~30MB/day — negligible.

**Decision — presentation order seed.** For components that randomize on mount (option order in `PickOneActivity`, pair order in `MatchActivity`, item order in `SortBuckets`), the snapshot includes a per-question `presentation_seed: int` generated at attempt creation. The frontend passes this seed to the component's shuffle logic so **resume shows the same layout** (FR-20: "same questions in the same order"). Without this, resume would shuffle differently and confuse the student.

**Decision — `visual_explanation_code` slot.** `grading_json[q_idx]` includes an optional `visual_explanation_code` field (nullable string). v1 leaves it null (FR-43 Pixi on eval cards is deferred). Pre-allocating the slot avoids a later migration when FR-43 ships.

**Decision — why a dedicated `practice_attempts` table (not reuse `sessions`):** Exam mode shoehorned a batch drill into `sessions` by storing `exam_questions[]` inside `state_json`. That forced every batch-drill concern through session serialization, the `state_version` CAS loop, and tutor-centric ownership checks. Let's Practice has no conversation history and no LLM turn — a purpose-built table is cleaner, smaller (no 100kb `state_json` per attempt), and makes "history of attempts" a trivial indexed query.

**Decision — why `question_json` is JSONB (not per-format columns):** the 11 activity types already use heterogeneous per-activity fields in `check_in_enrichment_service.CheckInDecision` + `ExplanationRepository.CheckInActivity`. Reusing the same shape keeps the frontend renderer wiring familiar and avoids a 30-column table. Pydantic `PracticeQuestionContent` (see §4) validates the JSON on write.

---

## 4. Backend Changes

### 4.1 `tutor/` module — runtime

#### API Layer (`tutor/api/practice.py`)

Mount as a new router with prefix `/practice` in `main.py`.

| Endpoint | Method | Path | Purpose |
|----------|--------|------|---------|
| `availability` | GET | `/practice/topics/{guideline_id}/availability` | `{has_bank, bank_size}` — used by topic list for greyed-out state (FR-5) |
| `start_or_resume` | POST | `/practice/attempts` | Body `{guideline_id}`. Returns existing `in_progress` attempt if one exists (FR-33), else creates a new 10-question set with `questions_snapshot_json` populated. Handles concurrent-tab race via catch-`IntegrityError`-and-reread (see "Concurrency" below). |
| `get_attempt` | GET | `/practice/attempts/{attempt_id}` | Full attempt: snapshot questions + current answers + status + grading_json if graded. Used by PracticeRunner (resume), Results, and Review pages. |
| `save_answer` | PATCH | `/practice/attempts/{attempt_id}/answer` | Body `{q_idx, answer}`. Idempotent auto-save as student moves through set. Returns 409 with `current_status` if `status != in_progress` (**not a silent no-op** — see "Debounce vs submit race" below). |
| `submit` | POST | `/practice/attempts/{attempt_id}/submit` | **Body `{final_answers_json: {q_idx: <answer>}}`**. Persists final answers **and** flips status `in_progress → grading` in a single transaction (atomic — kills the debounce race). Spawns background grading worker after commit. Returns immediately. |
| `retry_grading` | POST | `/practice/attempts/{attempt_id}/retry-grading` | Only valid when `status == grading_failed`. Resets `grading_error`, flips to `grading`, re-spawns worker. |
| `list_attempts` | GET | `/practice/attempts?guideline_id=X` | History for a topic, newest first (FR-45). |
| `recent_unread` | GET | `/practice/attempts/recent` | Returns attempts where **`status IN ('graded', 'grading_failed') AND results_viewed_at IS NULL`** for the current user. Drives the banner (FR-35 success + FR-40 failure). Polled every 30s by the banner; pauses when `document.visibilityState != 'visible'`. |
| `mark_viewed` | POST | `/practice/attempts/{attempt_id}/mark-viewed` | Sets `results_viewed_at` — clears banner for that attempt. Valid for both graded and grading_failed (tapping the failure banner to acknowledge is the same gesture as tapping results). |

**Debounce vs submit race (resolution):** the frontend debounces `save_answer` at 500ms. A student could edit a Review-screen answer and tap Submit before the debounced PATCH fires. To avoid silent answer loss:
1. `POST /submit` **carries the full final `answers_json`** in the body. The service merges it into `answers_json` before the status flip.
2. Server-side, the transaction is: `SELECT … FOR UPDATE` on the attempt row → verify `status == in_progress` → merge `final_answers_json` → set `status = 'grading'` + `submitted_at = now()` → commit → spawn worker.
3. The frontend `PracticeRunner` **cancels** any in-flight debounced PATCH before issuing the Submit (via AbortController), then calls Submit with the authoritative local state. If a stray late PATCH still arrives after commit, the server returns 409 (the client discards it).

**Concurrency — start_or_resume race:** two tabs calling `POST /attempts` concurrently both see no `in_progress` row, both try to INSERT. The partial unique index rejects the second with IntegrityError. The service catches IntegrityError, re-reads the `in_progress` row (written by the winning tab), and returns it. Unit test: `test_practice_service_concurrent_start_is_idempotent`.

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
        """FR-15..FR-20, FR-33 — return in-progress attempt if any, else new set.
        Handles concurrent-tab race: if the INSERT hits the partial unique index,
        re-read and return the winner (idempotent).
        """
        existing = self.attempt_repo.get_in_progress(user_id, guideline_id)
        if existing:
            return existing
        questions = self._select_set(guideline_id)  # 10 PracticeQuestion rows
        snapshot = [self._snapshot_question(q) for q in questions]
        try:
            return self.attempt_repo.create(
                user_id=user_id,
                guideline_id=guideline_id,
                question_ids=[q.id for q in questions],
                questions_snapshot_json=snapshot,
            )
        except IntegrityError:
            self.db.rollback()
            winner = self.attempt_repo.get_in_progress(user_id, guideline_id)
            if winner is None:
                raise  # genuinely unexpected
            return winner

    def _snapshot_question(self, q: PracticeQuestion) -> dict:
        """Copy the full question payload + a per-question presentation_seed
        so resume shows the same layout (FR-20)."""
        payload = dict(q.question_json)
        payload["_id"] = q.id
        payload["_format"] = q.format
        payload["_difficulty"] = q.difficulty
        payload["_concept_tag"] = q.concept_tag
        payload["_presentation_seed"] = random.randint(0, 2**31 - 1)
        return payload

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
        picked = self._pick_with_variety(structured, quota)
        chosen = free_form + picked
        random.shuffle(chosen)
        return self._enforce_no_consecutive_same_format(chosen)

    def save_answer(self, attempt_id: str, q_idx: int, answer) -> None:
        """Merges answer into answers_json. Raises ConflictError (→ HTTP 409)
        if status != 'in_progress'. Caller must be resilient to 409 on late PATCH."""
        ...

    def submit(self, attempt_id: str, user_id: str, final_answers: dict) -> PracticeAttempt:
        """Atomic: merge final_answers_json + flip status → 'grading' in one transaction.
        Spawns grading worker AFTER commit.
        """
        with self.db.begin_nested():  # SAVEPOINT — commit at exit
            row = (
                self.db.query(PracticeAttempt)
                .filter_by(id=attempt_id, user_id=user_id)
                .with_for_update()
                .one()
            )
            if row.status != "in_progress":
                raise AttemptNotInProgressError(row.status)
            row.answers_json = {**(row.answers_json or {}), **final_answers}
            row.status = "grading"
            row.submitted_at = datetime.utcnow()
        self.db.commit()
        self._spawn_grading_worker(attempt_id, user_id)
        return row

    def redact_for_student(self, snapshot: dict) -> dict:
        """Strip correct_answer / correct_index / correct_answer_bool / pairs'
        correctness / expected_answer / grading_rubric / explanation_why before
        sending to the student during the set (FR-26)."""
        ...
```

**Decision — grading worker mechanism:** use the exact threading pattern from `book_ingestion_v2/api/processing_routes.py::run_in_background_v2` — a fresh DB session, try/except, separate session for error handling after long LLM calls. The existing pattern is proven and doesn't require a task queue.

**Decision — threading vs asyncio boundary.** `run_in_background_v2` spawns a sync `threading.Thread`. For the "parallel ~1s wall-clock" grading claim (§6.5) we need concurrent LLM calls inside that thread. Approach: the worker uses `concurrent.futures.ThreadPoolExecutor(max_workers=10)` for per-question LLM calls (the existing OpenAI Python SDK is thread-safe for blocking calls; the grading path doesn't need async). **No `asyncio.gather` inside the sync worker** — the earlier §6.5 wording is updated accordingly. Simpler, fewer moving parts.

**Failure detection — honest v1 scope.** There is **no attempt-level heartbeat** today. `chapter_job_service` heartbeats operate on `ChapterProcessingJob` rows, which are unrelated to practice attempts. v1 therefore only catches failures that surface as **synchronous exceptions inside the worker** (LLM 5xx, OpenAI timeouts, JSON parse errors) — these get the 3-attempt exponential-backoff retry, then flip the attempt to `grading_failed` (FR-40). Silent thread death (process crash, container restart mid-grade) will leave the attempt stuck in `status='grading'` indefinitely. Students can see this on the landing page ("grading in progress…") but won't auto-recover.

Mitigation (post-v1, documented in §11): add `grading_started_at` timestamp + a periodic sweeper that flips `status='grading' AND grading_started_at < now() - 5min` to `grading_failed`. Out of scope for v1; if field reports surface stuck attempts, prioritize then.

#### Grading Service (`tutor/services/practice_grading_service.py`)

```python
class PracticeGradingService:
    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service  # Configured with practice_grader model

    def grade_attempt(self, attempt_id: str) -> None:
        """Entry point called from the background thread. Loads attempt +
        reads questions from attempt.questions_snapshot_json (NOT from the
        practice_questions table — the bank may have been regenerated since).

        For each of the 10 snapshot questions:
           - structured format: deterministic comparison (FR-37)
           - free_form:         LLM call for 0.0–1.0 score + rationale (FR-38)
           - any wrong/blank:   LLM call for 'wrong_pick_explanation' (FR-39)
        Uses ThreadPoolExecutor(max_workers=10) to fan out the LLM calls.
        Writes grading_json + total_score + graded_at. Retry 3× exponential
        backoff per LLM call; after 3 failures on any single call → the whole
        attempt flips to status='grading_failed' with the first failing error.
        """

    def _grade_structured(self, snapshot_q: dict, answer) -> tuple[float, bool]:
        """Deterministic: compare answer against snapshot's correct_index /
        correct_answer_bool / pairs / sequence_items / bucket_items / ...
        Blank → (0.0, False). No LLM call."""

    def _grade_freeform(self, snapshot_q: dict, answer) -> tuple[float, str]:
        """LLM: returns (fractional 0.0–1.0, 1-sentence rationale).
        Structured output schema enforces bounds (response_format=json_schema, strict)."""

    def _explain_wrong_pick(self, snapshot_q: dict, student_answer) -> str:
        """LLM: 'The student picked X but the correct answer is Y because ...'
        Generates per FR-39 for every wrong/blank structured answer."""
```

**Decision — one LLM call per wrong answer (not batched):** per-pick rationale depends on the student's specific answer, which the LLM cannot accurately analyze in a batch without leaking cross-question context. 10 parallel small calls finish in ≲1s with gpt-4o-mini via ThreadPoolExecutor. If latency becomes a complaint, revisit after measurement. This matches the existing "one LLM call per remedial card" pattern in `master_tutor.generate_simplified_card`.

**Retry pattern:** per LLM call, 3 attempts with 10s / 20s / 40s backoff (inside the thread-pool task). On final failure of any single call: `attempt.status = "grading_failed"`, `attempt.grading_error = "..."`, banner surfaces the attempt with a Retry-grading action (via the `status IN ('graded', 'grading_failed')` unread-banner query — see §4.1).

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

**Pipeline position — depends on explanation generation, not just topic decomposition.** The bank generator prompt (§6.1) consumes existing explanation cards as concept-grounding input. Therefore:

```
topic extraction → topic decomposition → explanation generation → check-in enrichment → practice-bank generation
```

The admin workflow mirrors check-in enrichment: a chapter cannot generate practice banks until explanation generation has completed for its topics. The `generate-practice-banks` endpoint guards on this (returns 400 "Explanations not generated yet" if any target guideline is missing `explanation_cards`). PRD wording "new last stage after topic decomposition" is updated to "new last stage after explanation generation" in the technical doc (Step 14).

**Bank-size edge case (FR-9).** If a topic is purely procedural and the LLM returns zero free-form questions after validate, we prefer to respect the topic's nature rather than force-insert a contrived FF. The generator service accepts `0 ≤ FF count ≤ 3` at validate-time; this is a minor deviation from PRD FR-9 "1–3 free-form". Flagged as Q6 in §12 for PRD author confirmation before implementation.


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

**`QuestionRenderer.tsx`**: dispatches on `question.format` to a **new practice-capture layer** (NOT the existing 11 check-in components as-is). See §5.4.1.

For `free_form` questions, `FreeFormQuestion.tsx` renders a simple `<textarea>`.

### 5.4.1 Practice-capture layer for the 11 interactive formats

**Reality check.** Current components in `llm-frontend/src/components/*Activity.tsx` are **correctness-driven, uncontrolled, and side-effectful**:
- Auto-submit on first correct pick (`PickOneActivity.tsx:50`); permanently disable further interaction (`disabled={isCorrect !== null}`).
- Play TTS on success and hints (`playTTS(checkIn.success_message)`, `playTTS(checkIn.hint)`) — conflicts with FR-28 (no audio on practice).
- Show correctness styling + shake animation — conflicts with FR-26 (no correctness signals).
- Randomize option order / pair order on mount via `useMemo`/`useState` initializers — would shuffle differently on resume, breaking FR-20.
- Emit `onComplete(CheckInActivityResult)` only after they decide the student is done — not controlled state, cannot hydrate from prior answer.
- Several components (e.g., `MatchActivity`, `SwipeClassifyActivity`) have multi-step internal state (selected-left-then-right, swipe-right-sorting) that is not exposed.

A `mode` prop alone does not fix this. Plan approach: **build a parallel `components/practice/capture/` layer** — one controlled component per format, ~100–200 lines each, reusing the **presentation** building blocks from the check-in components (option buttons, pair lists, swipe cards) but with:

| Requirement | How the capture layer meets it |
|---|---|
| Controlled answer state (FR-25) | Each component is pure-controlled: `value` + `onChange(answer)` props. Parent `PracticeRunner` owns state. |
| Hydrate from server on resume (FR-33) | Initial `value` comes from `attempt.answers_json[q_idx]`. |
| Stable presentation on resume (FR-20) | Shuffle uses `seed` prop (from snapshot's `_presentation_seed`). Deterministic. |
| No correctness signals (FR-26) | No `correct` / `wrong` classes, no shake animation, no disabling of options. |
| No audio (FR-28) | No `playTTS` calls. |
| No hints (FR-26) | No hint reveal logic. |
| Changeable until submit (FR-25) | Tapping a different option replaces the selection. Tapping the same option deselects. |

**Shared primitives to extract from check-in components into `components/shared/`:**
- `<OptionButton>` — option-row rendering (used by PickOne, TrueFalse, TapToEliminate, OddOneOut, SpotTheError)
- `<PairColumn>` / `<PairLine>` — two-column pair rendering (used by MatchPairs)
- `<BucketZone>` — drop target (used by SortBuckets, SwipeClassify)
- `<SequenceList>` — reorderable list (used by Sequence)

This refactor is **its own implementation step** (§8 Step 9a), sequenced before the frontend runtime (Step 9b). Without it, §8 Step 9 cannot deliver FR-25/26/28/33.

**Counter-option considered:** add a `mode='practice_capture'` prop to the existing 11 components and branch internally. Rejected: each component would need to fork ~60% of its logic, the branches would rot unless kept rigorously paired, and resume hydration requires lifting state anyway. A dedicated capture layer is smaller over time.

### 5.5 New: `PracticeResultsPage.tsx`

```
┌──────────────────────┐
│  Practice Results    │
│                      │
│       7.5 / 10       │
│                      │
│  [ Reteach         ] │   → /learn/:subject/:chapter/:topic?autostart=teach_me
│  [ Practice again  ] │   → POST /practice/attempts → /practice/:newId
│  [ Review my picks ] │   → PracticeReviewPage
└──────────────────────┘
```

Also calls `POST /practice/attempts/{id}/mark-viewed` on mount to clear the banner.

**Reteach autoselect implementation.** `ModeSelectPage.tsx:21–129` currently has no query-param autoselect behavior. Add: on mount, read `?autostart=<mode>` from `useSearchParams()`. If present and the mode is available for this topic, immediately invoke the existing Teach Me entry handler (same as tapping the Teach Me tile), then clear the query param via `navigate(..., { replace: true })` to avoid re-firing on back-navigation.

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

**Placement — above AppShell, covering ALL authenticated routes including chat sessions.** `AppShell` currently wraps only non-chat authenticated routes (`/learn/:subject`, `/learn/:subject/:chapter`, ModeSelectPage, report-card, profile, history — see `llm-frontend/src/App.tsx:94–119`). The chat-session routes (`teach/:sessionId`, `clarify/:sessionId`, `practice/:sessionId`, `exam/:sessionId` — lines 121–149) are **outside AppShell** by design (they have their own nav-bar).

FR-34 requires the banner to fire even when the student is mid-Teach-Me (post-submit, they go start another activity while grading runs in the background). So mounting `PracticeBanner` inside AppShell alone misses half the target surface.

**Approach:** mount `PracticeBanner` in a new top-level wrapper, `<AuthenticatedLayout>`, that sits **above both** the AppShell-wrapped route group and the chat-session routes but **below** `<ProtectedRoute>` / `<OnboardingGuard>`. The banner renders as a fixed-position element at the top of the viewport (z-index above all nav-bars); it doesn't interfere with chat session layout. Update `App.tsx` routes accordingly.

Polls `GET /practice/attempts/recent` every 30s. Pauses polling when `document.visibilityState != 'visible'` (zero-cost optimization; resumes immediately on visibility change). The `/recent` filter is `status IN ('graded', 'grading_failed') AND results_viewed_at IS NULL` (see §4.1 fix — earlier draft's `graded_at IS NOT NULL` filter silently excluded failed attempts from the banner).

**Success banner** (attempt has `status='graded'`):
```
┌────────────────────────────────────────────────┐
│ ✓ Your Practice results are ready  →           │
└────────────────────────────────────────────────┘
```
Tap → navigate to `PracticeResultsPage` for that attempt.

**Failure banner** (attempt has `status='grading_failed'`):
```
┌────────────────────────────────────────────────┐
│ ⚠ Grading failed. Retry?                       │
└────────────────────────────────────────────────┘
```
Tap → `POST /practice/attempts/{id}/retry-grading`, flip to a brief "Retrying…" state, reload banner state.

Silent when no unread attempts.

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

### 5.10 Modified: Scorecard — **query-path restructure, not a rename**

**Current code** (`tutor/services/report_card_service.py:240–308`) accumulates per-topic "exam" stats by iterating sessions and reading `state.get("exam_total_correct")` + `state.get("exam_questions")` **from `state_json`** — not from the `exam_score` / `exam_total` columns on `sessions`. Migration needs a structural change, not a rename.

**New aggregation path:**
1. After the existing `_group_sessions_by_topic` loop finishes (teach_me coverage, last_studied, etc.), call a new `_merge_practice_attempts_into_grouped(grouped, user_id)` helper.
2. That helper queries `PracticeAttemptRepository` with an aggregate:
   ```sql
   SELECT guideline_id,
          (array_agg(total_score ORDER BY graded_at DESC))[1] AS latest_score,
          (array_agg(total_possible ORDER BY graded_at DESC))[1] AS latest_total,
          COUNT(*) FILTER (WHERE status = 'graded') AS attempt_count,
          MAX(graded_at) AS last_practiced
     FROM practice_attempts
    WHERE user_id = :user_id AND status = 'graded'
    GROUP BY guideline_id
   ```
3. For each returned row, find the topic in `grouped[subject][chapter]["topics"][topic_key]` by `guideline_id` and set `latest_practice_score`, `latest_practice_total`, `practice_attempt_count`, and `last_practiced`.
4. Remove the old `mode == "exam"` and `mode == "practice"` branches from `_group_sessions_by_topic` (lines 85, 111, 263–296) — they're no longer a source of scorecard data.

**Backend response schema (`shared/models/schemas.py:87–97`):**
- **Keep** the integer `latest_exam_score` / `latest_exam_total` fields during Steps 1–11 (frontend still reads them).
- **Add** `latest_practice_score: Optional[float]`, `latest_practice_total: Optional[int]`, `practice_attempt_count: Optional[int]`.
- Step 11 populates the new fields; Step 13 removes the legacy integer exam fields once the frontend migrates.

**Frontend (`ReportCardPage.tsx` + types):**
- Rename on-screen label "Exam scores" → "Practice scores" (FR-48).
- Per-topic display: show `latest_practice_score / latest_practice_total (N attempts)` using fractional rendering (e.g., "7.5/10"). `attempt_count` is pluralized: "1 attempt" / "3 attempts" (FR-49).

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
- **Student path — per-pick rationale**: one call per wrong/blank structured answer. gpt-4o-mini, ~500 in / ~100 out. Worst case (10 wrongs): ~10 calls, ~5–8s end-to-end if sequential. **Optimization**: grade all 10 questions in parallel via `ThreadPoolExecutor(max_workers=10)` inside the sync grading worker (matches `run_in_background_v2`'s threading model — see §4.1 "threading vs asyncio boundary"). Compresses to ~1s wall-clock.
- **Student path — free-form grading**: 1–3 calls per attempt. ~1K in / ~200 out each. Parallel with rationale calls (same executor).

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

Each step is independently testable; earlier steps don't block on later ones landing. **Critical sequencing constraint:** additive work in Steps 1–11 leaves all existing exam + old-chat-practice code live and functional. Destructive removal is concentrated in Step 12 so production never has a half-deleted state.

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1 | **DB schema (additive only)**: new tables + LLM config seeds. **Does not** drop columns or delete rows. | `shared/models/entities.py` (add models, do **not** touch exam columns), `db.py` (add `_apply_practice_tables`; **do not** add `_cleanup_exam_and_old_practice_data` yet) | — | `python db.py --migrate` runs clean on a DB that still has live exam data; `sessions.exam_score/exam_total` still present; new tables + indexes + seeds present |
| 2 | **Repositories**: `PracticeQuestionRepository`, `PracticeAttemptRepository` (with `questions_snapshot_json` support + `list_recent_unread` filter on `status IN ('graded', 'grading_failed')`) | `shared/repositories/practice_question_repository.py`, `shared/repositories/practice_attempt_repository.py` | 1 | Unit tests with test DB; `test_partial_unique_index_rejects_second_in_progress`; `test_list_recent_unread_includes_failed` |
| 3 | **Bank generator service** + prompts + `V2JobType.PRACTICE_BANK_GENERATION` + dependency check on explanation generation | `book_ingestion_v2/services/practice_bank_generator_service.py`, `book_ingestion_v2/prompts/practice_bank_generation.txt`, `practice_bank_review_refine.txt`, `book_ingestion_v2/constants.py` | 1, 2 | Unit tests with mocked LLM; end-to-end against a real topic with explanation cards |
| 4 | **Ingestion API**: generate-practice-banks + status + bank-viewer endpoints | `book_ingestion_v2/api/sync_routes.py` | 3 | curl against local backend; job status transitions |
| 5 | **Admin UI**: `PracticeBankAdmin.tsx` page + hook in `BookV2Detail.tsx` | frontend admin | 4 | Manual — generate bank for one topic, view it |
| 6 | **Runtime grading service** (sync + ThreadPoolExecutor fan-out) | `tutor/services/practice_grading_service.py`, `tutor/prompts/practice_grading.py` | 2 | Unit tests for deterministic grading paths; `test_grading_failure_flips_status`; `test_grading_retries_3x_then_fails` |
| 7 | **Runtime practice service** (start_or_resume with concurrent-race handling + snapshot + atomic submit) | `tutor/services/practice_service.py`, `tutor/models/practice.py` | 2, 6 | Unit: `_select_set` (mix, FF absorption, variety), `test_concurrent_start_is_idempotent`, `test_submit_atomically_persists_final_answers_and_flips_status`, `test_save_answer_after_submit_returns_409` |
| 8 | **Runtime API**: `/practice` router (including `POST /submit` body-final-answers contract) | `tutor/api/practice.py`, `main.py` | 7 | curl full flow locally: start → save → submit-with-final-answers → poll /recent → mark-viewed. Integration test verifies debounce-race fix. |
| **9a** | **Practice-capture component layer**: 11 new controlled components in `components/practice/capture/` + extracted shared primitives in `components/shared/`. Existing `*Activity.tsx` components remain untouched and continue serving check-ins. | `llm-frontend/src/components/practice/capture/*.tsx`, `llm-frontend/src/components/shared/OptionButton.tsx` etc. | — (can be parallel with 6–8) | Storybook-style unit tests per component: hydrate from `value` prop, emit `onChange` on interaction, no TTS, no correctness styling, deterministic shuffle from `seed` prop |
| **9b** | **Frontend runtime**: landing + runner (using capture layer) + results + review + history + banner | `llm-frontend/src/pages/Practice*.tsx`, `llm-frontend/src/components/practice/{QuestionRenderer,FreeFormQuestion,PracticeBanner}.tsx`, `api.ts` | 8, 9a | Manual browser test — full student flow on a topic with a seeded bank, including pause/resume preserving option order (FR-20) |
| 9c | **Banner placement refactor**: new `<AuthenticatedLayout>` wrapper above both AppShell and chat-session routes; mount `PracticeBanner` there | `llm-frontend/src/App.tsx` | 9b | Manual: submit practice, start Teach Me, verify banner appears when grading completes |
| 10 | **ModeSelection refactor**: tile simplification + landing routing + disabled-when-no-bank + `?autostart=teach_me` handler | `llm-frontend/src/components/ModeSelection.tsx`, `pages/ModeSelectPage.tsx` | 9b | Manual — tap Let's Practice → landing; tap Reteach from results → ModeSelectPage auto-starts Teach Me |
| 11 | **Scorecard (additive)**: add new practice-v2 aggregator in `report_card_service` + new response fields; do **not** yet remove old `mode == "exam"` / `mode == "practice"` branches | `tutor/services/report_card_service.py`, `llm-frontend/src/pages/ReportCardPage.tsx`, `shared/models/schemas.py`, `api.ts` types | 2 | Unit test on `get_report_card` with mixed teach_me + practice-v2 attempts; legacy exam/practice session data still renders old fields correctly |
| 12 | **Destructive cleanup (backend)** — ALL of the following in a single deploy: <br>• Delete `exam_service.py`, `exam_prompts.py`, `practice_prompts.py`, `tests/unit/test_exam_lifecycle.py`. <br>• Remove all `session.mode == "exam"` and `session.mode == "practice"` branches across orchestrator, session_service, master_tutor, session_state, report_card_service. <br>• Remove `_process_exam_turn`, `_build_exam_feedback`, `generate_exam_welcome`, `_process_practice_turn`, `_build_practice_turn_prompt`. <br>• Remove `/sessions/{id}/end-exam`, `/sessions/{id}/exam-review`, `/sessions/{id}/end-practice` endpoints + `EndExamResponse` / `ExamReviewResponse` / `ExamReviewQuestion` schemas. <br>• Remove `exam_*` fields and `practice_questions_answered` from `SessionState` + `ResumableSessionResponse`. <br>• Run `_cleanup_exam_and_old_practice_data()` migration (DELETE rows + DROP columns in single transaction). <br>• Remove old-exam branches in `report_card_service`. | many — see §2 "Destructive" list | 9c, 10, 11 (all replacements live) | Backend tests pass; the grep-gate command in §2 returns 0; `python db.py --migrate` is idempotent; no production 500s from missing columns |
| 13 | **Destructive cleanup (frontend)**: delete `ExamReviewPage.tsx`, `/exam/:sessionId`, `/exam-review/:sessionId`, `/practice/:sessionId` routes; delete exam types + old practice types from `api.ts`; remove legacy `latest_exam_score`/`latest_exam_total` from response schema + reads | `llm-frontend/**/Exam*`, `App.tsx`, `api.ts`, `ReportCardPage.tsx` | 12 | `grep -rE '(exam-review\|end-exam\|/exam/\|end-practice\|ExamReviewPage\|getExamReview)' llm-frontend/src` returns 0 |
| 14 | **Docs**: new principles/functional/technical docs for practice; update scorecard + architecture-overview + database + ai-agent-files; delete `docs/feature-development/teach-me-practice-split/` (superseded); delete stale exam docs | `docs/principles/practice-mode.md`, `docs/functional/practice-mode.md`, `docs/technical/practice-mode.md`, updates to existing docs | 13 | `/update-all-docs` skill passes |

**Order rationale:** Steps 1–11 are **purely additive** — each is shippable independently and leaves exam + old-chat-practice live and working. Step 12 bundles ALL destructive changes (code + DB migration) in a single atomic deploy; running Step 1's migration alone would drop columns the live code still writes to, so the DDL is deliberately deferred. Steps 9a/9b/9c are split because the capture-component layer (9a) is a substantial refactor that the runtime UI (9b) depends on and the banner placement (9c) is a routing-tree change best isolated.

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
| `test_practice_full_flow` | POST /attempts → PATCH answers → POST /submit with final_answers_json → poll grading → GET attempt shows `status=graded` + grading_json |
| `test_submit_atomically_persists_final_answers_and_flips_status` | Debounce-race fix: submit body's `final_answers_json` overwrites any older auto-saved answer atomically with the status flip |
| `test_save_answer_after_submit_returns_409` | Late PATCH arriving after commit gets 409, not silent no-op |
| `test_concurrent_start_is_idempotent` | Two simultaneous POST /attempts → one row created, both return it |
| `test_review_renders_correctly_after_bank_regenerated` | Create attempt, submit, then `delete_by_guideline` + regenerate → GET attempt still returns full question payload from snapshot |
| `test_resume_presentation_order_stable` | Start attempt, answer Q1 with option B selected, pause, resume → option layout matches original (seed-driven shuffle) |
| `test_practice_parallel_attempts_across_topics` | Submit on topic A, start attempt on topic B before A finishes grading (FR-36) |
| `test_practice_multiple_history_attempts` | 3 submitted attempts on same topic → GET /attempts?guideline_id returns all 3 newest-first |
| `test_practice_resume_on_landing` | Create attempt, disconnect, hit landing again → in-progress attempt surfaces |
| `test_recent_unread_includes_failed` | `/recent` returns attempts with `status='grading_failed'`, not just `status='graded'` |
| `test_grading_failure_retry_clears_error` | Submit → force grading failure → `POST /retry-grading` → success → banner clears |
| `test_banner_covers_chat_session_routes` | Frontend test: submit practice, navigate to `/learn/.../teach/:sessionId` (outside AppShell), verify banner visible when grading completes |
| `test_reteach_autoselect` | Frontend test: navigate to `/learn/.../topic?autostart=teach_me` → Teach Me auto-starts, query param cleared |
| `test_step1_migration_is_additive_only` | Run Step 1 migration on a DB populated with exam sessions + exam columns → all exam data intact, new tables created |
| `test_step12_migration_cleans_up` | Run Step 12 migration → exam/old-practice rows deleted, exam columns dropped, all wrapped in single transaction |
| `test_exam_mode_404_after_deletion` | After Step 12: POST /sessions {mode: "exam"} returns 400 "Mode not supported"; POST /sessions {mode: "practice"} same |

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

- **Migration rollout — two deploys, not one:**
  - **Deploys for Steps 1–11** (additive): run `_apply_practice_tables` only. Creates new tables, new indexes, new LLM config seeds. Does **not** touch exam columns or sessions rows. Idempotent; safe to re-run on every deploy.
  - **Deploy for Step 12** (destructive): same deploy as the exam/old-practice code removal. Runs `_cleanup_exam_and_old_practice_data` inside a single `with engine.begin():` transaction — `DELETE FROM sessions WHERE mode IN ('exam', 'practice')` + `ALTER TABLE sessions DROP COLUMN IF EXISTS exam_score` + `ALTER TABLE sessions DROP COLUMN IF EXISTS exam_total`. Confirmed acceptable per FR-1 + FR-2 (no exam or old-practice data preserved).
- **Feature rollout:** ship to all users at once (PRD §10 out-of-scope: no feature flag, no phased rollout).
- **Ingestion backfill:** after Step 4 ships, run `POST /admin/v2/books/{id}/generate-practice-banks` for each existing book to populate banks. Without this step, every topic's Practice tile will be greyed out. Suggest a one-shot script `scripts/backfill_practice_banks.py` that iterates all books and calls the endpoint. **Revised time estimate:** ~2 min per guideline at gpt-5.2 medium + 1 review round; a chapter with 20 topics takes ~40 min (sequential within a chapter because of the chapter-level lock); parallelize across books. Start early — can run against Step 4 deploy while Steps 5–11 are still in progress.
- **Rollback plan (Step 12 only — other steps are pure additive):** the only meaningful rollback window is the Step 12 deploy. Take a DB snapshot immediately before it. If a critical bug surfaces post-deploy, revert the container image and restore the snapshot. Steps 1–11 can be rolled back by reverting the container alone (no data migration to reverse).
- **Infra:** no new AWS resources. No new secrets. `practice_grader` → gpt-4o-mini will appear in OpenAI cost reports; budget ~$0.0002 per submitted attempt (10 small calls). At 1000 attempts/day, ~$6/month.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Bank generation produces incorrect "correct answers" (distractors marked correct) | Medium | High (student learns wrong) | Review-refine pass is correctness-scoped + admin read-only bank viewer lets a human spot-check before topics go live. Start with `review_rounds=1` default; bump to 2 if audit flags issues. |
| FF grading inconsistent (LLM gives different score to same answer across attempts) | Medium | Medium | Accept it. FF is 1–3 out of 10 per attempt. Rubric in prompt anchors consistency. Log grading rationales so admin can audit patterns later. |
| Background grading thread dies silently (process crash, container restart mid-grade); attempt stuck in `status='grading'` | Low | Medium | **v1: no auto-recovery.** Student sees "grading in progress…" on landing page forever. Post-v1 mitigation (documented in §4.1): add `grading_started_at` timestamp + sweeper that flips stuck attempts to `grading_failed` after 5 min. If field reports surface stuck attempts, prioritize then. |
| Parallel grading (N attempts across topics all grading at once) overloads LLM rate limit | Low | Medium | Each attempt is ~10 small calls; OpenAI gpt-4o-mini rate limits are generous. `LLMService.call` already has built-in retry for rate-limit errors. If this becomes real, add a simple process-wide semaphore (`threading.BoundedSemaphore(20)`) around the per-call executor submits. |
| Bank < 30 questions after validate+top-up (LLM can't generate enough valid questions) | Low | Medium | `_top_up` runs until threshold or 3 attempts. If still < 30, log an admin alert and mark the topic as "bank unavailable" — the tile greys out gracefully (FR-5). |
| **Practice-capture component layer is substantial new code** (11 controlled components + shared primitives) | **High (certain)** | **Medium** | Scoped as dedicated Step 9a. Each capture component is ~100–200 lines, controlled props, no side effects. Storybook-style unit tests per component. Shared primitives (`OptionButton`, `PairColumn`, etc.) extracted from existing check-in components where pure, or duplicated where the check-in version is too entangled with correctness logic. |
| **Bank regeneration orphans historical attempts** (old `question_ids` point to deleted rows) | Would be High without mitigation | High | **Eliminated by design.** `practice_attempts.questions_snapshot_json` stores the full payload at creation; rendering/grading/review read only from the snapshot. `PracticeQuestionRepository.delete_by_guideline()` is safe to call at any time. Unit test `test_review_renders_correctly_after_bank_regenerated`. |
| **Debounced auto-save + Submit loses the student's last answer** | Would be High without mitigation | High | **Eliminated by design.** `POST /submit` carries `final_answers_json`; server persists answers + flips status in a single transaction; client cancels in-flight PATCH before issuing Submit. Late PATCH arriving after commit returns 409 and is discarded. Integration test `test_submit_with_in_flight_answer_persists_final`. |
| **Concurrent tabs both trigger `start_or_resume`**, second tab hits IntegrityError | Would be Medium without mitigation | Medium | **Eliminated by design.** Service catches IntegrityError, re-reads the winning `in_progress` row, returns it. Unit test `test_concurrent_start_is_idempotent`. |
| **Migration drops columns while live code still writes to them** | Would be HIGH without mitigation | HIGH (production crash) | **Eliminated by design.** §3 migration is split: Step 1 is additive-only (new tables + seeds), destructive cleanup (DELETE rows + DROP columns) is bundled into Step 12 alongside the code removal. Verified by test: Step 1's `_apply_practice_tables` runs clean on a DB that still has `sessions.exam_score/exam_total` populated. |
| **Step 12 code removal misses a reference to old exam/practice code** | Medium | Low (CI fails; easy fix) | Step 12 includes a mandatory grep gate in §2. CI runs the grep command as a test; deploy blocked if it returns non-zero. |
| **PracticeBanner mounted only in AppShell wouldn't cover chat-session routes** (FR-34 violation) | Would be Medium without mitigation | Medium | **Eliminated by design.** Step 9c introduces `<AuthenticatedLayout>` above both AppShell and chat-session routes; banner renders as a fixed-position element visible regardless of which route-group is active. |
| Discarded exam + old-practice history is a regression for long-tenured students | High (certain) | Low (confirmed by FR-1, FR-2) | PRD explicitly accepts this. No mitigation needed. A DB snapshot taken immediately before Step 12 deploy is the rollback path. |
| Banner polling at 30s is too slow (student sits staring at ModeSelection) | Medium | Low | 30s is a PRD-informed default. If UX testing shows impatience, drop to 10s or migrate to SSE post-ship. |
| Bank generation runtime per chapter is underestimated for multi-topic chapters | Medium | Low | Revised estimate: ~2 minutes per guideline at gpt-5.2 medium + 1 review round. A chapter with 20 topics takes ~40 min (sequential within chapter; lock prevents parallelism). Backfill script parallelizes across books. If slower than acceptable, drop review rounds to 0 and rely on the admin bank viewer for spot-checks. |

---

## 12. Open Questions

**Resolved in this revision:**

- **Q1 (RESOLVED):** FR-41 half-point granularity. **Decision:** round **at grading write time** — `total_score` is stored already rounded to the nearest 0.5 (`round(raw * 2) / 2`). All display paths read the stored value directly. Rationale: mixed-rounding (raw stored, rounded at display) causes sums/totals to disagree across views and creates a UX bug when students compare numbers. Per-question `score` remains raw fractional in `grading_json` for admin audit; only `total_score` is rounded.
- **Q3 (RESOLVED):** FR-43 Pixi visuals on evaluation cards. **Decision:** out of scope for v1 launch, but the data model is pre-wired. `grading_json[q_idx].visual_explanation_code` is a nullable string slot (see §3). v1 leaves it null. A later PR wires the existing `VisualExplanation` frontend component into `PracticeReviewPage.tsx` — no migration needed.
- **Q4 (RESOLVED):** FR-34 post-submit destination. **Decision:** route to **ModeSelectPage** (same topic's activity picker). PRD wording "topic list" was ambiguous; `ModeSelectPage` is a better fit because (a) the student is most likely to Reteach or Practice-again on the same topic, (b) the Reteach button on `PracticeResultsPage` also targets `ModeSelectPage` with `?autostart=teach_me`, keeping the mental model consistent. Update `docs/functional/practice-mode.md` in Step 14 to lock this in.
- **Q5 (RESOLVED):** Drop `exam_score`, `exam_total` columns. **Decision:** yes, in the Step 12 migration (`_cleanup_exam_and_old_practice_data`) alongside the `DELETE FROM sessions WHERE mode IN ('exam', 'practice')` and the code removal. See §3 migration split.

**Still open:**

- **Q2:** For FR-19 "at least 4 different formats per set" — does `free_form` count as a format? **Proposed:** yes. 10-question sets will naturally have ≥4 formats when 1–3 are FF and the rest are drawn randomly from 11 structured formats. Confirm with PRD author before Step 7.
- **Q6 (new):** FR-9 says "1–3 free-form (FF) text questions" per topic. Purely procedural topics may legitimately produce zero FFs — the LLM returns 0 valid FFs after review/refine, and forcing an additional pass to generate at least one FF risks low-quality contrived questions. **Proposed:** relax to `0 ≤ FF count ≤ 3` in the generator's validate step; update PRD wording if confirmed. Confirm with PRD author before Step 3.
