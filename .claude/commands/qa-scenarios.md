# QA Scenarios — Generate/Update e2e/scenarios.json from Codebase

Generate and refresh `e2e/scenarios.json` by scanning the current frontend codebase, cover core app flows (including tutor workflow), stamp update date metadata, and email an HTML scenario report.

## Input
- Optional `$ARGUMENTS` = run slug
- Default slug: `qa-scenarios-$(date +%Y%m%d-%H%M%S)`

## Step 0: Initialize

```bash
SLUG="${ARGUMENTS:-qa-scenarios-$(date +%Y%m%d-%H%M%S)}"
ROOT="$(pwd)"
E2E_DIR="$ROOT/e2e"
REPORT_DIR="$ROOT/reports/qa-scenarios"
mkdir -p "$E2E_DIR" "$REPORT_DIR"
LOG_FILE="$REPORT_DIR/${SLUG}.log"
REPORT_HTML="$REPORT_DIR/${SLUG}.html"
SCENARIOS_JSON="$E2E_DIR/scenarios.json"
SCENARIOS_PREV="$REPORT_DIR/${SLUG}.previous-scenarios.json"
TS_NOW="$(date '+%Y-%m-%d %H:%M:%S %Z')"
TODAY="$(date '+%Y-%m-%d')"

BRANCH="$(git -C "$ROOT" branch --show-current)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"

echo "[$TS_NOW] qa-scenarios started on $BRANCH@$COMMIT" | tee "$LOG_FILE"
[ -f "$SCENARIOS_JSON" ] && cp "$SCENARIOS_JSON" "$SCENARIOS_PREV"
```

## Step 1: Scan codebase for route + selector signals

```bash
# Route hints
find "$ROOT/llm-frontend/src" -type f \( -name "*.tsx" -o -name "*.ts" -o -name "*.jsx" -o -name "*.js" \) -print0 \
  | xargs -0 grep -nE "path=|createBrowserRouter|Routes|Route|navigate\(" > "$REPORT_DIR/${SLUG}.routes.txt" 2>/dev/null || true

# data-testid hints
find "$ROOT/llm-frontend/src" -type f \( -name "*.tsx" -o -name "*.ts" -o -name "*.jsx" -o -name "*.js" \) -print0 \
  | xargs -0 grep -hoE "data-testid=['\"][^'\"]+" > "$REPORT_DIR/${SLUG}.testids.raw.txt" 2>/dev/null || true

sort -u "$REPORT_DIR/${SLUG}.testids.raw.txt" > "$REPORT_DIR/${SLUG}.testids.txt" 2>/dev/null || true
```

## Step 2: Generate updated scenarios.json

Use Python to create/update scenarios with strong default coverage for:
- Tutor workflow (subject → topic → subtopic → chat → send message → back nav)
- Admin Books
- Admin Guidelines
- Admin Evaluation
- Cross-page navigation

Rules:
1. Keep existing scenario IDs when possible (stable IDs).
2. Add missing core scenarios if absent.
3. Remove obviously dead selectors only if no longer present in codebase scan.
4. Add/update top-level metadata:
   - `meta.lastUpdated` (YYYY-MM-DD)
   - `meta.lastUpdatedAt` (timestamp)
   - `meta.generatedBy` = `qa-scenarios`
   - `meta.branch`, `meta.commit`
5. Ensure output shape remains Playwright-runner compatible (`suites` array intact).

