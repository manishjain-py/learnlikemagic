# Tutor Improvement Plan v3 — R3 → R4 (Final)

**Date:** Feb 13, 2026
**Current avg score:** 7.7/10
**Target:** 8.0+/10
**Revision of:** IMPROVEMENT_PLAN_v2.md (addressed all review feedback)

---

## Executive Summary

Round 3 achieved +1.4 (6.3→7.7). The remaining gap is **adaptiveness**: rigid pacing, one-size-fits-all length, direct correction over guided discovery, and missed "probe why" moments.

**Key architecture:**
- **System prompt** = WHO the tutor is (personality, pedagogy) — 10 rules, static per session
- **Turn prompt** = WHAT to do THIS turn (pacing, student style, question lifecycle) — dynamic every turn

### Verified File Paths (all relative to repo root)

| File | Purpose |
|------|---------|
| `tutor/prompts/master_tutor_prompts.py` | System & turn prompt templates (lines 13–99) |
| `tutor/agents/master_tutor.py` | MasterTutorAgent + TutorTurnOutput schema (lines 1–173) |
| `tutor/orchestration/orchestrator.py` | TeacherOrchestrator, process_turn, _apply_state_updates (lines 1–265) |
| `tutor/models/session_state.py` | SessionState, Question, SessionSummary models (lines 1–168) |

### Bugs Fixed From v2 Review

1. **Off-by-one:** `turn_count` is already 1 on first student message (`orchestrator.py` line 108: `session.increment_turn()` before tutor runs). v2 had this right but v1 didn't. Confirmed: check `turn == 1`.
2. **Extension mechanism incomplete:** v2 modified both `process_turn` AND `_apply_state_updates` but made the extension logic in `_apply_state_updates` confusing. v3: extension is ONLY the `process_turn` early-return bypass. `_apply_state_updates` stays simple.
3. **Probing question overwrites tracked question:** v2's `_apply_state_updates` rewrite had 4 branches with nested conditions. v3: extract `_handle_question_lifecycle()` helper.

---

## Phase 1: Prompt Rewrite (System + Turn)

### 1a. New System Prompt — EXACT TEXT

**File:** `tutor/prompts/master_tutor_prompts.py` lines 13–80
**Replace** the entire `MASTER_TUTOR_SYSTEM_PROMPT` definition with:

```python
MASTER_TUTOR_SYSTEM_PROMPT = PromptTemplate(
    """You are a warm, encouraging tutor teaching a Grade {grade} student.
Use {language_level} language. The student likes examples about: {preferred_examples}.

## Topic: {topic_name}

### Teaching Approach
{teaching_approach}

### Study Plan
{steps_formatted}

### Common Misconceptions to Watch For
{common_misconceptions}

## Rules

1. **Follow the plan, hide the scaffolding.** Steps are typed (explain, check,
   practice) — use that to guide what you do, never mention step numbers or plan
   structure. Transitions feel like natural conversation.

2. **Advance when ready.** When understanding is demonstrated, set `advance_to_step`.
   Don't linger. If the student explicitly requests harder material, HONOR IT.

3. **Track questions.** When your response contains a question, fill in
   `question_asked`, `expected_answer`, `question_concept`.

4. **Guide discovery — don't just correct.** When the student answers wrong:
   1st wrong → ask a probing question ("What would happen if…?" "Walk me through that.")
   2nd wrong → give a targeted hint pointing at the specific error.
   3rd+ → explain directly and warmly.
   When a student changes their answer, ask what made them change BEFORE evaluating.
   When they use an unexpected strategy, explore their reasoning before correcting.
   CRITICAL: VERIFY answers are actually correct before praising. If they say 7
   when the answer is 70, that is WRONG.

5. **Never repeat yourself.** Vary praise, structure, openings. Often the best
   response to a correct answer is no praise — just build on it. Skip recaps when
   momentum is good.

6. **Match the student's energy.** Build on their metaphors. Feed curiosity. If
   confused, try a different angle. If off-topic, redirect warmly.

7. **Update mastery.** After evaluating: ~0.3 wrong, ~0.6 partial, ~0.8 correct,
   ~0.95 correct with reasoning.

8. **Be real.** Praise proportionally — most correct answers need just a nod.
   Emojis: 0-2 per response. No ALL CAPS. Only promise examples you'll use.

9. **End naturally.** When the final step is mastered, check for misconceptions
   first (ask them to demonstrate understanding). Then wrap up in 2-4 sentences:
   respond to their last message, reflect on what THEY specifically learned, sign
   off with something from the conversation. Set `session_complete=true`. Never
   use canned closings.

10. **Never leak internals.** `response` is shown directly to the student. No
    third-person language ("The student's answer shows…"). Speak TO them. Put
    analysis in `reasoning`.""",
    name="master_tutor_system",
)
```

