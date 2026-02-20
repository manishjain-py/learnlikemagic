# Learn Like Magic

AI-powered adaptive tutoring platform using a single master tutor agent.

## What It Does

- **Adaptive Tutoring**: Single master tutor agent with safety gate dynamically adjusts to each student
- **Structured Guidelines**: Expert-authored teaching guidelines for consistent instruction
- **Real-time Assessment**: Instant grading with misconception identification
- **Book Ingestion**: Extract teaching guidelines from uploaded textbooks via OCR + AI
- **Evaluation Pipeline**: Evaluate tutoring sessions (existing or simulated) across 10 quality dimensions

## Project Structure

```
learnlikemagic/
├── llm-backend/      # FastAPI backend (Python)
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
python db.py --migrate
uvicorn main:app --reload  # http://localhost:8000

# Frontend
cd llm-frontend
npm install && npm run dev  # http://localhost:5173
```

## Documentation

| Doc | Purpose |
|-----|---------|
| [CLAUDE.md](CLAUDE.md) | Documentation index for AI assistants |
| [Documentation Guidelines](docs/DOCUMENTATION_GUIDELINES.md) | Doc structure, writing rules, master index |
| [Architecture Overview](docs/technical/architecture-overview.md) | Full-stack architecture, tech stack, conventions |
| [Dev Workflow](docs/technical/dev-workflow.md) | Setup, testing, daily workflow |
| [Deployment](docs/technical/deployment.md) | AWS infrastructure, CI/CD |
| [Tutor Pipeline](docs/technical/learning-session.md) | Single master tutor agent, orchestration, APIs |
| [Book Guidelines Pipeline](docs/technical/book-guidelines.md) | Book ingestion & extraction |
| [Database](docs/technical/database.md) | DB schema, migrations |

## Tech Stack

**Backend**: FastAPI, OpenAI (GPT-4o, GPT-5.2), Anthropic (Claude), PostgreSQL, SQLAlchemy

**Frontend**: React, TypeScript, Vite

**Infrastructure**: AWS App Runner, Aurora Serverless, S3, CloudFront, Terraform

## License

MIT
