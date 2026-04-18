# Let's Practice v2 — QA Handover

**For:** a fresh Claude session helping the user manually test this feature.
**Status of code:** merged to `main` at commit `5da2d19`, pushed to `origin/main` on 2026-04-18.

Read this file first, then drill into the linked docs if you need more depth. Below is everything a new session needs to debug any issue that comes up during manual testing.

---

## 1. What this feature is

**Let's Practice v2** is a batch-drill learning mode that replaced the old Exam mode and the old chat-based Practice mode. The student:

1. Picks a topic → sees Let's Practice tile (enabled iff a question bank exists).
2. Taps it → lands on `PracticeLandingPage` → **Start practice** / **Resume** / **See past evaluations**.
3. Runner presents **10 questions, one at a time**, silent (no hints, no correctness, no audio, no Pixi).
4. Review screen → one-tap **Submit**. Student is routed back to the topic's ModeSelectPage and can go do anything else.
5. Grading runs **in the background** (ThreadPoolExecutor). When done, a top **banner** appears on any authenticated page.
6. Tap banner → results page with fractional score (half-point rounded), **Reteach** + **Practice again** CTAs, and per-question review with correct answer + LLM-written "why you were wrong" rationale.

Key design doc: `docs/principles/practice-mode.md`. Full student flow: `docs/functional/practice-mode.md`. Architecture + schema: `docs/technical/practice-mode.md`.

---

## 2. What was shipped (high level)

| Layer | Files (new unless noted) |
|---|---|
| **DB schema** | 2 new tables: `practice_questions`, `practice_attempts`. `sessions.exam_score`/`exam_total` dropped. All legacy exam/practice session rows deleted. |
| **Ingestion** | New last stage: bank generator (`book_ingestion_v2/services/practice_bank_generator_service.py`) + 2 prompts + `V2JobType.PRACTICE_BANK_GENERATION`. 4 admin endpoints in `book_ingestion_v2/api/sync_routes.py`. |
| **Runtime backend** | New `/practice/*` router (`tutor/api/practice.py`); `tutor/services/practice_service.py` (lifecycle) + `tutor/services/practice_grading_service.py` (deterministic + LLM grading, parallel). |
| **Runtime frontend** | 3 pages (Landing/Runner/Results) + 11 capture components + QuestionRenderer + FreeFormQuestion + PracticeBanner + AuthenticatedLayout. |
| **Admin UI** | `PracticeBankAdmin.tsx` (read-only bank viewer + generate controls). |
| **Scorecard** | Practice chip on report card (latest score + attempt count). |
| **Cleanup** | Exam mode, old chat-practice mode, exam/practice prompts + services + tests — all deleted. |
| **Docs** | 3 new practice-mode docs (principles/functional/technical). |
| **Tests** | 52 unit tests for grading/lifecycle/repository + 6 practice-scorecard tests. |

---

## 3. Architecture — one diagram

```
Frontend
  ModeSelectPage ──tap Let's Practice──► /practice/:guidelineId
                                                │
                          PracticeLandingPage ──┤
                                Start / Resume / History
                                                ▼
                          PracticeRunnerPage (Q-by-Q + Review + Submit)
                                                │
                                       POST /submit
                                                ▼
                          PracticeResultsPage  (polls /attempts/{id} every 2s, cap 5min)

  PracticeBanner (polls /attempts/recent every 30s)  — mounted in AuthenticatedLayout above
                                                        AppShell AND chat-session routes.

Backend
  /practice/start, /attempts/*, /attempts/recent, …  (REST only — NO websocket, NO agent turn loop)
       │
       ▼
  PracticeService  ──► PracticeAttemptRepository, PracticeQuestionRepository
       │
       │ on submit: threading.Thread daemon (fresh DB session) ──►
       ▼
  PracticeGradingService  ──► ThreadPoolExecutor(max_workers=10) ──► LLMService (practice_grader)

Ingestion
  Admin clicks Generate  ──►  practice_bank_generator_service.enrich_chapter()
                                │
                                ▼
                          generate → review-refine (N rounds) → validate → top-up
                                                                            ▼
                                                           PracticeQuestionRepository.bulk_insert
```

