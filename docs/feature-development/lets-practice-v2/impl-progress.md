# Let's Practice v2 — Implementation Progress & Handover

**Date:** 2026-04-17
**Branch:** `feat/lets-practice-v2` (off `main`)
**Status:** 6 of 16 steps complete. Backend ingestion + admin UI + grading service in place; next is the practice lifecycle service (Step 7).

---

## TL;DR

- PRD: `docs/feature-development/lets-practice-v2/prd.md`
- Impl plan: `docs/feature-development/lets-practice-v2/tech-impl-plan.md`
- This file: progress tracker + handover notes. Updated after each step completes.
- Work is on branch `feat/lets-practice-v2`. All changes so far are **committed to the working tree but not yet pushed / PR'd** — run `git status` to see what's in flight.

---

## Environment

- Backend venv: `llm-backend/venv` (NOT `.venv`)
- Import-level verification: `cd llm-backend && venv/bin/python -c "<import statement>"` (the `source venv/bin/activate` shell activation can be flaky; direct `venv/bin/python` is the reliable path)
- Backend dev server: `cd llm-backend && source venv/bin/activate && make run` → `http://localhost:8000`
- Frontend dev server: `cd llm-frontend && npm run dev` → `http://localhost:3000`
- DB migration: `cd llm-backend && venv/bin/python db.py --migrate`

---

## Open questions — RESOLVED

Both blocking questions from plan §12 are resolved. Downstream work should apply these decisions.

| Q | Decision | Applied where |
|---|----------|---------------|
| Q2: does `free_form` count toward FR-19's "≥4 distinct formats per set"? | **Yes** — FF counts as a format. | Step 7 `_select_set` variety check (not yet built) |
| Q6: can FF count be 0 for purely procedural topics? | **Yes** — relax FR-9 from "1–3" to "0–3". | Already applied in Step 3 (`MIN_FREE_FORM = 0`, prompt language, `_validate_bank`) |

---

## Progress tracker

