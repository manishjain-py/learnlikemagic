# Let's Practice v2 — Implementation Progress & Handover

**Date:** 2026-04-17
**Branch:** `feat/lets-practice-v2` (off `main`)
**Status:** 10 of 16 steps complete (counting 9a + 9b). Full student-facing drill flow is now clickable end-to-end locally. Next is Step 9c — AuthenticatedLayout wrapper + PracticeBanner placement so graded-set surface works mid-Teach-Me.

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
| 7 | Practice lifecycle service | ✅ Done | `tutor/services/practice_service.py` (new), `tutor/models/practice.py` (new DTOs) | Public API: `start_or_resume`, `save_answer`, `submit`, `retry_grading`, `get_attempt`, `list_attempts`, `mark_viewed`, `list_recent_unread`. Custom exceptions (NotFound/Permission/Conflict/BankEmpty) map 1:1 to 404/403/409/409. `_select_set` delivers exactly 3E/5M/2H with fallback backfill; `_enforce_no_consecutive_same_format` greedy-reorders to eliminate dupes. `_snapshot_question` injects `_id/_format/_difficulty/_concept_tag/_presentation_seed` (random int). Submit is atomic (`SELECT FOR UPDATE` → merge → flip → commit) then spawns daemon thread with fresh DB session + `practice_grader` LLM config + `initial_retry_delay=10`. Redaction strips 7 correctness keys + flattens match_pairs into `pair_lefts/pair_rights` + strips `correct_bucket` from sort_buckets/swipe_classify. Full lifecycle smoke test passed end-to-end: start → save_answer → submit → 6s grading → AttemptResults with 3.0/10 half-point score + kid-friendly rationales. |
| 8 | Practice runtime REST API | ✅ Done | `tutor/api/practice.py` (new), `main.py` (+1 import, +1 include_router) | 9 endpoints: POST /start, GET /availability/{gid}, GET /attempts/recent, GET /attempts/for-topic/{gid}, GET /attempts/{id}, PATCH /attempts/{id}/answer, POST /attempts/{id}/submit, POST /attempts/{id}/retry-grading, POST /attempts/{id}/mark-viewed. Route declaration order ensures `recent` and `for-topic` win over `{attempt_id}`. Exception→HTTP mapping via a `_call` helper: NotFound→404, Permission→403, Conflict→409, BankEmpty→409. All endpoints require `get_current_user` — no anonymous access (unlike sessions). Verified via FastAPI TestClient: 14/14 cases pass (start, idempotent resume, save, submit, 409-on-locked-attempt, 403-cross-user, grading transition, recent + mark-viewed flow, for-topic history, 404-unknown-id). |
| 9a | Practice-capture component layer | ✅ Done | `llm-frontend/src/components/practice/capture/*.tsx` (11 new + shared `types.ts`), `llm-frontend/src/components/shared/{OptionButton,PairColumn,BucketZone,SequenceList,seededShuffle}.tsx` (5 new shared) | All 11 capture components are controlled (`{ questionJson, value, onChange, seed, disabled }`), no correctness styling, no TTS, no auto-submit. Seed-stable presentation via `mulberry32` + Fisher-Yates — original indices are preserved as values so backend grading works. Per-format answer shapes match the backend: number for pick-style, boolean for true/false, `Record<string,string>` for match_pairs, `number[]` for bucket sorts, `string[]` for sequence. Fix along the way: added `reveal_text` to `REDACT_TOP_LEVEL_KEYS` in practice_service — it was leaking the predict_then_reveal answer in the redacted payload. `npm run build` passes clean. |
| 9b | Frontend runtime pages + chalkboard restyle | ✅ Done | `llm-frontend/src/pages/Practice{Landing,Runner,Results}Page.tsx` (3 new), `llm-frontend/src/components/practice/{QuestionRenderer,FreeFormQuestion}.tsx` (2 new), `llm-frontend/src/api.ts` (9 funcs + 5 interfaces), `App.tsx` (3 routes), `App.css` (+819 lines practice block), `AppShell.tsx` (+/practice in `isChalkboardRoute`), 4 shared primitives + 11 captures + `types.ts` migrated from inline styles to `.practice-*` class names | Runner: question-by-question navigation + internal "Review my picks" screen + atomic submit. Debounced PATCH (600ms) with AbortController canceling in-flight requests before submit. Results: fractional score, per-question expandable breakdown that re-uses `QuestionRenderer` in `disabled` mode to show the student's answer, plus rationale chip + correct-answer summary on wrong picks. Retry grading on `grading_failed`. Reteach CTA deferred to Step 10's ModeSelect refactor. Review + History pages folded into Landing + Results for v1. Banner (30s poll) deferred to Step 9c. **Chalkboard restyle:** on first browser walkthrough the inline cyan/teal styling clashed with the rest of the app's chalkboard aesthetic (PR #99). Refactored to use existing chalkboard tokens — `.selection-step` page surfaces, handwritten `--font-hand` question text, parchment CTAs + free-form textarea, gold/mint/coral chalk states for selection/correct/wrong. `/practice/*` added to `AppShell.isChalkboardRoute` so the theme scope covers the new routes. `npm run build` clean — 1075 modules; verified in Chrome on a graded attempt. |
| 9c | AuthenticatedLayout + banner placement | ⏳ Next | `llm-frontend/src/App.tsx`, `llm-frontend/src/components/AuthenticatedLayout.tsx` (new) | AppShell currently wraps only non-chat routes. Chat-session routes (`teach/:sessionId`, `clarify/:sessionId`) are outside. New wrapper sits above both route groups (below ProtectedRoute/OnboardingGuard) so `PracticeBanner` fires mid-Teach-Me after a practice submit. Fixed-position top element, z-indexed above nav bars. |
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

