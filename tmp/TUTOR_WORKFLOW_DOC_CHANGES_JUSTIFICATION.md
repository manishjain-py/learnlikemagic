# Tutor Workflow Pipeline - Documentation Changes Justification

**Date:** 2025-12-30
**Document Updated:** `docs/TUTOR_WORKFLOW_PIPELINE.md`

---

## Summary of Changes

| Category | Changes Made | Evidence |
|----------|--------------|----------|
| Path Corrections | Updated all backend paths after folder reorganization | `ls llm-backend/` - tutor/, shared/, study_plans/, book_ingestion/ |
| File Renaming | Updated file references to new names | Direct file checks |
| Module Structure | Updated to reflect new module-based organization | `main.py` imports |

---

## Detailed Changes

### 1. Backend Path Corrections

**All paths updated after recent folder reorganization:**

| Old Path | New Path | Verification |
|----------|----------|--------------|
| `llm-backend/workflows/` | `llm-backend/tutor/orchestration/` | `ls llm-backend/tutor/orchestration/` |
| `llm-backend/agents/` | `llm-backend/tutor/agents/` | `ls llm-backend/tutor/agents/` |
| `llm-backend/services/session_service.py` | `llm-backend/tutor/services/session_service.py` | Direct file check |
| `llm-backend/services/llm_service.py` | `llm-backend/shared/services/llm_service.py` | `ls llm-backend/shared/services/` |
| `llm-backend/adapters/workflow_adapter.py` | `llm-backend/tutor/orchestration/workflow_bridge.py` | Direct file check |
| `llm-backend/adapters/state_adapter.py` | `llm-backend/tutor/orchestration/state_converter.py` | Direct file check |
| `llm-backend/api/routes/sessions.py` | `llm-backend/tutor/api/sessions.py` | `ls llm-backend/tutor/api/` |
| `llm-backend/api/routes/curriculum.py` | `llm-backend/tutor/api/curriculum.py` | Direct file check |
| `llm-backend/api/routes/health.py` | `llm-backend/shared/api/health.py` | `main.py` imports |
| `llm-backend/api/routes/logs.py` | `llm-backend/tutor/api/logs.py` | Direct file check |
| `llm-backend/routers/admin_guidelines.py` | `llm-backend/study_plans/api/admin.py` | `grep "admin/guidelines"` |
| `llm-backend/features/study_plans/` | `llm-backend/study_plans/` | `ls llm-backend/study_plans/` |
| `llm-backend/features/book_ingestion/` | `llm-backend/book_ingestion/` | `ls llm-backend/book_ingestion/` |

---

### 2. File Renaming Corrections

| Old Name | New Name | Location |
|----------|----------|----------|
| `llm_schemas.py` | `schemas.py` | `tutor/agents/` |
| `workflow_adapter.py` | `workflow_bridge.py` | `tutor/orchestration/` |
| `state_adapter.py` | `state_converter.py` | `tutor/orchestration/` |
| `state.py` | `state.py` | Moved to `tutor/models/` |
| `helpers.py` | `helpers.py` | Moved to `tutor/models/` |
| `schemas.py` (workflow) | `schemas.py` | `tutor/orchestration/` |

---

### 3. Key Code Locations Section Updated

Updated to reflect new module structure:
- `llm-backend/tutor/` - Runtime tutoring (agents, orchestration, services, api)
- `llm-backend/shared/` - Cross-module (llm_service, health api)
- `llm-backend/study_plans/` - Study plan generation
- `llm-backend/book_ingestion/` - Book upload & extraction

---

### 4. Key Files Reference Section Updated

All backend file references updated to new locations:
- Workflow & State files → `tutor/orchestration/` and `tutor/models/`
- Agent files → `tutor/agents/`
- Service files → `tutor/services/` and `shared/services/`
- API files → `tutor/api/` and `shared/api/`
- Study Plans → `study_plans/services/`

---

## Verification Commands

```bash
# Verify tutor module structure
ls llm-backend/tutor/
# agents  api  models  orchestration  services

# Verify orchestration files
ls llm-backend/tutor/orchestration/
# schemas.py  state_converter.py  tutor_workflow.py  workflow_bridge.py

# Verify agents files
ls llm-backend/tutor/agents/
# base.py  evaluator_agent.py  executor_agent.py  planner_agent.py  prompts  schemas.py

# Check main.py imports
head -20 llm-backend/main.py
# from tutor.api import curriculum, sessions, logs
# from shared.api import health
# from study_plans.api import admin as admin_guidelines
```

---

## Previous Changes (2025-12-28) - Preserved

The following changes from previous updates remain valid:
- Pre-Built Study Plans section
- Phase 2 Session Creation flow with pre-built plan loading
- Study Plan endpoints in Admin Guidelines API
- study_plans database table documentation
- Pre-built study plans design decision
