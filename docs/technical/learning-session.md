# Learning Session — Technical

Architecture, agents, orchestration, and APIs for the tutoring pipeline.

---

## Architecture

```
Student Message
    │
    v
INPUT TRANSLATION (Hinglish/Hindi → English)
    │
    v
SAFETY AGENT (fast gate)
    │
    v
MODE ROUTER ──────────────────────────────────────┐
    │                                              │
    │ teach_me              clarify_doubts / exam  │
    v                                              v
MASTER TUTOR                              MASTER TUTOR
(mode-specific prompts)               (mode-specific prompts)
    │                                              │
    v                                              v
SANITIZATION CHECK (log-only)        MODE-SPECIFIC STATE
    │                                (concepts/scoring)
    v                                              │
STATE UPDATES                                      v
(mastery, misconceptions,                   Response
 explanation phase, step                  (+ audio_text)
 advance, coverage)
    │
    v
Response to Student
(+ audio_text for TTS)
```

Three-step pipeline: input translation (Hinglish/Hindi to English), a fast safety check, then a single master tutor call that handles all teaching. Each mode uses its own prompt templates. The orchestrator routes to mode-specific processing after the safety check. Sanitization check (leaked internal language detection) applies only to teach_me mode. All responses include an `audio_text` field for text-to-speech.

---

## Session Modes

The system supports three session modes, set at creation time and stored on `SessionState.mode`:

| Mode | Purpose | Study Plan | Mastery Tracking | Step Advancement | Completion |
|------|---------|------------|------------------|------------------|------------|
| `teach_me` | Structured lesson | Yes | Yes (per-concept) | Yes | `current_step > total_steps` |
| `clarify_doubts` | Student-led Q&A | Concepts tracked but no steps | Concepts discussed tracked | No | `clarify_complete` flag (via end-clarify endpoint or tutor intent) |
| `exam` | Knowledge assessment | Questions generated from plan | Score tracking | Question index advances | All questions answered or early end |

Mode-specific processing happens in the orchestrator after the shared safety check:
- `teach_me` → `process_turn()` main path
- `clarify_doubts` → `_process_clarify_turn()`
- `exam` → `_process_exam_turn()`

---

## Agent System

| Agent | Model | Structured Output | Responsibility |
|-------|-------|-------------------|----------------|
| **Safety** | Configurable (DB) | `SafetyOutput` (strict) | Content moderation gate |
| **Master Tutor** | Configurable (DB) | `TutorTurnOutput` (strict) | All teaching: explain, ask, evaluate, track mastery, advance |

Provider and model are configured via the `llm_config` DB table, read at session creation time through `LLMConfigService.get_config("tutor")`. Supported providers: `openai` (GPT-5.2, GPT-5.1), `anthropic` / `anthropic-haiku` (Claude), `google` (Gemini).

### TutorTurnOutput Schema

```python
TutorTurnOutput {
    response: str              # Student-facing text
    audio_text: str            # Hinglish/Hindi spoken version for TTS (Roman script)
    intent: str                # teach_me: answer/answer_change/question/confusion/novel_strategy/off_topic/continuation
                               # clarify_doubts: question/followup/done/off_topic
                               # exam: exam_answer/exam_complete
    answer_correct: bool|None  # true/false/null
    misconceptions_detected: list[str]
    mastery_signal: str|None   # strong/adequate/needs_remediation
    answer_score: float|None   # Fractional score 0.0-1.0 (exam mode partial credit)
    marks_rationale: str|None  # Brief justification for score (1-2 sentences)
    advance_to_step: int|None  # Step number or null
    mastery_updates: list[MasteryUpdate]  # [{concept, score}]
    question_asked: str|None   # Question text
    expected_answer: str|None
    question_concept: str|None
    # Explanation phase tracking (explain steps only)
    explanation_phase_update: str|None       # opening/explaining/informal_check/complete/skip
    explanation_building_blocks_covered: list[str]  # Building blocks covered this turn
    student_shows_understanding: bool|None   # Informal check result
    student_shows_prior_knowledge: bool|None # Skip explanation if student knows it
    session_complete: bool     # True when final step mastered
    turn_summary: str          # One-line summary (max 80 chars)
    reasoning: str             # Internal reasoning (not shown to student)
}
```

