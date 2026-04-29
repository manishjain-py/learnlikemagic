# Let's Practice — Technical

Batch-drill practice mode: offline question bank, 10-question sets, atomic submit, background grading, per-question review with LLM-generated rationales. Runs outside the chat orchestrator — REST only, no WebSocket.

Replaces the old Exam mode and the old tutor-in-the-loop Practice mode. All exam code paths, `exam_*` columns, and old chat-mode practice code were removed in Step 12 + 13 of the lets-practice-v2 feature branch.

---

## Architecture

```
Ingestion (offline, per topic)
    book_ingestion_v2 → practice_bank_generator_service
    → 30–40 questions per topic in practice_questions (JSONB)

Student runtime (per attempt)
    ModeSelect → PracticeLandingPage
        → POST /practice/start  (creates or resumes practice_attempts row)
        → PracticeRunnerPage (PATCH /answer debounced; questions snapshot)
        → POST /practice/submit (atomic SELECT FOR UPDATE → flip → worker thread)
        → PracticeGradingService (deterministic + ThreadPool LLM grader)
        → PracticeResultsPage polls /attempts/{id} until graded

Banner
    AuthenticatedLayout mounts PracticeBanner
    → polls /practice/attempts/recent every 30s (paused when tab hidden)
    → surfaces graded / grading_failed attempts across all authenticated routes
```

---

## Schema

### `practice_questions`

One row per question. Populated by the ingestion bank generator, read-only at runtime.

**Model:** `PracticeQuestion` (`shared/models/entities.py`)

| Column | Type | Description |
|---|---|---|
| `id` | VARCHAR | PK (UUID) |
| `guideline_id` | VARCHAR | FK → teaching_guidelines (CASCADE) |
| `format` | VARCHAR | One of 12: `pick_one`, `true_false`, `fill_blank`, `match_pairs`, `sort_buckets`, `sequence`, `spot_the_error`, `odd_one_out`, `predict_then_reveal`, `swipe_classify`, `tap_to_eliminate`, `free_form` |
| `difficulty` | VARCHAR | `easy` / `medium` / `hard` |
| `concept_tag` | VARCHAR | Concept label from the topic's guideline |
| `question_json` | JSONB | Full question payload — format-specific fields (options, correct_index, pairs, etc.) + universal `question_text` and `explanation_why` |
| `generator_model` | VARCHAR | Model id used to produce this question (for audit) |
| `created_at` | DATETIME | Timestamp |

**Indexes:** `idx_practice_questions_guideline` (guideline_id).

### `practice_attempts`

One row per attempt (in-progress, grading, graded, or grading_failed). Self-contained — snapshots the 10 selected questions at creation so bank regeneration never orphans history.

**Model:** `PracticeAttempt` (`shared/models/entities.py`)

| Column | Type | Description |
|---|---|---|
| `id` | VARCHAR | PK (UUID) |
| `user_id` | VARCHAR | FK → users (CASCADE) |
| `guideline_id` | VARCHAR | FK → teaching_guidelines (CASCADE) |
| `status` | VARCHAR | `in_progress` / `grading` / `graded` / `grading_failed` |
| `question_ids` | JSONB | The 10 selected `practice_questions.id` values (audit trail; rendering reads the snapshot, not these) |
| `questions_snapshot_json` | JSONB | 10 question payloads + per-q `_id`, `_format`, `_difficulty`, `_concept_tag`, `_presentation_seed` |
| `answers_json` | JSONB | `{q_idx (string): answer}` map, written by PATCH /answer and final submit |
| `grading_json` | JSONB | Per-question grading rows: `{q_idx, format, difficulty, concept_tag, correct, score, student_answer, correct_answer_summary, rationale, visual_explanation_code}`. Null until graded. |
| `total_score` | FLOAT | Aggregate score, half-point-rounded at write-time. Null until graded. |
| `total_possible` | INT | Always 10 for v1 |
| `grading_error` | TEXT | Exception text if grading failed |
| `grading_attempts` | INT | Counter incremented on each terminal grading transition (`graded` or `grading_failed`); enables Retry audit |
| `results_viewed_at` | DATETIME | Set by POST /mark-viewed to clear the banner |
| `created_at`, `submitted_at`, `graded_at` | DATETIME | Timestamps |

