# Learning Session — Technical

Architecture, agents, orchestration, and APIs for the tutoring pipeline.

---

## Architecture

```
                         Session Creation (POST /sessions)
                                       │
                ┌──────────────────────┼──────────────────────┐
                v                      v                      v
       teach_me + baatcheet    teach_me + explain        clarify_doubts
       (DialoguePhaseState)    (CardPhaseState)         (chat-only)
       Welcome = first card    Welcome = first card     LLM-generated
                │                      │                      │
                v                      v                      v
       /card-progress         /card-progress              WS /ws/{id}
       (nav + complete)       (nav + complete)           + REST /step
                              /card-action                + /end-clarify
                              (clear|explain_differently)
                              /simplify-card
                │                      │                      │
                └──────────────────────┴──────────────────────┘
                                       │
                              session.is_complete
```

Three independent paths share the same `SessionState` model and DB table:

- **Teach Me / Baatcheet** — pre-scripted dialogue cards (`topic_dialogues`). Single carousel UI driven by `/card-progress`. No master-tutor LLM calls during the session.
- **Teach Me / Explain** — pre-computed explanation cards (`topic_explanations`). Same carousel UI plus per-card simplification (`/simplify-card`) and variant switching (`/card-action`). No structured chat phase after the cards — completion ends the session and surfaces a "Let's Practice" CTA.
- **Clarify Doubts** — student-led Q&A. Master tutor agent runs per turn; safety + translation in parallel; concepts discussed tracked. Completion is signaled by the student or the tutor's `intent="done"`.

The interactive teach_me chat (master tutor explaining concepts step-by-step) and the v2 post-card session plan are no longer wired into the live flow. Bridge-turn and v2-plan code paths in `master_tutor.py` / `session_service.py` are vestigial — kept for the legacy non-card teach_me path that the default 5-step study plan still falls back to when no cards exist (rare; production guidelines all carry cards/dialogues by ingestion contract).

For Let's Practice, see `docs/technical/practice-mode.md`.

---

## Session Modes & Submodes

Set at creation, persisted on `SessionState.mode` + `SessionState.teach_me_mode` and on the DB row.

| `mode` | `teach_me_mode` | Phase model | Carousel | Master tutor calls |
|--------|------------------|-------------|----------|--------------------|
| `teach_me` | `baatcheet` | `DialoguePhaseState` (cards from `topic_dialogues`) | yes | none in-session |
| `teach_me` | `explain` | `CardPhaseState` (variants from `topic_explanations`) | yes | only for `/simplify-card` |
| `clarify_doubts` | n/a | chat history + `concepts_discussed` | no | every turn |

`SessionMode = Literal["teach_me", "clarify_doubts"]`, `TeachMeMode = Literal["explain", "baatcheet"]`. A paused Baatcheet and a paused Explain session can coexist for the same (user, guideline) thanks to the `teach_me_mode` column being part of the lookup.

`SessionState.is_complete` (single source of truth) branches:
- clarify_doubts → `clarify_complete`
- refresher → `card_phase.completed`
- teach_me + baatcheet → `dialogue_phase.completed`
- teach_me + explain → `card_phase.completed`
- legacy fallback → `current_step > total_steps`

---

## Agent System

Used only for Clarify Doubts turns and per-card simplification. Card-based Teach Me sessions don't invoke these per turn.

| Agent | Model | Structured Output | Responsibility |
|-------|-------|-------------------|----------------|
| **Safety** | Fast model (DB-config) | `SafetyOutput` | Content moderation gate (Clarify only) |
| **Master Tutor** | Tutor model (DB-config) | `TutorTurnOutput` | Clarify Doubts answers; per-card simplification (`SimplifiedCardOutput`) |

Provider/model resolved at session/turn creation via `LLMConfigService.get_config("tutor")`. Supported providers: `openai`, `anthropic`, `anthropic-haiku`, `google`. Translation + welcome use a separate `fast_model` config.

### TutorTurnOutput Schema

```python
TutorTurnOutput {
    response: str
    audio_text: str            # Spoken companion (Roman script, no symbols)
    intent: str                # legacy teach_me: answer/answer_change/question/confusion/novel_strategy/off_topic/continuation
                               # clarify: question/followup/done/off_topic
    answer_correct: bool|None
    answer_score: float|None   # exam-mode partial credit (unused in current flow)
    marks_rationale: str|None
    misconceptions_detected: list[str]
    mastery_signal: str|None   # strong/adequate/needs_remediation
    advance_to_step: int|None
    mastery_updates: list[MasteryUpdate]  # tracks concepts discussed in clarify
    question_asked, expected_answer, question_concept: str|None
    question_format: QuestionFormat|None
    explanation_phase_update: str|None    # vestigial — set during legacy explain steps only
    explanation_building_blocks_covered: list[str]
    student_shows_understanding, student_shows_prior_knowledge: bool|None
    session_complete: bool
    visual_explanation: VisualExplanation|None
    turn_summary: str
    reasoning: str
}
```

`QuestionFormat`: `fill_in_the_blank | single_select | multi_select | acknowledge` with `sentence_template` + `blanks` or `options`. `VisualExplanation`: `visual_prompt` + `output_type` (`image`/`animation`) + `title` + `narration`.

### SimplifiedCardOutput

`{ card_type, title, lines: [{display, audio}], visual_prompt }`. Per-line display+audio pairs power line-by-line typewriter sync. Flat `content` and `audio_text` are derived by joining lines.

---

## Orchestration

### Card-Based Teach Me (Explain + Baatcheet)

