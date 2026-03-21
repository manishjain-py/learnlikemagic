# Learning Session — Technical

Architecture, agents, orchestration, and APIs for the tutoring pipeline.

---

## Architecture

```
Student Message
    │
    ├──────────────────────┐
    v                      v
INPUT TRANSLATION    SAFETY AGENT
(Hinglish/Hindi→EN)  (fast gate)
    │                      │
    └──────────┬───────────┘
               │  (parallel)
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
 explanation phase, step                  (+ audio_text
 advance, coverage)                        + visual_explanation)
    │
    v
Response to Student
(+ audio_text for TTS)
    │
    v  (if visual_explanation present)
PIXI CODE GENERATOR
(LLM → Pixi.js v8 code)
    │
    v
Visual Update to Client
```

Pipeline: input translation and safety check run **in parallel** (saves 2-5s), then a single master tutor call that handles all teaching. Each mode uses its own prompt templates. The orchestrator routes to mode-specific processing after the safety check. Sanitization check (leaked internal language detection) applies only to teach_me mode. All responses include an `audio_text` field for text-to-speech. When the tutor includes a `visual_explanation` and the `show_visuals_in_tutor_flow` feature flag is enabled, a secondary LLM call generates executable Pixi.js v8 code for client-side rendering.

**Pre-computed explanations (card phase):** For subtopics that have pre-computed explanation variants in the `topic_explanations` table, session creation generates a welcome via `generate_tutor_welcome()` (master tutor agent, card-aware) and initializes a `CardPhaseState`. The student interacts with cards (read-only) until they either confirm understanding ("clear") or request a different approach ("explain_differently"). The card phase is handled entirely via the `POST /sessions/{id}/card-action` REST endpoint — it does not go through the orchestrator's `process_turn` pipeline. On "clear", the service: (1) builds `precomputed_explanation_summary` from shown variants, (2) generates a **v2 session plan** via `StudyPlanGeneratorService.generate_session_plan()` with step types `check_understanding`, `guided_practice`, `independent_practice`, `extend`, (3) generates a **bridge turn** via `generate_bridge_turn(bridge_type="understood")` that references specific card analogies and asks a recall question. When all variants are exhausted, the bridge uses `bridge_type="confused"` to start a fresh interactive explanation. The master tutor's system prompt receives the `precomputed_explanation_summary_section` so it avoids repeating covered material and uses the cards' analogies as shared vocabulary.

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

Provider and model are configured via the `llm_config` DB table, read at session creation time through `LLMConfigService.get_config("tutor")`. Supported providers: `openai` (GPT-5.4, GPT-5.3-codex, GPT-5.2, GPT-5.1), `anthropic` / `anthropic-haiku` (Claude), `google` (Gemini).

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
    question_format: QuestionFormat|None  # Structured question format for interactive UI
    # Explanation phase tracking (explain steps only)
    explanation_phase_update: str|None       # opening/explaining/informal_check/complete/skip
    explanation_building_blocks_covered: list[str]  # Building blocks covered this turn
    student_shows_understanding: bool|None   # Informal check result
    student_shows_prior_knowledge: bool|None # Skip explanation if student knows it
    session_complete: bool     # True when final step mastered
    visual_explanation: VisualExplanation|None  # Optional visual for PixiJS rendering
    turn_summary: str          # One-line summary (max 80 chars)
    reasoning: str             # Internal reasoning (not shown to student)
}

# QuestionFormat {
#     type: "fill_in_the_blank" | "single_select" | "multi_select" | "acknowledge"
#     sentence_template: str|None  # For fill_in_the_blank: "The sum of 3 and 4 is ___0___"
#     blanks: list[BlankItem]|None # For fill_in_the_blank: [{blank_id, correct_answer}]
#     options: list[OptionItem]|None  # For select types: [{key, text, correct}]
# }

