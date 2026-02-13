# Tutor Improvement Plan — R3 → R4

**Date:** Feb 13, 2026  
**Current avg score:** 7.7/10  
**Target:** 8.5+/10  
**Remaining issues:** All prompt/design-level (no model capability issues remain)

---

## Executive Summary

Round 3 achieved a +1.4 jump (6.3→7.7) by fixing critical bugs (system note leaks, wrong-answer validation, inverted understanding). The remaining gap is **adaptiveness** — the tutor delivers solid teaching but can't modulate style per student. Four issues account for the majority of remaining deductions:

1. **Rigid pacing** (7 occurrences of `wrong_pacing`) — weakest dimension at 6.8/10
2. **One-size-fits-all response length** (6 `missed_student_signal`) — walls of text to quiet students
3. **Direct correction over guided discovery** (3 `over_scaffolding`) — tells answers instead of probing
4. **Missed opportunities to probe "why"** (part of `missed_student_signal`) — doesn't investigate answer changes or wrong strategies

All fixes are prompt-level + minor code changes. No architectural changes needed.

---

## Issue 1: Rigid Pacing (P0)

### Symptoms
- **Arjun (Ace, 7.4):** Pacing scored 6/10. Tutor defers harder material to "next session" instead of escalating in real-time. Never pushed to 5-digit territory despite Arjun asking for it.
- **Priya (Struggler, 6.8):** Pacing scored 5/10. Dense multi-analogy explanations for a student who needs simple short steps.
- **All personas:** Turn 1 is consistently too dense/long regardless of student type.

### Root Cause Analysis

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_SYSTEM_PROMPT` (lines 10-100)

The prompt already contains pacing guidance in rule #2 (lines ~30-42):
```
- If the student gets 3+ correct answers at the current difficulty, escalate complexity.
- If the student explicitly requests harder material, HONOR IT...
- If the student is struggling (2+ incorrect answers), simplify...
- Match response length to the student's...
```

**Problem 1: Rules are buried.** Rule #2 is one of 11 rules in a long system prompt. By the time the model processes the turn prompt with all the session state, these pacing rules have low salience. The model defaults to its natural tendency: thorough, mid-pace explanations.

**Problem 2: No pacing signal in the turn prompt.** The turn prompt (`MASTER_TUTOR_TURN_PROMPT`, lines 103-120) provides `mastery_formatted` and `turn_timeline`, but doesn't synthesize these into a pacing directive. The model must infer pacing from raw mastery numbers — it doesn't.

**Problem 3: No mechanism to go beyond the study plan.** `SessionState.is_complete` (in `tutor/models/session_state.py`, line 89) returns `True` when `current_step > total_steps`. The orchestrator (`tutor/orchestration/orchestrator.py`, lines 90-97) short-circuits to `_generate_post_completion_response` when complete. There's no concept of "extend beyond plan" for aces — the study plan is a ceiling, not a floor.

**Problem 4: Turn 1 has no student signal yet.** On the first turn, `conversation_history` is `"(No prior messages — this is the first turn)"` and there's no student message to calibrate against. The prompt doesn't have a specific "first turn should be SHORT" directive.

### Proposed Changes

#### 1a. Add pacing directive to turn prompt

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_TURN_PROMPT`

Add a computed `{pacing_directive}` variable that the orchestrator/master_tutor builds from session state:

```python
MASTER_TUTOR_TURN_PROMPT = PromptTemplate(
    """## Current Session State

**Current Step**: Step {current_step} of {total_steps} — {current_step_info}
**Content Hint**: {content_hint}
**Mastery Estimates**:
{mastery_formatted}
**Misconceptions Detected**: {misconceptions}
**Session So Far**: {turn_timeline}

## ⚡ Pacing Directive
{pacing_directive}

{awaiting_answer_section}

## Conversation History
{conversation_history}

## Student's Message
{student_message}

Respond as the tutor. Return your response in the structured output format.""",
    name="master_tutor_turn",
)
```

