# Folder Reorganization: Implementation Plan

A step-by-step guide to safely reorganize the llm-backend folder structure without breaking functionality.

**Prerequisites:**
- Read [ARCHITECTURE.md](../ARCHITECTURE.md) for layer definitions
- Read [FOLDER_STRUCTURE_REORGANIZATION.md](./FOLDER_STRUCTURE_REORGANIZATION.md) for target structure

---

## Pre-Migration Checklist

Before starting, ensure:

```bash
# 1. Clean working directory
git status  # Should show no uncommitted changes

# 2. All tests pass
cd llm-backend
source venv/bin/activate
export OPENAI_API_KEY=sk-test-dummy-key
pytest tests/ -v

# 3. App starts successfully
python -c "from main import app; print('✅ App imports OK')"

# 4. Create a migration branch
git checkout -b refactor/folder-reorganization
```

---

## Migration Strategy

### Key Principles

1. **One phase = one commit** - Easy rollback if issues arise
2. **Move + update imports atomically** - Never leave broken imports
3. **Verify after each phase** - Run tests before proceeding
4. **Shared components first** - Dependencies before dependents

### Phase Execution Order

```
Phase 0: Preparation (scaffolding)
    ↓
Phase 1: Shared components (models, repos, utils, prompts, llm_service)
    ↓
Phase 2: Tutor module (agents, orchestration, services, api)
    ↓
Phase 3: Book ingestion module (promote from features/)
    ↓
Phase 4: Study plans module (promote from features/)
    ↓
Phase 5: Update main.py and clean up
    ↓
Phase 6: Final verification and cleanup
```

---

## Phase 0: Scaffolding (Non-Breaking)

**Goal:** Create new directory structure without moving any files.

### Step 0.1: Create directories

```bash
cd llm-backend

# Shared module
mkdir -p shared/{models,repositories,services,utils,prompts/templates}

# Tutor module
mkdir -p tutor/{api,services,agents/prompts,orchestration,models}

# Book ingestion module (will move from features/)
mkdir -p book_ingestion/{api,services,repositories,models,utils}

# Study plans module (will move from features/)
mkdir -p study_plans/{api,services,models}
```

### Step 0.2: Create __init__.py files

```bash
# Shared
touch shared/__init__.py
touch shared/models/__init__.py
touch shared/repositories/__init__.py
touch shared/services/__init__.py
touch shared/utils/__init__.py
touch shared/prompts/__init__.py

# Tutor
touch tutor/__init__.py
touch tutor/api/__init__.py
touch tutor/services/__init__.py
touch tutor/agents/__init__.py
touch tutor/agents/prompts/.gitkeep
touch tutor/orchestration/__init__.py
touch tutor/models/__init__.py

# Book ingestion
touch book_ingestion/__init__.py
touch book_ingestion/api/__init__.py
touch book_ingestion/services/__init__.py
touch book_ingestion/repositories/__init__.py
touch book_ingestion/models/__init__.py
touch book_ingestion/utils/__init__.py

# Study plans
touch study_plans/__init__.py
touch study_plans/api/__init__.py
touch study_plans/services/__init__.py
touch study_plans/models/__init__.py
```

### Step 0.3: Verify

```bash
python -c "from main import app; print('✅ Phase 0: Scaffolding OK')"
git add -A && git commit -m "Phase 0: Create new directory structure (scaffolding)"
```

---

## Phase 1: Move Shared Components

**Goal:** Move all shared code to `shared/` module.

### Step 1.1: Move models

```bash
# Move files
cp models/database.py shared/models/entities.py
cp models/domain.py shared/models/domain.py
cp models/schemas.py shared/models/schemas.py
cp models/logs.py shared/models/logs.py
```

Update `shared/models/__init__.py`:
```python
"""Shared data models."""
from shared.models.entities import *
from shared.models.domain import *
from shared.models.schemas import *
from shared.models.logs import *
```

### Step 1.2: Move repositories

```bash
cp repositories/session_repository.py shared/repositories/
cp repositories/event_repository.py shared/repositories/
cp repositories/guideline_repository.py shared/repositories/
```

Update `shared/repositories/__init__.py`:
```python
"""Shared data access layer."""
from shared.repositories.session_repository import SessionRepository
from shared.repositories.event_repository import EventRepository
from shared.repositories.guideline_repository import TeachingGuidelineRepository
```

### Step 1.3: Move utils

```bash
cp utils/constants.py shared/utils/
cp utils/exceptions.py shared/utils/
cp utils/formatting.py shared/utils/
```