---

## Orchestration Flow

`TeacherOrchestrator.process_turn(session, student_message)`:

1. **Input Translation** — Translate Hinglish/Hindi input to English via a fast LLM call. Returns unchanged if already English.
2. **Post-completion check** — If session already complete: for `clarify_doubts` mode, always short-circuit with a context-aware response. For `teach_me`, short-circuit if no extension allowed or extension_turns > 10. The context-aware response is LLM-generated and responds naturally to whatever the student said.
3. **Increment turn** — Add student message to history
4. **Build AgentContext** — Current state, mastery, study plan
5. **Safety Agent** — Fast content moderation gate. If unsafe: return guidance + log safety flag
6. **Mode Router** — Branch based on `session.mode`:
   - `clarify_doubts` → `_process_clarify_turn()`: runs master tutor with clarify-specific prompts (`CLARIFY_DOUBTS_SYSTEM_PROMPT` + `CLARIFY_DOUBTS_TURN_PROMPT`), tracks concepts discussed via `mastery_updates` (added to both `concepts_discussed` and `concepts_covered_set`), no step advancement. Marks `clarify_complete = True` when tutor output has `intent == "done"` or `session_complete == True` (student indicated they are done).
   - `exam` → `_process_exam_turn()`: evaluates answer against current exam question using fractional scoring (0.0-1.0). Score >= 0.8 → correct, >= 0.2 → partial, < 0.2 → incorrect. Records `marks_rationale` per question. Mid-exam responses show only the next question — correctness is not revealed. When the last question is answered, builds a full results response with per-question scores, rationales, and final score.
   - `teach_me` → continues to step 7
7. **Master Tutor Agent** — Single LLM call with system prompt (study plan + guidelines + 12 teaching rules + personalization block) and turn prompt (current state, mastery, explanation context, pacing directive, student style, feedback notices, history)
8. **Sanitization Check** — Regex-based detection of leaked internal language (e.g., "The student's...", "Assessment:..."). Logs a warning only — does not modify the response.
9. **Apply State Updates**:
   - Handle explanation phase lifecycle (opening → explaining → informal_check → complete)
   - Update mastery estimates
   - Track misconceptions
   - Handle question lifecycle (probe → hint → explain phases)
   - Advance step if needed + update coverage set (with explanation guard — cannot advance past incomplete explain steps)
   - Track off-topic count
   - Handle session completion (only honored on final step)
10. **Add response** (with `audio_text`) to conversation history
11. **Update session summary** — Turn timeline (capped at 30 entries), progress trend, concepts taught
12. **Return TurnResult** (includes `audio_text`)

---

## Prompt System

### System Prompt (teach_me — set once per session)

Contains:
- Student profile (grade, language level, preferred examples)
- Personalization block: uses `tutor_brief` (rich personality prose from enrichment profile) when available, falling back to basic name/age/about_me from user profile
- Study plan (steps with types, concepts, content hints)
- Topic guidelines (curriculum scope, common misconceptions)
- 12 teaching rules: explain first (structured explanation phases), advance when ready (with explanation guard), track questions, guide discovery with escalating strategy changes, never repeat, match energy, update mastery, be real with calibrated praise, end naturally, never leak internals, response/audio language instructions, explanation phase tracking
- Response and audio language instructions (from `language_utils.py`)

### Turn Prompt (teach_me — per turn)

Contains:
- Current step info (type, concept, content hint)
- Explanation context (when on an explain step: approach, building blocks covered/remaining, current phase, turns spent)
- Current mastery estimates
- Known misconceptions (with recurring misconception alerts)
- Turn timeline (session narrative so far, last 5 entries)
- Pacing directive (dynamic — includes explanation-aware pacing and attention span warnings)
- Student style (dynamic)
- Awaiting answer section (if question pending, includes attempt number and escalating strategy)
- Exam question context (when in exam mode: question text, expected answer, fractional scoring instructions)
- Feedback notices (when study plan was recently updated via mid-session feedback)
- Recent conversation history (max 10 messages)
- Current student message