#### 1b. Compute pacing directive in master_tutor.py

**File:** `tutor/agents/master_tutor.py`, method `_build_turn_prompt` (around line 90)

Add pacing computation logic:

```python
def _compute_pacing_directive(self, session: SessionState) -> str:
    """Synthesize session signals into an explicit pacing instruction."""
    turn = session.turn_count
    mastery_values = list(session.mastery_estimates.values())
    avg_mastery = sum(mastery_values) / len(mastery_values) if mastery_values else 0.0
    trend = session.session_summary.progress_trend
    recent_timeline = session.session_summary.turn_timeline[-3:]
    
    if turn == 0:
        return (
            "FIRST TURN: Keep your opening to 2-3 sentences max. Ask ONE simple "
            "question to gauge the student's level. Do NOT explain the topic yet — "
            "discover what they already know first."
        )
    
    if avg_mastery >= 0.8 and trend == "improving":
        return (
            "ACCELERATE: Student is acing this. Skip remaining easy checks. "
            "Push to harder applications, edge cases, or extend beyond the plan "
            "(e.g., larger numbers, trickier comparisons). Do NOT defer to 'next session'. "
            "Challenge them NOW. Keep responses concise — they don't need long explanations."
        )
    
    if avg_mastery < 0.4 or trend == "struggling":
        return (
            "SIMPLIFY: Student is struggling. Use shorter sentences (1-2 ideas per response). "
            "Break the current concept into smaller pieces. Ask yes/no or simple-choice "
            "questions instead of open-ended ones. More check-ins, less lecturing."
        )
    
    return (
        "STEADY: Student is progressing normally. Match your response length to theirs. "
        "Keep explanations focused on one idea at a time."
    )
```

Then call it in `_build_turn_prompt`:
```python
pacing_directive = self._compute_pacing_directive(session)
```
And pass it to `MASTER_TUTOR_TURN_PROMPT.render(...)`.

#### 1c. Add extension mechanism for aces

**File:** `tutor/models/session_state.py`

Add a field to allow extending beyond the plan:

```python
# In SessionState class (around line 82)
allow_extension: bool = Field(default=True, description="Allow tutor to teach beyond study plan for advanced students")
```

**File:** `tutor/orchestration/orchestrator.py`, `process_turn` method (lines 90-97)

Modify the completion check to allow extension:

```python
# Replace the hard stop
if session.is_complete and not session.allow_extension:
    # ... existing post-completion logic
```

And in the system prompt, add guidance that when all steps are done but mastery is high, the tutor can push further.

### Expected Impact
- **Arjun** pacing: 6 → 8 (+2). The pacing directive will explicitly tell the model to escalate.
- **Priya** pacing: 5 → 7 (+2). SIMPLIFY directive will force shorter exchanges.
- **All personas** Turn 1: density drops significantly with the FIRST TURN directive.
- Overall pacing dimension: 6.8 → 8.0+

### Risk Assessment
- **Low risk.** Pacing directive is additive — doesn't change core prompt logic, just adds a clear signal.
- **Watch for:** Over-acceleration (skipping needed practice). Mitigate by keeping the mastery threshold at 0.8.
- **Watch for:** FIRST TURN being too sparse for some personas. The "ask ONE question" approach should work for all types but monitor.

### Effort
**~3-4 hours.** Prompt changes + `_compute_pacing_directive` method + turn prompt template update + extension field.

---

## Issue 2: One-Size-Fits-All Response Length (P0)

### Symptoms
- **Meera (Quiet, 7.0):** Gives 1-5 word responses, receives multi-paragraph walls every turn. Authenticity scored 6/10 (lowest) due to template feel: "praise → analogy → table → question."
- Pattern applies broadly — tutor never calibrates verbosity to student's communication style.

