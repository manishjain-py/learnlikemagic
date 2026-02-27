Update all code-coupled agent context files to match the current codebase.

**Primary success criteria (non-negotiable):**
After this command runs, every `.agent/` file and `MEMORY.md` must accurately reflect the current codebase:
1. File counts, line counts, and module lists match reality.
2. API endpoint inventories are complete and correct.
3. Test counts, build commands, and known drift items are verified.
4. Audit metadata (date + commit baseline) is current on all `.agent/` files.

## AUTOMATION DIRECTIVE

This is a **fully automated pipeline**. The user will NOT be present to review plans, approve decisions, or give go-ahead between steps.

- **Do NOT** use `EnterPlanMode` or `AskUserQuestion` at any point.
- **Do NOT** pause for user confirmation between steps.
- Make all decisions autonomously.
- Execute every step end-to-end without stopping.
- If something fails, attempt to fix and retry (3 max).

---

## Step 0: Initialize

```bash
ROOT="$(pwd)"
BRANCH="$(git -C "$ROOT" branch --show-current)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
NOW="$(date '+%Y-%m-%d')"
echo "update-agent-files started on $BRANCH@$COMMIT at $NOW"
```

Read `docs/technical/ai-agent-files.md` to understand the full file inventory and update classification. Only **code-coupled** files get updated.

---

## Step 1: Launch 3 parallel sub-agents

Launch the following sub-agents **in parallel** using the Task tool. Each agent receives discovery instructions — it must glob/grep the actual codebase, not rely on hardcoded lists.

---

### Agent 1 — Repo Structure & File Indexes

**Updates:** `.agent/01-repo-map.md`, `.agent/07-file-indexes.md`

**Prompt:**

```
You are updating the LearnLikeMagic repo structure reference files. Read the current files, then verify every claim against the actual codebase.

Files to update:
- .agent/01-repo-map.md (repo layout, source footprint, domain maps)
- .agent/07-file-indexes.md (high-signal file index)

Discovery steps:
1. Read both current files to understand their structure.
2. Count Python files and lines in llm-backend/:
   find llm-backend -name "*.py" -not -path "*/venv/*" -not -path "*/__pycache__/*" | wc -l
   find llm-backend -name "*.py" -not -path "*/venv/*" -not -path "*/__pycache__/*" -exec cat {} + | wc -l
3. Count TypeScript/TSX files and lines in llm-frontend/src/:
   find llm-frontend/src -name "*.ts" -o -name "*.tsx" | wc -l
   find llm-frontend/src -name "*.ts" -o -name "*.tsx" -exec cat {} + | wc -l
4. Glob for top-level backend modules: llm-backend/tutor/, llm-backend/evaluation/, llm-backend/book_ingestion/, llm-backend/study_plans/, llm-backend/shared/, llm-backend/api/, llm-backend/scripts/
5. Glob for frontend feature dirs: llm-frontend/src/features/, llm-frontend/src/pages/, llm-frontend/src/components/
6. Check for any NEW top-level modules not in the current domain maps.
7. Verify every file listed in 07-file-indexes.md still exists. Remove stale entries, add new high-signal files.
8. Update both files with corrected counts, module lists, and file indexes.

Do NOT change the file structure/format — only update the data within the existing sections.
Do NOT touch the "Last audited" or "Code baseline" header lines — those get updated in a later step.
Report what changed and why.
```

---

### Agent 2 — APIs, Routes & Flows

**Updates:** `.agent/02-backend-api-and-flow.md`, `.agent/03-frontend-map.md`

**Prompt:**

