# Backend Architecture

Quick reference for navigating the `llm-backend/` codebase.

---

## Project Structure

```
llm-backend/
├── tutor/                # Runtime tutoring sessions
├── book_ingestion/       # Book upload & guideline extraction
├── study_plans/          # Study plan generation
├── shared/               # Cross-module utilities
├── api/                  # Root API (health, curriculum)
├── tests/
├── main.py               # FastAPI app entrypoint
└── config.py
```

Each module follows the same internal structure:

```
<module>/
├── api/              # REST endpoints
├── services/         # Business logic
├── agents/           # LLM-powered actors (AI modules only)
├── orchestration/    # Agent coordination (AI modules only)
├── repositories/     # Database access
├── models/           # Pydantic schemas
└── prompts/          # LLM prompt templates
```

---

## Key Terms

### Repository
**Data access layer.** CRUD operations on database tables.

- One per entity (Session, Event, Guideline)
- Returns domain objects, not ORM models
- No business logic

```
repositories/<entity>_repository.py
```

### Service
**Business logic.** Coordinates repositories, agents, and external systems.

- Stateless (all state via parameters)
- Can call: repositories, other services, external APIs
- Cannot call: database directly, LLM directly

```
services/<domain>_service.py
```

### Agent
**LLM-powered actor.** Has a persona, prompt, and structured output.

- Roles: Planner, Executor, Evaluator
- Stateless (takes state in, returns typed output)
- Behavior defined via prompts, not code

```
agents/<role>_agent.py
```

### Orchestration
**Agent coordination.** Defines execution flow and state transitions.

- Uses LangGraph for state machine
- Routes between agents based on conditions
- Manages workflow state

```
orchestration/<workflow>_workflow.py
```

---

## The Modules

### Tutor (Runtime)
Real-time adaptive tutoring with students.

```
tutor/
├── agents/           # planner, executor, evaluator
├── orchestration/    # LangGraph workflow
├── services/         # session_service
└── api/              # /sessions, /logs
```

**Flow:** `Request → API → Service → Orchestration → Agents → Response`

### Book Ingestion (Offline)
Extract teaching guidelines from uploaded books.

```
book_ingestion/
├── services/         # OCR, extraction, sync
├── repositories/     # book-specific data
└── api/              # upload endpoints
```

**Flow:** `Upload → OCR → Topic Detection → Guideline Extraction → DB`

### Study Plans (Offline)
Generate study plans from guidelines.

```
study_plans/
├── services/         # generation, review
└── api/              # admin endpoints
```

**Flow:** `Guidelines → AI Generation → AI Review → DB`

### Shared
Cross-module components.

```
shared/
├── services/         # llm_service (OpenAI wrapper)
├── repositories/     # shared data access
├── models/           # common schemas
├── utils/            # constants, exceptions
└── prompts/          # shared templates
```

---

## Quick Lookup

| I need to...                     | Look in...                        |
|----------------------------------|-----------------------------------|
| Add an API endpoint              | `<module>/api/`                   |
| Add business logic               | `<module>/services/`              |
| Add AI capability                | `<module>/agents/`                |
| Change agent execution flow      | `<module>/orchestration/`         |
| Add database queries             | `<module>/repositories/`          |
| Add/modify data structures       | `<module>/models/`                |
| Change LLM prompts               | `<module>/prompts/` or `shared/prompts/` |

---

## Decision Guide

```
Where does this code go?

Database read/write?      → Repository
LLM-powered with persona? → Agent
Coordinating agents?      → Orchestration
HTTP endpoint?            → API
Everything else?          → Service
```

---

## Tech Stack

- **FastAPI** - Web framework
- **LangGraph** - Agent orchestration
- **OpenAI** - LLM provider (GPT-4o, GPT-5.2)
- **PostgreSQL** - Database (AWS Aurora)
- **SQLAlchemy** - ORM
- **Pydantic** - Data validation
