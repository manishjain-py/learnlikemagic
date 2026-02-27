# AI Agent Context Files

How the ~31 files that give AI agents project context are organized, what each one does, and when they need updating.

---

## Overview

This repo contains a set of context files that AI coding agents (Claude Code, Gemini CLI, etc.) read at session start to understand the project, the user, and the codebase. These files live across four locations:

| Location | Purpose |
|----------|---------|
| Root (`/`) | Identity, persona, workspace rules, long-term memory |
| `.agent/` | Internal operator manual — repo map, API inventory, ops runbook, change playbooks |
| `.claude/commands/` | Automated skills invoked via `/command-name` |
| `.claude/`, `infra/.claude/` | Tool permissions and environment settings |
| `memory/` | Daily session logs |

Agents follow a **boot order** defined in `AGENTS.md` and `.agent/00-start-here.md`:
`SOUL.md → USER.md → AGENTS.md → memory files → .agent/ reference pack`

---

## File Inventory

### Identity & Persona

| File | Purpose | Update Trigger |
|------|---------|----------------|
| `SOUL.md` | Core persona: be helpful, have opinions, be resourceful, earn trust | Static — evolve when persona philosophy changes |
| `IDENTITY.md` | Agent name (Codex), creature type, vibe (pragmatic, direct) | Static — change when renaming the agent |
| `USER.md` | About the user: name, timezone, work style, preferences | Static — update when user preferences change |

### Operational Rules

| File | Purpose | Update Trigger |
|------|---------|----------------|
| `CLAUDE.md` | Project overview, doc index, backend layer pattern, file naming, Docker amd64 rule | Manual — update when adding new doc files or changing conventions |
| `.claude.md` | Detailed Claude Code instructions: architecture, deployment, code quality, testing checklist | Manual — update when stack or workflow changes significantly |
| `AGENTS.md` | Workspace-wide rules: boot order, memory management, safety, external actions, group chat | Manual — update when adding new agent workflows or rules |
| `GEMINI.md` | Gemini CLI mandates: boot order, research rules, execution validation, git ops | Manual — mirrors AGENTS.md for Gemini; update in parallel |

### Codebase Reference Pack (`.agent/`)

These files are **code-coupled** — they contain concrete counts, file paths, endpoint inventories, and test stats that drift as the codebase evolves. Updated by `/update-agent-files`.

| File | Purpose | Update Trigger |
|------|---------|----------------|
| `.agent/00-start-here.md` | Session boot order checklist, reference pack table of contents, scope guardrails | Code-coupled — update audit date/baseline after any refresh |
| `.agent/01-repo-map.md` | Repo layout, module ownership, source footprint (file counts, LOC), runtime entrypoints, domain maps | Code-coupled — update after adding/removing modules or significant code changes |
| `.agent/02-backend-api-and-flow.md` | Full router inventory, tutoring runtime flow, LLM provider architecture, session persistence, auth notes | Code-coupled — update after adding/changing API endpoints or routers |
| `.agent/03-frontend-map.md` | Route tree (public/protected/admin), auth flow, API surface, main UI domains, E2E coupling | Code-coupled — update after adding/changing frontend routes or pages |
| `.agent/04-ops-and-testing.md` | Local setup commands, Makefile/npm scripts, test inventory (unit/integration/E2E counts), CI workflows, deploy notes | Code-coupled — update after adding tests, changing build commands, or CI changes |
| `.agent/05-change-playbooks.md` | Concrete file touchpoints per change type (backend endpoint, tutoring behavior, auth, ingestion, eval, frontend, deploy, docs) | Code-coupled — update when file organization changes |
| `.agent/06-known-drift.md` | Verified doc/code drift items and operational risks | Code-coupled — update after fixing drift items or discovering new ones |
| `.agent/07-file-indexes.md` | High-signal file index for fast navigation: backend (38 files), frontend (8), E2E (3), infra/CI (4) | Code-coupled — update after adding/removing key files |

### Workflows & Skills (`.claude/commands/`)