### Mode-Specific Prompts

**Clarify Doubts** (`clarify_doubts_prompts.py`):
- Uses dedicated prompt templates: `CLARIFY_DOUBTS_SYSTEM_PROMPT` (system) and `CLARIFY_DOUBTS_TURN_PROMPT` (per turn). The `MasterTutorAgent._build_system_prompt()` detects `mode == "clarify_doubts"` and renders the clarify-specific system prompt; `_build_turn_prompt()` delegates to `_build_clarify_turn_prompt()`.
- System prompt: direct answers (no Socratic method), session closure rules (respect "I'm done"), concept tracking against study plan concepts, curriculum scope boundary
- Turn prompt: concepts discussed so far, conversation history, student message, structured output instructions (intent, mastery_updates for concept tracking, session_complete for closure)
- `mastery_updates` used to track which study plan concepts were substantively discussed
- `answer_correct` always null in clarify mode; `advance_to_step` never set

**Exam** (`exam_prompts.py`):
- Question generation prompt: difficulty distribution (~30% easy, ~50% medium, ~20% hard), question types (conceptual, procedural, application, real_world, error_spotting, reasoning) — used by `ExamService.generate_questions()`. Includes personalization section using `personality_json` (interests, people to reference).
- Evaluation: uses master tutor prompts with exam-specific context injected into the awaiting answer section (question text, expected answer, fractional scoring instructions with `answer_score` and `marks_rationale`). The evaluation system/turn prompt templates in `exam_prompts.py` exist but are not yet wired into the pipeline.
- Evaluation feedback is stored on `ExamQuestion.feedback` and `ExamQuestion.marks_rationale` but NOT shown to the student mid-exam. The orchestrator shows the next question between answers. Final results include per-question scores and rationales.

### Dynamic Signals

**Pacing Directive** (`_compute_pacing_directive`):

| Signal | Condition | Directive |
|--------|-----------|-----------|
| TURN 1 | First turn | Curiosity-building hook, inviting question, set explanation_phase_update='opening' |
| EXPLAIN (opening) | Explain step, phase=opening | Begin core explanation, one idea, everyday example, set phase='explaining' |
| EXPLAIN (building) | Explain step, phase=explaining, blocks remaining | Cover next building block with varied representation, one per turn |
| EXPLAIN (summarize) | Explain step, phase=explaining, all blocks covered | Summarize key idea, ask informal understanding check, set phase='informal_check' |
| EXPLAIN (check) | Explain step, phase=informal_check | Evaluate student's response, set student_shows_understanding accordingly |
| EXPLAIN (done) | Explain step, phase=informal_check, check passed | Acknowledge and transition, set phase='complete' |
| ACCELERATE | avg_mastery >= 0.8 & improving (or 60%+ concepts >= 0.7 & improving) | Skip steps aggressively, minimal scaffolding |
| EXTEND | Aced plan & is_complete | Push to harder territory |
| SIMPLIFY | (avg_mastery < 0.4 with real data) or trend == struggling | Shorter sentences, 1-2 ideas per response |
| CONSOLIDATE | avg_mastery 0.4-0.65 & steady & current question has 2+ wrong attempts | Same-level problem to build confidence |
| STEADY | Default | One idea at a time |

Note: ACCELERATE has early fast-track detection — if 60%+ of concepts have mastery >= 0.7 AND avg_mastery >= 0.65 AND trend is improving, the system forces the accelerate path.

Note: STEADY appends an attention span warning when the student's attention span (from enrichment profile) is reached. Thresholds: short=8 turns, medium=14 turns, long=20 turns. The tutor is prompted to start wrapping up.