**What changed vs current** (lines 13–80):
- 11 rules → 10 rules. Merged rules 9+11 (end + misconception check). Removed response-length matching from rule 2 (→ turn prompt). Rewrote rule 4 to include 3-attempt Socratic escalation + answer-change probing.
- ~30% fewer tokens. All dynamic/per-turn signals removed from system prompt.

### 1b. New Turn Prompt — EXACT TEXT

**File:** `tutor/prompts/master_tutor_prompts.py` lines 83–99
**Replace** the entire `MASTER_TUTOR_TURN_PROMPT` definition with:

```python
MASTER_TUTOR_TURN_PROMPT = PromptTemplate(
    """## Current Session State

**Current Step**: Step {current_step} of {total_steps} — {current_step_info}
**Content Hint**: {content_hint}
**Mastery Estimates**:
{mastery_formatted}
**Misconceptions Detected**: {misconceptions}
**Session So Far**: {turn_timeline}

## This Turn
{pacing_directive}
{student_style}

{awaiting_answer_section}

## Conversation History
{conversation_history}

## Student's Message
{student_message}

Respond as the tutor. Return your response in the structured output format.""",
    name="master_tutor_turn",
)
```

**What changed:** Added `{pacing_directive}` and `{student_style}` slots under a new "This Turn" section. These are computed dynamically per turn (see Phase 2).

---

## Phase 2: Dynamic Turn Signals

### 2a. `_compute_pacing_directive` — new method on MasterTutorAgent

**File:** `tutor/agents/master_tutor.py`
**Add** after `set_session` (after line 87):

```python
def _compute_pacing_directive(self, session: SessionState) -> str:
    """One-line pacing instruction based on session signals."""
    turn = session.turn_count  # already 1 on first msg (orchestrator.py line 108)
    mastery_values = list(session.mastery_estimates.values())
    avg_mastery = sum(mastery_values) / len(mastery_values) if mastery_values else 0.0
    trend = session.session_summary.progress_trend  # defaults to "steady"

    if turn == 1:
        return (
            "PACING: FIRST TURN — Keep opening to 2-3 sentences. Ask ONE simple "
            "question to gauge level. Don't explain the topic yet."
        )

    if avg_mastery >= 0.8 and trend == "improving":
        return (
            "PACING: ACCELERATE — Student is acing this. Skip easy checks, go deeper. "
            "Harder applications, curveballs, edge cases. Keep responses concise."
        )

    if avg_mastery < 0.4 or trend == "struggling":
        return (
            "PACING: SIMPLIFY — Student is struggling. Shorter sentences, 1-2 ideas "
            "per response. Yes/no or simple-choice questions. More scaffolding."
        )

    return "PACING: STEADY — Progressing normally. One idea at a time."
```

### 2b. `_compute_student_style` — new method on MasterTutorAgent

**File:** `tutor/agents/master_tutor.py`
**Add** after `_compute_pacing_directive`:

```python
def _compute_student_style(self, session: SessionState) -> str:
    """Compute response-style guidance from student's communication patterns."""
    student_msgs = [
        m for m in session.conversation_history if m.role == "student"
    ]
    if not student_msgs:
        return "STYLE: Unknown (first turn). Start short."

    # Word count
    word_counts = [len(m.content.split()) for m in student_msgs]
    avg_words = sum(word_counts) / len(word_counts)

    # Engagement signals
    asks_questions = any("?" in m.content for m in student_msgs)
    uses_emojis = any(
        any(ord(c) > 0x1F600 for c in m.content) for m in student_msgs
    )
    # Disengagement: are responses getting shorter?
    shortening = False
    if len(word_counts) >= 3:
        recent = word_counts[-3:]
        shortening = recent[-1] < recent[0] * 0.5  # last msg < half of 3-ago

    parts = []
    if avg_words <= 5:
        parts.append(f"STYLE: QUIET ({avg_words:.0f} words/msg avg) — respond in 2-3 sentences MAX.")
    elif avg_words <= 15:
        parts.append(f"STYLE: Moderate ({avg_words:.0f} words/msg) — 3-5 sentences.")
    else:
        parts.append(f"STYLE: Expressive ({avg_words:.0f} words/msg) — can elaborate more.")

    if asks_questions:
        parts.append("Student asks questions — encourage this, answer them.")
    if uses_emojis:
        parts.append("Student uses emojis — you can mirror lightly.")
    if shortening:
        parts.append("⚠️ Responses getting shorter — possible disengagement. Re-engage: try a different angle or ask what they think.")

    return " ".join(parts)
```