# VisualExplanation {
#     visual_prompt: str       # Natural language description of what to draw
#     output_type: str         # "image" (static) or "animation" (animated)
#     title: str|None          # Short title
#     narration: str|None      # Short narration text
# }
```

---

## Orchestration Flow

`TeacherOrchestrator.process_turn(session, student_message)`:

1. **Post-completion check** — If session already complete: for `clarify_doubts` mode, always short-circuit with a context-aware response. For `teach_me`, short-circuit if no extension allowed or extension_turns > 10. Post-completion paths still run safety + translation in parallel before responding. The context-aware response is LLM-generated and responds naturally to whatever the student said.
2. **Input Translation + Safety (parallel)** — Translation (Hinglish/Hindi → English via fast LLM call) and safety check run concurrently via `asyncio.gather`, saving 2-5s per turn.
3. **Increment turn** — Add translated student message to history
4. **Build AgentContext** — Current state, mastery, study plan
5. **Safety gate** — If unsafe: return guidance + log safety flag
6. **Mode Router** — Branch based on `session.mode`:
   - `clarify_doubts` → `_process_clarify_turn()`: runs master tutor with clarify-specific prompts (`CLARIFY_DOUBTS_SYSTEM_PROMPT` + `CLARIFY_DOUBTS_TURN_PROMPT`), tracks concepts discussed via `mastery_updates` (added to both `concepts_discussed` and `concepts_covered_set`), no step advancement. Marks `clarify_complete = True` when tutor output has `intent == "done"` or `session_complete == True` (student indicated they are done).
   - `exam` → `_process_exam_turn()`: evaluates answer against current exam question using fractional scoring (0.0-1.0). Score >= 0.8 → correct, >= 0.2 → partial, < 0.2 → incorrect. Records `marks_rationale` per question. Mid-exam responses show only the next question — correctness is not revealed. When the last question is answered, builds a full results response with per-question scores, rationales, and final score.
   - `teach_me` → continues to step 7
7. **Master Tutor Agent** — Single LLM call with system prompt (study plan + guidelines + 15 teaching rules + personalization block) and turn prompt (current state, mastery, explanation context, pacing directive, student style, feedback notices, history)
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
12. **Visual Generation (optional)** — If `tutor_output.visual_explanation` is present and visuals are enabled, generate Pixi.js v8 code via `PixiCodeGenerator`. Visual generation is gated by the `show_visuals_in_tutor_flow` feature flag (read from `feature_flags` DB table via `FeatureFlagService` at orchestrator initialization). When disabled, `_generate_pixi_code()` returns `None` and the frontend receives no visual. Failures are logged and silently skipped (never crashes the turn).
13. **Return TurnResult** (includes `audio_text`, optional `visual_explanation` with generated `pixi_code`, and optional `question_format`)

### Streaming Path

`TeacherOrchestrator.process_turn_stream(session, student_message)` is an async generator that yields tuples:

- `("token", str)` — text chunk for real-time streaming of the student-facing response
- `("result", TurnResult)` — final result with state updates applied (always emitted)
- `("visual", dict)` — Pixi.js visual data, sent after the result so text is not delayed

Only `teach_me` mode streams tokens. `clarify_doubts` and `exam` modes fall back to non-streaming `process_turn` internally. The WebSocket handler converts these into `token`, `assistant`, `state_update`, and `visual_update` messages.

---

## Prompt System

### System Prompt (teach_me — set once per session)

Contains:
- Student profile (grade, language level, preferred examples)
- Personalization block: uses `tutor_brief` (rich personality prose from enrichment profile) when available, falling back to basic name/age/about_me from user profile
- Prior topics context section (when `TopicGuidelines.prior_topics_context` is set — tells the tutor what earlier topics in the chapter cover)
- Pre-computed explanation summary section (when `precomputed_explanation_summary` is set after card phase completion — tells the tutor what was already explained via cards, so it does not repeat those analogies/examples/approaches)
- Study plan (steps with types, concepts, content hints)
- Topic guidelines (curriculum scope, common misconceptions)
- 15 teaching rules: verify-practice-extend (check card knowledge first, re-explain only if confused using different approach), advance when ready (with explanation guard), track questions, guide discovery with escalating strategy changes (strategy switch rule after 2 consecutive corrections, prerequisite gap detection), never repeat (use card analogies as shared vocabulary), detect false OKs strictly (no yes/no comprehension checks allowed, rote echoes caught), match energy (correction warmth, self-correction acknowledgment, correct-but-informal handling), update mastery, calibrated praise (confirm in 1 sentence after correct, drop reinforcement after 2+ correct), end naturally, never leak internals (colored emoji for illustrations), response/audio language instructions, explanation phase tracking (remedial re-explanation only), visual explanations (strongly encouraged), interactive question formats (fill_in_the_blank, single_select, multi_select, acknowledge via `question_format` field)
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
| TURN 1 | First turn, no card summary | Curiosity-building hook, inviting question, set explanation_phase_update='opening' |
| TURN 1 (post-cards) | First turn, precomputed_explanation_summary present | Connect to card analogies, ask student to explain back |
| CHECK UNDERSTANDING | v2 step type `check_understanding` | Ask recall/comprehension referencing card content, watch for misconceptions |
| GUIDED PRACTICE | v2 step type `guided_practice` | Work through problems together, reference card examples, increase difficulty |
| INDEPENDENT PRACTICE | v2 step type `independent_practice` | Student works alone, tutor only intervenes on errors |
| EXTEND | v2 step type `extend` | Apply concepts to new contexts, use personalization hint |
| QUICK-CHECK (cards) | v1 explain step where concept is in `card_covered_concepts` | Skip re-explanation, ask quick recall, advance if remembered |
| EXPLAIN (opening) | Explain step, phase=opening | Begin core explanation, one idea, everyday example, set phase='explaining' |
| EXPLAIN (building) | Explain step, phase=explaining, blocks remaining | Cover next building block with varied representation, one per turn |
| EXPLAIN (summarize) | Explain step, phase=explaining, all blocks covered | Summarize key idea, ask informal understanding check, set phase='informal_check' |
| EXPLAIN (check) | Explain step, phase=informal_check | Evaluate student's response, set student_shows_understanding accordingly |
| EXPLAIN (done) | Explain step, phase=informal_check, check passed | Acknowledge and transition, set phase='complete' |
| ACCELERATE | avg_mastery >= 0.8 & improving (or 60%+ concepts >= 0.7 & improving) | Skip steps aggressively, minimal scaffolding |
| EXTEND (post-plan) | Aced plan & is_complete | Push to harder territory |
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
| `POST` | `/sessions/{id}/card-action` | Card phase action: "clear" (transition to interactive) or "explain_differently" (switch variant) |
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
{"type": "token", "payload": {"message": "<chunk>"}}
{"type": "assistant", "payload": {"message": "...", "audio_text": "...", "visual_explanation": {...}, "question_format": {...}}}
{"type": "state_update", "payload": {"state": {...}}}
{"type": "visual_update", "payload": {"visual_explanation": {"output_type": "...", "title": "...", "narration": "...", "pixi_code": "..."}}}
{"type": "error", "payload": {"error": "..."}}
```