No `process_turn` involvement. The student's interactions with the carousel hit REST endpoints directly:

- `POST /sessions/{id}/card-progress` — debounced on every fwd/back nav. Updates `card_phase.current_card_idx` or `dialogue_phase.current_card_idx`. Optional `mark_complete=true` finalizes the phase via `_finalize_explain_session()` (Explain) or `_finalize_baatcheet_session()` (Baatcheet). Optional `check_in_events` payload appends per-check-in struggle data (wrong counts, confused pairs, auto-revealed items) to `card_phase.check_in_struggles` / `dialogue_phase.check_in_struggles`. Single endpoint covers both phases via `phase` field. Returns `{session_id, phase, card_idx, is_complete}` plus `{coverage, concepts_covered, guideline_id}` when completing.
- `POST /sessions/{id}/card-action` (Explain only) — `clear` invokes `_finalize_teach_me_session()` (sets `card_phase.completed=True`, builds `precomputed_explanation_summary` from variants + confusion + check-in struggles, populates `concepts_covered_set` from card concepts/titles, returns `{action: "teach_me_complete", message, audio_text, is_complete: true, coverage, concepts_covered, guideline_id}`); `explain_differently` switches to the next unseen variant via `_switch_variant_internal()` (resets `current_card_idx`, appends to `variants_shown`, reloads remedial cards from `student_topic_cards`). When all variants exhausted, also finalizes with a softer message ("We've looked at this from a few angles. Let's practice to see what stuck!").
- `POST /sessions/{id}/simplify-card` (Explain only) — generates a simplified version of a specific card. Loads original base card (always — never a previous simplification, prevents recursive stacking), passes previous attempts as context, calls `MasterTutorAgent.generate_simplified_card()` with `SIMPLIFY_CARD_PROMPT`. Tracks a `ConfusionEvent` per card and persists the simplification to `student_topic_cards` for cross-session persistence. Blocked for refresher topics (HTTP 400). Frontend submits `{card_idx, reason="simplify"}` — `reason` is currently a single unified approach (legacy `REASON_MAP` removed).

For refresher topics, `card-action: clear` short-circuits with `{action: "session_complete", message: "You've refreshed the basics..."}` — no precomputed summary, no concept extraction beyond the card phase.

`POST /sessions/{id}/step` rejects calls during card_phase OR dialogue_phase with HTTP 400 (`CardPhaseError`).

### Baatcheet Specifics

`SessionService.create_new_session` branches on `teach_me_mode == "baatcheet"`:
- Loads `DialogueRepository.get_by_guideline_id(guideline_id)`. Raises `BaatcheetUnavailableError` (HTTP 409) when no row exists.
- Initializes `DialoguePhaseState` (no variants).
- Welcome = first card's display lines (joined). Audio = first card's audio lines (joined).
- Returns `first_turn` with `session_phase: "dialogue_phase"`, `dialogue_cards` (full deck), `personalization` (`student_name` / `topic_name` for `{placeholder}` substitution at TTS time), and `dialogue_phase_state`.
- No master tutor calls. No safety calls.
- `_finalize_baatcheet_session()` (called when summary card hits `mark_complete=true`) marks `dialogue_phase.completed=True`, clears `is_paused`, and adds every study-plan concept token to `concepts_covered_set` + `card_covered_concepts` (token-level so coverage % is correctly computed; previous title-based path contributed zero coverage).

Refresher topics force `teach_me_mode="explain"` even if Baatcheet was requested.

### Clarify Doubts Turn Flow

`TeacherOrchestrator.process_turn(session, student_message)`:

1. **Post-completion check** — if `is_complete` and `mode=="clarify_doubts"`, OR `is_complete` and (extension disabled or extension_turns > 10), run safety + translation in parallel, then call `_process_post_completion()` (LLM-generated context-aware reply, plain text).
2. **Translation + Safety (parallel)** — `_translate_to_english()` (fast model via `llm.call_fast`, `translation.txt` prompt) + `SafetyAgent.execute()` via `asyncio.gather`. Translation skips empty / pure-number input.
3. **Increment turn**, add translated student message to history.
4. **Safety gate** — unsafe → return guidance.
5. **`_process_clarify_turn()`** — runs `MasterTutorAgent` with `CLARIFY_DOUBTS_SYSTEM_PROMPT` + `CLARIFY_DOUBTS_TURN_PROMPT`. Tracks concepts via `mastery_updates` (added to `concepts_discussed` and `concepts_covered_set`). Marks `clarify_complete=True` when `intent="done"` or `session_complete=True`.
6. **Add response** + audio_text to history.
7. **Optional visual generation** — if `visual_explanation` present and `show_visuals_in_tutor_flow` flag enabled (passed to orchestrator as `visuals_enabled`), generate Pixi.js code via `PixiCodeGenerator`. Failures logged and skipped (never raise).
8. **Return TurnResult**.

`process_turn_stream()` falls back to non-streaming for clarify_doubts (no token-level streaming for Q&A).

The teach_me streaming path (`process_turn_stream` for `teach_me`) is reachable only via the WebSocket endpoint when a session has no card_phase/dialogue_phase — currently dead code in production but still supported for the legacy fallback.

---

## Prompt System

### Master Tutor System Prompt (16 rules, 0-15)

Defined in `master_tutor_prompts.py` `MASTER_TUTOR_SYSTEM_PROMPT`. Used for clarify_doubts (via `_build_system_prompt()` branch) and per-card simplification.