### Root Cause Analysis

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_SYSTEM_PROMPT`, rule #2

The rule says "Match response length to the student's" but this is a single line buried in a dense rule. The model doesn't operationalize it because:

1. **No length signal in turn prompt.** The turn prompt doesn't include any metric about the student's message length or communication pattern. The model sees the raw conversation history but doesn't get an explicit "this student uses short messages" signal.

2. **Structured output encourages verbosity.** The `TutorTurnOutput` schema (`tutor/agents/master_tutor.py`, lines 24-65) has many fields to fill. The model tends to generate longer `response` text to "justify" the structured analysis it's doing internally.

3. **No response length constraint.** There's no max-length guidance conditional on student behavior.

### Proposed Changes

#### 2a. Add student communication style to turn prompt

**File:** `tutor/agents/master_tutor.py`, `_build_turn_prompt`

Compute and inject a communication style signal:

```python
def _compute_student_style(self, session: SessionState) -> str:
    """Analyze student's communication pattern from history."""
    student_msgs = [
        m for m in session.conversation_history if m.role == "student"
    ]
    if not student_msgs:
        return "Unknown (first turn) — start SHORT and adjust."
    
    avg_words = sum(len(m.content.split()) for m in student_msgs) / len(student_msgs)
    
    if avg_words <= 5:
        return (
            "QUIET STUDENT (avg {:.0f} words/msg). Keep responses to 2-3 sentences MAX. "
            "Ask simple, direct questions. No multi-paragraph explanations. "
            "Match their energy — be conversational, not lecturing."
        ).format(avg_words)
    elif avg_words <= 15:
        return "MODERATE communicator (avg {:.0f} words). Keep responses to 3-5 sentences.".format(avg_words)
    else:
        return "EXPRESSIVE student (avg {:.0f} words). You can elaborate more, but stay focused.".format(avg_words)
```

Add `{student_style}` to `MASTER_TUTOR_TURN_PROMPT` right after the pacing directive.

#### 2b. Elevate length-matching in system prompt

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_SYSTEM_PROMPT`

Move response-length matching out of rule #2 into its own top-level rule (make it rule #2, shift others down):

```
2. **Match the student's communication style.** This is NON-NEGOTIABLE.
   - If student gives 1-5 word answers: respond in 2-3 sentences. Period.
   - If student gives medium responses: 3-5 sentences.
   - If student writes paragraphs: you can elaborate.
   - NEVER send a multi-paragraph response to a quiet student.
   - Vary your response structure. Don't always follow "praise → explain → question."
     Sometimes just ask a question. Sometimes just build on their answer.
```

### Expected Impact
- **Meera** authenticity: 6 → 8 (+2). Shorter responses will feel more natural.
- **Meera** overall: 7.0 → 8.0+
- Broadly improves authenticity across all personas (7.5 → 8.0+).

### Risk Assessment
- **Low risk.** Worst case: responses become too terse for students who need explanation. Mitigated by the SIMPLIFY pacing directive which explicitly says to break into smaller pieces (not just shorter).
- **Watch for:** Struggler (Priya) getting responses that are too short to be helpful. The pacing directive handles this — SIMPLIFY says "more check-ins" not just "shorter."

### Effort
**~2 hours.** Prompt edits + `_compute_student_style` method + template variable.

---

## Issue 3: Direct Correction Instead of Guided Discovery (P1)

### Symptoms
- **Riya:** Tutor directly explained the correct comparison approach instead of asking probing questions.
- **Meera:** Repeated wrong answer — tutor explained the right answer instead of guiding her.
- **Kabir:** Ordering logic corrected directly instead of asking him to test his strategy.

