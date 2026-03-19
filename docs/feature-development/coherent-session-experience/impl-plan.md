# Tech Implementation Plan: Coherent Teach Me Session

**Date:** 2026-03-19
**Status:** Draft
**PRD:** `docs/feature-development/coherent-session-experience/plan.md`

---

## 1. Overview

Make the master tutor the single voice of the entire Teach Me session — from welcome through wrap-up. Replace all hardcoded messages with master-tutor-generated ones, enrich the explanation summary so the tutor can reference card content meaningfully, fix structural bugs (non-leading explain steps, duplicate welcome, card resume), and add missing UX (progress frame, farewell before summary).

No new tables. One new WebSocket message type (`card_navigate`). Changes touch 9 backend files and 1 frontend file.

---

## 2. Architecture Changes

### Before
```
Session Creation → hardcoded welcome → cards → hardcoded transition → master tutor takes over
                   ^^^^^^^^^^^^^^^^^^^          ^^^^^^^^^^^^^^^^^^^^
                   separate prompt               separate string
```

### After
```
Session Creation → master tutor welcome → cards → master tutor bridge → master tutor continues
                   ^^^^^^^^^^^^^^^^^^^^           ^^^^^^^^^^^^^^^^^^^
                   same brain                     same brain
```

### Modified modules
- `tutor/agents/base_agent.py` — extract `_execute_with_prompt()` helper from `execute()`
- `tutor/agents/master_tutor.py` — add welcome + bridge generation methods
- `tutor/prompts/master_tutor_prompts.py` — add welcome + bridge prompt templates
- `tutor/orchestration/orchestrator.py` — add `generate_tutor_welcome()`, `generate_bridge_turn()`
- `tutor/services/session_service.py` — wire master tutor for welcome + bridge + fallback
- `tutor/models/session_state.py` — add `card_covered_concepts` field
- `tutor/api/sessions.py` — fix duplicate welcome guard, add `card_navigate` WS message
- `book_ingestion_v2/services/explanation_generator_service.py` — add `teaching_notes` to generation
- `book_ingestion_v2/prompts/explanation_generation.txt` — update output schema
- `llm-frontend/src/pages/ChatSession.tsx` — welcome slide, bridge handling, farewell, progress frame, card resume

---

## 3. Database Changes

No schema changes. `summary_json` is JSONB — adding `teaching_notes` key is additive. Existing rows without `teaching_notes` handled via `.get('teaching_notes', '')` fallback.

To populate `teaching_notes` on existing data: re-run explanation generation for all topics (admin endpoint already supports `force=True`).

---

## 4. Backend Changes

### 4.1 Explanation Generator — Add `teaching_notes`

**File:** `book_ingestion_v2/services/explanation_generator_service.py`

Add `teaching_notes` field to `ExplanationSummaryOutput`:
```python
class ExplanationSummaryOutput(BaseModel):
    key_analogies: list[str] = Field(default_factory=list)
    key_examples: list[str] = Field(default_factory=list)
    teaching_notes: str = Field(default="", description="2-3 sentence narrative: what was explained, how, key conceptual progression")
```

Update `_build_summary()`:
```python
def _build_summary(self, gen_output, variant_config) -> dict:
    return {
        "card_titles": [c.title for c in gen_output.cards],
        "key_analogies": gen_output.summary.key_analogies,
        "key_examples": gen_output.summary.key_examples,
        "approach_label": variant_config["label"],
        "teaching_notes": gen_output.summary.teaching_notes,
    }
```

Update `_generate_cards()` output schema in prompt to include `teaching_notes`:
```json
"summary": {
    "key_analogies": ["analogy1"],
    "key_examples": ["example1"],
    "teaching_notes": "2-3 sentence narrative of what was explained and how"
}
```

Also update refinement prompt's output schema identically.

**Decision:** Generate `teaching_notes` in the same LLM call as cards (not a separate call). The LLM just wrote the cards — it can summarize them in the same output with near-zero additional cost.

**File:** `book_ingestion_v2/prompts/explanation_generation.txt`

Add to the end of the output format section:
```
The "teaching_notes" field should be a 2-3 sentence narrative summarizing: what conceptual progression you used, how your main analogy/example was applied, and what key insight the student should walk away with. Write it as if briefing another tutor who will continue the session: "Explained X using Y analogy — started with Z, built to W. Key insight: ..."
```

