# Architecture Guide

Quick reference for understanding and navigating the codebase.

---

## The 4 Layers

Every module in this codebase follows the same 4-layer structure:

```
┌─────────────────────────────────────────────────────────┐
│  API                                                    │
│  REST endpoints. Receives HTTP requests, returns JSON.  │
├─────────────────────────────────────────────────────────┤
│  Services                                               │
│  Business logic. Coordinates repositories, agents,      │
│  and external systems. No direct DB or LLM calls.       │
├─────────────────────────────────────────────────────────┤
│  Agents                (AI modules only)                │
│  LLM-powered actors. Each has a role, prompt, and       │
│  structured output. Stateless.                          │
├─────────────────────────────────────────────────────────┤
│  Orchestration         (AI modules only)                │
│  Coordinates agent execution. Defines flow, routing,    │
│  and state transitions. Uses LangGraph.                 │
├─────────────────────────────────────────────────────────┤
│  Repositories                                           │
│  Data access. CRUD operations on database tables.       │
│  One repository per entity/aggregate.                   │
└─────────────────────────────────────────────────────────┘
```

---

## Layer Definitions

### Repositories
**Purpose:** Data access layer. All database reads/writes go through here.

**Rules:**
- One repository per entity (Session, Event, Guideline, etc.)
- Methods return domain objects, not ORM models
- No business logic—just CRUD

**Example:**
```python
class SessionRepository:
    def get(self, session_id: str) -> Session | None
    def save(self, session: Session) -> None
    def update_mastery(self, session_id: str, score: float) -> None
```

**Naming:** `<entity>_repository.py`

---

### Services
**Purpose:** Business logic and orchestration. Coordinates other components.

**Rules:**
- Stateless—all state passed in/out via parameters
- Can call: repositories, other services, external APIs
- Cannot call: database directly, LLM directly (use agents)

**Types:**
| Type | Purpose | Example |
|------|---------|---------|
| Application Service | Coordinates use cases | `session_service.py` |
| Infrastructure Service | Wraps external APIs | `llm_service.py` |

**Example:**
```python
class SessionService:
    def create_session(self, request: CreateSessionRequest) -> SessionResponse:
        # 1. Validate request
        # 2. Call repository to persist
        # 3. Call orchestration to start workflow
        # 4. Return response
```

**Naming:** `<domain>_service.py`

---

### Agents
**Purpose:** LLM-powered task executors with specific roles.

**Rules:**
- Each agent has a persona (Planner, Executor, Evaluator)
- Uses prompts (declarative behavior via text, not code)
- Stateless—takes state in, returns structured output
- Calls LLMService, never the database

**Structure:**
```python
class PlannerAgent:
    role = "PLANNER"
    prompt_file = "planner.txt"
    output_schema = PlannerOutput

    def execute(self, state: WorkflowState) -> PlannerOutput:
        # 1. Extract context from state
        # 2. Load and format prompt
        # 3. Call LLM with structured output
        # 4. Return typed result
```

**Naming:** `<role>_agent.py`

---

### Orchestration
**Purpose:** Coordinates agent execution flow.

**Rules:**
- Defines which agents run, in what order, under what conditions
- Manages workflow state and transitions
- Uses LangGraph for state machine definition
- Contains adapters/bridges between API and workflow

**Components:**
| File | Purpose |
|------|---------|
| `tutor_workflow.py` | LangGraph state machine (nodes + edges) |
| `state.py` | Workflow state schema |
| `workflow_bridge.py` | API ↔ Workflow translation |
| `state_converter.py` | State format conversion |

**Naming:** `<workflow>_workflow.py` or `<workflow>_orchestrator.py`

---

## Module Structure

Each major feature follows this folder layout:

```
<module>/
├── api/              # REST endpoints
│   └── routes.py
├── services/         # Business logic
│   └── <name>_service.py
├── agents/           # LLM actors (if AI-powered)
│   ├── <role>_agent.py
│   └── prompts/
├── orchestration/    # Agent coordination (if AI-powered)
│   ├── workflow.py
│   └── state.py
├── repositories/     # Data access
│   └── <entity>_repository.py
└── models/           # Pydantic schemas
    └── schemas.py
```

---

## The Three Modules

### 1. Tutor (Runtime Tutoring)
Real-time adaptive tutoring sessions with students.

```
tutor/
├── api/              # /sessions, /logs endpoints
├── services/         # session_service.py
├── agents/           # planner, executor, evaluator
├── orchestration/    # LangGraph 4-node workflow
└── models/
```

**Flow:**
```
HTTP Request → API → SessionService → Orchestration → Agents → Response
```

### 2. Book Ingestion (Offline Pipeline)
Extract teaching guidelines from uploaded books.

```
book_ingestion/
├── api/              # Upload endpoints
├── services/         # OCR, extraction, sync
├── repositories/     # Book-specific data access
└── models/
```

**Flow:**
```
Book Upload → OCR → Topic Detection → Guideline Extraction → DB
```

### 3. Study Plans (Offline Pipeline)
Generate study plans from guidelines.

```
study_plans/
├── api/              # Admin endpoints
├── services/         # Generator, reviewer
└── models/
```

**Flow:**
```
Guidelines → AI Generation → AI Review → Approved Plan → DB
```

---

## Shared Components

Cross-cutting concerns used by all modules:

```
shared/
├── models/           # Common Pydantic/SQLAlchemy models
├── repositories/     # Shared data access (guidelines used by all)
├── services/         # llm_service.py (OpenAI wrapper)
├── utils/            # Constants, exceptions, formatting
└── prompts/          # Shared prompt templates
```

---

## Quick Reference

| I need to... | Look in... |
|--------------|------------|
| Add an API endpoint | `<module>/api/` |
| Add business logic | `<module>/services/` |
| Add an AI capability | `<module>/agents/` |
| Change agent execution order | `<module>/orchestration/` |
| Add database queries | `<module>/repositories/` |
| Add/modify data structures | `<module>/models/` |
| Change LLM prompts | `<module>/agents/prompts/` or `shared/prompts/` |

---

## Naming Conventions

| Component | Naming Pattern | Example |
|-----------|---------------|---------|
| Repository | `<entity>_repository.py` | `session_repository.py` |
| Service | `<domain>_service.py` | `session_service.py` |
| Agent | `<role>_agent.py` | `planner_agent.py` |
| Workflow | `<name>_workflow.py` | `tutor_workflow.py` |
| API Routes | `routes.py` or `<domain>.py` | `sessions.py` |
| Models | `schemas.py`, `domain.py` | — |

---

## Decision Guide

**"Where does this code go?"**

```
Is it database read/write?
  → Repository

Is it LLM-powered with a persona?
  → Agent

Is it coordinating multiple agents?
  → Orchestration

Is it an HTTP endpoint?
  → API

Everything else?
  → Service
```