Contents:
- Student profile (grade, language level, preferred examples).
- Personalization block: `tutor_brief` (rich personality prose) when set, else basic name/age/about_me fallback.
- `prior_topics_context_section` — when `TopicGuidelines.prior_topics_context` is set.
- `precomputed_explanation_summary_section` — when `precomputed_explanation_summary` is set after card phase completion.
- Study plan (v1 inline format or v2 richer format with description/card_references/misconceptions/success_criteria).
- Topic guidelines (curriculum scope, common misconceptions).
- 16 teaching rules:
  - Rule 0 — radical simplicity (under 15 words/sentence, child vocabulary, Indian context, no "upgrading" vocabulary from cards).
  - Rule 1 — ASK don't EXPLAIN (cards already taught everything; tutor only tests, practices, extends; remedial re-explanation only after 3+ wrong on the same concept).
  - Rule 2 — advance when ready (explanation guard; honor harder-material requests; skip on demonstrated prior knowledge).
  - Rule 3 — track questions (`question_asked`, `expected_answer`, `question_concept`).
  - Rule 4 — guide discovery on wrong answers (1st: probe; 2nd: hint; 3rd+: explain warmly; strategy switch after 2 consecutive corrections; prerequisite gap detection after 3+ errors).
  - Rule 5 — never repeat (vary structure + question formats; reuse card analogies as shared vocabulary).
  - Rule 6 — detect false OKs strictly (no yes/no comprehension checks; rote echoes caught).
  - Rule 7 — match energy (correction warmth, self-correction acknowledgment, correct-but-informal handling, first-instinct-right validation).
  - Rule 8 — update mastery (~0.3 wrong, ~0.6 partial, ~0.8 correct, ~0.95 with reasoning).
  - Rule 9 — calibrated praise (1-sentence confirmation; drop reinforcement after 2+ correct).
  - Rule 10 — end naturally; respect goodbyes; set `session_complete=true`.
  - Rule 11 — no internal leaks; markdown formatting; colored emoji (🔴🟠🟡🟢🔵🟣🟤⚫⚪) for color illustrations.
  - Rule 12 — response/audio language instructions (from `language_utils.py`).
  - Rule 13 — explanation phase tracking (remedial re-explanation only).
  - Rule 14 — visual explanations strongly encouraged on every explanation turn; never on test questions with numeric answers.
  - Rule 15 — interactive question formats (always set `question_format`; vary formats; never null).

### Master Tutor Turn Prompt

`MASTER_TUTOR_TURN_PROMPT` includes current step info, explanation context (when on legacy explain step), mastery estimates, misconceptions (with recurring alerts), turn timeline (last 5), pacing directive, student style, awaiting-answer section (with attempt number and escalating strategy by `wrong_attempts`), feedback notices (`[FEEDBACK]` / `[FEEDBACK-RESTART]` markers), conversation history (last 10), and the student message.

### Clarify Doubts Prompts (`clarify_doubts_prompts.py`)

`CLARIFY_DOUBTS_SYSTEM_PROMPT` — direct answers (no Socratic), strict closure rules (respect "I'm done"), concept tracking against study-plan concepts, curriculum scope boundary, language instructions. Personalization block included.

`CLARIFY_DOUBTS_TURN_PROMPT` — concepts discussed so far, conversation history, student message, structured-output instructions (intent, mastery_updates, session_complete).

`MasterTutorAgent._build_system_prompt()` and `_build_turn_prompt()` detect `mode == "clarify_doubts"` and route to the clarify-specific renderers.

### Welcome / Bridge / Simplify Prompts

- `MASTER_TUTOR_WELCOME_PROMPT` — used by `MasterTutorAgent.generate_welcome()` for legacy non-card teach_me sessions. Card-based sessions don't use it (welcome = first card).
- `MASTER_TUTOR_BRIDGE_PROMPT` — vestigial. `generate_bridge()` supports three types (`understood`, `confused`, `card_stuck`) but no caller in the live path.
- `SIMPLIFY_CARD_PROMPT` — used by `MasterTutorAgent.generate_simplified_card()`. Returns structured `SimplifiedCardOutput` with per-line display+audio pairs. Includes a `previous_attempts_section` so the LLM avoids repeating prior simplifications.

### Pacing Directives (`_compute_pacing_directive`)

Used by clarify_doubts and by the legacy teach_me chat path. Branches on turn count, current step type (v1 explain/check/practice or v2 check_understanding/guided_practice/independent_practice/extend), explanation phase, mastery, and progress trend. Outputs include:

| Signal | Trigger |
|--------|---------|
| TURN 1 | First turn (with vs. without precomputed_explanation_summary) |
| CHECK UNDERSTANDING / GUIDED / INDEPENDENT / EXTEND | v2 step types |
| QUICK-CHECK (cards) | v1 explain step where concept is in `card_covered_concepts` |
| EXPLAIN (opening / explaining / summarize / check / done) | Explain step with phase lifecycle |
| ACCELERATE | avg_mastery >= 0.8 + improving (or 60%+ concepts >= 0.7 with avg >= 0.65 + improving) |
| EXTEND (post-plan) | Aced plan + is_complete |
| SIMPLIFY | (avg_mastery < 0.4 with real data) or trend == struggling |
| CONSOLIDATE | avg_mastery 0.4-0.65 + steady + 2+ wrong attempts on current question |
| STEADY | Default; appends attention-span warning at thresholds short=8 / medium=14 / long=20 turns |

### Student Style (`_compute_student_style`)

Analyzes avg words/message, emoji usage, question-asking. Detects disengagement (responses getting shorter over 4+ messages: last response < 40% of first AND <= 5 words). Adjusts response length: QUIET <=5 words → 2-3 sentences; Moderate → 3-5; Expressive → can elaborate.

