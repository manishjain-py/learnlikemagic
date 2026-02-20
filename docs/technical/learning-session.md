# Learning Session — Technical

Architecture, agents, orchestration, and APIs for the tutoring pipeline.

---

## Architecture

```
Student Message
    │
    v
SAFETY AGENT (fast gate)
    │
    v
MASTER TUTOR (single LLM call handles everything)
    │
    v
SANITIZATION CHECK (detect leaked internal language)
    │
    v
STATE UPDATES (mastery, misconceptions, step advance)
    │
    v
Response to Student
```

Two-agent pipeline: a fast safety check followed by a single master tutor call that handles all teaching.

---

## Agent System

| Agent | Model | Structured Output | Responsibility |
|-------|-------|-------------------|----------------|
| **Safety** | GPT-5.2 / Claude | `SafetyOutput` (strict) | Content moderation gate |
| **Master Tutor** | GPT-5.2 / Claude | `TutorTurnOutput` (strict) | All teaching: explain, ask, evaluate, track mastery, advance |

Provider set via `APP_LLM_PROVIDER` env var: `openai`, `anthropic`, `anthropic-haiku`.

### TutorTurnOutput Schema

```python
TutorTurnOutput {
    response: str              # Student-facing text
    intent: str                # answer/question/confusion/off_topic/continuation/...
    answer_correct: bool|None  # true/false/null
    misconceptions_detected: list
    mastery_signal: str        # strong/adequate/needs_remediation
    advance_to_step: int|None  # Step number or null
    mastery_updates: list      # [{concept, score}]
    question_asked: str|None   # Question text
    expected_answer: str|None
    question_concept: str|None
    session_complete: bool     # True when final step mastered
    turn_summary: str          # One-line summary
    reasoning: str             # Internal reasoning (not shown to student)
}
```

---

## Orchestration Flow

`TeacherOrchestrator.process_turn(session, student_message)`:

1. **Post-completion check** — If session already complete (and no extension, or extension_turns > 10): generate LLM-powered context-aware response, return immediately
2. **Increment turn** — Add student message to history
3. **Build AgentContext** — Current state, mastery, study plan
4. **Safety Agent** — Fast content moderation gate. If unsafe: return guidance + log safety flag
5. **Master Tutor Agent** — Single LLM call with system prompt (study plan + guidelines + 10 teaching rules) and turn prompt (current state, mastery, pacing directive, student style, history)
6. **Sanitization Check** — Regex-based detection of leaked internal language (e.g., "The student's...", "Assessment:...")
7. **Apply State Updates**:
   - Update mastery estimates
   - Track misconceptions
   - Handle question lifecycle (probe → hint → explain phases)
   - Advance step if needed
   - Track off-topic count
   - Handle session completion (only honored on final step)
8. **Add response** to conversation history
9. **Update session summary** — Turn timeline, progress trend
10. **Return TurnResult**

---

## Prompt System

### System Prompt (set once per session)

Contains:
- Study plan (steps with types and concepts)
- Topic guidelines (learning objectives, prerequisites, misconceptions, teaching approach)
- 10 teaching rules (follow plan, advance when ready, track questions, guide discovery, never repeat, match energy, update mastery, be real, end naturally, never leak internals)

### Turn Prompt (per turn)

Contains:
- Current step info (type, concept, content hint)
- Current mastery estimates
- Known misconceptions
- Turn timeline (session narrative so far)
- Pacing directive (dynamic)
- Student style (dynamic)
- Awaiting answer section (if question pending)
- Recent conversation history
- Current student message

### Dynamic Signals

**Pacing Directive** (`_compute_pacing_directive`):

| Signal | Condition | Directive |
|--------|-----------|-----------|
| TURN 1 | First turn | Keep opening to 2-3 sentences, ask ONE simple question |
| ACCELERATE | avg_mastery >= 0.8 & improving | Skip steps aggressively, minimal scaffolding |
| EXTEND | Aced plan & is_complete | Push to harder territory |
| SIMPLIFY | avg_mastery < 0.4 or struggling | Shorter sentences, 1-2 ideas per response |
| CONSOLIDATE | avg_mastery 0.4-0.65 & 2+ wrong | Same-level problem to build confidence |
| STEADY | Default | One idea at a time |

**Student Style** (`_compute_student_style`):
- Analyzes avg words/message, emoji usage, question-asking
- Detects disengagement (responses getting shorter over 4+ messages)
- Adjusts response length (QUIET ≤5 words → 2-3 sentences; Moderate → 3-5; Expressive → can elaborate)

---

## Session API

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create session, get first turn |
| `POST` | `/sessions/{id}/step` | Submit student answer, get next turn |
| `GET` | `/sessions/{id}/summary` | Session performance summary |
| `GET` | `/sessions` | List all sessions for current user |
| `GET` | `/sessions/history` | Paginated session history (filterable) |
| `GET` | `/sessions/stats` | Aggregated learning stats |
| `GET` | `/sessions/scorecard` | Full student scorecard |
| `GET` | `/sessions/subtopic-progress` | Lightweight progress map |
| `GET` | `/sessions/{id}/replay` | Full conversation JSON |
| `GET` | `/sessions/{id}` | Full session state (debug) |
| `GET` | `/sessions/{id}/agent-logs` | Agent execution logs |

