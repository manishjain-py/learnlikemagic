# Tutor Workflow Pipeline Documentation - Change Justification Log

**Document Updated:** TUTOR_WORKFLOW_PIPELINE.md
**Last Updated:** 2025-12-28
**Reason:** Sync documentation with actual codebase implementation

---

## Update Log

### 2025-12-28 Update

| # | Change | Type | Evidence |
|---|--------|------|----------|
| 1 | Added "Pre-Built Study Plans" section before Phase 2 | NEW FEATURE | `workflow_adapter.py:99-127`, `features/study_plans/services/orchestrator.py` |
| 2 | Updated Phase 2 Session Creation flow with pre-built plan loading | FLOW UPDATE | `workflow_adapter.py:99-127`, `tutor_workflow.py:280-318` |
| 3 | Added 3 additional Logs API deprecated endpoints | MISSING | `api/routes/logs.py:40-77` |
| 4 | Added 3 Study Plan endpoints to Admin Guidelines API | MISSING | `admin_guidelines.py:725-795` |
| 5 | Added "Backend - Study Plans" section to Key Files Reference | NEW SECTION | `features/study_plans/services/*.py` |
| 6 | Added `study_plans` table to Database Tables | MISSING | `models/database.py:126-145` |
| 7 | Added "Pre-built study plans" to Key Design Decisions | MISSING | Architectural decision not documented |
| 8 | Added Backend Study Plans to Key Code Locations | MISSING | `features/study_plans/services/` exists |

---

### 2025-12-26 Update (Previous)

| # | Change | Type | Evidence |
|---|--------|------|----------|
| 1 | Updated Architecture diagram to show route_after_executor | MISSING | `tutor_workflow.py:90-102` |
| 2 | Added StudyPlanOrchestrator to architecture | MISSING | `workflow_adapter.py:69-71, 96-114` |
| 3 | Added study_plans to database list | MISSING | `models/database.py:126-150` |
| 4 | Fixed conversation context limiting (15 -> actual 10 in agents) | CORRECTION | `executor_agent.py:73`, `evaluator_agent.py:96` |
| 5 | Added route_after_executor routing function documentation | MISSING | `tutor_workflow.py:90-102` |
| 6 | Added prebuilt_plan flow to session creation | MISSING | `workflow_adapter.py:96-123` |
| 7 | Added study plan endpoints to Admin Guidelines API | MISSING | `admin_guidelines.py:725-795` |
| 8 | Expanded helpers.py function list | INCOMPLETE | `helpers.py` full analysis |
| 9 | Added Study Plans section to Key Files Reference | MISSING | `features/study_plans/services/*.py` |
| 10 | Added workflow_adapter StudyPlanOrchestrator integration | MISSING | `workflow_adapter.py:16, 69-71` |
| 11 | Added Pre-built study plans design decision | MISSING | Design pattern not documented |
| 12 | Added route_after_executor design decision | MISSING | Routing function not documented |

---

## Detailed Justifications (2025-12-28)

### 1. Added "Pre-Built Study Plans" Section

**Evidence:**
```python
# workflow_adapter.py:99-127
guideline_id = tutor_state.goal.guideline_id
prebuilt_plan = None
if guideline_id:
    try:
        prebuilt_plan = self.study_plan_orchestrator.get_study_plan(guideline_id)
        if prebuilt_plan:
            logger.info(f"Loaded pre-built study plan for guideline {guideline_id}")
        else:
            prebuilt_plan = self.study_plan_orchestrator.generate_study_plan(guideline_id)

# features/study_plans/services/orchestrator.py:13-103
class StudyPlanOrchestrator:
    """Orchestrates the creation and lifecycle of study plans."""
    def get_study_plan(self, guideline_id: str) -> dict | None: ...
    def generate_study_plan(self, guideline_id: str, force_regenerate: bool = False) -> dict: ...
```

**Why Added:** The study plans feature is a significant optimization that was completely undocumented.

---

### 2. Updated Phase 2 Session Creation Flow

**Evidence:**
```python
# tutor_workflow.py:280-318
def start_session(
    self,
    session_id: str,
    ...
    prebuilt_plan: Optional[dict] = None,  # <-- New parameter
) -> dict:
    initial_state = {
        ...
        "study_plan": prebuilt_plan or {},  # Uses pre-built if provided
    }
```

