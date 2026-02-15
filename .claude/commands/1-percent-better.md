# 1% Better — Iterative Tutor Improvement Loop

You are running a measure → analyze → fix → measure → compare cycle to improve the tutor.

**Reference:** Read `docs/EVALUATION_PIPELINE.md` for full pipeline details before starting.

---

## AUTOMATION DIRECTIVE

This is a **fully automated pipeline**. The user will NOT be present to review plans, approve decisions, or give go-ahead between steps.

- **Do NOT** use `EnterPlanMode` or `AskUserQuestion` at any point.
- **Do NOT** pause for user confirmation between steps.
- Make all decisions autonomously based on the data (evaluation scores, problems, root causes).
- Execute every step end-to-end without stopping.
- If something fails (tests, evaluation run), attempt to fix it yourself and retry. Only stop if you've exhausted reasonable recovery attempts (3 max).
- Log all decisions and rationale to the progress file (Step 0) so the user can review after the fact.

---

## Step 0: Create a json file in the root folder $ARGUMENTS.log. Keep updating the status/progress to this file. Anyone looking at this file should understand what is done, and what's going on currently and what's planned next.

---

## Step 1: Find an available topic

```bash
cd llm-backend
python -c "
from evaluation.config import EvalConfig
# List available guideline/topic IDs from the database or config
"
```

---

## Step 2: Run BASELINE evaluation (before any changes)

Run against **Struggler** and **Ace** personas (two extremes of student ability):

```bash
cd llm-backend
python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona struggler.json --skip-server
python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona ace.json --skip-server
```

Add skip-server flag only if the backend is running locally.
Save the run directory names — you'll need them for comparison in Step 6.

---

## Step 3: Analyze the results

Read the generated reports:
- `evaluation/runs/run_*_struggler/review.md` — overall evaluation
- `evaluation/runs/run_*_struggler/problems.md` — specific problems with root causes
- `evaluation/runs/run_*_ace/review.md`
- `evaluation/runs/run_*_ace/problems.md`

Focus on:
1. Which dimensions scored lowest?
2. What are the root causes? (e.g., `missed_student_signal`, `wrong_pacing`, `repetitive_approach`)
3. Are there patterns across both personas?
4. Which problems are `critical` or `major` severity?

---

## Step 4: Plan targeted improvements

Think deeply about what changes would address the identified problems.

**Critical guardrails:**
- The **master tutor LLM prompt** is the most sensitive file. Treat it like surgery — small, precise changes only.
- Do NOT bloat the prompt. If adding instructions, consider removing or consolidating less effective ones.
- Do NOT break what's already working well (for example, high-scoring dimensions).
- Prefer changes that fix root causes, not symptoms.
- Keep changes minimal and focused — ideally touching 1-3 files max.

---

## Step 5: Implement and verify

1. Make the planned code changes.
2. Do a self code review to ensure nothing is broken. Do correction if needed.
3. Run the existing test suite to make sure nothing is broken:
   ```bash
   cd llm-backend && python -m pytest tests/ -x -q
   ```
4. If tests fail, fix before proceeding.

---

## Step 6: Run POST-CHANGE evaluation

Run the same evaluation as Step 2 (same topic, same personas):

```bash
cd llm-backend
python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona struggler.json --skip-server
python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona ace.json --skip-server
```

---

## Step 7: Compare and report

Read both the BASELINE (Step 2) and POST-CHANGE (Step 6) reports. Output a comparison:

```
## 1% Better — Comparison Report

### Scores (Before → After)
| Dimension           | Struggler Before | Struggler After | Ace Before | Ace After |
|---------------------|-----------------|-----------------|------------|-----------|
| Responsiveness      |                 |                 |            |           |
| Explanation Quality  |                 |                 |            |           |
| Emotional Attunement |                 |                 |            |           |
| Pacing              |                 |                 |            |           |
| Authenticity         |                 |                 |            |           |
| **Average**         |                 |                 |            |           |

### What improved?
(list specific improvements with evidence)

### What regressed?
(list any regressions — this is critical to flag)

### Problems resolved?
(map original problems to whether they're fixed)

### Verdict: KEEP / REVERT / PARTIAL
```

**If scores regressed overall:** Recommend reverting the changes and explain why. Do NOT keep changes that make things worse.
