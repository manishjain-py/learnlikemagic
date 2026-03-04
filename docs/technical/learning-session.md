# Learning Session — Technical

Architecture, agents, orchestration, and APIs for the tutoring pipeline.

---

## Architecture

```
Student Message
    │
    v
TRANSLATE (Hinglish/Hindi → English)
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

Three-step pipeline: auto-translate student input (Hinglish/Hindi to English), fast safety check, then a single master tutor call that handles all teaching and returns both `response` and `audio_text` (spoken version for TTS). The orchestrator routes to mode-specific processing after the safety check. Sanitization check (leaked internal language detection) applies only to teach_me mode.

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
    audio_text: str            # Spoken version for TTS (Hinglish/Hindi/English based on preference)
    intent: str                # teach_me: answer/answer_change/question/confusion/novel_strategy/off_topic/continuation
                               # clarify_doubts: question/followup/done/off_topic
                               # exam: exam_answer/exam_complete
    answer_correct: bool|None  # true/false/null
    misconceptions_detected: list[str]
    mastery_signal: str|None   # strong/adequate/needs_remediation
    answer_score: float|None   # Fractional score 0.0-1.0 (exam mode, partial credit)
    marks_rationale: str|None  # Brief justification for score (1-2 sentences)
    advance_to_step: int|None  # Step number or null
    mastery_updates: list[MasteryUpdate]  # [{concept, score}]
    question_asked: str|None   # Question text
    expected_answer: str|None
    question_concept: str|None
    # Explanation phase tracking (explain steps only)
    explanation_phase_update: str|None      # opening/explaining/informal_check/complete/skip
    explanation_building_blocks_covered: list[str]  # Building blocks covered this turn
    student_shows_understanding: bool|None  # Informal check result
    student_shows_prior_knowledge: bool|None  # Skip explanation if student already knows
    session_complete: bool     # True when final step mastered
    turn_summary: str          # One-line summary (max 80 chars)
    reasoning: str             # Internal reasoning (not shown to student)
}
```

---

## Orchestration Flow

`TeacherOrchestrator.process_turn(session, student_message)`:

1. **Translate input** — Auto-translate Hinglish/Hindi student input to English via fast LLM call (returns original if already English)
2. **Post-completion check** — If session already complete: for `clarify_doubts` mode, always short-circuit with a context-aware response. For `teach_me`, short-circuit if no extension allowed or extension_turns > 10. The context-aware response is LLM-generated and responds naturally to whatever the student said.
3. **Increment turn** — Add student message to history
4. **Build AgentContext** — Current state, mastery, study plan
5. **Safety Agent** — Fast content moderation gate. If unsafe: return guidance + log safety flag
6. **Mode Router** — Branch based on `session.mode`:
   - `clarify_doubts` → `_process_clarify_turn()`: runs master tutor with clarify-specific prompts (`CLARIFY_DOUBTS_SYSTEM_PROMPT` + `CLARIFY_DOUBTS_TURN_PROMPT`), tracks concepts discussed via `mastery_updates` (added to both `concepts_discussed` and `concepts_covered_set`), no step advancement. Marks `clarify_complete = True` when tutor output has `intent == "done"` or `session_complete == True` (student indicated they are done).
   - `exam` → `_process_exam_turn()`: evaluates answer against current exam question using fractional scoring (`answer_score` 0.0-1.0 with `marks_rationale`). Categorical result derived from score: >= 0.8 correct, >= 0.2 partial, < 0.2 incorrect. Mid-exam responses show the next question without revealing correctness. When the last question is answered, builds a full results response with per-question review (score + rationale) and final score.
   - `teach_me` → continues to step 7
7. **Master Tutor Agent** — Single LLM call with system prompt (study plan + guidelines + 12 teaching rules + personalization block + language instructions) and turn prompt (current state, mastery, explanation context, pacing directive, student style, history)
8. **Sanitization Check** — Regex-based detection of leaked internal language (e.g., "The student's...", "Assessment:..."). Logs a warning only — does not modify the response.
9. **Apply State Updates**:
   - Handle explanation phase lifecycle (opening → explaining → informal_check → complete)
   - Update mastery estimates
   - Track misconceptions
   - Handle question lifecycle (probe → hint → explain phases)
   - Advance step if needed + update coverage set (with explanation guard: cannot advance past incomplete explanations)
   - Track off-topic count
   - Handle session completion (only honored on final step)
