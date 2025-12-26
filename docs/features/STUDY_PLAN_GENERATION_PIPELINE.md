# Study Plan Generation Pipeline

---

## Document Purpose

**Design spec** for moving study plan generation from Tutor Workflow to Guideline Generation Workflow.

| Aspect | Details |
|--------|---------|
| **Problem** | Study plan generation happens at runtime (user-facing) - too slow for good UX |
| **Solution** | Pre-generate generic study plans during admin workflow (can take time, use better models) |
| **Key Benefit** | User-facing tutor workflow starts instantly with pre-built plan |

---

## Architecture Change

```
BEFORE (study plan at runtime):
┌──────────────────────┐      ┌─────────────────────────────────────┐
│ Guideline Workflow   │      │ Tutor Workflow (user-facing)        │
│                      │      │                                     │
│ Guidelines → Sync DB │─────▶│ PLANNER creates plan  ← SLOW       │
│                      │      │ EXECUTOR/EVALUATOR loop             │
└──────────────────────┘      └─────────────────────────────────────┘

AFTER (study plan pre-generated):
┌─────────────────────────────────────┐    ┌────────────────────────────┐
│ Guideline Workflow (admin-facing)   │    │ Tutor Workflow (FAST)      │
│                                     │    │                            │
│ Guidelines → Sync DB → Approve      │    │ Load pre-built plan ✓      │
│       ↓                             │───▶│ EXECUTOR/EVALUATOR loop    │
│ [Admin clicks "Generate Plan"]      │    │ (PLANNER only for replan)  │
│       ↓                             │    │                            │
│ Generator → Reviewer → Update       │    └────────────────────────────┘
│       ↓                             │
│ study_plans table                   │
└─────────────────────────────────────┘
```

---

## Requirements Summary

| # | Requirement | Decision |
|---|-------------|----------|
| 1 | Trigger | Manual admin button on approved guidelines page |
| 2 | Storage | Separate `study_plans` table with FK to guideline |
| 3 | Review loop | AI→AI, one pass: generate → review → update |
| 4 | Tutor integration | Skip PLANNER on first turn; PLANNER only for replanning |
| 5 | Cardinality | 1:1 (one study plan per guideline) |
| 6 | Backward compat | On-demand generation when accessed (no PLANNER fallback) |

---

## Study Plan Generation Flow

```
Admin clicks "Generate Study Plan" on approved guideline
                    ↓
    ┌───────────────────────────────┐
    │   STUDY PLAN GENERATOR        │
    │   (thinking model: o1/o3)     │
    │                               │
    │   Input:                      │
    │   - guideline text            │
    │   - topic/subtopic info       │
    │   - grade level               │
    │                               │
    │   Output:                     │
    │   - study_plan (3-5 steps)    │
    │   - reasoning                 │
    └───────────────┬───────────────┘
                    ↓
    ┌───────────────────────────────┐
    │   STUDY PLAN REVIEWER         │
    │   (thinking model: o1/o3)     │
    │                               │
    │   Input:                      │
    │   - generated study_plan      │
    │   - guideline context         │
    │                               │
    │   Output:                     │
    │   - approved: bool            │
    │   - feedback: str (if issues) │
    │   - suggested_changes: list   │
    └───────────────┬───────────────┘
                    ↓
              ┌─────┴─────┐
              │ approved? │
              └─────┬─────┘
           yes/     \no
             ↓       ↓
         [SAVE]   ┌──────────────────────┐
                  │ GENERATOR (update)   │
                  │ Refine based on      │
                  │ reviewer feedback    │
                  └──────────┬───────────┘
                             ↓
                         [SAVE]
```

---

## Data Model

### New Table: `study_plans`

```sql
CREATE TABLE study_plans (
    id VARCHAR PRIMARY KEY,
    guideline_id VARCHAR NOT NULL REFERENCES teaching_guidelines(id),

    -- The plan itself
    plan_json JSONB NOT NULL,          -- {todo_list: [...], metadata: {...}}

    -- Generation metadata
    generator_model VARCHAR,            -- e.g., "o1", "gpt-4o"
    reviewer_model VARCHAR,
    generation_reasoning TEXT,
    reviewer_feedback TEXT,
    was_revised BOOLEAN DEFAULT FALSE,

    -- Status
    status VARCHAR DEFAULT 'active',    -- active, deprecated
    version INT DEFAULT 1,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(guideline_id)                -- 1:1 relationship
);
```

### Plan JSON Structure (same as current PLANNER output)

```json
{
  "todo_list": [
    {
      "step_id": "uuid",
      "title": "Pizza Fraction Fun",
      "description": "Introduce fractions using pizza slices",
      "teaching_approach": "Visual + gamification",
      "success_criteria": "Student correctly compares 3 fraction pairs",
      "status": "pending"
    }
  ],
  "metadata": {
    "plan_version": 1,
    "estimated_duration_minutes": 15,
    "difficulty_level": "grade-appropriate"
  }
}
```