### 4.2 Base Agent — Extract Reusable LLM Call Helper

**File:** `tutor/agents/base_agent.py`

Extract the LLM call + parse + validate logic from `execute()` (lines 157-207) into a reusable method:

```python
async def _execute_with_prompt(self, prompt: str) -> BaseModel:
    """Execute LLM call with a pre-built prompt string. Reuses execute()'s
    logging, timeout handling, schema validation, and error handling."""
    start_time = time.time()
    self._last_prompt = prompt

    try:
        output_model = self.get_output_model()
        schema = get_strict_schema(output_model)

        loop = asyncio.get_event_loop()
        if self._use_fast_model:
            result = await loop.run_in_executor(
                None,
                lambda: self.llm.call_fast(prompt=prompt, json_mode=True),
            )
        else:
            result = await loop.run_in_executor(
                None,
                lambda: self.llm.call(
                    prompt=prompt,
                    reasoning_effort=self._reasoning_effort,
                    json_schema=schema,
                    schema_name=output_model.__name__,
                ),
            )

        output_text = result.get("output_text", "{}")
        try:
            parsed = json.loads(output_text)
        except (json.JSONDecodeError, TypeError):
            parsed = {}

        validated = validate_agent_output(
            output=parsed, model=output_model, agent_name=self.agent_name,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(json.dumps({
            "agent": self.agent_name, "event": "completed",
            "duration_ms": duration_ms,
        }))

        return validated

    except asyncio.TimeoutError:
        raise AgentTimeoutError(self.agent_name, self.timeout_seconds)
    except AgentError:
        raise
    except Exception as e:
        raise AgentExecutionError(self.agent_name, str(e)) from e
```

Then refactor `execute()` to call it:
```python
async def execute(self, context: AgentContext) -> BaseModel:
    logger.info(json.dumps({
        "agent": self.agent_name, "event": "started",
        "turn_id": context.turn_id, "current_step": context.current_step,
    }))
    prompt = self.build_prompt(context)
    return await self._execute_with_prompt(prompt)
```

**Decision:** This gives welcome/bridge methods access to the full BaseAgent machinery (structured output parsing, schema validation, logging, timeout, error handling) without needing a fake AgentContext. `execute()` behavior is unchanged — it just delegates to the new helper.

### 4.3 Master Tutor Agent — Welcome + Bridge Methods

**File:** `tutor/agents/master_tutor.py`

Add two new methods that build purpose-specific prompts and delegate to `_execute_with_prompt()`:

```python
async def generate_welcome(self, session: SessionState) -> TutorTurnOutput:
    """Generate session opening via master tutor with full context."""
    system_prompt = self._build_system_prompt(session)
    welcome_prompt = self._build_welcome_prompt(session)
    combined = f"{system_prompt}\n\n---\n\n{welcome_prompt}"
    output = await self._execute_with_prompt(combined)
    # Sanitize: zero out dangerous fields to prevent state corruption
    output.session_complete = False
    output.advance_to_step = None
    output.mastery_updates = []
    return output

async def generate_bridge(self, session: SessionState, bridge_type: str) -> TutorTurnOutput:
    """Generate post-card bridge. bridge_type: 'understood' | 'confused'."""
    system_prompt = self._build_system_prompt(session)
    bridge_prompt = self._build_bridge_prompt(session, bridge_type)
    combined = f"{system_prompt}\n\n---\n\n{bridge_prompt}"
    output = await self._execute_with_prompt(combined)
    # Sanitize: bridge can set question_asked/explanation_phase but NOT end session or advance
    output.session_complete = False
    output.advance_to_step = None
    output.mastery_updates = []
    return output
```

**`_build_welcome_prompt()`** — conditionals in Python, `{variable}` syntax in template:
```python
def _build_welcome_prompt(self, session: SessionState) -> str:
    has_cards = session.card_phase is not None
    student_name = getattr(session.student_context, 'student_name', None)

    if has_cards:
        card_framing = (
            "After your greeting, the student will read explanation cards about the topic. "
            "Frame the session: mention you've prepared some cards, they should read through "
            "them, and then you'll check understanding and practice together."
        )
    else:
        card_framing = "After your greeting, you'll start explaining the topic interactively."

    name_instruction = f"Address them by name ({student_name})." if student_name else ""

    return MASTER_TUTOR_WELCOME_PROMPT.render(
        card_framing=card_framing,
        name_instruction=name_instruction,
    )
```

