# Tutor Improve — Phase 2.5: Code Review

You are running Phase 2.5 (Code Review) of the master tutor improvement initiative. This phase reviews the Phase 2 implementation for functional correctness and regression risks. **No code changes are made** — this is purely a review that produces a structured report.

---

## Input

**Input arguments format:** `initiative_id: <INIT-XXX-name>`

---

## Process

### Step 1: Load context

Read these files to understand intent and constraints:
- `tutor-improvement/initiatives/<initiative_id>/feedback.md` — what problem we're solving
- `tutor-improvement/initiatives/<initiative_id>/phase1-analysis.md` — root cause, proposed strategy, risk assessment
- `tutor-improvement/initiatives/<initiative_id>/phase2-implementation.md` — what was changed and why

### Step 2: Identify all changed files

Run `git diff main --name-only` (or read the Phase 2 implementation doc) to get the list of changed files.

Read **every changed file in full** — you need complete context, not just diffs.

### Step 3: Read the diffs

Run `git diff main` to see the exact changes. Study each diff carefully.

### Step 4: Review for functional correctness

For each changed file, check:

1. **Logic errors** — Off-by-one, wrong conditions, missing null checks, incorrect state transitions
2. **Edge cases** — What happens on empty input, None values, disconnects, timeouts, concurrent access?
3. **Type safety** — Are types consistent? Could a None slip through where a value is expected?
4. **Error handling** — Are exceptions caught appropriately? Could errors be silently swallowed?
5. **Escape hatches** — Are there code paths that bypass the new logic and fall back to old behavior? Are those fallbacks correct?
6. **Data flow** — Does data flow correctly through the new code? Are all producers matched with consumers?
7. **Async correctness** — For async code: are there race conditions, missing awaits, stale closures, or thread-safety issues?
8. **String/encoding** — For parsers/extractors: are all escape sequences handled? What about unicode, empty strings, malformed input?

### Step 5: Review for regression risks

Check whether the changes could break existing functionality:

1. **Existing callers** — Do all existing callers of modified functions still work? Are return types/signatures preserved?
2. **State management** — Could the changes cause state to be lost, duplicated, or corrupted?
3. **Logging/observability** — Is logging parity maintained between old and new code paths?
4. **API contract** — Do REST/WebSocket responses still match the expected contract?
5. **Frontend/backend alignment** — If both sides changed, are message formats consistent?
6. **Test coverage** — Are the changes covered by existing tests? Are new edge cases untested?
7. **Performance** — Could the changes introduce latency, memory leaks, or excessive API calls?

### Step 6: Check against Phase 1 risks

Re-read the Risk Assessment from `phase1-analysis.md`. For each predicted risk:
- Was it mitigated?
- Was the mitigation correct?
- Were there unforeseen risks that Phase 1 missed?

### Step 7: Produce the review document

Create `tutor-improvement/initiatives/<initiative_id>/phase2.5-review.md` with this structure:

```markdown
# Phase 2.5: Code Review — <initiative_id>

**Date:** <today>
**Reviewer:** Claude Code
**Files reviewed:** <count>

---

## Functional Correctness Issues

For each issue found:

### Issue N: <title> — <file:line>

<description of the problem>

**Severity:** Critical / Medium / Low
**Fix:** <what should change>

---

## Regression Risks

For each risk found:

### Risk N: <title> — <file:line>

<description of the regression risk>

**Severity:** Critical / Medium / Low — <impact description>

---

## Phase 1 Risk Assessment Check

| Predicted Risk | Mitigated? | Notes |
|---------------|------------|-------|
| ... | Yes/No/Partial | ... |

---

## Things Done Well

Bullet list of things the implementation got right — good patterns, correct edge case handling, etc.

---

## Verdict

**PASS** / **PASS WITH FIXES** / **FAIL**

### Required Fixes (before merge)

Numbered list of issues that must be fixed. Reference the issue numbers above.

### Recommended Fixes (non-blocking)

Numbered list of improvements that should be done but don't block merge.
```

### Step 8: Update index

Update `tutor-improvement/index.md` — set this initiative's status to "Phase 2.5 Complete — <VERDICT>".

### Step 9: Report to user

Output:
1. The verdict (PASS / PASS WITH FIXES / FAIL)
2. Count of issues by severity
3. Required fixes summary (if any)
4. Tell the user to review `phase2.5-review.md` and then either fix issues or proceed to Phase 3 (`/tutor-improve-measure`)
