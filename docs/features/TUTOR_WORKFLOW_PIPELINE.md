# Tutor Workflow Pipeline

---

## Document Purpose

**This is the Single Source of Truth (SSOT)** for the adaptive AI tutoring workflow.

| Aspect | Details |
|--------|---------|
| **What it captures** | End-to-end workflow from topic selection -> session creation -> 3-agent teaching loop -> evaluation -> completion |
| **Audience** | New and existing developers needing complete context on this feature |
| **Scope** | Frontend components, LangGraph workflow, 3 agents (PLANNER/EXECUTOR/EVALUATOR), state management, API endpoints |
| **Maintenance** | Update this doc whenever tutor workflow code changes to keep it accurate |

**Key Code Locations:**
- Frontend Tutor: `llm-frontend/src/TutorApp.tsx`, `llm-frontend/src/api.ts`
- Frontend Admin: `llm-frontend/src/features/admin/`
- Backend Workflow: `llm-backend/workflows/`, `llm-backend/agents/`
- Backend Services: `llm-backend/services/session_service.py`, `llm-backend/adapters/`
- API: `llm-backend/api/routes/sessions.py`, `llm-backend/api/routes/curriculum.py`
- Admin API: `llm-backend/routers/admin_guidelines.py`, `llm-backend/features/book_ingestion/api/routes.py`

---

## Architecture Overview

```
+-------------------------------------------------------------------------+
|                         FRONTEND (React + React Router)                  |
|   Routes: / (tutor), /admin/books, /admin/guidelines                     |
|   Tutor: Subject -> Topic -> Subtopic Selection -> Chat Interface        |
+-------------------------------------+-----------------------------------+
                                      | REST API
+-------------------------------------v-----------------------------------+
|                         BACKEND (FastAPI)                                |
|   Routes: /sessions, /sessions/{id}/step, /sessions/{id}/summary         |
|           /curriculum, /admin/guidelines/*, /admin/books/*               |
|                                                                          |
|   SessionService -> SessionWorkflowAdapter -> TutorWorkflow (LangGraph)  |
|                                                                          |
|   +---------------------------------------------------------------+     |
|   |                    LANGGRAPH WORKFLOW                          |     |
|   |                                                                |     |
|   |  START -> ROUTER --+-> PLANNER -> EXECUTOR -+-> END            |     |
|   |                    |                        |                  |     |
|   |                    +-> EVALUATOR -+--> replan -> PLANNER       |     |
|   |                    |              +--> continue -> EXECUTOR    |     |
|   |                    |              +--> end -> END              |     |
|   |                    |                                           |     |
|   |                    +-> EXECUTOR (edge case)                    |     |
|   +---------------------------------------------------------------+     |
+-----------------------------------------+-------------------------------+
                                          |
+-----------------------------------------v-------------------------------+
|   PostgreSQL: sessions, events, teaching_guidelines, checkpoint_*       |
+-------------------------------------------------------------------------+
```

## The 3-Agent System

| Agent | Model | Reasoning | Structured Output | Responsibility |
|-------|-------|-----------|-------------------|----------------|
| **PLANNER** | GPT-5.2 | high | json_schema (strict) | Creates/updates study plan (3-5 steps), adapts to student profile |
| **EXECUTOR** | GPT-5.2 | none | json_schema (strict) | Generates teaching messages, questions, hints based on current plan |
| **EVALUATOR** | GPT-5.2 | medium | json_schema (strict) | Evaluates responses, updates step statuses, decides routing |

**Notes:**
- A ROUTER node provides intelligent entry-point routing but is not an LLM-based agent
- All agents use GPT-5.2 with strict `json_schema` structured output for guaranteed schema adherence
- PLANNER uses "high" reasoning for deep strategic thinking; EXECUTOR uses "none" for low-latency execution; EVALUATOR uses "medium" for balanced evaluation
- PLANNER has a safety guard: if plan exists and `replan_needed=False`, returns current state unchanged
- PLANNER uses a hardcoded test student profile for experimentation (see `planner_agent.py:100-110`)
- Pre-computed strict schemas are defined in `agents/llm_schemas.py`

---

## Pipeline Phases

| Phase | Action | Endpoint | Handler |
|-------|--------|----------|---------|
| 1 | Select Subject/Topic/Subtopic | `GET /curriculum` | TeachingGuidelineRepository |
| 2 | Create Session | `POST /sessions` | SessionService.create_new_session() |
| 3 | Submit Answer | `POST /sessions/{id}/step` | SessionService.process_step() |
| 4 | Get Summary | `GET /sessions/{id}/summary` | SessionService.get_summary() |