**Why Changed:** The flow diagram didn't show that PLANNER can be skipped when a pre-built plan exists.

---

### 3. Added 3 Additional Logs API Deprecated Endpoints

**Evidence:**
```python
# api/routes/logs.py:40-77
@router.get("/{session_id}/logs/text", response_class=PlainTextResponse)
async def get_session_logs_text(...): """Deprecated"""

@router.get("/{session_id}/logs/summary", response_model=SessionLogsSummary)
async def get_session_logs_summary(...): """Deprecated"""

@router.get("/{session_id}/logs/stream")
async def stream_session_logs(...): """Deprecated"""
```

**Why Added:** Only 2 of 5 deprecated endpoints were documented.

---

### 4. Added 3 Study Plan Endpoints to Admin Guidelines API

**Evidence:**
```python
# admin_guidelines.py:725-795
@router.post("/{guideline_id}/generate-study-plan")
@router.get("/{guideline_id}/study-plan")
@router.post("/bulk-generate-study-plans")
```

**Why Added:** These endpoints existed but were not in the API reference table.

---

### 5-6. Added Study Plans Files and Database Table

**Evidence:**
```
# Directory listing: llm-backend/features/study_plans/services/
orchestrator.py
generator_service.py
reviewer_service.py

# models/database.py:126-145
class StudyPlan(Base):
    __tablename__ = "study_plans"
    id, guideline_id, plan_json, generator_model, reviewer_model, ...
```

**Why Added:** Both the service files and database table were missing from documentation.

---

### 7-8. Added Design Decision and Key Code Location

**Why Added:** The pre-built study plans optimization is an important architectural decision that affects session startup latency.

---

## Detailed Justifications (2025-12-26)

### 1. Updated Architecture Diagram - route_after_executor

**Evidence:**
```python
# tutor_workflow.py:90-102
def route_after_executor(state: SimplifiedState) -> Literal["evaluator", "end"]:
    """
    Routing logic after EXECUTOR executes.
    If the last message is from a student, go to EVALUATOR to evaluate it.
    Otherwise, END (wait for student response).
    """
    conversation = state.get("conversation", [])
    if conversation and conversation[-1].get("role") == "student":
        return "evaluator"
    return "end"
```

**Why Added:** The documentation only showed `route_entry` and `route_after_evaluation`, but `route_after_executor` is a critical routing function that controls flow after EXECUTOR runs.

---

### 2. Added StudyPlanOrchestrator to Architecture

**Evidence:**
```python
# workflow_adapter.py:16
from features.study_plans.services.orchestrator import StudyPlanOrchestrator

# workflow_adapter.py:69-71
self.study_plan_orchestrator = StudyPlanOrchestrator(
    db, self.llm_service
)
```

**Why Added:** The SessionWorkflowAdapter integrates with StudyPlanOrchestrator to pre-load study plans, which is a significant architectural component not previously documented.

---

### 3. Added study_plans to Database Tables

**Evidence:**
```python
# models/database.py:126-150
class StudyPlan(Base):
    __tablename__ = "study_plans"
    id = Column(String, primary_key=True)
    guideline_id = Column(String, ForeignKey("teaching_guidelines.id", ondelete="CASCADE"), unique=True)
    plan_json = Column(Text, nullable=False)
    generator_model = Column(String)
    reviewer_model = Column(String)
    # ... additional fields
```

**Why Added:** The study_plans table is used by the tutor workflow but was not listed in the Database Tables section.

---

### 4. Fixed Conversation Context Limiting

**Evidence:**
```python
# helpers.py:130 - default is 15
def get_relevant_context(conversation: List[Dict[str, Any]], max_messages: int = 15):

# executor_agent.py:73 - actually uses 10
relevant_conversation = get_relevant_context(list(state.get("conversation", [])), max_messages=10)

# evaluator_agent.py:96 - also uses 10
relevant_conversation = get_relevant_context(list(conversation), max_messages=10)
```

**Why Changed:** Documentation said "Max 15 messages" but agents actually use `max_messages=10`. Updated to clarify: "Default 15 messages in helper; agents use 10 messages".

