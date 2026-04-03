# Claude Code Context

## Project Overview
LearnLikeMagic: AI-powered adaptive tutoring platform using a single master tutor agent.

## Codebase Structure
```
learnlikemagic/
├── llm-backend/          # FastAPI backend (Python)
├── llm-frontend/         # React frontend (TypeScript)
├── infra/terraform/      # AWS infrastructure
└── docs/                 # Documentation
```

## Principles

The `docs/principles/` folder captures the core vision and philosophy behind how the app works. These are the "why" behind design decisions — they should guide all implementation, even as features evolve or get rewritten. When building or changing any feature, always stay aligned with the relevant principles.

| Principle | Scope |
|-----------|-------|
| `docs/principles/how-to-explain.md` | How the tutor explains concepts to students |
| `docs/principles/breaking-down-chapters-into-topics.md` | How content is structured into teachable units |
| `docs/principles/interactive-teaching.md` | How the tutor behaves during live sessions (false OK detection, scaffolding, pacing) |
| `docs/principles/evaluation.md` | How tutor quality is measured (7 dimensions, persona-aware scoring) |
| `docs/principles/ux-design.md` | UX principles for all interfaces (mobile-first, warm language, minimal typing) |
| `docs/principles/scorecard.md` | How student progress is tracked (deterministic metrics only) |
| `docs/principles/content-extraction-from-books.md` | What to extract from books (full coverage, no copyrighted expression) |
| `docs/principles/book-ingestion-pipeline.md` | Operational principles for the multi-stage ingestion pipeline |
| `docs/principles/autoresearch.md` | How autonomous prompt optimization works |
| `docs/principles/prerequisites.md` | How prerequisite knowledge gaps are handled (refresher topics, warm-up framing) |

## Documentation Index

| Doc | Purpose | When to Reference |
|-----|---------|-------------------|
| `docs/DOCUMENTATION_GUIDELINES.md` | Doc structure, writing rules, master index | Understanding doc organization |
| `docs/functional/app-overview.md` | What the app is, user journey, UX philosophy | App context, onboarding new people |
| `docs/functional/learning-session.md` | Tutoring experience from student POV | Understanding the tutor feature |
| `docs/functional/evaluation.md` | Tutor quality testing from admin POV | Understanding evaluation |
| `docs/functional/scorecard.md` | Student progress report | Understanding scorecard |
| `docs/functional/auth-and-onboarding.md` | Login, signup, onboarding | Understanding auth flows |
| `docs/technical/architecture-overview.md` | Full-stack architecture, tech stack, conventions | Code organization, adding new code |
| `docs/technical/learning-session.md` | Tutor pipeline technical details | Working on tutor code |
| `docs/technical/evaluation.md` | Evaluation pipeline technical details | Working on evaluation |
| `docs/technical/scorecard.md` | Scorecard service technical details | Working on scorecard |
| `docs/technical/auth-and-onboarding.md` | Auth architecture, Cognito, APIs | Working on auth |
| `docs/technical/dev-workflow.md` | Local setup, testing, git workflow | Dev environment, testing |
| `docs/technical/deployment.md` | AWS infra, Terraform, CI/CD | Deploying, debugging prod |
| `docs/technical/database.md` | DB schema, migrations | Database changes |
| `docs/technical/ai-agent-files.md` | Agent context file inventory, update policy | Understanding/updating agent files |
| `docs/technical/auto-research/overview.md` | Autonomous prompt optimization system | Working on autoresearch |

## Key Conventions

**Backend layers:** API → Service → Agent/Orchestration → Repository

**File naming:**
- `<entity>_repository.py` - Data access
- `<domain>_service.py` - Business logic
- `<role>_agent.py` - LLM-powered actors
- `orchestrator.py` - Agent orchestration

**Critical:** Always build Docker images with `--platform linux/amd64` for AWS deployment.

## Claude Code as LLM Provider

When the admin dashboard is configured to use `claude_code` as the LLM provider, **always use Claude Code** — never silently switch to another provider (OpenAI, Anthropic API, etc.) without explicit user approval.

**Adapter:** `shared/services/claude_code_adapter.py` — calls the `claude` CLI as a subprocess.

Key rules for the adapter:
- **Strip ANTHROPIC_API_KEY from subprocess env** — this is critical. `load_dotenv()` in import chains sets `ANTHROPIC_API_KEY`, and the Claude Code CLI picks it up, authenticating via the API key (with low/no balance) instead of the user's Claude subscription. The adapter passes `env=clean_env` to subprocess to prevent this.
- **Prompt via stdin** (`input=` param in subprocess), not as a `-p` CLI argument. More robust for large/complex prompts.
- **Retry transient errors** — "credit balance", "rate limit", "overloaded" errors get exponential backoff (3 attempts, 10s base delay).
- **Always pass** `--dangerously-skip-permissions --no-session-persistence --max-turns 1 --output-format json`.