10. **Add response** (with `audio_text`) to conversation history
11. **Update session summary** — Turn timeline (capped at 30 entries), progress trend, concepts taught
12. **Return TurnResult** (includes `audio_text` for TTS)

---

## Prompt System

### System Prompt (set once per session)

Contains:
- Student profile (grade, language level, preferred examples)
- Personalization block — either a rich personality profile (`tutor_brief` from personality enrichment) or basic info (student name, age, about_me from user profile)
- Study plan (steps with types and concepts)
- Topic guidelines (teaching approach, common misconceptions)
- 12 teaching rules: explain first (structured explanation phases with building blocks), advance when ready (with explanation guard), track questions, guide discovery with escalating strategy changes, never repeat, match energy, update mastery, be real with calibrated praise, end naturally, never leak internals + formatting rules, response/audio language instructions, explanation phase tracking instructions
- Response language instruction (English/Hindi/Hinglish based on `text_language_preference`)
- Audio language instruction (for `audio_text` field, based on `audio_language_preference`)

### Turn Prompt (per turn)

Contains:
- Current step info (type, concept, content hint)
- Explanation context (for explain steps: approach, analogy, building blocks with done/TODO markers, current phase, turns spent)
- Current mastery estimates
- Known misconceptions (with recurring misconception alerts)
- Turn timeline (session narrative so far, last 5 entries)
- Pacing directive (dynamic — includes explanation-aware pacing)
- Student style (dynamic)
- Awaiting answer section (if question pending, includes attempt number and escalating strategy)
- Exam evaluation section (for exam mode: question text, expected answer, fractional scoring instructions)
- Recent conversation history (max 10 messages)
- Current student message

### Mode-Specific Prompts

**Clarify Doubts** (`clarify_doubts_prompts.py`):
- Uses dedicated prompts: `CLARIFY_DOUBTS_SYSTEM_PROMPT` (direct answers, session closure rules, concept tracking, curriculum scope) and `CLARIFY_DOUBTS_TURN_PROMPT` (concepts discussed so far, conversation history, closure detection)
- Wired in `MasterTutorAgent._build_system_prompt()` and `_build_clarify_turn_prompt()` — when `session.mode == "clarify_doubts"`, the agent uses these instead of the master tutor prompts
- `mastery_updates` used to track which study plan concepts were substantively discussed
- `answer_correct` always null in clarify mode; `advance_to_step` never set
- Includes response and audio language instructions matching the student's preferences

**Exam** (`exam_prompts.py`):
- Question generation prompt: difficulty distribution (~30% easy, ~50% medium, ~20% hard), question types expanded to include `real_world`, `error_spotting`, `reasoning` in addition to `conceptual`, `procedural`, `application` — used by `ExamService.generate_questions()`. Includes personalization section from student personality.
- Evaluation: uses the master tutor prompts with an exam-specific awaiting_answer_section injected into the turn prompt. This section includes the question, expected answer, concept, difficulty, and fractional scoring instructions (`answer_score` 0.0-1.0 + `marks_rationale`). The evaluation system/turn prompt templates in `exam_prompts.py` exist but are not used for evaluation — they are reserved for future dedicated exam evaluation.
- Mid-exam: orchestrator constructs its own response showing only the next question (no correctness revealed). On final question: builds full results response with per-question score and rationale.

### Dynamic Signals

**Pacing Directive** (`_compute_pacing_directive`):

| Signal | Condition | Directive |
|--------|-----------|-----------|
| TURN 1 | First turn | Curiosity-building hook, inviting question, set explanation_phase_update='opening' |
| EXPLAIN (opening) | Current step is explain, phase is opening | Begin core explanation, ONE idea, everyday example, set phase='explaining' |
| EXPLAIN (building) | Phase is explaining, blocks remaining | Cover next building block, vary representation, one idea per turn |
| EXPLAIN (summarize) | Phase is explaining, all blocks covered | Summarize key idea, ask informal understanding check, set phase='informal_check' |
| EXPLAIN (check) | Phase is informal_check | Evaluate student's explanation; if understanding shown, set phase='complete' |
| EXPLAIN (done) | Phase is informal_check, check passed | Acknowledge and transition to next activity, set phase='complete' |
| ACCELERATE | avg_mastery >= 0.8 & improving (or 60%+ concepts >= 0.7 & improving) | Skip steps aggressively, minimal scaffolding |
| EXTEND | Aced plan & is_complete | Push to harder territory |
| SIMPLIFY | (avg_mastery < 0.4 with real data) or trend == struggling | Shorter sentences, 1-2 ideas per response |
| CONSOLIDATE | avg_mastery 0.4-0.65 & steady & current question has 2+ wrong attempts | Same-level problem to build confidence |
| STEADY | Default | One idea at a time |

