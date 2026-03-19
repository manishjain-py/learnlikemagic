# Tech Implementation Plan: Coherent Teach Me Session

**Date:** 2026-03-19
**Status:** Draft
**PRD:** `docs/feature-development/coherent-session-experience/plan.md`

---

## 1. Overview

Make the master tutor the single voice of the entire Teach Me session — from welcome through wrap-up. Replace all hardcoded messages with master-tutor-generated ones, enrich the explanation summary so the tutor can reference card content meaningfully, fix structural bugs (non-leading explain steps, duplicate welcome, card resume), and add missing UX (progress frame, farewell before summary).

No new tables. No new endpoints. Changes touch 8 backend files and 1 frontend file.

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
- `tutor/agents/master_tutor.py` — add welcome + bridge generation methods
- `tutor/prompts/master_tutor_prompts.py` — add welcome + bridge prompt templates
- `tutor/orchestration/orchestrator.py` — add `generate_tutor_welcome()`, `generate_bridge_turn()`
- `tutor/services/session_service.py` — wire master tutor for welcome + bridge + fallback
- `tutor/api/sessions.py` — fix duplicate welcome guard
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
    "teaching_notes": "2-3 sentence narrative of what was explained and how — what conceptual progression was used, how analogies were applied, what key insight was built"
}
```

Also update refinement prompt's output schema identically.

**Decision:** Generate `teaching_notes` in the same LLM call as cards (not a separate call). The LLM just wrote the cards — it can summarize them in the same output with near-zero additional cost.

**File:** `book_ingestion_v2/prompts/explanation_generation.txt`

Add to the end of the output format section:
```
The "teaching_notes" field should be a 2-3 sentence narrative summarizing: what conceptual progression you used, how your main analogy/example was applied, and what key insight the student should walk away with. Write it as if briefing another tutor who will continue the session: "Explained X using Y analogy — started with Z, built to W. Key insight: ..."
```

### 4.2 Master Tutor Agent — Welcome + Bridge Methods

**File:** `tutor/agents/master_tutor.py`

Add two new methods:

```python
async def generate_welcome(self, session: SessionState) -> TutorTurnOutput:
    """Generate session opening via master tutor with full context."""
    system_prompt = self._build_system_prompt(session)
    welcome_prompt = self._build_welcome_prompt(session)
    combined = f"{system_prompt}\n\n---\n\n{welcome_prompt}"
    return await self._execute_structured(combined)

async def generate_bridge(self, session: SessionState, bridge_type: str) -> TutorTurnOutput:
    """Generate post-card bridge. bridge_type: 'understood' | 'confused'."""
    system_prompt = self._build_system_prompt(session)
    bridge_prompt = self._build_bridge_prompt(session, bridge_type)
    combined = f"{system_prompt}\n\n---\n\n{bridge_prompt}"
    return await self._execute_structured(combined)
```

**`_build_welcome_prompt()`:**
```python
def _build_welcome_prompt(self, session: SessionState) -> str:
    has_cards = session.card_phase is not None
    student_name = getattr(session.student_context, 'student_name', None)
    return MASTER_TUTOR_WELCOME_PROMPT.render(
        topic_name=session.topic.topic_name,
        has_cards=has_cards,
        student_name=student_name or "there",
    )
```

**`_build_bridge_prompt()`:**
```python
def _build_bridge_prompt(self, session: SessionState, bridge_type: str) -> str:
    teaching_notes = session.precomputed_explanation_summary or "No detailed notes available."
    return MASTER_TUTOR_BRIDGE_PROMPT.render(
        bridge_type=bridge_type,
        teaching_notes=teaching_notes,
    )
```

**`_execute_structured()`** — shared helper to avoid duplicating LLM call logic:
```python
async def _execute_structured(self, combined_prompt: str) -> TutorTurnOutput:
    """Call LLM with combined prompt and return structured output."""
    response = await self.llm.call_structured_async(
        prompt=combined_prompt,
        output_model=TutorTurnOutput,
        component_key="tutor",
    )
    return response