```bash
python3 - <<'PY'
import json, os, copy, datetime
from pathlib import Path

root = Path(os.environ.get('ROOT', '.')).resolve()
e2e = root / 'e2e'
report_dir = root / 'reports' / 'qa-scenarios'
scenarios_path = e2e / 'scenarios.json'
ids_path = report_dir / f"{os.environ.get('SLUG')}.testids.txt"

existing = {}
if scenarios_path.exists():
    try:
        existing = json.loads(scenarios_path.read_text())
    except Exception:
        existing = {}

present_ids = set()
if ids_path.exists():
    for line in ids_path.read_text().splitlines():
        if "data-testid='" in line:
            present_ids.add(line.split("data-testid='")[-1])
        elif 'data-testid="' in line:
            present_ids.add(line.split('data-testid="')[-1])

def has(tid):
    return (not present_ids) or (tid in present_ids)

# Core scenario template
suites = [
  {
    "name": "Tutor Flow",
    "route": "/",
    "scenarios": [
      {"id":"tutor-001","name":"Landing page loads with subject selection","steps":[{"action":"navigate","url":"/"},{"action":"screenshot","label":"landing-page"}],"assertions":[{"type":"visible","selector":"[data-testid='subject-list']"}]},
      {"id":"tutor-002","name":"Subject → topic list","steps":[{"action":"navigate","url":"/"},{"action":"waitForSelector","selector":"[data-testid='subject-item']","timeout":15000},{"action":"click","selector":"[data-testid='subject-item']:first-child"},{"action":"screenshot","label":"topic-selection"}],"assertions":[{"type":"visible","selector":"[data-testid='topic-list']"}]},
      {"id":"tutor-003","name":"Topic → subtopic list","steps":[{"action":"navigate","url":"/"},{"action":"waitForSelector","selector":"[data-testid='subject-item']","timeout":15000},{"action":"click","selector":"[data-testid='subject-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='topic-item']","timeout":15000},{"action":"click","selector":"[data-testid='topic-item']:first-child"},{"action":"screenshot","label":"subtopic-selection"}],"assertions":[{"type":"visible","selector":"[data-testid='subtopic-list']"}]},
      {"id":"tutor-004","name":"Start tutor chat session","steps":[{"action":"navigate","url":"/"},{"action":"waitForSelector","selector":"[data-testid='subject-item']","timeout":15000},{"action":"click","selector":"[data-testid='subject-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='topic-item']","timeout":15000},{"action":"click","selector":"[data-testid='topic-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='subtopic-item']","timeout":15000},{"action":"click","selector":"[data-testid='subtopic-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='chat-container']","timeout":30000},{"action":"screenshot","label":"chat-session-started"}],"assertions":[{"type":"visible","selector":"[data-testid='chat-input']"},{"type":"visible","selector":"[data-testid='send-button']"}]},
      {"id":"tutor-005","name":"Send message and receive tutor response","steps":[{"action":"navigate","url":"/"},{"action":"waitForSelector","selector":"[data-testid='subject-item']","timeout":15000},{"action":"click","selector":"[data-testid='subject-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='topic-item']","timeout":15000},{"action":"click","selector":"[data-testid='topic-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='subtopic-item']","timeout":15000},{"action":"click","selector":"[data-testid='subtopic-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='chat-input']","timeout":30000},{"action":"type","selector":"[data-testid='chat-input']","value":"I think the answer is 5"},{"action":"click","selector":"[data-testid='send-button']"},{"action":"waitForResponse","timeout":30000},{"action":"screenshot","label":"tutor-response-received"}],"assertions":[{"type":"countAtLeast","selector":"[data-testid='teacher-message']","count":2}]}
    ]
  },
  {
    "name":"Admin — Books Dashboard","route":"/admin/books","scenarios":[
      {"id":"admin-books-001","name":"Books dashboard loads","steps":[{"action":"navigate","url":"/admin/books"},{"action":"screenshot","label":"books-dashboard"}],"assertions":[{"type":"visible","selector":"h1"}]},
      {"id":"admin-books-002","name":"Create book form loads","steps":[{"action":"navigate","url":"/admin/books/new"},{"action":"screenshot","label":"create-book-form"}],"assertions":[{"type":"visible","selector":"[data-testid='create-book-form']"}]}
    ]
  },
  {
    "name":"Admin — Guidelines Review","route":"/admin/guidelines","scenarios":[
      {"id":"admin-guidelines-001","name":"Guidelines page loads","steps":[{"action":"navigate","url":"/admin/guidelines"},{"action":"screenshot","label":"guidelines-page"}],"assertions":[{"type":"visible","selector":"[data-testid='guidelines-page']"}]}
    ]
  },
  {
    "name":"Admin — Evaluation Dashboard","route":"/admin/evaluation","scenarios":[
      {"id":"admin-eval-001","name":"Evaluation dashboard loads","steps":[{"action":"navigate","url":"/admin/evaluation"},{"action":"screenshot","label":"eval-dashboard"}],"assertions":[{"type":"visible","selector":"[data-testid='eval-dashboard']"}]}
    ]
  }
]

out = {
  "meta": {
    "lastUpdated": datetime.datetime.now().strftime('%Y-%m-%d'),
    "lastUpdatedAt": datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z'),
    "generatedBy": "qa-scenarios",
    "branch": os.popen(f"git -C '{root}' branch --show-current").read().strip(),
    "commit": os.popen(f"git -C '{root}' rev-parse --short HEAD").read().strip()
  },
  "suites": suites
}

# Preserve any existing suite/scenario not covered above (append only)
if isinstance(existing, dict) and isinstance(existing.get('suites'), list):
    known_ids = {sc['id'] for su in suites for sc in su.get('scenarios', []) if 'id' in sc}
    for su in existing.get('suites', []):
        extras = []
        for sc in su.get('scenarios', []):
            sid = sc.get('id')
            if sid and sid not in known_ids:
                extras.append(sc)
        if extras:
            out['suites'].append({"name": su.get('name','Legacy Suite'), "route": su.get('route','/'), "scenarios": extras})

scenarios_path.write_text(json.dumps(out, indent=2))
print(f"WROTE {scenarios_path}")
PY
```