---

## Phase 1: Topic Selection (Frontend)

### Selection Flow
```
Frontend: TutorApp.tsx
    |
    +-> Step 1: Load subjects
    |     GET /curriculum?country=India&board=CBSE&grade=3
    |     Response: {subjects: ["Mathematics", "English", ...]}
    |
    +-> Step 2: User selects subject -> Load topics
    |     GET /curriculum?...&subject=Mathematics
    |     Response: {topics: ["Fractions", "Multiplication", ...]}
    |
    +-> Step 3: User selects topic -> Load subtopics
    |     GET /curriculum?...&subject=Mathematics&topic=Fractions
    |     Response: {subtopics: [{subtopic, guideline_id}, ...]}
    |
    +-> Step 4: User selects subtopic -> Create session
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
    |
    +-> 1. Load teaching guideline from DB (500-2000 words)
    +-> 2. Generate session_id (UUID)
    +-> 3. Initialize TutorState
    |
    +-> 4. SessionWorkflowAdapter.execute_present_node()
            |
            +-> TutorWorkflow.start_session()
                    |
                    +-> LangGraph: START -> ROUTER -> PLANNER -> EXECUTOR -> END
```

### LangGraph Execution (New Session)

**ROUTER** (`route_entry`):
```python
if not study_plan.todo_list:
    return "planner"  # New session -> create plan
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
    "content": "Imagine a pizza cut into 4 equal slices...",
    "timestamp": "2024-11-19T14:20:00Z"
}
```

### Response
```json
{
  "session_id": "uuid-456",
  "first_turn": {
    "message": "Imagine a pizza...",
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
    |
    +-> 1. Load session from DB
    +-> 2. Add student message to history
    |
    +-> 3. SessionWorkflowAdapter.execute_step_workflow()
            |
            +-> TutorWorkflow.submit_response()
                    |
                    +-> LangGraph: START -> ROUTER -> EVALUATOR -> [route] -> ...
```

### LangGraph Execution (Student Response)

**ROUTER** (`route_entry`):
```python
if conversation[-1].role == "student":
    return "evaluator"  # Student answered -> evaluate
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
    return "replan"  # -> PLANNER (update plan)
elif all_steps_completed:
    return "end"     # -> Session complete
else:
    return "continue"  # -> EXECUTOR (next question)
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
    "labels": [],
    "confidence": 0.9
  }
}
```

---

## Phase 4: Session Completion & Summary

### When Session Ends
- All steps have `status: "completed"` -> EVALUATOR routes to END
- Max replans exceeded -> END with intervention flag
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
pending --first question--> in_progress
                                |
              +-----------------+-----------------+
              |                 |                 |
       success_criteria    needs_more_work     3+ failures
       FULLY met              continue             |
              |                 |                 v
              v                 |             blocked
         completed              |           (replan trigger)
              |                 |
              +--------<--------+
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
    |
    v
ROUTER detects replan_needed -> "replan"
    |
    v
PLANNER receives:
  - Original plan
  - Assessment notes
  - Replan reason
  - Recent conversation
    |
    v
PLANNER outputs:
  - Updated todo_list (may insert prerequisite steps)
  - Incremented plan_version
  - Incremented replan_count
    |
    v