```

**Decision:** Reuse `_build_system_prompt()` for welcome/bridge. The system prompt has full context (student profile, topic, study plan, precomputed summary). Welcome/bridge only differ in the turn prompt, which is purpose-specific. This avoids maintaining separate system prompts.

**Decision:** Both methods return `TutorTurnOutput` (same structured output as normal turns). Most fields will be null/default for welcome. For bridge with `bridge_type='understood'`, the tutor can set `question_asked` + `expected_answer` since it's asking the student to explain back. For `bridge_type='confused'`, the tutor can set `explanation_phase_update='opening'`.

### 4.3 Prompt Templates

**File:** `tutor/prompts/master_tutor_prompts.py`

Add two new templates at the end of file:

```python
MASTER_TUTOR_WELCOME_PROMPT = PromptTemplate(
    """## Session Opening

This is the very first message of the session. The student hasn't spoken yet.

{% if has_cards %}
After your greeting, the student will read explanation cards about the topic.
Frame the session: mention you've put together some cards, they should read through them, and then you'll check understanding and practice together.
{% else %}
After your greeting, you'll start explaining the topic interactively.
{% endif %}

Generate a warm greeting that:
1. Addresses the student{% if student_name != 'there' %} (their name is {{ student_name }}){% endif %}
2. Builds curiosity about the topic — connect it to their world in 1 sentence
3. Briefly frames what's coming in the session
4. 2-3 sentences max. No questions (student can't respond yet).

Set all state fields to null/default — no mastery updates, no questions, no phase updates.
""",
    name="master_tutor_welcome",
)


MASTER_TUTOR_BRIDGE_PROMPT = PromptTemplate(
    """## Post-Card Bridge

{% if bridge_type == 'understood' %}
The student just finished reading explanation cards and indicated they understand.

### What the cards covered
{{ teaching_notes }}

Reference something SPECIFIC from the cards — a particular analogy, example, or concept.
Ask the student to explain it back in their own words. This checks what they absorbed.
2-3 sentences. Warm, conversational. Frame as "let's see what stuck" not as a test.

Set question_asked and expected_answer for what you're asking.
{% else %}
The student read all available explanation card variants but is still confused.

### What the cards covered
{{ teaching_notes }}

DO NOT re-greet them. Start with empathy ("No worries, let's talk it through").
Begin a fresh explanation using a DIFFERENT approach than the cards used.
Reference what the cards tried so the student knows you're aware.

Set explanation_phase_update='opening' to start fresh explanation.
{% endif %}
""",
    name="master_tutor_bridge",
)
```

### 4.4 Orchestrator — Wire Welcome + Bridge

**File:** `tutor/orchestration/orchestrator.py`

Add two new methods:

```python
async def generate_tutor_welcome(self, session: SessionState) -> tuple[str, Optional[str]]:
    """Generate welcome via master tutor (replaces hardcoded welcome and WELCOME_MESSAGE_PROMPT)."""
    self.master_tutor.set_session(session)
    output = await self.master_tutor.generate_welcome(session)
    return output.response, output.audio_text

async def generate_bridge_turn(self, session: SessionState, bridge_type: str) -> TurnResult:
    """Generate post-card bridge via master tutor. Returns TurnResult with state applied."""
    self.master_tutor.set_session(session)
    output = await self.master_tutor.generate_bridge(session, bridge_type)

    # Apply state updates from bridge (question tracking for 'understood', phase for 'confused')
    state_changed = self._apply_state_updates(session, output)

    # Add to conversation history
    from tutor.models.messages import create_teacher_message
    session.add_message(create_teacher_message(output.response, audio_text=output.audio_text))

    # Update session summary
    session.session_summary.turn_timeline.append(output.turn_summary)

    return TurnResult(
        response=output.response,
        audio_text=output.audio_text,
        intent=output.intent,
        state_changed=state_changed,
    )