**`_build_bridge_prompt()`** — conditionals in Python:
```python
def _build_bridge_prompt(self, session: SessionState, bridge_type: str) -> str:
    teaching_notes = session.precomputed_explanation_summary or ""

    if bridge_type == "understood":
        context_block = (
            "The student just finished reading explanation cards and indicated they understand."
        )
        if teaching_notes:
            instruction = (
                "Reference something SPECIFIC from the cards — a particular analogy, example, "
                "or concept. Ask the student to explain it back in their own words. 2-3 sentences. "
                "Warm, conversational. Frame as 'let's see what stuck' not a test.\n"
                "Set question_asked and expected_answer for what you're asking."
            )
        else:
            instruction = (
                "Ask the student what they found most interesting or what stood out from the cards. "
                "Then ask them to explain the main idea in their own words. 2-3 sentences.\n"
                "Set question_asked and expected_answer for what you're asking."
            )
    else:  # confused
        context_block = (
            "The student read all available explanation card variants but is still confused."
        )
        instruction = (
            "DO NOT re-greet them. Start with empathy ('No worries, let's talk it through'). "
            "Begin a fresh explanation using a DIFFERENT approach than the cards used.\n"
            "Set explanation_phase_update='opening' to start fresh explanation."
        )

    notes_section = f"### What the cards covered\n{teaching_notes}" if teaching_notes else ""

    return MASTER_TUTOR_BRIDGE_PROMPT.render(
        context_block=context_block,
        notes_section=notes_section,
        instruction=instruction,
    )
```

**Decision:** Reuse `_build_system_prompt()` for welcome/bridge. The system prompt has full context (student profile, topic, study plan, precomputed summary). Welcome/bridge only differ in the turn prompt. This avoids maintaining separate system prompts.

**Decision:** Sanitize output after LLM call — zero out `session_complete`, `advance_to_step`, `mastery_updates` for welcome/bridge. LLMs ignore "set to null" instructions, and a hallucinated `session_complete=True` would end the session right after cards. Bridge is allowed to set `question_asked` (for "understood") and `explanation_phase_update` (for "confused") since those are intentional.

### 4.4 Prompt Templates

**File:** `tutor/prompts/master_tutor_prompts.py`

Add two templates using `{variable}` syntax (compatible with `PromptTemplate.render()`):

```python
MASTER_TUTOR_WELCOME_PROMPT = PromptTemplate(
    """## Session Opening

This is the very first message of the session. The student hasn't spoken yet.

{card_framing}

Generate a warm greeting that:
1. {name_instruction} Builds curiosity about the topic — connect it to their world in 1 sentence.
2. Briefly frames what's coming in the session.
3. 2-3 sentences max. No questions (student can't respond yet).

Set all state fields to null/default — no mastery updates, no questions, no phase updates.
""",
    name="master_tutor_welcome",
)


MASTER_TUTOR_BRIDGE_PROMPT = PromptTemplate(
    """## Post-Card Bridge

{context_block}

{notes_section}

{instruction}
""",
    name="master_tutor_bridge",
)
```

**Decision:** All conditional logic lives in `_build_welcome_prompt()` and `_build_bridge_prompt()` (Python), not in templates. Templates are simple `{variable}` interpolation. This avoids the Jinja2 vs str.format() incompatibility.

### 4.5 Orchestrator — Wire Welcome + Bridge

**File:** `tutor/orchestration/orchestrator.py`

Add two new methods:

