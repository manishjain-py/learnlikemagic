# E2E Runner — Full App E2E Testing Pipeline

Run the full application locally, execute all E2E test scenarios via Playwright, capture screenshots of every flow, visually inspect each screen, and produce a comprehensive HTML QA report with email delivery.

## Input
- Optional `$ARGUMENTS` = report slug
- Default slug: `e2e-runner-$(date +%Y%m%d-%H%M%S)`

## ENVIRONMENT SETUP

**All Python commands MUST use the project virtual environment.** The venv is at `llm-backend/venv` (NOT `.venv`).

```bash
cd llm-backend && source venv/bin/activate && python ...
```

## AUTOMATION DIRECTIVE

This is a **fully automated pipeline**. The user will NOT be present to review plans, approve decisions, or give go-ahead between steps.

- **Do NOT** use `EnterPlanMode` or `AskUserQuestion` at any point.
- **Do NOT** pause for user confirmation between steps.
- Make all decisions autonomously.
- Execute every step end-to-end without stopping.
- If something fails, attempt to fix and retry (3 max).
- Log all decisions and rationale to the progress file so the user can review after the fact.

---

## Step 0: Initialize

```bash
SLUG="${ARGUMENTS:-e2e-runner-$(date +%Y%m%d-%H%M%S)}"
ROOT="$(pwd)"
REPORT_DIR="$ROOT/reports/e2e-runner"
SCREENSHOT_DIR="$REPORT_DIR/screenshots"
mkdir -p "$SCREENSHOT_DIR"
LOG_FILE="$REPORT_DIR/${SLUG}.log"
PROGRESS_FILE="$REPORT_DIR/${SLUG}.progress.json"
SUMMARY_HTML="$REPORT_DIR/${SLUG}.html"

BRANCH="$(git -C "$ROOT" branch --show-current)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
NOW="$(date '+%Y-%m-%d %H:%M:%S %Z')"

echo "[$NOW] e2e-runner started on $BRANCH@$COMMIT" | tee "$LOG_FILE"
echo '{"status":"running","step":"init","branch":"'"$BRANCH"'","commit":"'"$COMMIT"'","started":"'"$NOW"'"}' > "$PROGRESS_FILE"
```

Keep `$PROGRESS_FILE` updated with current status/step as the pipeline progresses.

---

## Step 0b: Install dependencies and Playwright browsers

```bash
# Frontend deps (only if node_modules is missing or stale)
cd "$ROOT/llm-frontend"
if [ ! -d node_modules ]; then
  echo "Installing frontend deps..." | tee -a "$LOG_FILE"
  npm ci 2>/dev/null || npm install
fi

# E2E deps
cd "$ROOT/e2e"
if [ ! -d node_modules ]; then
  echo "Installing e2e deps..." | tee -a "$LOG_FILE"
  npm ci 2>/dev/null || npm install
fi

# Playwright: install chromium if not already installed
if ! npx playwright install --dry-run chromium 2>/dev/null | grep -q "already installed"; then
  echo "Installing Playwright chromium..." | tee -a "$LOG_FILE"
  npx playwright install chromium
fi
```

---

## Step 1: Start the backend server

Set up trap-based cleanup so servers are always killed on exit or error:

```bash
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo "Cleaning up servers..." | tee -a "$LOG_FILE"
  [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null && echo "Backend stopped"  | tee -a "$LOG_FILE"
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "Frontend stopped" | tee -a "$LOG_FILE"
}
trap cleanup EXIT

cd "$ROOT/llm-backend" && source venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000 >> "$LOG_FILE" 2>&1 &
BACKEND_PID=$!
echo "Backend started with PID $BACKEND_PID" | tee -a "$LOG_FILE"

# Wait for backend to be ready (up to 60s)
BACKEND_READY=0
for i in $(seq 1 30); do
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "Backend is ready after ${i}x2s" | tee -a "$LOG_FILE"
    BACKEND_READY=1
    break
  fi
  sleep 2
done

if [ "$BACKEND_READY" -eq 0 ]; then
  echo "ERROR: Backend not ready after 60s. Check $LOG_FILE for details." | tee -a "$LOG_FILE"
  echo "Hints: port 8000 in use? missing .env? uvicorn crash? Run: lsof -i :8000" | tee -a "$LOG_FILE"
  exit 1
fi
```

---

## Step 2: Start the frontend dev server

```bash
cd "$ROOT/llm-frontend"
npm run dev >> "$LOG_FILE" 2>&1 &
FRONTEND_PID=$!
echo "Frontend started with PID $FRONTEND_PID" | tee -a "$LOG_FILE"

# Wait for frontend to be ready (up to 60s)
FRONTEND_READY=0
for i in $(seq 1 30); do
  if curl -s http://localhost:5173 > /dev/null 2>&1; then
    echo "Frontend is ready after ${i}x2s" | tee -a "$LOG_FILE"
    FRONTEND_READY=1
    break
  fi
  sleep 2
done

if [ "$FRONTEND_READY" -eq 0 ]; then
  echo "ERROR: Frontend not ready after 60s. Check $LOG_FILE for details." | tee -a "$LOG_FILE"
  echo "Hints: port 5173 in use? missing node_modules? Run: lsof -i :5173" | tee -a "$LOG_FILE"
  exit 1
fi
```