```

**Decision:** `generate_bridge_turn()` applies state updates (unlike `generate_tutor_welcome()`) because the bridge can set `question_asked` or `explanation_phase_update` which affect the next turn's pacing directive. Welcome has no state side-effects.

### 4.5 Session Service — Replace Hardcoded Messages

**File:** `tutor/services/session_service.py`

#### Change 1: `create_new_session()` — Master tutor welcome for card sessions

Replace lines 138-171 (the card-phase branch):

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

#### Change 2: `complete_card_phase()` — Master tutor bridge

Replace the `action == "clear"` branch (lines 854-872):

```python
if action == "clear":
    session.complete_card_phase()
    self._advance_past_explanation_steps(session)

    precomputed_summary = self._build_precomputed_summary(session)
    session.precomputed_explanation_summary = precomputed_summary

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
    # All variants exhausted — master tutor re-explains (was generic welcome)
    precomputed_summary = self._build_precomputed_summary(session)
    session.precomputed_explanation_summary = precomputed_summary

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

### 4.6 Card-Aware Pacing for Non-Leading Explain Steps

**File:** `tutor/agents/master_tutor.py`

Modify `_compute_pacing_directive()` — add check before the explanation-aware pacing block:

```python
# Card-aware: if current step is explain but cards already covered the topic
current_step = session.current_step_data
if current_step and current_step.type == "explain" and session.precomputed_explanation_summary:
    return (
        "PACING: QUICK-CHECK (cards covered this) — The student already read explanation "
        "cards about this topic. Do NOT re-explain from scratch. Instead, ask a quick "
        "'what do you remember about {concept}?' check. If they remember, set "
        "explanation_phase_update='complete' and advance. If not, give a brief 2-3 sentence "
        "refresher using a different angle than the cards, then ask again."
    ).format(concept=current_step.concept)
```

Insert this after the `turn == 1` block and before the existing explain-step pacing block (line ~179). This ensures non-leading explain steps that were covered by cards get the quick-check treatment.

### 4.7 WebSocket — Fix Duplicate Welcome

**File:** `tutor/api/sessions.py`

Line 721: Change guard from `turn_count == 0` to conversation history check:

```python
# Before:
if session.turn_count == 0 and not session.is_in_card_phase():

# After:
if not session.conversation_history and not session.is_in_card_phase():
```

**Rationale:** `turn_count` stays 0 after `create_new_session()` because `add_message()` doesn't increment it. `conversation_history` has the welcome message. This prevents double welcome.

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

Modify `handleCardAction` (lines 907-946). The response now includes `audio_text`:

```typescript
if (result.action === 'transition_to_interactive' || result.action === 'fallback_dynamic') {
  setSessionPhase('interactive');
  const bridgeMsg: Message = {
    role: 'teacher',
    content: result.message,
    audioText: result.audio_text || null,  // NEW: backend now returns audio_text
  };
  setMessages(prev => [...prev, bridgeMsg]);

  // ... existing slide index calculation, adapted for welcome slide offset:
  const teacherCount = messages.filter(m => m.role === 'teacher').length + 1; // +1 for bridge
  const totalSlides = explanationCards.length + teacherCount; // welcome is separate from cards
  setCurrentSlideIdx(totalSlides - 1);

  localStorage.removeItem(`slide-pos-${sessionId}`);
  // Auto-play TTS
  if (result.audio_text) {
    playTeacherAudio(result.audio_text, `bridge-${Date.now()}`);
  }
}
```

#### Change 3: Show tutor's farewell before summary

Add state: `const [showSummary, setShowSummary] = useState(false);`

Replace the `isComplete` render condition (line 1063):

```typescript
{showSummary ? (
  // Existing summary card JSX (lines 1063-1187)
  <div className="summary-card" ...>
    {/* existing summary content */}
  </div>
) : (
  // Carousel (shows even when isComplete — tutor's final message is visible)
  <div className="chat-container" ...>
    {/* existing carousel JSX */}
    {isComplete && (
      <div style={{ textAlign: 'center', padding: '16px' }}>
        <button
          className="action-button primary"
          onClick={() => setShowSummary(true)}
        >
          View Session Summary
        </button>
      </div>
    )}
  </div>
)}
```

