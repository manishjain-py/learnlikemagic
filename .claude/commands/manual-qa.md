# Manual QA — Visual UI Testing via Computer Use

Test any UI flow visually using the computer-use MCP. Navigate the running app in a browser, interact with elements, capture screenshots at every step, generate a self-contained HTML report with embedded screenshots, and email it.

## Input

- `$ARGUMENTS` = Natural language description of what to test. Can be a specific flow, a page, or a broad area.
- Examples:
  - `"Test the complete onboarding flow for a new user"`
  - `"Test the teach-me session: select subject → chapter → topic → start session → send a message"`
  - `"Verify admin books dashboard loads and can navigate to a book detail page"`
  - `"Check report card page shows subjects and drill-down works"`

If `$ARGUMENTS` is empty, ask the user what flow to test.

---

## AUTOMATION DIRECTIVE

This is a **semi-automated pipeline**. The agent drives all browser interaction and reporting autonomously, but:
- **DO** pause to ask the user if the test requirements are ambiguous
- **DO NOT** pause for permission between test steps — execute them continuously
- If a step fails (element not found, page didn't load), **record the failure**, take a screenshot, and continue to the next step

---

## APP CONTEXT: LearnLikeMagic

LearnLikeMagic is an AI-powered adaptive tutoring platform. The app has two sides:
1. **Student-facing** — login, onboarding, learning sessions (teach/clarify/exam), report card, history, profile
2. **Admin-facing** — book management, evaluation, LLM config, test scenarios, feature flags, docs

### Route Map (quick reference)

**Public:**
- `/login` — Auth method picker (email, phone, OAuth)
- `/login/email` — Email + password form
- `/login/phone` — Phone + OTP form
- `/signup/email` → `/signup/email/verify` — Signup + verification
- `/forgot-password` — Password reset

**Student (protected, requires auth + completed onboarding):**
- `/learn` — Subject selection grid
- `/learn/:subject` — Chapter selection
- `/learn/:subject/:chapter` — Topic selection
- `/learn/:subject/:chapter/:topic` — Mode selection (Teach Me / Clarify / Exam)
- `/learn/:subject/:chapter/:topic/{teach|clarify|exam}/:sessionId` — Chat session
- `/learn/:subject/:chapter/:topic/exam-review/:sessionId` — Exam review
- `/profile` — View/edit profile
- `/profile/enrichment` — Enrichment profile (interests, learning style)
- `/report-card` — Progress dashboard with subject drill-down
- `/history` — Session history with filtering and pagination

**Admin (protected, admin-only):**
- `/admin` — Dashboard home (9 card grid)
- `/admin/books-v2` — Book list → `/admin/books-v2/new` (create) → `/admin/books-v2/:id` (detail)
- `/admin/books-v2/:bookId/explanations/:chapterId` — Explanation management
- `/admin/books-v2/:bookId/topics/:chapterId` — Topic management
- `/admin/books-v2/:bookId/guidelines/:chapterId` — Guidelines
- `/admin/books-v2/:bookId/ocr/:chapterId` — OCR results
- `/admin/books-v2/:bookId/visuals/:chapterId` — Visual assets
- `/admin/evaluation` — Evaluation dashboard
- `/admin/llm-config` — LLM provider config
- `/admin/test-scenarios` — E2E test scenarios viewer
- `/admin/feature-flags` — Feature flag toggles
- `/admin/docs` — Documentation viewer
- `/admin/issues` — Issue tracker

### Key Test IDs (data-testid selectors)

```
subject-list, subject-item          — Subject grid
chapter-list, chapter-item          — Chapter grid
topic-list, topic-item              — Topic grid
mode-selection                      — Mode picker container
mode-teach-me, mode-clarify-doubts, mode-exam — Mode buttons
chat-container, chat-input, send-button        — Chat session
mic-button, pause-button                       — Chat controls
teacher-message                                — Teacher response bubble
reportcard-subject-card                        — Report card subject card
create-book-form                               — Book creation form
eval-dashboard                                 — Evaluation dashboard
```

---

## Step 0: Initialize

```bash
SLUG="manual-qa-$(date +%Y%m%d-%H%M%S)"
ROOT="$(pwd)"
REPORT_DIR="$ROOT/reports/manual-qa"
SCREENSHOT_DIR="$REPORT_DIR/$SLUG/screenshots"
mkdir -p "$SCREENSHOT_DIR"
LOG_FILE="$REPORT_DIR/${SLUG}.log"
REPORT_HTML="$REPORT_DIR/${SLUG}-report.html"

BRANCH="$(git -C "$ROOT" branch --show-current)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
NOW="$(date '+%Y-%m-%d %H:%M:%S %Z')"

echo "[$NOW] manual-qa started on $BRANCH@$COMMIT" | tee "$LOG_FILE"
echo "Requirements: $ARGUMENTS" | tee -a "$LOG_FILE"
```

---

## Step 1: Plan test steps

Based on the user's requirements (`$ARGUMENTS`):

1. **Parse what needs testing.** Identify which flows, pages, or user journeys are involved.
2. **Read frontend code if needed.** If the requirements reference a feature you're unsure about, read the relevant component:
   - Routes: `llm-frontend/src/App.tsx`
   - Features: `llm-frontend/src/features/<domain>/pages/` and `llm-frontend/src/features/<domain>/components/`
   - E2E scenarios: `e2e/scenarios.json` (for known selectors and step patterns)
3. **Write a test plan** — ordered list of steps, each with:
   - Action (navigate, click, type, wait, verify)
   - Expected outcome
   - Screenshot label

Log the test plan to `$LOG_FILE`.

---

## Step 2: Determine app URL and prepare browser

Check which environment to test against:

```bash
# Check if frontend is running locally
if curl -s http://localhost:3000 > /dev/null 2>&1; then
  APP_URL="http://localhost:3000"
  echo "Using local frontend at $APP_URL" | tee -a "$LOG_FILE"
elif curl -s http://localhost:5173 > /dev/null 2>&1; then
  APP_URL="http://localhost:5173"
  echo "Using local frontend (Vite) at $APP_URL" | tee -a "$LOG_FILE"
else
  echo "No local frontend detected." | tee -a "$LOG_FILE"
  # Ask user for URL or start the frontend
fi
```

If no frontend is running, ask the user whether to:
- Start it (`cd llm-frontend && npm run dev`)
- Use a deployed URL they provide

### Request computer-use access

Load ALL computer-use tools via ToolSearch:
```
query: "computer-use", max_results: 30
```

Then call `mcp__computer-use__request_access` for the applications you need:
- The browser being used (Chrome, Safari, Arc, etc.)
- Any other apps needed for the flow

### Open the app in the browser

Use `mcp__computer-use__open_application` to open the browser, then navigate to the app URL.

**IMPORTANT — Browser tier limitations:**
Browsers are granted at **"read"** tier by default — you can see screenshots but clicks/typing are blocked. Two options:

1. **Preferred: Use the app that's already open.** If the user already has the app open in their browser, just take screenshots to verify state and use keyboard shortcuts (Cmd+L to focus address bar) or other creative approaches.
2. **Alternative: Ask the user** to navigate to specific URLs if you can't interact with the browser directly. Print the URL clearly so they can click/paste it.

Adapt your approach based on what tier the browser is granted at. If clicks work, use them. If not, work with what you have.

---

## Step 3: Execute test steps

For each planned test step:

1. **Perform the action:**
   - Navigate: ask user or use address bar shortcut
   - Click: `mcp__computer-use__left_click` at coordinates (identify from screenshot)
   - Type: `mcp__computer-use__type` for text input
   - Wait: `mcp__computer-use__wait` for animations/loading (1-3 seconds)
   - Scroll: `mcp__computer-use__scroll` to find elements below fold

2. **Take a screenshot** after each action:
   - Use `mcp__computer-use__screenshot`
   - The screenshot comes back as a file path — save/record that path
   - Copy the screenshot to `$SCREENSHOT_DIR` with a descriptive name:
     ```bash
     cp "<screenshot_path>" "$SCREENSHOT_DIR/step-{N}-{label}.png"
     ```

3. **Verify expected state** by analyzing the screenshot:
   - Is the expected page/element visible?
   - Are there error messages?
   - Does the layout look correct?
   - Are interactive elements in the right state?

4. **Record result** for this step:
   - **PASS** — expected state matches
   - **FAIL** — expected state doesn't match (describe what's wrong)
   - **BLOCKED** — couldn't perform the action (e.g., element not found, permission denied)
   - **WARN** — action succeeded but something looks off