Note: ACCELERATE has early fast-track detection — if 60%+ of concepts have mastery >= 0.7 AND avg_mastery >= 0.65 AND trend is improving, the system forces the accelerate path.

**Attention Span Awareness**: When the student's `attention_span` is set (from enrichment profile), the STEADY pacing directive appends a session length warning when turn count exceeds the threshold for the student's attention span (short: 8, medium: 14, long: 20 turns). This prompts the tutor to begin wrapping up.

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
| `GET` | `/sessions/{id}/summary` | Session performance summary |
| `GET` | `/sessions` | List all sessions for current user |
| `GET` | `/sessions/history` | Paginated session history (filterable by subject) |
| `GET` | `/sessions/stats` | Aggregated learning stats |
| `GET` | `/sessions/report-card` | Student report card with coverage and exam data |
| `GET` | `/sessions/topic-progress` | Lightweight topic progress for selection indicators |
| `GET` | `/sessions/resumable?guideline_id=X` | Find a paused Teach Me session for a subtopic |
| `GET` | `/sessions/guideline/{id}` | List sessions for a guideline (filterable by mode, completion) |
| `GET` | `/sessions/{id}/exam-review` | Detailed exam review for a completed exam (per-question scores + rationale) |
| `GET` | `/sessions/{id}/replay` | Full conversation JSON |
| `GET` | `/sessions/{id}` | Full session state (debug) |
| `GET` | `/sessions/{id}/agent-logs` | Agent execution logs |
| `POST` | `/transcribe` | Audio transcription via OpenAI Whisper |
| `POST` | `/text-to-speech` | Text-to-speech via Google Cloud TTS (Hindi/English voices) |

### WebSocket Endpoint

`WS /sessions/ws/{session_id}` — Used by both the frontend and the evaluation pipeline for real-time chat.

Auth via `?token=<jwt>` query param. For user-linked sessions, token must belong to session owner (validated via Cognito). Anonymous sessions allowed without token for backward compatibility.

**Connection flow:** Auth check → accept connection → send initial `state_update` → if first turn (turn_count == 0), generate welcome via `generate_welcome_message()` (returns `(message, audio_text)` — teach_me fallback; sessions created via REST already have the mode-specific welcome in history) → enter main message loop.

**Client sends:** `{"type": "chat", "payload": {"message": "..."}}`

**Server emits:**
```json
{"type": "typing", "payload": {}}
{"type": "assistant", "payload": {"message": "...", "audio_text": "..."}}
{"type": "state_update", "payload": {"state": {...}}}
{"type": "error", "payload": {"error": "..."}}
```

The `audio_text` field contains the spoken version of the tutor's response for TTS playback (language depends on student's `audio_language_preference`).

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
- Load guideline → Build StudentContext from user profile (including personality, enrichment, language preferences)
- Load personalized study plan from DB (user_id + guideline_id); if none exists for `teach_me` mode, generate one via `StudyPlanGeneratorService`
- Convert via topic_adapter → Create SessionState (with mode)
- For `teach_me` mode: initialize explanation phase if first step is "explain"
- For `exam` mode: guard against duplicate incomplete exams for same user + guideline (returns 409); generate exam questions via ExamService before welcome
- Generate mode-specific welcome message (each mode has its own welcome generator, returns `(message, audio_text)` tuple)
- For `exam`: append first question to welcome message; include `exam_questions` list in response
- Persist session to DB (with state_version=1)
- For `clarify_doubts`: attach past discussions for same user + guideline (up to 5 most recent, only sessions with at least one concept discussed)
- Return `{session_id, first_turn, mode}` (first_turn includes `audio_text`)

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
    student_context: StudentContext      # grade, board, language_level, name, age, about_me, personality, attention_span
    pace_preference: str                 # slow/normal/fast
    allow_extension: bool                # Continue past study plan
    is_paused: bool                      # Whether Teach Me session is paused
    concepts_covered_set: set[str]       # Concepts covered in this session
    # Explanation tracking
    explanation_phases: dict[str, ExplanationPhase]  # Per-concept explanation phase tracking
    current_explanation_concept: Optional[str]        # Which concept is currently being explained
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
    board: str                          # Educational board (e.g., "CBSE")
    language_level: str                 # "simple" | "standard" | "advanced"
    preferred_examples: list            # e.g., ["food", "sports", "games"] — from personality_json if available
    student_name: Optional[str]         # From user profile (preferred_name or name)
    student_age: Optional[int]          # From user profile
    about_me: Optional[str]             # From user profile
    text_language_preference: str       # "en" | "hi" | "hinglish" — language for text responses
    audio_language_preference: str      # "en" | "hi" | "hinglish" — language for TTS audio
    tutor_brief: Optional[str]          # Compact prose personality for system prompt (from PersonalityRepository)
    personality_json: Optional[dict]    # Full structured personality (for exam gen, example themes)
    attention_span: Optional[str]       # "short" | "medium" | "long" (from EnrichmentRepository)
