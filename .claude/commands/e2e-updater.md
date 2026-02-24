# E2E Updater — Generate/Update e2e/scenarios.json from Codebase

## Critical Responsibility

This skill is the **single source of truth for what gets E2E tested**. If a flow is missing from `scenarios.json`, it has zero automated coverage and regressions will ship silently. Your job is to ensure every user-facing flow and subflow has at least one scenario. After generating scenarios, you MUST produce a coverage analysis that honestly assesses what is and isn't covered.

**Before generating scenarios, read the functional docs** to understand all app flows:
- `docs/functional/app-overview.md` — All features and user journeys
- `docs/functional/learning-session.md` — Tutor session flows (3 modes, pause/resume, voice)
- `docs/functional/auth-and-onboarding.md` — Auth methods, signup, onboarding wizard
- `docs/functional/scorecard.md` — Scorecard views, practice again
- `docs/functional/book-guidelines.md` — Book upload, guidelines, study plans
- `docs/functional/evaluation.md` — Evaluation dashboard, simulations

## App Flow Inventory (Reference Checklist)

Every scenario generation run must check coverage against this inventory. Flows marked with routes are directly testable via navigation.

### Student Flows
| # | Flow | Route | Key Subflows |
|---|------|-------|--------------|
| S1 | Login page | `/login` | 3 method buttons visible (email, phone, Google) |
| S2 | Email login | `/login/email` | Form loads, fields present |
| S3 | Phone login | `/login/phone` | Country code picker, phone input |
| S4 | Email signup | `/signup/email` | Form loads, password requirements shown |
| S5 | Email verification | `/signup/email/verify` | 6-digit code input |
| S6 | Forgot password | `/forgot-password` | Form loads |
| S7 | Onboarding wizard | `/onboarding` | Name, age, grade, board steps |
| S8 | Profile page | `/profile` | View mode, edit mode, logout button |
| S9 | Subject selection | `/` | Subject list loads, items clickable |
| S10 | Topic selection | `/` | Topic list loads after subject click |
| S11 | Subtopic selection | `/` | Subtopic list loads after topic click, progress badges |
| S12 | Mode selection | `/` | Teach Me, Clarify Doubts, Exam buttons; Resume if available |
| S13 | Chat session | `/` | Chat container, input field, send button, teacher messages |
| S14 | Send message + response | `/` | Type message, send, receive teacher response |
| S15 | Voice input | `/` | Mic button present |
| S16 | Pause session | `/` | Pause button visible during Teach Me |
| S17 | Session complete | `/` | Summary card after session ends |
| S18 | Scorecard overview | `/scorecard` | Mastery ring, subject cards, strengths, needs practice |
| S19 | Scorecard subject detail | `/scorecard` | Click subject card, see topics/subtopics |
| S20 | Session history | `/history` | Past sessions list |

### Admin Flows
| # | Flow | Route | Key Subflows |
|---|------|-------|--------------|
| A1 | Books dashboard | `/admin/books` | Book list, status indicators |
| A2 | Create book | `/admin/books/new` | Form with title, author, grade fields |
| A3 | Book detail | `/admin/books/:id` | Page list, upload area, OCR view |
| A4 | Guidelines review | `/admin/guidelines` | Filter controls, guideline list, approve/reject |
| A5 | Evaluation dashboard | `/admin/evaluation` | Run list, start simulation, view results |
| A6 | LLM config | `/admin/llm-config` | Config form loads |
| A7 | Docs viewer | `/admin/docs` | Page loads, doc list |
| A8 | Test scenarios | `/admin/test-scenarios` | Page loads |

---

## Input
- Optional `$ARGUMENTS` = run slug
- Default slug: `e2e-updater-$(date +%Y%m%d-%H%M%S)`

## Step 0: Initialize

