# Tutor Improvement Plan v2 — R3 → R4 (Revised)

**Date:** Feb 13, 2026  
**Current avg score:** 7.7/10  
**Target:** 8.5+/10  
**Revision of:** IMPROVEMENT_PLAN.md (fixed 3 bugs, consolidated prompts, added tests)

---

## Executive Summary

Round 3 achieved +1.4 (6.3→7.7). The remaining gap is **adaptiveness**: rigid pacing, one-size-fits-all length, direct correction over guided discovery, and missed "probe why" moments. This plan addresses all four issues while **keeping the system prompt compact** (11 rules → 10 rules) by consolidating related behaviors.

**Key design principle:** The *system prompt* defines WHO the tutor is (personality, pedagogy). The *turn prompt* provides WHAT to do THIS turn (pacing directive, student style signals, question lifecycle state).

### Bugs Fixed From v1 Review

1. **Off-by-one:** `turn_count` is already 1 on first student message (incremented at `orchestrator.py` line 108 before tutor runs). Fixed: check `turn == 1`, not `turn == 0`.
2. **Extension mechanism incomplete:** v1 only modified the `process_turn` early return but `_apply_state_updates` still advances past final step. Fixed: added extension-aware logic in both places.
3. **Probing question overwrites tracked question:** When tutor asks a Socratic follow-up, `output.question_asked` triggers `set_question()`, replacing `last_question` and losing `wrong_attempts`. Fixed: introduced question lifecycle state machine that preserves the original question during probing.

---

## Architecture: Question Lifecycle State Machine

