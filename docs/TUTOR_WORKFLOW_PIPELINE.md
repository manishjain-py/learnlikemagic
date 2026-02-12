# Tutor Workflow Pipeline

---

## Document Purpose

**This is the Single Source of Truth (SSOT)** for the adaptive AI tutoring workflow.

| Aspect | Details |
|--------|---------|
| **What it captures** | End-to-end workflow from topic selection -> session creation -> single master tutor teaching loop -> completion |
| **Audience** | New and existing developers needing complete context on this feature |
| **Scope** | Frontend components, single master tutor architecture, state management, REST + WebSocket APIs, evaluation pipeline |
| **Maintenance** | Update this doc whenever tutor workflow code changes to keep it accurate |

**Key Code Locations:**
- Frontend Tutor: `llm-frontend/src/TutorApp.tsx`, `llm-frontend/src/api.ts`
- Frontend Admin: `llm-frontend/src/features/admin/`
- Backend Tutor: `llm-backend/tutor/` (agents, orchestration, services, api, models, prompts, utils)
- Backend Shared: `llm-backend/shared/` (llm_service, anthropic_adapter, health api)
- Backend Study Plans: `llm-backend/study_plans/services/`
- Backend Evaluation: `llm-backend/evaluation/`
- Admin API: `llm-backend/study_plans/api/admin.py`, `llm-backend/book_ingestion/api/routes.py`

---

## Architecture Overview

```
+-------------------------------------------------------------------------+
|                         FRONTEND (React + React Router)                  |
|   Routes: / (tutor), /admin/books, /admin/guidelines                     |
|   Tutor: Subject -> Topic -> Subtopic Selection -> Chat Interface        |
+-------------------------------------+-----------------------------------+
                                      | REST + WebSocket
+-------------------------------------v-----------------------------------+
|                         BACKEND (FastAPI)                                |
|   REST:  /sessions, /sessions/{id}/step, /sessions/{id}/summary         |
|   WS:   /sessions/ws/{session_id}                                       |
|   Eval: /api/evaluation/*                                               |
|                                                                          |
|   SessionService -> TeacherOrchestrator -> Master Tutor Agent            |
|                                                                          |
|   +---------------------------------------------------------------+     |
|   |               SINGLE MASTER TUTOR ARCHITECTURE                |     |
|   |                                                                |     |
|   |   Student Message                                              |     |
|   |       |                                                        |     |
|   |       v                                                        |     |
|   |   SAFETY AGENT (fast gate)                                     |     |
|   |       |                                                        |     |
|   |       v                                                        |     |
|   |   MASTER TUTOR (single LLM call handles everything)            |     |
|   |       |                                                        |     |
|   |       v                                                        |     |
|   |   STATE UPDATES (mastery, misconceptions, step advance)        |     |
|   |       |                                                        |     |
|   |       v                                                        |     |
|   |   Response to Student                                          |     |
|   +---------------------------------------------------------------+     |
+-----------------------------------------+-------------------------------+
                                          |
+-----------------------------------------v-------------------------------+
|   PostgreSQL: sessions, events, teaching_guidelines, study_plans         |
+-------------------------------------------------------------------------+
```

## The Agent System

| Agent | Model | Reasoning | Structured Output | Responsibility |
|-------|-------|-----------|-------------------|----------------|
| **SAFETY** | GPT-5.2 | none | json_schema (strict) | Fast content moderation gate |
| **MASTER TUTOR** | GPT-5.2 | none | json_schema (strict) | All teaching: explain, ask questions, evaluate answers, track mastery, advance steps |

**Key difference from old architecture:** The old 3-agent pipeline (PLANNER -> EXECUTOR -> EVALUATOR) has been replaced with a single Master Tutor agent that handles all teaching in one LLM call, producing more natural conversations.

**Provider support:** The system supports OpenAI (GPT-5.2) and Anthropic (Claude) via the `APP_LLM_PROVIDER` environment variable.

---

## Pipeline Phases

| Phase | Action | Endpoint | Handler |
|-------|--------|----------|---------|
| 1 | Select Subject/Topic/Subtopic | `GET /curriculum` | TeachingGuidelineRepository |
| 2 | Create Session | `POST /sessions` | SessionService.create_new_session() |
| 3 | Submit Answer (REST) | `POST /sessions/{id}/step` | SessionService.process_step() |
| 3a | Chat (WebSocket) | `WS /sessions/ws/{id}` | websocket_endpoint() |
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

---

## Pre-Built Study Plans

Before a session starts, the system loads a **pre-built study plan** from the database. The study plan defines the teaching sequence (explain -> check -> practice steps).

### Study Plan Conversion
```
DB StudyPlan.plan_json -> topic_adapter.convert_guideline_to_topic() -> Topic model
```