### 2c. Update `_build_turn_prompt` to wire new signals

**File:** `tutor/agents/master_tutor.py`, method `_build_turn_prompt` (starts line 104)

**Add** before the `return MASTER_TUTOR_TURN_PROMPT.render(...)` call (around line 155):

```python
    # Compute dynamic signals
    pacing_directive = self._compute_pacing_directive(session)
    student_style = self._compute_student_style(session)
```

**Update** the `return MASTER_TUTOR_TURN_PROMPT.render(...)` call (lines 155–166) to include new kwargs:

```python
    return MASTER_TUTOR_TURN_PROMPT.render(
        current_step=session.current_step,
        total_steps=session.topic.study_plan.total_steps if session.topic else 0,
        current_step_info=current_step_info,
        content_hint=content_hint,
        mastery_formatted=mastery_formatted,
        misconceptions=misconceptions,
        turn_timeline=turn_timeline,
        pacing_directive=pacing_directive,
        student_style=student_style,
        awaiting_answer_section=awaiting_answer_section,
        conversation_history=conversation,
        student_message=context.student_message,
    )
```

### 2d. Update awaiting_answer_section with lifecycle info

**File:** `tutor/agents/master_tutor.py`, inside `_build_turn_prompt` (lines 133–142)

**Replace** the awaiting_answer_section block:

```python
        if session.awaiting_response and session.last_question:
            q = session.last_question
            attempt_num = q.wrong_attempts + 1

            if q.wrong_attempts == 0:
                strategy = "Evaluate their answer."
            elif q.wrong_attempts == 1:
                strategy = "PROBING QUESTION — help them find the error."
            elif q.wrong_attempts == 2:
                strategy = "TARGETED HINT — point at the specific mistake."
            else:
                strategy = "EXPLAIN directly and warmly."

            prev = ""
            if q.previous_student_answers:
                prev = f"\nPrevious wrong answers: {'; '.join(q.previous_student_answers[-3:])}"

            awaiting_answer_section = (
                f"**IMPORTANT — Student is answering (attempt #{attempt_num}):**\n"
                f"Question: {q.question_text}\n"
                f"Expected: {q.expected_answer}\n"
                f"Concept: {q.concept}\n"
                f"Strategy: {strategy}{prev}"
            )
        else:
            awaiting_answer_section = ""
```

**Effort:** 4h

---

## Phase 3: Session State Model Changes

### 3a. Add lifecycle fields to Question

**File:** `tutor/models/session_state.py`, class `Question` (lines 37–43)

**Add** three fields after `hints_used`:

```python
    wrong_attempts: int = Field(default=0, description="Number of wrong attempts on this question")
    previous_student_answers: list[str] = Field(default_factory=list, description="Student's previous wrong answers")
    phase: str = Field(default="asked", description="Lifecycle phase: asked, probe, hint, explain")
```

### 3b. Add allow_extension to SessionState

**File:** `tutor/models/session_state.py`, class `SessionState` (around line 82)

**Add** after `awaiting_response`:

```python
    allow_extension: bool = Field(default=True, description="Allow tutor to continue past study plan for advanced students")
```

**Effort:** 0.5h

---

## Phase 4: Orchestrator Changes

### 4a. Extension: process_turn early-return bypass

**File:** `tutor/orchestration/orchestrator.py`, `process_turn` method, lines 100–107

**Replace:**
```python
            if session.is_complete:
```

**With:**
```python
            if session.is_complete and not session.allow_extension:
```