Update `shared/utils/__init__.py`:
```python
"""Shared utilities."""
from shared.utils.constants import *
from shared.utils.exceptions import *
from shared.utils.formatting import *
```

### Step 1.4: Move prompts

```bash
cp prompts/loader.py shared/prompts/
cp -r prompts/templates/* shared/prompts/templates/ 2>/dev/null || true
```

Update `shared/prompts/__init__.py`:
```python
"""Prompt loading utilities."""
from shared.prompts.loader import PromptLoader
```

### Step 1.5: Move llm_service

```bash
cp services/llm_service.py shared/services/
```

Update `shared/services/__init__.py`:
```python
"""Shared services."""
from shared.services.llm_service import LLMService
```

### Step 1.6: Update shared module imports

Update imports within the moved files to use `shared.` prefix:

**shared/models/entities.py:**
```python
# No changes needed - uses SQLAlchemy only
```

**shared/repositories/session_repository.py:**
```python
# Change: from models.database import ...
# To:     from shared.models.entities import ...
```

**shared/repositories/guideline_repository.py:**
```python
# Change: from models.database import ...
# To:     from shared.models.entities import ...
```

**shared/utils/formatting.py:**
```python
# Change: from models.domain import HistoryEntry
# To:     from shared.models.domain import HistoryEntry
```

**shared/prompts/loader.py:**
```python
# Update path resolution to work from new location
# Change: PROMPTS_DIR = Path(__file__).parent / "templates"
# To:     PROMPTS_DIR = Path(__file__).parent / "templates"
# (same, but verify paths work)
```

### Step 1.7: Create backward compatibility shims (temporary)

To avoid updating all consumers at once, create re-exports in old locations:

**models/__init__.py:**
```python
"""Backward compatibility - imports from shared.models"""
from shared.models import *
```

**repositories/__init__.py:**
```python
"""Backward compatibility - imports from shared.repositories"""
from shared.repositories import *
```

**utils/__init__.py:**
```python
"""Backward compatibility - imports from shared.utils"""
from shared.utils import *
```

**prompts/__init__.py:**
```python
"""Backward compatibility - imports from shared.prompts"""
from shared.prompts import *
```

**services/__init__.py (update, keep session_service for now):**
```python
"""Backward compatibility for llm_service."""
from shared.services.llm_service import LLMService
from services.session_service import SessionService
```

### Step 1.8: Verify Phase 1

```bash
# Verify imports work
python -c "from shared.models import TutorState; print('✅ shared.models OK')"
python -c "from shared.repositories import SessionRepository; print('✅ shared.repositories OK')"
python -c "from shared.utils import MAX_STEPS; print('✅ shared.utils OK')"
python -c "from shared.services import LLMService; print('✅ shared.services OK')"

# Verify backward compat
python -c "from models import TutorState; print('✅ models backward compat OK')"
python -c "from repositories import SessionRepository; print('✅ repositories backward compat OK')"

# Verify app still works
python -c "from main import app; print('✅ App imports OK')"

# Run tests
pytest tests/ -v --tb=short

# Commit
git add -A && git commit -m "Phase 1: Move shared components to shared/ module"
```

---

## Phase 2: Move Tutor Components

**Goal:** Move all tutor-specific code to `tutor/` module.

### Step 2.1: Move agents

```bash
cp agents/base.py tutor/agents/
cp agents/planner_agent.py tutor/agents/
cp agents/executor_agent.py tutor/agents/
cp agents/evaluator_agent.py tutor/agents/
cp agents/llm_schemas.py tutor/agents/schemas.py  # Rename!
cp -r agents/prompts/* tutor/agents/prompts/
```

Update imports in each agent file:
```python
# Change: from agents.base import BaseAgent
# To:     from tutor.agents.base import BaseAgent

# Change: from services.llm_service import LLMService
# To:     from shared.services import LLMService

# Change: from workflows.state import SimplifiedState
# To:     from tutor.orchestration.state import SimplifiedState

# Change: from workflows.helpers import ...
# To:     from tutor.orchestration.helpers import ...
```

Update `tutor/agents/__init__.py`:
```python
"""Tutor AI agents."""
from tutor.agents.base import BaseAgent
from tutor.agents.planner_agent import PlannerAgent
from tutor.agents.executor_agent import ExecutorAgent
from tutor.agents.evaluator_agent import EvaluatorAgent
```

### Step 2.2: Move orchestration (workflows + adapters)