The `topic_adapter` converts the DB format (todo_list with title/description) into the new model format (StudyPlanStep with type/concept/content_hint).

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
    +-> 1. Load teaching guideline from DB
    +-> 2. Load study plan from DB (if available)
    +-> 3. Convert to Topic model via topic_adapter
    +-> 4. Create StudentContext (grade, board, language_level)
    +-> 5. Create SessionState
    +-> 6. Generate welcome message via orchestrator
    +-> 7. Persist session to DB
    +-> 8. Return {session_id, first_turn}
```

### Response
```json
{
  "session_id": "uuid-456",
  "first_turn": {
    "message": "Welcome! I'm excited to learn about fractions with you...",
    "hints": [],
    "step_idx": 1
  }
}
```

---

## Phase 3: Student Response Loop

### REST Entry Point
```
POST /sessions/{session_id}/step
Body: {student_reply: "I think 5/8 is bigger because 5 is more than 3"}
```

### WebSocket Entry Point
```
WS /sessions/ws/{session_id}
Send: {"type": "chat", "payload": {"message": "I think 5/8 is bigger..."}}
```

### Orchestrator Flow
```
TeacherOrchestrator.process_turn(session, student_message)
    |
    +-> 1. Increment turn, add student message to history
    +-> 2. Build AgentContext
    |
    +-> 3. SAFETY AGENT (fast check)
    |       |-> If unsafe: return guidance, log safety flag
    |       |-> If safe: continue
    |
    +-> 4. MASTER TUTOR AGENT (single LLM call)
    |       Input: system prompt (study plan, guidelines, 8 teaching rules)
    |              + turn prompt (current state, mastery, history, student message)
    |       Output: TutorTurnOutput {
    |           response,           # student-facing text
    |           intent,             # answer/question/confusion/off_topic/continuation
    |           answer_correct,     # true/false/null
    |           misconceptions_detected,
    |           mastery_signal,     # low/medium/high
    |           advance_to_step,    # step number or null
    |           mastery_updates,    # {concept: score}
    |           question_asked,     # question text or null
    |           expected_answer,    # expected answer or null
    |           turn_summary,       # one-line summary
    |           reasoning           # internal reasoning
    |       }
    |
    +-> 5. APPLY STATE UPDATES
    |       - Update mastery estimates
    |       - Track misconceptions
    |       - Track questions (set/clear)
    |       - Advance step if needed
    |       - Track off-topic count
    |
    +-> 6. Add teacher response to conversation history
    +-> 7. Update session summary (turn timeline, progress trend)
    +-> 8. Return TurnResult
```

### REST Response
```json
{
  "next_turn": {
    "message": "Great job! You're right that 5/8 is bigger...",
    "hints": [],
    "step_idx": 1,
    "mastery_score": 0.68,
    "is_complete": false
  },
  "routing": "Continue",
  "last_grading": {
    "score": 0.9,
    "rationale": "Student correctly compared numerators",
    "labels": [],
    "confidence": 0.8
  }
}
```

### WebSocket Response
```json
{"type": "typing", "payload": {}}
{"type": "assistant", "payload": {"message": "Great job! ..."}}
{"type": "state_update", "payload": {"state": {"current_step": 1, ...}}}
```

---

## Phase 4: Session Completion & Summary

### When Session Ends
- All study plan steps completed -> `session.is_complete` returns true
- Frontend detects `is_complete: true` in response

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
    "You're ready to move to more advanced topics."
  ]
}
```

---

## State Management

### SessionState (Pydantic Model)
```python
class SessionState(BaseModel):
    # Identification
    session_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int

    # Topic & Plan
    topic: Optional[Topic]          # Topic with study plan and guidelines

    # Progress
    current_step: int               # 1-indexed
    concepts_covered: List[str]
    mastery_estimates: Dict[str, float]  # {concept: 0.0-1.0}

    # Assessment
    last_question: Optional[Question]
    awaiting_response: bool

    # Memory
    conversation_history: List[Message]  # Max 10 messages
    session_summary: SessionSummary      # Turn timeline, concepts, examples, etc.

    # Behavioral
    off_topic_count: int
    warning_count: int
    safety_flags: List[str]

    # Student Context
    student_context: StudentContext      # grade, board, language_level
```

### Study Plan Model
```python
class StudyPlan(BaseModel):
    steps: List[StudyPlanStep]

class StudyPlanStep(BaseModel):
    step_id: int
    type: str           # "explain", "check", or "practice"
    concept: str
    content_hint: Optional[str]
    question_type: Optional[str]
    question_count: Optional[int]
```

### Step Advancement
The Master Tutor decides when to advance steps via `advance_to_step` in its output. Step advancement is applied in `_apply_state_updates()`.