---

## Session API

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create session (mode + teach_me_mode); returns first_turn with `session_phase` |
| `POST` | `/sessions/{id}/step` | Submit student answer (Clarify only; rejects card_phase/dialogue_phase) |
| `POST` | `/sessions/{id}/pause` | Pause a Teach Me session (sets `is_paused=True`) |
| `POST` | `/sessions/{id}/resume` | Resume a paused session (returns conversation history) |
| `POST` | `/sessions/{id}/end-clarify` | End a Clarify Doubts session (`clarify_complete=True`) |
| `POST` | `/sessions/{id}/card-progress` | Single endpoint for both `card_phase` and `dialogue_phase`: nav (`card_idx`), `mark_complete` flag, optional `check_in_events` |
| `POST` | `/sessions/{id}/card-action` | `clear` (end Teach Me, build summary, surface Practice CTA) or `explain_differently` (switch variant; finalize when exhausted). Optional `check_in_events` |
| `POST` | `/sessions/{id}/simplify-card` | Per-card simplification (Explain only; blocked on refresher) |
| `GET` | `/sessions/{id}/summary` | Performance summary |
| `GET` | `/sessions` | List sessions for current user |
| `GET` | `/sessions/history` | Paginated history (filterable by subject) |
| `GET` | `/sessions/stats` | Aggregated learning stats |
| `GET` | `/sessions/report-card` | Report card with coverage |
| `GET` | `/sessions/topic-progress` | Lightweight topic progress map |
| `GET` | `/sessions/resumable?guideline_id=X` | Find paused Teach Me session for a subtopic |
| `GET` | `/sessions/teach-me-options?guideline_id=X` | Aggregator for the Teach Me sub-chooser: availability + in-progress / completed pointers + Baatcheet stale flag for both submodes |
| `GET` | `/sessions/guideline/{id}` | List sessions for a guideline (filter by mode, completion) |
| `GET` | `/sessions/{id}/replay` | Full state JSON; includes `_replay_explanation_cards`, `_replay_dialogue_cards`, `_replay_dialogue_personalization`, and authoritative `is_complete` |
| `GET` | `/sessions/{id}` | Full session state (debug) |
| `GET` | `/sessions/{id}/agent-logs` | Agent execution logs |
| `POST` | `/transcribe` | Audio transcription via OpenAI Whisper |
| `POST` | `/text-to-speech` | TTS via Google Cloud TTS (Hindi/English/Hinglish voices) |

### WebSocket Endpoint

`WS /sessions/ws/{session_id}` — used by Clarify Doubts in the frontend and by the evaluation pipeline. Card-based Teach Me does NOT use the WebSocket — it uses REST endpoints only.

Auth via `?token=<jwt>` query param. For user-linked sessions, the token must belong to the session owner (validated via Cognito). Anonymous sessions allowed without token for backward compat.

**Connection flow:** auth check → accept connection → send initial `state_update` → if first turn (empty conversation_history) AND not in card phase, generate welcome via `generate_welcome_message()` → enter main loop. Baatcheet sessions seed the welcome on session creation, so this path is skipped for them.

**Client → server:** `{"type": "chat" | "get_state" | "card_navigate", "payload": {"message": "...", "card_idx": N}}`. `card_navigate` is preserved for backward compat but the canonical path is now REST `/card-progress`.

**Server → client:**
```
{"type": "typing", "payload": {}}
{"type": "token", "payload": {"message": "<chunk>"}}        # teach_me streaming only (legacy path)
{"type": "assistant", "payload": {"message": "...", "audio_text": "...", "visual_explanation": {...}, "question_format": {...}}}
{"type": "state_update", "payload": {"state": SessionStateDTO}}
{"type": "visual_update", "payload": {"visual_explanation": {...with pixi_code}}}
{"type": "error", "payload": {"error": "..."}}
```

`SessionStateDTO`: `session_id`, `current_step`, `total_steps`, `current_concept`, `progress_percentage`, `mastery_estimates`, `is_complete`, `mode`, `coverage`, `concepts_discussed`, `is_paused`. Note: no `teach_me_mode` field on the DTO — frontend reads it from the session creation response.

### Session Creation

```
POST /sessions
Body: {
  student: {id, grade, prefs: {style, lang}},
  goal: {topic, syllabus, learning_objectives, guideline_id},
  mode: "teach_me" | "clarify_doubts",
  teach_me_mode: "explain" | "baatcheet"   # only when mode == "teach_me"
}
```