## Next step briefing — Step 9c

**Goal:** PracticeBanner + AuthenticatedLayout wrapper so a graded set surfaces even when the student is mid-Teach-Me (FR-35) or mid-Clarify (FR-40).

**Problem today:**
`AppShell` wraps only non-chat routes. Chat-session routes (`teach/:sessionId`, `clarify/:sessionId`, `exam/:sessionId`, `practice/:sessionId`) are outside `AppShell` because they have their own nav bar. So if we put the banner in `AppShell`, it never fires during a chat session — exactly when the student is waiting on practice results.

**Solution per plan §5.4.3:**
A new `AuthenticatedLayout` wrapper that sits ABOVE both `AppShell` routes AND chat-session routes (below `ProtectedRoute/OnboardingGuard`). `PracticeBanner` is mounted in this wrapper as a fixed-position top element, z-indexed above the chat nav bar.

**Files to touch:**
- `llm-frontend/src/components/AuthenticatedLayout.tsx` (new)
- `llm-frontend/src/components/practice/PracticeBanner.tsx` (new)
- `llm-frontend/src/App.tsx` — restructure `<Route>` tree so `AuthenticatedLayout` wraps both the AppShell-route group AND the chat-session-route group.

**PracticeBanner behavior (FR-35, FR-40):**
- Polls `GET /practice/attempts/recent` every 30s.
- Pauses when `document.visibilityState !== 'visible'` (saves battery on backgrounded tabs).
- For each `graded` attempt not yet viewed: show a green banner ("Your practice set is ready — tap to see how you did") that navigates to `/practice/attempts/{id}/results`.
- For each `grading_failed` attempt not yet viewed: show a yellow banner with a "Retry" button that calls `POST /practice/attempts/{id}/retry-grading` inline.
- Results page already calls `mark-viewed` on graded/failed — same trigger clears the banner. Clicking the banner itself doesn't need to call mark-viewed explicitly; navigating to results covers it.

**Success criteria:**
- Submit a practice set. Navigate away (e.g. into Teach Me on another topic). Within ~30s the banner appears at the top of the screen with the score.
- Clicking the banner routes to results; the banner disappears after mark-viewed fires.
- Tab backgrounded → poll pauses. Foregrounded → poll resumes.

---

## Superseded briefing — Step 9b

**Goal:** Runtime pages + `QuestionRenderer` that compose the Step 9a captures into a usable drill flow. This is the first slice a student can actually use.

**Files to touch:**
- `llm-frontend/src/pages/Practice{Landing,Runner,Results,Review,History}Page.tsx` (5 new)
- `llm-frontend/src/components/practice/{QuestionRenderer,FreeFormQuestion,PracticeBanner}.tsx` (3 new)
- `llm-frontend/src/api.ts` — add practice API client functions
- `llm-frontend/src/App.tsx` — register 5 new routes

**What to read first:**
- The existing chat-session flow for how routes are structured today.
- `src/api.ts` — existing fetch helper pattern.
- `PracticeBankAdmin.tsx` — the viewer pattern I already built; `QuestionRenderer` will share the format→component switch shape.

