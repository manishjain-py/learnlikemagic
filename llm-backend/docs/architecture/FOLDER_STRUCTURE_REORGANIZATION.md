# LLM-Backend Folder Structure Reorganization

## Document Purpose
Implementation plan for reorganizing the llm-backend folder structure into clear, consistent modules following our 4-layer architecture.

**Related:** See [ARCHITECTURE.md](../ARCHITECTURE.md) for layer definitions and conventions.

---

## 1. Context: Current State

### 1.1 Overview
The codebase has two distinct workflows that currently share a flat structure, making boundaries unclear.

### 1.2 Two Core Workflows

#### A. Tutor Workflow (Runtime)
Real-time adaptive tutoring using LangGraph with 3 AI agents.

```
Student Request → SessionService → Orchestration → Agents → Response
                                        ↓
                    ROUTER → PLANNER → EXECUTOR → EVALUATOR
```

#### B. Guideline Generation (Offline)
Extract guidelines from books, generate study plans.

```
Book Upload → OCR → Topic Detection → Guideline Extraction → DB
                                                              ↓
                                          Study Plan Generation
```

### 1.3 Current Structure (Problems)

```
llm-backend/
├── adapters/           # Tutor-specific, but generic name
├── agents/             # Tutor-specific
├── workflows/          # Tutor-specific
├── services/           # Mixed (session + llm)
├── api/routes/         # Mixed
├── features/           # Guidelines, nested 4+ levels deep
│   ├── book_ingestion/
│   │   ├── api/
│   │   ├── models/
│   │   ├── repositories/
│   │   └── services/
│   └── study_plans/
├── routers/            # Another router location
├── models/             # Shared
├── repositories/       # Shared
└── ...
```

**Issues:**
1. Unclear which files belong to which workflow
2. Inconsistent structure (tutor = flat, guidelines = nested)
3. `adapters/` is tutor-specific but sounds generic
4. `features/book_ingestion/` has 4+ levels of nesting
5. Multiple router locations (`api/routes/`, `routers/`, `features/*/api/`)

---

## 2. Goal

Reorganize into **4 clear modules** following consistent 4-layer architecture:

| Module | Purpose |
|--------|---------|
| `shared/` | Components used by multiple modules |
| `tutor/` | Runtime tutoring workflow |
| `book_ingestion/` | Book → Guidelines pipeline |
| `study_plans/` | Guidelines → Study Plans pipeline |

Each module follows the same internal structure (see ARCHITECTURE.md).

---

## 3. Target Structure

```
llm-backend/
├── main.py                     # FastAPI app entry point
├── config.py                   # Configuration
├── database.py                 # SQLAlchemy setup
│
├── shared/                     # CROSS-CUTTING CONCERNS
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── entities.py         # SQLAlchemy ORM (renamed from database.py)
│   │   ├── domain.py           # Core business objects
│   │   └── schemas.py          # Shared API schemas
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── session_repository.py
│   │   ├── event_repository.py
│   │   └── guideline_repository.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── llm_service.py      # OpenAI/Gemini wrapper
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── constants.py
│   │   ├── exceptions.py
│   │   └── formatting.py
│   └── prompts/
│       ├── __init__.py
│       ├── loader.py
│       └── templates/          # Shared prompt files
│
├── tutor/                      # TUTOR WORKFLOW MODULE
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── sessions.py         # Session endpoints
│   │   ├── logs.py             # Agent log endpoints
│   │   └── curriculum.py       # Curriculum endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   └── session_service.py  # Application service
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseAgent class
│   │   ├── planner_agent.py
│   │   ├── executor_agent.py
│   │   ├── evaluator_agent.py
│   │   ├── schemas.py          # Agent I/O schemas
│   │   └── prompts/            # Agent-specific prompts
│   │       ├── planner_initial.txt
│   │       ├── planner_replan.txt
│   │       ├── executor.txt
│   │       └── evaluator.txt
│   ├── orchestration/          # LangGraph workflow (was workflows/ + adapters/)
│   │   ├── __init__.py
│   │   ├── tutor_workflow.py   # LangGraph state machine
│   │   ├── state.py            # SimplifiedState schema
│   │   ├── workflow_bridge.py  # API ↔ Workflow (was workflow_adapter.py)
│   │   └── state_converter.py  # State conversion (was state_adapter.py)
│   └── models/
│       ├── __init__.py
│       └── schemas.py          # Tutor-specific request/response
│
├── book_ingestion/             # BOOK INGESTION MODULE (was features/book_ingestion/)
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py           # Upload endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── orchestrator.py     # Main extraction pipeline
│   │   ├── ocr_service.py
│   │   ├── topic_deduplication_service.py
│   │   ├── db_sync_service.py
│   │   └── ...
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── book_repository.py  # Book-specific data access
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py          # Book ingestion schemas
│   └── utils/
│       ├── __init__.py
│       └── s3_client.py
│
├── study_plans/                # STUDY PLANS MODULE (was features/study_plans/)
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── admin.py            # Admin endpoints (was admin_guidelines.py)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── orchestrator.py     # Plan generation pipeline
│   │   ├── generator_service.py
│   │   └── reviewer_service.py
│   └── models/
│       ├── __init__.py
│       └── schemas.py
│
├── api/                        # ROOT API (minimal)
│   ├── __init__.py
│   └── routes/
│       ├── __init__.py
│       └── health.py           # Health check only
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    └── integration/
```