**Student Style** (`_compute_student_style`):
- Analyzes avg words/message, emoji usage, question-asking
- Detects disengagement (responses getting shorter over 4+ messages: last response < 40% of first and <= 5 words)
- Adjusts response length (QUIET <=5 words → 2-3 sentences; Moderate → 3-5; Expressive → can elaborate)

---

## Session API

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create session (with mode), get first turn |
| `POST` | `/sessions/{id}/step` | Submit student answer, get next turn |
| `POST` | `/sessions/{id}/pause` | Pause a Teach Me session |
| `POST` | `/sessions/{id}/resume` | Resume a paused session (returns conversation history) |
| `POST` | `/sessions/{id}/end-clarify` | End a Clarify Doubts session (marks complete server-side) |
| `POST` | `/sessions/{id}/end-exam` | End an exam early and get results |
| `POST` | `/sessions/{id}/feedback` | Submit mid-session feedback to regenerate study plan (max 3/session) |
| `GET` | `/sessions/{id}/summary` | Session performance summary |
| `GET` | `/sessions` | List all sessions for current user |
| `GET` | `/sessions/history` | Paginated session history (filterable by subject) |
| `GET` | `/sessions/stats` | Aggregated learning stats |
| `GET` | `/sessions/report-card` | Student report card with coverage and exam data |
| `GET` | `/sessions/topic-progress` | Lightweight topic progress map |
| `GET` | `/sessions/resumable?guideline_id=X` | Find a paused Teach Me session for a subtopic |
| `GET` | `/sessions/guideline/{id}` | List sessions for a guideline (filterable by mode, completion) |
| `GET` | `/sessions/{id}/exam-review` | Detailed exam review (per-question scores, rationales, answers) |
| `GET` | `/sessions/{id}/replay` | Full conversation JSON |
| `GET` | `/sessions/{id}` | Full session state (debug) |
| `GET` | `/sessions/{id}/agent-logs` | Agent execution logs |
| `POST` | `/transcribe` | Audio transcription via OpenAI Whisper |
| `POST` | `/text-to-speech` | Text-to-speech via Google Cloud TTS (Hindi/English/Hinglish voice) |

### WebSocket Endpoint

`WS /sessions/ws/{session_id}` — Used by both the frontend and the evaluation pipeline for real-time chat.

Auth via `?token=<jwt>` query param. For user-linked sessions, token must belong to session owner (validated via Cognito). Anonymous sessions allowed without token for backward compatibility.

**Connection flow:** Auth check → accept connection → send initial `state_update` → if first turn (turn_count == 0), generate welcome via `generate_welcome_message()` (teach_me fallback — sessions created via REST already have the mode-specific welcome in history) → enter main message loop.

**Client sends:** `{"type": "chat", "payload": {"message": "..."}}`

**Server emits:**
```json
{"type": "typing", "payload": {}}
{"type": "assistant", "payload": {"message": "..."}}
{"type": "state_update", "payload": {"state": {...}}}
{"type": "error", "payload": {"error": "..."}}
```

The `state_update` payload includes (via `SessionStateDTO`):
- `session_id`, `current_step`, `total_steps`, `current_concept`, `progress_percentage`
- `mastery_estimates`: `{concept: score}` dict
- `is_complete`: whether session has ended
- `mode`: current session mode
- `coverage`: concept coverage percentage (teach_me)
- `concepts_discussed`: list of concepts discussed (clarify_doubts)
- `exam_progress`: `{current_question, total_questions, correct_so_far}` (exam, only when questions exist)
- `is_paused`: whether session is paused

**Additional client message types:**
- `{"type": "get_state"}` — requests the current state (server responds with a `state_update`)

### Session Creation

```
POST /sessions
Body: {
  student: {id, grade, prefs: {style, lang}},
  goal: {topic, syllabus, learning_objectives, guideline_id},
  mode: "teach_me" | "clarify_doubts" | "exam"
}
```

