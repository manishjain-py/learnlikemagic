# Let's Practice v2 — Implementation Progress & Handover

**Date:** 2026-04-17
**Branch:** `feat/lets-practice-v2` (off `main`)
**Status:** 3 of 16 steps complete. Backend foundation in place; ready to build the ingestion API (Step 4) next.

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
| 1 | Additive DB schema + LLM seeds | ✅ Done | `shared/models/entities.py`, `db.py` | `PracticeQuestion` + `PracticeAttempt` models added. `_apply_practice_tables()` creates partial unique index on `(user_id, guideline_id) WHERE status='in_progress'`. Seeded `practice_bank_generator` (openai/gpt-5.2) and `practice_grader` (openai/gpt-4o-mini) via `_ensure_llm_config`. **Exam columns untouched** — destructive cleanup is Step 12. |
| 2 | Practice repositories | ✅ Done | `shared/repositories/practice_question_repository.py`, `shared/repositories/practice_attempt_repository.py`, `shared/repositories/__init__.py` | Both classes exported. Repos commit per-op; atomic SELECT FOR UPDATE + flip lives in Step 7 service. `list_recent_unread` returns both `graded` and `grading_failed` attempts (drives banner). `answers_json` uses string keys for JSON portability. |
| 3 | Bank generator service + prompts | ✅ Done | `book_ingestion_v2/services/practice_bank_generator_service.py`, `book_ingestion_v2/prompts/practice_bank_generation.txt`, `book_ingestion_v2/prompts/practice_bank_review_refine.txt`, `book_ingestion_v2/constants.py` | `V2JobType.PRACTICE_BANK_GENERATION` enum added. Service mirrors `check_in_enrichment_service` pattern. Reuses `MatchPairOutput`, `BucketItemOutput`, and all format-specific min/max constants from check-in service. `_generate_and_refine_bank` runs initial generation → `review_rounds` refine passes → validate → up to 2 top-up attempts to reach `TARGET_BANK_SIZE=30`. Caps at `MAX_BANK_SIZE=40`. Validate drops: unknown format, empty text fields, FF overflow past 3, dupes by question_text. If final valid < 30 → skip insert + mark failed. |
| 4 | Ingestion API endpoints | ⏳ Next | `book_ingestion_v2/api/sync_routes.py` (extend) | Mirror `generate_check_ins` / `get_latest_check_in_job`. New endpoints: `POST /admin/v2/books/{id}/generate-practice-banks`, `GET /admin/v2/books/{id}/practice-bank-jobs/latest`, `GET /admin/v2/books/{id}/practice-bank-status`, `GET /admin/v2/books/{id}/practice-banks/{guideline_id}`. Chapter-level lock via `ChapterJobService.acquire_lock` with `V2JobType.PRACTICE_BANK_GENERATION.value`. Background task `_run_practice_bank_generation` constructs `LLMService` via `LLMConfigService.get_config("practice_bank_generator")`. |
| 5 | Admin UI bank viewer | Pending | `llm-frontend/src/features/admin/pages/PracticeBankAdmin.tsx` (new), `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` (extend), `llm-frontend/src/features/admin/api/adminApiV2.ts` (new endpoints) | Add "Practice Banks" section in BookV2Detail with per-topic status + generate button + viewer link. New page shows read-only list of 30-40 questions per topic — format, difficulty, correct answer, explanation. No regen-per-question, no analytics. |
| 6 | Grading service | Pending | `tutor/services/practice_grading_service.py` (new), `tutor/prompts/practice_grading.py` (new) | `grade_attempt(attempt_id)` entry-point for the bg worker. Deterministic structured grading. LLM for FF grading (JSON schema: `{score: float[0,1], rationale: str}`). LLM for per-pick rationale (one call per wrong/blank structured answer). `ThreadPoolExecutor(max_workers=10)` for parallel LLM calls. 3x retry with 10/20/40s backoff per call; final failure → `mark_grading_failed`. LLM config key: `practice_grader` (openai/gpt-4o-mini, reasoning_effort=none). |
| 7 | Practice lifecycle service | Pending | `tutor/services/practice_service.py` (new), `tutor/models/practice.py` (new Pydantic DTOs) | `start_or_resume`: catch IntegrityError from partial unique index + re-read winner (idempotent). `_select_set`: 3E/5M/2H mix, **all FFs absorbed** (Q2: FF counts toward ≥4-format variety check), random pick with `_enforce_no_consecutive_same_format`. `_snapshot_question`: copy `question_json` + add `_id/_format/_difficulty/_concept_tag/_presentation_seed`. `submit`: `SELECT FOR UPDATE` → merge `final_answers_json` → flip status → commit → spawn worker. `save_answer`: raises `ConflictError` (→ HTTP 409) if status != `in_progress`. `redact_for_student`: strip `correct_index`/`correct_answer_bool`/`pairs` correctness/`expected_answer`/`grading_rubric`/`explanation_why` from snapshot before serving during the set (FR-26). |
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
- **Bank generator LLM:** `practice_bank_generator` (openai/gpt-5.2, medium reasoning). One call per topic. Review-refine is correctness-scoped only (no tone rewrites).
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