```python
async def generate_tutor_welcome(self, session: SessionState) -> tuple[str, Optional[str]]:
    """Generate welcome via master tutor. Falls back to simple message on failure."""
    try:
        self.master_tutor.set_session(session)
        output = await self.master_tutor.generate_welcome(session)
        return output.response, output.audio_text
    except Exception as e:
        logger.warning(f"Master tutor welcome failed, using fallback: {e}")
        topic = session.topic.topic_name if session.topic else "this topic"
        fallback = f"Let's learn about {topic}! I'll walk you through it, and then we can talk about any questions."
        return fallback, fallback

async def generate_bridge_turn(self, session: SessionState, bridge_type: str) -> TurnResult:
    """Generate post-card bridge via master tutor. Falls back on failure."""
    try:
        self.master_tutor.set_session(session)
        output = await self.master_tutor.generate_bridge(session, bridge_type)

        # Apply whitelisted state updates (question tracking, explanation phase — NOT session_complete/advance)
        state_changed = self._apply_state_updates(session, output)

        from tutor.models.messages import create_teacher_message
        session.add_message(create_teacher_message(output.response, audio_text=output.audio_text))
        session.session_summary.turn_timeline.append(output.turn_summary)

        return TurnResult(
            response=output.response,
            audio_text=output.audio_text,
            intent=output.intent,
            state_changed=state_changed,
        )
    except Exception as e:
        logger.warning(f"Master tutor bridge failed, using fallback: {e}")
        if bridge_type == "understood":
            fallback = "Great! Now let's make sure you've got it. Can you tell me in your own words what you just learned?"
        else:
            fallback = "No worries — let me try explaining this a different way."

        from tutor.models.messages import create_teacher_message
        session.add_message(create_teacher_message(fallback, audio_text=fallback))

        return TurnResult(response=fallback, audio_text=fallback, intent="continuation", state_changed=False)
```

**Decision:** Both methods wrap LLM calls in try/except with hardcoded fallbacks. Session creation and card-action must never fail because of an LLM error. The fallbacks are simple but functional — student never sees an error.

**Decision:** `generate_bridge_turn()` applies state updates via `_apply_state_updates()`. The output is already sanitized in `generate_bridge()` (session_complete, advance_to_step, mastery_updates zeroed out), so only safe fields (question_asked, explanation_phase_update) are applied.

### 4.6 Session Service — Replace Hardcoded Messages

**File:** `tutor/services/session_service.py`

#### Change 1: `create_new_session()` — Master tutor welcome for card sessions

Replace the card-phase branch (lines 138-171). Parallelize welcome generation with card loading:

```python
if explanations and mode == "teach_me":
    first_variant = explanations[0]

    session.card_phase = CardPhaseState(
        guideline_id=request.goal.guideline_id,
        active=True,
        current_variant_key=first_variant.variant_key,
        current_card_idx=0,
        total_cards=len(first_variant.cards_json),
        variants_shown=[first_variant.variant_key],
        available_variant_keys=[e.variant_key for e in explanations],
    )

    # Master tutor generates welcome (was hardcoded)
    # Card data is already loaded — welcome LLM call is the only latency
    welcome, audio_text = asyncio.run(
        self.orchestrator.generate_tutor_welcome(session)
    )

    first_turn = {
        "message": welcome,
        "audio_text": audio_text,
        "hints": [],
        "step_idx": session.current_step,
        "explanation_cards": first_variant.cards_json,
        "session_phase": "card_phase",
        "card_phase_state": {
            "current_variant_key": first_variant.variant_key,
            "current_card_idx": 0,
            "total_cards": len(first_variant.cards_json),
            "available_variants": len(explanations),
        },
    }
```

**Latency note:** Card loading is a DB read (~50ms) that's already done by this point. The welcome LLM call (~2-3s) is the only added latency. This matches non-card sessions which already pay this cost via `generate_welcome_message()`. Frontend should show a loading state during session creation.

#### Change 2: `complete_card_phase()` — Master tutor bridge

Replace the `action == "clear"` branch (lines 854-872):

```python
if action == "clear":
    session.complete_card_phase()
    self._advance_past_explanation_steps(session)

    precomputed_summary = self._build_precomputed_summary(session)
    session.precomputed_explanation_summary = precomputed_summary

    # Populate card_covered_concepts for pacing directive
    session.card_covered_concepts = self._extract_card_covered_concepts(session)

    # Master tutor generates bridge (was hardcoded)
    bridge_result = asyncio.run(
        self.orchestrator.generate_bridge_turn(session, bridge_type="understood")
    )

    self._persist_session_state(session_id, session, expected_version)

    return {
        "action": "transition_to_interactive",
        "message": bridge_result.response,
        "audio_text": bridge_result.audio_text,
    }
```