### Root Cause Analysis

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_SYSTEM_PROMPT`, rule #4

Rule #4 says: "When correcting, be warm but direct — explain why, don't just say 'not quite.'" This **actively encourages direct correction**. The phrase "be warm but direct" is interpreted by the model as "explain the right answer."

There is no Socratic questioning guidance anywhere in the prompt. The model's default behavior when it sees `answer_correct=false` is to explain — because the prompt tells it to.

**File:** `tutor/agents/master_tutor.py`, `TutorTurnOutput` schema (lines 24-65)

The structured output has `answer_correct` and `misconceptions_detected` but no field for "strategy for correction" (e.g., "probe", "hint", "direct_explain"). The model decides correction strategy implicitly with no prompt guidance favoring Socratic approaches.

### Proposed Changes

#### 3a. Replace "direct correction" with Socratic protocol

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_SYSTEM_PROMPT`, rule #4

Replace the current rule #4 with:

```
4. **Use guided discovery when students make errors.** When a student gives a wrong answer:
   - FIRST ATTEMPT: Ask a probing question that helps them see the error themselves.
     Examples: "What would happen if we tried that with a simpler number?"
     "Can you walk me through how you got that?" "Let's check — what is 4 × 100?"
   - SECOND ATTEMPT: Give a targeted hint pointing toward the specific error.
   - THIRD ATTEMPT: Explain directly, warmly.
   - NEVER jump straight to the correct answer on first wrong attempt.
   - Set `answer_correct=false` and note the misconception, but let the student
     try to self-correct before you explain.
```

#### 3b. Add correction_strategy to structured output

**File:** `tutor/agents/master_tutor.py`, `TutorTurnOutput`

Add a field to make the model explicitly choose its correction approach:

```python
correction_strategy: Optional[str] = Field(
    default=None,
    description="When answer_correct=false, your strategy: 'probe' (ask probing question), 'hint' (give targeted hint), or 'explain' (direct explanation). Use 'probe' on first wrong attempt, 'hint' on second, 'explain' on third."
)
```

This forces the model to think about its correction approach explicitly rather than defaulting to explanation.

#### 3c. Track wrong-attempt count per question

**File:** `tutor/models/session_state.py`, `Question` class (line 35)

Add:
```python
wrong_attempts: int = Field(default=0, description="Number of wrong attempts on this question")
```

**File:** `tutor/orchestration/orchestrator.py`, `_apply_state_updates` (around line 175)

When `answer_correct is False` and there's an active question, increment `wrong_attempts` instead of clearing the question:

```python
elif output.answer_correct is False and session.last_question:
    session.last_question.wrong_attempts += 1
    # Don't clear the question — let student try again
elif output.answer_correct is True:
    session.clear_question()
```

#### 3d. Inject attempt count into turn prompt

**File:** `tutor/agents/master_tutor.py`, `_build_turn_prompt`

When `session.awaiting_response`, include the attempt count:

```python
awaiting_answer_section = (
    f"**IMPORTANT — Student is answering this question (attempt #{q.wrong_attempts + 1}):**\n"
    f"Question: {q.question_text}\n"
    f"Expected Answer: {q.expected_answer}\n"
    f"Concept: {q.concept}\n"
    f"{'Use PROBING QUESTION — do not explain the answer yet.' if q.wrong_attempts == 0 else ''}"
    f"{'Give a TARGETED HINT.' if q.wrong_attempts == 1 else ''}"
    f"{'You may now EXPLAIN DIRECTLY.' if q.wrong_attempts >= 2 else ''}"
)
```

### Expected Impact
- **Over-scaffolding** root cause: 3 → 0-1 occurrences.
- **Explanation quality** likely stays same or improves (Socratic discovery is better pedagogy).
- **Responsiveness** improves — model is reacting to student errors more thoughtfully.
- Estimated +0.3-0.5 on avg score.

### Risk Assessment
- **Medium risk.** Socratic questioning is harder for the model to do well. Bad probing questions could frustrate students.
- **Mitigate:** The 3-attempt escalation ensures students aren't stuck forever. Monitor Priya (struggler) closely — she may need direct explanation sooner. Consider making the threshold 2 attempts for struggling students (tie into pacing directive).
- **Watch for:** Model generating fake "probing" questions that are actually just restating the answer as a question ("Isn't it actually 70?"). Add negative example to prompt if this occurs.

