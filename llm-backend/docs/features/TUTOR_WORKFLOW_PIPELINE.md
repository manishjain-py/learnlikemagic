# Tutor Workflow Pipeline

---

## Document Purpose

**This is the Single Source of Truth (SSOT)** for the adaptive AI tutoring workflow.

| Aspect | Details |
|--------|---------|
| **What it captures** | End-to-end workflow from topic selection → session creation → 3-agent teaching loop → evaluation → completion |
| **Audience** | New and existing developers needing complete context on this feature |
| **Scope** | Frontend components, LangGraph workflow, 3 agents (PLANNER/EXECUTOR/EVALUATOR), state management, API endpoints |
| **Maintenance** | Update this doc whenever tutor workflow code changes to keep it accurate |

**Key Code Locations:**
- Frontend: `llm-frontend/src/TutorApp.tsx`, `llm-frontend/src/api.ts`
- Backend Workflow: `llm-backend/workflows/`, `llm-backend/agents/`
- Backend Services: `llm-backend/services/session_service.py`, `llm-backend/adapters/`
- API: `llm-backend/api/routes/sessions.py`

---

> Complete technical reference for the adaptive AI tutoring system with 3-agent LangGraph architecture.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                                 │
│   Subject → Topic → Subtopic Selection → Chat Interface                 │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ REST API
┌─────────────────────────────────▼───────────────────────────────────────┐
│                         BACKEND (FastAPI)                                │
│   Routes: /sessions, /sessions/{id}/step, /sessions/{id}/summary        │
│                                                                          │
│   SessionService → SessionWorkflowAdapter → TutorWorkflow (LangGraph)   │
│                                                                          │
│   ┌───────────────────────────────────────────────────────────────┐     │
│   │                    LANGGRAPH WORKFLOW                          │     │
│   │  START → ROUTER → PLANNER ──┐                                  │     │
│   │                    ↓        │                                  │     │
│   │              EXECUTOR ←─────┤                                  │     │
│   │                    ↓        │                                  │     │
│   │              EVALUATOR ─────┴─→ END                            │     │
│   └───────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────┐
│   PostgreSQL: sessions, events, teaching_guidelines, checkpoints        │
└─────────────────────────────────────────────────────────────────────────┘
```

## The 3-Agent System

| Agent | Model | Responsibility |
|-------|-------|----------------|
| **PLANNER** | GPT-4o | Creates/updates study plan (3-5 steps), adapts to student profile |
| **EXECUTOR** | GPT-4o | Generates teaching messages, questions, hints based on current plan |
| **EVALUATOR** | GPT-4o | Evaluates responses, updates step statuses, decides routing |

---

## Pipeline Phases

| Phase | Action | Endpoint | Handler |
|-------|--------|----------|---------|
| 1 | Select Subject/Topic/Subtopic | `GET /curriculum` | CurriculumService |
| 2 | Create Session | `POST /sessions` | SessionService.create_new_session() |
| 3 | Submit Answer | `POST /sessions/{id}/step` | SessionService.process_step() |
| 4 | Get Summary | `GET /sessions/{id}/summary` | SessionService.get_summary() |

---

## Phase 1: Topic Selection (Frontend)

### Selection Flow
```
Frontend: TutorApp.tsx
    │
    ├─▶ Step 1: Load subjects
    │     GET /curriculum?country=India&board=CBSE&grade=3
    │     Response: {subjects: ["Mathematics", "English", ...]}
    │
    ├─▶ Step 2: User selects subject → Load topics
    │     GET /curriculum?...&subject=Mathematics
    │     Response: {topics: ["Fractions", "Multiplication", ...]}
    │
    ├─▶ Step 3: User selects topic → Load subtopics
    │     GET /curriculum?...&subject=Mathematics&topic=Fractions
    │     Response: {subtopics: [{subtopic, guideline_id}, ...]}
    │
    └─▶ Step 4: User selects subtopic → Create session
```

**Hardcoded Values (Frontend):**
```typescript
const COUNTRY = 'India';
const BOARD = 'CBSE';
const GRADE = 3;
```

---

## Phase 2: Session Creation

### Entry Point
```
POST /sessions
Body: {
  student: {id, grade, prefs: {style, lang}},
  goal: {topic, syllabus, learning_objectives, guideline_id}
}
```

### Flow
```
SessionService.create_new_session()
    │
    ├─▶ 1. Load teaching guideline from DB (500-2000 words)
    ├─▶ 2. Generate session_id (UUID)
    ├─▶ 3. Initialize TutorState
    │
    └─▶ 4. SessionWorkflowAdapter.execute_present_node()
            │
            └─▶ TutorWorkflow.start_session()
                    │
                    └─▶ LangGraph: START → ROUTER → PLANNER → EXECUTOR → END