**Key pieces:**

1. **`QuestionRenderer`** — dispatch table `format → CaptureComponent`. Passes `questionJson`, `value`, `onChange`, `seed`, `disabled` through. Adds `FreeFormQuestion` for `free_form` (textarea; no correctness styling).

2. **`PracticeLandingPage`** — lists past attempts (`GET /practice/attempts/for-topic/{gid}`) + "Start Practice" button that hits `POST /practice/start` then routes to the runner.

3. **`PracticeRunnerPage`** — one question at a time with Prev/Next navigation; "Review my picks" screen before submit; atomic submit that (a) cancels in-flight debounced PATCHes via AbortController, (b) calls `POST /attempts/{id}/submit` with `{ final_answers }`, (c) routes to results.

4. **`PracticeResultsPage`** — fractional score (half-point rounded), Reteach / Practice-again / Review-my-picks CTAs. Reteach routes to `/mode-select` with `?autostart=teach_me`; Practice-again calls `/practice/start` with the same guideline_id.

5. **`PracticeReviewPage`** — per-question breakdown using the captures in `disabled` mode + correctness indicator + `rationale`.

6. **`PracticeHistoryPage`** — same data as landing but as a standalone page.

7. **`PracticeBanner`** — polls `/practice/attempts/recent` every 30s; pauses when `document.visibilityState !== 'visible'`. Success banner → Results page. Failure banner → `POST /retry-grading`.

**Success criteria:**
- Can start practice from the admin UI test URL → complete a full 10-question set → see graded results with kid-friendly rationales → review each question.
- Debounced save during the set; submit is atomic (no race with late PATCHes).
- Banner fires once on success and clears after `mark-viewed`.

---

## Superseded briefing — Step 9a

**Goal:** Practice-capture components. A NEW parallel React component layer — not a fork of check-in's existing `*Activity.tsx` — that captures student input per question format. Controlled components: `{ value, onChange, seed }`.

**Key constraint — why this isn't reuse:**
Existing `*Activity.tsx` components are correctness-driven, uncontrolled, side-effectful (auto-submit on correct, TTS, non-deterministic shuffle, internal multi-step state). Practice capture must be pure + controlled so the batch-drill flow can buffer answers, navigate between questions, and round-trip state via PATCH /answer. Per plan §5.4.1 the "add a `mode` prop to existing" option was rejected because it would leak runtime correctness logic into the batch path.

**Files to create:**
- `llm-frontend/src/components/practice/capture/{PickOne,TrueFalse,FillBlank,MatchPairs,SortBuckets,Sequence,SpotTheError,OddOneOut,PredictThenReveal,SwipeClassify,TapToEliminate}Capture.tsx` (11 new)
- `llm-frontend/src/components/shared/{OptionButton,PairColumn,BucketZone,SequenceList}.tsx` (shared primitives — reuse between capture variants)
- Note: `FreeForm` capture lives in Step 9b (`FreeFormQuestion.tsx` — textarea w/ no correctness styling)

**What to read first:**
- Existing `llm-frontend/src/components/*Activity.tsx` files — understand the correctness-driven behavior you're explicitly NOT copying.
- `llm-frontend/src/components/practice/**` — may already have stubs or be empty.

**Controlled-component contract:**
```ts
interface CaptureProps<T> {
  questionJson: Record<string, unknown>;  // redacted payload (no correctness)
  value: T | null;                        // current student answer from parent state
  onChange: (value: T) => void;           // called on every input change
  seed: number;                           // for deterministic shuffle
  disabled?: boolean;                     // freeze during review / after submit
}
```

**Per-format answer shape (must match backend grading):**
- `pick_one` / `fill_blank` / `tap_to_eliminate` / `predict_then_reveal` / `spot_the_error` / `odd_one_out`: `number` (index)
- `true_false`: `boolean`
- `match_pairs`: `{ [leftText: string]: string }` (map left → right)
- `sort_buckets` / `swipe_classify`: `number[]` (bucket_idx per item, in the order served)
- `sequence`: `string[]` (the reordered sequence_items)

**Shuffle-by-seed:** Use a simple deterministic seeded shuffle (e.g., mulberry32 → Fisher-Yates) so options order is stable on refresh. Don't touch `questionJson.options` order — the backend grading compares against the original snapshot.

