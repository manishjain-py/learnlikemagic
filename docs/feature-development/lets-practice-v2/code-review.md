# Code Review — Let's Practice v2 (PR #103)

**Reviewer:** Claude Opus 4.7 (1M context)
**Date:** 2026-04-17
**Scope:** Full PR review against `tech-impl-plan.md` + `impl-progress.md`. Two passes.

---

## Overall

Substantial, well-executed PR. Architecture, sequencing (additive → destructive → docs), and all plan-level correctness concerns (atomic submit, snapshot isolation, partial unique index, banner placement, concurrent-tab race, redaction) are implemented correctly. Grep-gates clean. The code shows good engineering judgment in several places (Python merge over SQL aggregate for SQLite portability, controlled-components capture layer, threading pattern for grading worker).

**Merge-blockers:** F1, F12 (tests).
**Nice-to-fix follow-up:** F2, F3, F5, F9, F10.
**Cosmetic:** F4, F6, F7, F8, P2, P3, P6, P7.

---

## Critical / Concerning

### F1 — `SequenceCapture` doesn't persist initial shuffle as the student answer
**File:** `llm-frontend/src/components/practice/capture/SequenceCapture.tsx:19`

`current = value ?? initialOrder` — if the student never drags the up/down buttons, `value` stays `null`. Backend grading compares `answer == sequence_items` list equality; `null` → graded as blank (wrong). If the seeded shuffle happens to produce the correct order (1/n! chance), the student sees a correct-looking sequence, leaves it alone, and is marked wrong.

**Fix:** `useEffect` on mount that calls `onChange(initialOrder)` when `value == null`, so the shuffled order becomes the registered answer until the student reorders.