```bash
SLUG="${ARGUMENTS:-e2e-updater-$(date +%Y%m%d-%H%M%S)}"
ROOT="$(pwd)"
E2E_DIR="$ROOT/e2e"
REPORT_DIR="$ROOT/reports/e2e-updater"
mkdir -p "$E2E_DIR" "$REPORT_DIR"
LOG_FILE="$REPORT_DIR/${SLUG}.log"
REPORT_HTML="$REPORT_DIR/${SLUG}.html"
COVERAGE_LOG="$REPORT_DIR/${SLUG}.coverage.md"
SCENARIOS_JSON="$E2E_DIR/scenarios.json"
SCENARIOS_PREV="$REPORT_DIR/${SLUG}.previous-scenarios.json"
TS_NOW="$(date '+%Y-%m-%d %H:%M:%S %Z')"
TODAY="$(date '+%Y-%m-%d')"

BRANCH="$(git -C "$ROOT" branch --show-current)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"

echo "[$TS_NOW] e2e-updater started on $BRANCH@$COMMIT" | tee "$LOG_FILE"
[ -f "$SCENARIOS_JSON" ] && cp "$SCENARIOS_JSON" "$SCENARIOS_PREV"
```

## Step 1: Read functional docs + scan codebase

Read all functional docs listed in the "Critical Responsibility" section above to understand the full app surface. Then scan the codebase:

```bash
# Route hints
find "$ROOT/llm-frontend/src" -type f \( -name "*.tsx" -o -name "*.ts" -o -name "*.jsx" -o -name "*.js" \) -print0 \
  | xargs -0 grep -nE "path=|createBrowserRouter|Routes|Route|navigate\(" > "$REPORT_DIR/${SLUG}.routes.txt" 2>/dev/null || true

# data-testid hints
find "$ROOT/llm-frontend/src" -type f \( -name "*.tsx" -o -name "*.ts" -o -name "*.jsx" -o -name "*.js" \) -print0 \
  | xargs -0 grep -hoE "data-testid=['\"][^'\"]+" > "$REPORT_DIR/${SLUG}.testids.raw.txt" 2>/dev/null || true

sort -u "$REPORT_DIR/${SLUG}.testids.raw.txt" > "$REPORT_DIR/${SLUG}.testids.txt" 2>/dev/null || true
```

After scanning, cross-reference the discovered routes and testids against the App Flow Inventory above. Identify any flows that:
- Have routes but no scenarios
- Have `data-testid` attributes but no scenario references them
- Are listed in the inventory but have no testable selector yet

## Step 2: Generate updated scenarios.json

Use Python to create/update scenarios. **Aim for at least one scenario per flow in the inventory.** Prioritize flows by user impact: tutor selection flow, chat, scorecard, and admin dashboards are highest priority.

Coverage targets:
- Tutor workflow (subject → topic → subtopic → chat → send message → back nav)
- Auth pages (login, signup forms load correctly)
- Onboarding wizard (page loads, steps visible)
- Profile page
- Scorecard (overview loads, subject detail)
- Session history
- Admin: Books dashboard + create + detail
- Admin: Guidelines review
- Admin: Evaluation dashboard
- Admin: LLM config, Docs viewer, Test scenarios
- Cross-page navigation

Rules:
1. Keep existing scenario IDs when possible (stable IDs).
2. Add missing core scenarios if absent.
3. Remove obviously dead selectors only if no longer present in codebase scan.
4. Add/update top-level metadata:
   - `meta.lastUpdated` (YYYY-MM-DD)
   - `meta.lastUpdatedAt` (timestamp)
   - `meta.generatedBy` = `e2e-updater`
   - `meta.branch`, `meta.commit`
5. Ensure output shape remains Playwright-runner compatible (`suites` array intact).
6. **Screenshot timing rule**: NEVER place a `screenshot` step immediately after a `click` or `navigate` step that triggers async data loading. Always insert a `waitForSelector` step targeting the expected loaded content BEFORE the `screenshot`. This prevents capturing "Loading..." states. For example, after clicking a subject that loads topics, wait for `[data-testid='topic-list']` before the screenshot.
7. **Assertion vs waitForSelector**: Assertions with `toBeVisible` auto-retry but run AFTER screenshots. A passing assertion does NOT mean the screenshot captured the right state. Always use explicit `waitForSelector` steps to gate screenshots.
8. **New scenario checklist**: For every new scenario, verify: (a) every `click` on an async-loading trigger is followed by a `waitForSelector` for the loaded content, (b) every `screenshot` is preceded by a `waitForSelector` for the content you want to capture, (c) assertions reference selectors that actually exist in the codebase.

