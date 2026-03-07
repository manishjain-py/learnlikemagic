# Tutor Improve — Phase 3: Measurement & Report

You are running Phase 3 (Measurement) of the master tutor improvement initiative. This phase runs before/after evaluations and produces a scored report with a verdict.

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

## AUTOMATION DIRECTIVE

This is a **fully automated pipeline** after it starts. The user will NOT be present to review plans or give go-ahead between steps.

- **Do NOT** use `EnterPlanMode` or `AskUserQuestion` at any point.
- **Do NOT** pause for user confirmation between steps.
- Execute every step end-to-end without stopping.
- If something fails, attempt to fix and retry (3 max). Only stop if recovery is exhausted.

---

## Input

**Input arguments format:** `initiative_id: <INIT-XXX-name>`

---

## Process

### Step 1: Read context

Read Phase 1 and Phase 2 docs:
- `tutor-improvement/initiatives/<initiative_id>/phase1-analysis.md`
- `tutor-improvement/initiatives/<initiative_id>/phase2-implementation.md`

Extract the topic ID to use for evaluation (from Phase 1 analysis or pick a suitable one from eval config).

### Step 2: Find a topic for evaluation

```bash
cd llm-backend && source venv/bin/activate
python -c "
from evaluation.config import EvalConfig
# List available guideline/topic IDs
"
```

Pick a topic that is relevant to the feedback being tested.

### Step 3: Run evaluations in parallel

Use the **Agent tool** to run baseline and post-change evaluations simultaneously:

**Agent A (baseline — worktree on main):**
1. Create a git worktree: `git worktree add ../learnlikemagic-baseline main`
2. Run 3 eval sessions (struggler, average, ace) from the worktree:
   ```bash
   cd ../learnlikemagic-baseline/llm-backend && source venv/bin/activate
   python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona struggler.json --skip-server
   python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona average_student.json --skip-server
   python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona ace.json --skip-server
   ```
3. Copy the run directories to `tutor-improvement/initiatives/<initiative_id>/baseline-conversations/`
4. Clean up worktree: `git worktree remove ../learnlikemagic-baseline`

**Agent B (post-change — current branch):**
1. Run 3 eval sessions (struggler, average, ace) from current branch:
   ```bash
   cd llm-backend && source venv/bin/activate
   python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona struggler.json --skip-server
   python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona average_student.json --skip-server
   python -m evaluation.run_evaluation --topic-id <TOPIC_ID> --persona ace.json --skip-server
   ```
2. Copy the run directories to `tutor-improvement/initiatives/<initiative_id>/post-change-conversations/`

**Important:** Both agents need the backend server running. Start it before dispatching agents if `--skip-server` is not appropriate. Use `--skip-server` if the server is already running.

### Step 4: Collect and compare scores

After both agents complete:
1. Read all evaluation JSONs from baseline and post-change runs
2. Extract scores per dimension per persona
3. Calculate deltas

### Step 5: Produce measurement report

Create `tutor-improvement/initiatives/<initiative_id>/phase3-report.md` using the template at `tutor-improvement/templates/phase3-report.md`.

Fill in ALL sections:
- End-to-end summary
- Before/after score tables (per persona, per dimension)
- Key conversation evidence (excerpts showing the issue before vs. after)
- Feedback-specific assessment
- Improvement score (average delta)
- Confidence level (High/Medium/Low)
- Verdict: SHIP / REVERT / NEEDS-MORE-DATA

### Step 6: Generate HTML report

Save the report as `tutor-improvement/initiatives/<initiative_id>/phase3-report.html` — a well-structured HTML document with proper styling for readability.

### Step 7: Email the report

```bash
BRANCH=$(git branch --show-current)
REPORT_FILE="$(pwd)/tutor-improvement/initiatives/<initiative_id>/phase3-report.html"

osascript -e '
tell application "Mail"
    set newMessage to make new outgoing message with properties {subject:"Tutor Improvement Report — <initiative_id> — <VERDICT>", content:"See attached HTML report.", visible:false}
    tell newMessage
        make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
        make new attachment with properties {file name:POSIX file "'"$REPORT_FILE"'"} at after the last paragraph
    end tell
    send newMessage
end tell'
```

Replace `<VERDICT>` with the actual verdict and `<initiative_id>` with the real ID.

### Step 8: Update index

Update `tutor-improvement/index.md` — set this initiative's status to the final verdict (SHIP / REVERT / NEEDS-MORE-DATA) with scores.