5. **Log** the step result and any observations to `$LOG_FILE`.

### Error handling

- If a page doesn't load within 10 seconds, record as FAIL and move on
- If an element isn't visible, scroll down once and retry before failing
- If the browser blocks interaction, switch to screenshot-only mode and record what you can verify visually
- Never abandon the entire test for a single step failure — always continue

---

## Step 4: Generate HTML report

Build a self-contained HTML report at `$REPORT_HTML`. **Embed all screenshots as base64** so the report is a single file that works in email.

### Base64 encode screenshots

```bash
# For each screenshot, create a base64 data URI
for img in "$SCREENSHOT_DIR"/*.png; do
  base64 -i "$img" | tr -d '\n'
done
```

### HTML report structure

Use Python to generate the report (cleaner string handling):

```python
import base64, json, html, os, sys
from pathlib import Path
from datetime import datetime

screenshot_dir = sys.argv[1]  # $SCREENSHOT_DIR
report_path = sys.argv[2]     # $REPORT_HTML
branch = sys.argv[3]
commit = sys.argv[4]
test_data_json = sys.argv[5]  # JSON string with test results

test_data = json.loads(test_data_json)
# test_data = {
#   "title": "...",
#   "requirements": "...",
#   "steps": [
#     {"number": 1, "action": "...", "expected": "...", "result": "PASS|FAIL|BLOCKED|WARN",
#      "notes": "...", "screenshot": "step-1-login.png"},
#     ...
#   ]
# }
```