Replace the fallback path (lines 884-903):

```python
else:
    # All variants exhausted — master tutor re-explains (was generate_welcome_message)
    precomputed_summary = self._build_precomputed_summary(session)
    session.precomputed_explanation_summary = precomputed_summary
    session.card_covered_concepts = self._extract_card_covered_concepts(session)

    session.complete_card_phase()
    self._init_dynamic_fallback(session)

    bridge_result = asyncio.run(
        self.orchestrator.generate_bridge_turn(session, bridge_type="confused")
    )

    self._persist_session_state(session_id, session, expected_version)

    return {
        "action": "fallback_dynamic",
        "message": bridge_result.response,
        "audio_text": bridge_result.audio_text,
    }
```

**Note on G3 correction:** The exhausted-variants path was NOT hardcoded — it called `generate_welcome_message()` which is a dynamic LLM call. However, that prompt is generic (no card context, no awareness student is confused). The replacement is still an improvement: master tutor has full context including teaching_notes and knows the student is confused.

#### Change 3: `_build_precomputed_summary()` — Use teaching_notes

```python
def _build_precomputed_summary(self, session: SessionState) -> str:
    if not session.card_phase:
        return ""

    explanation_repo = ExplanationRepository(self.db)
    summaries = []
    for variant_key in session.card_phase.variants_shown:
        explanation = explanation_repo.get_variant(
            session.card_phase.guideline_id, variant_key
        )
        if explanation and explanation.summary_json:
            s = explanation.summary_json
            # Prefer teaching_notes (richer), fallback to structured labels
            if s.get("teaching_notes"):
                summaries.append(
                    f"Variant '{s.get('approach_label', variant_key)}':\n"
                    f"{s['teaching_notes']}"
                )
            else:
                summaries.append(
                    f"Variant '{s.get('approach_label', variant_key)}': "
                    f"Topics covered: {', '.join(s.get('card_titles', []))}. "
                    f"Analogies used: {', '.join(s.get('key_analogies', []))}. "
                    f"Examples used: {', '.join(s.get('key_examples', []))}."
                )

    return "\n".join(summaries)
```

#### Change 4: Add `_extract_card_covered_concepts()` helper

```python
def _extract_card_covered_concepts(self, session: SessionState) -> set[str]:
    """Build set of concepts covered by cards, for pacing directive per-concept checks."""
    concepts = set()
    if not session.topic or not session.topic.study_plan:
        return concepts
    for step in session.topic.study_plan.steps:
        if step.type == "explain":
            concepts.add(step.concept)
    # Also add concepts that were skipped by _advance_past_explanation_steps
    concepts.update(session.concepts_covered_set)
    return concepts
```

### 4.7 Session State — Add card_covered_concepts

**File:** `tutor/models/session_state.py`

Add field to `SessionState`:
```python
card_covered_concepts: set[str] = set()  # concepts covered by pre-computed cards
```

This is populated during `complete_card_phase()` and persisted in `state_json`. Used by the pacing directive (§4.8) for per-concept checks.

### 4.8 Card-Aware Pacing for Non-Leading Explain Steps

**File:** `tutor/agents/master_tutor.py`

Modify `_compute_pacing_directive()` — add check after the `turn == 1` block and BEFORE the existing explain-step pacing block (line ~179):

```python
# Card-aware: if current step is explain and cards already covered THIS concept
current_step = session.current_step_data
if (current_step and current_step.type == "explain"
        and current_step.concept in session.card_covered_concepts):
    return (
        "PACING: QUICK-CHECK (cards covered this) — The student already read explanation "
        "cards covering '{concept}'. Do NOT re-explain from scratch. Ask a quick "
        "'what do you remember about {concept}?' check. If they remember, set "
        "explanation_phase_update='complete' and advance. If not, give a brief 2-3 sentence "
        "refresher using a different angle than the cards, then ask again."
    ).format(concept=current_step.concept)
```

**Decision:** Check against `card_covered_concepts` (per-concept set) not `precomputed_explanation_summary` (session-level string). This is precise: if cards only covered concept A, concept B still gets full explanation. In practice, cards cover the entire topic so all explain step concepts will be in this set, but the per-concept check is more robust.