| # | Step | Status | Key files | Notes |
|---|------|--------|-----------|-------|
| 1 | Additive DB schema + LLM seeds | ✅ Done | `shared/models/entities.py`, `db.py` | `PracticeQuestion` + `PracticeAttempt` models added. `_apply_practice_tables()` creates partial unique index on `(user_id, guideline_id) WHERE status='in_progress'`. Seeded `practice_bank_generator` (claude_code/claude-opus-4-6 — admin/offline pipelines use claude_code per project rule, matches `check_in_enrichment`) and `practice_grader` (openai/gpt-4o-mini — runtime path uses openai) via `_ensure_llm_config`. **Exam columns untouched** — destructive cleanup is Step 12. |
| 2 | Practice repositories | ✅ Done | `shared/repositories/practice_question_repository.py`, `shared/repositories/practice_attempt_repository.py`, `shared/repositories/__init__.py` | Both classes exported. Repos commit per-op; atomic SELECT FOR UPDATE + flip lives in Step 7 service. `list_recent_unread` returns both `graded` and `grading_failed` attempts (drives banner). `answers_json` uses string keys for JSON portability. |
| 3 | Bank generator service + prompts | ✅ Done | `book_ingestion_v2/services/practice_bank_generator_service.py`, `book_ingestion_v2/prompts/practice_bank_generation.txt`, `book_ingestion_v2/prompts/practice_bank_review_refine.txt`, `book_ingestion_v2/constants.py` | `V2JobType.PRACTICE_BANK_GENERATION` enum added. Service mirrors `check_in_enrichment_service` pattern. Reuses `MatchPairOutput`, `BucketItemOutput`, and all format-specific min/max constants from check-in service. `_generate_and_refine_bank` runs initial generation → `review_rounds` refine passes → validate → up to 2 top-up attempts to reach `TARGET_BANK_SIZE=30`. Caps at `MAX_BANK_SIZE=40`. Validate drops: unknown format, empty text fields, FF overflow past 3, dupes by question_text. If final valid < 30 → skip insert + mark failed. |
| 4 | Ingestion API endpoints | ✅ Done | `book_ingestion_v2/api/sync_routes.py`, `book_ingestion_v2/models/schemas.py` | 4 endpoints registered on the existing `/admin/v2/books/{book_id}` router — same scoping rules + lock pattern as check-in enrichment. Background task `_run_practice_bank_generation` fetches `practice_bank_generator` LLM config (fallback: `explanation_generator`), instantiates `PracticeBankGeneratorService`, calls `enrich_guideline` or `enrich_chapter`, then `release_lock`. New response schemas: `TopicPracticeBankStatus`, `ChapterPracticeBankStatusResponse`, `PracticeBankQuestionItem`, `PracticeBankDetailResponse`. |
| 5 | Admin UI bank viewer | ✅ Done | `llm-frontend/src/features/admin/pages/PracticeBankAdmin.tsx` (new), `BookV2Detail.tsx` (extend), `adminApiV2.ts` (+4 funcs), `App.tsx` (+1 route) | BookV2Detail mirrors the Check-ins integration (state, polling, handler, step badge, manage-link + rounds select + running chip + result banner). PracticeBankAdmin is read-only: per-topic list with question counts + Generate/Regenerate/View; View modal shows all questions with expand-on-click (Question / Correct / Why / Rubric / Raw JSON). Browser-tested on test_mathematics_2_2026 / Introducing Thousands — all 30 questions render cleanly. Known polish-later: for `true_false` / `match_pairs` the collapsed row shows generic `question_text` instead of the format-specific content. |
| 6 | Grading service | ✅ Done | `tutor/services/practice_grading_service.py` (new), `tutor/prompts/practice_grading.py` (new) | `grade_attempt(attempt_id)` idempotent entry-point: bails if status != 'grading'. Three phases: (1) deterministic pass classifies structured vs free-form, enqueues LLM tasks for wrong/blank structured + all free-form; (2) `ThreadPoolExecutor(max_workers=10)` runs per-task LLM calls in parallel; (3) assemble `grading_json` + half-point-rounded `total_score` via `save_grading`. Unhandled errors → `mark_grading_failed`. Structured correctness handled for all 11 non-FF formats (pick_one/fill_blank/tap_to_eliminate/predict_then_reveal use `correct_index`; true_false uses `correct_answer_bool`; match_pairs compares dict; sort_buckets/swipe_classify compare list[int]; sequence compares list[str]; spot_the_error + odd_one_out use their own index fields). LLMService construction + `initial_retry_delay=10` passed-in at worker-spawn time (Step 7). Pydantic strict schemas: `FreeFormGradingOutput` (score float 0-1 + rationale) and `PickRationaleOutput` (rationale). 18/18 deterministic cases smoke-tested. `visual_explanation_code` slot pre-wired in `grading_json[q_idx]` as null for FR-43. |
| 7 | Practice lifecycle service | ⏳ Next | `tutor/services/practice_service.py` (new), `tutor/models/practice.py` (new Pydantic DTOs) | `start_or_resume`: catch IntegrityError from partial unique index + re-read winner (idempotent). `_select_set`: 3E/5M/2H mix, **all FFs absorbed** (Q2: FF counts toward ≥4-format variety check), random pick with `_enforce_no_consecutive_same_format`. `_snapshot_question`: copy `question_json` + add `_id/_format/_difficulty/_concept_tag/_presentation_seed`. `submit`: `SELECT FOR UPDATE` → merge `final_answers_json` → flip status → commit → spawn worker. `save_answer`: raises `ConflictError` (→ HTTP 409) if status != `in_progress`. `redact_for_student`: strip `correct_index`/`correct_answer_bool`/`pairs` correctness/`expected_answer`/`grading_rubric`/`explanation_why` from snapshot before serving during the set (FR-26). |
| 8 | Practice runtime REST API | Pending | `tutor/api/practice.py` (new), `main.py` (register router) | Endpoints per plan §4.1 table. `/practice/attempts/recent` polls every 30s from frontend banner. `POST /submit` body carries `final_answers_json` (kills the debounce race). Every endpoint does `attempt.user_id == current_user.id` ownership check mirroring `_check_session_ownership`. Register at `/practice` prefix. |
| 9a | Practice-capture component layer | Pending | `llm-frontend/src/components/practice/capture/*.tsx` (11 new), `llm-frontend/src/components/shared/{OptionButton,PairColumn,BucketZone,SequenceList}.tsx` (new shared primitives) | **Key refactor — not a trivial reuse.** Existing `*Activity.tsx` are correctness-driven, uncontrolled, side-effectful (auto-submit on correct, TTS, non-deterministic shuffle, multi-step internal state). New layer is pure controlled: `{ value, onChange, seed }` props. Deterministic shuffle via seed. No TTS. No correctness styling. Do NOT fork existing check-in components with a `mode` prop — build parallel components per plan §5.4.1 counter-option rejection. |
| 9b | Frontend runtime pages | Pending | `llm-frontend/src/pages/Practice{Landing,Runner,Results,Review,History}Page.tsx` (5 new), `llm-frontend/src/components/practice/{QuestionRenderer,FreeFormQuestion,PracticeBanner}.tsx` (3 new), `llm-frontend/src/api.ts` (new funcs) | Runner: question-by-question + review screen + atomic submit (AbortController cancels in-flight debounced PATCH before calling submit). Results: fractional score (half-point rounded), Reteach / Practice-again / Review-my-picks. Banner: 30s poll of `/practice/attempts/recent`, pauses when `document.visibilityState != 'visible'`. Success banner → PracticeResultsPage. Failure banner → `POST /retry-grading`. |
| 9c | AuthenticatedLayout + banner placement | Pending | `llm-frontend/src/App.tsx`, `llm-frontend/src/components/AuthenticatedLayout.tsx` (new) | AppShell currently wraps only non-chat routes. Chat-session routes (`teach/:sessionId`, `clarify/:sessionId`) are outside. New wrapper sits above both route groups (below ProtectedRoute/OnboardingGuard) so `PracticeBanner` fires mid-Teach-Me after a practice submit. Fixed-position top element, z-indexed above nav bars. |
| 10 | ModeSelection refactor | Pending | `llm-frontend/src/components/ModeSelection.tsx`, `llm-frontend/src/pages/ModeSelectPage.tsx` | Delete Exam tile + `completedExams` / `incompleteExam` / `incompletePractice` state. Let's Practice tile has NO badges. `practiceAvailable` from new `getPracticeAvailability(guideline_id)` API in the page-load `Promise.all`; disable tile when no bank. Handle `?autostart=teach_me` query param (from PracticeResultsPage's Reteach). On autostart, invoke existing Teach Me entry handler then clear query via `navigate(..., {replace: true})`. |
| 11 | Scorecard additive | Pending | `tutor/services/report_card_service.py`, `shared/models/schemas.py`, `llm-frontend/src/pages/ReportCardPage.tsx`, `llm-frontend/src/api.ts` types | **Structural change, not a rename.** Current code reads exam stats from `state_json` via session iteration. New `_merge_practice_attempts_into_grouped(grouped, user_id)` issues SQL aggregate over `practice_attempts` (latest score via `array_agg ORDER BY graded_at DESC`, count, `MAX(graded_at)`). Response schema **additively** gets `latest_practice_score` (Optional[float]), `latest_practice_total` (Optional[int]), `practice_attempt_count` (Optional[int]). Legacy integer `latest_exam_score`/`latest_exam_total` kept until Step 13. Frontend: rename label "Exam scores" → "Practice scores", fractional render (e.g. "7.5/10"), pluralize attempts. |
| 12 | Destructive cleanup (backend + DB) | Pending | Many — see plan §2 "Destructive" list | **SINGLE atomic deploy.** Delete `exam_service.py`, `exam_prompts.py`, `practice_prompts.py`, `tests/unit/test_exam_lifecycle.py`. Remove `session.mode == "exam"` and `"practice"` branches across orchestrator, session_service, master_tutor, session_state, report_card_service. Remove `/end-exam`, `/exam-review`, `/end-practice` endpoints + DTOs. Run `_cleanup_exam_and_old_practice_data()` inside single `with engine.begin():` transaction: `DELETE FROM sessions WHERE mode IN ('exam', 'practice')` + `ALTER TABLE sessions DROP COLUMN IF EXISTS exam_score` + `exam_total`. **Grep-gate CI test** must return 0: ``grep -rE '(ExamService\|exam_prompts\|practice_prompts\|_process_practice_turn\|_process_exam_turn\|_build_practice_turn_prompt\|practice_questions_answered\|exam_questions\|ExamQuestion\|ExamFeedback\|end-practice\|end-exam\|exam-review)' llm-backend/ \| grep -v docs/ \| wc -l`` |
| 13 | Destructive cleanup (frontend) | Pending | `llm-frontend/src/pages/ExamReviewPage.tsx` (delete), `App.tsx`, `api.ts`, `ReportCardPage.tsx` | Delete ExamReviewPage. Delete `/exam/:sessionId`, `/exam-review/:sessionId`, old `/practice/:sessionId` routes. Delete `ExamReviewResponse`, `ExamReviewQuestion`, `getExamReview` from api.ts. Remove legacy `latest_exam_score`/`latest_exam_total` reads from ReportCardPage. Grep-gate: ``grep -rE '(exam-review\|end-exam\|/exam/\|end-practice\|ExamReviewPage\|getExamReview)' llm-frontend/src`` must return 0. |
| 14 | Docs | Pending | `docs/principles/practice-mode.md` (new), `docs/functional/practice-mode.md` (new), `docs/technical/practice-mode.md` (new), updates to `docs/principles/scorecard.md`, `docs/technical/architecture-overview.md`, `docs/technical/database.md`, `docs/technical/ai-agent-files.md`, `CLAUDE.md` doc index table | Delete `docs/feature-development/teach-me-practice-split/` (superseded). Run `/update-all-docs` skill at end. |