---

## Step 3: Run Playwright E2E tests

```bash
cd "$ROOT/e2e"
npx playwright test --reporter=list,json,html 2>&1 | tee -a "$LOG_FILE"
E2E_EXIT=${PIPESTATUS[0]}
echo "E2E tests exited with code $E2E_EXIT" | tee -a "$LOG_FILE"
```

This executes all scenarios from `e2e/scenarios.json`, capturing screenshots at every labeled step. Failed tests automatically get a failure screenshot.

After Playwright completes, read:
- `reports/e2e-runner/scenario-results.json` — per-scenario pass/fail with screenshot filenames
- `reports/e2e-runner/test-results.json` — Playwright's full JSON report

---

## Step 4: Visual inspection with Claude

**This is the key differentiator.** After Playwright finishes, read EVERY screenshot from `$SCREENSHOT_DIR` using the Read tool (which can read images).

For each screenshot, analyze:

1. **Layout**: Is the page rendered correctly? Any overlapping elements, broken layouts, missing components?
2. **Content**: Is there meaningful content shown (not empty states when data is expected)?
3. **Errors**: Are there any visible error messages, console error banners, or broken images?
4. **UX issues**: Are buttons visible and accessible? Is text readable? Is spacing consistent?
5. **Responsiveness**: Does the viewport look appropriate for the 1280x720 resolution?

Record findings per screenshot as a structured list:
- Screenshot filename
- Page/scenario context
- Observations (list)
- Severity per observation: `info` | `warning` | `critical`

---

## Step 5: Build the HTML QA report

Generate `$SUMMARY_HTML` — a self-contained HTML file with:

1. **Header**: Run timestamp, branch, commit, overall verdict
2. **Executive Summary**: Total scenarios, passed, failed, visual warnings count
3. **Per-Suite Breakdown**: Table with scenario name, status (PASS/FAIL), duration, screenshot count
4. **Screenshot Gallery**: For each scenario, show its screenshots inline (use base64-encoded images so the report is fully self-contained). Apply border colors:
   - Green border = scenario passed, no visual issues
   - Yellow border = scenario passed but visual warnings found
   - Red border = scenario failed
5. **Visual Inspection Findings**: Claude's observations organized by severity
   - Critical issues first (red)
   - Warnings (yellow)
   - Info observations (blue)
6. **Test Failure Details**: For any failed scenarios, show the error message and failure screenshot
7. **Overall Verdict Banner**:
   - ✅ ALL PASS = all scenarios passed, no visual issues
   - ⚠️ WARNINGS = all scenarios passed but visual issues found
   - ❌ FAILURES = one or more scenarios failed

Use clean CSS. Make it look professional — cards, zebra tables, proper typography.

To embed screenshots as base64, read each PNG file and encode it:
```python
import base64
with open(screenshot_path, 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
# Use in HTML: <img src="data:image/png;base64,{b64}" />
```

You can use a Python helper script to do the base64 encoding of all screenshots.

---

## Step 6: Email the report

Primary method (include scenario-results.json as attachment if it exists):
```bash
cd "$ROOT/llm-backend" && source venv/bin/activate
SCENARIO_RESULTS="$REPORT_DIR/scenario-results.json"
EXTRA_ATTACH=""
[ -f "$SCENARIO_RESULTS" ] && EXTRA_ATTACH="--attachment \"$SCENARIO_RESULTS\""

python scripts/send_coverage_report.py \
  --to "manishjain.py@gmail.com" \
  --subject "E2E Runner Report — $BRANCH — $(date +%Y-%m-%d) — <VERDICT>" \
  --report "$SUMMARY_HTML" \
  --log "$LOG_FILE" \
  $EXTRA_ATTACH
EMAIL_EXIT=$?
```

Replace `<VERDICT>` with the actual verdict (ALL PASS / WARNINGS / FAILURES).

Fallback (macOS Mail.app):
```bash
if [ "$EMAIL_EXIT" -ne 0 ]; then
  osascript <<OSA
tell application "Mail"
  set newMessage to make new outgoing message with properties {subject:"E2E Runner Report — $BRANCH — $(date +%Y-%m-%d) — <VERDICT>", content:"See attached QA report and log.", visible:false}
  tell newMessage
    make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
    make new attachment with properties {file name:POSIX file "$SUMMARY_HTML"} at after the last paragraph
    make new attachment with properties {file name:POSIX file "$LOG_FILE"} at after the last paragraph
  end tell
  send newMessage
end tell
OSA
fi
```

If both fail, log the error and print local paths for manual access.

---

## Step 7: Final output

Print a concise summary:
- Total scenarios: X
- Passed: Y | Failed: Z
- Visual issues found: N (critical: C, warning: W, info: I)
- Email delivery status
- Artifact paths:
  - HTML report:            `$SUMMARY_HTML`
  - Log file:               `$LOG_FILE`
  - Progress file:          `$PROGRESS_FILE`
  - Screenshots:            `$SCREENSHOT_DIR/`
  - Playwright HTML report: `$REPORT_DIR/playwright-report/index.html`
  - Scenario results JSON:  `$REPORT_DIR/scenario-results.json`