EXECUTOR generates message for new/updated step
```

---

## Key Files Reference

### Backend - Workflow & State
| File | Purpose |
|------|---------|
| `workflows/tutor_workflow.py` | LangGraph workflow + TutorWorkflow class |
| `workflows/state.py` | SimplifiedState TypedDict |
| `workflows/helpers.py` | get_current_step(), update_plan_statuses(), calculate_progress() |
| `workflows/schemas.py` | Validation schemas |

### Backend - Agents
| File | Purpose |
|------|---------|
| `agents/base.py` | BaseAgent abstract class with execution + logging |
| `agents/planner_agent.py` | PLANNER - creates/updates study plans (GPT-5.2 high reasoning) |
| `agents/executor_agent.py` | EXECUTOR - generates teaching messages (GPT-5.2 no reasoning) |
| `agents/evaluator_agent.py` | EVALUATOR - evaluates + routes (GPT-5.2 medium reasoning) |
| `agents/llm_schemas.py` | Pydantic models + pre-computed strict schemas for GPT-5.2 structured output |

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
| `services/llm_service.py` | LLM API wrapper (GPT-5.2 w/strict schema, GPT-5.1, GPT-4o, Gemini) |
| `api/routes/sessions.py` | Session endpoints |
| `api/routes/curriculum.py` | Curriculum discovery endpoints |
| `api/routes/health.py` | Health check endpoints |
| `api/routes/logs.py` | Logs API (DEPRECATED - returns empty, logs go to stdout) |
| `routers/admin_guidelines.py` | Admin guidelines API |
| `features/book_ingestion/api/routes.py` | Book ingestion & page management API |
| `features/book_ingestion/services/topic_subtopic_summary_service.py` | Auto-summary generation |
| `adapters/workflow_adapter.py` | TutorWorkflow <-> SessionService bridge |
| `adapters/state_adapter.py` | TutorState <-> SimplifiedState conversion |

### Frontend
| File | Purpose |
|------|---------|
| `src/TutorApp.tsx` | Main tutor component (selection + chat) |
| `src/api.ts` | Tutor API client with TypeScript interfaces |
| `src/App.tsx` | Routing: `/` (tutor), `/admin/books`, `/admin/guidelines` |
| `src/features/admin/pages/BooksDashboard.tsx` | Book list with status badges |
| `src/features/admin/pages/BookDetail.tsx` | Book management (pages + guidelines) |
| `src/features/admin/pages/GuidelinesReview.tsx` | Guidelines approval with filters |
| `src/features/admin/components/GuidelinesPanel.tsx` | Generate -> Finalize -> Approve workflow |
| `src/features/admin/api/adminApi.ts` | Admin API client |
| `src/features/admin/types/index.ts` | TypeScript interfaces for admin |

---

## LLM Calls Summary

| Agent | Model | Reasoning | Purpose | Output Schema |
|-------|-------|-----------|---------|---------------|
| PLANNER | GPT-5.2 | high | Create study plan | PlannerLLMOutput (strict json_schema) |
| PLANNER | GPT-5.2 | high | Replan | PlannerLLMOutput (strict json_schema) |
| EXECUTOR | GPT-5.2 | none | Generate message | ExecutorLLMOutput (strict json_schema) |
| EVALUATOR | GPT-5.2 | medium | Evaluate + route | EvaluatorLLMOutput (strict json_schema) |

**LLM Service Features:**
- GPT-5.2 for all agents with strict `json_schema` structured output
- Reasoning effort levels: none (fast), low, medium, high, xhigh (maximum)
- GPT-5.2 fallback to GPT-5.1, then GPT-4o if unavailable
- GPT-5.1 method with fallback to GPT-4o
- GPT-4o for legacy support
- Gemini support (gemini-3-pro-preview, via GEMINI_API_KEY)
- Automatic retry: 3 attempts with exponential backoff (1s -> 2s -> 4s)
- Timeout: 60 seconds per request
- Handles: RateLimitError, APITimeoutError, OpenAIError
- `make_schema_strict()` helper for Pydantic to OpenAI strict schema conversion

---

## API Endpoints Reference

### Health & Status
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check: returns `{status: "ok"}` |
| `GET` | `/health/db` | Database connectivity check |

### Session Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/sessions` | Create new session, returns first question |
| `POST` | `/sessions/{id}/step` | Submit student answer, get next turn |
| `GET` | `/sessions/{id}/summary` | Get session performance summary |
| `GET` | `/sessions/{id}` | Debug: Get full session state |

### Curriculum Discovery
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/curriculum?country=&board=&grade=` | Get available subjects |
| `GET` | `/curriculum?...&subject=` | Get topics for a subject |
| `GET` | `/curriculum?...&subject=&topic=` | Get subtopics with guideline IDs |

### Logs API (DEPRECATED)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/sessions/logs` | Returns empty list (deprecated) |
| `GET` | `/sessions/{id}/logs` | Returns empty (logs now go to stdout) |

### Book Ingestion API (`/admin/books`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/books` | Create new book |
| `GET` | `/admin/books` | List books with filters (country, board, grade, subject) |
| `GET` | `/admin/books/{id}` | Get book details |
| `DELETE` | `/admin/books/{id}` | Delete book |
| `POST` | `/admin/books/{id}/pages` | Upload page image (multipart/form-data) |
| `PUT` | `/admin/books/{id}/pages/{num}/approve` | Approve page |
| `DELETE` | `/admin/books/{id}/pages/{num}` | Delete page |
| `GET` | `/admin/books/{id}/pages/{num}` | Get page details |
| `POST` | `/admin/books/{id}/generate-guidelines` | Generate guidelines from pages |
| `POST` | `/admin/books/{id}/finalize` | Finalize & refine guidelines |
| `GET` | `/admin/books/{id}/guidelines` | List all guidelines for book |
| `GET` | `/admin/books/{id}/guidelines/{topic}/{subtopic}` | Get specific guideline |
| `PUT` | `/admin/books/{id}/guidelines/approve` | Approve & sync guidelines to DB |
| `DELETE` | `/admin/books/{id}/guidelines` | Reject/delete all guidelines |

