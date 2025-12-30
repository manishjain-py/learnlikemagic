# Learn Like Magic

AI-powered adaptive tutoring platform using LangGraph agents.

## What It Does

- **Adaptive Tutoring**: 3-agent system (Planner, Executor, Evaluator) dynamically adjusts to each student
- **Structured Guidelines**: Expert-authored teaching guidelines for consistent instruction
- **Real-time Assessment**: Instant grading with misconception identification
- **Book Ingestion**: Extract teaching guidelines from uploaded textbooks via OCR + AI

## Project Structure

```
learnlikemagic/
├── llm-backend/      # FastAPI + LangGraph (Python)
├── llm-frontend/     # React + TypeScript
├── infra/terraform/  # AWS infrastructure
└── docs/             # Documentation
```

## Quick Start

```bash
# Backend
cd llm-backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Add OPENAI_API_KEY, DATABASE_URL
python db.py --migrate && python db.py --seed-guidelines data/seed_guidelines.json
uvicorn main:app --reload  # http://localhost:8000

# Frontend
cd llm-frontend
npm install && npm run dev  # http://localhost:5173
```

## Documentation

| Doc | Purpose |
|-----|---------|
| [CLAUDE.md](CLAUDE.md) | Documentation index for AI assistants |
| [Backend Architecture](docs/backend-architecture.md) | Code organization, key terms, file conventions |
| [Dev Workflow](docs/dev-workflow.md) | Setup, testing, daily workflow |
| [Deployment](docs/deployment.md) | AWS infrastructure, CI/CD |
| [Tutor Pipeline](docs/TUTOR_WORKFLOW_PIPELINE.md) | 3-agent tutoring system |
| [Book Guidelines Pipeline](docs/BOOK_GUIDELINES_PIPELINE.md) | Book ingestion & extraction |
| [Tech Stack](docs/tech-stack-rationale.md) | Technology choices |

## Tech Stack

**Backend**: FastAPI, LangGraph, OpenAI (GPT-4o, GPT-5.2), PostgreSQL, SQLAlchemy

**Frontend**: React, TypeScript, Vite

**Infrastructure**: AWS App Runner, Aurora Serverless, S3, CloudFront, Terraform

## License

MIT