Flow (`SessionService.create_new_session`):
1. Resolve mode + teach_me_mode (default `explain`).
2. Load guideline; raise 404 if missing.
3. Detect refresher (`guideline.metadata.is_refresher`); reject non-teach_me modes; force `teach_me_mode="explain"` if `baatcheet` was requested.
4. Build `StudentContext` from user profile (when authenticated): name, age, about_me, `tutor_brief` from `personality_repository`, `personality_json`, `attention_span` from `enrichment_repository`, text/audio language preferences. Falls back to request data otherwise.
5. Load study plan (clarify only — teach_me sessions don't need a study plan since cards/dialogues ARE the lesson). Personalized plan resolution: user+guideline → guideline-only fallback → on-the-fly generation via `StudyPlanGeneratorService` for clarify_doubts.
6. Convert via `topic_adapter.convert_guideline_to_topic()` → `Topic` model.
7. Create `SessionState`, set `session_id`, `is_refresher`, `teach_me_mode`.
8. **Branch by mode**:
   - `teach_me + baatcheet` → `DialogueRepository.get_by_guideline_id()`; raise `BaatcheetUnavailableError` (409) if missing; init `DialoguePhaseState`; welcome = first card lines; first_turn includes `dialogue_cards`, `dialogue_phase_state`, `personalization`, `teach_me_mode="baatcheet"`.
   - `teach_me + explain` → `ExplanationRepository.get_by_guideline_id()`; pick variant (preferred = student's last-used from `student_topic_cards_repository`, else first available); init `CardPhaseState`; pre-load saved simplifications from `student_topic_cards`; welcome = first card content; first_turn includes `explanation_cards`, `card_phase_state`, `session_phase="card_phase"`.
   - `clarify_doubts` → generate welcome via `orchestrator.generate_clarify_welcome()`; first_turn = chat-only.
9. Persist session to DB (state_version=1).
10. For clarify_doubts, attach past discussions (up to 5 most recent sessions for same user + guideline with non-empty concepts_discussed).
11. Return `{session_id, first_turn, mode, teach_me_mode}`.

Session ownership: user-linked sessions require the caller to be the owner. Anonymous sessions (user_id=None) allow access for backward compat.

---

## State Management

### SessionState

```python
class SessionState(BaseModel):
    session_id, created_at, updated_at, turn_count
    topic: Optional[Topic]
    mode: SessionMode                        # "teach_me" | "clarify_doubts"
    teach_me_mode: TeachMeMode               # "explain" | "baatcheet" (Teach Me submode)
    current_step: int
    mastery_estimates: dict[str, float]
    misconceptions: list[Misconception]
    last_question: Optional[Question]
    conversation_history: list[Message]      # sliding window (max 10)
    full_conversation_log: list[Message]
    session_summary: SessionSummary
    student_context: StudentContext
    pace_preference: str                     # slow/normal/fast
    allow_extension: bool                    # legacy chat extension flag
    is_paused: bool
    concepts_covered_set: set[str]
    # Phases — exactly one is active at a time
    card_phase: Optional[CardPhaseState]         # Explain submode
    dialogue_phase: Optional[DialoguePhaseState] # Baatcheet submode
    precomputed_explanation_summary: Optional[str]  # built at card_phase finalize
    card_covered_concepts: set[str]
    explanation_phases: dict[str, ExplanationPhase]
    current_explanation_concept: Optional[str]
    # Clarify state
    concepts_discussed: list[str]
    clarify_complete: bool
    is_refresher: bool
    # + off_topic_count, warning_count, safety_flags
```

`is_complete` is a computed property — see Modes table above.

### CardPhaseState (Explain)

```python
class CardPhaseState(BaseModel):
    guideline_id: str
    active: bool
    current_variant_key: str                 # e.g. "A"
    current_card_idx: int
    total_cards: int
    variants_shown: list[str]
    available_variant_keys: list[str]
    completed: bool
    remedial_cards: dict[int, list[RemedialCard]]   # {base_card_idx: [simplifications by depth]}
    confusion_events: list[ConfusionEvent]
    check_in_struggles: list[CheckInStruggleEvent]
```

`RemedialCard`: `card_id` (e.g. `"remedial_A_3_1"`), `source_card_idx`, `depth`, `card` dict (title/content/audio_text/card_type, plus optional `visual_explanation` with pixi_code).

`ConfusionEvent`: `base_card_idx`, `base_card_title`, `depth_reached`, `escalated`.

`CheckInStruggleEvent`: `card_idx` (1-based), `card_title`, `activity_type` (pick_one/true_false/fill_blank/match_pairs/sort_buckets/sequence/spot_the_error/odd_one_out/predict_then_reveal/swipe_classify/tap_to_eliminate), `wrong_count`, `hints_shown`, `confused_pairs` (`{left, right, wrong_count, wrong_picks}`), `auto_revealed`.

### DialoguePhaseState (Baatcheet)

```python
class DialoguePhaseState(BaseModel):
    guideline_id: str
    active: bool
    current_card_idx: int
    total_cards: int
    completed: bool
    last_visited_at: Optional[datetime]      # used for resume CTA
    check_in_struggles: list[CheckInStruggleEvent]
```

No variants, no remedial cards — Baatcheet is a single linear dialogue.

### StudentContext

```python
class StudentContext(BaseModel):
    grade, board, language_level
    preferred_examples: list[str]
    student_name, student_age, about_me
    text_language_preference: str            # "en" | "hi" | "hinglish"
    audio_language_preference: str
    tutor_brief: Optional[str]               # rich personality from enrichment
    personality_json: Optional[dict]
    attention_span: Optional[str]            # "short" | "medium" | "long"
```

When `tutor_brief` is set, it replaces basic name/age personalization in the system prompt.

### ExplanationPhase (legacy)

```python
class ExplanationPhase(BaseModel):
    concept, step_id
    phase: ExplanationPhaseName              # not_started/opening/explaining/informal_check/complete
    tutor_turns_in_phase: int
    building_blocks_covered: list[str]
    student_engaged: bool
    informal_check_passed: bool
    skip_reason: Optional[str]
```

Used only by the legacy non-card teach_me chat path. `_handle_explanation_phase()` manages lifecycle. `can_advance_past_explanation()` guards step advancement.

### Question Lifecycle (Clarify only)

```python
class Question(BaseModel):
    question_text, expected_answer, concept, rubric
    hints: list[str], hints_used: int
    wrong_attempts: int
    previous_student_answers: list[str]
    phase: str                                # asked → probe → hint → explain
```

Phase progression on wrong answer: 1st → probe; 2nd → hint; 3rd → explain (different approach); 4th+ → strategy change (prerequisite step-back). `_handle_question_lifecycle()` covers five cases (wrong on pending, correct, new question, replace pending, same-concept follow-up).

### Persistence and Concurrency

State is serialized JSON in `state_json`. All writes use compare-and-swap (CAS) via `state_version`:

- REST path (`_persist_session_state`): atomic `UPDATE ... WHERE state_version = expected_version`, raises `StaleStateError` on conflict.
- WebSocket path (`_save_session_to_db`): same CAS, returns `(new_version, None)` on success or `(db_version, reloaded_session)` on conflict. Caller adopts reloaded state and notifies the client.

Prevents concurrent REST calls (e.g., pause from one tab while chatting in another) from silently overwriting each other.

---

## Study Plan Integration

Card-based Teach Me sessions don't use a study plan at runtime — the cards/dialogue ARE the lesson. The study plan is only loaded for clarify_doubts and the legacy non-card teach_me path.

### Plan Versions

- **v1 (legacy):** types `explain`, `check`, `practice`. Step type inferred from title/description keywords or default pattern (explain, explain, check, explain, ..., practice). Explain steps carry `explanation_approach`, `explanation_building_blocks`, `explanation_analogy`, `min_explanation_turns`.
- **v2 (post-card):** types `check_understanding`, `guided_practice`, `independent_practice`, `extend`. Steps carry `description`, `card_references`, `misconceptions_to_probe`, `success_criteria`, `difficulty`, `personalization_hint`. Detected via `metadata.plan_version >= 2` in `plan_json`. Generated by `StudyPlanGeneratorService.generate_session_plan()` and converted by `topic_adapter.convert_session_plan_to_study_plan()`. Currently unreachable in the live flow (the post-card transition was removed) but the plan format and pacing directives remain.

`TopicGuidelines.prior_topics_context` (optional) — rendered as a "Prior Topics in This Chapter" section in the master tutor system prompt.

Plan resolution order at session creation (clarify only):
1. Personalized plan for user+guideline (`study_plans` table).
2. Any existing plan for the guideline (fallback).
3. For clarify_doubts with an authenticated user: generate on-the-fly via `StudyPlanGeneratorService`.
4. Default 5-step plan (`explain → explain → check → explain → practice`) if no plan exists at all (`topic_adapter._generate_default_plan`).

---

## LLM Calls

| Call | Model | Purpose | Output | Prompt Source |
|------|-------|---------|--------|---------------|
| Translation | Fast (DB) | Hinglish/Hindi → English (Clarify only); `llm.call_fast()` skipped on empty/pure-number input | JSON `{english}` | `tutor/prompts/translation.txt` |
| Safety | Fast (DB) | Content moderation gate (Clarify only) | `SafetyOutput` | `templates.py SAFETY_TEMPLATE` |
| Master Tutor (clarify) | Tutor (DB) | Doubt-clearing Q&A | `TutorTurnOutput` | `clarify_doubts_prompts.py` |
| Master Tutor (legacy teach_me) | Tutor (DB) | Structured chat lesson | `TutorTurnOutput` | `master_tutor_prompts.py` |
| Card Simplification | Tutor (DB) | Simplify a specific Explain card | `SimplifiedCardOutput` | `master_tutor_prompts.py SIMPLIFY_CARD_PROMPT` |
| Welcome (legacy teach_me) | Tutor (DB) | Welcome for non-card sessions | JSON `{response, audio_text}` | `orchestrator_prompts.py` |
| Welcome (Clarify) | Tutor (DB) | Welcome for Q&A | JSON | inline in `orchestrator.py` |
| Post-Completion | Tutor (DB) | Context-aware reply after session ends | Plain text | inline in `orchestrator.py` |
| Study Plan Gen | DB key `study_plan_generator` | Generate / regenerate personalized plan | Structured JSON | `StudyPlanGeneratorService` |
| Pixi Code Gen | Tutor (DB) | Generate Pixi.js v8 code from visual description | Plain JS | `pixi_code_generator.py` |

All non-fast calls share the `tutor` config key from `llm_config`. The Anthropic adapter maps structured output to tool_use and reasoning effort to thinking budgets.

Card-based Teach Me sessions make ZERO LLM calls during the session itself — the dialogue (Baatcheet) and explanation cards (Explain) are fully pre-computed during ingestion. The only in-session LLM call for Explain is per-card simplification, triggered by user tap.

---

## Transcription and TTS

**Transcription** — `POST /transcribe` (OpenAI Whisper):
- Accepts audio up to 25 MB (webm, ogg, mp4, mpeg, wav, flac).
- Returns `{text}`.
- Used in Clarify Doubts for voice input.

**Text-to-Speech** — `POST /text-to-speech` (Google Cloud TTS):
- Up to 5,000 chars; `language` param (`en`, `hi`, `hinglish`).
- Voices: `en-IN-Neural2-A` (English), `hi-IN-Neural2-D` (Hindi/Hinglish).
- Returns MP3.
- Used as fallback when card audio URLs are missing. Pre-built audio URLs (S3) on dialogue / explanation cards are the primary source.

Card audio playback uses pre-rendered MP3 URLs (populated by ingestion stages) when present; falls back to live `synthesizeSpeech` when absent. Personalized lines (containing `{student_name}` placeholders) are always synthesized live.

---

## Key Files

### Agents (`tutor/agents/`)

| File | Purpose |
|------|---------|
| `base_agent.py` | `BaseAgent` ABC: `execute()`, `build_prompt()`, LLM call with strict schema |
| `master_tutor.py` | `MasterTutorAgent`: `TutorTurnOutput` (with audio_text, answer_score/marks_rationale for exam mode, explanation phase fields, visual_explanation, question_format), `SimplifiedCardOutput` (per-line display+audio pairs), `QuestionFormat`/`BlankItem`/`OptionItem`, `VisualExplanation`. Methods: `generate_welcome()` (legacy non-card), `generate_bridge()` (vestigial), `generate_simplified_card()` (uses SIMPLIFY_CARD_PROMPT, returns flat content + per-line audio). Pacing/style computation (explanation-aware + attention span + v2 step types). Personalization block (tutor_brief or name/age fallback). Mode-specific prompt routing (clarify uses dedicated prompts) |
| `safety.py` | `SafetyAgent`: fast content moderation gate. Allow-list pre-filter (`_is_provably_safe`) for 1-2 char messages, pure math, known safe single words ("yes", "ok", "haan", "nahi", etc.). Fails safe on LLM error |

### Orchestration (`tutor/orchestration/`)

| File | Purpose |
|------|---------|
| `orchestrator.py` | `TeacherOrchestrator`: parallel translation + safety → mode router → master_tutor (clarify path) → state updates → optional visual generation. `process_turn()` (non-streaming) and `process_turn_stream()` (clarify falls back to non-streaming). `_translate_to_english()`. `_process_clarify_turn()` with clarify_complete handling. `_handle_explanation_phase()` for legacy explanation lifecycle. `_generate_pixi_code()` gated by `show_visuals_in_tutor_flow`. `generate_simplified_card()` (delegates to master tutor). `generate_welcome_message()` (legacy teach_me) and `generate_clarify_welcome()`. `generate_tutor_welcome()` and `generate_bridge_turn()` exist but are not called from the live path. Post-completion response generator |

### Models (`tutor/models/`)

| File | Purpose |
|------|---------|
| `session_state.py` | `SessionState` (with `mode`, `teach_me_mode`, `is_refresher`, `is_paused`); `CardPhaseState` (with `RemedialCard`, `ConfusionEvent`, `CheckInStruggleEvent`); `DialoguePhaseState` (Baatcheet sibling — single linear deck, no variants); `ExplanationPhase`, `Question`, `Misconception`, `SessionSummary`. `is_complete` property branches by mode/refresher/submode. Helpers: `is_in_card_phase()`, `is_in_dialogue_phase()`, `complete_card_phase()`, `complete_dialogue_phase()` |
| `study_plan.py` | `Topic`, `TopicGuidelines` (with `prior_topics_context`), `StudyPlan`, `StudyPlanStep`. v1 fields: `explanation_approach`, `explanation_building_blocks`, `explanation_analogy`, `min_explanation_turns`. v2 fields: `description`, `card_references`, `misconceptions_to_probe`, `success_criteria`, `difficulty`, `personalization_hint`. Step types: v1 explain/check/practice + v2 check_understanding/guided_practice/independent_practice/extend |
| `messages.py` | `Message` (with audio_text), `StudentContext` (with text/audio language prefs, tutor_brief, personality_json, attention_span). WebSocket DTOs: `ClientMessage` (chat/start_session/get_state/card_navigate), `ServerMessage` (assistant/state_update/error/typing/token), `SessionStateDTO`. Card Phase DTOs: `ExplanationLineDTO` (display/audio/audio_url), `ExplanationCardDTO` (with welcome/check_in card_types), `CardActionRequest` (with optional check_in_events), `CheckInEventDTO`, `CardPhaseDTO`, `SimplifyCardRequest` (`card_idx`, `reason`). Factory functions (`create_token_message`, `create_typing_indicator`, etc.) |
| `agent_logs.py` | `AgentLogEntry`, `AgentLogStore` (in-memory, thread-safe) |

### Prompts (`tutor/prompts/`)

| File | Purpose |
|------|---------|
| `master_tutor_prompts.py` | `MASTER_TUTOR_SYSTEM_PROMPT` (16 rules 0-15 — ASK don't EXPLAIN as Rule 1), `MASTER_TUTOR_TURN_PROMPT`, `MASTER_TUTOR_WELCOME_PROMPT` (legacy non-card welcome), `MASTER_TUTOR_BRIDGE_PROMPT` (vestigial — 3 bridge types), `SIMPLIFY_CARD_PROMPT` (per-card simplification, max 10 words/sentence, structured per-line output) |
| `clarify_doubts_prompts.py` | `CLARIFY_DOUBTS_SYSTEM_PROMPT`, `CLARIFY_DOUBTS_TURN_PROMPT`. Direct answers, strict closure rules, concept tracking |
| `orchestrator_prompts.py` | `WELCOME_MESSAGE_PROMPT` (legacy teach_me welcome) |
| `templates.py` | `PromptTemplate` class, `SAFETY_TEMPLATE`, format helpers |
| `language_utils.py` | `get_response_language_instruction()` and `get_audio_language_instruction()` for en/hi/hinglish |
| `translation.txt` | Hinglish/Hindi → English translation prompt |

### Utils (`tutor/utils/`)

| File | Purpose |
|------|---------|
| `schema_utils.py` | `get_strict_schema()`, `validate_agent_output()`, `parse_json_safely()`, `extract_json_from_text()` |
| `prompt_utils.py` | `format_conversation_history()` (max_turns default=5; master tutor overrides to 10) |
| `state_utils.py` | `update_mastery_estimate()`, `calculate_overall_mastery()`, `should_advance_step()`, `get_mastery_level()`, `merge_misconceptions()` |

### Services & API

| File | Purpose |
|------|---------|
| `tutor/services/session_service.py` | Session creation (3 paths: baatcheet branch, explain branch with card phase init + saved-simplifications pre-load, clarify branch). `record_card_progress()` (single endpoint for both phases — nav + `mark_complete` → `_finalize_explain_session`/`_finalize_baatcheet_session` + check_in_events). `process_step()` (rejects card_phase + dialogue_phase). `pause_session()`, `resume_session()`, `end_clarify_session()`. `complete_card_phase()` (clear → `_finalize_teach_me_session`; explain_differently → `_switch_variant_internal` or finalize when exhausted; refresher short-circuits with session_complete message). `simplify_card()` (RemedialCard/ConfusionEvent tracking, base-card-only input, previous attempts context, blocked for refresher, persists to `student_topic_cards`). `_finalize_explain_session()` (idempotent — flips `card_phase.completed=True`, clears `is_paused`). `_finalize_teach_me_session()` (calls `complete_card_phase`, builds `precomputed_explanation_summary`, populates `concepts_covered_set` + `card_covered_concepts`, returns Practice CTA payload). `_finalize_baatcheet_session()` (token-level coverage propagation). Vestigial: `_generate_v2_session_plan()` (no longer called) |
| `tutor/services/pixi_code_generator.py` | `PixiCodeGenerator`: NL visual description → Pixi.js v8 code via tutor model. Canvas 500x350. Gated by `show_visuals_in_tutor_flow`. Returns empty string on failure |
| `tutor/services/topic_adapter.py` | `convert_guideline_to_topic()` (refresher returns empty plan; otherwise `_convert_study_plan`). `convert_session_plan_to_study_plan()` for v2 plans. `_infer_step_type()` for v1 step type inference. `_generate_default_plan()` 5-step fallback |
| `tutor/services/report_card_service.py` | Report card aggregation, topic progress |
| `tutor/api/sessions.py` | REST + WebSocket + agent logs endpoints. Session ownership checks. `/teach-me-options` aggregator (availability + in-progress / completed pointers + Baatcheet stale flag). `/card-progress` (single endpoint for card_phase + dialogue_phase). `/replay` includes `_replay_explanation_cards`, `_replay_dialogue_cards`, `_replay_dialogue_personalization`, authoritative `is_complete`. WebSocket loop is for non-card sessions only |
| `tutor/api/transcription.py` | OpenAI Whisper endpoint |
| `tutor/api/tts.py` | Google Cloud TTS endpoint (Hindi/English/Hinglish voices) |
| `tutor/api/curriculum.py` | Curriculum discovery endpoints |
| `tutor/api/practice.py` | Practice mode endpoints (see `docs/technical/practice-mode.md`) |
| `shared/repositories/explanation_repository.py` | `ExplanationRepository`: CRUD for `topic_explanations` (Explain variants). `get_by_guideline_id()`, `get_variant()`, `upsert()`, `has_explanations()`, `parse_cards()` |
| `shared/repositories/dialogue_repository.py` | `DialogueRepository`: CRUD for `topic_dialogues` (Baatcheet dialogues). `get_by_guideline_id()`, `is_stale()` (compares variant A's content hash to dialogue's stored hash for the stale badge) |
| `shared/repositories/student_topic_cards_repository.py` | Per-student saved simplifications for cross-session persistence |
| `tutor/exceptions.py` | `TutorAgentError`, `LLMError`, `AgentError`, `SessionError`, `StateError`, `PromptError`, `ConfigurationError`, `CardPhaseError`, `InvalidCardActionError`, `SessionModeError`, `VariantNotFoundError` |
| `shared/services/llm_service.py` | LLM wrapper (OpenAI Responses API, Chat Completions, Gemini, Anthropic) |
| `shared/services/anthropic_adapter.py` | Claude API adapter (tool_use for structured output, thinking budgets) |
| `shared/services/llm_config_service.py` | DB-backed LLM config: component_key → provider + model_id |
| `shared/services/feature_flag_service.py` | DB-backed feature flags (`show_visuals_in_tutor_flow` gate for Pixi visual generation) |

### Frontend (`llm-frontend/src/`)

| File | Purpose |
|------|---------|
| `pages/TeachMeSubChooser.tsx` | Sub-chooser between mode selection and ChatSession for Teach Me. Two cards (Baatcheet recommended, Explain). Calls `/teach-me-options`. Routes to existing in-progress session when present |
| `pages/ChatSession.tsx` | Single page that renders all three flows: card_phase (Explain), dialogue_phase (Baatcheet via `BaatcheetViewer`), or interactive chat (Clarify). Drives `/card-progress` debounced posts. Shows Teach Me completion screen with concepts covered + Let's Practice CTA |
| `components/teach/BaatcheetViewer.tsx` | Baatcheet carousel with per-line MP3 + typewriter sync. Owns card index, audio playback, check-in dispatch, server progress posting |
| `components/CheckInDispatcher.tsx` | Dispatches per-card check-in activity by type |
| `components/ModeSelection.tsx` | Mode picker (Teach Me / Clarify Doubts / Practice). Shows resume CTA for in-progress teach_me sessions |
| `api.ts` | Typed wrappers: `createSession` (with `teach_me_mode`), `submitStep`, `pauseSession`, `resumeSession`, `endClarifySession`, `cardAction`, `simplifyCard`, `postCardProgress`, `getTeachMeOptions`, `getSessionReplay`, `getReportCard`, `getTopicProgress`, `getResumableSession`, `getGuidelineSessions`, `transcribeAudio`. WebSocket helpers for the chat loop |
