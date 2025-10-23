# LearnLikeMagic Backend Architecture

> **Comprehensive guide to the backend architecture, components, and code organization**
> **Last Updated:** October 23, 2025
> **Version:** 2.0 - Post-refactoring architecture

## Table of Contents

1. [Overview](#overview)
2. [High-Level Architecture](#high-level-architecture)
3. [Technology Stack](#technology-stack)
4. [Layered Architecture](#layered-architecture)
5. [Component Details](#component-details)
6. [Data Flow](#data-flow)
7. [Database Schema](#database-schema)
8. [LangGraph Agent System](#langgraph-agent-system)
9. [Design Principles](#design-principles)
10. [Code Organization](#code-organization)
11. [Key Workflows](#key-workflows)

---

## Overview

The LearnLikeMagic backend is a **FastAPI-based** adaptive tutoring system that uses **LangGraph** for orchestrating AI-driven educational conversations. It provides personalized, step-by-step tutoring experiences powered by OpenAI's GPT models.

### Core Capabilities

- 🎓 **Adaptive Learning**: Dynamic difficulty adjustment based on student performance
- 🤖 **AI-Driven Tutoring**: Natural language interactions using LLM
- 📊 **Progress Tracking**: Real-time mastery score calculation
- 🎯 **Curriculum-Based**: Structured learning following educational standards
- 📈 **Performance Analytics**: Session summaries and learning insights

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Client Layer                            │
│                     (Frontend / API Clients)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ HTTP/JSON
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer (FastAPI)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐     │
│  │   Health     │  │  Curriculum  │  │    Sessions       │     │
│  │  Endpoints   │  │  Discovery   │  │   Management      │     │
│  └──────────────┘  └──────────────┘  └───────────────────┘     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ Pydantic Models
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Service Layer                               │
│  ┌─────────────────────┐      ┌──────────────────────────┐     │
│  │  SessionService     │      │   GraphService           │     │
│  │  - Orchestration    │      │   - LangGraph execution  │     │
│  │  - Business logic   │      │   - Node coordination    │     │
│  └─────────────────────┘      └──────────────────────────┘     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ Domain Models
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Repository Layer                              │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │
│  │   Session      │  │     Event      │  │   Guideline      │  │
│  │  Repository    │  │   Repository   │  │   Repository     │  │
│  └────────────────┘  └────────────────┘  └──────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ SQLAlchemy ORM
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Database (PostgreSQL)                         │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌──────────────┐  │
│  │ sessions │  │  events  │  │  content   │  │  guidelines  │  │
│  └──────────┘  └──────────┘  └────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘

                    External Services
┌──────────────────┐              ┌─────────────────┐
│   OpenAI API     │              │  LangGraph      │
│   (GPT-4o-mini)  │              │  (Agent System) │
└──────────────────┘              └─────────────────┘
```

---

## Technology Stack

### Core Framework
- **FastAPI** (0.104+) - Modern Python web framework with automatic OpenAPI docs
- **Uvicorn** - ASGI server for production deployment
- **Pydantic** (2.0+) - Data validation and settings management

### AI/LLM Integration
- **LangGraph** (0.2+) - Agent orchestration framework for state-based workflows
- **LangChain Core** (0.3+) - LLM utilities and abstractions
- **OpenAI Python SDK** (1.0+) - GPT-4o-mini API integration

### Database
- **SQLAlchemy** (2.0+) - ORM for database operations
- **PostgreSQL** - Production database (AWS Aurora)
- **psycopg2-binary** - PostgreSQL adapter

### Development Tools
- **pytest** - Testing framework with fixtures and coverage
- **pytest-asyncio** - Async test support
- **pytest-cov** - Coverage reporting
- **black** - Code formatter
- **mypy** - Type checker
- **flake8** - Linter

---

## Layered Architecture

The backend follows a **4-layer architecture** with clear separation of concerns:

### 1. API Layer (`api/routes/`)

**Responsibility:** HTTP request/response handling

- Route definitions and URL mapping
- Request validation (Pydantic schemas)
- Response serialization
- Error handling and status codes

**Key Files:**
- `api/routes/health.py` - Health check endpoints
- `api/routes/curriculum.py` - Curriculum discovery
- `api/routes/sessions.py` - Session CRUD operations

**Example:**
```python
@router.post("/sessions", response_model=CreateSessionResponse)
def create_session(request: CreateSessionRequest, db: Session = Depends(get_db)):
    service = SessionService(db)
    return service.create_new_session(request)
```

### 2. Service Layer (`services/`)

**Responsibility:** Business logic orchestration

- Coordinate multiple repositories
- Execute complex workflows
- Apply business rules
- Transform data between layers

**Key Files:**
- `services/session_service.py` - Session lifecycle management
- `services/graph_service.py` - LangGraph execution coordination

**Example:**
```python
class SessionService:
    def create_new_session(self, request: CreateSessionRequest):
        # 1. Validate guideline exists
        # 2. Initialize tutor state
        # 3. Generate first question via graph
        # 4. Persist session
        # 5. Return first turn
```

### 3. Repository Layer (`repositories/`)

**Responsibility:** Data access abstraction

- Database CRUD operations
- Query construction
- ORM interactions
- Data mapping (ORM ↔ Domain models)

**Key Files:**
- `repositories/session_repository.py` - Session data access
- `repositories/event_repository.py` - Event logging
- `repositories/guideline_repository.py` - Curriculum queries

**Example:**
```python
class SessionRepository:
    def create(self, session_id: str, state: TutorState) -> SessionModel:
        session = SessionModel(
            id=session_id,
            state_json=state.model_dump_json(),
            mastery=state.mastery_score,
            step_idx=state.step_idx
        )
        self.db.add(session)
        self.db.commit()
        return session
```

### 4. Database Layer (`models/database.py`)

**Responsibility:** Data persistence schema

- SQLAlchemy ORM models
- Table definitions
- Relationships and constraints
- Database migrations

---

## Component Details

### Core Components

#### 1. **Session Management**

Manages the lifecycle of tutoring sessions from creation to completion.

**Components:**
- `SessionService` - High-level session orchestration
- `SessionRepository` - Session data persistence
- `Session` (ORM) - Database model
- `TutorState` (Domain) - In-memory state representation

**Flow:**
```
POST /sessions
    ↓
SessionService.create_new_session()
    ↓
GuidelineRepository.get_by_id() - Fetch teaching guideline
    ↓
GraphService.execute_present_node() - Generate first question
    ↓
SessionRepository.create() - Persist to database
    ↓
Return CreateSessionResponse
```

#### 2. **LangGraph Agent System**

Orchestrates the adaptive tutoring workflow using a state machine.

**Nodes:**
- `present` - Generate teaching turn
- `check` - Grade student response
- `diagnose` - Update evidence and mastery
- `advance` - Move to next concept
- `remediate` - Provide scaffolding

**State Management:**
```python
class TutorState(BaseModel):
    session_id: str
    student: Student
    goal: Goal
    step_idx: int
    history: List[HistoryEntry]
    evidence: List[Evidence]
    mastery_score: float
    last_grading: Optional[GradingResult]
    next_action: str
```

**Routing Logic:**
```python
def route_after_check(state):
    grading = state["last_grading"]
    if grading["score"] >= 0.8 and grading["confidence"] >= 0.6:
        return "advance"
    else:
        return "remediate"
```

#### 3. **Prompt Management**

LLM prompts are externalized as template files for easy versioning and A/B testing.

**Structure:**
```
prompts/
├── templates/
│   ├── teaching_prompt.txt      # Present node system prompt
│   ├── grading_prompt.txt       # Check node system prompt
│   ├── remediation_prompt.txt   # Remediate helper prompt
│   └── fallback_responses.json  # Default responses
└── loader.py                    # PromptLoader class
```

**Usage:**
```python
from prompts.loader import PromptLoader

system_prompt = PromptLoader.load("teaching_prompt")
response = llm.generate(system_prompt, user_message)
```

#### 4. **Curriculum Discovery**

Provides hierarchical curriculum browsing (Country → Board → Grade → Subject → Topic → Subtopic).

**API Endpoints:**
```
GET /curriculum?country=India&board=CBSE&grade=3
    → {"subjects": ["Mathematics", "English"]}

GET /curriculum?...&subject=Mathematics
    → {"topics": ["Fractions", "Multiplication"]}

GET /curriculum?...&topic=Fractions
    → {"subtopics": [{"subtopic": "...", "guideline_id": "g1"}]}
```

**Repository Methods:**
```python
class GuidelineRepository:
    def get_subjects(country, board, grade) -> List[str]
    def get_topics(country, board, grade, subject) -> List[str]
    def get_subtopics(...) -> List[SubtopicWithGuideline]
    def get_guideline_by_id(id) -> TeachingGuideline
```

---

## Data Flow

### Session Creation Flow

```
1. Client sends POST /sessions
   {
     "student": {"id": "s1", "grade": 3},
     "goal": {"topic": "Fractions", "guideline_id": "g1"}
   }

2. API Layer (sessions.py)
   - Validates CreateSessionRequest
   - Passes to SessionService

3. Service Layer (session_service.py)
   - Fetches teaching guideline from GuidelineRepository
   - Initializes TutorState with default values
   - Calls GraphService.execute_present_node()

4. Graph Layer (graph_service.py)
   - Pre-loads guideline into graph state
   - Executes present node via LangGraph

5. LangGraph Node (nodes.py:present_node)
   - Loads teaching_prompt.txt template
   - Formats conversation history
   - Calls OpenAI API with system + user prompt
   - Parses structured JSON response

6. Back to Service Layer
   - Extracts first turn from state
   - Persists via SessionRepository.create()

7. Repository Layer (session_repository.py)
   - Converts TutorState to SessionModel (ORM)
   - Inserts into PostgreSQL database
   - Commits transaction

8. Response
   {
     "session_id": "uuid",
     "first_turn": {
       "message": "Let's learn fractions!",
       "hints": ["..."],
       "step_idx": 0
     }
   }
```

### Session Step Flow

```
1. Client sends POST /sessions/{id}/step
   {"student_reply": "5/8 is bigger"}

2. API Layer
   - Validates StepRequest
   - Passes to SessionService.process_step()

3. Service Layer
   - Fetches existing session from SessionRepository
   - Deserializes TutorState from state_json
   - Calls GraphService.execute_step_workflow()

4. GraphService executes graph:
   a. check_node()
      - Calls OpenAI to grade response
      - Returns GradingResult (score, rationale)

   b. diagnose_node()
      - Updates evidence list
      - Recalculates mastery score (EMA)

   c. route_after_check()
      - If score >= 0.8: → advance_node()
      - Else: → remediate_node()

   d. present_node()
      - Generates next teaching turn

5. Service Layer
   - Updates session via SessionRepository.update()
   - Logs step event via EventRepository.log()
   - Builds StepResponse

6. Response
   {
     "next_turn": {"message": "...", "step_idx": 1},
     "routing": "Advance",
     "last_grading": {"score": 1.0, "rationale": "..."}
   }
```

---

## Database Schema

### Entity-Relationship Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      teaching_guidelines                     │
├─────────────────────────────────────────────────────────────┤
│ id (PK)              VARCHAR                                 │
│ country              VARCHAR                                 │
│ board                VARCHAR                                 │
│ grade                INTEGER                                 │
│ subject              VARCHAR                                 │
│ topic                VARCHAR                                 │
│ subtopic             VARCHAR                                 │
│ guideline            TEXT                                    │
│ metadata_json        TEXT                                    │
│ created_at           TIMESTAMP                               │
├─────────────────────────────────────────────────────────────┤
│ INDEX: idx_curriculum (country, board, grade, subject, topic)│
└─────────────────────────────────────────────────────────────┘
                              │
                              │ guideline_id (FK)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                         sessions                             │
├─────────────────────────────────────────────────────────────┤
│ id (PK)              VARCHAR                                 │
│ student_json         TEXT        {id, grade, prefs}          │
│ goal_json            TEXT        {topic, objectives}         │
│ state_json           TEXT        Full TutorState             │
│ mastery              FLOAT       Current mastery score       │
│ step_idx             INTEGER     Current step number         │
│ created_at           TIMESTAMP                               │
│ updated_at           TIMESTAMP                               │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      │ session_id (FK)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                          events                              │
├─────────────────────────────────────────────────────────────┤
│ id (PK)              VARCHAR                                 │
│ session_id (FK)      VARCHAR     → sessions.id              │
│ node                 VARCHAR     Node name (present, check)  │
│ step_idx             INTEGER     When event occurred         │
│ payload_json         TEXT        Node input/output           │
│ created_at           TIMESTAMP                               │
├─────────────────────────────────────────────────────────────┤
│ INDEX: idx_session_step (session_id, step_idx)              │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **JSON Storage** - `student_json`, `goal_json`, `state_json` store complex objects as JSON
   - **Pros**: Schema flexibility, faster writes, no joins
   - **Cons**: No querying nested fields (acceptable trade-off)

2. **Denormalized `mastery` and `step_idx`** - Duplicated from `state_json` for indexing
   - Enables efficient queries: `WHERE mastery >= 0.85 ORDER BY step_idx DESC`

3. **Event Sourcing Pattern** - All node executions logged in `events` table
   - Enables audit trail and replay capabilities
   - Supports analytics and debugging

---

## LangGraph Agent System

### Graph Definition

```python
workflow = StateGraph(GraphState)

# Add nodes
workflow.add_node("present", present_node)
workflow.add_node("check", check_node)
workflow.add_node("diagnose", diagnose_node)
workflow.add_node("advance", advance_node)
workflow.add_node("remediate", remediate_node)

# Define edges
workflow.set_entry_point("present")
workflow.add_edge("present", "check")
workflow.add_conditional_edges(
    "check",
    route_after_check,
    {"advance": "advance", "remediate": "remediate"}
)
workflow.add_edge("advance", route_after_advance)
workflow.add_edge("remediate", "diagnose")
workflow.add_edge("diagnose", "present")

graph = workflow.compile()
```

### Node Details

#### 1. **present_node** (Teaching Turn Generation)

**Purpose:** Generate contextual teaching question/explanation

**Inputs:**
- `student` - Student profile (grade, preferences)
- `goal` - Learning objectives
- `history` - Conversation history
- `teaching_guideline` - Curriculum content

**Process:**
1. Load `teaching_prompt.txt` template
2. Format conversation history
3. Call OpenAI API with structured output
4. Parse JSON response

**Output:**
```json
{
  "message": "Let's explore fractions! ...",
  "hints": ["Remember the denominator...", "..."],
  "expected_answer_form": "short_text"
}
```

#### 2. **check_node** (Response Grading)

**Purpose:** Evaluate student's answer

**Inputs:**
- `student_reply` - Student's response
- `last_teacher_message` - Context for grading

**Process:**
1. Load `grading_prompt.txt` template
2. Call OpenAI API for evaluation
3. Parse structured grading

**Output:**
```json
{
  "score": 0.85,
  "rationale": "Student correctly identified...",
  "labels": ["correct_comparison"],
  "confidence": 0.9
}
```

#### 3. **diagnose_node** (State Update)

**Purpose:** Update learning evidence and mastery score

**Process:**
1. Append grading to evidence list
2. Calculate new mastery using EMA:
   ```python
   mastery = ALPHA * score + (1 - ALPHA) * prev_mastery
   ```
3. Update next_action based on mastery

**No LLM call** - Pure function

#### 4. **advance_node** (Progression)

**Purpose:** Move to next concept when student demonstrates understanding

**Process:**
1. Increment step_idx
2. Update goal if applicable
3. Set next_action = "present"

**No LLM call** - Pure function

#### 5. **remediate_node** (Scaffolding)

**Purpose:** Provide hints and simpler explanation

**Inputs:**
- Current grading result
- Last teacher message

**Process:**
1. Load `remediation_prompt.txt`
2. Call OpenAI for simplified explanation
3. Add to history as hint

**Output:** Enhanced hints for struggling students

---

## Design Principles

### 1. **Single Responsibility Principle (SRP)**

Each module has one clear purpose:
- `SessionService` - Session orchestration only
- `SessionRepository` - Session data access only
- `present_node` - Teaching turn generation only

### 2. **Dependency Injection**

Dependencies passed as parameters for testability:
```python
class SessionService:
    def __init__(self, db: Session):
        self.db = db
        self.session_repo = SessionRepository(db)
        self.event_repo = EventRepository(db)
        self.guideline_repo = GuidelineRepository(db)
```

### 3. **Separation of Concerns**

Clear boundaries between layers:
- API Layer: HTTP only
- Service Layer: Business logic only
- Repository Layer: Database only
- Graph Nodes: State transformation only

### 4. **Don't Repeat Yourself (DRY)**

Shared utilities for common operations:
- `utils/formatting.py` - History formatting
- `utils/constants.py` - Magic numbers
- `prompts/loader.py` - Template loading

### 5. **Pure Functions**

Graph nodes are stateless transformations:
```python
def diagnose_node(state: GraphState) -> GraphState:
    # Input: state dict
    # Output: new state dict
    # No side effects (DB, API calls, globals)
```

### 6. **Fail Fast**

Validate early with Pydantic:
```python
class CreateSessionRequest(BaseModel):
    student: Student  # Validated on parsing
    goal: Goal        # Type checking enforced
```

---

## Code Organization

### Directory Structure

```
llm-backend/
├── api/                         # API Layer
│   └── routes/
│       ├── health.py            # Health checks
│       ├── curriculum.py        # Curriculum API
│       └── sessions.py          # Session API
│
├── services/                    # Service Layer
│   ├── session_service.py       # Session orchestration
│   └── graph_service.py         # Graph execution
│
├── repositories/                # Repository Layer
│   ├── session_repository.py    # Session CRUD
│   ├── event_repository.py      # Event logging
│   └── guideline_repository.py  # Curriculum queries
│
├── models/                      # Data Models
│   ├── database.py              # SQLAlchemy ORM models
│   ├── domain.py                # Business logic models
│   └── schemas.py               # API request/response schemas
│
├── graph/                       # LangGraph Components
│   ├── state.py                 # State definitions
│   ├── nodes.py                 # Node implementations
│   └── build_graph.py           # Graph compilation
│
├── prompts/                     # LLM Prompts
│   ├── templates/               # Prompt template files
│   │   ├── teaching_prompt.txt
│   │   ├── grading_prompt.txt
│   │   └── remediation_prompt.txt
│   └── loader.py                # PromptLoader class
│
├── utils/                       # Shared Utilities
│   ├── formatting.py            # History formatting
│   ├── constants.py             # Centralized constants
│   └── exceptions.py            # Custom exceptions
│
├── tests/                       # Test Suite
│   ├── conftest.py              # Pytest fixtures
│   ├── unit/                    # Unit tests
│   └── integration/             # Integration tests
│
├── main.py                      # FastAPI app (66 lines!)
├── database.py                  # Database manager
├── config.py                    # Configuration
├── llm.py                       # OpenAI provider
└── requirements.txt             # Dependencies
```

### Import Conventions

```python
# External libraries
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

# Local packages (absolute imports)
from database import get_db
from models import CreateSessionRequest, CreateSessionResponse
from services import SessionService
from utils.constants import MAX_STEPS
```

---

## Key Workflows

### 1. New Session Creation

```
User Request → API → SessionService → GuidelineRepository
                                    ↓
                              GraphService
                                    ↓
                           present_node (LLM)
                                    ↓
                         SessionRepository.create()
                                    ↓
                              Response to User
```

### 2. Student Response Processing

```
User Response → API → SessionService.process_step()
                               ↓
                    SessionRepository.get_by_id()
                               ↓
                   GraphService.execute_step_workflow()
                               ↓
                    ┌──────────┴──────────┐
                    ▼                     ▼
              check_node (LLM)      diagnose_node
                    │                     │
                    ▼                     ▼
              route_after_check    update mastery
                    │                     │
          ┌─────────┴─────────┐          │
          ▼                   ▼          │
    advance_node       remediate_node ───┘
          │                   │
          └─────────┬─────────┘
                    ▼
             present_node (LLM)
                    ▼
         SessionRepository.update()
                    ▼
              Response to User
```

### 3. Session Summary Generation

```
User Request → API → SessionService.get_summary()
                               ↓
                    SessionRepository.get_by_id()
                               ↓
                    Extract from state_json:
                    - steps_completed
                    - mastery_score
                    - evidence (misconceptions)
                               ↓
                    Generate suggestions
                               ↓
                         Response to User
```

---

## Performance Considerations

### 1. **Database Connection Pooling**

```python
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,           # Max simultaneous connections
    max_overflow=10,       # Extra connections under load
    pool_timeout=30,       # Wait time before error
    pool_pre_ping=True     # Verify connection health
)
```

### 2. **LLM Call Optimization**

- **Prompt Caching**: PromptLoader caches templates in memory
- **Structured Outputs**: Use JSON mode to avoid parsing errors
- **Async Support**: Ready for async/await pattern (future enhancement)

### 3. **JSON Serialization**

- Pydantic `model_dump_json()` for fast serialization
- SQLAlchemy `Text` columns for large JSON objects
- No unnecessary deserialization (stored as string until needed)

### 4. **Indexing Strategy**

```sql
-- Fast curriculum queries
CREATE INDEX idx_curriculum ON teaching_guidelines
    (country, board, grade, subject, topic);

-- Fast event lookups
CREATE INDEX idx_session_step ON events
    (session_id, step_idx);
```

---

## Security & Best Practices

### 1. **Environment Variables**

All secrets in `.env` (gitignored):
```bash
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://...
```

### 2. **Input Validation**

Pydantic models validate all inputs:
```python
class CreateSessionRequest(BaseModel):
    student: Student        # Type-checked
    goal: Goal             # Validated structure

    @validator('student')
    def validate_student(cls, v):
        if v.grade < 1 or v.grade > 12:
            raise ValueError("Grade must be 1-12")
        return v
```

### 3. **Error Handling**

Custom exceptions with HTTP mapping:
```python
class SessionNotFoundException(LearnLikeMagicException):
    def to_http_exception(self) -> HTTPException:
        return HTTPException(status_code=404, detail=self.message)
```

### 4. **Logging**

Structured logging at key points:
```python
logger.info(f"Creating session for student {student_id}")
logger.error(f"Failed to create session: {error}")
```

---

## Testing Strategy

### 1. **Unit Tests** (`tests/unit/`)

Test individual functions in isolation:
```python
def test_format_conversation_history():
    history = [{"role": "teacher", "msg": "Hello"}]
    result = format_conversation_history(history)
    assert "Teacher: Hello" in result
```

### 2. **Integration Tests** (`tests/integration/`)

Test component interactions:
```python
def test_create_session_flow(db_session, mock_llm):
    service = SessionService(db_session)
    response = service.create_new_session(request)
    assert response.session_id is not None
```

### 3. **Fixtures** (`tests/conftest.py`)

Reusable test data:
```python
@pytest.fixture
def sample_tutor_state():
    return TutorState(
        session_id="test-123",
        student=sample_student(),
        goal=sample_goal(),
        ...
    )
```

---

## Deployment Architecture

### Production Setup (AWS)

```
┌─────────────────────────────────────────────────────────┐
│               CloudFront (CDN)                          │
│            Frontend Distribution                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTPS
                     ▼
┌─────────────────────────────────────────────────────────┐
│            AWS App Runner                               │
│       (Serverless Container Service)                    │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │   FastAPI Backend (Docker Container)           │    │
│  │   - Auto-scaling (0-25 instances)              │    │
│  │   - Health checks                              │    │
│  │   - Automatic deployments                      │    │
│  └────────────────────────────────────────────────┘    │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ VPC Connection
                     ▼
┌─────────────────────────────────────────────────────────┐
│          AWS Aurora PostgreSQL                          │
│       (Production Database Cluster)                     │
│  - Multi-AZ for high availability                       │
│  - Automated backups                                    │
│  - Read replicas                                        │
└─────────────────────────────────────────────────────────┘
```

### CI/CD Pipeline

```
Developer Push to main
        ↓
   GitHub Actions
        ↓
   Build Docker Image (AMD64)
        ↓
   Push to ECR (Container Registry)
        ↓
   Trigger App Runner Deployment
        ↓
   Health Check (30s timeout)
        ↓
   Route Traffic to New Version
```

---

## Future Enhancements

### Planned Improvements

1. **Async/Await Pattern**
   - Convert to async FastAPI endpoints
   - Async LLM calls for better concurrency

2. **Caching Layer**
   - Redis for session state caching
   - Reduce database reads

3. **Rate Limiting**
   - Per-user request limits
   - OpenAI API quota management

4. **Observability**
   - Distributed tracing (OpenTelemetry)
   - Metrics dashboard (Prometheus/Grafana)

5. **Advanced Analytics**
   - Student learning patterns
   - Curriculum effectiveness metrics

---

## References

### Documentation
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [Pydantic Docs](https://docs.pydantic.dev/)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)

### Related Documents
- [Development Workflow](./dev-workflow.md)
- [Deployment Guide](./deployment.md)
- [Backend README](../llm-backend/README.md)

---

**Document Version:** 1.0
**Author:** LearnLikeMagic Team
**Last Updated:** October 23, 2025