```

When the user is authenticated, `StudentContext` is populated from multiple sources:
- **User profile**: name (preferred_name or name), age, about_me, grade, board, text/audio language preferences
- **Personality profile** (`PersonalityRepository`): `tutor_brief` (LLM-generated personality prose for the tutor system prompt) and `personality_json` (structured personality including `example_themes` for preferred examples)
- **Enrichment profile** (`EnrichmentRepository`): `attention_span` for session length awareness

The personalization block in the system prompt uses `tutor_brief` when available (rich personality), falling back to basic name/age/about_me fields.

### ExplanationPhase

```python
class ExplanationPhase(BaseModel):
    concept: str                        # Concept being explained
    step_id: int                        # Study plan step ID
    phase: ExplanationPhaseName         # "not_started" | "opening" | "explaining" | "informal_check" | "complete"
    tutor_turns_in_phase: int           # Tutor turns spent so far
    building_blocks_covered: list[str]  # Building blocks already covered
    student_engaged: bool               # Whether student has shown engagement
    informal_check_passed: bool         # Whether informal understanding check passed
    skip_reason: Optional[str]          # e.g., "student_demonstrated_knowledge"
```

Explanation phases are tracked per-concept in `SessionState.explanation_phases`. The orchestrator's `_handle_explanation_phase()` manages lifecycle transitions based on `TutorTurnOutput` fields. Step advancement is blocked (`can_advance_past_explanation()`) until the explanation is complete, skipped, or the informal check has passed after minimum turns.

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

**Explanation guard**: If the current step is an `explain` step and the explanation is not yet complete (`can_advance_past_explanation()` returns false), advancement is blocked and logged. The explanation must reach "complete" phase, have a skip reason (e.g., student demonstrated prior knowledge), or have the informal check passed after minimum turns before the step can be advanced past.

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
    question_type: "conceptual" | "procedural" | "application" | "real_world" | "error_spotting" | "reasoning"
    expected_answer: str
    student_answer: Optional[str]
    result: Optional["correct" | "partial" | "incorrect"]
    feedback: str
    score: float              # Fractional score 0.0-1.0 (from answer_score)
    marks_rationale: str      # Brief justification for the score

class ExamFeedback(BaseModel):
    score: float              # Total score (sum of per-question scores, e.g., 5.3)
    total: int                # Number of questions
    percentage: float         # score/total * 100
    strengths: list[str]
    weak_areas: list[str]
    patterns: list[str]
    next_steps: list[str]
```

Exam questions are generated at session creation time via `ExamService.generate_questions()`, which uses an LLM call with structured output. Default: 7 questions. On failure, retries with 3 questions. The generation prompt includes `personalization_section` from student personality when available.

**Fractional scoring**: Each answer is scored 0.0-1.0 via `TutorTurnOutput.answer_score` (with `marks_rationale`). Categorical result is derived from the fractional score: >= 0.8 is "correct", >= 0.2 is "partial", < 0.2 is "incorrect". Final exam score is the sum of all per-question scores (e.g., 5.3/7 = 75.7%).

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