### 4.9 WebSocket — Fix Duplicate Welcome + Card Navigate

**File:** `tutor/api/sessions.py`

**Fix duplicate welcome (line 721):**
```python
# Before:
if session.turn_count == 0 and not session.is_in_card_phase():

# After:
if not session.conversation_history and not session.is_in_card_phase():
```

**Add card_navigate message type** in the WebSocket message loop:

```python
if client_msg.type == "card_navigate":
    # Update server-side card position for resume support
    if session.is_in_card_phase() and session.card_phase:
        card_idx = client_msg.payload.get("card_idx", 0)
        session.card_phase.current_card_idx = card_idx
        ws_version, reloaded = _save_session_to_db(db, session_id, session, ws_version)
        if reloaded:
            session = reloaded
    continue
```

Also add `"card_navigate"` to the `ClientMessage` type union / validation.

---

## 5. Frontend Changes

### Modified: `ChatSession.tsx`

#### Change 1: Show welcome slide before cards

Modify `carouselSlides` useMemo (lines 143-194). When in `card_phase`, prepend the welcome message as the first slide:

```typescript
const carouselSlides = useMemo(() => {
  const slides: Slide[] = [];

  // Welcome slide — always first if we have a teacher message
  if (messages.length > 0 && messages[0].role === 'teacher') {
    slides.push({
      id: 'welcome',
      type: 'message',
      content: messages[0].content,
      audioText: messages[0].audioText,
    });
  }

  // Explanation cards (card phase)
  if (sessionPhase === 'card_phase' && explanationCards.length > 0) {
    explanationCards.forEach((card, i) => {
      slides.push({
        id: `card-${i}`,
        type: 'explanation',
        content: card.content,
        title: card.title,
        cardType: card.card_type,
        visual: card.visual,
        audioText: card.content,
      });
    });
  }

  // Interactive message slides (skip first teacher msg — already shown as welcome)
  if (sessionPhase === 'interactive') {
    let teacherIdx = 0;
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].role !== 'teacher') continue;
      teacherIdx++;
      if (teacherIdx === 1 && explanationCards.length > 0) continue; // skip welcome
      // ... rest of existing message slide logic
    }
  }

  // Streaming slide
  if (streamingText && sessionPhase === 'interactive') {
    slides.push({ id: 'streaming', type: 'message', content: streamingText });
  }

  return slides;
}, [messages, explanationCards, sessionPhase, streamingText]);
```

#### Change 2: Handle bridge turn from card-action (+ audio_text)

Modify `handleCardAction` (lines 907-946). Use `carouselSlides.length` for index:

```typescript
if (result.action === 'transition_to_interactive' || result.action === 'fallback_dynamic') {
  setSessionPhase('interactive');
  const bridgeMsg: Message = {
    role: 'teacher',
    content: result.message,
    audioText: result.audio_text || null,
  };
  setMessages(prev => [...prev, bridgeMsg]);

  // Derive index from carousel length (avoids fragile manual counting)
  // Note: setMessages is async, so we compute based on what carouselSlides WILL be
  // after the next render. For now, jump to last slide on next tick.
  requestAnimationFrame(() => {
    setCurrentSlideIdx(carouselSlides.length); // will be length-1 of new slides
  });

  localStorage.removeItem(`slide-pos-${sessionId}`);
  if (result.audio_text) {
    playTeacherAudio(result.audio_text, `bridge-${Date.now()}`);
  }
}
```

**Decision:** Use `carouselSlides.length` (derived from render state) instead of manual counting of messages + cards. If carousel construction changes, index math stays correct.

#### Change 3: Send card_navigate on swipe

In the swipe handler (handleFocusSwipeEnd), when in card phase, send position to server via WebSocket:

```typescript
// After updating currentSlideIdx:
if (sessionPhase === 'card_phase' && wsRef.current) {
  // Subtract 1 for welcome slide offset
  const cardIdx = Math.max(0, newIdx - 1);
  wsRef.current.send({ type: 'card_navigate', payload: { card_idx: cardIdx } });
}
```

#### Change 4: Show tutor's farewell before summary

Add state: `const [showSummary, setShowSummary] = useState(false);`

Replace the `isComplete` render condition (line 1063):