```bash
cp workflows/tutor_workflow.py tutor/orchestration/
cp workflows/state.py tutor/orchestration/
cp workflows/helpers.py tutor/orchestration/
cp workflows/schemas.py tutor/orchestration/
cp adapters/workflow_adapter.py tutor/orchestration/workflow_bridge.py  # Rename!
cp adapters/state_adapter.py tutor/orchestration/state_converter.py    # Rename!
```

Update imports in orchestration files:

**tutor/orchestration/tutor_workflow.py:**
```python
# Change: from agents.planner_agent import PlannerAgent
# To:     from tutor.agents import PlannerAgent, ExecutorAgent, EvaluatorAgent

# Change: from workflows.state import SimplifiedState
# To:     from tutor.orchestration.state import SimplifiedState

# Change: from workflows.helpers import ...
# To:     from tutor.orchestration.helpers import ...
```

**tutor/orchestration/workflow_bridge.py:**
```python
# Change: from workflows.tutor_workflow import TutorWorkflow
# To:     from tutor.orchestration.tutor_workflow import TutorWorkflow

# Change: from adapters.state_adapter import StateAdapter
# To:     from tutor.orchestration.state_converter import StateConverter

# Change: from models import ...
# To:     from shared.models import ...

# Change: from repositories import ...
# To:     from shared.repositories import ...

# Rename class: SessionWorkflowAdapter -> WorkflowBridge
```

**tutor/orchestration/state_converter.py:**
```python
# Change: from models import TutorState
# To:     from shared.models import TutorState

# Rename class: StateAdapter -> StateConverter
```

Update `tutor/orchestration/__init__.py`:
```python
"""Tutor workflow orchestration."""
from tutor.orchestration.tutor_workflow import TutorWorkflow
from tutor.orchestration.state import SimplifiedState
from tutor.orchestration.workflow_bridge import WorkflowBridge
from tutor.orchestration.state_converter import StateConverter
```

### Step 2.3: Move session service

```bash
cp services/session_service.py tutor/services/
```

Update imports in `tutor/services/session_service.py`:
```python
# Change: from adapters.workflow_adapter import SessionWorkflowAdapter
# To:     from tutor.orchestration import WorkflowBridge

# Change: from models import ...
# To:     from shared.models import ...

# Change: from repositories import ...
# To:     from shared.repositories import ...

# Change: from utils.formatting import ...
# To:     from shared.utils.formatting import ...

# Change: from utils.constants import ...
# To:     from shared.utils.constants import ...

# Change: from utils.exceptions import ...
# To:     from shared.utils.exceptions import ...

# Update class usage: SessionWorkflowAdapter -> WorkflowBridge
```

Update `tutor/services/__init__.py`:
```python
"""Tutor services."""
from tutor.services.session_service import SessionService
```

### Step 2.4: Move API routes

```bash
cp api/routes/sessions.py tutor/api/
cp api/routes/logs.py tutor/api/
cp api/routes/curriculum.py tutor/api/
```

Update imports in each API file:
```python
# Change: from services import SessionService
# To:     from tutor.services import SessionService

# Change: from models import ...
# To:     from shared.models import ...

# Change: from repositories import ...
# To:     from shared.repositories import ...
```

Update `tutor/api/__init__.py`:
```python
"""Tutor API routes."""
from tutor.api import sessions, logs, curriculum
```

### Step 2.5: Create backward compatibility shims (temporary)

**agents/__init__.py:**
```python
"""Backward compatibility - imports from tutor.agents"""
from tutor.agents import *
```

**workflows/__init__.py:**
```python
"""Backward compatibility - imports from tutor.orchestration"""
from tutor.orchestration import *
from tutor.orchestration.tutor_workflow import TutorWorkflow, build_workflow
```

**adapters/__init__.py:**
```python
"""Backward compatibility - imports from tutor.orchestration"""
from tutor.orchestration.workflow_bridge import WorkflowBridge as SessionWorkflowAdapter
from tutor.orchestration.state_converter import StateConverter as StateAdapter
```

**Update services/__init__.py:**
```python
"""Backward compatibility."""
from shared.services.llm_service import LLMService
from tutor.services.session_service import SessionService
```

### Step 2.6: Verify Phase 2

