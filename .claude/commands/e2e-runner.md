# E2E Runner — Full App E2E Testing Pipeline

Run the full application locally, execute all E2E test scenarios via Playwright, upload results to S3, and email the Playwright HTML report link.

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
  if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo "Frontend is ready after ${i}x2s" | tee -a "$LOG_FILE"
    FRONTEND_READY=1
    break
  fi
  sleep 2
done

if [ "$FRONTEND_READY" -eq 0 ]; then
  echo "ERROR: Frontend not ready after 60s. Check $LOG_FILE for details." | tee -a "$LOG_FILE"
  echo "Hints: port 3000 in use? missing node_modules? Run: lsof -i :3000" | tee -a "$LOG_FILE"
  exit 1
fi
```

---

## Step 3: Run Playwright E2E tests

```bash
cd "$ROOT/e2e"
npx playwright test 2>&1 | tee -a "$LOG_FILE"
E2E_EXIT=${PIPESTATUS[0]}
echo "E2E tests exited with code $E2E_EXIT" | tee -a "$LOG_FILE"
```

This executes all scenarios from `e2e/scenarios.json`, capturing screenshots at every labeled step. Failed tests automatically get a failure screenshot.

After Playwright completes, results are in:
- `reports/e2e-runner/test-results.json` — Playwright's native JSON report (pass/fail, duration, errors)
- `reports/e2e-runner/screenshots/` — screenshots from test steps

---

## Step 3b: Upload test results and screenshots to S3

After Playwright tests complete, upload results and screenshots to S3 so the admin UI can display them.

```bash
cd "$ROOT/llm-backend" && source venv/bin/activate

echo "Uploading E2E results to S3..." | tee -a "$LOG_FILE"
python scripts/upload_e2e_results.py --results-dir "$REPORT_DIR" 2>&1 | tee -a "$LOG_FILE"
UPLOAD_EXIT=$?

if [ "$UPLOAD_EXIT" -eq 0 ]; then
  echo "E2E results uploaded to S3 successfully" | tee -a "$LOG_FILE"
else
  echo "WARNING: Failed to upload E2E results to S3 (exit code $UPLOAD_EXIT)" | tee -a "$LOG_FILE"
fi
```

This uploads:
- All screenshots to `s3://bucket/e2e-results/screenshots/<run-slug>/`
- `e2e-results/latest-results.json` (Playwright JSON report, overwritten each run)
- `e2e-results/runs/<run-slug>/results.json` (timestamped history)

---

## Step 4: Email the report

Primary method:
```bash
cd "$ROOT/llm-backend" && source venv/bin/activate

# Determine verdict from Playwright results
VERDICT="UNKNOWN"
if [ "$E2E_EXIT" -eq 0 ]; then
  VERDICT="ALL PASS"
else
  VERDICT="FAILURES"
fi

python scripts/send_coverage_report.py \
  --to "manishjain.py@gmail.com" \
  --subject "E2E Runner Report — $BRANCH — $(date +%Y-%m-%d) — $VERDICT" \
  --report "$REPORT_DIR/playwright-report/index.html" \
  --log "$LOG_FILE"
EMAIL_EXIT=$?
```

Fallback (macOS Mail.app):
```bash
if [ "$EMAIL_EXIT" -ne 0 ]; then
  osascript <<OSA
tell application "Mail"
  set newMessage to make new outgoing message with properties {subject:"E2E Runner Report — $BRANCH — $(date +%Y-%m-%d) — $VERDICT", content:"See attached Playwright report and log.", visible:false}
  tell newMessage
    make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
    make new attachment with properties {file name:POSIX file "$REPORT_DIR/playwright-report/index.html"} at after the last paragraph
    make new attachment with properties {file name:POSIX file "$LOG_FILE"} at after the last paragraph
  end tell
  send newMessage
end tell
OSA
fi
```

If both fail, log the error and print local paths for manual access.

---

## Step 4b: Commit and push e2e/scenarios.json to trigger production deploy

After uploading results to S3, commit and push `e2e/scenarios.json` so the next auto-deploy includes the latest scenario definitions. Production reads scenarios from the Docker image (copied during CI build) and results from S3.

```bash
cd "$ROOT"

if ! git diff --quiet e2e/scenarios.json 2>/dev/null || ! git diff --cached --quiet e2e/scenarios.json 2>/dev/null; then
  echo "Committing updated e2e/scenarios.json..." | tee -a "$LOG_FILE"
  git add e2e/scenarios.json
  git commit -m "chore: update e2e scenarios.json after e2e-runner

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
  git push
  echo "e2e/scenarios.json pushed — deploy will trigger automatically" | tee -a "$LOG_FILE"
else
  echo "e2e/scenarios.json unchanged, skipping commit" | tee -a "$LOG_FILE"
fi
```

---

## Step 5: Final output

Print a concise summary:
- Total scenarios: X
- Passed: Y | Failed: Z
- Email delivery status
- Artifact paths:
  - Log file:               `$LOG_FILE`
  - Progress file:          `$PROGRESS_FILE`
  - Screenshots:            `$SCREENSHOT_DIR/`
  - Playwright HTML report: `$REPORT_DIR/playwright-report/index.html`
  - Playwright JSON report: `$REPORT_DIR/test-results.json`
