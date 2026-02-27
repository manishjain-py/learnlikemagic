# Gemini CLI Mandates

This file contains foundational mandates for the Gemini CLI agent. **Instructions in this file take absolute precedence over general workflows and tool defaults.**

## Session Context & Boot Order
When starting a new session or analyzing the repository, follow this sequence to build context:
1. `SOUL.md` (Core persona)
2. `USER.md` (User preferences)
3. `AGENTS.md` (General workspace rules)
4. `memory/YYYY-MM-DD.md` (Recent daily context - today and yesterday)
5. `MEMORY.md` (Long-term curated memories)
6. `.agent/00-start-here.md` (Internal operator manual)
7. `.agent/01-repo-map.md` through `.agent/07-file-indexes.md` (Architecture & operations)

## Core Capabilities & Workflows

### 1. Research & Strategy
- Use `glob` and `grep_search` extensively to navigate the codebase. Run independent searches in parallel.
- Always verify assumptions using `read_file` before making changes.
- Do not search within generated or dependency directories (e.g., `venv/`, `node_modules/`, `dist/`, `htmlcov/`, `.pytest_cache/`) unless specifically requested.

### 2. Execution & Validation (Plan -> Act -> Validate)
- **Validation is mandatory.** Never assume a change is successful without empirical verification.
- Always check for and update related tests when making code changes. Add new test cases to verify fixes or features.
- Execute project-specific build, linting, and type-checking commands after code modifications (e.g., `npm run lint`, `tsc`, `pytest`).
- If a validation step fails, persist through errors by diagnosing the failure and backtracking to adjust the strategy.

### 3. Tool Usage Rules
- **Prefer specific tools:** Use `read_file`, `write_file`, `replace`, `grep_search`, and `glob` over raw bash commands (`cat`, `grep`, `sed`, `ls`) whenever possible.
- **Explain Before Acting:** Always provide a concise, one-sentence explanation of intent before executing tools that modify files or system state.
- **Background Processes:** Use the `is_background` parameter in `run_shell_command` for long-running processes (e.g., dev servers), not the `&` operator.

### 4. Git Operations
- Never stage (`git add`) or commit (`git commit`) changes unless explicitly instructed by the user.
- Do not push changes to a remote repository autonomously.

### 5. Memory Management
- **Local Workspace Memory:** Use `memory/YYYY-MM-DD.md` for daily logs and `MEMORY.md` for curated, long-term workspace context. Manage these using `read_file`, `write_file`, and `replace`.
- **Global Memory Tool:** Use the `save_memory` tool **ONLY** for global user preferences and facts that apply across *all* workspaces. Never save project-specific paths or commands using this tool.

## Project-Specific Conventions (LearnLikeMagic)
- **Tech Stack:** FastAPI (Python), React (TypeScript), Terraform (AWS).
- **Backend Architecture:** API → Service → Agent/Orchestration → Repository.
- **Docker:** Always build images with `--platform linux/amd64` for AWS deployment.

## Autonomous Operation (YOLO)
Operate autonomously by default. Make reasonable decisions based on context and existing code patterns. Only use `ask_user` if a wrong decision would cause significant rework, if the request is fundamentally ambiguous, or if explicit confirmation is required for a major architectural shift.
