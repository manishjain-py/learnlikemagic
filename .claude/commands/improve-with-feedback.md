# Improve with Feedback — User-Driven Tutor Fix Loop

You are running a feedback → persona → fix → evaluate → review cycle to improve the tutor based on real user feedback.

**Reference:** Read `docs/EVALUATION_PIPELINE.md` for full pipeline details before starting.

---

## ENVIRONMENT SETUP

**All Python commands MUST use the project virtual environment.** The venv is at `llm-backend/venv` (NOT `.venv`).

For every `python` or `python -m` command in this pipeline, use:
```bash
cd llm-backend && source venv/bin/activate && python ...
```

Or use the full path: `llm-backend/venv/bin/python`

Do NOT use bare `python` or `python3` — the system Python lacks project dependencies.

---

**Input arguments format:** `logfilename: <path> feedback: <user's feedback text>`

Parse the arguments to extract:
- `logfilename` — name for the progress/status log file (used in Step 0)
- `feedback` — the user's specific feedback about what went wrong (expect 1-2 focused issues)

---

## AUTOMATION DIRECTIVE

This is a **fully automated pipeline**. The user will NOT be present to review plans, approve decisions, or give go-ahead between steps.

- **Do NOT** use `EnterPlanMode` or `AskUserQuestion` at any point.
- **Do NOT** pause for user confirmation between steps.
- Make all decisions autonomously based on the user's feedback.
- Execute every step end-to-end without stopping.
- If something fails (tests, evaluation run), attempt to fix it yourself and retry. Only stop if you've exhausted reasonable recovery attempts (3 max).
- Log all decisions and rationale to the progress file (Step 0) so the user can review after the fact.

---

## Step 0: Create progress log

Create a json file in the root folder using the `logfilename` argument value (e.g., `<logfilename>.log`). Keep updating the status/progress to this file. Anyone looking at this file should understand what is done, what's going on currently, and what's planned next.

---

## Step 0.5: Create a new branch from latest main

```bash
git checkout main && git pull origin main
git checkout -b improve-with-feedback/$(date +%Y%m%d-%H%M%S)
```

All changes in this run will be committed to this branch.

---

## Step 1: Analyze the feedback

Read the user's `feedback` carefully.

Extract:
1. **Find an available topic** — pick a suitable topic/guideline ID from the evaluation config to run the evaluation against.
2. **Root cause hypothesis** — why might the tutor behave this way? (e.g., prompt gap, missing instruction, wrong prioritization). Read the tutor prompt and relevant code to form your hypothesis.
3. **Behavioral signals** — what student actions or requests would trigger the problematic tutor behavior?

Log your analysis to the progress file.

---

## Step 2: Create a custom student persona

Based on the feedback analysis, create a new student persona JSON file under `llm-backend/evaluation/personas/` that is specifically designed to reproduce the reported issues.

**Key principles:**
- The persona should exhibit the exact behavioral signals identified in Step 1.
- For example, if the user reported "tutor doesn't simplify when asked", the persona should be a student who frequently asks for simpler explanations.
- If the user reported "tutor moves too fast", the persona should be a student who needs more time and asks to slow down.
- The persona should be realistic — don't make it a caricature. It should behave like a real student who would naturally trigger the problematic tutor behavior.
- Name the persona descriptively (e.g., `simplification_seeker.json`, `slow_pace_learner.json`).

Log the persona design rationale to the progress file.

---

## Step 3: Plan targeted improvements

Think deeply about what changes would address the user's feedback.

**Critical guardrails:**
- The **master tutor LLM prompt** is the most sensitive file. Treat it like surgery — small, precise changes only.
- Do NOT bloat the prompt. If adding instructions, consider removing or consolidating less effective ones.
- Do NOT break what's already working well.
- Prefer changes that fix root causes, not symptoms.
- Keep changes minimal and focused — ideally touching 1-3 files max.
- Remember: we're addressing only 1-2 specific feedback items, so changes should be tightly scoped.

---

## Step 4: Implement and verify

1. Make the planned code changes.
2. Do a self code review to ensure nothing is broken. Do correction if needed.
3. Run the existing test suite to make sure nothing is broken:
   ```bash
   cd llm-backend && source venv/bin/activate && python -m pytest tests/ -x -q
   ```
4. If tests fail, fix before proceeding.

---

## Step 5: Run evaluation with custom persona

Run the evaluation using the topic identified in Step 1 and the custom persona created in Step 2:

```bash
cd llm-backend && source venv/bin/activate
python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona <CUSTOM_PERSONA>.json --skip-server
```

Add `--skip-server` flag only if the backend is running locally.
Save the run directory name for the review in Step 6.

---

## Step 6: Review and report

Read the generated evaluation artifacts:
- The full simulated conversation transcript
- `evaluation/runs/run_*/review.md`
- `evaluation/runs/run_*/problems.md`

Produce a review report focused on whether the user's original feedback has been addressed:

```
## Improve with Feedback — Review Report

### User Feedback
(quote the original feedback verbatim)

### Root Cause Analysis
(what was causing the reported behavior)

### Changes Made
(list files changed and what was modified)

### Custom Persona
(describe the persona created and why)

### Evaluation Scores
| Dimension            | Score |
|----------------------|-------|
| Responsiveness       |       |
| Explanation Quality  |       |
| Emotional Attunement |       |
| Pacing               |       |
| Authenticity         |       |
| **Average**          |       |

### Feedback-Specific Assessment
For each feedback item:
- **Feedback:** <original feedback>
- **Addressed?** YES / PARTIALLY / NO
- **Evidence:** <specific moments from the simulated conversation that show whether the issue is fixed>

### Other Observations
(any new issues spotted in the simulated conversation, positive or negative)

### Verdict: ADDRESSED / PARTIALLY ADDRESSED / NOT ADDRESSED
```

**If the feedback is not addressed:** Do NOT revert the changes. Report clearly so the user can decide. All changes stay on the branch for review.

---

## Step 7: Email the final report

Send the review report (nicely formatted html report) from Step 6 via macOS Mail.app. The email subject should include the branch name and verdict.

```bash
BRANCH=$(git branch --show-current)
```

Then use AppleScript to send the email with the log file attached:

```bash
LOGFILE="$(pwd)/<LOGFILENAME>.log"

osascript -e '
tell application "Mail"
    set newMessage to make new outgoing message with properties {subject:"Improve with Feedback Report — '"$BRANCH"' — <VERDICT>", content:"<FULL_REVIEW_REPORT_FROM_STEP_6>", visible:false}
    tell newMessage
        make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
        make new attachment with properties {file name:POSIX file "'"$LOGFILE"'"} at after the last paragraph
    end tell
    send newMessage
end tell'
```

Replace `<VERDICT>` with the actual verdict (ADDRESSED / PARTIALLY ADDRESSED / NOT ADDRESSED), `<FULL_REVIEW_REPORT_FROM_STEP_6>` with the full review report text generated in Step 6, and `<LOGFILENAME>` with the `logfilename` argument value.