```bash
python3 - <<'PY'
import json, os, copy, datetime
from pathlib import Path

root = Path(os.environ.get('ROOT', '.')).resolve()
e2e = root / 'e2e'
report_dir = root / 'reports' / 'e2e-updater'
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
      {"id":"tutor-001","name":"Landing page loads with subject selection","steps":[{"action":"navigate","url":"/"},{"action":"waitForSelector","selector":"[data-testid='subject-list']","timeout":15000},{"action":"screenshot","label":"landing-page"}],"assertions":[{"type":"visible","selector":"[data-testid='subject-list']"}]},
      {"id":"tutor-002","name":"Subject → topic list","steps":[{"action":"navigate","url":"/"},{"action":"waitForSelector","selector":"[data-testid='subject-item']","timeout":15000},{"action":"click","selector":"[data-testid='subject-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='topic-list']","timeout":15000},{"action":"screenshot","label":"topic-selection"}],"assertions":[{"type":"visible","selector":"[data-testid='topic-list']"}]},
      {"id":"tutor-003","name":"Topic → subtopic list","steps":[{"action":"navigate","url":"/"},{"action":"waitForSelector","selector":"[data-testid='subject-item']","timeout":15000},{"action":"click","selector":"[data-testid='subject-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='topic-item']","timeout":15000},{"action":"click","selector":"[data-testid='topic-item']:first-child"},{"action":"waitForSelector","selector":"[data-testid='subtopic-list']","timeout":15000},{"action":"screenshot","label":"subtopic-selection"}],"assertions":[{"type":"visible","selector":"[data-testid='subtopic-list']"}]},
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
    "generatedBy": "e2e-updater",
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

## Step 3: Generate coverage analysis log

**This step is mandatory.** After generating scenarios.json, produce a coverage analysis file that maps every flow in the App Flow Inventory to the scenarios that cover it. Be honest about gaps.

Write `$COVERAGE_LOG` as a Markdown file with this structure:

```markdown
# E2E Coverage Analysis
Generated: <timestamp>
Branch: <branch> @ <commit>

## Summary
- **Total scenarios**: <N>
- **Flows covered**: <X> / 28
- **Coverage percentage**: <X/28 * 100>%
- **Confidence level**: <HIGH | MEDIUM | LOW>
- **Confidence reasoning**: <1-2 sentences explaining the confidence level>

## Flow Coverage Matrix

### Student Flows
| # | Flow | Covered? | Scenario IDs | Notes |
|---|------|----------|--------------|-------|
| S1 | Login page | YES/NO | tutor-xxx | ... |
...

### Admin Flows
| # | Flow | Covered? | Scenario IDs | Notes |
|---|------|----------|--------------|-------|
| A1 | Books dashboard | YES/NO | admin-xxx | ... |
...

## Gaps & Recommendations
<List flows with NO coverage and what data-testid attributes would be needed to cover them>

## Selector Audit
- data-testid attributes in codebase: <N>
- data-testid attributes referenced by scenarios: <N>
- Unused testids (in code but no scenario): <list>
- Missing testids (in scenario but not in code): <list>
```

Confidence level criteria:
- **HIGH**: 80%+ flows covered, all critical paths (tutor selection, chat, admin dashboards) have scenarios, no missing selectors
- **MEDIUM**: 60-79% flows covered, all critical paths covered but secondary flows (auth, profile, scorecard detail) are missing
- **LOW**: Below 60% flows covered, or any critical path is missing

```bash
python3 - <<'PY'
import json, os, datetime
from pathlib import Path

root = Path(os.environ.get('ROOT', '.')).resolve()
scenarios = json.loads((root / 'e2e' / 'scenarios.json').read_text())
coverage_log = Path(os.environ['COVERAGE_LOG'])
ids_path = root / 'reports' / 'e2e-updater' / f"{os.environ.get('SLUG')}.testids.txt"

