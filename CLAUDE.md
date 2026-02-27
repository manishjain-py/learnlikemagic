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

## Documentation Index

| Doc | Purpose | When to Reference |
|-----|---------|-------------------|
| `docs/DOCUMENTATION_GUIDELINES.md` | Doc structure, writing rules, master index | Understanding doc organization |
| `docs/functional/app-overview.md` | What the app is, user journey, UX philosophy | App context, onboarding new people |
| `docs/functional/learning-session.md` | Tutoring experience from student POV | Understanding the tutor feature |
| `docs/functional/evaluation.md` | Tutor quality testing from admin POV | Understanding evaluation |
| `docs/functional/scorecard.md` | Student progress report | Understanding scorecard |
| `docs/functional/book-guidelines.md` | Book → guidelines → study plans from admin POV | Understanding content pipeline |
| `docs/functional/auth-and-onboarding.md` | Login, signup, onboarding | Understanding auth flows |
| `docs/technical/architecture-overview.md` | Full-stack architecture, tech stack, conventions | Code organization, adding new code |
| `docs/technical/learning-session.md` | Tutor pipeline technical details | Working on tutor code |
| `docs/technical/evaluation.md` | Evaluation pipeline technical details | Working on evaluation |
| `docs/technical/scorecard.md` | Scorecard service technical details | Working on scorecard |
| `docs/technical/book-guidelines.md` | Book/guidelines pipeline technical details | Working on content pipeline |
| `docs/technical/auth-and-onboarding.md` | Auth architecture, Cognito, APIs | Working on auth |
| `docs/technical/dev-workflow.md` | Local setup, testing, git workflow | Dev environment, testing |
| `docs/technical/deployment.md` | AWS infra, Terraform, CI/CD | Deploying, debugging prod |
| `docs/technical/database.md` | DB schema, migrations | Database changes |
| `docs/technical/ai-agent-files.md` | Agent context file inventory, update policy | Understanding/updating agent files |

## Key Conventions

**Backend layers:** API → Service → Agent/Orchestration → Repository

**File naming:**
- `<entity>_repository.py` - Data access
- `<domain>_service.py` - Business logic
- `<role>_agent.py` - LLM-powered actors
- `orchestrator.py` - Agent orchestration

**Critical:** Always build Docker images with `--platform linux/amd64` for AWS deployment.