Flow:
- Load guideline → Load study plan → Convert via topic_adapter → Create SessionState (with mode)
- Build StudentContext from user profile when authenticated (name, age, about_me for personalization)
- For `exam` mode: generate exam questions via ExamService before welcome
- Generate mode-specific welcome message (each mode has its own welcome generator)
- For `exam`: append first question to welcome message
- Persist session to DB (with state_version=1)
- For `clarify_doubts`: attach past discussions for same user + guideline (up to 5 most recent, only sessions with at least one concept discussed)
- Return `{session_id, first_turn, mode}`

Session ownership: user-linked sessions require the caller to be the session owner. Anonymous sessions (user_id=None) allow access for backward compatibility.

---

## State Management

### SessionState

```python
class SessionState(BaseModel):
    session_id: str
    turn_count: int
    topic: Optional[Topic]
    mode: SessionMode                    # "teach_me" | "clarify_doubts" | "exam"
    current_step: int                    # 1-indexed
    mastery_estimates: Dict[str, float]  # {concept: 0.0-1.0}
    misconceptions: List[Misconception]
    last_question: Optional[Question]    # Tracks question lifecycle
    conversation_history: List[Message]  # Sliding window (max 10)
    full_conversation_log: List[Message]
    session_summary: SessionSummary
    student_context: StudentContext      # grade, board, language_level, name, age, about_me
    pace_preference: str                 # slow/normal/fast
    allow_extension: bool                # Continue past study plan
    is_paused: bool                      # Whether Teach Me session is paused
    concepts_covered_set: set[str]       # Concepts covered in this session
    # Clarify Doubts state
    concepts_discussed: list[str]        # Concepts discussed in Q&A
    clarify_complete: bool               # Whether student ended the Clarify session
    # Exam state
    exam_questions: list[ExamQuestion]
    exam_current_question_idx: int
    exam_total_correct: int
    exam_total_partial: int
    exam_total_incorrect: int
    exam_finished: bool
    exam_feedback: Optional[ExamFeedback]
    # + off_topic_count, warning_count, safety_flags, etc.
```

### StudentContext

```python
class StudentContext(BaseModel):
    grade: int
    board: str                # Educational board (e.g., "CBSE")
    language_level: str       # "simple" | "standard" | "advanced"
    preferred_examples: list  # e.g., ["food", "sports", "games"]
    student_name: Optional[str]   # From user profile
    student_age: Optional[int]    # From user profile
    about_me: Optional[str]       # From user profile
```

When the user is authenticated, `StudentContext` is populated from the user profile (name, age, about_me), which enables personalized tutoring (addressing the student by name, age-appropriate language).

### Question Lifecycle

```python
class Question(BaseModel):
    question_text: str
    expected_answer: str
    concept: str
    rubric: str = ""               # Evaluation criteria
    hints: list[str] = []          # Available hints
    hints_used: int = 0            # Number of hints provided
    wrong_attempts: int = 0
    previous_student_answers: list[str] = []
    phase: str = "asked"           # asked → probe → hint → explain
```

Phase progression:
- 1st wrong → `probe` (probing question)
- 2nd wrong → `hint` (targeted hint)
- 3rd wrong → `explain` (explain directly, try completely different approach)
- 4th+ wrong → strategy change (step back to prerequisite or break into smaller pieces)
- Correct → clear question

The orchestrator handles five question lifecycle cases:
1. Wrong answer on pending question → increment attempts, update phase, do NOT clear
2. Correct answer → clear question, optionally track new one
3. New question, no pending → track it
4. New question, different concept pending → replace
5. Same concept follow-up while pending → keep original lifecycle

### Step Advancement

Master tutor sets `advance_to_step` in output. Applied in `_apply_state_updates()`. When advancing, all intermediate step concepts are added to `concepts_covered_set`.

Session completion logic:
- `is_complete` property: `clarify_doubts` → returns `clarify_complete`; `teach_me` → `current_step > total_steps`; `exam` → also `current_step > total_steps` (but see note below)
- For exam mode, REST responses use `exam_finished` instead of `is_complete` to determine completion, since exams track progress via `exam_current_question_idx` rather than `current_step`
- The orchestrator's `_process_exam_turn()` checks `exam_finished` and `exam_current_question_idx` directly