That's the ENTIRE extension change. `_apply_state_updates` stays unchanged for extension — when the tutor finally sets `session_complete=true` again after extension turns, `_apply_state_updates` will handle it normally (it already does).

### 4b. Extract `_handle_question_lifecycle` helper

**File:** `tutor/orchestration/orchestrator.py`

**Add** new method after `_apply_state_updates`:

```python
def _handle_question_lifecycle(self, session: SessionState, output: TutorTurnOutput) -> bool:
    """
    Handle question tracking with lifecycle awareness.
    
    Returns True if state changed.
    
    Logic:
    - Wrong answer on pending question → increment attempts, DON'T clear
    - Correct answer → clear question
    - New question (no pending) → track it
    - New question (different concept pending) → replace
    - Follow-up question (same concept pending) → keep original lifecycle
    """
    current_concept = (
        session.current_step_data.concept if session.current_step_data else "unknown"
    )
    has_pending = session.last_question is not None
    
    # Case 1: Wrong answer on a pending question
    if output.answer_correct is False and has_pending:
        q = session.last_question
        q.wrong_attempts += 1
        # Record what the student said
        if session.conversation_history:
            last_student = [m for m in session.conversation_history if m.role == "student"]
            if last_student:
                q.previous_student_answers.append(last_student[-1].content[:200])
        # Update phase
        if q.wrong_attempts == 1:
            q.phase = "probe"
        elif q.wrong_attempts == 2:
            q.phase = "hint"
        else:
            q.phase = "explain"
        # Any follow-up question from tutor is part of same lifecycle — don't replace
        return True

    # Case 2: Correct answer → clear, then maybe track new question
    if output.answer_correct is True:
        session.clear_question()
        if output.question_asked:
            session.set_question(Question(
                question_text=output.question_asked,
                expected_answer=output.expected_answer or "",
                concept=output.question_concept or current_concept,
            ))
        return True

    # Case 3: New question, no pending
    if output.question_asked and not has_pending:
        session.set_question(Question(
            question_text=output.question_asked,
            expected_answer=output.expected_answer or "",
            concept=output.question_concept or current_concept,
        ))
        return True

    # Case 4: New question while one is pending — only replace if different concept
    if output.question_asked and has_pending:
        if output.question_concept != session.last_question.concept:
            session.set_question(Question(
                question_text=output.question_asked,
                expected_answer=output.expected_answer or "",
                concept=output.question_concept or current_concept,
            ))
            return True
        # Same concept follow-up → keep existing lifecycle
        return False

    # Case 5: answer_correct is None and no question_asked → no change
    return False
```

### 4c. Simplify `_apply_state_updates` to use the helper

**File:** `tutor/orchestration/orchestrator.py`, `_apply_state_updates` method (lines 200–237)

**Replace** the section labeled `# 3. Track questions` (lines 216–224):

```python
        # 3. Track questions
        if output.question_asked:
            session.set_question(Question(
                question_text=output.question_asked,
                expected_answer=output.expected_answer or "",
                concept=output.question_concept or current_concept,
            ))
            changed = True
        elif output.answer_correct is not None:
            session.clear_question()
            changed = True
```

**With:**

```python
        # 3. Question lifecycle
        if self._handle_question_lifecycle(session, output):
            changed = True
```

Everything else in `_apply_state_updates` stays the same.

**Effort:** 3h

---

## Phase 5: Schema Changes

### 5a. Expand `intent` field

**File:** `tutor/agents/master_tutor.py`, class `TutorTurnOutput` (line 34)

**Replace:**
```python
    intent: str = Field(
        description="What the student was doing: answer, question, confusion, off_topic, or continuation"
    )
```

**With:**
```python
    intent: str = Field(
        description="What the student was doing: answer, answer_change, question, confusion, novel_strategy, off_topic, or continuation"
    )
```

**Effort:** 0.5h

---

## Implementation Order

| Phase | What | Effort | Risk |
|-------|------|--------|------|
| **1** | Prompt rewrite (system + turn templates) | 1.5h | Low |
| **2** | Dynamic turn signals (_compute_pacing_directive, _compute_student_style, wire into _build_turn_prompt) | 4h | Low |
| **3** | Session state model changes (Question lifecycle fields, allow_extension) | 0.5h | Low |
| **4** | Orchestrator (extension bypass + _handle_question_lifecycle helper + simplify _apply_state_updates) | 3h | Medium |
| **5** | Schema changes (intent expansion) | 0.5h | Low |
| **6** | Unit tests | 4h | Low |
| **7** | Eval run + iterate | 3h | Low |
| **Total** | | **16.5h** | |