```bash
# Verify new imports work
python -c "from tutor.agents import PlannerAgent; print('✅ tutor.agents OK')"
python -c "from tutor.orchestration import TutorWorkflow; print('✅ tutor.orchestration OK')"
python -c "from tutor.services import SessionService; print('✅ tutor.services OK')"

# Verify backward compat still works
python -c "from agents import PlannerAgent; print('✅ agents backward compat OK')"
python -c "from workflows import TutorWorkflow; print('✅ workflows backward compat OK')"
python -c "from services import SessionService; print('✅ services backward compat OK')"

# Verify app
python -c "from main import app; print('✅ App imports OK')"

# Run tests
pytest tests/ -v --tb=short

# Commit
git add -A && git commit -m "Phase 2: Move tutor components to tutor/ module"
```

---

## Phase 3: Move Book Ingestion

**Goal:** Promote `features/book_ingestion/` to top-level `book_ingestion/`.

### Step 3.1: Copy all book ingestion files

```bash
# API
cp features/book_ingestion/api/routes.py book_ingestion/api/
cp features/book_ingestion/api/__init__.py book_ingestion/api/

# Services (all of them)
cp features/book_ingestion/services/*.py book_ingestion/services/

# Repositories
cp features/book_ingestion/repositories/*.py book_ingestion/repositories/

# Models
cp features/book_ingestion/models/*.py book_ingestion/models/

# Utils
cp features/book_ingestion/utils/*.py book_ingestion/utils/

# Tests (keep in place or move to main tests/)
```

### Step 3.2: Update imports in book_ingestion files

All files need import updates:
```python
# Change: from features.book_ingestion.services import ...
# To:     from book_ingestion.services import ...

# Change: from features.book_ingestion.models import ...
# To:     from book_ingestion.models import ...

# Change: from features.book_ingestion.repositories import ...
# To:     from book_ingestion.repositories import ...

# Change: from models.database import ...
# To:     from shared.models.entities import ...

# Change: from services.llm_service import LLMService
# To:     from shared.services import LLMService
```

### Step 3.3: Update __init__.py files

**book_ingestion/__init__.py:**
```python
"""Book ingestion pipeline."""
```

**book_ingestion/services/__init__.py:**
```python
"""Book ingestion services."""
from book_ingestion.services.guideline_extraction_orchestrator import GuidelineExtractionOrchestrator
from book_ingestion.services.ocr_service import OCRService
# ... other exports
```

### Step 3.4: Create backward compatibility shim

**features/book_ingestion/__init__.py:**
```python
"""Backward compatibility - imports from book_ingestion"""
from book_ingestion import *
```

**features/book_ingestion/api/__init__.py:**
```python
"""Backward compatibility."""
from book_ingestion.api import routes
```

### Step 3.5: Verify Phase 3

```bash
# Verify new imports
python -c "from book_ingestion.api import routes; print('✅ book_ingestion.api OK')"
python -c "from book_ingestion.services import GuidelineExtractionOrchestrator; print('✅ book_ingestion.services OK')"

# Verify backward compat
python -c "from features.book_ingestion.api import routes; print('✅ features backward compat OK')"

# Verify app
python -c "from main import app; print('✅ App imports OK')"

# Run tests
pytest tests/ -v --tb=short

# Commit
git add -A && git commit -m "Phase 3: Promote book_ingestion to top-level module"
```

---

## Phase 4: Move Study Plans

**Goal:** Promote `features/study_plans/` to top-level `study_plans/`.

### Step 4.1: Copy study plans files

```bash
# Services
cp features/study_plans/services/*.py study_plans/services/

# API (from routers/)
cp routers/admin_guidelines.py study_plans/api/admin.py
```

### Step 4.2: Update imports