```
You are updating the LearnLikeMagic API and route reference files. Read the current files, then verify every claim against the actual codebase.

Files to update:
- .agent/02-backend-api-and-flow.md (router inventory, runtime flow, LLM architecture)
- .agent/03-frontend-map.md (route tree, auth flow, API surface)

Discovery steps:
1. Read both current files to understand their structure.
2. Grep for include_router in llm-backend/main.py to find all registered routers.
3. For each router file found, read it and catalog all endpoints (method, path, description).
4. Grep for @router. and @app. decorators across llm-backend/ to catch any missed routes.
5. Grep for WebSocket in llm-backend/ for WebSocket endpoints.
6. Read llm-frontend/src/App.tsx for the React route tree.
7. Grep for <Route in llm-frontend/src/ to find all route definitions.
8. Grep for useNavigate|navigate\( in llm-frontend/src/ to find programmatic navigation.
9. Check for any NEW routers, endpoints, or frontend routes not in the current files.
10. Verify the tutoring runtime flow description matches the current code in llm-backend/tutor/.
11. Update both files with corrected endpoint inventories and route trees.

Do NOT change the file structure/format — only update the data within the existing sections.
Do NOT touch the "Last audited" or "Code baseline" header lines — those get updated in a later step.
Report what changed and why.
```

---

### Agent 3 — Ops, Testing, Playbooks & Drift

**Updates:** `.agent/04-ops-and-testing.md`, `.agent/05-change-playbooks.md`, `.agent/06-known-drift.md`, `MEMORY.md`

**Prompt:**

```
You are updating the LearnLikeMagic ops, testing, and drift reference files. Read the current files, then verify every claim against the actual codebase.

Files to update:
- .agent/04-ops-and-testing.md (setup commands, test counts, CI, deploy)
- .agent/05-change-playbooks.md (file touchpoints per change type)
- .agent/06-known-drift.md (doc/code drift items)
- MEMORY.md (baseline commit, stable facts)

Discovery steps:
1. Read all four current files to understand their structure.
2. Count test files:
   find llm-backend -name "test_*.py" -not -path "*/venv/*" | wc -l
   find llm-backend -name "test_*.py" -path "*/integration/*" | wc -l
3. Read llm-backend/Makefile for current build/test commands.
4. Read llm-frontend/package.json scripts section for npm commands.
5. Glob .github/workflows/*.yml to verify CI workflow list.
6. For each drift item in 06-known-drift.md, check if it's been fixed:
   - Read the specific files referenced in each drift item
   - Mark resolved items and note any new drift discovered
7. Verify file touchpoints in 05-change-playbooks.md — check that referenced files still exist.
8. Update MEMORY.md: set "Current baseline" to the current branch@commit (get from git rev-parse --short HEAD and git branch --show-current).
9. Update all four files with corrected data.

Do NOT change the file structure/format — only update the data within the existing sections.
Do NOT touch the "Last audited" or "Code baseline" header lines in .agent/ files — those get updated in a later step.
Report what changed and why.
```

---

## Step 2: Reconcile the master index

After all 3 agents complete, scan for agent context files that exist on disk but are missing from `docs/technical/ai-agent-files.md`.

**Discovery:**
1. Glob for all files in these locations:
   - Root: `*.md` (filter to agent-relevant files — SOUL, IDENTITY, USER, CLAUDE, AGENTS, GEMINI, MEMORY, HEARTBEAT, TOOLS, .claude.md)
   - `.agent/*.md`
   - `.claude/commands/*.md`
   - `.claude/settings.local.json`, `infra/.claude/settings.local.json`
   - `memory/*.md`
2. Compare the discovered file list against every file path mentioned in `docs/technical/ai-agent-files.md`.
3. For any **new files** not in the index:
   - Read the file to determine its purpose and update trigger classification (static / manual / code-coupled / automatic).
   - Add it to the correct category table in `docs/technical/ai-agent-files.md`.
4. For any **deleted files** still listed in the index:
   - Remove the row from the category table.
5. Log additions and removals.

---

## Step 3: Update audit metadata

After all 3 agents complete, update the header of every `.agent/*.md` file:

```
Last audited: <today's date YYYY-MM-DD>
Code baseline: `<branch>@<short-commit-hash>`
```

Use the branch and commit captured in Step 0.

For each `.agent/` file, find the existing `Last audited:` and `Code baseline:` lines and replace them with current values.

---

## Step 4: Summary

Print a concise summary:
- Files updated (list each with one-line change description)
- Files unchanged
- New drift items discovered (if any)
- Audit metadata: date and commit baseline applied