---

## Master Tutor Prompt System

### System Prompt (set once per session)
Contains:
- Study plan (steps with types and concepts)
- Topic guidelines (learning objectives, prerequisites, misconceptions, teaching approach)
- 8 teaching rules:
  1. Follow the study plan
  2. Advance when student demonstrates understanding
  3. Track questions asked
  4. Evaluate answers
  5. Vary explanation structure
  6. Stay on topic
  7. Update mastery signals
  8. Sound human and natural

### Turn Prompt (per turn)
Contains:
- Current step info (type, concept, content hint)
- Current mastery estimates
- Known misconceptions
- Awaiting answer section (if question was asked)
- Recent conversation history
- Current student message

---

## Key Files Reference

### Backend - Agents (`llm-backend/tutor/agents/`)
| File | Purpose |
|------|---------|
| `base_agent.py` | BaseAgent ABC: execute(), build_prompt(), LLM call with strict schema |
| `master_tutor.py` | MasterTutorAgent: single agent for all teaching, TutorTurnOutput model |
| `safety.py` | SafetyAgent: fast content moderation gate |

### Backend - Orchestration (`llm-backend/tutor/orchestration/`)
| File | Purpose |
|------|---------|
| `orchestrator.py` | TeacherOrchestrator: safety -> master_tutor -> state updates |

### Backend - Models (`llm-backend/tutor/models/`)
| File | Purpose |
|------|---------|
| `session_state.py` | SessionState, Question, Misconception, SessionSummary, create_session() |
| `study_plan.py` | Topic, TopicGuidelines, StudyPlan, StudyPlanStep |
| `messages.py` | Message, StudentContext, WebSocket DTOs, factory functions |
| `agent_logs.py` | AgentLogEntry, AgentLogStore (in-memory, thread-safe) |

### Backend - Prompts (`llm-backend/tutor/prompts/`)
| File | Purpose |
|------|---------|
| `master_tutor_prompts.py` | System prompt (study plan + guidelines + rules) and turn prompt |
| `orchestrator_prompts.py` | Welcome message and session summary prompts |
| `templates.py` | PromptTemplate class, SAFETY_TEMPLATE |

### Backend - Utils (`llm-backend/tutor/utils/`)
| File | Purpose |
|------|---------|
| `schema_utils.py` | get_strict_schema(), make_schema_strict() for OpenAI structured output |
| `prompt_utils.py` | format_conversation_history(), build_context_section() |
| `state_utils.py` | update_mastery_estimate(), calculate_overall_mastery(), should_advance_step() |

### Backend - Services & API
| File | Purpose |
|------|---------|
| `tutor/services/session_service.py` | Session creation, step processing, summary generation |
| `tutor/services/topic_adapter.py` | DB guideline + study plan -> Topic model conversion |
| `tutor/api/sessions.py` | REST + WebSocket + agent logs endpoints |
| `tutor/api/curriculum.py` | Curriculum discovery endpoints |
| `shared/services/llm_service.py` | LLM wrapper (GPT-5.2, GPT-5.1, GPT-4o, Gemini, Anthropic) |
| `shared/services/anthropic_adapter.py` | Claude API adapter (thinking, tool_use structured output) |

### Backend - Evaluation (`llm-backend/evaluation/`)
| File | Purpose |
|------|---------|
| `config.py` | EvalConfig: server, session, simulation, LLM settings |
| `student_simulator.py` | LLM-powered student with persona (OpenAI or Anthropic) |
| `session_runner.py` | Session lifecycle: create via REST, converse via WebSocket |
| `evaluator.py` | 10-dimension LLM judge (coherence, naturalness, etc.) |
| `report_generator.py` | Generates conversation.md, evaluation.json, review.md, problems.md |
| `run_evaluation.py` | CLI: `python -m evaluation.run_evaluation` |
| `api.py` | FastAPI endpoints for starting/monitoring evaluation runs |
| `personas/average_student.json` | Default student persona |

---

## LLM Calls Summary

| Agent | Model | Reasoning | Purpose | Output Schema |
|-------|-------|-----------|---------|---------------|
| SAFETY | GPT-5.2 | none | Content moderation | SafetyOutput (strict) |
| MASTER TUTOR | GPT-5.2 | none | All teaching | TutorTurnOutput (strict) |
| WELCOME | GPT-5.2 | none | Welcome message | Plain text |

**LLM Service Features:**
- GPT-5.2 with strict `json_schema` structured output
- Anthropic Claude support via AnthropicAdapter (thinking + tool_use)
- Provider switching via `APP_LLM_PROVIDER` env var (openai/anthropic/anthropic-haiku)
- Reasoning effort levels: none, low, medium, high, xhigh
- GPT-5.2 fallback to GPT-5.1, then GPT-4o
- Gemini support (gemini-3-pro-preview)
- Automatic retry: 3 attempts with exponential backoff
- `make_schema_strict()` for Pydantic to OpenAI strict schema conversion

