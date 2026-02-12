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
| `docs/backend-architecture.md` | Backend layers, key terms (service, agent, orchestration, repository), file conventions | Understanding code organization, where to add new code |
| `docs/dev-workflow.md` | Local setup, daily workflow, testing, making changes | Setting up dev environment, running tests, git workflow |
| `docs/deployment.md` | AWS infrastructure, CI/CD, production URLs, troubleshooting | Deploying, debugging prod issues, infrastructure questions |
| `docs/tech-stack-rationale.md` | Why each technology was chosen | Understanding tech decisions |
| `docs/TUTOR_WORKFLOW_PIPELINE.md` | Tutor feature: single master tutor agent, WebSocket + REST, evaluation pipeline | Working on tutoring sessions, agent logic, orchestration |
| `docs/BOOK_GUIDELINES_PIPELINE.md` | Book ingestion feature: OCR, topic detection, guideline extraction | Working on book upload, content extraction |

## Key Conventions

**Backend layers:** API → Service → Agent/Orchestration → Repository

**File naming:**
- `<entity>_repository.py` - Data access
- `<domain>_service.py` - Business logic
- `<role>_agent.py` - LLM-powered actors
- `orchestrator.py` - Agent orchestration

**Critical:** Always build Docker images with `--platform linux/amd64` for AWS deployment.