---

## Component Design

### 1. StudyPlanGeneratorService

```python
class StudyPlanGeneratorService:
    """Generates generic study plan from guideline."""

    async def generate(
        self,
        guideline: TeachingGuideline,
    ) -> StudyPlanGeneratorOutput:
        """
        Input: guideline (with topic, subtopic, grade, content)
        Output: study_plan dict + reasoning
        Model: o1 or o3 (thinking model for deep reasoning)
        """
```

### 2. StudyPlanReviewerService

```python
class StudyPlanReviewerService:
    """Reviews generated study plan for quality."""

    async def review(
        self,
        study_plan: dict,
        guideline: TeachingGuideline,
    ) -> StudyPlanReviewOutput:
        """
        Output: {approved: bool, feedback: str, suggested_changes: list}
        Model: o1 or o3
        """
```

### 3. StudyPlanOrchestrator

```python
class StudyPlanOrchestrator:
    """Orchestrates generate → review → update flow."""

    async def create_study_plan(
        self,
        guideline_id: str,
    ) -> StudyPlan:
        """
        1. Load guideline
        2. Generate initial plan
        3. Review plan
        4. If not approved: regenerate with feedback
        5. Save to study_plans table
        """
```

---

## Tutor Workflow Changes

### Current Flow (PLANNER on every new session)
```
POST /sessions → PLANNER creates plan → EXECUTOR starts
```

### New Flow (Skip PLANNER, load pre-built plan)
```
POST /sessions
    ↓
Load study_plan from DB (by guideline_id)
    ↓
    ├── Plan exists? → Initialize state with plan → EXECUTOR starts
    │
    └── No plan? → Generate on-demand → Save → EXECUTOR starts
                   (one-time cost, then cached)
```

### PLANNER Role Changes
- **Before**: Creates plan from scratch on every session
- **After**: Only invoked for REPLANNING (when EVALUATOR triggers replan)

### Router Logic Update
```python
def route_entry(state):
    if not state["study_plan"]["todo_list"]:
        # This should not happen anymore (plan pre-loaded)
        raise Error("No study plan - should be pre-generated")

    if state["replan_needed"]:
        return "planner"  # Replan case

    if last_message_is_student:
        return "evaluator"

    return "executor"
```

---

## API Endpoints

### New Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/guidelines/{id}/generate-study-plan` | Trigger study plan generation |
| `GET` | `/admin/guidelines/{id}/study-plan` | Get study plan for guideline |
| `DELETE` | `/admin/guidelines/{id}/study-plan` | Delete and regenerate |

### Bulk Operations (future)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/guidelines/generate-study-plans` | Bulk generate for multiple guidelines |

---

## Key Files to Modify/Create

### New Files
| File | Purpose |
|------|---------|
| `llm-backend/services/study_plan_generator_service.py` | Generator component |
| `llm-backend/services/study_plan_reviewer_service.py` | Reviewer component |
| `llm-backend/services/study_plan_orchestrator.py` | Orchestration |
| `llm-backend/models/study_plan.py` | SQLAlchemy model |
| `llm-backend/agents/prompts/study_plan_generator.txt` | Generator prompt |
| `llm-backend/agents/prompts/study_plan_reviewer.txt` | Reviewer prompt |

### Modified Files
| File | Change |
|------|--------|
| `llm-backend/services/session_service.py` | Load pre-built plan instead of calling PLANNER |
| `llm-backend/workflows/tutor_workflow.py` | Update router logic |
| `llm-backend/adapters/workflow_adapter.py` | Pass pre-loaded plan |
| `llm-backend/routers/admin_guidelines.py` | Add study plan endpoints |
| `llm-frontend/src/features/admin/pages/GuidelinesReview.tsx` | Add "Generate Plan" button |
| `llm-frontend/src/features/admin/api/adminApi.ts` | Add API calls |

---

## Edge Cases

| Case | Handling |
|------|----------|
| No study plan when student starts session | Generate on-demand, save for future |
| Guideline updated after plan generated | Mark plan as `deprecated`, require regeneration |
| Plan generation fails | Return error, allow retry |
| Reviewer rejects plan | One revision attempt with feedback |

---

## Open Questions

1. **Model selection**: Confirm o1/o3 availability and cost implications
2. **Timeout handling**: Thinking models can take 30-60s - need appropriate timeouts
3. **Plan versioning**: When guideline changes, auto-deprecate plan or manual?
4. **Bulk generation**: Priority for batch processing UI?

---

## Success Metrics

- Session start time: < 2s (vs current 5-10s with PLANNER)
- Study plan quality: Measured via student completion rates
- Admin workflow: Plan generation < 60s acceptable