---

### 5. Added route_after_executor Routing Function

**Evidence:**
```python
# tutor_workflow.py:220-228
workflow.add_conditional_edges(
    "executor",
    route_after_executor,
    {
        "evaluator": "evaluator",
        "end": END,
    },
)
```

**Why Added:** This routing function was missing from the documentation but is essential for understanding the workflow edge cases.

---

### 6. Added Prebuilt Plan Flow to Session Creation

**Evidence:**
```python
# workflow_adapter.py:96-123
guideline_id = tutor_state.goal.guideline_id
prebuilt_plan = None
if guideline_id:
    try:
        # Try to get existing plan
        study_plan = self.study_plan_orchestrator.get_study_plan(guideline_id)
        if study_plan and study_plan.plan_json:
            prebuilt_plan = study_plan.plan_json
        else:
            # On-demand generation (fallback)
            self.study_plan_orchestrator.generate_study_plan(guideline_id)
            # ...
```

**Why Added:** The session creation flow now includes study plan pre-loading as an optimization, which significantly affects how sessions start.

---

### 7. Added Study Plan Endpoints to Admin Guidelines API

**Evidence:**
```python
# admin_guidelines.py:725-749
@router.post("/{guideline_id}/generate-study-plan")

# admin_guidelines.py:752-765
@router.get("/{guideline_id}/study-plan")

# admin_guidelines.py:772-795
@router.post("/bulk-generate-study-plans")
```

**Why Added:** These endpoints exist in `admin_guidelines.py` and are part of the admin workflow but were not documented.

---

### 8. Expanded helpers.py Function List

**Evidence:**
Full function list from `helpers.py`:
- `get_current_step()` - line 21
- `update_plan_statuses()` - line 63
- `get_relevant_context()` - line 129
- `validate_status_updates()` - line 174
- `is_session_complete()` - line 216
- `should_trigger_replan()` - line 329
- `calculate_progress()` - line 283
- `generate_step_id()` - line 268

**Why Changed:** Documentation only listed 3 functions; expanded to show all 8 helper functions.

---

### 9. Added Study Plans Section to Key Files Reference

**Evidence:**
```
llm-backend/features/study_plans/services/orchestrator.py
llm-backend/features/study_plans/services/generator_service.py
llm-backend/features/study_plans/services/reviewer_service.py
```

**Why Added:** These files are part of the tutor workflow's study plan integration but were not documented in Key Files Reference.

---

### 10. Added Workflow Adapter StudyPlanOrchestrator Integration

**Evidence:**
```python
# workflow_adapter.py:16
from features.study_plans.services.orchestrator import StudyPlanOrchestrator

# workflow_adapter.py:69-71
self.study_plan_orchestrator = StudyPlanOrchestrator(db, self.llm_service)
```

**Why Changed:** Updated `workflow_adapter.py` description to note it includes StudyPlanOrchestrator integration.

---

### 11-12. Added Design Decisions

Added two new design decisions:
- **Pre-built study plans**: Documents the optimization of loading plans from DB
- **route_after_executor**: Documents the additional routing function

---

## Files Examined During Analysis

**Backend:**
- `llm-backend/workflows/tutor_workflow.py` - LangGraph workflow definition
- `llm-backend/workflows/state.py` - SimplifiedState TypedDict
- `llm-backend/workflows/helpers.py` - Helper functions
- `llm-backend/agents/planner_agent.py` - PLANNER agent
- `llm-backend/agents/executor_agent.py` - EXECUTOR agent
- `llm-backend/agents/evaluator_agent.py` - EVALUATOR agent
- `llm-backend/services/llm_service.py` - LLM API wrapper
- `llm-backend/services/session_service.py` - Session orchestration
- `llm-backend/adapters/workflow_adapter.py` - Workflow adapter
- `llm-backend/api/routes/sessions.py` - Session endpoints
- `llm-backend/routers/admin_guidelines.py` - Admin guidelines API
- `llm-backend/features/study_plans/services/*.py` - Study plan services
- `llm-backend/models/database.py` - Database models

**Frontend:**
- `llm-frontend/src/TutorApp.tsx` - Main tutor component
- `llm-frontend/src/api.ts` - API client