**Indexes:**
- `idx_practice_attempts_user_guideline` (user_id, guideline_id)
- `idx_practice_attempts_user_status` (user_id, status) — drives `/attempts/recent`
- **Partial unique:** `uq_practice_attempts_one_inprogress_per_topic` on (user_id, guideline_id) WHERE status='in_progress' — enforces "at most one resumable attempt per topic"

---

## Ingestion: Question Bank Generation

**Service:** `PracticeBankGeneratorService` — `book_ingestion_v2/services/practice_bank_generator_service.py`

**Prompts:**
- `book_ingestion_v2/prompts/practice_bank_generation.txt`
- `book_ingestion_v2/prompts/practice_bank_review_refine.txt`

**Flow:**

```
enrich_guideline(guideline_id)
    → load topic + approved explanation cards (concept grounding)
    → _generate_and_refine_bank():
        initial generation → N review_rounds of refine → validate
        if valid count < TARGET_BANK_SIZE (30): run up to 2 top-up attempts
        cap at MAX_BANK_SIZE (40)
    → insert into practice_questions (transactional per guideline)
```

**Validation drops:**
- Unknown format
- Empty text fields
- Free-form count exceeds 3 (relaxed from "1–3" to "0–3" — procedural topics can have 0)
- Duplicate `question_text`
- Structured questions missing their format-specific correctness field

If final valid count < 30, the guideline is marked failed — no partial bank is inserted.

**LLM config:** `practice_bank_generator` (seeded to `claude_code/claude-opus-4-7`, medium reasoning). Admin/offline pipelines use `claude_code` per project rule — this matches sibling services (`check_in_enrichment`, `explanation_generator`, `book_ingestion_v2`). The chosen model id is stamped into each row's `generator_model` column for audit.