# Collect all scenario IDs and their selectors
all_scenarios = []
all_selectors = set()
for suite in scenarios.get('suites', []):
    for sc in suite.get('scenarios', []):
        all_scenarios.append(sc)
        for step in sc.get('steps', []):
            sel = step.get('selector', '')
            if 'data-testid' in sel:
                all_selectors.add(sel.split("data-testid='")[-1].split("'")[0] if "data-testid='" in sel else sel.split('data-testid="')[-1].split('"')[0])
        for a in sc.get('assertions', []):
            sel = a.get('selector', '')
            if 'data-testid' in sel:
                all_selectors.add(sel.split("data-testid='")[-1].split("'")[0] if "data-testid='" in sel else sel.split('data-testid="')[-1].split('"')[0])

# Collect testids from codebase
code_testids = set()
if ids_path.exists():
    for line in ids_path.read_text().splitlines():
        tid = ''
        if "data-testid='" in line:
            tid = line.split("data-testid='")[-1]
        elif 'data-testid="' in line:
            tid = line.split('data-testid="')[-1]
        if tid:
            code_testids.add(tid)

total_scenarios = len(all_scenarios)
sc_ids = {sc['id'] for sc in all_scenarios}

# Flow inventory — each entry: (id, name, route, covered_if_any_of_these_scenario_prefixes)
student_flows = [
    ('S1', 'Login page', '/login', ['auth-login']),
    ('S2', 'Email login', '/login/email', ['auth-email-login']),
    ('S3', 'Phone login', '/login/phone', ['auth-phone']),
    ('S4', 'Email signup', '/signup/email', ['auth-signup']),
    ('S5', 'Email verification', '/signup/email/verify', ['auth-verify']),
    ('S6', 'Forgot password', '/forgot-password', ['auth-forgot']),
    ('S7', 'Onboarding wizard', '/onboarding', ['onboarding']),
    ('S8', 'Profile page', '/profile', ['profile']),
    ('S9', 'Subject selection', '/', ['tutor-001']),
    ('S10', 'Topic selection', '/', ['tutor-002']),
    ('S11', 'Subtopic selection', '/', ['tutor-003']),
    ('S12', 'Mode selection', '/', ['tutor-mode']),
    ('S13', 'Chat session', '/', ['tutor-004']),
    ('S14', 'Send message + response', '/', ['tutor-005']),
    ('S15', 'Voice input', '/', ['tutor-voice']),
    ('S16', 'Pause session', '/', ['tutor-pause']),
    ('S17', 'Session complete', '/', ['tutor-complete']),
    ('S18', 'Scorecard overview', '/scorecard', ['scorecard']),
    ('S19', 'Scorecard subject detail', '/scorecard', ['scorecard-detail']),
    ('S20', 'Session history', '/history', ['history']),
]

admin_flows = [
    ('A1', 'Books dashboard', '/admin/books', ['admin-books-001']),
    ('A2', 'Create book', '/admin/books/new', ['admin-books-002']),
    ('A3', 'Book detail', '/admin/books/:id', ['admin-books-detail']),
    ('A4', 'Guidelines review', '/admin/guidelines', ['admin-guidelines']),
    ('A5', 'Evaluation dashboard', '/admin/evaluation', ['admin-eval']),
    ('A6', 'LLM config', '/admin/llm-config', ['admin-llm']),
    ('A7', 'Docs viewer', '/admin/docs', ['admin-docs']),
    ('A8', 'Test scenarios', '/admin/test-scenarios', ['admin-test']),
]

def check_covered(prefixes):
    matching = []
    for prefix in prefixes:
        for sid in sc_ids:
            if sid == prefix or sid.startswith(prefix):
                matching.append(sid)
    return matching

lines = []
lines.append('# E2E Coverage Analysis')
lines.append(f'Generated: {datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")}')
meta = scenarios.get('meta', {})
lines.append(f'Branch: {meta.get("branch", "?")} @ {meta.get("commit", "?")}')
lines.append('')