### Effort
**~4-5 hours.** Prompt rewrite + new schema field + attempt tracking in state + orchestrator logic change + turn prompt update.

---

## Issue 4: Missed Opportunities to Probe "Why" (P1)

### Symptoms
- **Riya:** Changed a correct answer to incorrect — tutor didn't ask why.
- **Meera:** Self-doubt pattern noted but only got surface-level "trust your instinct."
- **Kabir:** Digit-sum strategy invented — tutor corrected but didn't explore where the idea came from.
- **Dev:** Exit misconception ("more big digits = bigger") — session wrapped up instead of digging in.

### Root Cause Analysis

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_SYSTEM_PROMPT`

There is **no rule about probing answer changes or novel student strategies.** The prompt tells the model to "evaluate answers carefully" (rule #4) and "check for misconceptions before ending" (rule #11), but never says:

- "If a student changes their answer, ask why before proceeding"
- "If a student uses an unexpected strategy, explore it"
- "If a student shows a pattern (e.g., self-doubt), address it explicitly"

**File:** `tutor/agents/master_tutor.py`, `TutorTurnOutput`

The `intent` field (line 29) categorizes student messages as: `answer, question, confusion, off_topic, continuation`. There's no category for "answer_change" or "novel_strategy" — the model doesn't have a vocabulary for these important pedagogical moments.

**File:** `tutor/models/session_state.py`, `SessionState`

No tracking of previous answers. The `last_question` tracks the current question and expected answer, but not the student's previous attempt. When a student changes from correct→incorrect, there's no signal to the model that a change occurred.

### Proposed Changes

#### 4a. Add "probe why" rule to system prompt

**File:** `tutor/prompts/master_tutor_prompts.py`, `MASTER_TUTOR_SYSTEM_PROMPT`

Add as a new high-priority rule (insert after rule #4):

```
5. **Probe "why" at critical moments.** These are golden teaching opportunities — don't skip them:
   - **Answer change:** If a student changes their answer (especially correct → incorrect), 
     ALWAYS ask "What made you change your mind?" before evaluating.
   - **Novel strategy:** If a student uses an unexpected method (even a wrong one), ask them to 
     explain their thinking. Understanding their reasoning is more valuable than correcting the answer.
   - **Repeated pattern:** If you notice a pattern (always second-guessing, always rushing, always 
     adding instead of multiplying), name it gently and explore it.
   - **Exit misconceptions:** If you detect a misconception in the student's last 1-2 messages 
     before session end, you MUST probe it. Never close on an unresolved misconception.
```

#### 4b. Expand intent categories

**File:** `tutor/agents/master_tutor.py`, `TutorTurnOutput`

Update the `intent` field description:

```python
intent: str = Field(
    description="What the student was doing: answer, answer_change, question, confusion, novel_strategy, off_topic, or continuation"
)
```

This forces the model to distinguish between a regular answer and an answer change or novel strategy, which triggers different behavior in the prompt.

#### 4c. Track previous answer in session state

**File:** `tutor/models/session_state.py`, `Question` class

Add:
```python
previous_student_answers: list[str] = Field(default_factory=list, description="Student's previous answers to this question")
```

**File:** `tutor/orchestration/orchestrator.py`, `_apply_state_updates`

When processing an answer (correct or not), if there's an active question, append the student's message to `previous_student_answers`:

```python
if session.last_question and output.intent in ("answer", "answer_change"):
    session.last_question.previous_student_answers.append(student_message_text)
```

#### 4d. Surface previous answers in turn prompt

**File:** `tutor/agents/master_tutor.py`, `_build_turn_prompt`

When building the awaiting_answer_section, include previous attempts:

```python
if q.previous_student_answers:
    prev = "; ".join(q.previous_student_answers)
    awaiting_answer_section += f"\nStudent's previous answers to this question: {prev}\n"
    awaiting_answer_section += "If the student changed their answer, ASK WHY before evaluating.\n"