Remove the old `{isComplete ? (...) : (...)}` ternary that immediately hid the carousel.

#### Change 4: TeachMe progress frame

Add state: `const [totalSteps, setTotalSteps] = useState(0);`

Populate from state update (add to onStateUpdate handler):
```typescript
if (state.total_steps != null) setTotalSteps(state.total_steps);
```

Also populate from firstTurn initialization and replay.

Remove `sessionMode !== 'teach_me'` exclusion (line 1033). Add teach_me content:

```typescript
{sessionMode === 'teach_me' && totalSteps > 0 && (
  <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
    Step {stepIdx} of {totalSteps}
  </span>
)}
```

#### Change 5: Card resume from server state

Modify replay hydration. When card phase is active, use server position:

```typescript
// During replay hydration (lines ~368-394)
if (state.card_phase?.active && state.card_phase.current_card_idx != null) {
  // Server-tracked position (+1 for welcome slide)
  setCurrentSlideIdx(state.card_phase.current_card_idx + 1);
} else {
  // Fallback to localStorage for interactive phase
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

All three use the master tutor's full system prompt (which includes study plan, precomputed summary, student profile). The turn prompt is minimal — just the purpose-specific instruction.

**Latency impact:** Welcome adds ~2-3s to session creation (was instant with hardcoded). Bridge adds ~2-3s to "I understand!" click (was instant). Acceptable tradeoff for coherent experience.

### Modified prompt (explanation generation)

`teaching_notes` field added to existing generation output schema. No additional LLM call — generated alongside cards in the same response.

---

## 7. Configuration & Environment

No new environment variables. No config changes. All changes use existing `tutor` LLM config component.

---

## 8. Implementation Order

| Step | What | Files | Depends On | Test |
|------|------|-------|------------|------|
| 1 | Add `teaching_notes` to explanation generator | `explanation_generator_service.py`, `explanation_generation.txt` | — | Generate explanations for a test topic, verify `teaching_notes` in `summary_json` |
| 2 | Enrich `_build_precomputed_summary()` | `session_service.py` | Step 1 | Unit test: summary with/without teaching_notes |
| 3 | Add welcome/bridge prompt templates | `master_tutor_prompts.py` | — | Templates render without error |
| 4 | Add `generate_welcome()`, `generate_bridge()` to master tutor agent | `master_tutor.py` | Step 3 | Mock LLM call, verify structured output |
| 5 | Add `generate_tutor_welcome()`, `generate_bridge_turn()` to orchestrator | `orchestrator.py` | Step 4 | Mock master tutor, verify return shape |
| 6 | Wire welcome in `create_new_session()` | `session_service.py` | Step 5 | Create session with cards, verify LLM-generated welcome (not hardcoded) |
| 7 | Wire bridge in `complete_card_phase()` | `session_service.py` | Step 5 | Complete card phase, verify LLM-generated bridge + audio_text |
| 8 | Add card-aware pacing directive | `master_tutor.py` | Step 2 | Unit test: pacing returns QUICK-CHECK when explain step + precomputed summary |
| 9 | Fix duplicate welcome guard | `sessions.py` | — | WS connect with existing welcome in history → no second welcome |
| 10 | Frontend: welcome slide before cards | `ChatSession.tsx` | Step 6 | Start session → see welcome slide → swipe → cards |
| 11 | Frontend: bridge turn handling | `ChatSession.tsx` | Step 7 | Click "I understand!" → see tutor bridge → interactive phase |
| 12 | Frontend: farewell before summary | `ChatSession.tsx` | — | Complete session → see tutor's closing → click "View Summary" |
| 13 | Frontend: teach_me progress frame | `ChatSession.tsx` | — | Start teach_me → see step progress |
| 14 | Frontend: card resume from server | `ChatSession.tsx` | — | Reload mid-cards → resume at server position |

**Order rationale:** Backend layers bottom-up (generator → agent → orchestrator → service). Frontend changes after backend is wired. Bug fixes (step 9) are standalone. Frontend steps 12-14 are independent and can be done in any order.

---

## 9. Testing Plan

### Unit tests

| Test | Verifies | Key Mocks |
|------|----------|-----------|
| `test_teaching_notes_in_summary` | `ExplanationSummaryOutput` includes `teaching_notes`, `_build_summary()` propagates it | LLM response |
| `test_precomputed_summary_uses_teaching_notes` | `_build_precomputed_summary()` prefers `teaching_notes` over structured labels | ExplanationRepository |
| `test_precomputed_summary_fallback` | Falls back to structured labels when no `teaching_notes` | ExplanationRepository |
| `test_master_tutor_welcome` | `generate_welcome()` returns valid `TutorTurnOutput` with response + audio_text | LLM service |
| `test_master_tutor_bridge_understood` | `generate_bridge('understood')` sets `question_asked` | LLM service |
| `test_master_tutor_bridge_confused` | `generate_bridge('confused')` sets `explanation_phase_update='opening'` | LLM service |
| `test_card_aware_pacing` | `_compute_pacing_directive()` returns QUICK-CHECK when explain step + precomputed summary | None |
| `test_pacing_normal_without_cards` | Explain step without precomputed summary → normal explain pacing | None |
| `test_duplicate_welcome_guard` | WS handler skips welcome when `conversation_history` already has messages | DB session |

### Manual verification

1. **Welcome:** Start new teach_me session with cards → first slide is personalized welcome from tutor (mentions student name, topic, frames session)
2. **Cards:** Swipe through cards → same experience as before
3. **Bridge ("I understand!"):** Click "I understand!" → tutor references specific card content, asks to explain back
4. **Bridge (all variants):** Click "Explain differently" until exhausted → tutor acknowledges, starts fresh explanation
5. **Non-leading explain step:** Reach a non-leading explain step after cards → tutor does quick-check, not full re-explanation
6. **Session ending:** Complete all steps → see tutor's farewell message → click "View Summary" → see summary
7. **Progress frame:** During teach_me session → see "Step X of Y" in header
8. **Card resume:** Start session, read 5 of 10 cards, close browser → reopen → resume at correct position
9. **No duplicate welcome:** Start non-card session → only one welcome message appears

---

## 10. Deployment Considerations

- **No migrations needed.** `summary_json` is JSONB — new keys are additive.
- **Backfill:** After deploying, re-run explanation generation (`POST /admin/v2/books/{id}/generate-explanations?force=true`) to populate `teaching_notes` for existing topics. Until then, summary falls back to existing structured labels.
- **Latency:** Session creation gains ~2-3s for welcome LLM call. Monitor App Runner response times. If problematic, welcome can be generated async and streamed to frontend.
- **Rollback:** If master tutor welcome/bridge quality is poor, revert session_service.py changes to restore hardcoded messages. All other changes (teaching_notes, pacing, bug fixes) are safe to keep.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Welcome LLM latency delays session start | Med | Med | Monitor. Can parallelize card loading with welcome generation. |
| Master tutor generates poor welcome (too long, asks questions) | Low | Med | Prompt is explicit about constraints. Add length guard in orchestrator. |
| Bridge turn doesn't reference cards well | Med | Low | Depends on teaching_notes quality. Fallback to structured labels ensures baseline. |
| Existing topics lack teaching_notes until backfill | High (initially) | Low | Graceful fallback to old summary format. No breakage. |
| Card-aware pacing confuses tutor on non-leading explain steps | Low | Med | Pacing directive is clear. Master tutor already handles explain steps well. |

---

## 12. Open Questions

None — all decisions made. Implementation can proceed.
