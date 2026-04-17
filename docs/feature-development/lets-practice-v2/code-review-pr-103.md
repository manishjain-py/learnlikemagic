# Code Review: PR #103 — Let's Practice v2 (Steps 1–10)

**Reviewer:** Claude Code  
**Date:** 2026-04-17  
**PR:** feat/lets-practice-v2 (steps 1–10)

---

## Overview

Large, well-structured feature implementing batch drill practice from DB schema through frontend (6,981 additions, 51 files). Architecture is correct — practice is a separate REST system, not threaded through the tutor orchestrator. Key hard problems are handled well: snapshot isolation, atomic submit with `SELECT FOR UPDATE`, seed-stable shuffles, controlled capture components, partial unique index for concurrency safety.

---

## Must Fix Before Merge 🔴

### 1. `match_pairs` grading false-positive

**File:** `llm-backend/tutor/services/practice_grading_service.py:193`

```python
# Current — unsafe
return all(expected.get(k) == v for k, v in student_answer.items())

# Fix
return all(k in expected and expected[k] == v for k, v in student_answer.items())
```

`expected.get(k)` returns `None` for keys not in the dict. If a student submits a key not in `expected` with value `None`, the current code incorrectly grades it correct. The length check on line 191 doesn't fully protect against this because a student could submit keys that don't exist in `expected` and just happen to have `None` values.

---

### 2. `TapToEliminateCapture` emits `-1` as a valid answer

**File:** `llm-frontend/src/components/practice/capture/TapToEliminateCapture.tsx:30`

```tsx
// Current — -1 sentinel bleeds into answers_json
if (value === idx) onChange(-1 as number);

// Fix — clear the answer back to unanswered
if (value === idx) onChange(null as unknown as number);
```

When a student selects option `idx` and then eliminates it, `onChange(-1)` fires. The `-1` is stored in `answers_json` and shows up in grading review as `student_answer: -1`, which is misleading. The intent is "no answer selected", so `null` is correct.

---

### 3. Conflicting LLM seeds in `db.py` — fresh installs get wrong provider

**File:** `llm-backend/db.py:82–85`

```python
# Current in _LLM_CONFIG_SEEDS — WRONG
{
    "component_key": "practice_bank_generator",
    "provider": "openai",
    "model_id": "gpt-5.2",
    ...
},

# Fix — must match _apply_practice_tables()
{
    "component_key": "practice_bank_generator",
    "provider": "claude_code",
    "model_id": "claude-opus-4-6",
    ...
},
```

`_LLM_CONFIG_SEEDS` seeds `practice_bank_generator` as `openai/gpt-5.2`, but `_apply_practice_tables()` (line 747) correctly seeds it as `claude_code/claude-opus-4-6`. On a **fresh DB install**, `_seed_llm_config` runs first (inserts `openai/gpt-5.2`), then `_ensure_llm_config` runs as "insert if missing" — the row already exists, so the final config is `openai/gpt-5.2`. Existing deployments get the correct value; fresh installs do not.

---

### 4. FR-17 not implemented — free-form questions not prioritised in `_select_set`

**File:** `llm-backend/tutor/services/practice_service.py` — `_select_set()` method

The tech plan (§FR-17) requires: *"all free-form questions absorbed first; they reduce the quota for their difficulty tier."* The actual implementation buckets free-form questions alongside structured ones by difficulty. A bank heavy in structured `easy` questions may never include its free-form questions.

The plan's required logic:
```python
free_form = [q for q in bank if q.format == "free_form"]
structured = [q for q in bank if q.format != "free_form"]
quota = {"easy": 3, "medium": 5, "hard": 2}
for q in free_form:
    quota[q.difficulty] = max(0, quota[q.difficulty] - 1)
picked = _pick_with_variety(structured, quota)
chosen = free_form + picked
```

---

### 5. Verify admin bank endpoints are authentication-guarded

**File:** `llm-backend/book_ingestion_v2/api/sync_routes.py:1328, 1405, 1456, 1479`

The four new practice bank endpoints (`POST /generate-practice-banks`, `GET /practice-bank-status`, `GET /practice-bank-jobs/latest`, `GET /practice-banks/{guideline_id}`) have no `current_user = Depends(get_current_user)` guards. All sibling admin routes in this file follow the same pattern — no per-route auth. Confirm the router is protected at the `APIRouter` or middleware level; if not, unauthenticated users can trigger expensive LLM generation jobs.

