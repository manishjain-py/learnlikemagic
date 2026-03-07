# Tutor Improve — Phase 2: Implementation

You are running Phase 2 (Implementation) of the master tutor improvement initiative. This phase implements the changes proposed in Phase 1.

**Reference:** Read `docs/technical/evaluation.md` and `tutor-improvement/README.md` for context.

---

## ENVIRONMENT SETUP

**All Python commands MUST use the project virtual environment.** The venv is at `llm-backend/venv` (NOT `.venv`).

For every `python` or `python -m` command, use:
```bash
cd llm-backend && source venv/bin/activate && python ...
```

Do NOT use bare `python` or `python3` — the system Python lacks project dependencies.

---

## Input

**Input arguments format:** `initiative_id: <INIT-XXX-name>`

---

## Process

### Step 1: Read Phase 1 analysis

Read `tutor-improvement/initiatives/<initiative_id>/phase1-analysis.md`.

**Gate check:** If the recommendation is SKIP or NEEDS-DISCUSSION, inform the user and stop. Only proceed if recommendation is PROCEED.

### Step 2: Create branch

```bash
git checkout main && git pull origin main
git checkout -b tutor-improve/<initiative_id>
```

### Step 3: Implement changes

Follow the Proposed Change Strategy from Phase 1. Key guardrails:

- The **master tutor LLM prompt** is the most sensitive file. Treat it like surgery — small, precise changes only.
- Do NOT bloat the prompt. If adding instructions, consider removing or consolidating less effective ones.
- Do NOT break what's already working well.
- Prefer changes that fix root causes, not symptoms.
- Keep changes minimal and focused — ideally touching 1-3 files max.

### Step 4: Self code-review

Review your changes against the Phase 1 risk assessment. Check:
- Does this address the root cause?
- Could this cause any of the predicted regressions?
- Are changes minimal and focused?

Fix any issues found.

### Step 5: Run tests

```bash
cd llm-backend && source venv/bin/activate && python -m pytest tests/ -x -q
```

If tests fail, fix before proceeding.

### Step 6: Produce implementation document

Create `tutor-improvement/initiatives/<initiative_id>/phase2-implementation.md` using the template at `tutor-improvement/templates/phase2-implementation.md`.

Fill in ALL sections:
- Files changed with summary
- Diffs summary
- Code review findings
- Test results
- Deviations from Phase 1 plan (if any)

### Step 7: Commit

Stage all changes and commit:
```bash
git add -A
git commit -m "tutor-improve(<initiative_id>): <concise description of changes>"
```

### Step 8: Update index

Update `tutor-improvement/index.md` — set this initiative's status to "Phase 2 Complete".

### Step 9: Report to user

Output a summary of what was changed and tell the user to proceed to Phase 3 (`/tutor-improve-measure`) when ready.