Study plan loading priority:
1. **Personalized plan**: Look up `StudyPlan` by `user_id + guideline_id`
2. **Shared plan**: Fall back to any plan for the `guideline_id`
3. **Auto-generate** (teach_me only): If no plan exists and user is authenticated, generate a personalized plan via `StudyPlanGeneratorService` (uses `study_plan_generator` LLM config), save it to DB, and use it
4. **Default**: If all above fail, a default 4-step plan is generated: explain → check → explain → practice

Study plan steps have types: `explain`, `check`, `practice`. Step type is inferred from the plan item's title/description keywords or defaults to a pattern (explain, check, explain, check, ..., practice at end).

**Explain step sub-plan fields** (only used for explain steps):
- `explanation_approach`: Teaching method (e.g., "visual analogy", "storytelling")
- `explanation_building_blocks`: Ordered sub-ideas to cover across turns
- `explanation_analogy`: Suggested real-world connection
- `min_explanation_turns`: Minimum tutor turns before advancing (default: 2)

---

## LLM Calls

| Call | Model | Purpose | Output | Prompt Source |
|------|-------|---------|--------|---------------|
| Input Translation | Configurable (DB) | Translate Hinglish/Hindi to English | JSON `{english: str}` | Inline in `orchestrator.py` |
| Safety | Configurable (DB) | Content moderation | SafetyOutput (strict) | `templates.py` SAFETY_TEMPLATE |
| Master Tutor (teach_me) | Configurable (DB) | Structured teaching + state updates | TutorTurnOutput (strict) | `master_tutor_prompts.py` |
| Master Tutor (clarify) | Configurable (DB) | Direct Q&A answers | TutorTurnOutput (strict) | `clarify_doubts_prompts.py` |
| Master Tutor (exam) | Configurable (DB) | Exam answer evaluation + scoring | TutorTurnOutput (strict) | `master_tutor_prompts.py` (with exam section injected) |
| Welcome (Teach Me) | Configurable (DB) | Welcome message for structured lesson | JSON `{response, audio_text}` | `orchestrator_prompts.py` |
| Welcome (Clarify) | Configurable (DB) | Welcome message for Q&A mode | JSON `{response, audio_text}` | Inline in `orchestrator.py` |
| Welcome (Exam) | Configurable (DB) | Welcome message for exam mode | JSON `{response, audio_text}` | Inline in `orchestrator.py` |
| Post-Completion | Configurable (DB) | Context-aware reply after session ends | Plain text | Inline in `orchestrator.py` |
| Exam Questions | Configurable (DB) | Generate exam questions at session start | Structured JSON (array of questions) | `exam_prompts.py` EXAM_QUESTION_GENERATION_PROMPT |
| Study Plan Generation | Configurable (DB, `study_plan_generator` key) | Generate personalized study plan | Structured JSON | `StudyPlanGeneratorService` |

LLM provider/model is resolved at session creation from the `llm_config` DB table via `LLMConfigService.get_config("tutor")`. The Anthropic adapter maps structured output to tool_use, and reasoning effort to thinking budgets. Welcome messages and input translation use `reasoning_effort="none"` for speed.

---

## Audio: Transcription and Text-to-Speech

### Transcription (Speech-to-Text)

Audio transcription is handled by a separate endpoint (`POST /transcribe`) using OpenAI Whisper:
- Accepts audio files up to 25 MB
- Supported formats: webm, ogg, mp4, mpeg, wav, flac
- Returns `{text: str}` — the transcribed text
- Used by the frontend's voice input feature

### Text-to-Speech

Text-to-speech is handled by `POST /text-to-speech` using Google Cloud TTS API:
- Accepts `{text: str, language: "en" | "hi" | "hinglish"}` (max 5000 characters)
- Returns streaming MP3 audio
- Voice selection based on language:
  - English: `en-IN-Neural2-A` (Indian English)
  - Hindi/Hinglish: `hi-IN-Neural2-D` (Hindi)