**Do NOT shoehorn practice into `session_service.py` / `orchestrator.py`.** Practice is deliberately outside the chat-based tutor orchestrator. It is REST CRUD + a threaded grading worker. No conversation, no streaming, no agent turns.

---

## 4. Code map — "where does this live?"

### Backend (`llm-backend/`)

| Concern | File |
|---|---|
| Practice ORM models | `shared/models/entities.py` — classes `PracticeQuestion` (line ~378), `PracticeAttempt` (line ~401) |
| Practice DTOs + exceptions | `tutor/models/practice.py` — `Attempt`, `AttemptResults`, `AttemptSummary`, `GradedQuestion`, `Practice*Error` |
| Attempt repo (CRUD) | `shared/repositories/practice_attempt_repository.py` |
| Bank repo (CRUD + batch count) | `shared/repositories/practice_question_repository.py` |
| Practice REST router | `tutor/api/practice.py` |
| Lifecycle service (set selection, submit, redaction) | `tutor/services/practice_service.py` |
| Grading service (deterministic + LLM, parallel) | `tutor/services/practice_grading_service.py` |
| Grading prompt templates | `tutor/prompts/practice_grading.py` |
| Bank generator | `book_ingestion_v2/services/practice_bank_generator_service.py` |
| Bank generator prompts | `book_ingestion_v2/prompts/practice_bank_generation.txt`, `practice_bank_review_refine.txt` |
| Admin ingestion endpoints | `book_ingestion_v2/api/sync_routes.py` (search for `practice-bank`) |
| Admin response schemas | `book_ingestion_v2/models/schemas.py` — `TopicPracticeBankStatus`, `PracticeBankDetailResponse`, … |
| DB migration (additive) | `db.py` → `_apply_practice_tables()` |
| DB migration (destructive Step-12 cleanup) | `db.py` → `_cleanup_exam_and_old_practice_data()` |
| LLM config seeds | `db.py` → `_LLM_CONFIG_SEEDS` (rows for `practice_bank_generator`, `practice_grader`) |
| Report card practice merge | `tutor/services/report_card_service.py` — `_load_user_practice_attempts`, `_merge_practice_attempts_into_grouped` |

### Frontend (`llm-frontend/src/`)

| Concern | File |
|---|---|
| Route wiring | `App.tsx` — look for the `/practice/…` routes and `<AuthenticatedLayout>` wrapper |
| Top-level layout wrapper | `components/AuthenticatedLayout.tsx` (mounts `<PracticeBanner/>` + `<Outlet/>`) |
| Banner (poll + display + retry) | `components/practice/PracticeBanner.tsx` |
| Landing (Start / Resume / History) | `pages/PracticeLandingPage.tsx` |
| Runner (Q-by-Q + Review + Submit) | `pages/PracticeRunnerPage.tsx` |
| Results (poll → score → per-Q review) | `pages/PracticeResultsPage.tsx` |
| Format dispatcher | `components/practice/QuestionRenderer.tsx` |
| Free-form question | `components/practice/FreeFormQuestion.tsx` |
| 11 capture components | `components/practice/capture/*Capture.tsx` + `types.ts` |
| Shared UI primitives | `components/shared/` — `OptionButton`, `PairColumn`, `BucketZone`, `SequenceList`, `seededShuffle.ts` |
| Admin bank viewer | `features/admin/pages/PracticeBankAdmin.tsx` |
| Admin API funcs | `features/admin/api/adminApiV2.ts` (practice-bank helpers) |
| API client (runtime) | `api.ts` — search for `getPractice*`, `startPractice`, `submitPractice`, `PracticeAttempt*` interfaces |
| ModeSelection tile logic | `components/ModeSelection.tsx`, `pages/ModeSelectPage.tsx` |
| Teach-Me → Practice CTA rewire | `pages/ChatSession.tsx` → `handleStartPracticeFromCTA` (line ~1079) |
| Report-card practice chip | `pages/ReportCardPage.tsx` — `formatPracticeScore`, `.reportcard-practice-score` |
| Practice CSS | `App.css` — search for `.practice-` prefix |

### Tests