## Next step briefing — Step 4

**Goal:** Ingestion API endpoints for practice bank generation + admin viewer. Pure mirror of check-in enrichment endpoints.

**Files to touch:**
- `llm-backend/book_ingestion_v2/api/sync_routes.py` (extend — don't rewrite)

**What to read first:**
- `sync_routes.py` lines ~1100–1320 (the check-in enrichment endpoints and `_run_check_in_enrichment` background task). This is the template to copy.

**Endpoints to add:**

| Method | Path | Mirrors |
|--------|------|---------|
| POST | `/admin/v2/books/{book_id}/generate-practice-banks?chapter_id&guideline_id&force&review_rounds` | `POST /generate-check-ins` |
| GET | `/admin/v2/books/{book_id}/practice-bank-jobs/latest?chapter_id&guideline_id` | `GET /check-in-jobs/latest` |
| GET | `/admin/v2/books/{book_id}/practice-bank-status?chapter_id` | `GET /check-in-status` (per-topic counts) |
| GET | `/admin/v2/books/{book_id}/practice-banks/{guideline_id}` | NEW — returns the full bank for admin viewer |

**Background task:** `_run_practice_bank_generation(db, job_id, book_id, chapter_id, guideline_id, force_str, review_rounds_str)`. Construct `LLMService` via `LLMConfigService.get_config("practice_bank_generator")`. Catch on lookup failure and use `explanation_generator` as the fallback (match check-in pattern). Instantiate `PracticeBankGeneratorService(db, llm_service)`. Call `enrich_guideline` or `enrich_chapter` based on whether `guideline_id` was passed.

**Lock:** `ChapterJobService.acquire_lock(chapter_id_or_guideline_id, V2JobType.PRACTICE_BANK_GENERATION.value)`.

**Success criteria:**
- `curl -XPOST '<base>/admin/v2/books/<id>/generate-practice-banks?guideline_id=<gid>&review_rounds=1'` returns 202 with a job id.
- Polling `/practice-bank-jobs/latest?guideline_id=<gid>` shows transitions pending → running → completed.
- After completion, `GET /practice-banks/<gid>` returns the list of questions.
- `_apply_practice_tables` migration already ran (Step 1); the `practice_questions` table is populated.

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
- Last commit before work started: `1649f03` (docs: add PRD for Let's Practice v2, PR #100)
- Uncommitted additive changes touch the files in the Steps 1–3 rows of the tracker above.
- `memory/2026-04-16.md` is untracked — unrelated to this branch, leave it.

Recommended next commit boundary: after Step 4 (first testable end-to-end slice — admin can generate a bank and view it).