### WebSocket Endpoint

`WS /sessions/ws/{session_id}` — Used by evaluation pipeline (not frontend).

Auth via `?token=<jwt>` query param.

**Client sends:** `{"type": "chat", "payload": {"message": "..."}}`

**Server emits:**
```json
{"type": "typing", "payload": {}}
{"type": "assistant", "payload": {"message": "..."}}
{"type": "state_update", "payload": {"state": {...}}}
```

### Session Creation

```
POST /sessions
Body: {
  student: {id, grade, prefs: {style, lang}},
  goal: {topic, syllabus, learning_objectives, guideline_id}
}
```

Flow: Load guideline → Load study plan → Convert via topic_adapter → Create SessionState → Generate welcome → Persist → Return `{session_id, first_turn}`

---

## State Management

### SessionState

```python
class SessionState(BaseModel):
    session_id: str
    turn_count: int
    topic: Optional[Topic]
    current_step: int                   # 1-indexed
    mastery_estimates: Dict[str, float] # {concept: 0.0-1.0}
    misconceptions: List[Misconception]
    last_question: Optional[Question]   # Tracks question lifecycle
    conversation_history: List[Message] # Sliding window (max 10)
    full_conversation_log: List[Message]
    session_summary: SessionSummary
    student_context: StudentContext     # grade, board, language_level
    pace_preference: str                # slow/normal/fast
    allow_extension: bool               # Continue past study plan
    # + off_topic_count, warning_count, safety_flags, etc.
```

### Question Lifecycle

```python
class Question(BaseModel):
    question_text: str
    expected_answer: str
    concept: str
    wrong_attempts: int = 0
    previous_student_answers: List[str] = []
    phase: str = "asked"  # asked → probe → hint → explain
```

Phase progression:
- 1st wrong → `probe` (probing question)
- 2nd wrong → `hint` (targeted hint)
- 3rd+ wrong → `explain` (explain directly)
- Correct → clear question

### Step Advancement

Master tutor sets `advance_to_step` in output. Applied in `_apply_state_updates()`.

Session completion: `current_step > total_steps` → `is_complete = true`.

Extension: Advanced students can continue up to 10 turns beyond `total_steps * 2`.

---

## Study Plan Integration

Study plans are loaded from the database and converted to the tutor's internal model:

```
DB StudyPlan.plan_json → topic_adapter.convert_guideline_to_topic() → Topic model
```

Study plan steps have types: `explain`, `check`, `practice`.

---

## LLM Calls

| Call | Model | Purpose | Output |
|------|-------|---------|--------|
| Safety | GPT-5.2 / Claude | Content moderation | SafetyOutput (strict) |
| Master Tutor | GPT-5.2 / Claude | All teaching | TutorTurnOutput (strict) |
| Welcome | GPT-5.2 / Claude | Welcome message | Plain text |
| Post-Completion | GPT-5.2 / Claude | Context-aware reply after session ends | Plain text |

---

## Key Files

### Agents (`tutor/agents/`)

| File | Purpose |
|------|---------|
| `base_agent.py` | BaseAgent ABC: execute(), build_prompt(), LLM call with strict schema |
| `master_tutor.py` | MasterTutorAgent: single agent for all teaching, TutorTurnOutput model |
| `safety.py` | SafetyAgent: fast content moderation gate |

### Orchestration (`tutor/orchestration/`)

| File | Purpose |
|------|---------|
| `orchestrator.py` | TeacherOrchestrator: safety → master_tutor → state updates |

### Models (`tutor/models/`)

| File | Purpose |
|------|---------|
| `session_state.py` | SessionState, Question, Misconception, SessionSummary, create_session() |
| `study_plan.py` | Topic, TopicGuidelines, StudyPlan, StudyPlanStep |
| `messages.py` | Message, StudentContext, WebSocket DTOs |
| `agent_logs.py` | AgentLogEntry, AgentLogStore (in-memory, thread-safe) |

### Prompts (`tutor/prompts/`)

| File | Purpose |
|------|---------|
| `master_tutor_prompts.py` | System prompt (study plan + guidelines + rules) and turn prompt |
| `orchestrator_prompts.py` | Welcome message and session summary prompts |
| `templates.py` | PromptTemplate class, SAFETY_TEMPLATE |

### Utils (`tutor/utils/`)

| File | Purpose |
|------|---------|
| `schema_utils.py` | get_strict_schema(), validate_agent_output(), parse_json_safely() |
| `prompt_utils.py` | format_conversation_history() |
| `state_utils.py` | update_mastery_estimate(), calculate_overall_mastery(), should_advance_step() |

### Services & API

| File | Purpose |
|------|---------|
| `tutor/services/session_service.py` | Session creation, step processing, summary |
| `tutor/services/topic_adapter.py` | DB guideline + study plan → Topic model |
| `tutor/api/sessions.py` | REST + WebSocket + agent logs endpoints |
| `tutor/api/curriculum.py` | Curriculum discovery endpoints |
| `shared/services/llm_service.py` | LLM wrapper (OpenAI, Gemini, Anthropic) |
| `shared/services/anthropic_adapter.py` | Claude API adapter |