```

### LangGraph Execution (New Session)

**ROUTER** (`route_entry`):
```python
if not study_plan.todo_list:
    return "planner"  # New session → create plan
```

**PLANNER** (`planner_agent.py`):
```python
# Input: guidelines, student_profile, topic_info
# Output: study_plan with todo_list (3-5 steps)

study_plan = {
    "todo_list": [
        {
            "step_id": "uuid",
            "title": "Pizza Fraction Fun",
            "description": "Introduce fractions using pizza slices",
            "teaching_approach": "Visual + gamification",
            "success_criteria": "Student correctly compares 3 fraction pairs",
            "status": "pending",  # pending | in_progress | completed | blocked
            "status_info": {
                "questions_asked": 0,
                "questions_correct": 0,
                "attempts": 0
            }
        },
        # ... more steps
    ],
    "metadata": {
        "plan_version": 1,
        "replan_count": 0,
        "max_replans": 3
    }
}
```

**EXECUTOR** (`executor_agent.py`):
```python
# Input: study_plan, current_step, conversation
# Output: Teaching message added to conversation

message = {
    "role": "tutor",
    "content": "🍕 Imagine a pizza cut into 4 equal slices...",
    "timestamp": "2024-11-19T14:20:00Z"
}
```

### Response
```json
{
  "session_id": "uuid-456",
  "first_turn": {
    "message": "🍕 Imagine a pizza...",
    "hints": ["Count the slices each person has"],
    "step_idx": 0,
    "mastery_score": 0.5
  }
}
```

---

## Phase 3: Student Response Loop

### Entry Point
```
POST /sessions/{session_id}/step
Body: {student_reply: "I have 3 slices and you have 1, so I have more!"}
```

### Flow
```
SessionService.process_step()
    │
    ├─▶ 1. Load session from DB
    ├─▶ 2. Add student message to history
    │
    └─▶ 3. SessionWorkflowAdapter.execute_step_workflow()
            │
            └─▶ TutorWorkflow.submit_response()
                    │
                    └─▶ LangGraph: START → ROUTER → EVALUATOR → [route] → ...
```

### LangGraph Execution (Student Response)

**ROUTER** (`route_entry`):
```python
if conversation[-1].role == "student":
    return "evaluator"  # Student answered → evaluate
```

**EVALUATOR** (`evaluator_agent.py`) - The Traffic Controller:

5 responsibilities in one LLM call:

```python
# Output structure:
{
    # 1. EVALUATION
    "score": 0.95,              # 0.0-1.0
    "feedback": "Excellent! You correctly compared...",
    "reasoning": "Student understood numerator comparison",

    # 2. STEP STATUS UPDATES
    "updated_step_statuses": {
        "step-uuid-1": "in_progress"  # or "completed" | "blocked"
    },
    "updated_status_info": {
        "step-uuid-1": {
            "questions_asked": 2,
            "questions_correct": 2,
            "attempts": 2
        }
    },

    # 3. ASSESSMENT TRACKING
    "assessment_note": "2024-11-19 14:30 - Student correctly compared fractions...",

    # 4. OFF-TOPIC HANDLING
    "was_off_topic": false,
    "off_topic_response": null,  # or friendly redirect

    # 5. REPLANNING DECISION
    "replan_needed": false,
    "replan_reason": null  # or "Student failed 3x on same concept"
}
```

**Routing After Evaluation** (`route_after_evaluation`):
```python
if replan_needed and replan_count < max_replans:
    return "replan"  # → PLANNER (update plan)
elif all_steps_completed:
    return "end"     # → Session complete
else:
    return "continue"  # → EXECUTOR (next question)