```typescript
{showSummary ? (
  <div className="summary-card" ...>
    {/* existing summary content — unchanged */}
  </div>
) : (
  <div className="chat-container" ...>
    {/* existing carousel JSX */}
    {isComplete && (
      <div style={{ textAlign: 'center', padding: '16px' }}>
        <button className="action-button primary" onClick={() => setShowSummary(true)}>
          View Session Summary
        </button>
      </div>
    )}
  </div>
)}
```

#### Change 5: TeachMe progress frame

Add state: `const [totalSteps, setTotalSteps] = useState(0);`

Populate from state update, firstTurn initialization, and replay.

Remove `sessionMode !== 'teach_me'` exclusion (line 1033). Add teach_me content:

```typescript
{sessionMode === 'teach_me' && totalSteps > 0 && (
  <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
    Step {stepIdx} of {totalSteps}
  </span>
)}
```

#### Change 6: Card resume from server state

Modify replay hydration. When card phase is active, use server position:

```typescript
if (state.card_phase?.active && state.card_phase.current_card_idx != null) {
  setCurrentSlideIdx(state.card_phase.current_card_idx + 1); // +1 for welcome slide
} else {
  const savedPos = localStorage.getItem(`slide-pos-${sessionId}`);
  if (savedPos) setCurrentSlideIdx(parseInt(savedPos, 10));
}
```

---

## 6. LLM Integration

### New prompts (via master tutor)

| Prompt | Purpose | Called From | Est. Tokens |
|--------|---------|-------------|-------------|
| Welcome | Session opening | `orchestrator.generate_tutor_welcome()` | ~500 input, ~100 output |
| Bridge (understood) | Post-card check | `orchestrator.generate_bridge_turn('understood')` | ~600 input, ~100 output |
| Bridge (confused) | Re-explanation start | `orchestrator.generate_bridge_turn('confused')` | ~600 input, ~150 output |

All three use the master tutor's full system prompt. The turn prompt is purpose-specific.

### Modified prompt (explanation generation)

`teaching_notes` field added to existing output schema. No additional LLM call.

---

## 7. Configuration & Environment

No new environment variables. No config changes. All changes use existing `tutor` LLM config component.

---

## 8. Implementation Order

| Step | What | Files | Depends On | Test |
|------|------|-------|------------|------|
| 1 | Add `teaching_notes` to explanation generator | `explanation_generator_service.py`, `explanation_generation.txt` | — | Generate explanations, verify `teaching_notes` in `summary_json` |
| 2 | Enrich `_build_precomputed_summary()` | `session_service.py` | Step 1 | Unit test: summary with/without teaching_notes |
| 3 | Add `card_covered_concepts` to SessionState | `session_state.py` | — | Field exists, serializes correctly |
| 4 | Extract `_execute_with_prompt()` in BaseAgent | `base_agent.py` | — | Existing `execute()` still works (refactor, no behavior change) |
| 5 | Add welcome/bridge prompt templates | `master_tutor_prompts.py` | — | Templates render without error |
| 6 | Add `generate_welcome()`, `generate_bridge()` to master tutor | `master_tutor.py` | Steps 4, 5 | Mock LLM, verify structured output + sanitized fields |
| 7 | Add `generate_tutor_welcome()`, `generate_bridge_turn()` to orchestrator | `orchestrator.py` | Step 6 | Mock master tutor, verify return shape + fallback on error |
| 8 | Wire welcome in `create_new_session()` | `session_service.py` | Step 7 | Create session with cards → LLM-generated welcome |
| 9 | Wire bridge in `complete_card_phase()` + card_covered_concepts | `session_service.py` | Steps 3, 7 | Card phase completion → LLM bridge + audio_text |
| 10 | Add card-aware pacing directive | `master_tutor.py` | Step 3 | Unit test: QUICK-CHECK when concept in card_covered_concepts |
| 11 | Fix duplicate welcome + add card_navigate WS message | `sessions.py` | — | WS connect → no double welcome; card swipe → server position updates |
| 12 | Frontend: welcome slide before cards | `ChatSession.tsx` | Step 8 | Session start → welcome slide → swipe → cards |
| 13 | Frontend: bridge handling + card_navigate | `ChatSession.tsx` | Steps 9, 11 | "I understand!" → bridge; swipe → server position |
| 14 | Frontend: farewell before summary | `ChatSession.tsx` | — | Session complete → see farewell → click "View Summary" |
| 15 | Frontend: teach_me progress frame | `ChatSession.tsx` | — | Teach_me → see "Step X of Y" |
| 16 | Frontend: card resume from server | `ChatSession.tsx` | Step 11 | Reload mid-cards → resume at server position |