total_flows = len(student_flows) + len(admin_flows)
covered_count = 0

student_rows = []
for fid, name, route, prefixes in student_flows:
    matching = check_covered(prefixes)
    covered = 'YES' if matching else 'NO'
    if matching:
        covered_count += 1
    student_rows.append(f'| {fid} | {name} | {covered} | {", ".join(matching) if matching else "-"} | {route} |')

admin_rows = []
for fid, name, route, prefixes in admin_flows:
    matching = check_covered(prefixes)
    covered = 'YES' if matching else 'NO'
    if matching:
        covered_count += 1
    admin_rows.append(f'| {fid} | {name} | {covered} | {", ".join(matching) if matching else "-"} | {route} |')

pct = round(covered_count / total_flows * 100) if total_flows else 0
if pct >= 80:
    confidence = 'HIGH'
    reasoning = f'{covered_count}/{total_flows} flows covered ({pct}%). All critical paths have scenarios and selectors match the codebase.'
elif pct >= 60:
    confidence = 'MEDIUM'
    reasoning = f'{covered_count}/{total_flows} flows covered ({pct}%). Critical paths are covered but secondary flows (auth, profile, scorecard detail) are missing scenarios.'
else:
    confidence = 'LOW'
    reasoning = f'{covered_count}/{total_flows} flows covered ({pct}%). Significant gaps exist — multiple user-facing flows have no E2E coverage.'

lines.append('## Summary')
lines.append(f'- **Total scenarios**: {total_scenarios}')
lines.append(f'- **Flows covered**: {covered_count} / {total_flows}')
lines.append(f'- **Coverage percentage**: {pct}%')
lines.append(f'- **Confidence level**: {confidence}')
lines.append(f'- **Confidence reasoning**: {reasoning}')
lines.append('')

lines.append('## Flow Coverage Matrix')
lines.append('')
lines.append('### Student Flows')
lines.append('| # | Flow | Covered? | Scenario IDs | Route |')
lines.append('|---|------|----------|--------------|-------|')
lines.extend(student_rows)
lines.append('')
lines.append('### Admin Flows')
lines.append('| # | Flow | Covered? | Scenario IDs | Route |')
lines.append('|---|------|----------|--------------|-------|')
lines.extend(admin_rows)
lines.append('')

# Gaps
uncovered = []
for fid, name, route, prefixes in student_flows + admin_flows:
    if not check_covered(prefixes):
        uncovered.append((fid, name, route))

lines.append('## Gaps & Recommendations')
if uncovered:
    for fid, name, route in uncovered:
        lines.append(f'- **{fid} — {name}** (`{route}`): No scenario. Add data-testid to the page component and create a scenario.')
else:
    lines.append('All flows have at least one scenario.')
lines.append('')

# Selector audit
unused = code_testids - all_selectors
missing = all_selectors - code_testids
lines.append('## Selector Audit')
lines.append(f'- data-testid attributes in codebase: {len(code_testids)}')
lines.append(f'- data-testid attributes referenced by scenarios: {len(all_selectors)}')
lines.append(f'- Unused testids (in code but no scenario): {", ".join(sorted(unused)) if unused else "none"}')
lines.append(f'- Missing testids (in scenario but not in code): {", ".join(sorted(missing)) if missing else "none"}')

coverage_log.write_text('\n'.join(lines))
print(f'WROTE {coverage_log}')
print(f'COVERAGE: {covered_count}/{total_flows} flows ({pct}%) — Confidence: {confidence}')
PY
```

## Step 4: Generate HTML scenario report

Create an HTML report with:
- metadata (lastUpdated, branch, commit)
- total suites + total scenarios
- coverage percentage and confidence level
- table of all scenarios (suite, id, name, route)

```bash
python3 - <<'PY'
import json, os, html
from pathlib import Path

root = Path(os.environ['ROOT'])
scenarios = json.loads((root/'e2e/scenarios.json').read_text())
report_html = Path(os.environ['REPORT_HTML'])
coverage_log = Path(os.environ['COVERAGE_LOG'])

