# Code Review — Let's Practice v2 (post PR #103 + #104 feedback commit)

**Reviewer:** Claude Opus 4.7 (1M context)
**Date:** 2026-04-18
**Scope:** Fresh review of `feat/lets-practice-v2` against `tech-impl-plan.md`, `prd.md`, and prior `code-review.md`. Focused on what the feedback commit (`028ea1d`) claims to have fixed vs what is actually in the code, plus new findings.

---

## Overall

Feedback commit `028ea1d` applied 17 of the 20 flagged items from PR #103/#104 correctly. Three items were explicitly deferred (F12 tests, PR-104 #5 admin auth, PR-104 #6 SwipeClassify). Of those three, **one is a genuine functional bug** (SwipeClassify) and **one is the branch's largest durability risk** (F12).

Two new findings surfaced in this pass (G1, G2). Remaining plan deviations are mostly cosmetic.

**Merge-blockers:** G1, F12 (still).
**Fix before ship:** G2.
**Nice-to-fix follow-up:** P4, match-pairs identity-shuffle risk, admin endpoint auth.

---

## Verified fixed

| Flag | Commit fix | Verified |
|---|---|---|
| F1 | SequenceCapture registers initial order via `useEffect` | `SequenceCapture.tsx:26-31` — correct |
| F2 | TapToEliminate emits `null` (not `-1`) on eliminating the picked option | `TapToEliminateCapture.tsx:33` — correct |
| F3 | `humanizeTopicSlug` threaded through ChatSession + ModeSelectPage practice nav | `ChatSession.tsx:1081-1083`, `ModeSelectPage.tsx:141` — correct |
| F5 | Dead `find_most_recent_completed_teach_me` removed | grep → 0 matches |
| F6/F7 | Stale comments on `_finalize_teach_me_session` and `_get_canonical_concepts` updated | grep → 0 matches |
| F8 | `.reportcard-exam-score` → `.reportcard-practice-score` | `ReportCardPage.tsx:84` — correct |
| F10 | `_check_no_conflicting_jobs` no longer swallows non-lock exceptions by string-match | `practice_bank_generator_service.py:310-336` — rewrote to rely on explicit `status` check |
| F11 | `retry_grading` uses `SELECT FOR UPDATE` + atomic txn | `practice_service.py:169-205` — correct |
| P1 | `_LLM_CONFIG_SEEDS` `practice_bank_generator` = `claude_code/claude-opus-4-6` matches `_ensure_llm_config` | `db.py:81-85` — correct |
| P2 | Dead `exam_score/exam_total` ADD blocks removed from `_apply_learning_modes_columns` | `db.py:191-231` — correct |
| P3 | `sequence_items` seed-shuffled in `_redact_questions` so raw JSON doesn't leak the order | `practice_service.py:375-380` — correct |
| PR-104 #1 | match_pairs grading guards against unknown-key-with-None falsely matching | `practice_grading_service.py:195` — correct |
| PR-104 #4 | `_select_set` absorbs ALL free-form questions first, reduces difficulty quota | `practice_service.py:266-273` — correct |
| PR-104 #7 | Silent exception swallow fix (same as F10) | verified |
| PR-104 #8 | `SequenceList` uses `key={item}` | `SequenceList.tsx:29` — correct |
| PR-104 #9 | `PracticeResultsPage` caps grading poll at 5 min + stuck-state + Retry | `PracticeResultsPage.tsx:14, 73-77, 151-170` — correct |
| Q5 / F9 (partial) | `counts_by_guidelines` batch aggregate replaces per-topic count calls in `/practice-bank-status` | `practice_question_repository.py:36-51`, `sync_routes.py:1436` — backend only |

---

## Genuinely missed — still open

### G1 — `SwipeClassifyCapture` (and `SortBucketsCapture`) retain stale internal state across consecutive same-format questions

**Files:** `llm-frontend/src/components/practice/capture/SwipeClassifyCapture.tsx:28-30`, `SortBucketsCapture.tsx:30`, `llm-frontend/src/pages/PracticeRunnerPage.tsx:155-162`