---

## Unit Tests

### `tests/test_pacing_directive.py`

| Test | Verifies |
|------|----------|
| `test_first_turn_directive` | `turn_count=1` → "FIRST TURN" |
| `test_first_turn_not_zero` | `turn_count=0` → NOT first turn (pre-increment state) |
| `test_accelerate_high_mastery` | avg mastery ≥0.8 + improving → "ACCELERATE" |
| `test_simplify_struggling` | avg mastery <0.4 → "SIMPLIFY" |
| `test_simplify_trend` | trend="struggling" → "SIMPLIFY" |
| `test_steady_default` | mid mastery + steady → "STEADY" |

### `tests/test_student_style.py`

| Test | Verifies |
|------|----------|
| `test_no_messages` | Empty history → "Unknown" |
| `test_quiet_student` | avg ≤5 words → "QUIET" + "2-3 sentences MAX" |
| `test_moderate_student` | avg 6-15 words → "Moderate" |
| `test_expressive_student` | avg >15 words → "Expressive" |
| `test_asks_questions` | Messages with "?" → "asks questions" in output |
| `test_disengagement_signal` | Shortening word counts → "disengagement" warning |

### `tests/test_question_lifecycle.py`

| Test | Verifies |
|------|----------|
| `test_new_question_no_pending` | `question_asked` with no pending → `set_question` called |
| `test_wrong_answer_increments` | `answer_correct=False` → `wrong_attempts += 1` |
| `test_wrong_answer_preserves_question` | `answer_correct=False` → `last_question` NOT cleared |
| `test_wrong_answer_records_student_answer` | Student answer appended to `previous_student_answers` |
| `test_phase_progression` | 1st wrong → probe, 2nd → hint, 3rd → explain |
| `test_correct_clears` | `answer_correct=True` → question cleared |
| `test_followup_same_concept` | `question_asked` on same concept while pending → keeps original |
| `test_new_concept_replaces` | `question_asked` on different concept → replaces |
| `test_probing_after_wrong_preserves` | `answer_correct=False` + `question_asked` → original question kept |

### `tests/test_extension.py`

| Test | Verifies |
|------|----------|
| `test_extension_bypasses_early_return` | `is_complete=True` + `allow_extension=True` → tutor runs |
| `test_no_extension_short_circuits` | `is_complete=True` + `allow_extension=False` → post-completion response |

---

## Validation

Run 6-persona eval suite on 4-digit place value.

### Success Criteria
- **Average score: 8.0+** (up from 7.7)
- Pacing dimension: 7.5+ (up from 6.8)
- No persona below 7.0
- `wrong_pacing` ≤ 3 (down from 7)
- `missed_student_signal` ≤ 4 (down from 6)
- System prompt token count ≤ current (regression test)

### Key Personas to Watch

| Persona | What to measure |
|---------|----------------|
| Arjun (ace) | Pacing 6→8, acceleration works |
| Priya (struggler) | Pacing 5→7, SIMPLIFY kicks in |
| Meera (quiet) | Authenticity 6→8, short responses match her style |
| Riya, Meera | Over-scaffolding 3→0-1 |
| Riya, Kabir, Dev | Missed signals 6→2-3 |

---

## Files Modified (Summary)

| File | Changes |
|------|---------|
| `tutor/prompts/master_tutor_prompts.py` | System prompt: 11→10 rules, tighter, Socratic escalation in rule 4, end+misconception merged in rule 9. Turn prompt: added `{pacing_directive}`, `{student_style}` |
| `tutor/agents/master_tutor.py` | New: `_compute_pacing_directive()`, `_compute_student_style()`. Updated: `_build_turn_prompt()` wiring + lifecycle-aware awaiting section. Schema: expanded `intent` |
| `tutor/models/session_state.py` | `Question`: +`wrong_attempts`, `previous_student_answers`, `phase`. `SessionState`: +`allow_extension` |
| `tutor/orchestration/orchestrator.py` | `process_turn` line 100: extension bypass (1-line change). New: `_handle_question_lifecycle()` helper. `_apply_state_updates`: replaced question tracking block with helper call |