| File | What it covers |
|---|---|
| `llm-backend/tests/unit/test_practice_grading_service.py` | `_check_structured` for all 11 formats, blank handling, half-point rounding, grading_failed path, FF threshold, idempotent skip |
| `llm-backend/tests/unit/test_practice_service.py` | `_select_set` (mix, FF absorption, variety, too-small), redaction, start_or_resume, save_answer 409, submit atomicity, retry_grading |
| `llm-backend/tests/unit/test_practice_attempt_repository.py` | CRUD, `list_recent_unread` (graded + failed), `latest_graded`, count, `mark_submitted` no-op when not in_progress, `mark_viewed` |
| `llm-backend/tests/unit/test_report_card_service.py::TestReportCardPracticeAttempts` | Practice-only topic rows, merge with teach_me, exclusion of failed/in-progress, latest wins |

Run: `cd llm-backend && venv/bin/python -m pytest tests/unit/test_practice_*.py tests/unit/test_report_card_service.py -q --no-cov`

---

## 5. Locked design decisions (DO NOT change without explicit user approval)

These are invariants. If any test fails because it conflicts with one of these, the **test is probably wrong** — not the code.

1. **Self-contained attempts via snapshot** — `practice_attempts.questions_snapshot_json` stores the full question payload at attempt creation. Rendering / grading / review read **only from the snapshot**, never from `practice_questions`. Bank regeneration must never orphan history. (`practice_service._snapshot_question`)

2. **Atomic submit** — `POST /practice/attempts/{id}/submit` carries `final_answers_json` in the body. Server: `SELECT FOR UPDATE` → ownership + status check → merge final_answers → flip status to `grading` → commit → spawn worker. Client: `AbortController` cancels any in-flight debounced PATCH before calling submit. Late PATCH after commit → **409, not silent no-op**. (`practice_service.submit`, `PracticeRunnerPage.handleSubmit`)

3. **Concurrent-tab start race** — `start_or_resume` catches `IntegrityError` from the partial unique index and re-reads the winning `in_progress` row. Both tabs return the same attempt. (`practice_service.start_or_resume`)

4. **Partial unique index** — `uq_practice_attempts_one_inprogress_per_topic` on `(user_id, guideline_id) WHERE status='in_progress'`. Enforced on Postgres; SQLite tests don't enforce, so concurrency is tested at the service level via IntegrityError simulation.