---

## API Endpoints Reference

### Health & Status
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health/db` | Database connectivity check |

### Session Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/sessions` | Create new session, returns first question |
| `POST` | `/sessions/{id}/step` | Submit student answer, get next turn |
| `GET` | `/sessions/{id}/summary` | Get session performance summary |
| `GET` | `/sessions/{id}` | Debug: Get full session state |
| `GET` | `/sessions/{id}/agent-logs` | Get agent execution logs |
| `WS` | `/sessions/ws/{id}` | WebSocket chat connection |

### Curriculum Discovery
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/curriculum?country=&board=&grade=` | Get available subjects |
| `GET` | `/curriculum?...&subject=` | Get topics for a subject |
| `GET` | `/curriculum?...&subject=&topic=` | Get subtopics with guideline IDs |

### Evaluation Pipeline
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/evaluation/start` | Start evaluation run in background |
| `GET` | `/api/evaluation/status` | Get current evaluation status |
| `GET` | `/api/evaluation/runs` | List all evaluation runs |
| `GET` | `/api/evaluation/runs/{id}` | Get specific run details |
| `POST` | `/api/evaluation/runs/{id}/retry-evaluation` | Re-evaluate existing conversation |

---

## Evaluation Pipeline

The evaluation pipeline simulates a tutoring session and evaluates quality across 10 dimensions.

### Flow
```
1. Load persona (simulated student profile)
2. Create session via REST API
3. Run conversation via WebSocket (student simulator <-> tutor)
4. Evaluate conversation with LLM judge (10 dimensions)
5. Generate reports (conversation.md, evaluation.json, review.md, problems.md)
```

### 10 Evaluation Dimensions
1. **Coherence** - Logical thread across turns
2. **Non-Repetition** - Avoids repeating explanations
3. **Natural Flow** - Feels like natural tutoring
4. **Engagement** - Keeps student interested
5. **Responsiveness** - Responds to student input
6. **Pacing** - Appropriate speed
7. **Grade Appropriateness** - Right level of complexity
8. **Topic Coverage** - Covers learning objectives
9. **Session Arc** - Natural beginning/middle/end
10. **Overall Naturalness** - Human-like feel

### CLI Usage
```bash
cd llm-backend
python -m evaluation.run_evaluation
```

### Environment Variables
```bash
EVAL_LLM_PROVIDER=openai      # or "anthropic"
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

---

## Persistence & Checkpointing

### Database Tables
| Table | Purpose |
|-------|---------|
| `sessions` | Session state: `id`, `student_json`, `goal_json`, `state_json`, `mastery`, `step_idx`, timestamps |
| `events` | Audit log: `session_id`, `node`, `step_idx`, `payload_json` |
| `teaching_guidelines` | Guideline data with review workflow |
| `study_plans` | Pre-built study plans (1:1 with teaching_guidelines) |
| `contents` | RAG corpus: `topic`, `grade`, `skill`, `text`, `tags` |

**Note:** LangGraph checkpoint tables are no longer used. Session state is stored as serialized `SessionState` in `sessions.state_json`.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Single master tutor agent** | Replaces 3-agent pipeline for more natural, coherent conversations |
| **Safety gate + master tutor** | Two-step: fast safety check, then full teaching in one call |
| **Pydantic SessionState** | Clean, typed state model with serialization (replaces LangGraph state) |
| **StudyPlan-driven teaching** | Pre-built study plans define the teaching sequence |
| **Topic adapter pattern** | Bridges DB models to tutor models cleanly |
| **WebSocket + REST** | REST for compatibility, WebSocket for real-time chat |
| **In-memory agent logs** | Thread-safe log store for debugging, accessible via API |
| **Evaluation pipeline** | Automated quality measurement with LLM judge |
| **Anthropic provider support** | Configurable LLM provider (OpenAI or Claude) |
| **Conversation window (10 msgs)** | Prevents context overflow while maintaining recent context |
| **Session summary tracking** | Turn timeline, concepts taught, progress trend |
| **Stdout structured logging** | JSON logs for cloud-native observability |

---

## Configuration

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `ANTHROPIC_API_KEY` | "" | Anthropic API key (optional) |
| `APP_LLM_PROVIDER` | "openai" | LLM provider: openai, anthropic, anthropic-haiku |
| `DATABASE_URL` | postgresql://... | PostgreSQL connection URL |
| `LOG_FORMAT` | "json" | Logging format: json or text |
| `LOG_LEVEL` | "INFO" | Logging level |