The runner mounts `<QuestionRenderer>` without a key. When Q1 and Q2 share a format (allowed up to 2 consecutive per FR-19), React reuses the underlying capture component instance. `useState()` initializers only run once per instance, so:

- `SwipeClassifyCapture` — `cursor` state persists. After Q1 where all items are classified (`cursor = -1`), Q2 renders "All items classified" on mount, **blocking the student from swiping** until they force a remount by navigating elsewhere and back.
- `SortBucketsCapture` — `active` state persists. A student who tapped an item on Q1 but clicked Next before classifying (e.g., `active=3`) arrives on Q2 with `active` still `3`. Tapping a bucket on Q2 silently classifies Q2's item 3.

The prior commit marked PR-104 #6 "no functional bug." That judgment is wrong — the swipe case surfaces any time two swipe_classify questions are consecutive (permitted by FR-19), and will look like a broken UI to the student.

**Fix:** add a `key` to `<QuestionRenderer>` in `PracticeRunnerPage.tsx` so React remounts across question boundaries regardless of format:

```tsx
<QuestionRenderer
  key={q.q_id}
  format={q.format}
  ...
/>
```

Alternatively reset internal state via `useEffect([questionJson])` inside each capture — but `key` is one line and covers all 11 components.

### G2 — `PracticeBankAdmin` N+1 job-status polling on mount (primary F9 concern) not fixed

**File:** `llm-frontend/src/features/admin/pages/PracticeBankAdmin.tsx:213-220`

The feedback commit batched the backend `count_by_guideline` calls (via `counts_by_guidelines`), but the **primary** N+1 F9 flagged was the frontend iterating `getPracticeBankJobStatus` once per topic on page mount. That loop is still in place:

```tsx
topics.forEach(t => {
  getPracticeBankJobStatus(bookId, { guidelineId: t.guideline_id }).then(job => { ... })
});
```

A 20-topic chapter fires 20 parallel requests on mount, most of which 404. F9 proposed a bulk "latest jobs for chapter" endpoint. Either add that endpoint or gate the per-topic probe on a session-scoped "I kicked off a job this session" ref.

### F12 — Practice backend has zero unit tests

**Directories:** `llm-backend/tests/unit/` has no `test_practice_*.py`; `llm-frontend/src/__tests__/` is empty.

`test_report_card_service.py` added 6 cases under `TestReportCardPracticeAttempts` (practice-only, teach_me+practice, grading_failed excluded, in_progress excluded, latest-wins, practice-only-user). But the rest of the ~3000 lines of new practice code — `PracticeService`, `PracticeGradingService`, `PracticeAttemptRepository`, `PracticeBankGeneratorService`, `practice_service._select_set`, `_check_structured` for 11 formats, `submit` atomicity, `retry_grading` ownership, `start_or_resume` IntegrityError re-read, `_redact_questions` for every format, `save_answer` post-submit 409, LLM retry→`grading_failed` path — has **no test coverage at all**.

This was explicitly deferred in commit `028ea1d`'s "Deferred" list. Plan §9 lists 15 unit + 14 integration tests; none are committed. This is the biggest durability risk on this branch — any future refactor here will regress silently.

Highest-leverage tests to land before merge:
- `PracticeGradingService._check_structured` parameterized across all 11 formats (18 cases already validated manually per impl-progress)
- `PracticeService._select_set` — FR-16 mix + FR-17 FF absorption + FR-19 variety
- `PracticeService.start_or_resume` — concurrent-tab IntegrityError re-read
- `PracticeService.submit` — atomic flip + final-answer merge + late PATCH → 409
- `PracticeService.retry_grading` — F11's `SELECT FOR UPDATE` path
- `PracticeAttemptRepository` — partial unique index behavior
- `PracticeGradingService.grade_attempt` — half-point rounding + 3×retry → `grading_failed`
- Snapshot isolation — `test_review_renders_correctly_after_bank_regenerated`

---

## Open / unresolved