```

**EXECUTOR** (if continuing):
- Generates next question for current step
- Or moves to next pending step if current completed

### Response
```json
{
  "next_turn": {
    "message": "Great! Now Maria has 2/4 of a chocolate bar...",
    "hints": ["Compare the top numbers"],
    "step_idx": 0,
    "mastery_score": 0.68,
    "is_complete": false
  },
  "routing": "Advance",
  "last_grading": {
    "score": 0.95,
    "rationale": "Student correctly identified...",
    "labels": []
  }
}
```

---

## Phase 4: Session Completion & Summary

### When Session Ends
- All steps have `status: "completed"` → EVALUATOR routes to END
- Max replans exceeded → END with intervention flag
- Frontend detects `is_complete: true`

### Summary Endpoint
```
GET /sessions/{session_id}/summary
```

### Response
```json
{
  "steps_completed": 3,
  "mastery_score": 0.87,
  "misconceptions_seen": ["confusing_denominator_size"],
  "suggestions": [
    "Excellent work on Fractions!",
    "Ready for more advanced topics",
    "Review: denominator concepts"
  ]
}
```

---

## State Management

### SimplifiedState (LangGraph State)
```python
class SimplifiedState(TypedDict):
    # Session metadata
    session_id: str
    created_at: str
    last_updated_at: str

    # Immutable inputs
    guidelines: str                    # Teaching guideline (500-2000 words)
    student_profile: Dict[str, Any]    # {interests, learning_style, grade, ...}
    topic_info: Dict[str, Any]         # {topic, subtopic, grade}
    session_context: Dict[str, Any]    # {estimated_duration_minutes}

    # Dynamic state
    study_plan: Dict[str, Any]         # SOURCE OF TRUTH (todo_list with statuses)
    assessment_notes: str              # Accumulated text observations
    conversation: Sequence[Dict]       # Append-only messages

    # Control flags
    replan_needed: bool
    replan_reason: Optional[str]

    # Observability
    agent_logs: Sequence[Dict]         # Append-only execution logs
```

### Step Status Flow
```
pending ──first question──▶ in_progress
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
       success_criteria    needs_more_work     3+ failures
       FULLY met              continue             │
              │                 │                 ▼
              ▼                 │             blocked
         completed              │           (replan trigger)
              │                 │
              └────────◀────────┘
```

### Dynamic Current Step (No Manual Tracking)
```python
def get_current_step(plan):
    # Priority 1: Find step with status="in_progress"
    # Priority 2: Find first step with status="pending"
    # Default: None (all completed)
```

---

## Replanning Logic

### Triggers (EVALUATOR decides)
- 3+ failures on same concept
- Knowledge gap detected (missing prerequisite)
- Student excelling (can skip steps)
- Approach not working

### Does NOT Trigger
- Single mistakes (normal learning)
- Off-topic responses (redirect instead)
- Normal progression

### Replan Flow
```
EVALUATOR sets replan_needed=true, replan_reason="..."
    │
    ▼
ROUTER detects replan_needed → "replan"
    │
    ▼
PLANNER receives:
  - Original plan
  - Assessment notes
  - Replan reason
  - Recent conversation
    │
    ▼
PLANNER outputs:
  - Updated todo_list (may insert prerequisite steps)
  - Incremented plan_version
  - Incremented replan_count
    │
    ▼