**Sequencing constraint:** Steps 1–11 are purely additive — any subset can ship independently while exam + old-chat-practice stay live. Step 12 is the ONLY destructive deploy; it bundles code removal + DB DDL in one transaction so runtime never sees half-state.

---

## Locked design decisions

Already in the code or prompts — don't re-debate these without an explicit reason.

### Schema / persistence
- **Self-contained attempts.** `practice_attempts.questions_snapshot_json` stores the full question payload at attempt creation. Rendering, grading, and review read **only from the snapshot** — never from `practice_questions`. This eliminates the bank-regen-orphans-history risk by design.
- **Per-question `_presentation_seed`.** Stored in snapshot on create. Frontend shuffle components consume this seed → stable option order on resume.
- **Dedicated `practice_attempts` table** (not `sessions.state_json`). Purpose-built schema, smaller rows, trivial history queries.
- **JSONB `question_json`** (not per-format columns). Matches `CheckInDecision` / `TopicExplanation` pattern.
- **Partial unique index** on `(user_id, guideline_id) WHERE status='in_progress'` → one resumable attempt per topic.

### LLM / ingestion
- **Ingestion position:** after explanation generation (not just topic decomposition). Bank prompt consumes explanation cards for concept grounding. PRD wording will be corrected in Step 14.
- **Bank generator LLM:** `practice_bank_generator` (claude_code/claude-opus-4-6, medium reasoning). One call per topic. Review-refine is correctness-scoped only (no tone rewrites). **Corrected from impl-plan's openai/gpt-5.2 seed** — admin/offline pipelines use claude_code per project rule (`CLAUDE.md` + memory `feedback_claude_code_provider.md`); openai/gpt-5.2 was inconsistent with every sibling ingestion component (check_in_enrichment, explanation_generator, book_ingestion_v2 all use claude_code). Runtime grader (`practice_grader`) stays on openai/gpt-4o-mini.
- **Grader LLM:** `practice_grader` (openai/gpt-4o-mini, reasoning=none). One call per wrong answer for per-pick rationale (not batched — batch would leak cross-question context). Run in parallel via `ThreadPoolExecutor(max_workers=10)` → ~1s wall-clock.
- **Fail-open on review-refine errors:** keep prior bank output, continue validate.
- **FF count 0–3** at validate time. Purely procedural topics can legitimately have 0 FFs.
- **Bank targets:** `TARGET_BANK_SIZE=30`, `MAX_BANK_SIZE=40`, `MAX_GENERATION_ATTEMPTS=3`. If final valid < 30 → fail the guideline (don't insert a partial bank).

### Runtime (Step 7+)
- **Atomic submit.** `POST /submit` body carries `final_answers_json`. Server: `SELECT FOR UPDATE` → merge → flip status → commit → spawn worker. Client: AbortController cancels in-flight debounced PATCH before calling submit. Late PATCHes → 409 (not silent no-op).
- **Concurrent-tab start race** handled via IntegrityError catch + re-read of the winning `in_progress` row.
- **Silent thread death not mitigated in v1.** Post-v1: add `grading_started_at` + 5-min sweeper.
- **Half-point rounding at write-time** (`round(raw * 2) / 2` stored into `total_score`). All display paths read the stored value. Per-question `score` in `grading_json` stays raw fractional.
- **Post-submit destination = `ModeSelectPage`** (not "topic list"). Reteach from results also goes to ModeSelectPage with `?autostart=teach_me`.
- **Practice outside the chat orchestrator.** REST CRUD + threaded worker. Do NOT shoehorn into `session_service` / `orchestrator.py`.

### Frontend
- **New capture component layer** (Step 9a). Existing `*Activity.tsx` remain untouched and continue serving check-ins. Parallel layer, not a `mode` prop fork.
- **Banner lives above AppShell AND chat-session routes** via new `<AuthenticatedLayout>` wrapper. AppShell-only mount would miss mid-Teach-Me banner firing.
- **Poll, not push.** 30s `/recent` poll. Pause on `document.visibilityState != 'visible'`. No WebSocket / SSE for banner in v1.
- **`visual_explanation_code` slot pre-wired** in `grading_json[q_idx]` as nullable. FR-43 Pixi on eval cards deferred but no migration needed when enabled later.

---

## Next step briefing — Step 7

**Goal:** Practice lifecycle service — the piece that turns a bank into an attempt: set selection, snapshot, submit, save-answer, redact. This is the central backend service Step 8's REST API will call into.

**Files to touch:**
- `llm-backend/tutor/services/practice_service.py` (new)
- `llm-backend/tutor/models/practice.py` (new — Pydantic DTOs for the REST API)

**What to read first:**
- `shared/models/entities.py::PracticeAttempt` — the data shape this service writes to
- `shared/repositories/practice_attempt_repository.py` — primitive ops (create, save_answer, mark_submitted, save_grading, etc.). The atomic SELECT FOR UPDATE + flip logic for submit lives in the service, NOT the repo.
- `shared/repositories/practice_question_repository.py::list_by_guideline` — source of bank questions for set selection.

**Methods to build:**

| Method | Behavior |
|--------|----------|
| `start_or_resume(user_id, guideline_id)` | If an `in_progress` attempt exists for (user, topic), return it (redacted). Otherwise select a new 10-question set from the bank, snapshot it, attempt to `create()`. Catch `IntegrityError` from the partial-unique index (concurrent-tab race) and re-read the winning row. |
| `_select_set(questions)` | 3 easy / 5 medium / 2 hard mix. **All FFs absorbed** (Q2: FF counts toward the ≥4-format-variety check). Random pick. Call `_enforce_no_consecutive_same_format` to shuffle within difficulty. |
| `_snapshot_question(q)` | Copy `question_json`, inject `_id`, `_format`, `_difficulty`, `_concept_tag`, `_presentation_seed` (random int for deterministic shuffle on the frontend). |
| `save_answer(attempt_id, q_idx, answer, user_id)` | Ownership check + status check (raises `ConflictError` → HTTP 409 if status != `in_progress`). Delegates to repo. |
| `submit(attempt_id, final_answers, user_id)` | `SELECT FOR UPDATE` + `attempt.status == 'in_progress'` guard. Merge `final_answers_json`, flip status to `grading`, commit — then spawn the grading worker thread (imports `PracticeGradingService` from Step 6). Returns the flipped attempt. |
| `redact_for_student(attempt)` | Strip `correct_index`, `correct_answer_bool`, per-pair correctness, `expected_answer`, `grading_rubric`, `explanation_why` from `questions_snapshot_json` before serving during the set (FR-26). Results view reads unredacted. |

**Locked design decisions** (already in the impl plan + locked-decisions section of this doc):
- Atomic submit via `SELECT FOR UPDATE` + flip + commit + spawn worker.
- Concurrent-tab start race handled via IntegrityError catch + re-read.
- Silent thread death not mitigated in v1.
- Half-point rounding already applied by Step 6 — this service just passes raw answers through.

**Worker spawn pattern for grading:**
```python
def _spawn_grading_worker(attempt_id: str):
    import threading
    from database import get_db_manager
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from tutor.services.practice_grading_service import PracticeGradingService
    from config import get_settings

    def _run():
        db = get_db_manager().get_session()
        try:
            settings = get_settings()
            config = LLMConfigService(db).get_config("practice_grader")
            llm = LLMService(
                api_key=settings.openai_api_key,
                provider=config["provider"],
                model_id=config["model_id"],
                gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
                anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
                initial_retry_delay=10,  # 10/20/40s backoff per plan §6
            )
            PracticeGradingService(db, llm).grade_attempt(attempt_id)
        finally:
            db.close()
    threading.Thread(target=_run, daemon=True).start()
```

**Success criteria:**
- `start_or_resume` returns an `Attempt` DTO with a 10-question redacted snapshot on the first call; the same attempt on the second call for the same user+topic.
- Two concurrent `start_or_resume` calls race cleanly — both return the same in-progress attempt_id (one winner, one re-reader).
- `submit` flips status and — after a short wait — `grading_json` is populated and `total_score` is a half-point number.
- Import-check clean; no broken references.

---

## Superseded briefing — Step 5

**Goal:** Admin UI for practice banks — surface status per topic, trigger generation, view the resulting questions.

**Files to touch:**
- `llm-frontend/src/features/admin/api/adminApiV2.ts` (extend — add 4 new API client functions)
- `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` (extend — add "Practice Banks" section mirroring Check-Ins section)
- `llm-frontend/src/features/admin/pages/PracticeBankAdmin.tsx` (new — per-topic viewer)
- Router registration for the new viewer route (check how `CheckInAdmin` / `ExplanationAdmin` pages are wired — likely in `App.tsx` or a feature router).

**What to read first:**
- `llm-frontend/src/features/admin/api/adminApiV2.ts` — existing `generateCheckIns`, `getCheckInJobsLatest`, `getCheckInStatus` functions. Copy the shape.
- `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` — find the "Check-Ins" section (button + per-topic status table). Mirror under a new "Practice Banks" heading.
- Whatever admin page already exists for viewing check-in content per topic — the practice bank viewer follows the same layout (topic picker → list of cards/questions). Read-only. No regen-per-question, no analytics.

**API functions to add in `adminApiV2.ts`:**

| Function | Backend endpoint |
|----------|------------------|
| `generatePracticeBanks(bookId, { chapterId?, guidelineId?, force?, reviewRounds? })` | `POST /admin/v2/books/{id}/generate-practice-banks` |
| `getPracticeBankStatus(bookId, chapterId)` | `GET /admin/v2/books/{id}/practice-bank-status` |
| `getPracticeBankJobsLatest(bookId, { chapterId?, guidelineId? })` | `GET /admin/v2/books/{id}/practice-bank-jobs/latest` |
| `getPracticeBank(bookId, guidelineId)` | `GET /admin/v2/books/{id}/practice-banks/{guideline_id}` |

**UI behaviors:**
- Per-topic row in BookV2Detail "Practice Banks" section: topic title, question count (or "–" if 0), "Generate" / "Regenerate" button, link to viewer.
- `Generate` button posts with `force=false`; `Regenerate` posts with `force=true`. Both accept a `reviewRounds` number input (default 1).
- Running job state surfaces via `getPracticeBankJobsLatest` polled every 2s while a job is `pending` / `running`.
- PracticeBankAdmin viewer page: read-only table of all questions in the bank. Columns: format, difficulty, concept_tag, question_text (truncated), correct-answer summary, explanation_why. Expand-on-click row for full `question_json` pretty-print.

**Success criteria:**
- Admin can navigate to a V2 book's detail page, see a "Practice Banks" section with a row per approved topic.
- Clicking "Generate" on a topic fires the POST and the row flips to a "running" indicator, then to a question count.
- Clicking the topic link opens PracticeBankAdmin and renders all 30-40 questions.
- `npm run typecheck` (or equivalent) is clean; no new ESLint errors.

---

## Patterns cheat-sheet

When picking up a step, these patterns are already established:

- **Service construction:** `LLMConfigService(db).get_config("<key>")` → `LLMService(api_key=..., provider=config["provider"], model_id=config["model_id"], gemini_api_key=..., anthropic_api_key=...)`. See `sync_routes.py::_run_check_in_enrichment` lines ~1259–1277.
- **Background task pattern:** use `run_in_background_v2` from `book_ingestion_v2/api/processing_routes.py`. Spawns a `threading.Thread` with fresh DB session. Matches the existing check-in enrichment launcher.
- **Structured LLM output:** `LLMService.make_schema_strict(PydanticModel.model_json_schema())` → pass as `json_schema=` to `self.llm.call(...)`. Response: `response["output_text"]` → `self.llm.parse_json_response(...)` → `PydanticModel.model_validate(...)`.
- **DB session refresh after long LLM calls:** `_refresh_db_session()` pattern — close old session, `get_db_manager().get_session()`, re-wire repos on `self`. Prevents stale connections.
- **Repository commit policy:** simple write ops commit themselves; atomic multi-step ops (like `submit`) are handled in the service with `self.db.begin_nested()` / `with_for_update()` and explicit `self.db.commit()`.
- **JSONB mutation:** use `from sqlalchemy.orm.attributes import flag_modified; flag_modified(row, "answers_json")` after in-place dict edits, or assign a new dict wholesale.
- **Partial unique indexes:** create via raw `CREATE UNIQUE INDEX IF NOT EXISTS ... WHERE ...` in a `_apply_*_tables` function in `db.py`. Do NOT try to declare via SQLAlchemy `postgresql_where` — the codebase's pattern is raw SQL for portability.
- **V2JobType extensions:** add the enum value in `book_ingestion_v2/constants.py`, then use `V2JobType.X.value` when calling `ChapterJobService.acquire_lock` / `get_latest_job`.

---

## Handover instructions for a new session

Copy-paste this into a new chat:

> I'm continuing the Let's Practice v2 implementation on branch `feat/lets-practice-v2`. Progress + context are in `docs/feature-development/lets-practice-v2/impl-progress.md`. The PRD is in `prd.md` and the tech impl plan is in `tech-impl-plan.md` in the same directory. **Read the progress doc first**, then pick up at the next `Pending` step in the tracker table. Each step is independently testable; don't jump ahead. When a step is complete, update the progress doc's tracker table and the Locked decisions section if anything new got decided.

---

## Git checkpoint

As of 2026-04-17 end-of-session:
- Branch: `feat/lets-practice-v2` (local; not pushed)
- Last commit on the branch: `fc4cdbd` (feat: let's practice v2 — additive backend foundation (steps 1-3))
- Uncommitted additive changes:
  - `book_ingestion_v2/api/sync_routes.py` — 4 endpoints + `_run_practice_bank_generation` background task.
  - `book_ingestion_v2/models/schemas.py` — 4 new Pydantic response schemas.
  - `db.py` — `practice_bank_generator` seed corrected to `claude_code/claude-opus-4-6` (was `openai/gpt-5.2` in Step 1's draft).
- DB migration applied: both tables + partial unique index + both LLM config rows verified via SELECT.
- End-to-end tested: POST returns 202 → job transitions pending→running→completed (4m 19s on claude_code/claude-opus-4-6 for one topic with 1 review round) → GET `/practice-banks/{gid}` returns 30 questions spanning all 12 formats (FF=2, TF=1, SB=2, OOO=2, TAP=3, SEQ=2, PICK=5, MP=3, FB=4, SPOT=2, PR=3, SC=1) and a sensible difficulty mix. Status endpoint returns the expected per-topic summary for the chapter (only 1 of 8 topics has explanations, so only that one has a bank).
- Import-verified after every edit; 28 routes registered on the running uvicorn (`--reload` picks up changes automatically).

Recommended next commit boundary: now. The branch is in a clean additive state with verified end-to-end behavior. Then move to Step 5 (admin UI).