**Order rationale:** Bottom-up: schema/models → agent infra → agent methods → orchestrator → service → frontend. Bug fixes (step 11) standalone. Frontend steps 14-16 independent.

---

## 9. Testing Plan

### Unit tests

| Test | Verifies | Key Mocks |
|------|----------|-----------|
| `test_teaching_notes_in_summary` | `_build_summary()` propagates `teaching_notes` | LLM response |
| `test_precomputed_summary_uses_teaching_notes` | Prefers `teaching_notes` over structured labels | ExplanationRepository |
| `test_precomputed_summary_fallback` | Falls back to structured labels when no `teaching_notes` | ExplanationRepository |
| `test_execute_with_prompt` | BaseAgent helper returns validated output, matches execute() behavior | LLM service |
| `test_master_tutor_welcome` | `generate_welcome()` returns response + audio_text, session_complete=False | LLM service |
| `test_master_tutor_bridge_understood` | Sets `question_asked`, session_complete=False | LLM service |
| `test_master_tutor_bridge_confused` | Sets `explanation_phase_update='opening'`, session_complete=False | LLM service |
| `test_welcome_fallback` | Orchestrator returns hardcoded welcome on LLM failure | LLM service (raises) |
| `test_bridge_fallback` | Orchestrator returns hardcoded bridge on LLM failure | LLM service (raises) |
| `test_card_aware_pacing_per_concept` | QUICK-CHECK when concept in `card_covered_concepts` | None |
| `test_pacing_no_quickcheck_uncovered_concept` | Normal explain pacing when concept NOT in `card_covered_concepts` | None |
| `test_duplicate_welcome_guard` | WS skips welcome when `conversation_history` has messages | DB session |
| `test_card_navigate_updates_server` | WS `card_navigate` updates `card_phase.current_card_idx` | DB session |

### Manual verification

1. **Welcome:** Start teach_me with cards → first slide is personalized welcome (name, topic, frames session)
2. **Cards:** Swipe through → same experience as before
3. **Bridge ("I understand!"):** Click → tutor references specific card content, asks to explain back
4. **Bridge (all variants):** Exhaust variants → tutor acknowledges, starts fresh explanation
5. **Non-leading explain:** Reach explain step after cards → tutor quick-checks, not full re-explanation
6. **Farewell:** Complete all steps → see tutor's closing → click "View Summary" → summary
7. **Progress:** During teach_me → see "Step X of Y"
8. **Card resume:** Read 5/10 cards, close browser → reopen → resume at correct card
9. **No duplicate welcome:** Non-card session → one welcome only
10. **LLM failure:** (dev test) Block LLM → session still creates with fallback welcome

---

## 10. Deployment Considerations

- **No migrations needed.** `summary_json` is JSONB — new keys are additive.
- **Backfill:** Re-run `POST /admin/v2/books/{id}/generate-explanations?force=true` after deploy. Fallback to structured labels until then.
- **Latency:** Card sessions gain ~2-3s for welcome LLM call (matches non-card sessions which already have this). Frontend shows loading state during session creation.
- **Rollback:** Revert session_service.py to restore hardcoded messages. Other changes are safe to keep.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Welcome/bridge LLM call fails | Low | High | try/except with hardcoded fallback. Session always created. |
| LLM hallucinates session_complete on bridge | Low | High | Sanitize: zero out session_complete, advance_to_step, mastery_updates before applying. |
| Welcome latency delays session start | Med | Med | Matches existing non-card path. Frontend loading state. |
| Bridge doesn't reference cards well (empty teaching_notes) | Med | Low | Prompt handles sparse notes: focuses on topic broadly. Fallback to structured labels. |
| Card-aware pacing fires for wrong concept | Low | Med | Per-concept check via `card_covered_concepts` set, not session-level string. |

---

## 12. Open Questions

None — all decisions made. Implementation can proceed.