**Admin API** (registered on the existing `/admin/v2/books/{book_id}` router):

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/v2/books/{book_id}/generate-practice-banks` | Trigger per-chapter or per-guideline generation (body: `{chapter_id?, guideline_id?, force?, review_rounds?}`) |
| `GET` | `/admin/v2/books/{book_id}/practice-bank-status` | Per-topic question counts for a chapter |
| `GET` | `/admin/v2/books/{book_id}/practice-bank-jobs/latest` | Latest job status (for polling while running) |
| `GET` | `/admin/v2/books/{book_id}/practice-banks/{guideline_id}` | Full bank detail for viewer |

Jobs run via `run_in_background_v2` — threaded DB session, per-topic lock, matches the `check_in_enrichment` launcher pattern.

---

## Runtime: Practice Lifecycle

**Service:** `PracticeService` — `llm-backend/tutor/services/practice_service.py`

**DTOs:** `llm-backend/tutor/models/practice.py` — `Attempt`, `AttemptQuestion`, `AttemptResults`, `GradedQuestion`, `AttemptSummary`. Request bodies (`StartRequest`, `SaveAnswerRequest`, `SubmitRequest`) and the `AvailabilityResponse` live in `tutor/api/practice.py`.

**Custom exceptions** (map 1:1 to HTTP codes in the API layer):

| Exception | HTTP | Trigger |
|---|---|---|
| `PracticeNotFoundError` | 404 | Unknown attempt_id |
| `PracticePermissionError` | 403 | Attempt belongs to another user |
| `PracticeConflictError` | 409 | Status mismatch (e.g., PATCH /answer on a submitted attempt) |
| `PracticeBankEmptyError` | 409 | `start_or_resume` on a topic with no bank |

### Public methods

| Method | Behavior |
|---|---|
| `start_or_resume(user_id, guideline_id)` | If an `in_progress` attempt exists, return it redacted. Otherwise pick a 10-question set, snapshot, and `create()`. Catches `IntegrityError` from the partial unique index (concurrent-tab race) and re-reads the winning row. |
| `save_answer(attempt_id, q_idx, answer, user_id)` | Ownership + status check → `ConflictError` if status != `in_progress`. Delegates to repo. |
| `submit(attempt_id, final_answers, user_id)` | Atomic: `SELECT FOR UPDATE` → merge answers → flip status to `grading` → commit → spawn daemon-thread grading worker. Returns the flipped attempt. |
| `retry_grading(attempt_id, user_id)` | Only valid when status == `grading_failed`. Flips back to `grading` + respawns worker. |
| `mark_viewed(attempt_id, user_id)` | Sets `results_viewed_at`. Used by results page (auto on mount) and banner-tap to clear the notification. |
| `get_attempt(attempt_id, user_id)` | Returns redacted `Attempt` (during set) or `AttemptResults` (graded / grading_failed). |
| `list_recent_unread(user_id)` | Returns graded / grading_failed attempts with `results_viewed_at IS NULL`. Drives banner. |
| `list_attempts(user_id, guideline_id)` | Returns all attempts for a topic, newest first. Drives history. |

### Set selection (`_select_set`)

Exactly 3 easy / 5 medium / 2 hard. All free-form questions are absorbed first (they count toward the difficulty mix; they don't expand the set). If difficulty buckets underfill, `_select_set` backfills from leftover structured questions. Bank smaller than 10 raises `PracticeBankEmptyError`. After picking, `_enforce_no_consecutive_same_format` greedy-reorders to eliminate same-format adjacency. A logger warning fires when the picked set has fewer than 4 distinct formats (variety target is non-blocking — narrow banks still ship a set).

### Snapshot (`_snapshot_question`)

Copies `question_json` + injects `_id`, `_format`, `_difficulty`, `_concept_tag`, `_presentation_seed` (random 32-bit int). The frontend seeded-shuffle consumes `_presentation_seed` for stable option order on resume.

### Redaction (`_redact_questions`)

During the set, the server strips correctness from the snapshot before serving:
- Top-level keys removed: `correct_index`, `correct_answer_bool`, `expected_answer`, `grading_rubric`, `explanation_why`, `error_index`, `odd_index`, `reveal_text`
- `match_pairs`: drops `pairs`, exposes parallel `pair_lefts` / `pair_rights` arrays (frontend shuffles rights)
- `sort_buckets` / `swipe_classify`: each `bucket_items[i]` reduced to `{text}` (no `correct_bucket`)
- `sequence`: deterministically shuffled by `_presentation_seed` before serving so the served order doesn't leak the answer; the on-disk snapshot stays in correct order for grading

The unredacted snapshot is used for grading and review.

### Atomic submit

```python
# Inside PracticeService.submit()
row = db.query(PracticeAttempt).filter_by(id=attempt_id).with_for_update().first()
# ownership + status guards → 404 / 403 / 409
row.answers_json = {**row.answers_json, **final_answers}
row.status = 'grading'
row.submitted_at = datetime.utcnow()
db.commit()
self._spawn_grading_worker(attempt_id)
```

The worker is a daemon thread with a **fresh DB session** (not `self.db`) and a fresh `LLMService(initial_retry_delay=10)` — 10/20/40s backoff on transient errors. Silent thread death is NOT mitigated server-side in v1; the frontend results page caps polling at ~5 minutes and surfaces a Retry CTA when stuck. A post-v1 server-side sweeper is tracked as follow-up.

---

## Grading

**Service:** `PracticeGradingService` — `llm-backend/tutor/services/practice_grading_service.py`

**Prompts:** `llm-backend/tutor/prompts/practice_grading.py` — two Pydantic output schemas: `FreeFormGradingOutput` (score + rationale) and `PickRationaleOutput` (rationale for wrong picks).

**Entry point:** `grade_attempt(attempt_id)` — idempotent; bails if status != `grading`.

**Three phases:**

1. **Deterministic pass** classifies every structured question as correct/wrong/blank and enqueues LLM tasks only for wrong/blank structured (one rationale call each) + all free-form (one grading call each).
2. **LLM pass** — `ThreadPoolExecutor(max_workers=GRADING_PARALLELISM=10)` grades tasks in parallel. ~1s wall-clock for a typical 10-question set. Per-pick rationales are generated one LLM call per wrong answer (not batched — batching would leak cross-question context).
3. **Assemble** `grading_json` per q_idx + half-point-round `total_score` via `round(raw * 2) / 2`. Per-question `score` in `grading_json` stays raw fractional. A free-form answer is flagged `correct=true` only when its fractional score `>= FF_CORRECT_THRESHOLD (0.75)`.

**Structured correctness** (deterministic, no LLM):

| Format | Comparison |
|---|---|
| `pick_one`, `fill_blank`, `tap_to_eliminate`, `predict_then_reveal` | `answer == correct_index` |
| `true_false` | `answer == correct_answer_bool` |
| `match_pairs` | Deep dict equality |
| `sort_buckets`, `swipe_classify` | Per-item bucket equality |
| `sequence` | List equality |
| `spot_the_error` | `answer == error_index` |
| `odd_one_out` | `answer == odd_index` |

**Unhandled errors** → `mark_grading_failed(attempt_id, exception_text)`. Student sees the grading_failed banner with an inline Retry button.

**LLM config:** `practice_grader` (seeded to `openai/gpt-4o-mini`, reasoning none). Runtime path uses `openai` for latency; admin uses `claude_code` per the provider split. Both rationale prompts produce 2-3 short, kid-friendly sentences (≤60 words, ESL-aware) — see `tutor/prompts/practice_grading.py`.

**`visual_explanation_code` slot:** pre-wired in `grading_json[q_idx]` as `null`. Reserved for FR-43 (Pixi on eval cards), not populated in v1 — no migration needed when enabled later.

---

## Runtime API

**Router:** `tutor/api/practice.py`, prefix `/practice`. All endpoints require `get_current_user` — no anonymous access.

| Method | Path | Body / Query | Response |
|---|---|---|---|
| `POST` | `/start` | `{guideline_id}` | `Attempt` (redacted) |
| `GET` | `/availability/{guideline_id}` | — | `{available: bool, question_count: int}` |
| `GET` | `/attempts/recent` | — | `{attempts: AttemptSummary[]}` (graded+failed, `results_viewed_at IS NULL`) |
| `GET` | `/attempts/for-topic/{guideline_id}` | — | `AttemptSummary[]` |
| `GET` | `/attempts/{attempt_id}` | — | `Attempt` (in-progress) \| `AttemptResults` (graded) |
| `PATCH` | `/attempts/{attempt_id}/answer` | `{q_idx, answer}` | 204 |
| `POST` | `/attempts/{attempt_id}/submit` | `{final_answers}` | `Attempt` (status=`grading`) |
| `POST` | `/attempts/{attempt_id}/retry-grading` | — | 204 |
| `POST` | `/attempts/{attempt_id}/mark-viewed` | — | 204 |

Route declaration order matters: `recent` and `for-topic` are declared before `{attempt_id}` so they win the `/attempts/*` match.

A `_call()` helper wraps each handler to map `PracticeException` subclasses to FastAPI `HTTPException` with the right status + detail.

---

## Frontend

### Capture component layer

**Path:** `llm-frontend/src/components/practice/capture/*.tsx` (11 controlled components, one per structured format) + `llm-frontend/src/components/practice/FreeFormQuestion.tsx` (12th, free-form textarea). Shared `CaptureProps<T>` contract in `capture/types.ts`.

New parallel layer — not a fork of check-in's `*Activity.tsx`. Existing check-in components are correctness-driven, uncontrolled, side-effectful (auto-submit, TTS, non-deterministic shuffle). Practice capture is pure controlled:

```tsx
interface CaptureProps<T> {
  questionJson: Record<string, unknown>;  // redacted (no correctness)
  value: T | null;                        // answer from parent state
  onChange: (value: T) => void;
  seed: number;                           // for deterministic shuffle
  disabled?: boolean;                     // freeze during review
}
```

Per-format answer shapes match the backend grading comparators (see Grading above).

Deterministic shuffle via `mulberry32(seed)` + Fisher-Yates. Original indices are preserved as values, so shuffling presentation order doesn't break backend grading.

**Shared primitives:** `components/shared/{OptionButton, PairColumn, BucketZone, SequenceList, seededShuffle}.tsx`.

### Pages & routing

**Paths:** `llm-frontend/src/pages/Practice{Landing,Runner,Results}Page.tsx`.

| Route | Component |
|---|---|
| `/practice/:guidelineId` | `PracticeLandingPage` |
| `/practice/attempts/:attemptId/run` | `PracticeRunnerPage` |
| `/practice/attempts/:attemptId/results` | `PracticeResultsPage` |

All three live inside `AuthenticatedLayout` → `AppShell` so the practice banner fires during the drill too (see §Banner below). `/practice/*` is added to `AppShell.isChalkboardRoute` so the chalkboard theme scope covers the new routes.

**Landing:** fetches `listPracticeAttemptsForTopic(guidelineId)`. Shows Start + Resume + past-attempts list.

**Runner:** one question at a time + Prev/Next. Debounced PATCH on every answer change (600ms) with an `AbortController` that cancels any in-flight PATCH before submit. Review-my-picks screen before submit.

**Results:** fetches `/attempts/{id}` in a 2s poll until status becomes `graded` or `grading_failed`. After 150 polls (~5 min) the page assumes the worker died silently and surfaces a "Grading is taking longer than expected" state with the same Retry button as `grading_failed`. Renders `QuestionRenderer` in `disabled` mode for each question + rationale chip + correct-answer summary on wrong picks. Reteach CTA requires topic-path state (`subject && chapter && topic`); banner-sourced results hide Reteach. Practice-again calls `/practice/start` to spin up a fresh set on the same topic.

### Banner

**Component:** `llm-frontend/src/components/practice/PracticeBanner.tsx`, mounted in `AuthenticatedLayout`.

- Fetches `listRecentPracticeAttempts()` on mount, then polls every 30s.
- Paused when `document.visibilityState !== 'visible'`; resumes on return.
- Filters out the attempt whose results page the student is currently viewing (avoids 30s overlap).
- Green/mint banner for `graded` → tap → results. Amber banner for `grading_failed` → inline Retry button → `POST /retry-grading`.
- `mark-viewed` fires on banner tap to clear the notification.

### ModeSelect integration

`ModeSelectPage.tsx` calls `getPracticeAvailability(guidelineId)` on mount. The Practice tile in `ModeSelection.tsx` is always rendered (outside refresher scope); `disabled + grayscale + "No practice bank for this topic yet"` when `!available`. Keeps the affordance discoverable.

The `?autostart=teach_me` query param (used by the Reteach CTA on PracticeResultsPage) is handled by a ref-guarded one-shot useEffect — clears the query via `navigate(pathname, {replace:true})` before firing `handleModeSelect('teach_me')`.

### Teach Me → Practice handoff

After the Teach Me card phase ends, the completion screen surfaces a **"Let's Practice — put it to work!"** CTA. It navigates to `/practice/:guidelineId` with `{topicTitle, subject, chapter, topic}` state — no backend session-create round-trip. (Replaces the old handoff that created a `mode='practice'` chat session.)

---

## Scorecard Integration

`report_card_service.py` merges graded attempts into the per-topic report card:

- `_load_user_practice_attempts(user_id)` — fetches `status='graded'` attempts ordered `guideline_id ASC, graded_at DESC` so `attempts[0]` per group is the latest.
- `_merge_practice_attempts_into_grouped()` groups in Python (no SQL `array_agg` — keeps the code portable across SQLite test and Postgres prod without dialect-specific aggregates) and augments or creates topic rows.
- `_build_guideline_lookup` was extended to include `subject` and accept practice attempts as a second source of guideline_ids so practice-only topics (no teach_me session) still resolve hierarchy and render on the scorecard.

Per topic, the scorecard emits three new optional fields:

| Field | Source |
|---|---|
| `latest_practice_score` | `attempts[0].total_score` (latest graded) |
| `latest_practice_total` | `attempts[0].total_possible` |
| `practice_attempt_count` | `len(attempts)` for the topic |

The legacy `latest_exam_score` / `latest_exam_total` fields were dropped in Step 13.

---

## Key Files

**Backend:**

| File | Purpose |
|---|---|
| `shared/models/entities.py` | `PracticeQuestion`, `PracticeAttempt` ORM models |
| `shared/repositories/practice_question_repository.py` | Bank read/write primitives (`list_by_guideline`, `count_by_guideline`, `counts_by_guidelines`, `bulk_insert`, `delete_by_guideline`) |
| `shared/repositories/practice_attempt_repository.py` | Attempt CRUD primitives; atomic submit logic lives in the service |
| `tutor/services/practice_service.py` | Lifecycle — `start_or_resume`, `save_answer`, `submit`, `retry_grading`, `list_*`, redaction |
| `tutor/services/practice_grading_service.py` | Deterministic + ThreadPool LLM grading |
| `tutor/prompts/practice_grading.py` | Pydantic output schemas + prompt templates |
| `tutor/models/practice.py` | REST DTOs + custom exceptions |
| `tutor/api/practice.py` | Runtime HTTP surface (`/practice/*`) |
| `book_ingestion_v2/services/practice_bank_generator_service.py` | Ingestion bank generator |
| `book_ingestion_v2/prompts/practice_bank_generation.txt` | Bank generation prompt |
| `book_ingestion_v2/prompts/practice_bank_review_refine.txt` | Correctness review + refine prompt |
| `book_ingestion_v2/services/stage_launchers.py` | `launch_practice_bank_job` — DAG-aware threaded job spawn |
| `book_ingestion_v2/stages/practice_bank.py` | DAG stage definition (job type `v2_practice_bank_generation`) |
| `book_ingestion_v2/api/sync_routes.py` | Admin trigger + status endpoints (lines ~1900-2100) |
| `tutor/services/report_card_service.py` | Practice merge into scorecard |
| `db.py::_apply_practice_tables()` | Partial unique index + LLM config seeds |
| `tests/unit/test_practice_service.py`, `test_practice_grading_service.py`, `test_practice_attempt_repository.py` | Unit tests |

**Frontend:**

| File | Purpose |
|---|---|
| `llm-frontend/src/pages/PracticeLandingPage.tsx` | Start / Resume / past-attempts list with status chips |
| `llm-frontend/src/pages/PracticeRunnerPage.tsx` | Question-by-question + review + submit |
| `llm-frontend/src/pages/PracticeResultsPage.tsx` | Fractional score + per-question review + CTAs + 5-min stuck-grading guard |
| `llm-frontend/src/components/practice/QuestionRenderer.tsx` | Format → capture dispatch table |
| `llm-frontend/src/components/practice/capture/*.tsx` | 11 controlled capture components (one per structured format) |
| `llm-frontend/src/components/practice/capture/types.ts` | `CaptureProps<T>` shared contract |
| `llm-frontend/src/components/practice/FreeFormQuestion.tsx` | Free-form textarea |
| `llm-frontend/src/components/practice/PracticeBanner.tsx` | 30s poll + visibility pause + Retry |
| `llm-frontend/src/components/AuthenticatedLayout.tsx` | Mounts PracticeBanner above AppShell + chat-session groups |
| `llm-frontend/src/components/AppShell.tsx` | Adds `/practice` to `isChalkboardRoute` so the chalkboard theme covers practice routes |
| `llm-frontend/src/components/ModeSelection.tsx` | Renders the Practice tile (disabled when no bank) |
| `llm-frontend/src/components/shared/{OptionButton,PairColumn,BucketZone,SequenceList,seededShuffle}.{tsx,ts}` | Shared primitives reused by capture components |
| `llm-frontend/src/features/admin/pages/PracticeBankAdmin.tsx` | Per-topic read-only bank viewer (route: `/admin/books-v2/:bookId/practice-banks/:chapterId`) |
| `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | "Practice Banks" section (trigger + per-chapter status poll + review-rounds picker) |
| `llm-frontend/src/api.ts` | Practice API client functions + TS interfaces (`startPractice`, `getPracticeAvailability`, `getPracticeAttempt`, `savePracticeAnswer`, `submitPractice`, `retryPracticeGrading`, `markPracticeViewed`, `listRecentPracticeAttempts`, `listPracticeAttemptsForTopic`) |
| `llm-frontend/src/App.tsx` | Routes (`/practice/:guidelineId`, `/practice/attempts/:attemptId/{run,results}`) under AuthenticatedLayout |

---

## Configuration

**LLM config entries** (seeded via `db.py::_ensure_llm_config()` on migration):

| Component Key | Provider | Model | Purpose |
|---|---|---|---|
| `practice_bank_generator` | claude_code | claude-opus-4-7 | Offline bank generation + refine (admin path) |
| `practice_grader` | openai | gpt-4o-mini | Runtime free-form grading + per-pick rationales |

**Admin override:** both are configurable via `/admin/llm-config` UI.

**Feature flags:** none — ships enabled for all users.

---

## Locked Decisions (Reference)

See `docs/feature-development/lets-practice-v2/impl-progress.md` for the full list. Highlights:

- **Self-contained attempts** via `questions_snapshot_json` — bank regen never orphans history.
- **Atomic submit** via `SELECT FOR UPDATE` + flip + spawn worker.
- **Concurrent-tab start race** handled via IntegrityError catch on the partial unique index + re-read.
- **Half-point rounding at write-time** on `total_score`; per-question `score` in `grading_json` stays raw fractional.
- **Ingestion position** — after explanation generation (not just topic decomposition). Bank prompt consumes explanation cards for concept grounding.
- **Bank generator LLM** — `claude_code/claude-opus-4-7` (matches all sibling ingestion components, never `openai` for admin/offline pipelines).
- **Grader LLM** — `openai/gpt-4o-mini`, one call per wrong answer (not batched — batching would leak cross-question context), ThreadPool parallelism cuts wall-clock to ~1s.
- **`visual_explanation_code` pre-wired** in `grading_json[q_idx]` as nullable — reserved slot, no migration needed when FR-43 is enabled.
- **Practice runs outside the chat orchestrator** — REST CRUD + threaded worker. Not shoehorned into `session_service` / `orchestrator.py`.