Extension: Advanced students in teach_me mode can continue up to 10 turns beyond `total_steps * 2`.

### Exam State

```python
class ExamQuestion(BaseModel):
    question_idx: int
    question_text: str
    concept: str
    difficulty: "easy" | "medium" | "hard"
    question_type: "conceptual" | "procedural" | "application"
    expected_answer: str
    student_answer: Optional[str]
    result: Optional["correct" | "partial" | "incorrect"]
    feedback: str

class ExamFeedback(BaseModel):
    score: int
    total: int
    percentage: float
    strengths: list[str]
    weak_areas: list[str]
    patterns: list[str]
    next_steps: list[str]
```

Exam questions are generated at session creation time via `ExamService.generate_questions()`, which uses an LLM call with structured output. Default: 7 questions. On failure, retries with 3 questions.

### Persistence and Concurrency

Session state is persisted to the database as serialized JSON (`state_json`). All writes use **compare-and-swap (CAS)** via a `state_version` column:

- REST path (`_persist_session_state`): atomic `UPDATE ... WHERE state_version = expected_version`, raises `StaleStateError` on conflict
- WebSocket path (`_save_session_to_db`): same CAS check, returns `(new_version, None)` on success or `(db_version, reloaded_session)` on conflict. On conflict, the caller adopts the reloaded state (so subsequent saves use the correct version) and sends an error message to the client: "Session was updated from another tab. Your last message was not saved. Please resend."

This prevents concurrent REST calls (e.g., pause from one tab while chatting in another) from silently overwriting each other's state. The WebSocket path also persists `exam_score`/`exam_total` and `is_paused` fields to the session record alongside the full state JSON.

---

## Study Plan Integration

Study plans are loaded from the database and converted to the tutor's internal model:

```
DB StudyPlan.plan_json → topic_adapter.convert_guideline_to_topic() → Topic model
```

Study plan steps have types: `explain`, `check`, `practice`. Step type is inferred from the plan item's title/description keywords or defaults to a pattern (explain, check, explain, check, ..., practice at end).

If no study plan exists in the DB, a default 4-step plan is generated: explain → check → explain → practice.

---

## LLM Calls

| Call | Model | Purpose | Output | Prompt Source |
|------|-------|---------|--------|---------------|
| Safety | Configurable (DB) | Content moderation | SafetyOutput (strict) | `templates.py` SAFETY_TEMPLATE |
| Master Tutor | Configurable (DB) | All teaching (teach_me, clarify_doubts, exam evaluation) | TutorTurnOutput (strict) | `master_tutor_prompts.py` (shared across all modes) |
| Welcome (Teach Me) | Configurable (DB) | Welcome message for structured lesson | Plain text | `orchestrator_prompts.py` |
| Welcome (Clarify) | Configurable (DB) | Welcome message for Q&A mode | Plain text | Inline in `orchestrator.py` |
| Welcome (Exam) | Configurable (DB) | Welcome message for exam mode | Plain text | Inline in `orchestrator.py` |
| Post-Completion | Configurable (DB) | Context-aware reply after session ends | Plain text | Inline in `orchestrator.py` |
| Exam Questions | Configurable (DB) | Generate exam questions at session start | Structured JSON (array of questions) | `exam_prompts.py` EXAM_QUESTION_GENERATION_PROMPT |

LLM provider/model is resolved at session creation from the `llm_config` DB table via `LLMConfigService.get_config("tutor")`. The Anthropic adapter maps structured output to tool_use, and reasoning effort to thinking budgets.

---

## Transcription

Audio transcription is handled by a separate endpoint (`POST /transcribe`) using OpenAI Whisper:
- Accepts audio files up to 25 MB
- Supported formats: webm, ogg, mp4, mpeg, wav, flac
- Returns `{text: str}` — the transcribed text
- Used by the frontend's voice input feature

---

