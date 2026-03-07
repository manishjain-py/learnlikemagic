# Tutor Improve — Phase 1: Analysis

You are running Phase 1 (Analysis) of the master tutor improvement initiative. This phase produces a detailed analysis document for human review. **No code changes are made.**

**Reference:** Read `docs/technical/evaluation.md` and `tutor-improvement/README.md` for context.

---

## Input

**Input arguments format:** `initiative_id: <INIT-XXX-name> feedback: "<feedback text>"`

Parse the arguments to extract:
- `initiative_id` — e.g., `INIT-001-praise-calibration`
- `feedback` — the user's specific feedback about what the tutor does wrong

---

## Process

### Step 1: Create initiative folder

Create `tutor-improvement/initiatives/<initiative_id>/` and save the raw feedback:

```
tutor-improvement/initiatives/<initiative_id>/feedback.md
```

Contents:
```markdown
# Feedback — <initiative_id>

**Date:** <today>

## Raw Feedback

> <feedback text verbatim>
```

### Step 2: Deep-read master tutor code

Read ALL of these files thoroughly:
- `llm-backend/tutor/agents/master_tutor.py`
- `llm-backend/tutor/prompts/master_tutor_prompts.py`
- `llm-backend/tutor/orchestration/orchestrator.py`
- `llm-backend/tutor/prompts/orchestrator_prompts.py`
- `llm-backend/tutor/models/session_state.py`
- `llm-backend/tutor/services/session_service.py`

### Step 3: Analyze feedback against architecture

Think deeply about:
1. Which parts of the code are responsible for the reported behavior?
2. What is the root cause? (prompt gap, wrong prioritization, missing logic, etc.)
3. What specific changes would fix it?
4. What could break if we change this?

### Step 4: Produce analysis document

Create `tutor-improvement/initiatives/<initiative_id>/phase1-analysis.md` using the template at `tutor-improvement/templates/phase1-analysis.md`.

Fill in ALL sections:
- **Feedback Summary** — what's reported
- **Current Behavior** — how the code handles this today (with `file:line` references)
- **Root Cause Hypothesis** — why it happens
- **Proposed Change Strategy** — what to modify and how
- **Impact Prediction** — High/Medium/Low with rationale
- **Risk Assessment** — what could regress
- **Recommendation** — PROCEED / SKIP / NEEDS-DISCUSSION with reasoning

### Step 5: Update index

Update `tutor-improvement/index.md` — add a row for this initiative with status "Phase 1 Complete".

### Step 6: Report to user

Output the analysis summary and tell the user to review `phase1-analysis.md` before proceeding to Phase 2.