5. **Half-point rounding at write-time** — `total_score = round(raw * 2) / 2` stored once when grading completes. All display paths read the stored value. Per-question `score` stays raw fractional in `grading_json`. (Python uses banker's rounding for midpoints — `6.25 → 6.0`, `6.75 → 7.0`.)

6. **Banner placement** — `<AuthenticatedLayout>` mounts `<PracticeBanner/>` **above both AppShell and chat-session routes**. Mounting inside AppShell alone misses mid-Teach-Me banner firing.

7. **Banner filter** — `/practice/attempts/recent` returns `status IN ('graded', 'grading_failed') AND results_viewed_at IS NULL`. Failed attempts MUST be in the banner so students can Retry — **do not narrow to `graded` only**.

8. **Presentation seed** — each snapshot has `_presentation_seed: int` generated at attempt creation. Frontend shuffle components consume this seed via `seededShuffle` (`mulberry32` + Fisher-Yates). Same seed → same layout on resume.

9. **Sequence redaction** — `sequence_items` is stored in correct order in the snapshot and seed-shuffled during redaction on every serve (snapshot not mutated). Grading compares against the snapshot's original order.

10. **Poll, not push** — 30s banner poll, `visibilitychange`-paused. No WebSocket / SSE in v1.

11. **No half-state migrations** — additive migration (`_apply_practice_tables`) in Step 1 leaves exam code alive. Destructive (`_cleanup_exam_and_old_practice_data`) runs ONLY in Step 12, same deploy as code removal, single `engine.begin()` transaction (events-first delete → sessions delete → DROP COLUMN).

12. **Practice LLM configs** — `practice_bank_generator` = `claude_code/claude-opus-4-6` (offline, per CLAUDE.md rule), `practice_grader` = `openai/gpt-4o-mini` (runtime, fast). Admin can override in `/admin/llm-config`.

13. **FF count 0–3** per topic (Q6 resolution). Purely procedural topics may have 0 FFs.

14. **FF correctness threshold = 0.75** (intentional; plan had 0.5 as an inline comment but code kept 0.75 as a judgment call — still open, in `practice_grading_service.py:47`).

15. **Capture components are pure-controlled** — `{questionJson, value, onChange, seed, disabled}`. No auto-submit, no correctness styling, no TTS, no hints. Original indices preserved as values.

16. **QuestionRenderer has `key={q.q_id}`** — forces remount across questions so internal state (cursor, active) doesn't leak between consecutive same-format questions. **DO NOT REMOVE THE KEY.** (Previously caused SwipeClassify to show "All classified" on Q2 — see fix in `PracticeRunnerPage.tsx:156`.)

---

## 6. Symptom → code area (debugging handbook)

When the user reports a bug during manual testing, use this to jump straight to the likely root cause.

| Symptom | Likely root cause | Files to inspect first |
|---|---|---|
| **Tile disabled on a topic that should be available** | Availability endpoint returns `available: false` (bank count < 10) | `tutor/api/practice.py` (`/availability/{gid}`), `PracticeQuestionRepository.count_by_guideline` |
| **Tile enabled but Start fails with "bank empty"** | Bank has < 10 rows (gating mismatch — availability uses `>= 10`, `_select_set` also needs 10) | `practice_service._select_set`, `PracticeBankEmptyError` |
| **Questions repeated within a set** | `_select_set` backfill path pulled dupes | `practice_service._select_set` (leftover shuffle) |
| **More than 2 consecutive same-format questions** | `_enforce_no_consecutive_same_format` greedy failed | `practice_service._enforce_no_consecutive_same_format` |
| **Resume shows different option order** | Seed not persisting, or frontend not using it | Check `_presentation_seed` in snapshot (`_snapshot_question`); verify capture uses `seededShuffle(…, seed)` |
| **Student answer silently lost after submit** | Debounce-race NOT handled; PATCH landed after status flipped | `PracticeRunnerPage.handleSubmit` (AbortController cancel), `practice_service.submit` (final_answers merge) — should see 409 in Network |
| **"All items classified" on a fresh swipe_classify / stuck active item on sort_buckets** | QuestionRenderer lost its `key` — component reused across questions | `PracticeRunnerPage.tsx:156` — must have `key={q.q_id}` on `<QuestionRenderer>` |
| **Correct answer visible before submit** | Redaction missing a field | `practice_service.REDACT_TOP_LEVEL_KEYS` + format-specific logic in `_redact_questions` (lines 345-383). For sequence: seed-shuffle; for match_pairs: split into `pair_lefts/pair_rights`; for bucket items: strip `correct_bucket` |
| **Banner doesn't appear within 30s of submit** | Poll paused (tab hidden), user already on results page (filter), or `/recent` returned empty | `PracticeBanner.fetchRecent`, `list_recent_unread` query in repo (must include `grading_failed`), `currentResultsId` filter in banner |
| **Banner appears forever (won't clear)** | `results_viewed_at` not stamped | `PracticeResultsPage.tsx:93-99` `markPracticeViewed` call on mount; `PracticeAttemptRepository.mark_viewed` |
| **Results page shows score but wrong rationale per Q** | `grading_json[q_idx]` mis-keyed | `practice_grading_service.grade_attempt` (Phase 3 assembly — keys must be stringified q_idx) |
| **Grading stuck forever in "Grading your answers…"** | Background thread died silently (acknowledged v1 limitation). No heartbeat/sweeper. After 5min, results page shows "taking longer than expected" + Retry | `PracticeResultsPage.POLL_MAX_ATTEMPTS=150`, `practice_service._spawn_grading_worker` — thread may have crashed; check backend logs for `Grading worker crashed for attempt …` |
| **Grading fails on a specific format** | `_check_structured` or `_summarize_pick` missing a branch | `practice_grading_service._check_structured` — 11-branch switch. Confirm q shape matches expected keys (e.g. `pairs` = list of `{left, right}`, `bucket_items` = list of `{text, correct_bucket}`) |
| **Match_pairs shown as "wrong" when student got it right** | Unknown-key-None guard regressed | `practice_grading_service._check_structured` match_pairs branch (line ~195) — must check `k in expected` before comparing |
| **Reteach CTA missing from results page** | No `subject/chapter/topic` in `location.state` — normal for banner-opened results. | `PracticeResultsPage.canReteach` logic (line ~37) — expected. Only runner/results accessed directly from ModeSelectPage carry the state |
| **Teach Me → Practice CTA 404s** | `teachMeGuidelineId` unset OR route mismatch | `ChatSession.handleStartPracticeFromCTA` (line ~1079) — navigates to `/practice/:guidelineId` |
| **Report card practice chip missing or wrong** | `_merge_practice_attempts_into_grouped` couldn't resolve hierarchy | `report_card_service._build_guideline_lookup` (must include subject + accept practice attempts source); `_load_user_practice_attempts` (filters `status='graded'`) |
| **Admin bank viewer N+1 requests on page load** | `sessionStorage` gate regressed | `PracticeBankAdmin.tsx` useEffect at mount — should probe ONLY topics in the `practice-bank-active-topics:<book>:<chapter>` sessionStorage list + one unconditional chapter-level call |
| **Bank generation failing with "explanations not generated yet"** | Prerequisite guard (correct behavior). Run explanation generation first | `practice_bank_generator_service._load_explanation_cards` + `enrich_guideline` early-return |
| **Bank generation returns < 30 valid questions after top-up** | LLM produced low-quality / duplicate questions; top-up exhausted at 3 attempts | `practice_bank_generator_service.MAX_GENERATION_ATTEMPTS`, `_validate_bank`, `_top_up`. Bank NOT inserted; topic stays greyed out. Consider `review_rounds=0` or re-run |
| **Migration error on DB boot** | Events FK with ON DELETE RESTRICT was blocking sessions delete | `db._cleanup_exam_and_old_practice_data` — events-first delete is intentional; idempotent on rerun |

---

## 7. Known / deferred items (NOT bugs — don't file)

| Item | Why not a bug |
|---|---|
| Admin `/admin/v2/*` endpoints lack auth dependency | Pre-existing pattern across all V2 admin endpoints, not unique to practice. Flagged in code-review-2 as a separate follow-up PR. |
| FF correctness threshold is 0.75 not plan's inline-comment 0.5 | Locked decision — stricter pedagogical choice. Documented in locked-decisions #14. PRD author still to confirm if they want 0.5. |
| Endpoint paths differ slightly from tech-impl-plan.md (`POST /start` vs `POST /attempts`, etc.) | Frontend matches backend — system is consistent. Plan doc is stale; cosmetic. |
| Match pairs rare identity-shuffle leak (~4% at 4 pairs) | Correct pairing leaks only when seeded shuffle is the identity permutation. Student still has to match mentally. Soft exposure. Low practical risk. |
| Silent grading-thread death → attempt stuck in `status='grading'` indefinitely | Acknowledged v1 limitation. Results page caps poll at 5min, shows Retry. Post-v1 fix: add `grading_started_at` + sweeper. |
| Banner may briefly show score 0 stale before refresh | Not observed in practice but possible. Banner re-fetches next poll cycle. |
| Chat-session route reuse `/session/:sessionId` (backward-compat route) | Intentional — legacy links continue to work. |

---

## 8. Dev setup

```bash
# Backend
cd llm-backend
source venv/bin/activate      # NOT .venv — see memory/Project Memory → Python Environment
make run                      # http://localhost:8000

# Frontend
cd llm-frontend
npm run dev                   # http://localhost:3000

# DB migrate
cd llm-backend
venv/bin/python db.py --migrate

# Run practice tests
cd llm-backend
venv/bin/python -m pytest tests/unit/test_practice_*.py -q --no-cov

# Import-check the backend
cd llm-backend
venv/bin/python -c "from main import app"
```

**Venv gotcha:** `source venv/bin/activate` can be flaky in some shells. Reliable alternative: `llm-backend/venv/bin/python <command>` directly.

**Frontend build:** `cd llm-frontend && npm run build` — should report 1076 modules, no errors.

---

## 9. Test surface & URLs

**Student:**
- ModeSelectPage: `http://localhost:3000/learn/:subject/:chapter/:topic`
- Practice landing: `http://localhost:3000/practice/:guidelineId`
- Practice runner: `http://localhost:3000/practice/attempts/:attemptId/run`
- Practice results: `http://localhost:3000/practice/attempts/:attemptId/results`
- Report card: `http://localhost:3000/report-card`
- Session history: `http://localhost:3000/history`

**Admin:**
- Book V2 detail: `http://localhost:3000/admin/books-v2/:bookId`
- Practice Bank admin: `http://localhost:3000/admin/books-v2/:bookId/practice-banks/:chapterId`
- LLM config: `http://localhost:3000/admin/llm-config`

**Backend routes (for curl-testing):**
- `POST /practice/start {guideline_id}` — start/resume
- `GET /practice/availability/:gid` — tile gating
- `GET /practice/attempts/:id` — runner hydrate / results poll (shape depends on status)
- `PATCH /practice/attempts/:id/answer {q_idx, answer}` — auto-save
- `POST /practice/attempts/:id/submit {final_answers}` — atomic submit
- `POST /practice/attempts/:id/retry-grading` — on `grading_failed`
- `POST /practice/attempts/:id/mark-viewed` — clears banner
- `GET /practice/attempts/recent` — banner poll source
- `GET /practice/attempts/for-topic/:gid` — history

All require `Authorization: Bearer <jwt>`.

---

## 10. Manual test flows (refer back to prior message)

The detailed 10-step test guide was delivered in the previous message. Key scenarios to exercise:

1. Tile gating — disabled / enabled by availability
2. Admin bank generation — **verify the G2 fix: only 1 chapter-level call on mount, no per-topic N+1**
3. Full drill — all 12 formats, skip + edit + submit
4. **Verify G1 fix** — consecutive same-format questions (esp. `swipe_classify`, `sort_buckets`) must NOT leak state
5. Banner from Teach Me / `/learn` / other routes
6. Resume mid-set — same questions, same seed, same prior answers
7. Debounce-race safety — edit + submit within 600ms
8. Grading failure path — break LLM config → submit → amber banner → Retry
9. Results: fractional score, Reteach, Practice again, per-Q expansion
10. Report card practice chip, session history no exam filter, legacy routes 404

---

## 11. If debugging, in this order

1. **Reproduce** — get the exact URL, student, topic, browser steps.
2. **Check browser DevTools Network + Console first** — often reveals 4xx/5xx immediately.
3. **Check backend stdout** — errors log with `logger.exception` in `PracticeService`, `PracticeGradingService`, `PracticeBankGeneratorService`.
4. **Cross-reference with symptom table (§6)** — jump to the implicated file.
5. **Read the locked-decisions list (§5) before proposing a fix** — many "bugs" are actually invariants.
6. **Run the unit tests** — 87 tests in the practice + scorecard suite. If any break, that localizes the break fast.
7. **Check the git log of the implicated file** — the commit message usually explains the "why."
8. **If the issue is NOT in the symptom table and not caught by tests**, it's likely a genuine new bug. Write a minimal repro, check the locked-decisions list one more time, then fix with tight scope (don't refactor surrounding code).

---

## 12. Further reading (if you need depth)

- `docs/feature-development/lets-practice-v2/prd.md` — requirements (FR-1 through FR-51)
- `docs/feature-development/lets-practice-v2/tech-impl-plan.md` — full technical spec, ~1000 lines
- `docs/feature-development/lets-practice-v2/impl-progress.md` — commit-by-commit log + locked-decisions + testing backlog
- `docs/feature-development/lets-practice-v2/code-review.md` — first-pass review (F1-F12)
- `docs/feature-development/lets-practice-v2/code-review-2.md` — second-pass review (G1-G2, verifies prior fixes)
- `docs/principles/practice-mode.md` — the "why"
- `docs/functional/practice-mode.md` — student journey
- `docs/technical/practice-mode.md` — architecture + schema + APIs + frontend layers
- `CLAUDE.md` — top-level project context