**study_plans/services/*.py:**
```python
# Change: from services.llm_service import LLMService
# To:     from shared.services import LLMService

# Change: from models.database import ...
# To:     from shared.models.entities import ...

# Change: from repositories import ...
# To:     from shared.repositories import ...
```

**study_plans/api/admin.py:**
```python
# Change: from features.book_ingestion.services import ...
# To:     from book_ingestion.services import ...

# Change: from features.study_plans.services import ...
# To:     from study_plans.services import ...
```

### Step 4.3: Update __init__.py files

**study_plans/__init__.py:**
```python
"""Study plan generation pipeline."""
```

**study_plans/services/__init__.py:**
```python
"""Study plan services."""
from study_plans.services.orchestrator import StudyPlanOrchestrator
from study_plans.services.generator_service import StudyPlanGeneratorService
from study_plans.services.reviewer_service import StudyPlanReviewerService
```

**study_plans/api/__init__.py:**
```python
"""Study plan API routes."""
from study_plans.api import admin
```

### Step 4.4: Create backward compatibility shim

**features/study_plans/__init__.py:**
```python
"""Backward compatibility - imports from study_plans"""
from study_plans import *
```

**features/study_plans/services/__init__.py:**
```python
"""Backward compatibility."""
from study_plans.services import *
```

**routers/__init__.py:**
```python
"""Backward compatibility."""
from study_plans.api import admin as admin_guidelines
```

### Step 4.5: Verify Phase 4

```bash
# Verify new imports
python -c "from study_plans.services import StudyPlanOrchestrator; print('✅ study_plans.services OK')"
python -c "from study_plans.api import admin; print('✅ study_plans.api OK')"

# Verify backward compat
python -c "from features.study_plans.services import orchestrator; print('✅ features backward compat OK')"
python -c "from routers import admin_guidelines; print('✅ routers backward compat OK')"

# Verify app
python -c "from main import app; print('✅ App imports OK')"

# Run tests
pytest tests/ -v --tb=short

# Commit
git add -A && git commit -m "Phase 4: Promote study_plans to top-level module"
```

---

## Phase 5: Update main.py and Integration Points

**Goal:** Update entry point and cross-module references to use new paths.

### Step 5.1: Update main.py

```python
"""
LearnLikeMagic LLM Backend - FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings, validate_required_settings
from database import get_db_manager

# Updated imports - new module locations
from api.routes import health                    # Keep: general endpoint
from tutor.api import sessions, logs, curriculum # Changed: from tutor module
from book_ingestion.api import routes as book_routes  # Changed: promoted
from study_plans.api import admin as admin_guidelines # Changed: promoted

# ... rest of file unchanged
```

### Step 5.2: Update tutor cross-module import

**tutor/orchestration/workflow_bridge.py** imports from study_plans:
```python
# Change: from features.study_plans.services.orchestrator import StudyPlanOrchestrator
# To:     from study_plans.services import StudyPlanOrchestrator
```

### Step 5.3: Update tests

Update test imports to use new paths. Key files:

**tests/conftest.py:**
```python
# Update any fixture imports
from shared.models import TutorState, Student, Goal
from tutor.services import SessionService
```

**tests/integration/test_session_endpoints.py:**
```python
from tutor.services import SessionService
from shared.models import CreateSessionRequest
```

**tests/integration/test_tutor_workflow.py:**
```python
from tutor.orchestration import TutorWorkflow, SimplifiedState
from tutor.agents import PlannerAgent, ExecutorAgent, EvaluatorAgent
```

### Step 5.4: Verify Phase 5

```bash
# Verify main.py works with new imports
python -c "from main import app; print('✅ main.py updated OK')"

# Run full test suite
pytest tests/ -v

# Start server and test manually
uvicorn main:app --reload &
sleep 3
curl http://localhost:8000/
curl http://localhost:8000/docs
pkill -f uvicorn

# Commit
git add -A && git commit -m "Phase 5: Update main.py and cross-module imports"
```

---

## Phase 6: Final Cleanup

**Goal:** Remove old directories and backward compatibility shims.

### Step 6.1: Remove backward compatibility shims

Update all remaining files that still use old import paths to use new paths:

```bash
# Find files still using old imports
grep -r "from models import\|from models\." --include="*.py" | grep -v shared | grep -v __pycache__
grep -r "from repositories import" --include="*.py" | grep -v shared | grep -v __pycache__
grep -r "from agents import\|from agents\." --include="*.py" | grep -v tutor | grep -v __pycache__
grep -r "from workflows import\|from workflows\." --include="*.py" | grep -v tutor | grep -v __pycache__
grep -r "from adapters import\|from adapters\." --include="*.py" | grep -v tutor | grep -v __pycache__
grep -r "from features\." --include="*.py" | grep -v __pycache__
```

Update each file found to use new import paths.

### Step 6.2: Delete old directories

```bash
# Only after all imports updated!
rm -rf models/
rm -rf repositories/
rm -rf utils/
rm -rf prompts/
rm -rf agents/
rm -rf workflows/
rm -rf adapters/
rm -rf services/session_service.py  # Keep llm_service.py until shared verified
rm -rf features/
rm -rf routers/
```

### Step 6.3: Clean up services directory

If `services/` only contained `session_service.py` and `llm_service.py`:
```bash
rm -rf services/
```

### Step 6.4: Final verification

```bash
# Verify no broken imports
python -c "from main import app; print('✅ App OK')"

# Full test suite
pytest tests/ -v

# Manual API test
uvicorn main:app --reload &
sleep 3

# Test health
curl http://localhost:8000/

# Test curriculum
curl "http://localhost:8000/curriculum?country=India&board=CBSE&grade=3"

# Test session creation (adjust guideline_id as needed)
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"student": {"id": "test1", "grade": 3}, "goal": {"topic": "Test", "syllabus": "CBSE", "learning_objectives": ["Test"], "guideline_id": "g1"}}'

pkill -f uvicorn

# Commit
git add -A && git commit -m "Phase 6: Remove backward compatibility shims and old directories"
```

---

## Post-Migration Checklist

After completing all phases:

- [ ] All tests pass: `pytest tests/ -v`
- [ ] App starts: `python -c "from main import app"`
- [ ] API docs accessible: http://localhost:8000/docs
- [ ] Create session works
- [ ] Step through session works
- [ ] Session summary works
- [ ] Book ingestion endpoints work
- [ ] Study plan admin endpoints work
- [ ] No old directories remain
- [ ] No backward compat shims remain

---

## Rollback Procedures

### Rollback single phase

```bash
# See recent commits
git log --oneline -10

# Revert specific phase
git revert <commit-hash>
```

### Rollback entire migration

```bash
# Return to main branch
git checkout main

# Delete migration branch
git branch -D refactor/folder-reorganization
```

### Rollback with preserved work

```bash
# Stash current changes
git stash

# Return to last working commit
git checkout <last-working-commit>

# Create new branch from there
git checkout -b refactor/folder-reorganization-v2

# Apply stashed changes selectively
git stash show -p | git apply --reject
```

---

## Import Update Patterns

### Quick Reference

| Old Import | New Import |
|------------|------------|
| `from models import X` | `from shared.models import X` |
| `from models.database import X` | `from shared.models.entities import X` |
| `from models.domain import X` | `from shared.models.domain import X` |
| `from repositories import X` | `from shared.repositories import X` |
| `from utils.X import Y` | `from shared.utils.X import Y` |
| `from prompts.loader import X` | `from shared.prompts import X` |
| `from services.llm_service import X` | `from shared.services import X` |
| `from services import SessionService` | `from tutor.services import SessionService` |
| `from agents.X import Y` | `from tutor.agents import Y` |
| `from workflows.X import Y` | `from tutor.orchestration import Y` |
| `from adapters.workflow_adapter import X` | `from tutor.orchestration import WorkflowBridge` |
| `from adapters.state_adapter import X` | `from tutor.orchestration import StateConverter` |
| `from features.book_ingestion.X import Y` | `from book_ingestion.X import Y` |
| `from features.study_plans.X import Y` | `from study_plans.X import Y` |
| `from routers.admin_guidelines import X` | `from study_plans.api.admin import X` |

### Rename Reference

| Old Name | New Name |
|----------|----------|
| `database.py` (models) | `entities.py` |
| `llm_schemas.py` | `schemas.py` |
| `workflow_adapter.py` | `workflow_bridge.py` |
| `state_adapter.py` | `state_converter.py` |
| `SessionWorkflowAdapter` class | `WorkflowBridge` class |
| `StateAdapter` class | `StateConverter` class |

---

## Estimated Effort

| Phase | Files to Update | Estimated Time |
|-------|-----------------|----------------|
| Phase 0: Scaffolding | 0 | 5 min |
| Phase 1: Shared | ~15 | 30 min |
| Phase 2: Tutor | ~20 | 45 min |
| Phase 3: Book Ingestion | ~25 | 45 min |
| Phase 4: Study Plans | ~8 | 20 min |
| Phase 5: Integration | ~10 | 30 min |
| Phase 6: Cleanup | ~5 | 15 min |
| **Total** | **~83** | **~3 hours** |

---

## Troubleshooting

### "Module not found" errors

1. Check `__init__.py` exists in the module directory
2. Check the import path matches the file location
3. Run `python -c "import <module>; print(<module>.__file__)"` to see what's loaded

### Circular import errors

1. Check if two modules import each other
2. Move shared types to `shared/models/`
3. Use `TYPE_CHECKING` for type-only imports:
   ```python
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       from some.module import SomeType
   ```

### Tests fail after migration

1. Check test fixtures use updated import paths
2. Check test file imports are updated
3. Run individual test file: `pytest tests/path/to/test.py -v`

### App won't start

1. Run `python -c "from main import app"` to see error
2. Fix import in reported file
3. Repeat until no errors