```

### Expected Impact
- **Missed_student_signal** root cause: 6 → 2-3 occurrences.
- Riya, Meera, Kabir, Dev all improve — these are the personas where "why" probing was flagged.
- Estimated +0.3 on avg score, with largest gains on Responsiveness dimension.

### Risk Assessment
- **Low risk.** Adding "probe why" is purely additive. Worst case: model over-probes and slows pacing. Mitigate by limiting to "critical moments" (answer changes, novel strategies, exit misconceptions).
- **Watch for:** Model asking "why did you change your mind?" when student didn't actually change their answer (hallucinating a change). The `previous_student_answers` tracking helps ground this.

### Effort
**~3 hours.** Prompt additions + intent expansion + state tracking + turn prompt injection.

---

## Implementation Order & Dependencies

| Priority | Issue | Depends On | Effort | Expected Impact |
|----------|-------|-----------|--------|-----------------|
| 1 | **Pacing directive** (Issue 1) | None | 3-4h | +0.5-0.8 avg |
| 2 | **Response length calibration** (Issue 2) | None (can parallel with #1) | 2h | +0.3-0.5 avg |
| 3 | **Socratic correction** (Issue 3) | None, but benefits from #1 (pacing-aware attempt thresholds) | 4-5h | +0.3-0.5 avg |
| 4 | **Probe "why"** (Issue 4) | Benefits from #3 (attempt tracking infrastructure) | 3h | +0.2-0.3 avg |

**Recommended approach:** Implement #1 and #2 together (they're independent), run R4 eval. Then implement #3 and #4 together, run R5 eval.

**Total effort:** ~12-14 hours of engineering work across both rounds.

---

## Validation Plan

### Which personas to watch per issue

| Issue | Primary Personas | Key Dimensions | Target Score |
|-------|-----------------|----------------|--------------|
| Pacing | Arjun (ace), Priya (struggler) | Pacing | Arjun: 6→8, Priya: 5→7 |
| Response length | Meera (quiet) | Authenticity, Responsiveness | Meera: 6→8 (authenticity) |
| Socratic correction | Riya (average), Meera (quiet) | Explanation quality | Over-scaffolding: 3→0-1 |
| Probe "why" | Riya, Kabir, Dev | Responsiveness | Missed_student_signal: 6→2-3 |

### Eval methodology
- Run same 6-persona eval suite on same topic (4-digit place value) for direct comparison
- Track root cause distribution: `wrong_pacing` should drop from 7 to ≤2, `missed_student_signal` from 6 to ≤3
- Overall pacing dimension should rise from 6.8 to 8.0+
- Watch for regressions in Explanation Quality (currently 8.2) — Socratic changes shouldn't hurt this
- After R4, run multi-topic validation (fractions, geometry) per R3 report P2 recommendation

### Success criteria for R4
- Average score: 8.3+ (up from 7.7)
- Pacing dimension average: 7.5+
- No persona below 7.0
- `wrong_pacing` occurrences: ≤3 (down from 7)
- `missed_student_signal` occurrences: ≤4 (down from 6)

---

## Files Modified (Summary)

| File | Changes |
|------|---------|
| `tutor/prompts/master_tutor_prompts.py` | New rules (#2 length matching, #5 probe why), rewrite rule #4 (Socratic), add `{pacing_directive}` and `{student_style}` to turn prompt |
| `tutor/agents/master_tutor.py` | Add `_compute_pacing_directive()`, `_compute_student_style()`, new `correction_strategy` field on `TutorTurnOutput`, expanded `intent` values, pass new variables to turn prompt |
| `tutor/models/session_state.py` | Add `allow_extension` to `SessionState`, add `wrong_attempts` and `previous_student_answers` to `Question` |
| `tutor/orchestration/orchestrator.py` | Modify completion check for extension, update `_apply_state_updates` for attempt tracking |
| `evaluation/evaluator.py` | No changes needed (evaluator already covers all relevant dimensions) |