---

## 4. Key Simplifications

| Before | After | Reason |
|--------|-------|--------|
| `adapters/` + `workflows/` | `tutor/orchestration/` | Single location for workflow logic |
| `features/book_ingestion/` | `book_ingestion/` | Promoted to top-level, flatter |
| `features/study_plans/` | `study_plans/` | Promoted to top-level, flatter |
| `routers/admin_guidelines.py` | `study_plans/api/admin.py` | Colocated with module |
| Backward compat re-exports | None | Clean break, no confusion |
| `models/database.py` | `shared/models/entities.py` | Clearer naming |

---

## 5. Implementation Plan

### Phase 1: Create Directory Structure
**Objective:** Create new directories without breaking anything.

```bash
mkdir -p shared/{models,repositories,services,utils,prompts/templates}
mkdir -p tutor/{api,services,agents/prompts,orchestration,models}
mkdir -p book_ingestion/{api,services,repositories,models,utils}
mkdir -p study_plans/{api,services,models}
touch shared/__init__.py shared/models/__init__.py ...
```

**Verification:** `python -c "from main import app"` still works.

### Phase 2: Move Shared Components
**Files to move:**

| From | To |
|------|-----|
| `models/database.py` | `shared/models/entities.py` |
| `models/domain.py` | `shared/models/domain.py` |
| `models/schemas.py` | `shared/models/schemas.py` |
| `models/logs.py` | `shared/models/logs.py` |
| `repositories/*` | `shared/repositories/*` |
| `utils/*` | `shared/utils/*` |
| `prompts/*` | `shared/prompts/*` |
| `services/llm_service.py` | `shared/services/llm_service.py` |

**Update all imports** from `models` → `shared.models`, etc.

### Phase 3: Move Tutor Components
**Files to move:**

| From | To |
|------|-----|
| `agents/*` | `tutor/agents/*` |
| `workflows/tutor_workflow.py` | `tutor/orchestration/tutor_workflow.py` |
| `workflows/state.py` | `tutor/orchestration/state.py` |
| `workflows/helpers.py` | `tutor/orchestration/helpers.py` |
| `adapters/workflow_adapter.py` | `tutor/orchestration/workflow_bridge.py` |
| `adapters/state_adapter.py` | `tutor/orchestration/state_converter.py` |
| `services/session_service.py` | `tutor/services/session_service.py` |
| `api/routes/sessions.py` | `tutor/api/sessions.py` |
| `api/routes/logs.py` | `tutor/api/logs.py` |
| `api/routes/curriculum.py` | `tutor/api/curriculum.py` |

### Phase 4: Move Book Ingestion Components
**Files to move:**