| File | Purpose | Update Trigger |
|------|---------|----------------|
| `prd-generator.md` | Requirements → PRD doc with ambiguity discussion (interactive) | Manual — update when PRD template or process changes |
| `tech-impl-plan-generator.md` | PRD → technical implementation plan with build sequence | Manual — update when planning process changes |
| `code-implementer.md` | Tech plan → working code via orchestrator + sub-agents | Manual — update when implementation workflow changes |
| `update-all-docs.md` | Refresh all project docs via 7 parallel sub-agents | Manual — update when doc structure or areas change |
| `update-agent-files.md` | Refresh code-coupled `.agent/` files via 3 parallel sub-agents | Manual — update when agent file structure changes |
| `improve-with-feedback.md` | Feedback → persona → tutor fix → evaluate → report cycle | Manual — update when evaluation pipeline changes |
| `1-percent-better.md` | Iterative tutor improvement: measure → analyze → fix → measure → compare | Manual — update when evaluation dimensions change |
| `e2e-runner.md` | Start app, run Playwright E2E tests, upload to S3, email report | Manual — update when E2E infrastructure changes |
| `e2e-updater.md` | Generate/update `e2e/scenarios.json` from functional docs and codebase | Manual — update when E2E scenario format changes |
| `unit-test-runner.md` | Run pytest with coverage, build HTML report, email | Manual — update when test infrastructure changes |
| `unit-test-updater.md` | Generate/clean unit tests by priority tier to reach 80% coverage | Manual — update when test strategy changes |

### Memory

| File | Purpose | Update Trigger |
|------|---------|----------------|
| `MEMORY.md` | Curated long-term memory: workspace identity, stable facts, operational baselines | Code-coupled — update baseline commit and facts after significant changes |
| `HEARTBEAT.md` | Periodic task checklist (currently empty) | Manual — add tasks for periodic automated checks |
| `memory/YYYY-MM-DD.md` | Daily session logs (raw notes from each work session) | Automatic — created per session, old ones accumulate |

### Environment & Permissions

| File | Purpose | Update Trigger |
|------|---------|----------------|
| `.claude/settings.local.json` | Claude Code permission allowlist: 70+ bash commands, read paths, web access | Manual — update when new tools or paths are needed |
| `infra/.claude/settings.local.json` | Minimal permission allowlist for infra subdir (read + python) | Manual — update when infra tooling changes |

---

## Update Classification

| Classification | Meaning | Files | How Updated |
|----------------|---------|-------|-------------|
| **Static** | Rarely changes; only when philosophy/identity shifts | SOUL.md, IDENTITY.md, USER.md | Human edits directly |
| **Manual** | Changes when processes or conventions change | CLAUDE.md, .claude.md, AGENTS.md, GEMINI.md, HEARTBEAT.md, all commands/*.md, settings files | Human edits when making process changes |
| **Code-coupled** | Contains concrete code references (paths, counts, endpoints) that drift | `.agent/00–07`, MEMORY.md | Automated via `/update-agent-files` |
| **Automatic** | Created/appended by agent sessions | `memory/YYYY-MM-DD.md` | Created each session; no manual maintenance needed |

---

## Keeping Files Current

Run `/update-agent-files` after significant codebase changes (new modules, API endpoints, route changes, test additions). This skill:

1. Reads this index to understand the file inventory
2. Launches 3 parallel sub-agents to update code-coupled files
3. Reconciles this index — discovers new agent files on disk and adds them, removes deleted ones
4. Updates audit metadata (date + commit baseline) on all `.agent/` files

**When to run:**
- After adding/removing backend routers or endpoints
- After adding/removing frontend routes or pages
- After significant test additions or infrastructure changes
- Before onboarding a new agent or starting a major feature
- After any `/update-all-docs` run (docs and agent files should stay in sync)

**What it does NOT update:**
- Static files (SOUL.md, IDENTITY.md, USER.md) — these are human-authored
- Manual files (AGENTS.md, GEMINI.md, commands/) — these change with process, not code
- Daily memory logs — these are session artifacts