**Success criteria:**
- 11 new components compile under strict TS.
- Each one captures input via `onChange` without any correctness styling (no red/green until review).
- Storybook/PoC smoke: render each component with a sample redacted `questionJson`, verify input is captured.

---

## Superseded briefing — Step 8

**Goal:** Practice runtime REST API — thin HTTP wrapper around `PracticeService` that serves the student app. REST only (no WebSocket). Every endpoint ownership-checks `attempt.user_id == current_user.id`.

**Files to touch:**
- `llm-backend/tutor/api/practice.py` (new)
- `llm-backend/main.py` (register router)

**What to read first:**
- Any existing tutor API module for the auth pattern — `tutor/api/session.py` is the closest analogue. Look for the `current_user` dependency and the `_check_session_ownership` helper it mirrors.
- `tutor/services/practice_service.py` — the service layer this API wraps.
- `tutor/models/practice.py` — response DTOs (`Attempt`, `AttemptResults`, `AttemptSummary`).

**Endpoints (per plan §4.1):**

| Method | Path | Body / Query | Returns |
|--------|------|-------------|---------|
| POST | `/practice/start` | `{guideline_id: str}` | `Attempt` (200 or 201) |
| GET | `/practice/attempts/{attempt_id}` | — | `Attempt` \| `AttemptResults` |
| PATCH | `/practice/attempts/{attempt_id}/answer` | `{q_idx: int, answer: Any}` | `204 No Content` (debounced per-answer save) |
| POST | `/practice/attempts/{attempt_id}/submit` | `{final_answers: Dict[str, Any]}` | `Attempt` (status='grading') |
| POST | `/practice/attempts/{attempt_id}/retry-grading` | — | `204 No Content` |
| POST | `/practice/attempts/{attempt_id}/mark-viewed` | — | `204 No Content` |
| GET | `/practice/attempts/recent` | — | `list[AttemptSummary]` (banner poll, 30s interval) |
| GET | `/practice/attempts/for-topic/{guideline_id}` | — | `list[AttemptSummary]` (history) |
| GET | `/practice/availability/{guideline_id}` | — | `{available: bool, question_count: int}` (drives ModeSelectPage tile) |

**Exception mapping (wrap every handler):**
- `PracticeNotFoundError` → 404
- `PracticePermissionError` → 403
- `PracticeConflictError` → 409
- `PracticeBankEmptyError` → 409 with detail `"no bank available for this topic"`

**Wiring:**
- Register at prefix `/practice` in `main.py`.
- Each endpoint constructs `PracticeService(db)` — no shared singleton.
- `current_user.id` is the ownership key; never trust a `user_id` sent in the body.

**Success criteria:**
- `curl -H 'Auth: ...' -XPOST /practice/start -d '{"guideline_id":"..."}'` returns 200 with a redacted `Attempt`.
- Two parallel starts with the same user+topic return the same `attempt.id`.
- `curl -XPATCH /practice/attempts/{id}/answer` on a submitted attempt returns 409.
- `curl -XPOST /practice/attempts/{id}/submit` returns immediately (before grading finishes); polling the attempt transitions `grading → graded`.
- Recent-attempts poll returns any `graded` or `grading_failed` attempt not yet `mark-viewed`'d.

---

## Superseded briefing — Step 7

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

As of 2026-04-17:
- Branch: `feat/lets-practice-v2` (local; not pushed)
- Commits on the branch (oldest → newest):
  - `fc4cdbd` — additive backend foundation (steps 1-3)
  - `7d4a37d` — ingestion API (step 4)
  - `db69da5` — admin UI + grading service (steps 5-6)
  - `11ad29f` — lifecycle service (step 7)
  - `dc17d4f` — runtime REST API (step 8)
  - `06c1423` — capture components (step 9a)
  - (step 9b — runtime pages + chalkboard restyle — committed after this update)
- DB migration applied on local dev; claude_code/claude-opus-4-6 bank generation verified on one topic (30 questions, 12 formats).
- Full student flow clickable end-to-end locally: landing → start → runner (Prev/Next + Review) → atomic submit → grading poll → graded results with fractional score + per-question rationales.
- Step 9b visual consistency: new practice pages fully styled with chalkboard tokens (`--board-green`, `--parchment`, `--chalk-*`, `--font-hand`) so they match the app's aesthetic from PR #99. `/practice/*` added to `AppShell.isChalkboardRoute`.

Next step: 9c (AuthenticatedLayout + PracticeBanner placement).
