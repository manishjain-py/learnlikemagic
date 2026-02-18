# Unit Test Runner — Run Unit Tests + Coverage HTML + Email Report

Run all available unit tests in this repo, generate coverage artifacts, build a readable HTML summary, and email the report.

## Input
- Optional `$ARGUMENTS` = report slug
- Default slug: `unit-test-$(date +%Y%m%d-%H%M%S)`

## Step 0: Initialize

```bash
SLUG="${ARGUMENTS:-unit-test-$(date +%Y%m%d-%H%M%S)}"
ROOT="$(pwd)"
REPORT_DIR="$ROOT/reports/unit-test"
mkdir -p "$REPORT_DIR"
LOG_FILE="$REPORT_DIR/${SLUG}.log"
SUMMARY_HTML="$REPORT_DIR/${SLUG}.html"

BRANCH="$(git -C "$ROOT" branch --show-current)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
NOW="$(date '+%Y-%m-%d %H:%M:%S %Z')"

echo "[$NOW] unit-test-runner started on $BRANCH@$COMMIT" | tee "$LOG_FILE"
```

## Step 1: Run backend unit tests + coverage (required)

```bash
cd "$ROOT/llm-backend" || exit 1
source venv/bin/activate
python -m pytest tests/unit/ \
  --cov=. \
  --cov-report=term-missing \
  --cov-report=html:htmlcov \
  --cov-report=json:coverage-unit.json \
  --no-header -q 2>&1 | tee -a "$LOG_FILE"
BACKEND_EXIT=${PIPESTATUS[0]}
```

Backend artifacts:
- `llm-backend/htmlcov/index.html`
- `llm-backend/coverage-unit.json`

## Step 2: Discover and run additional unit suites (best effort)

Check top-level folders under repo root and run additional suites only if clearly configured:
- Python: if `tests/unit` exists and command works in that folder
- Node: only if `package.json` has a `test` script (`npm run test -- --coverage`)

Rules:
1. Treat these as optional; do **not** fail entire run for missing scripts.
2. Append all output to `$LOG_FILE`.
3. Record each suite as: `name`, `command`, `status`.
4. If none found, record: `No additional unit test suites detected`.

## Step 3: Build HTML summary report

Use `llm-backend/coverage-unit.json` to extract:
- line-rate percentage
- covered lines
- total lines

Generate `$SUMMARY_HTML` with:
1. Header: run timestamp, branch, commit
2. Backend status: PASS/FAIL
3. Coverage summary card
4. Additional suites table (or “none detected”)
5. Link/path note to backend coverage HTML: `llm-backend/htmlcov/index.html`
6. Overall status banner:
   - ✅ PASS = backend passed and all optional suites passed
   - ⚠️ PARTIAL = backend passed but optional suites had failures
   - ❌ FAIL = backend failed

Use clean CSS (simple cards + zebra table).

## Step 4: Email report (ALWAYS include htmlcov/index.html)

Always send an email to `manishjain.py@gmail.com` with **all three attachments**:
1. `$SUMMARY_HTML`
2. `$LOG_FILE`
3. `$ROOT/llm-backend/htmlcov/index.html`

Use macOS Mail.app (required):

```bash
COVERAGE_INDEX="$ROOT/llm-backend/htmlcov/index.html"

osascript <<OSA
 tell application "Mail"
   set newMessage to make new outgoing message with properties {subject:"Unit Test Report — $BRANCH — $(date +%Y-%m-%d)", content:"Hi Manish,\n\nAttached are today’s unit test summary, execution log, and coverage index (htmlcov/index.html).", visible:false}
   tell newMessage
     make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
     make new attachment with properties {file name:POSIX file "$SUMMARY_HTML"} at after the last paragraph
     make new attachment with properties {file name:POSIX file "$LOG_FILE"} at after the last paragraph
     make new attachment with properties {file name:POSIX file "$COVERAGE_INDEX"} at after the last paragraph
   end tell
   send newMessage
 end tell
OSA
EMAIL_EXIT=$?
```

If Mail.app send fails, print the three file paths clearly for manual sharing.

## Step 5: Final output

Print a concise summary:
- Backend tests: pass/fail
- Coverage %
- Optional suites run + status
- Email delivery status
- Paths to:
  - `$SUMMARY_HTML`
  - `$LOG_FILE`
  - `llm-backend/htmlcov/index.html`