- Audio config: speaking_rate=1.1, pitch=3.0
- Requires `google_cloud_tts_api_key` in settings
- The tutor generates `audio_text` alongside every response (a spoken version tailored for TTS, using the student's `audio_language_preference`). The frontend sends this `audio_text` to the TTS endpoint for playback.

---

## Key Files

### Agents (`tutor/agents/`)

| File | Purpose |
|------|---------|
| `base_agent.py` | BaseAgent ABC: execute(), build_prompt(), LLM call with strict schema |
| `master_tutor.py` | MasterTutorAgent: single agent for all teaching, TutorTurnOutput model (with audio_text, answer_score, marks_rationale, explanation phase fields), pacing/style computation (with explanation-aware pacing and attention span), personalization block (tutor_brief or fallback), explanation context builder, clarify-specific prompt routing |
| `safety.py` | SafetyAgent: fast content moderation gate |

### Orchestration (`tutor/orchestration/`)

| File | Purpose |
|------|---------|
| `orchestrator.py` | TeacherOrchestrator: input translation → safety → mode router → master_tutor → state updates. Includes `_translate_to_english()` for Hinglish/Hindi input. Mode-specific methods: `_process_clarify_turn()` (with clarify_complete handling), `_process_exam_turn()` (with fractional scoring via answer_score/marks_rationale). `_handle_explanation_phase()` for explanation lifecycle. `_apply_state_updates()` with explanation guard on step advancement. Exam feedback builder. Separate welcome generators per mode returning `(message, audio_text)` tuples. Post-completion response generator. |

### Models (`tutor/models/`)

| File | Purpose |
|------|---------|
| `session_state.py` | SessionState (with ExplanationPhase tracking), Question, Misconception, SessionSummary, ExamQuestion (with score/marks_rationale), ExamFeedback, ExplanationPhase, create_session() |
| `study_plan.py` | Topic, TopicGuidelines, StudyPlan, StudyPlanStep (with explanation sub-plan fields: approach, building_blocks, analogy, min_turns) |
| `messages.py` | Message (with audio_text), StudentContext (with language preferences, tutor_brief, personality_json, attention_span), WebSocket DTOs (ClientMessage, ServerMessage with audio_text, SessionStateDTO), factory functions |
| `agent_logs.py` | AgentLogEntry, AgentLogStore (in-memory, thread-safe) |

### Prompts (`tutor/prompts/`)

| File | Purpose |
|------|---------|
| `master_tutor_prompts.py` | System prompt (study plan + guidelines + 12 rules + personalization + language instructions + explanation phase tracking) and turn prompt (with explanation context section). Used for teach_me and exam modes. |
| `clarify_doubts_prompts.py` | System and turn prompts for Clarify Doubts mode. **Actively wired** — used by `MasterTutorAgent._build_system_prompt()` and `_build_clarify_turn_prompt()` when mode is `clarify_doubts`. |
| `exam_prompts.py` | Exam question generation prompt (actively used by ExamService, includes personalization section) and evaluation prompts (evaluation prompts defined but not yet wired — exam eval uses master tutor prompts with injected exam section). |
| `orchestrator_prompts.py` | Welcome message (Teach Me) and session summary prompts |
| `language_utils.py` | `get_response_language_instruction()` and `get_audio_language_instruction()` — return prompt text for language preferences (en/hi/hinglish). Used by system prompts and welcome generators. |
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
| `tutor/services/session_service.py` | Session creation (all modes, with personalized plan generation), step processing, pause/resume, end clarify, end exam, summary, CAS persistence, duplicate exam guard, StudentContext building from profile+personality+enrichment |
| `tutor/services/exam_service.py` | Exam question generation via LLM with retry. ExamGenerationError (LearnLikeMagicException subclass) |
| `tutor/services/topic_adapter.py` | DB guideline + study plan → Topic model |
| `tutor/services/report_card_service.py` | Report card aggregation, topic progress for selection indicators |
| `tutor/api/sessions.py` | REST + WebSocket + agent logs endpoints, session ownership checks, end-clarify endpoint, exam-review endpoint, guideline sessions endpoint |
| `tutor/api/transcription.py` | Audio transcription endpoint (OpenAI Whisper) |
| `tutor/api/tts.py` | Text-to-speech endpoint (Google Cloud TTS, Hindi/English voices) |
| `tutor/api/curriculum.py` | Curriculum discovery endpoints |
| `tutor/exceptions.py` | Custom exception hierarchy (TutorAgentError, LLMError, AgentError, SessionError, StateError, PromptError, ConfigurationError) |
| `shared/services/llm_service.py` | LLM wrapper (OpenAI Responses API, Chat Completions, Gemini, Anthropic) |
| `shared/services/anthropic_adapter.py` | Claude API adapter (tool_use for structured output, thinking budgets) |
| `shared/services/llm_config_service.py` | DB-backed LLM config: component_key → provider + model_id |