Issues 3 and 4 require a proper state machine for question tracking. The current code has a binary model (question exists or doesn't). We need:

```
                    ┌─────────────────────────────────────┐
                    │                                     │
                    ▼                                     │
  [no_question] ──► [asked] ──► [wrong_attempt_1] ──► [probe] ──► [wrong_attempt_2] ──► [hint] ──► [wrong_attempt_3] ──► [explain]
                      │                                                                                                     │
                      │              (correct at any stage)                                                                  │
                      └──────────────────────────────────► [clear] ◄────────────────────────────────────────────────────────┘
```

**States:**
- `asked` — question posed, awaiting first answer
- `wrong_attempt_N` — student answered incorrectly (N = 1, 2, 3+)
- `probe` — tutor asked a probing question about the error (follow-up, NOT a new tracked question)
- `hint` — tutor gave a targeted hint
- `explain` — tutor explained directly (3rd+ wrong attempt)
- `clear` — student answered correctly or tutor moved on

**Critical rule:** A probing/follow-up question after a wrong answer is NOT a new tracked question — it's part of the same question's lifecycle. Only `output.question_asked` on a *new concept* creates a new tracked question.

---

## File Changes

### 1. Session State: Add Question Lifecycle Fields

**File:** `tutor/models/session_state.py`  
**Class:** `Question` (lines 37–43)

Add three fields:

```python
class Question(BaseModel):
    """A question asked to the student."""

    question_text: str = Field(description="The question asked")
    expected_answer: str = Field(description="Expected/correct answer")
    concept: str = Field(description="Concept being tested")
    rubric: str = Field(default="", description="Evaluation criteria")
    hints: list[str] = Field(default_factory=list, description="Available hints")
    hints_used: int = Field(default=0, description="Number of hints provided")
    # NEW fields for question lifecycle
    wrong_attempts: int = Field(default=0, description="Number of wrong attempts on this question")
    previous_student_answers: list[str] = Field(default_factory=list, description="Student's previous answers")
    phase: str = Field(default="asked", description="Lifecycle phase: asked, probe, hint, explain")
```

**Class:** `SessionState` (line 82 area)

Add extension field:

```python
    allow_extension: bool = Field(default=True, description="Allow tutor to extend beyond study plan for advanced students")
```

**Effort:** 0.5h

---

### 2. Orchestrator: Fix State Updates + Extension Logic

**File:** `tutor/orchestration/orchestrator.py`

#### 2a. Fix `process_turn` completion check (line 100)

Replace:
```python
            if session.is_complete:
```

With:
```python
            if session.is_complete and not session.allow_extension:
```

#### 2b. Rewrite question tracking in `_apply_state_updates` (lines 184–192)

The current code:
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

Replace with:
```python
        # 3. Question lifecycle management
        if output.answer_correct is False and session.last_question:
            # Wrong answer — advance lifecycle, don't clear
            q = session.last_question
            q.wrong_attempts += 1
            # Record student's answer from conversation history
            if session.conversation_history:
                q.previous_student_answers.append(
                    session.conversation_history[-1].content[:200]
                )
            # Update phase based on attempt count
            if q.wrong_attempts == 1:
                q.phase = "probe"
            elif q.wrong_attempts == 2:
                q.phase = "hint"
            else:
                q.phase = "explain"
            # If tutor asked a follow-up, it's part of the same question lifecycle
            # — do NOT replace last_question
            changed = True
        elif output.answer_correct is True:
            session.clear_question()
            changed = True
            # If tutor asked a NEW question (new concept), track it
            if output.question_asked:
                session.set_question(Question(
                    question_text=output.question_asked,
                    expected_answer=output.expected_answer or "",
                    concept=output.question_concept or current_concept,
                ))
        elif output.question_asked and not session.last_question:
            # New question when none was pending
            session.set_question(Question(
                question_text=output.question_asked,
                expected_answer=output.expected_answer or "",
                concept=output.question_concept or current_concept,
            ))
            changed = True
        elif output.question_asked and session.last_question:
            # New question asked while one is pending — only replace if different concept
            if output.question_concept != session.last_question.concept:
                session.set_question(Question(
                    question_text=output.question_asked,
                    expected_answer=output.expected_answer or "",
                    concept=output.question_concept or current_concept,
                ))
                changed = True
            # else: same concept follow-up — keep existing question lifecycle
```

#### 2c. Fix extension in completion handler (lines 199–207)

Replace the session completion block:
```python
        # 6. Handle session completion (only honor on final step to prevent premature endings)
        if output.session_complete:
            total = session.topic.study_plan.total_steps if session.topic else 0
            if session.current_step >= total:
                # Advance past final step to trigger is_complete
                while not session.is_complete:
                    if not session.advance_step():
                        break
                changed = True
            else:
                logger.warning(
                    f"LLM signaled session_complete on step {session.current_step}/{total}, ignoring"
                )
```

With:
```python
        # 6. Handle session completion
        if output.session_complete:
            total = session.topic.study_plan.total_steps if session.topic else 0
            if session.current_step >= total:
                if not session.allow_extension:
                    while not session.is_complete:
                        if not session.advance_step():
                            break
                    changed = True
                else:
                    # Extension mode: mark complete, advance past
                    while not session.is_complete:
                        if not session.advance_step():
                            break
                    changed = True
            else:
                logger.warning(
                    f"LLM signaled session_complete on step {session.current_step}/{total}, ignoring"
                )
```

Note: For true extension (ace students staying longer), the pacing directive in the turn prompt tells the tutor to keep going. The `allow_extension` flag on `process_turn` prevents the early-return short circuit so the tutor can still generate a response even after the plan is "done." The tutor itself controls when to finally set `session_complete=true`.

**Effort:** 3h (careful state logic + edge cases)

---

### 3. System Prompt: Consolidated and Tighter

**File:** `tutor/prompts/master_tutor_prompts.py`  
**Current:** 11 rules, ~700 tokens  
**Proposed:** 10 rules, ~650 tokens

**Design:** Removed response-length matching from rule #2 (moved to turn prompt as dynamic signal). Merged "Socratic correction" and "probe why" INTO rule #4 (replacing direct-correction guidance). Removed the old standalone length rule since it's now a turn-prompt signal. Net result: fewer rules, tighter prompt, new behaviors integrated.

Here is the **exact** replacement for `MASTER_TUTOR_SYSTEM_PROMPT`:

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

## How to Teach This Session

1. **Follow the study plan, but hide the scaffolding.** Each step is typed (explain,
   check, practice) — use that to guide what you do, but never mention step numbers
   or plan structure. Transitions should feel like natural conversation.

2. **Advance when ready — adapt your pace to the student.** When understanding is
   demonstrated, set `advance_to_step`. Don't linger. If mastery is high (>0.8),
   skip easy checks and go deeper — harder applications, edge cases, curveballs.
   If the student explicitly requests harder material, HONOR IT immediately.
   If struggling (2+ wrong), simplify: smaller steps, yes/no questions, more scaffolding.

3. **Track your questions.** When your response includes a question, fill in
   `question_asked`, `expected_answer`, and `question_concept`.

4. **Guide discovery — don't just correct.** When a student answers wrong:
   - 1st wrong attempt → ask a probing question to help them find the error themselves.
     ("What would happen if...?" "Walk me through how you got that.")
   - 2nd wrong attempt → give a targeted hint pointing at the specific error.
   - 3rd+ → explain directly and warmly.
   When a student changes their answer (especially correct→wrong), ask what made them
   change their mind BEFORE evaluating. When a student uses an unexpected strategy,
   explore their reasoning before correcting. These are golden teaching moments.
   - CRITICAL: Before praising, VERIFY the answer is actually correct. If the student
     says 7 when the answer is 70, that is WRONG. Check the specific value.

5. **Never repeat yourself.** Vary praise, structure, openings. Often the best response
   to a correct answer is no praise — just build on it. Skip recaps and go straight
   to the next challenge when momentum is good.

6. **Match the student's energy.** Build on their metaphors. Feed their curiosity.
   If confused, try a different angle. If off-topic, redirect warmly.

7. **Update mastery.** After evaluating: ~0.3 wrong, ~0.6 partial, ~0.8 correct,
   ~0.95 correct with reasoning.

8. **Be a real teacher.** Keep praise proportional — most correct answers need just a
   nod. Emojis: 0-2 per response. No ALL CAPS. Only promise examples you'll use.

9. **End naturally.** When the final step is mastered, wrap up in 2-4 sentences:
   acknowledge their last message, reflect on what THEY specifically learned (actual
   concepts, not generic praise), and sign off with something from the conversation.
   Set `session_complete=true`. Never use canned closings. Before ending, verify the
   student doesn't hold a misconception — if they do, correct it first.

10. **Never leak internal language.** Your `response` is shown directly to the student.
    Never use third-person ("The student's answer shows..."). Always speak TO them.
    Put analysis in `reasoning`.""",
    name="master_tutor_system",
)
```

**What changed vs. current prompt:**
- Rule #1: Trimmed verbosity (removed "Moving to Step 4" example)
- Rule #2: Removed response-length matching (→ turn prompt). Tightened pacing text.
- Rule #4: **Major rewrite.** Merged old rule #4 (direct correction), Issue 3 (Socratic protocol), and Issue 4 (probe "why") into one cohesive rule. The 3-attempt escalation, answer-change probing, and novel-strategy exploration are all here.
- Rule #9: Merged old rules #9 and #11 (end naturally + check misconceptions before ending)
- Old rule #10 (no internal language): kept as rule #10
- Net: 11 rules → 10 rules, fewer tokens, three new behaviors integrated

**Effort:** 1.5h (careful wording + testing prompt token count)

---

### 4. Turn Prompt: Add Dynamic Signals

**File:** `tutor/prompts/master_tutor_prompts.py`

Replace `MASTER_TUTOR_TURN_PROMPT` with:

```python
MASTER_TUTOR_TURN_PROMPT = PromptTemplate(
    """## Current Session State

**Current Step**: Step {current_step} of {total_steps} — {current_step_info}
**Content Hint**: {content_hint}
**Mastery Estimates**:
{mastery_formatted}
**Misconceptions Detected**: {misconceptions}
**Session So Far**: {turn_timeline}

## ⚡ This Turn
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

**Effort:** 0.5h

---

### 5. Master Tutor Agent: Compute Dynamic Signals

**File:** `tutor/agents/master_tutor.py`

#### 5a. Add `_compute_pacing_directive` method (new method on `MasterTutorAgent`)

```python
def _compute_pacing_directive(self, session: SessionState) -> str:
    """Synthesize session signals into an explicit pacing instruction."""
    turn = session.turn_count
    mastery_values = list(session.mastery_estimates.values())
    avg_mastery = sum(mastery_values) / len(mastery_values) if mastery_values else 0.0
    trend = session.session_summary.progress_trend

    # BUG FIX: turn_count is already 1 on first student message
    # (incremented at orchestrator.py line 108 before tutor runs)
    if turn == 1:
        return (
            "FIRST TURN: Keep your opening to 2-3 sentences. Ask ONE simple "
            "question to gauge level. Don't explain the topic yet."
        )

    if avg_mastery >= 0.8 and trend == "improving":
        if session.is_complete:
            return (
                "EXTEND: Student has aced the plan. Push to harder territory — "
                "bigger numbers, trickier problems, edge cases. Do NOT wrap up "
                "or defer to 'next session'. Challenge them. Keep responses concise."
            )
        return (
            "ACCELERATE: Student is acing this. Skip easy checks, go deeper. "
            "Harder applications, curveballs. Keep responses concise."
        )

    if avg_mastery < 0.4 or trend == "struggling":
        return (
            "SIMPLIFY: Student is struggling. Shorter sentences, 1-2 ideas per "
            "response. Yes/no or simple-choice questions. More check-ins."
        )

    return "STEADY: Progressing normally. One idea at a time."
```

#### 5b. Add `_compute_student_style` method

```python
def _compute_student_style(self, session: SessionState) -> str:
    """Compute response-length guidance from student's communication pattern."""
    student_msgs = [
        m for m in session.conversation_history if m.role == "student"
    ]
    if not student_msgs:
        return "Student style: unknown (first turn). Start short."

    avg_words = sum(len(m.content.split()) for m in student_msgs) / len(student_msgs)

    if avg_words <= 5:
        return (
            f"Student style: QUIET ({avg_words:.0f} words/msg avg). "
            "Respond in 2-3 sentences MAX. No walls of text."
        )
    elif avg_words <= 15:
        return f"Student style: moderate ({avg_words:.0f} words/msg). 3-5 sentences."
    else:
        return f"Student style: expressive ({avg_words:.0f} words/msg). Can elaborate."
```

#### 5c. Update `_build_turn_prompt` to use new signals and question lifecycle

In `_build_turn_prompt` (starting line 104), add computation and update the awaiting_answer_section:

```python
    # Compute dynamic signals
    pacing_directive = self._compute_pacing_directive(session)
    student_style = self._compute_student_style(session)

    # Build question lifecycle section
    if session.awaiting_response and session.last_question:
        q = session.last_question
        attempt_num = q.wrong_attempts + 1

        # Correction strategy guidance based on lifecycle phase
        if q.wrong_attempts == 0:
            strategy = "Evaluate their answer."
        elif q.wrong_attempts == 1:
            strategy = "Use a PROBING QUESTION — help them find the error themselves."
        elif q.wrong_attempts == 2:
            strategy = "Give a TARGETED HINT pointing at the specific error."
        else:
            strategy = "EXPLAIN directly and warmly."

        prev_answers = ""
        if q.previous_student_answers:
            prev_answers = (
                f"\nPrevious answers: {'; '.join(q.previous_student_answers[-3:])}"
                "\nIf student changed their answer, ASK WHY before evaluating."
            )

        awaiting_answer_section = (
            f"**IMPORTANT — Student is answering (attempt #{attempt_num}):**\n"
            f"Question: {q.question_text}\n"
            f"Expected: {q.expected_answer}\n"
            f"Concept: {q.concept}\n"
            f"{strategy}{prev_answers}"
        )
    else:
        awaiting_answer_section = ""
```

And pass the new variables to `render()`:

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

#### 5d. Expand `intent` field and add `correction_strategy`

In `TutorTurnOutput` (line 30):

```python
    intent: str = Field(
        description="What the student was doing: answer, answer_change, question, confusion, novel_strategy, off_topic, or continuation"
    )
```

Add new field after `mastery_signal`:

```python
    correction_strategy: Optional[str] = Field(
        default=None,
        description="When answer_correct=false: 'probe' (ask probing question), 'hint' (targeted hint), or 'explain' (direct). Follow the attempt guidance in the turn prompt."
    )
```

**Effort:** 4h (two new methods + turn prompt wiring + schema changes + testing)

---

## Implementation Order

| Phase | What | Depends On | Effort | Risk |
|-------|------|-----------|--------|------|
| **Phase 1** | Pacing directive + student style (Issues 1+2) | None | 5h | Low |
| | — `_compute_pacing_directive` with `turn==1` fix | | | |
| | — `_compute_student_style` | | | |
| | — Turn prompt template update | | | |
| | — System prompt consolidation (all 10 rules) | | | |
| **Phase 2** | Question lifecycle + Socratic + probe why (Issues 3+4) | Phase 1 prompt | 7h | Medium |
| | — `Question` model: `wrong_attempts`, `previous_student_answers`, `phase` | | | |
| | — `SessionState.allow_extension` | | | |
| | — Orchestrator `_apply_state_updates` rewrite | | | |
| | — Orchestrator extension logic | | | |
| | — Turn prompt awaiting_answer_section with lifecycle | | | |
| | — `TutorTurnOutput`: `correction_strategy`, expanded `intent` | | | |
| **Phase 3** | Unit tests | Phase 1+2 | 4h | Low |
| **Phase 4** | Eval run + iterate | Phase 1+2+3 | 3h | Low |
| | **Total** | | **19h** | |

---

## Unit Test Plan

**File:** `tests/test_pacing_directive.py`

| Test | What it verifies |
|------|-----------------|
| `test_first_turn_directive` | `turn_count=1` → returns FIRST TURN directive |
| `test_first_turn_not_zero` | `turn_count=0` → does NOT return first turn (pre-increment state) |
| `test_accelerate_high_mastery` | avg mastery ≥0.8 + improving → ACCELERATE |
| `test_extend_past_plan` | `is_complete=True` + high mastery → EXTEND |
| `test_simplify_struggling` | avg mastery <0.4 → SIMPLIFY |
| `test_simplify_trend` | trend="struggling" → SIMPLIFY |
| `test_steady_default` | mid mastery + steady → STEADY |

**File:** `tests/test_student_style.py`

| Test | What it verifies |
|------|-----------------|
| `test_no_messages` | Empty history → "unknown" |
| `test_quiet_student` | avg ≤5 words → QUIET |
| `test_moderate_student` | avg 6-15 words → moderate |
| `test_expressive_student` | avg >15 words → expressive |

**File:** `tests/test_question_lifecycle.py`

| Test | What it verifies |
|------|-----------------|
| `test_new_question_tracked` | `question_asked` with no pending → `set_question` called |
| `test_wrong_answer_increments_attempts` | `answer_correct=False` → `wrong_attempts += 1` |
| `test_wrong_answer_preserves_question` | `answer_correct=False` → `last_question` NOT cleared |
| `test_wrong_answer_records_student_answer` | Student answer appended to `previous_student_answers` |
| `test_wrong_answer_phase_progression` | 1st wrong → probe, 2nd → hint, 3rd → explain |
| `test_correct_answer_clears_question` | `answer_correct=True` → question cleared |
| `test_followup_same_concept_preserves_lifecycle` | `question_asked` on same concept → keeps `wrong_attempts` |
| `test_new_concept_question_replaces` | `question_asked` on different concept → new question |
| `test_probing_question_not_new_tracked_question` | `answer_correct=False` + `question_asked` → original question preserved |

**File:** `tests/test_extension.py`

| Test | What it verifies |
|------|-----------------|
| `test_extension_allows_post_plan_turns` | `is_complete=True` + `allow_extension=True` → tutor still runs |
| `test_no_extension_short_circuits` | `is_complete=True` + `allow_extension=False` → post-completion response |

**Effort:** 4h (mock SessionState, mock LLM not needed for pure logic tests)

---

## Validation Plan

Same as v1 — run 6-persona eval suite on 4-digit place value.

### Success Criteria
- Average score: 8.3+ (up from 7.7)
- Pacing dimension: 7.5+ (up from 6.8)
- No persona below 7.0
- `wrong_pacing` ≤ 3 (down from 7)
- `missed_student_signal` ≤ 4 (down from 6)
- `over_scaffolding` ≤ 1 (down from 3)
- System prompt token count ≤ current (regression test)

### Key Personas to Watch
| Issue | Persona | Metric |
|-------|---------|--------|
| Pacing | Arjun (ace) | Pacing 6→8, extension works |
| Pacing | Priya (struggler) | Pacing 5→7, SIMPLIFY kicks in |
| Length | Meera (quiet) | Authenticity 6→8, short responses |
| Socratic | Riya, Meera | Over-scaffolding 3→0-1 |
| Probe why | Riya, Kabir, Dev | Missed signals 6→2-3 |

---

## Files Modified (Summary)

| File | Changes |
|------|---------|
| `tutor/prompts/master_tutor_prompts.py` | Consolidated system prompt (11→10 rules, Socratic+probe merged into rule #4, end+misconception check merged into rule #9). Turn prompt: added `{pacing_directive}`, `{student_style}` |
| `tutor/agents/master_tutor.py` | New: `_compute_pacing_directive()`, `_compute_student_style()`. Updated: `_build_turn_prompt()` to pass new vars and lifecycle-aware awaiting section. Schema: added `correction_strategy`, expanded `intent` |
| `tutor/models/session_state.py` | `Question`: added `wrong_attempts`, `previous_student_answers`, `phase`. `SessionState`: added `allow_extension` |
| `tutor/orchestration/orchestrator.py` | `process_turn`: extension-aware completion check. `_apply_state_updates`: complete rewrite of question tracking (lifecycle state machine) and extension-aware completion |
| `tests/test_pacing_directive.py` | New: 7 unit tests |
| `tests/test_student_style.py` | New: 4 unit tests |
| `tests/test_question_lifecycle.py` | New: 9 unit tests |
| `tests/test_extension.py` | New: 2 unit tests |