The HTML must include:
1. **Header** — Report title, date, branch, commit, overall verdict
2. **Summary bar** — Total steps, passed, failed, blocked, warnings (color-coded)
3. **Requirements** — What was tested (from user input)
4. **Test steps table** — For each step:
   - Step number
   - Action description
   - Expected outcome
   - Result badge (green PASS / red FAIL / yellow WARN / gray BLOCKED)
   - Notes/observations
   - Embedded screenshot (base64 `<img>` tag, max-width: 100%)
5. **Footer** — Generation timestamp, agent info

**Styling:**
- Clean, professional design with inline CSS (no external stylesheets)
- Max width 1000px, centered
- Result badges: green (#2e7d32) PASS, red (#c62828) FAIL, amber (#f57f17) WARN, gray (#757575) BLOCKED
- Screenshots in expandable `<details>` blocks (collapsed by default to keep report scannable)
- Responsive — works in email clients

---

## Step 5: Email report

Send the HTML report to `manish@simplifyloop.com` via macOS Mail.app:

```bash
SUBJECT="Manual QA Report — $BRANCH — $(date +%Y-%m-%d) — ${VERDICT}"

osascript <<OSA
tell application "Mail"
  set newMessage to make new outgoing message with properties {subject:"$SUBJECT", content:"Hi Manish,\n\nAttached is the manual QA test report.\n\nFlow tested: $REQUIREMENTS_SUMMARY\nVerdict: $VERDICT\nSteps: $TOTAL_STEPS (${PASSED} passed, ${FAILED} failed)\n\nSee the attached HTML report for full details with screenshots.", visible:false}
  tell newMessage
    make new to recipient at end of to recipients with properties {address:"manish@simplifyloop.com"}
    make new attachment with properties {file name:POSIX file "$REPORT_HTML"} at after the last paragraph
  end tell
  send newMessage
end tell
OSA
EMAIL_EXIT=$?
```

If Mail.app fails, print the report path for manual access.

---

## Step 6: Final output

Print a concise summary:

```
Manual QA Report — {flow tested}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Verdict:      PASS / FAIL / PARTIAL
Steps:        X total (Y passed, Z failed, W warnings)
Branch:       {branch}@{commit}
Email:        Sent to manish@simplifyloop.com / Failed (see local path)
Report:       {$REPORT_HTML}
Screenshots:  {$SCREENSHOT_DIR}/
Log:          {$LOG_FILE}
```

---

## Tips for effective testing

- **Before clicking**, always take a screenshot to identify element positions
- **After clicking**, wait 1-2 seconds then screenshot to verify the result
- **For forms**, type slowly and verify each field
- **For navigation**, verify both the URL change and the page content
- **For loading states**, take multiple screenshots to capture the transition
- **For responsive issues**, note if elements overlap or are cut off
- **Compare against the route map** above to verify you're on the right page
- **Read the frontend code** (`llm-frontend/src/features/...`) when unsure about expected behavior — the component source is the ground truth