### P4 — FF correctness threshold 0.75 vs plan's 0.5
**File:** `practice_grading_service.py:47`

`FF_CORRECT_THRESHOLD = 0.75`. Plan §4.1 comment says `correct: bool  # score >= 0.5 for display`. Commit `028ea1d` explicitly deferred this as "judgment call." Needs a call from the PRD author — if 0.75 is intentional, document in `tech-impl-plan.md` or `impl-progress.md` as a locked decision; if it was drift, reconcile.

### P5 — Endpoint paths still deviate from plan docs
| Plan | Implementation |
|---|---|
| `POST /practice/attempts` | `POST /practice/start` |
| `GET /practice/topics/{gid}/availability` | `GET /practice/availability/{gid}` |
| `GET /practice/attempts?guideline_id=X` | `GET /practice/attempts/for-topic/{gid}` |

Frontend matches backend so the system is consistent. Plan docs / impl-progress not updated. Cosmetic — but worth reconciling before the PR closes so the next contributor isn't confused.

### PR-104 #5 — Admin endpoints lack auth
All `/admin/v2/books/{book_id}/*` endpoints (including the 4 practice-bank ones) declare no `get_current_user` dependency. This is a pre-existing pattern across the admin v2 surface, not a regression introduced by this branch, but worth flagging — a deployed admin URL is effectively public. Consider adding an admin-role guard at the router level as a separate PR.

---

## New minor finding

### Match-pairs theoretical answer leak via identity-shuffle
**File:** `practice_service.py:365-368`, `MatchPairsCapture.tsx:22`

Redaction sends `pair_lefts` + `pair_rights` as parallel arrays. `lefts[i] ↔ rights[i]` is the correct pairing in the underlying `pairs` list. `MatchPairsCapture` seed-shuffles the rights via `seededShuffle(rightsRaw, seed)`. If the seeded permutation happens to be the identity (1/n! chance — ~4% for 4 pairs, ~0.8% for 5 pairs), the correct pairing is presented in perfect left-right index alignment. Mitigation: the student still has to mentally match, so the exposure is soft. Low practical risk.

If worth hardening: re-roll the shuffle server-side until it's a derangement (no fixed points), or ship `pair_rights` pre-shuffled on the server and let the client display them in the received order.

---

## Notes on verified-solid items

Everything else called out in `code-review.md` under "Verified solid" remains correct:
- Atomic submit (`with_for_update` + ownership + status guard + commit-before-spawn)
- Concurrent-tab race (IntegrityError catch + re-read winner)
- Parallel LLM grading via `ThreadPoolExecutor(max_workers=10)`
- Snapshot isolation (`_presentation_seed` injected once, stable on resume)
- Bank generator fail-open + top-up to 3 attempts
- `_redact_questions` covers pairs (split into lefts/rights), bucket_items (strip correct_bucket), sequence_items (seed-shuffled), plus all correct-answer top-level keys
- Banner poll 30s + `visibilitychange`-paused + `currentResultsId` filter + inline retry
- `<AuthenticatedLayout>` above both AppShell and chat-session routes (verified in `App.tsx:98-140`)
- DB migration: events-first delete → sessions delete → DROP COLUMN, single `engine.begin()` txn
- Scorecard: Python merge (SQLite-portable), practice-only topics create rows, half-point render, pluralized attempt count
- Grep gates: backend + frontend both return 0 source-code matches
- Step 1/12 migration split working as specified

---

## Recommendation

**Block the PR on G1 and F12.** G1 is a genuine functional bug that will surface in live student sessions (not a theoretical edge case). F12 is technical debt that will compound — land at minimum the deterministic-grading parameterization and the lifecycle-transition tests (atomic submit, concurrent-start race, save-after-submit 409, retry_grading lock) before merging.

**Fix G2 before merge** — the admin N+1 is cheap to either batch-endpoint or session-gate. Leaving it means the admin page gets noticeably slower as chapters grow.

Everything else (P4, P5, match-pairs identity shuffle, admin auth) can ship as follow-up PRs. None are merge-blockers.