## Step 3: Generate HTML scenario report

Create an HTML report with:
- metadata (lastUpdated, branch, commit)
- total suites + total scenarios
- table of all scenarios (suite, id, name, route)
- note about tutor workflow scenarios explicitly included

```bash
python3 - <<'PY'
import json, os, html
from pathlib import Path

root = Path(os.environ['ROOT'])
scenarios = json.loads((root/'e2e/scenarios.json').read_text())
report_html = Path(os.environ['REPORT_HTML'])

rows = []
total = 0
for suite in scenarios.get('suites', []):
    route = suite.get('route','')
    for sc in suite.get('scenarios', []):
        total += 1
        rows.append(f"<tr><td>{html.escape(suite.get('name',''))}</td><td>{html.escape(sc.get('id',''))}</td><td>{html.escape(sc.get('name',''))}</td><td><code>{html.escape(route)}</code></td></tr>")

meta = scenarios.get('meta', {})
html_out = f"""<!doctype html><html><head><meta charset='utf-8'><title>QA Scenarios Report</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;margin:24px;color:#111}}.card{{border:1px solid #ddd;border-radius:12px;padding:14px;margin:10px 0}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ddd;padding:8px}}tr:nth-child(even){{background:#fafafa}}</style></head><body>
<h1>QA Scenarios Report</h1>
<div class='card'><b>Last updated:</b> {meta.get('lastUpdatedAt','')}<br><b>Branch:</b> {meta.get('branch','')}<br><b>Commit:</b> {meta.get('commit','')}<br><b>Total suites:</b> {len(scenarios.get('suites',[]))}<br><b>Total scenarios:</b> {total}</div>
<div class='card'><b>Coverage note:</b> Tutor workflow scenarios are included (selection flow + chat interaction).</div>
<table><thead><tr><th>Suite</th><th>ID</th><th>Scenario</th><th>Route</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
report_html.write_text(html_out)
print(f"WROTE {report_html}")
PY
```

## Step 4: Email report + updated scenarios

Send email via macOS Mail.app with attachments:
- `$REPORT_HTML`
- `$SCENARIOS_JSON`
- `$LOG_FILE`

```bash
osascript <<OSA
tell application "Mail"
  set newMessage to make new outgoing message with properties {subject:"QA Scenarios Update — $BRANCH — $(date +%Y-%m-%d)", content:"Hi Manish,\n\nAttached are the latest generated QA scenarios report, updated scenarios.json, and run log.\n\nGenerated by qa-scenarios.", visible:false}
  tell newMessage
    make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
    make new attachment with properties {file name:POSIX file "$REPORT_HTML"} at after the last paragraph
    make new attachment with properties {file name:POSIX file "$SCENARIOS_JSON"} at after the last paragraph
    make new attachment with properties {file name:POSIX file "$LOG_FILE"} at after the last paragraph
  end tell
  send newMessage
end tell
OSA
```

## Step 5: Final output

Print:
- updated scenarios path
- lastUpdated date from JSON
- total suites/scenarios
- report path
- email send status