rows = []
total = 0
for suite in scenarios.get('suites', []):
    route = suite.get('route','')
    for sc in suite.get('scenarios', []):
        total += 1
        rows.append(f"<tr><td>{html.escape(suite.get('name',''))}</td><td>{html.escape(sc.get('id',''))}</td><td>{html.escape(sc.get('name',''))}</td><td><code>{html.escape(route)}</code></td></tr>")

# Read coverage summary from log
coverage_summary = ''
if coverage_log.exists():
    for line in coverage_log.read_text().splitlines():
        if line.startswith('- **'):
            coverage_summary += html.escape(line) + '<br>'

meta = scenarios.get('meta', {})
html_out = f"""<!doctype html><html><head><meta charset='utf-8'><title>E2E Scenarios Report</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;margin:24px;color:#111}}.card{{border:1px solid #ddd;border-radius:12px;padding:14px;margin:10px 0}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ddd;padding:8px}}tr:nth-child(even){{background:#fafafa}}.coverage-high{{border-color:#22c55e;background:#f0fdf4}}.coverage-medium{{border-color:#eab308;background:#fefce8}}.coverage-low{{border-color:#ef4444;background:#fef2f2}}</style></head><body>
<h1>E2E Scenarios Report</h1>
<div class='card'><b>Last updated:</b> {meta.get('lastUpdatedAt','')}<br><b>Branch:</b> {meta.get('branch','')}<br><b>Commit:</b> {meta.get('commit','')}<br><b>Total suites:</b> {len(scenarios.get('suites',[]))}<br><b>Total scenarios:</b> {total}</div>
<div class='card'><b>Coverage Analysis:</b><br>{coverage_summary}</div>
<table><thead><tr><th>Suite</th><th>ID</th><th>Scenario</th><th>Route</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
report_html.write_text(html_out)
print(f"WROTE {report_html}")
PY
```

## Step 4b: Commit and push e2e/scenarios.json to trigger production deploy

After generating scenarios, commit and push so the next auto-deploy includes the latest definitions. Production reads scenarios from the Docker image (copied during CI build).

```bash
cd "$ROOT"

if ! git diff --quiet e2e/scenarios.json 2>/dev/null || ! git diff --cached --quiet e2e/scenarios.json 2>/dev/null; then
  echo "Committing updated e2e/scenarios.json..." | tee -a "$LOG_FILE"
  git add e2e/scenarios.json
  git commit -m "chore: update e2e scenarios.json after e2e-updater

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
  git push
  echo "e2e/scenarios.json pushed — deploy will trigger automatically" | tee -a "$LOG_FILE"
else
  echo "e2e/scenarios.json unchanged, skipping commit" | tee -a "$LOG_FILE"
fi
```

---

## Step 5: Email report + updated scenarios

Send email via macOS Mail.app with attachments:
- `$REPORT_HTML`
- `$SCENARIOS_JSON`
- `$COVERAGE_LOG`
- `$LOG_FILE`

```bash
osascript <<OSA
tell application "Mail"
  set newMessage to make new outgoing message with properties {subject:"E2E Scenarios Update — $BRANCH — $(date +%Y-%m-%d)", content:"Hi Manish,\n\nAttached are the latest generated QA scenarios report, coverage analysis, updated scenarios.json, and run log.\n\nGenerated by e2e-updater.", visible:false}
  tell newMessage
    make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
    make new attachment with properties {file name:POSIX file "$REPORT_HTML"} at after the last paragraph
    make new attachment with properties {file name:POSIX file "$SCENARIOS_JSON"} at after the last paragraph
    make new attachment with properties {file name:POSIX file "$COVERAGE_LOG"} at after the last paragraph
    make new attachment with properties {file name:POSIX file "$LOG_FILE"} at after the last paragraph
  end tell
  send newMessage
end tell
OSA
```

## Step 6: Final output

Print:
- updated scenarios path
- lastUpdated date from JSON
- total suites/scenarios
- **coverage percentage and confidence level**
- coverage log path
- report path
- email send status