| From | To |
|------|-----|
| `features/book_ingestion/api/*` | `book_ingestion/api/*` |
| `features/book_ingestion/services/*` | `book_ingestion/services/*` |
| `features/book_ingestion/models/*` | `book_ingestion/models/*` |
| `features/book_ingestion/repositories/*` | `book_ingestion/repositories/*` |
| `features/book_ingestion/utils/*` | `book_ingestion/utils/*` |

### Phase 5: Move Study Plans Components
**Files to move:**

| From | To |
|------|-----|
| `features/study_plans/services/*` | `study_plans/services/*` |
| `routers/admin_guidelines.py` | `study_plans/api/admin.py` |

### Phase 6: Update Entry Point (main.py)

```python
# Before
from api.routes import health, curriculum, sessions, logs
from features.book_ingestion.api import routes as book_routes
from routers import admin_guidelines

# After
from api.routes import health
from tutor.api import sessions, logs, curriculum
from book_ingestion.api import routes as book_routes
from study_plans.api import admin as admin_routes
```

### Phase 7: Update Tests
Fix all test imports to use new paths.

### Phase 8: Clean Up
Delete empty directories:
- `features/`
- `routers/`
- `adapters/`
- `workflows/`
- Old `services/session_service.py`
- Old `models/`, `repositories/`, `utils/`, `prompts/`

---

## 6. Import Update Pattern

### Example: session_service.py

**Before:**
```python
from models import CreateSessionRequest, TutorState, Student
from repositories import SessionRepository, EventRepository
from adapters.workflow_adapter import SessionWorkflowAdapter
from utils.formatting import extract_last_turn
from utils.constants import MAX_STEPS
```

**After:**
```python
from shared.models import CreateSessionRequest, TutorState, Student
from shared.repositories import SessionRepository, EventRepository
from tutor.orchestration.workflow_bridge import WorkflowBridge
from shared.utils.formatting import extract_last_turn
from shared.utils.constants import MAX_STEPS
```

---

## 7. Verification Checklist

After each phase:
- [ ] `python -c "from main import app"` succeeds
- [ ] `pytest tests/unit/` passes
- [ ] `pytest tests/integration/` passes
- [ ] API endpoints respond correctly

Final verification:
- [ ] Full test suite passes
- [ ] Manual API testing (create session, step, summary)
- [ ] No orphaned files in old locations

---

## 8. Rollback Plan

1. **Git history:** Each phase should be a separate commit
2. **If critical issues:** `git revert` to previous state
3. **No backward compat layer:** Clean break is intentional—old imports should fail fast to catch missed updates

---

## 9. Files Requiring Import Updates

### Tutor Module
- `tutor/orchestration/tutor_workflow.py`
- `tutor/orchestration/helpers.py`
- `tutor/orchestration/workflow_bridge.py`
- `tutor/orchestration/state_converter.py`
- `tutor/agents/base.py`
- `tutor/agents/planner_agent.py`
- `tutor/agents/executor_agent.py`
- `tutor/agents/evaluator_agent.py`
- `tutor/services/session_service.py`
- `tutor/api/sessions.py`
- `tutor/api/logs.py`
- `tutor/api/curriculum.py`

### Book Ingestion Module
- `book_ingestion/api/routes.py`
- `book_ingestion/services/*.py`
- `book_ingestion/repositories/*.py`

### Study Plans Module
- `study_plans/api/admin.py`
- `study_plans/services/orchestrator.py`
- `study_plans/services/generator_service.py`
- `study_plans/services/reviewer_service.py`

### Root
- `main.py`
- `database.py`

### Tests
- All files in `tests/`

---

## 10. Summary

| Metric | Before | After |
|--------|--------|-------|
| Top-level modules | Mixed (unclear) | 4 (shared, tutor, book_ingestion, study_plans) |
| Max nesting depth | 4+ levels | 2 levels |
| Architectural consistency | Varies | Same 4-layer pattern everywhere |
| Adapters as separate folder | Yes | No (merged into orchestration) |
| Backward compat re-exports | Planned | Removed |