For `teach_me` mode, the server streams `token` messages in real time as the tutor generates its response, followed by the full `assistant` message. For `clarify_doubts` and `exam`, only the final `assistant` message is sent (no token streaming). The `visual_update` message is sent after the `assistant` message when the tutor generated a visual explanation — this allows the text to arrive without waiting for Pixi code generation.

The `audio_text` field contains the spoken version of the response for TTS (in the student's audio language preference).

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
- `{"type": "card_navigate", "payload": {"card_idx": N}}` — update card position during card phase (persists to DB)

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
- Load guideline
- Build StudentContext from user profile when authenticated (name, age, about_me, tutor_brief from personality profile, personality_json, attention_span from enrichment, text/audio language preferences)
- Load personalized study plan from DB (user_id + guideline_id), falling back to any plan for that guideline
- For `teach_me`: if no plan exists, generate a personalized plan via `StudyPlanGeneratorService` using the student's personality context
- Convert via topic_adapter → Create SessionState (with mode)
- **Card phase check** (`teach_me` only): query `ExplanationRepository.get_by_guideline_id()`. If pre-computed explanations exist:
  - Initialize `CardPhaseState` on the session (active=true, first variant selected, cards counted)
  - Generate welcome via `generate_tutor_welcome()` (master tutor agent, card-aware framing — mentions cards are prepared)
  - Skip explanation phase initialization
  - Return explanation cards in `first_turn` with `session_phase: "card_phase"` and `card_phase_state` metadata
- **Standard path** (no pre-computed explanations, or non-teach_me modes):
  - For `teach_me`: initialize explanation phase if first step is `explain` type
  - For `exam` mode: guard against duplicate incomplete exams (409 if one exists with progress), then generate exam questions via ExamService before welcome
  - Generate mode-specific welcome message (each mode has its own welcome generator) — returns `(message, audio_text)` tuple with language-appropriate content
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
    student_context: StudentContext      # grade, board, language, personality, attention span
    pace_preference: str                 # slow/normal/fast
    allow_extension: bool                # Continue past study plan
    is_paused: bool                      # Whether Teach Me session is paused
    concepts_covered_set: set[str]       # Concepts covered in this session
    # Explanation tracking
    explanation_phases: dict[str, ExplanationPhase]  # Per-concept explanation lifecycle
    current_explanation_concept: Optional[str]        # Active explanation concept
    # Pre-computed explanations (card phase)
    card_phase: Optional[CardPhaseState]           # Card-based explanation state (None when not in card phase)
    precomputed_explanation_summary: Optional[str]  # Summary of shown cards, injected into tutor system prompt
    card_covered_concepts: set[str]                # Concepts covered during card phase, for quick-check pacing
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
    preferred_examples: list            # e.g., ["food", "sports", "games"]
    student_name: Optional[str]         # From user profile
    student_age: Optional[int]          # From user profile
    about_me: Optional[str]             # From user profile
    text_language_preference: str       # "en" | "hi" | "hinglish" — language for text responses
    audio_language_preference: str      # "en" | "hi" | "hinglish" — language for TTS audio
    tutor_brief: Optional[str]          # Rich personality prose from enrichment profile
    personality_json: Optional[dict]    # Full structured personality (for exam personalization)
    attention_span: Optional[str]       # "short" | "medium" | "long" — from enrichment profile
```

When the user is authenticated, `StudentContext` is populated from the user profile (name, age, about_me), the personality profile (`tutor_brief`, `personality_json`), and the enrichment profile (`attention_span`). `tutor_brief` is used in the system prompt personalization block — when available, it replaces the basic name/age personalization with a rich personality prose that tailors the tutor's entire interaction style.

### ExplanationPhase

```python
class ExplanationPhase(BaseModel):
    concept: str                     # Concept being explained
    step_id: int                     # Study plan step ID
    phase: ExplanationPhaseName      # not_started/opening/explaining/informal_check/complete
    tutor_turns_in_phase: int        # Tutor turns spent so far
    building_blocks_covered: list[str]  # Building blocks already covered
    student_engaged: bool            # Whether student showed engagement
    informal_check_passed: bool      # Whether informal understanding check passed
    skip_reason: Optional[str]       # e.g., "student_demonstrated_knowledge"
```

Explanation phases are tracked per concept in `SessionState.explanation_phases`. The orchestrator's `_handle_explanation_phase()` manages lifecycle transitions based on `TutorTurnOutput` fields. The `can_advance_past_explanation()` guard prevents step advancement until the explanation is complete (phase=complete, skip_reason set, informal check passed, or minimum turns reached during informal_check phase).

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

Master tutor sets `advance_to_step` in output. Applied in `_apply_state_updates()`. When advancing, all intermediate step concepts are added to `concepts_covered_set`. An **explanation guard** prevents advancement past explain steps that are not yet complete — the explanation must reach `phase=complete`, have a `skip_reason` set, or pass the informal check before the step can advance.

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
    score: float                # Fractional score 0.0-1.0
    marks_rationale: str        # Brief justification for score

class ExamFeedback(BaseModel):
    score: float               # Total fractional score (e.g., 5.3)
    total: int                 # Total questions
    percentage: float
    strengths: list[str]
    weak_areas: list[str]
    patterns: list[str]
    next_steps: list[str]
```

Exam questions are generated at session creation time via `ExamService.generate_questions()`, which uses an LLM call with structured output. Default: 7 questions. On failure, retries with 3 questions. Questions are personalized using `personality_json` (student name, interests, people to reference) when available.

Scoring uses fractional values (0.0-1.0) per question via `TutorTurnOutput.answer_score`, with categorical result derived: score >= 0.8 → correct, >= 0.2 → partial, < 0.2 → incorrect. The `marks_rationale` provides a brief justification for each score.

### Card Phase (Pre-Computed Explanations)

```python
class CardPhaseState(BaseModel):
    guideline_id: str              # FK for explanation lookups
    active: bool                   # Whether card phase is currently active
    current_variant_key: str       # Current variant being shown (e.g., "A")
    current_card_idx: int          # Current card index (0-based)
    total_cards: int               # Total cards in current variant
    variants_shown: list[str]      # Variant keys already shown
    available_variant_keys: list[str]  # All available variant keys
    completed: bool                # True when student says "clear" or exhausts variants
```

Card phase is initialized during session creation when `ExplanationRepository.get_by_guideline_id()` returns pre-computed explanation variants for the guideline. Welcome is generated via `generate_tutor_welcome()` (master tutor agent, card-aware framing). The `POST /sessions/{id}/card-action` endpoint handles two actions:

- **`clear`**: Student understood the cards. Flow: (1) builds `precomputed_explanation_summary` from shown variants' summaries (prefers `teaching_notes` from summary_json, falls back to structured labels), (2) generates **v2 session plan** via `_generate_v2_session_plan()` → `StudyPlanGeneratorService.generate_session_plan()` → `convert_session_plan_to_study_plan()`, replacing the v1 plan with steps typed `check_understanding`/`guided_practice`/`independent_practice`/`extend`, (3) generates a **bridge turn** via `generate_bridge_turn(bridge_type="understood")` — master tutor generates a recall question referencing specific card analogies. Returns `{action: "transition_to_interactive", message, audio_text, question_format}`.
- **`explain_differently`**: Switches to the next unseen variant from `available_variant_keys`. If all variants are exhausted, completes the card phase with the same v2 plan generation flow, but uses `bridge_type="confused"` — the master tutor starts a fresh interactive explanation with a different approach. Returns `{action: "fallback_dynamic", message, audio_text, question_format}`.

Bridge turn generation uses `MASTER_TUTOR_BRIDGE_PROMPT` via `MasterTutorAgent.generate_bridge()`, which builds context from the precomputed summary and the bridge type. State updates from the bridge turn (e.g., question tracking) are applied normally.

The `process_step()` REST endpoint rejects calls during an active card phase (HTTP 400), directing the client to use `/card-action` instead. The `/replay` endpoint includes explanation cards for sessions still in card phase.

Pre-computed explanations are stored in the `topic_explanations` DB table, managed by `ExplanationRepository` (shared/repositories). Each variant has a `variant_key`, `variant_label`, `cards_json` (array of card objects with `card_idx`, `card_type`, `title`, `content`, optional `visual`), and `summary_json` (approach label, card titles, key analogies, key examples, optional `teaching_notes` for richer summaries).

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

### Plan Versions

**v1 (legacy):** Steps have types `explain`, `check`, `practice`. Step type is inferred from the plan item's title/description keywords or defaults to a pattern (explain, check, explain, check, ..., practice at end). Explain steps can include sub-plan fields: `explanation_approach`, `explanation_building_blocks` (ordered sub-ideas to cover across turns), `explanation_analogy`, and `min_explanation_turns`.

**v2 (post-card interactive):** Generated at card phase completion via `StudyPlanGeneratorService.generate_session_plan()`, converted by `convert_session_plan_to_study_plan()`. Steps have types `check_understanding`, `guided_practice`, `independent_practice`, `extend`. Each step carries: `description`, `card_references` (card concepts/analogies to reference), `misconceptions_to_probe`, `success_criteria`, `difficulty`, `personalization_hint`. The pacing system has dedicated directives for each v2 step type. Detected via `plan_version: 2` in plan metadata.

The `TopicGuidelines` model also carries `prior_topics_context` (optional), which provides curriculum context about what prior topics in the same chapter cover. When present, it is rendered as a "Prior Topics in This Chapter" section in the master tutor system prompt, helping the tutor understand what the student may have already learned.

Plan resolution order at session creation:
1. Personalized plan for this user + guideline (from `study_plans` table)
2. Any existing plan for this guideline (fallback)
3. For `teach_me` mode with an authenticated user: generate a personalized plan on-the-fly via `StudyPlanGeneratorService` using the student's personality context
4. If no plan exists at all, a default 5-step plan is generated: explain → explain → check → explain → practice

### Mid-Session Feedback

The `POST /sessions/{id}/feedback` endpoint allows study plan regeneration during an active session:

- Accepts `feedback_text` (free-form) and `action` ("continue" or "restart")
- Rate limited to 3 feedback submissions per session (tracked in `session_feedbacks` table)
- Generates a new plan via `StudyPlanGeneratorService.generate_plan_with_feedback()` with context: feedback text, concepts already covered, current position
- **Continue**: splices new remaining steps from current position forward, filtering out already-covered concepts
- **Restart**: replaces entire plan and resets session state (step, mastery, misconceptions, explanation phases, conversation history) to step 1; generates a new welcome message
- Both actions upsert the `study_plans` table and persist via CAS
- A `[FEEDBACK]` or `[FEEDBACK-RESTART]` marker is added to the turn timeline, which triggers a contextual notice in the next turn prompt so the tutor acknowledges the change naturally

---

## LLM Calls

| Call | Model | Purpose | Output | Prompt Source |
|------|-------|---------|--------|---------------|
| Input Translation | Configurable (DB) | Hinglish/Hindi → English | JSON `{english: str}` | Inline in `orchestrator.py` |
| Safety | Configurable (DB) | Content moderation | SafetyOutput (strict) | `templates.py` SAFETY_TEMPLATE |
| Master Tutor (teach_me) | Configurable (DB) | Structured lesson teaching | TutorTurnOutput (strict) | `master_tutor_prompts.py` |
| Master Tutor (clarify) | Configurable (DB) | Doubt-clearing Q&A | TutorTurnOutput (strict) | `clarify_doubts_prompts.py` |
| Master Tutor (exam) | Configurable (DB) | Exam answer evaluation | TutorTurnOutput (strict) | `master_tutor_prompts.py` (with exam context injected) |
| Tutor Welcome | Configurable (DB) | Welcome for card-phase sessions | TutorTurnOutput (strict) | `master_tutor_prompts.py` MASTER_TUTOR_WELCOME_PROMPT |
| Bridge Turn | Configurable (DB) | Post-card transition (understood/confused) | TutorTurnOutput (strict) | `master_tutor_prompts.py` MASTER_TUTOR_BRIDGE_PROMPT |
| Welcome (Teach Me) | Configurable (DB) | Welcome for non-card sessions | JSON `{response, audio_text}` | `orchestrator_prompts.py` |
| Welcome (Clarify) | Configurable (DB) | Welcome message for Q&A mode | JSON `{response, audio_text}` | Inline in `orchestrator.py` |
| Welcome (Exam) | Configurable (DB) | Welcome message for exam mode | JSON `{response, audio_text}` | Inline in `orchestrator.py` |
| Post-Completion | Configurable (DB) | Context-aware reply after session ends | Plain text | Inline in `orchestrator.py` |
| Exam Questions | Configurable (DB) | Generate exam questions at session start | Structured JSON (array of questions) | `exam_prompts.py` EXAM_QUESTION_GENERATION_PROMPT |
| Study Plan Gen | Configurable (DB, `study_plan_generator`) | Generate/regenerate personalized study plan | Structured JSON | `StudyPlanGeneratorService` |
| Session Plan Gen | Configurable (DB, `study_plan_generator`) | Generate v2 interactive plan at card completion | Structured JSON | `StudyPlanGeneratorService.generate_session_plan()` |
| Pixi Code Gen | Configurable (DB) | Generate Pixi.js v8 code from visual description | Plain JavaScript | `pixi_code_generator.py` inline prompt |

LLM provider/model is resolved at session creation from the `llm_config` DB table via `LLMConfigService.get_config("tutor")`. Study plan generation uses a separate config key `study_plan_generator`. The Anthropic adapter maps structured output to tool_use, and reasoning effort to thinking budgets.

---

## Transcription and TTS

**Audio Transcription** is handled by a separate endpoint (`POST /transcribe`) using OpenAI Whisper:
- Accepts audio files up to 25 MB
- Supported formats: webm, ogg, mp4, mpeg, wav, flac
- Returns `{text: str}` — the transcribed text
- Used by the frontend's voice input feature

**Text-to-Speech** is handled by `POST /text-to-speech` using Google Cloud TTS:
- Accepts text up to 5,000 characters and a `language` parameter (`en`, `hi`, or `hinglish`)
- Uses Indian voices: `en-IN-Neural2-A` for English, `hi-IN-Neural2-D` for Hindi/Hinglish
- Returns MP3 audio stream
- Tutor responses include an `audio_text` field specifically crafted for TTS — this is a spoken version of the response in the student's audio language preference, which may differ from the displayed text language

---

## Key Files

### Agents (`tutor/agents/`)

| File | Purpose |
|------|---------|
| `base_agent.py` | BaseAgent ABC: execute(), build_prompt(), LLM call with strict schema |
| `master_tutor.py` | MasterTutorAgent: single agent for all teaching, TutorTurnOutput model (with audio_text, answer_score, marks_rationale, explanation phase fields, visual_explanation, question_format), QuestionFormat/BlankItem/OptionItem models (structured interactive questions), VisualExplanation model, pacing/style computation (explanation-aware + attention span + v2 step types), personalization block (tutor_brief or name/age fallback), mode-specific prompt routing (clarify uses dedicated prompts), `generate_welcome()` (card-aware via MASTER_TUTOR_WELCOME_PROMPT), `generate_bridge()` (post-card bridge via MASTER_TUTOR_BRIDGE_PROMPT) |
| `safety.py` | SafetyAgent: fast content moderation gate |

### Orchestration (`tutor/orchestration/`)

| File | Purpose |
|------|---------|
| `orchestrator.py` | TeacherOrchestrator: parallel input translation + safety → mode router → master_tutor → state updates → optional visual generation. `process_turn()` (non-streaming) and `process_turn_stream()` (async generator with token streaming for teach_me). Input translation (`_translate_to_english`). Mode-specific methods: `_process_clarify_turn()` (with clarify_complete handling), `_process_exam_turn()` (with fractional scoring and marks_rationale). `_handle_explanation_phase()` for explanation lifecycle. `_generate_pixi_code()` for visual explanation rendering. Exam feedback builder. Separate welcome generators per mode returning `(message, audio_text)` tuples with language-aware prompts. `generate_tutor_welcome()` (delegates to master tutor for card-aware welcome). `generate_bridge_turn()` (post-card bridge with state updates). Post-completion response generator. TurnResult includes `question_format`. |

### Models (`tutor/models/`)

| File | Purpose |
|------|---------|
| `session_state.py` | SessionState, CardPhaseState (pre-computed explanation card tracking), ExplanationPhase, Question, Misconception, SessionSummary, ExamQuestion (with score, marks_rationale), ExamFeedback (with float score), create_session() |
| `study_plan.py` | Topic, TopicGuidelines, StudyPlan, StudyPlanStep (v1 explanation sub-plan fields: approach, building_blocks, analogy, min_turns; v2 session plan fields: description, card_references, misconceptions_to_probe, success_criteria, difficulty, personalization_hint). Step types: v1 `explain`/`check`/`practice`, v2 `check_understanding`/`guided_practice`/`independent_practice`/`extend` |
| `messages.py` | Message (with audio_text), StudentContext (with text/audio language prefs, tutor_brief, personality_json, attention_span), WebSocket DTOs (ClientMessage, ServerMessage with audio_text and token type, SessionStateDTO), Card Phase DTOs (ExplanationCardDTO, CardActionRequest, CardPhaseDTO), factory functions (`create_token_message`, `create_typing_indicator`, etc.) |
| `agent_logs.py` | AgentLogEntry, AgentLogStore (in-memory, thread-safe) |

### Prompts (`tutor/prompts/`)

| File | Purpose |
|------|---------|
| `master_tutor_prompts.py` | System prompt (study plan + guidelines + 15 rules + personalization + language instructions), turn prompt (with explanation context, feedback notices), welcome prompt (MASTER_TUTOR_WELCOME_PROMPT, card-aware), bridge prompt (MASTER_TUTOR_BRIDGE_PROMPT, post-card transition). Used for teach_me and exam modes. |
| `clarify_doubts_prompts.py` | System and turn prompts for Clarify Doubts mode. **Actively wired** — clarify mode uses these via `MasterTutorAgent._build_system_prompt()` and `_build_clarify_turn_prompt()`. Direct answer rules, session closure rules, concept tracking. |
| `exam_prompts.py` | Exam question generation prompt (actively used by ExamService, includes personalization section) and evaluation prompts (**evaluation prompts defined but not yet wired** — exam eval uses master tutor prompts with exam context injected). |
| `orchestrator_prompts.py` | Welcome message (Teach Me) and session summary prompts |
| `templates.py` | PromptTemplate class, SAFETY_TEMPLATE, format helpers |
| `language_utils.py` | `get_response_language_instruction()` and `get_audio_language_instruction()` — generate prompt instructions for text/audio language based on student preferences (en/hi/hinglish) |

### Utils (`tutor/utils/`)

| File | Purpose |
|------|---------|
| `schema_utils.py` | get_strict_schema(), validate_agent_output(), parse_json_safely(), extract_json_from_text() |
| `prompt_utils.py` | format_conversation_history(max_turns default=5, overridden to 10 by master tutor) |
| `state_utils.py` | update_mastery_estimate(), calculate_overall_mastery(), should_advance_step(), get_mastery_level(), merge_misconceptions() |

### Services & API

| File | Purpose |
|------|---------|
| `tutor/services/session_service.py` | Session creation (all modes, with personalized plan generation, duplicate exam guard, and card phase initialization with tutor welcome), step processing (with card phase guard), pause/resume, end clarify, end exam, card phase actions (complete_card_phase with clear/explain_differently, variant switching, precomputed summary building, v2 session plan generation via `_generate_v2_session_plan()`, bridge turn generation), mid-session feedback (process_feedback with continue/restart), summary, CAS persistence |
| `tutor/services/exam_service.py` | Exam question generation via LLM with retry and personalization. ExamGenerationError (LearnLikeMagicException subclass) |
| `tutor/services/pixi_code_generator.py` | PixiCodeGenerator: translates natural language visual descriptions into executable Pixi.js v8 code via LLM (uses the tutor's configured model). Gated by `show_visuals_in_tutor_flow` feature flag. Used by the orchestrator for `visual_explanation` rendering. Canvas 500x350. Returns empty string on failure (never crashes the turn). |
| `tutor/services/topic_adapter.py` | DB guideline + study plan → Topic model. `convert_guideline_to_topic()` for session creation. `convert_session_plan_to_study_plan()` for v2 plan conversion at card completion. Detects v2 plans via `plan_version` metadata. |
| `tutor/services/report_card_service.py` | Report card aggregation, topic progress |
| `tutor/api/sessions.py` | REST + WebSocket + agent logs endpoints, session ownership checks, end-clarify endpoint, card-action endpoint, feedback endpoint, exam-review endpoint, guideline sessions endpoint |
| `tutor/api/transcription.py` | Audio transcription endpoint (OpenAI Whisper) |
| `tutor/api/tts.py` | Text-to-speech endpoint (Google Cloud TTS, Hindi/English/Hinglish voices) |
| `tutor/api/curriculum.py` | Curriculum discovery endpoints |
| `shared/repositories/explanation_repository.py` | ExplanationRepository: CRUD for `topic_explanations` table (pre-computed explanation variants). Read by session service during card phase, written by the ingestion pipeline. Methods: `get_by_guideline_id()`, `get_variant()`, `upsert()`, `has_explanations()`, `parse_cards()`. |
| `tutor/exceptions.py` | Custom exception hierarchy (TutorAgentError, LLMError, AgentError, SessionError, StateError, PromptError, ConfigurationError) |
| `shared/services/llm_service.py` | LLM wrapper (OpenAI Responses API, Chat Completions, Gemini, Anthropic) |
| `shared/services/anthropic_adapter.py` | Claude API adapter (tool_use for structured output, thinking budgets) |
| `shared/services/llm_config_service.py` | DB-backed LLM config: component_key → provider + model_id |
| `shared/services/feature_flag_service.py` | DB-backed feature flags: flag_name → enabled boolean (used for `show_visuals_in_tutor_flow` gate) |