## Key Files

### Agents (`tutor/agents/`)

| File | Purpose |
|------|---------|
| `base_agent.py` | BaseAgent ABC: execute(), build_prompt(), LLM call with strict schema |
| `master_tutor.py` | MasterTutorAgent: single agent for all teaching, TutorTurnOutput model, pacing/style computation, personalization block |
| `safety.py` | SafetyAgent: fast content moderation gate |

### Orchestration (`tutor/orchestration/`)

| File | Purpose |
|------|---------|
| `orchestrator.py` | TeacherOrchestrator: safety → mode router → master_tutor → state updates. Mode-specific methods: `_process_clarify_turn()` (with clarify_complete handling), `_process_exam_turn()` (with partial scoring). Exam feedback builder. Separate welcome generators per mode (`generate_welcome_message`, `generate_clarify_welcome`, `generate_exam_welcome`). Post-completion response generator. |

### Models (`tutor/models/`)

| File | Purpose |
|------|---------|
| `session_state.py` | SessionState, Question, Misconception, SessionSummary, ExamQuestion, ExamFeedback, create_session() |
| `study_plan.py` | Topic, TopicGuidelines, StudyPlan, StudyPlanStep |
| `messages.py` | Message, StudentContext, WebSocket DTOs (ClientMessage, ServerMessage, SessionStateDTO), factory functions |
| `agent_logs.py` | AgentLogEntry, AgentLogStore (in-memory, thread-safe) |

### Prompts (`tutor/prompts/`)

| File | Purpose |
|------|---------|
| `master_tutor_prompts.py` | System prompt (study plan + guidelines + rules + personalization) and turn prompt. Used for ALL modes. |
| `clarify_doubts_prompts.py` | System and turn prompts for Clarify Doubts mode. **Defined but not yet wired** — clarify mode currently uses master tutor prompts. |
| `exam_prompts.py` | Exam question generation prompt (actively used by ExamService) and evaluation prompts (**evaluation prompts defined but not yet wired** — exam eval uses master tutor prompts). |
| `orchestrator_prompts.py` | Welcome message (Teach Me) and session summary prompts |
| `templates.py` | PromptTemplate class, SAFETY_TEMPLATE, format helpers |

### Utils (`tutor/utils/`)

| File | Purpose |
|------|---------|
| `schema_utils.py` | get_strict_schema(), validate_agent_output(), parse_json_safely(), extract_json_from_text() |
| `prompt_utils.py` | format_conversation_history(max_turns default=5, overridden to 10 by master tutor) |
| `state_utils.py` | update_mastery_estimate(), calculate_overall_mastery(), should_advance_step(), get_mastery_level(), merge_misconceptions() |

### Services & API

| File | Purpose |
|------|---------|
| `tutor/services/session_service.py` | Session creation (all modes), step processing, pause/resume, end clarify, end exam, summary, CAS persistence |
| `tutor/services/exam_service.py` | Exam question generation via LLM with retry. ExamGenerationError (LearnLikeMagicException subclass) |
| `tutor/services/topic_adapter.py` | DB guideline + study plan → Topic model |
| `tutor/services/scorecard_service.py` | Scorecard aggregation, subtopic progress |
| `tutor/api/sessions.py` | REST + WebSocket + agent logs endpoints, session ownership checks, end-clarify endpoint |
| `tutor/api/transcription.py` | Audio transcription endpoint (OpenAI Whisper) |
| `tutor/api/curriculum.py` | Curriculum discovery endpoints |
| `tutor/exceptions.py` | Custom exception hierarchy (TutorAgentError, LLMError, AgentError, SessionError, StateError, PromptError, ConfigurationError) |
| `shared/services/llm_service.py` | LLM wrapper (OpenAI Responses API, Chat Completions, Gemini, Anthropic) |
| `shared/services/anthropic_adapter.py` | Claude API adapter (tool_use for structured output, thinking budgets) |
| `shared/services/llm_config_service.py` | DB-backed LLM config: component_key → provider + model_id |
