# LLM Backend

FastAPI backend with LangGraph agents for adaptive tutoring.

## Project Structure

```
llm-backend/
├── tutor/                # Runtime tutoring (3-agent LangGraph system)
│   ├── agents/           # Planner, Executor, Evaluator
│   ├── orchestration/    # LangGraph workflow
│   └── services/         # Session management
├── book_ingestion/       # Book upload & guideline extraction
│   ├── services/         # OCR, boundary detection, merging
│   └── api/              # Upload endpoints
├── study_plans/          # Study plan generation
│   ├── services/         # Generator, Reviewer, Orchestrator
│   └── api/              # Admin endpoints
├── shared/               # Cross-module components
│   ├── services/         # LLMService (OpenAI wrapper)
│   ├── repositories/     # Shared data access
│   └── models/           # Common schemas
├── api/                  # Root-level routes (health, curriculum)
├── tests/
├── main.py               # FastAPI app entrypoint
├── config.py             # Settings
└── db.py                 # Database CLI
```

## Quick Start

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your OPENAI_API_KEY, DATABASE_URL

# Database
python db.py --migrate
python db.py --seed-guidelines data/seed_guidelines.json

# Run
uvicorn main:app --reload
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

## Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/health/db` | GET | Database health |
| `/curriculum` | GET | Discover subjects/topics/subtopics |
| `/sessions` | POST | Start tutoring session |
| `/sessions/{id}/step` | POST | Submit student response |
| `/sessions/{id}/summary` | GET | Session summary |
| `/admin/books/*` | * | Book management |
| `/admin/guidelines/*` | * | Guideline review |

## Documentation

| Doc | Purpose | When to Reference |
|-----|---------|-------------------|
| `../docs/backend-architecture.md` | Layers, key terms, file conventions | Understanding code organization |
| `../docs/dev-workflow.md` | Setup, testing, making changes | Development workflow |
| `../docs/deployment.md` | AWS, CI/CD, troubleshooting | Deploying to production |
| `../docs/TUTOR_WORKFLOW_PIPELINE.md` | 3-agent tutoring system | Working on tutor module |
| `../docs/BOOK_GUIDELINES_PIPELINE.md` | Book ingestion pipeline | Working on book_ingestion |

## Key Conventions

**Layers:** API → Service → Agent/Orchestration → Repository

**File naming:**
- `<entity>_repository.py` - Data access
- `<domain>_service.py` - Business logic
- `<role>_agent.py` - LLM-powered actors
- `<name>_workflow.py` - Agent orchestration

## Environment Variables

```bash
OPENAI_API_KEY=sk-...        # Required
DATABASE_URL=postgresql://...  # Required (or sqlite:///./tutor.db)
LLM_MODEL=gpt-4o-mini        # Optional
```

## Testing

```bash
export OPENAI_API_KEY=sk-test-dummy  # Required for imports
pytest                    # All tests
pytest -m unit            # Fast unit tests only
pytest --cov-report=html  # Coverage report
```

See `../docs/dev-workflow.md` for full testing guide.

## Docker

```bash
# Build (use AMD64 for AWS)
docker buildx build --platform linux/amd64 -t llm-backend .

# Run
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... -e DATABASE_URL=... llm-backend
```

See `../docs/deployment.md` for full deployment guide.