### Admin Guidelines API (`/admin/guidelines`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/books` | List books with extraction status |
| `GET` | `/books/{id}/topics` | Get topics with subtopics for a book |
| `GET` | `/books/{id}/subtopics/{key}?topic_key=` | Get guideline details |
| `PUT` | `/books/{id}/subtopics/{key}` | DISABLED (501) - use regeneration |
| `GET` | `/books/{id}/page-assignments` | Get page-to-subtopic assignments |
| `POST` | `/books/{id}/extract?start_page=&end_page=` | Run guideline extraction |
| `POST` | `/books/{id}/finalize?auto_sync=` | Finalize guidelines |
| `POST` | `/books/{id}/sync-to-database?status_filter=` | Sync to teaching_guidelines table |
| `GET` | `/review` | List all guidelines for review with filters |
| `GET` | `/review/filters` | Get filter options and counts |
| `GET` | `/books/{id}/review` | List book guidelines for review |
| `POST` | `/{guideline_id}/approve` | Approve or reject (body: `{approved: bool}`) |
| `DELETE` | `/{guideline_id}` | Delete a guideline |

---

## Complete Flow Diagram

```
+-------------------------------------------------------------------------+
|                          NEW SESSION FLOW                                |
|                                                                          |
|  POST /sessions                                                          |
|       |                                                                  |
|       v                                                                  |
|  Load guideline from DB                                                  |
|       |                                                                  |
|       v                                                                  |
|  +-------------------------------------------------------------+        |
|  | LANGGRAPH: ROUTER -> PLANNER -> EXECUTOR -> END              |        |
|  |                                                              |        |
|  | ROUTER: No plan? -> "planner"                                |        |
|  | PLANNER: Create 3-5 step plan                               |        |
|  | EXECUTOR: Generate first question                           |        |
|  +-------------------------------------------------------------+        |
|       |                                                                  |
|       v                                                                  |
|  Return: {session_id, first_turn: {message, hints, step_idx}}           |
+-------------------------------------------------------------------------+

+-------------------------------------------------------------------------+
|                       STUDENT RESPONSE FLOW                              |
|                                                                          |
|  POST /sessions/{id}/step                                                |
|       |                                                                  |
|       v                                                                  |
|  Add student message to conversation                                     |
|       |                                                                  |
|       v                                                                  |
|  +-------------------------------------------------------------+        |
|  | LANGGRAPH: ROUTER -> EVALUATOR -> [route_after_evaluation]   |        |
|  |                                                              |        |
|  | ROUTER: Last msg is student? -> "evaluator"                  |        |
|  | EVALUATOR:                                                   |        |
|  |   - Score response (0.0-1.0)                                |        |
|  |   - Generate feedback                                        |        |
|  |   - Update step statuses                                     |        |
|  |   - Track assessment notes                                   |        |
|  |   - Decide: replan_needed?                                   |        |
|  |                                                              |        |
|  | ROUTING:                                                     |        |
|  |   replan_needed=true -> PLANNER -> EXECUTOR -> END           |        |
|  |   all_completed=true -> END                                  |        |
|  |   else -> EXECUTOR -> END                                    |        |
|  +-------------------------------------------------------------+        |
|       |                                                                  |
|       v                                                                  |
|  Return: {next_turn: {message, hints, step_idx, is_complete}}           |
+-------------------------------------------------------------------------+
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Status-based navigation** | Plan is source of truth; no manual step tracking |
| **3 separate agents** | Clear separation: planning vs execution vs evaluation |
| **ROUTER node** | Smart entry-point routing prevents infinite loops |
| **EVALUATOR as traffic controller** | Centralized routing decisions |
| **LangGraph + PostgreSQL checkpoints** | Session persistence, resumability |
| **Append-only conversation** | Never delete messages, maintain full context |
| **Simple text assessment notes** | Flexible, readable, no rigid schema |
| **5-section EVALUATOR prompt** | Structured output for all responsibilities |
| **Hardcoded student profile** | Experimentation mode (PLANNER overrides with test profile) |
| **Conversation context limiting** | Max 15 messages (first 3 + summary + last N) to prevent context overflow |
| **Single in_progress step** | Only ONE step can be in_progress at a time (enforced in validation) |
| **Auto-generated summaries** | Topic/subtopic summaries via gpt-4o-mini for token efficiency |
| **Stdout logging** | Logs API deprecated; structured JSON logs go to stdout |

---

## Persistence & Checkpointing

### Database Tables
| Table | Purpose |
|-------|---------|
| `sessions` | Session state: `id`, `student_json`, `goal_json`, `state_json`, `mastery`, `step_idx`, timestamps |
| `events` | Audit log: `session_id`, `node`, `step_idx`, `payload_json`, indexed by (session_id, step_idx) |
| `teaching_guidelines` | Guideline data with review workflow (see below) |
| `contents` | RAG corpus: `topic`, `grade`, `skill`, `text`, `tags` |
| `checkpoint_*` | LangGraph PostgreSQL checkpoint tables |

**teaching_guidelines columns:**
- Identity: `id`, `country`, `board`, `grade`, `subject`, `topic`, `subtopic`
- Content: `guideline` (main text), `metadata_json`
- Keys: `topic_key`, `subtopic_key`, `topic_title`, `subtopic_title`
- Summaries: `topic_summary`, `subtopic_summary` (auto-generated 15-40 words via gpt-4o-mini)
- Source: `book_id`, `source_page_start`, `source_page_end`
- Workflow: `status`, `review_status`, `version`

**books table:**
- Identity: `id`, `title`, `author`, `edition`, `edition_year`
- Curriculum: `country`, `board`, `grade`, `subject`
- Storage: `s3_prefix`, `cover_image_s3_key`
- Stats: `page_count`, `guideline_count`, `approved_guideline_count`
- Workflow: `has_active_job`, `created_at`, `updated_at`

### Checkpointing
- Uses `PostgresSaver` from `langgraph.checkpoint.postgres`
- State auto-saved after each node execution
- Resume from any checkpoint on failure
- `thread_id` = `session_id` for LangGraph config

---

## Logging & Observability

### Structured Logging to stdout
All logging is done via structured JSON to stdout for cloud-native observability:

```python
# In main.py - JSONFormatter outputs structured logs
{
  "timestamp": "2024-11-19T14:30:00Z",
  "level": "INFO",
  "logger": "agents.evaluator_agent",
  "step": "AGENT_EXECUTION:EVALUATOR",
  "status": "complete",
  "session_id": "uuid-123",
  "agent": "evaluator",
  "output": {...},
  "duration_ms": 1234
}
```

### Agent Execution Logs
- Each agent logs start/complete events with timing
- Full output and reasoning captured in `agent_logs` state field
- Duration tracked for performance monitoring

### Log Format Configuration
```bash
# Environment variables
LOG_FORMAT=json  # or "text" for development
LOG_LEVEL=INFO
```

**Note:** The `/sessions/logs` API endpoints are deprecated. They return empty responses. All logs are streamed to stdout.

---

## Admin Guideline Workflow

### Book Ingestion Pipeline
```
1. Create Book -> Upload Pages -> Approve Pages
2. Generate Guidelines -> Finalize -> Approve & Sync
```

### Guideline Status Flow
```
open --------+---------> stable ---------> final ---------> [synced to DB]
             |                              |
             +-----> needs_review ----------+
```

### Frontend Admin Routes
| Route | Component | Purpose |
|-------|-----------|---------|
| `/admin/books` | BooksDashboard | List books with status badges |
| `/admin/books/new` | CreateBook | Create new book form |
| `/admin/books/:id` | BookDetail | Manage pages and guidelines |
| `/admin/guidelines` | GuidelinesReview | Review/approve DB guidelines |

### Guideline Generation Workflow
1. **Generate**: AI analyzes approved pages, creates subtopic guidelines
2. **Finalize**: Improves names, merges duplicates, generates summaries, marks as 'final'
3. **Approve & Sync**: Copies final guidelines to `teaching_guidelines` table with `review_status=TO_BE_REVIEWED`
4. **Review**: Individual guidelines can be approved/rejected in GuidelinesReview

### Book Status States
| Status | Condition |
|--------|-----------|
| Draft | `page_count == 0` |
| Ready for Extraction | `page_count > 0 && guideline_count == 0` |
| Processing | `has_active_job == true` |
| Pending Review | Guidelines exist, not all approved |
| Approved | All guidelines approved |