---

## Should Fix 🟡

### 6. `SwipeClassifyCapture` stale-closure cursor desync

**File:** `llm-frontend/src/components/practice/capture/SwipeClassifyCapture.tsx:40`

```tsx
// Current — cursor is stale inside classify() when undo fires
const nextCursor = deck.findIndex((o, i) => i > cursor && ...);
```

When the student uses "undo re-classify", `setCursor(deckIdx)` fires but the `classify` closure still reads the old `cursor` value (classic React stale closure). Fix: derive cursor from the `value` state on each render rather than tracking it as separate state, or use the functional updater form.

---

### 7. `_check_no_conflicting_jobs` swallows DB exceptions

**File:** `llm-backend/book_ingestion_v2/services/practice_bank_generator_service.py:338–340`

```python
# Current — swallows all non-conflict exceptions
except Exception as e:
    if "Cannot run" in str(e):
        raise

# Fix — only catch the specific conflict RuntimeError
except RuntimeError:
    raise
```

A transient DB error in `get_latest_job` silently skips the conflict check and allows a duplicate generation job to start.

---

### 8. `SequenceList` uses unstable React keys

**File:** `llm-frontend/src/components/shared/SequenceList.tsx:28`

```tsx
// Current — index in key defeats reconciliation during reorder
<div key={`${i}:${item}`} className="practice-seq-row">

// Fix — item text is unique per generator validation
<div key={item} className="practice-seq-row">
```

Using the array index as part of the key means React associates the new item at position 0 with the old item at position 0 after reorder, defeating reconciliation. Since the bank generator deduplicates sequence items, `key={item}` is safe.

---

### 9. `PracticeResultsPage` has no poll timeout for stuck-in-grading attempts

**File:** `llm-frontend/src/pages/PracticeResultsPage.tsx:61–77`

The polling loop (2s interval) has no maximum iteration count or timeout. The impl-progress acknowledges "silent thread death leaves attempt stuck in `grading` indefinitely" as a v1 known limitation. Without a timeout, the page polls forever for stuck attempts. Add a 5-minute cap (150 polls × 2s) and surface a "grading is taking longer than expected" message with a Retry button.

---

## Plan Deviations (acknowledged)

| Deviation | File | Notes |
|-----------|------|-------|
| API paths changed (`/practice/start` vs `/practice/attempts`) | `tutor/api/practice.py` | Frontend + backend internally consistent; plan contract deviated |
| `PracticeHistoryPage` / `PracticeReviewPage` folded into existing pages | — | Acknowledged scope reduction in impl-progress |
| `PracticeBankEmptyError` maps to HTTP 409 | `tutor/api/practice.py` | Semantically incorrect; 404 or 503 would be better |
| Banner tap → Results page has no Reteach CTA | `PracticeResultsPage.tsx` | Known limitation; topic-path state not available from banner nav |

---

## Code Quality Observations

| # | File | Issue |
|---|------|-------|
| Q1 | `practice_grading_service.py`, `practice_bank_generator_service.py` | Chained `.replace()` for prompt templates is injection-unsafe if question text contains `{placeholder}` patterns — use a single `str.format_map()` pass |
| Q2 | `practice_service.py` `_select_set` | FR-19 (≥4 distinct formats) logs a warning but doesn't enforce; a narrow bank silently violates the spec |
| Q3 | `practice_service.py` `_spawn_grading_worker` | Deferred imports inside thread function are a code smell; if `practice_grader` config is ever switched to `claude_code`, confirm `LLMService` strips `ANTHROPIC_API_KEY` per CLAUDE.md |
| Q4 | `practice_attempt_repository.py` `save_answer` | SELECT + UPDATE on every debounced save; for future scaling, a JSONB merge update would be more efficient |
| Q5 | `sync_routes.py` `get_practice_bank_status` | N+1 COUNT queries (one per topic); replace with a single `GROUP BY guideline_id` aggregate |

---

## Verdict

**Conditionally approvable.** The implementation is solid and production-ready for most flows. The architecture is correct and the hard concurrency/isolation problems are well-solved.

**5 must-fix items** (items 1–5 above) before merge.  
**4 should-fix items** (items 6–9) are non-blocking but recommended.  
**Steps 11–14** (Scorecard, destructive cleanup, docs) are out of scope for this PR as expected.