EXECUTOR generates message for new/updated step
```

---

## Key Files Reference

### Backend - Workflow & State
| File | Purpose |
|------|---------|
| `workflows/tutor_workflow.py` | LangGraph workflow + TutorWorkflow class |
| `workflows/state.py` | SimplifiedState TypedDict |
| `workflows/helpers.py` | get_current_step(), update_plan_statuses() |

### Backend - Agents
| File | Purpose |
|------|---------|
| `agents/base.py` | BaseAgent abstract class |
| `agents/planner_agent.py` | PLANNER - creates/updates study plans |
| `agents/executor_agent.py` | EXECUTOR - generates teaching messages |
| `agents/evaluator_agent.py` | EVALUATOR - evaluates + routes |

### Backend - Prompts
| File | Purpose |
|------|---------|
| `agents/prompts/planner_initial.txt` | Initial planning prompt |
| `agents/prompts/planner_replan.txt` | Replanning prompt |
| `agents/prompts/executor.txt` | Message generation prompt |
| `agents/prompts/evaluator.txt` | Evaluation prompt (5 sections) |

### Backend - Services & API
| File | Purpose |
|------|---------|
| `services/session_service.py` | Session orchestration |
| `services/llm_service.py` | OpenAI API wrapper |
| `services/agent_logging_service.py` | Dual-format logging |
| `api/routes/sessions.py` | Session endpoints |
| `adapters/workflow_adapter.py` | TutorWorkflow ↔ SessionService bridge |
| `adapters/state_adapter.py` | TutorState ↔ SimplifiedState conversion |

### Frontend
| File | Purpose |
|------|---------|
| `src/TutorApp.tsx` | Main component (selection + chat) |
| `src/api.ts` | API client with TypeScript interfaces |

---

## LLM Calls Summary

| Agent | Model | Purpose | Output |
|-------|-------|---------|--------|
| PLANNER | GPT-4o | Create study plan | JSON: todo_list, metadata |
| PLANNER | GPT-4o | Replan | JSON: updated todo_list |
| EXECUTOR | GPT-4o | Generate message | JSON: message, hints, reasoning |
| EVALUATOR | GPT-4o | Evaluate + route | JSON: score, feedback, statuses, replan |

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          NEW SESSION FLOW                                │
│                                                                          │
│  POST /sessions                                                          │
│       │                                                                  │
│       ▼                                                                  │
│  Load guideline from DB                                                  │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐        │
│  │ LANGGRAPH: ROUTER → PLANNER → EXECUTOR → END                │        │
│  │                                                              │        │
│  │ ROUTER: No plan? → "planner"                                │        │
│  │ PLANNER: Create 3-5 step plan                               │        │
│  │ EXECUTOR: Generate first question                           │        │
│  └─────────────────────────────────────────────────────────────┘        │
│       │                                                                  │
│       ▼                                                                  │
│  Return: {session_id, first_turn: {message, hints, step_idx}}           │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                       STUDENT RESPONSE FLOW                              │
│                                                                          │
│  POST /sessions/{id}/step                                                │
│       │                                                                  │
│       ▼                                                                  │
│  Add student message to conversation                                     │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐        │
│  │ LANGGRAPH: ROUTER → EVALUATOR → [route_after_evaluation]    │        │
│  │                                                              │        │
│  │ ROUTER: Last msg is student? → "evaluator"                  │        │
│  │ EVALUATOR:                                                   │        │
│  │   - Score response (0.0-1.0)                                │        │
│  │   - Generate feedback                                        │        │
│  │   - Update step statuses                                     │        │
│  │   - Track assessment notes                                   │        │
│  │   - Decide: replan_needed?                                  │        │
│  │                                                              │        │
│  │ ROUTING:                                                     │        │
│  │   replan_needed=true → PLANNER → EXECUTOR → END             │        │
│  │   all_completed=true → END                                   │        │
│  │   else → EXECUTOR → END                                      │        │
│  └─────────────────────────────────────────────────────────────┘        │
│       │                                                                  │
│       ▼                                                                  │
│  Return: {next_turn: {message, hints, step_idx, is_complete}}           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Status-based navigation** | Plan is source of truth; no manual step tracking |
| **3 separate agents** | Clear separation: planning vs execution vs evaluation |
| **EVALUATOR as traffic controller** | Centralized routing decisions |
| **LangGraph + PostgreSQL checkpoints** | Session persistence, resumability |
| **Append-only conversation** | Never delete messages, maintain full context |
| **Simple text assessment notes** | Flexible, readable, no rigid schema |
| **5-section EVALUATOR prompt** | Structured output for all responsibilities |
| **Hardcoded student profile** | Experimentation mode (to be made dynamic) |

---

## Persistence & Checkpointing

### Database Tables
| Table | Purpose |
|-------|---------|
| `sessions` | Full `state_json` (TutorState serialized) |
| `events` | Audit log of node executions |
| `teaching_guidelines` | Guideline text by subtopic |
| `checkpoint_*` | LangGraph checkpoint tables |

### Checkpointing
- State auto-saved after each node execution
- Resume from any checkpoint on failure
- `thread_id` = `session_id` for LangGraph config

---

## Logging & Observability

### Agent Logging Service
```
logs/sessions/{session_id}/
    agent_steps.jsonl    # Machine-readable (one JSON per line)
    agent_steps.txt      # Human-readable (formatted output)
```

### Log Entry Structure
```json
{
  "timestamp": "2024-11-19T14:30:00Z",
  "agent": "evaluator",
  "input_summary": "Evaluate response for 'Pizza Fractions'",
  "output": {...},
  "reasoning": "Student correctly compared..."
}
```