### F12 — Missing committed unit tests for the new practice code
**Files:** `llm-backend/tests/unit/test_practice_*.py` (don't exist)

Plan §9 lists 13+ unit tests and 14+ integration tests. Only `test_report_card_service.py` has practice-related tests (for the scorecard merge). PR description mentions "14/14 TestClient cases", "18/18 deterministic grading cases" — these were run manually during development but **not committed**. The frontend `src/__tests__/` directory is now empty after the Step-13 cleanup.

High-leverage tests to commit (mapping the plan's list):
- `PracticeGradingService._check_structured` for all 11 non-FF formats (18 cases already validated manually)
- `PracticeService._select_set` difficulty mix + FF absorption + variety
- `PracticeService.start_or_resume` IntegrityError re-read path
- `PracticeService.submit` atomic flip + final-answer merge + late PATCH → 409
- `PracticeAttemptRepository` partial unique index behavior
- `PracticeGradingService.grade_attempt` half-point rounding + retry→`grading_failed`

Without these, regressions in the core batch-drill machinery won't be caught.

---

## Minor

### F2 — `TapToEliminateCapture` writes `-1` sentinel to answer state
**File:** `llm-frontend/src/components/practice/capture/TapToEliminateCapture.tsx:30`

When the student eliminates their currently-selected option, `onChange(-1 as number)` sets the answer to `-1`. This persists via `savePracticeAnswer` to `answers_json["q_idx"] = -1`. Grading treats `-1` as wrong (index bounds), and `_summarize_pick` produces `"(invalid index -1)"` — suboptimal for the rationale prompt.

**Fix:** Clear to `null`/`undefined` instead of `-1`. Requires adjusting the `CaptureProps<T>` contract to allow `onChange(null)` (or teaching the runner's answer store to treat a specific sentinel as cleared).

### F3 — `ChatSession.tsx:1082` passes URL slug as `topicTitle`
**File:** `llm-frontend/src/pages/ChatSession.tsx:1082`

```tsx
navigate(`/practice/${teachMeGuidelineId}`, {
  state: { topicTitle: topic, subject, chapter, topic },
});
```

The URL param `topic` is the slug (e.g. `"comparing-like-denominators"`), not the display title. `PracticeLandingPage` renders `topicTitle` as the heading, so the student sees the slug rather than "Comparing Like Denominators". Same pattern in `ModeSelectPage.tsx:131`.

**Fix:** Pass the actual display title from session state / TeachingGuideline.

### F4 — `ModeSelectPage.tsx:110` autostart doesn't await async handler
```tsx
autostartFiredRef.current = true;
navigate(location.pathname, { replace: true });
handleModeSelect('teach_me');  // not awaited
```

Works because all state/error handling is internal. If a sync throw ever occurs before `.catch` binds, it becomes an unhandled promise rejection. Defensive fix: `void handleModeSelect('teach_me').catch(() => {})` or wrap with explicit try.

### F5 — Dead method: `session_repository.py:240` `find_most_recent_completed_teach_me`
Grep returns only its own definition. Previously used by `_resolve_practice_context` (deleted in Step 12) for the FR-21 "context auto-attach". No callers remain. Delete.

### F6 — Stale comment in `session_service.py:1041-1043`
`_finalize_teach_me_session` docstring: *"a later Practice session (launched via the CTA or auto-attached) can read it as shared vocabulary via `source_state.precomputed_explanation_summary`"*. Practice is no longer a session; the handoff is a route navigate. The field itself is still consumed by `master_tutor.py:349/411/737` for subsequent teach_me turns, so the **write is still needed** — but the docstring's stated reason is obsolete.

### F7 — Stale docstring in `session_repository.py:269-297`
`_get_canonical_concepts` rationale: *"practice plans are subsets — so we anchor the coverage denominator on teach_me only to prevent denominator shrinkage when a struggle-weighted practice plan becomes the latest session."* Practice no longer creates sessions; the scenario is gone. Code behavior is still correct (teach_me-only is the right anchor) but the rationale is wrong.

### F8 — CSS class name `reportcard-exam-score` is now the practice chip
**File:** `llm-frontend/src/pages/ReportCardPage.tsx:84`

The exam chip was removed in Step 13; the practice chip reuses the class. Rename to `reportcard-practice-score` for clarity.

### F9 — N+1 API calls on `PracticeBankAdmin` mount
**File:** `llm-frontend/src/features/admin/pages/PracticeBankAdmin.tsx:213-220`

One `getPracticeBankJobStatus` call per topic on page load (to detect in-flight jobs to resume polling). A 20-topic chapter fires 20 parallel requests, most returning 404. A single bulk "latest jobs for chapter" endpoint would be cleaner.

### F10 — Silent exception swallow in `practice_bank_generator_service.py:330-340`
```python
except Exception as e:
    if "Cannot run" in str(e):
        raise
```

If `job_service.get_latest_job` fails with a transient DB error, the check silently passes and generation proceeds — missing a real conflict. Prefer narrow `try/except (NotFoundError,)` around the one fetch, or a `.first()` that returns `None` rather than raising.

### F11 — `retry_grading` lacks `SELECT FOR UPDATE`
**File:** `llm-backend/tutor/services/practice_service.py:169-181`

Unlike `submit`, `retry_grading` just reads and flips. Two simultaneous retry clicks could both see `grading_failed`, both flip to `grading`, both spawn workers. Workers are idempotent against the snapshot, but `grading_attempts` counter would double-increment. Low-probability race; plan doesn't explicitly require the lock here.

---

## Plan-deviation / cleanup

### P1 — Inconsistent LLM config seeds in `db.py`
**Files:** `db.py:81-84` (seed list) vs `db.py:750-756` (`_apply_practice_tables`)

`_LLM_CONFIG_SEEDS` has `practice_bank_generator` as `openai/gpt-5.2`. `_apply_practice_tables` inserts it as `claude_code/claude-opus-4-6` (the locked correction per impl-progress). In normal migration flow, `_ensure_llm_config` wins because it runs first and `_seed_llm_config` then sees non-empty table. Functionally correct; update the seed list for consistency so a future migration reordering doesn't silently seed the wrong provider.

### P2 — Dead ADD blocks in `db.py:208-216` `_apply_learning_modes_columns`
Still adds `exam_score` / `exam_total` columns if missing. `_cleanup_exam_and_old_practice_data` drops them later in the same migration. Fresh DB → redundant add+drop cycle. Existing DB → skipped then dropped. No functional bug, just leftover code. Delete.

### P3 — `sequence_items` not redacted
**File:** `llm-backend/tutor/services/practice_service.py:52-61` `REDACT_TOP_LEVEL_KEYS`

For the `sequence` format, the correct answer IS the original order of `sequence_items`. `REDACT_TOP_LEVEL_KEYS` omits `sequence_items`, so the raw (correct) order ships to the frontend. `SequenceCapture` mitigates visually via seeded shuffle, but the answer is present in the JSON response. Low practical risk for 9-year-olds; flag for rigor.

### P4 — FF correctness threshold deviates from plan
**File:** `llm-backend/tutor/services/practice_grading_service.py:47`

`FF_CORRECT_THRESHOLD = 0.75`. Plan §4.1 Pydantic comment says `correct: bool  # score >= 0.5 for display`. Unclear if intentional — 0.75 is a stricter pedagogical choice. Confirm with PRD author.

### P5 — Endpoint paths differ from plan §4.1
| Plan | Implementation |
|---|---|
| `POST /practice/attempts` | `POST /practice/start` |
| `GET /practice/topics/{gid}/availability` | `GET /practice/availability/{gid}` |
| `GET /practice/attempts?guideline_id=X` | `GET /practice/attempts/for-topic/{gid}` |

Frontend matches backend, so the system is consistent. Plan docs should be updated or these should be noted as locked deviations in `impl-progress.md`.

### P6 — `find_most_recent_completed_teach_me` dead code (duplicate of F5)

### P7 — Practice lock-key semantics
**File:** `llm-backend/book_ingestion_v2/api/sync_routes.py:1359, 1377`

For single-topic generation, `lock_chapter_id = guideline_id`. For chapter/book generation, `lock_chapter_id = chapter_id or book_id`. These are different keys — so a chapter-level job and a topic-level job for a topic in that chapter don't block each other via the lock. Admin UI gates concurrent generation, so the race is unlikely in practice, but the lock-scoping is looser than check-in enrichment's pattern.

---

## Verified solid (not issues)

- **Atomic submit** — `with_for_update()`, ownership + status guard, final-answer merge, commit-before-worker-spawn (`practice_service.py:125-167`)
- **Concurrent-tab race** — IntegrityError catch + re-read winner (`practice_service.py:101-107`)
- **Parallel LLM grading** — `ThreadPoolExecutor(max_workers=10)`, half-point rounding at write-time (`practice_grading_service.py:119-142`)
- **Snapshot isolation** — `_presentation_seed` injected once at attempt creation, stable on resume
- **Bank generator** — check_in_enrichment pattern; fail-open review-refine; top-up to 3 attempts; Q6 FF-count-0-3 applied
- **Capture components** — controlled, no TTS, no correctness styling, seed-stable `mulberry32` + Fisher-Yates, original indices preserved as values
- **Banner** — 30s poll, visibility-paused, `currentResultsId` filter, inline retry on `grading_failed`
- **AuthenticatedLayout** — above both AppShell + chat-session routes
- **Grep-gates** — backend (with documented exclusions for autoresearch data) + frontend both return 0 source-code matches
- **DB migration** — single `engine.begin()` transaction, events-first delete to satisfy FK RESTRICT
- **Scorecard** — Python merge (SQLite-portable), practice-only topics create rows, half-point render, pluralized attempt count
- **MatchPairs unpair/re-pair logic** — correctly handles "right already used by another left" via the `for k of next` cleanup loop
- **SwipeClassify cursor** — handles re-classify + resume correctly
- **`precomputed_explanation_summary`** — despite the stale comment (F6), still consumed by `master_tutor.py` for teach_me subsequent turns

---

## Recommendation

**Ship as-is after F1 + F12.** F1 is a genuine grade-correctness footgun that will surface in real student attempts. F12 is the single biggest durability risk for this large surface — commit at least the grading-determinism and lifecycle-transition tests so future refactors have a safety net. Everything else can land as follow-up PRs.
