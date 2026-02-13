# IMPROVEMENT_PLAN.md — Senior Engineer Review

**Reviewer:** Automated code review  
**Date:** Feb 13, 2026

---

## 🔴 Critical: All File Paths in the Plan Are Wrong

The plan consistently references a **non-existent path structure**. Every single file path in the "Files Modified (Summary)" table and throughout the document is wrong:

| Plan Says | Actual Path |
|-----------|-------------|
| `tutor/prompts/master_tutor_prompts.py` | `tutor/prompts/master_tutor_prompts.py` ✅ (this one is correct) |
| `tutor/agents/master_tutor.py` | `tutor/agents/master_tutor.py` ✅ (correct) |
| `tutor/models/session_state.py` | `tutor/models/session_state.py` ✅ (correct) |
| `tutor/orchestration/orchestrator.py` | `tutor/orchestration/orchestrator.py` ✅ (correct) |

**Update:** The paths in the plan are actually correct relative to the repo root. The *original task description* gave wrong paths (`shared/prompts/`, `shared/services/`), but the plan itself uses the right `tutor/` prefix. **No path issues in the plan itself.**

---

## Issue 1: Pacing Directive — Review

### ✅ Feasible, but line number references are off

The plan references "lines 10-100" for `MASTER_TUTOR_SYSTEM_PROMPT` and "lines 103-120" for `MASTER_TUTOR_TURN_PROMPT`. Actual locations:
- `MASTER_TUTOR_SYSTEM_PROMPT`: lines 13–80 (the PromptTemplate definition)
- `MASTER_TUTOR_TURN_PROMPT`: lines 83–99

Not a blocker, but shows the plan was written from memory, not from the code.

### ⚠️ `_compute_pacing_directive` references wrong method name and location

The plan says to add `_compute_pacing_directive` to `_build_turn_prompt` at "around line 90" in `tutor/agents/master_tutor.py`. The actual `_build_turn_prompt` method starts at **line 104**. The method signature and structure match what the plan expects though — this is feasible.

### ⚠️ `session.session_summary.progress_trend` — works, but initialized late

The plan's `_compute_pacing_directive` reads `session.session_summary.progress_trend`. Looking at `orchestrator.py` lines 155-163, `progress_trend` is updated **after** the tutor call, not before. So on any given turn, the pacing directive will use the *previous turn's* trend value. This is actually fine (you want to react to what happened), but worth noting — on turn 1, `progress_trend` defaults to `"steady"` (session_state.py line 72), so the FIRST TURN logic must be triggered by `turn_count`, not trend. The plan correctly uses `turn == 0` for this.

### ⚠️ `session.turn_count` is 0 on first real turn? No.

The plan checks `if turn == 0` for first turn. But looking at `orchestrator.py` line 108: `session.increment_turn()` is called **before** the master tutor executes. So by the time `_compute_pacing_directive` runs, `turn_count` is already 1 on the first real student message. The check should be `if turn == 1` or better, check `len(session.conversation_history) <= 1`.

**This is a bug in the plan.**

### ⚠️ Extension mechanism — `is_complete` check is correct but incomplete

The plan proposes adding `allow_extension: bool` to `SessionState` and modifying the completion check. Looking at `orchestrator.py` lines 100-107:

```python
if session.is_complete:
    session.add_message(create_student_message(student_message))
    response = await self._generate_post_completion_response(session, student_message)
    return TurnResult(...)
```

This is a hard early return. The plan's fix (`if session.is_complete and not session.allow_extension`) would work. However, there's a subtlety: `is_complete` (session_state.py line 89) checks `current_step > total_steps`. The completion is triggered in `_apply_state_updates` (orchestrator.py lines 199-207) which advances past the final step. So the extension mechanism also needs to prevent `_apply_state_updates` from advancing past the final step when `allow_extension=True`. The plan doesn't address this — it only modifies the `process_turn` early return, not the `_apply_state_updates` completion logic.

**This is a gap — you'd get one extra turn but then `is_complete` would still be True on the next turn.**

### Effort estimate: 3-4h → **Reasonable, maybe 4-5h** given the edge cases above.

---

## Issue 2: Response Length Calibration — Review

### ✅ Straightforward and feasible

The `_compute_student_style` method accesses `session.conversation_history` which contains `Message` objects. Need to verify the `Message` model has a `content` field and `role` field.

Looking at the imports in session_state.py: `from tutor.models.messages import Message, StudentContext`. The plan assumes `m.role == "student"` and `m.content` — these need to match the actual `Message` model. I don't have the messages.py file, but given the code in `format_conversation_history` and how messages are created via `create_student_message`/`create_teacher_message`, this is almost certainly correct.

### ⚠️ Template variable injection

The plan says to add `{student_style}` to `MASTER_TUTOR_TURN_PROMPT`. Looking at `_build_turn_prompt` (master_tutor.py line 140), the `render()` call passes explicit kwargs. You'd need to:
1. Add `{student_style}` to the template string
2. Add `student_style=...` to the `render()` call

The plan mentions this but doesn't show the render() call update explicitly. Minor, but could be missed.

### Effort estimate: 2h → **Accurate.**

---

## Issue 3: Socratic Correction — Review

### ⚠️ `Question` class has no `wrong_attempts` field — plan is correct about adding it

The actual `Question` class (session_state.py lines 37-43) has: `question_text`, `expected_answer`, `concept`, `rubric`, `hints`, `hints_used`. The plan proposes adding `wrong_attempts: int`. This is clean and compatible.

### 🔴 State update logic has a subtle bug

The plan proposes (Issue 3c):
```python
elif output.answer_correct is False and session.last_question:
    session.last_question.wrong_attempts += 1
    # Don't clear the question — let student try again
```

Looking at the actual `_apply_state_updates` (orchestrator.py lines 184-192):
```python
if output.question_asked:
    session.set_question(Question(...))
    changed = True
elif output.answer_correct is not None:
    session.clear_question()
    changed = True
```

The current logic clears the question whenever `answer_correct is not None` (true OR false) and no new question was asked. The plan's change would need to modify this `elif` to only clear on `answer_correct=True`. But there's a problem: when the tutor asks a probing follow-up question after a wrong answer, `output.question_asked` would be set (the probing question), which would **replace** the original question and lose the `wrong_attempts` counter.

**Fix needed:** The probing question should either (a) be a different field (e.g. `follow_up_question`), or (b) the `wrong_attempts` counter should be preserved when setting a new question on the same concept. The plan doesn't handle this.

### ⚠️ `correction_strategy` field — good forcing function but needs prompt reinforcement

Adding `correction_strategy: Optional[str]` to `TutorTurnOutput` is a good idea. But the model won't reliably use it unless the system prompt explicitly references it. The plan updates rule #4 but doesn't mention connecting rule #4 to the schema field description. The field's own description is sufficient for some models, but for reliability, the system prompt should say "Set `correction_strategy` to 'probe', 'hint', or 'explain'."

### Effort estimate: 4-5h → **More like 5-7h** given the state management complexity above.

---

## Issue 4: Probe "Why" — Review

### ✅ Prompt additions are clean and feasible

Adding a new rule #5 to the system prompt is straightforward. The expanded `intent` values (`answer_change`, `novel_strategy`) are a good addition.

### ⚠️ `previous_student_answers` tracking has a dependency on Issue 3

The plan says to add `previous_student_answers: list[str]` to `Question`. But if Issue 3's state changes are also applied, the interaction between `wrong_attempts` increment and `previous_student_answers` append needs to happen in the same code path. The plan treats them as separate changes but they both modify `_apply_state_updates` in overlapping areas.

### ⚠️ Getting the student message text in `_apply_state_updates`

The plan proposes:
```python
if session.last_question and output.intent in ("answer", "answer_change"):
    session.last_question.previous_student_answers.append(student_message_text)
```

But `_apply_state_updates` (orchestrator.py line 172) only receives `(session, output)` — it doesn't have `student_message_text`. You'd need to either:
1. Pass `student_message` to `_apply_state_updates` (method signature change)
2. Pull it from `session.conversation_history[-1].content`

The plan doesn't mention this. Option 2 works since the student message is added to history before the tutor runs (orchestrator.py line 109).

### Effort estimate: 3h → **Accurate if done after Issue 3**, otherwise +1h for the overlapping state logic.

---

## Cross-Cutting Concerns

### 1. Prompt length bloat

Issues 1-4 collectively add ~500-800 tokens to the system prompt and ~200-400 tokens to the turn prompt. The current system prompt is already ~700 tokens. This nearly doubles it. For models with limited attention, the added rules may actually reduce compliance with existing rules.

**Recommendation:** After adding new rules, re-number and possibly consolidate. Consider moving the most important directives (pacing, length matching) to the turn prompt where they have higher salience, and keeping the system prompt for general personality/approach.

### 2. No tests mentioned

The plan mentions an eval suite but zero unit tests for the new methods (`_compute_pacing_directive`, `_compute_student_style`, modified `_apply_state_updates`). These are pure logic functions that are easily testable.

**Recommendation:** Add unit tests for each new method. Especially for edge cases: empty conversation history, zero mastery values, no last_question when answer_correct is set, etc. Budget +2-3h.

### 3. `PromptTemplate.render()` — verify it supports new variables

The plan adds `{pacing_directive}` and `{student_style}` to `MASTER_TUTOR_TURN_PROMPT`. Need to verify `PromptTemplate.render()` doesn't fail on unexpected kwargs or missing kwargs. Looking at `tutor/prompts/templates.py` would confirm this, but it's likely a simple `.format(**kwargs)` which would raise `KeyError` if a template variable isn't passed.

### 4. Total effort estimate

| Issue | Plan Estimate | Revised Estimate |
|-------|--------------|------------------|
| Issue 1 (Pacing) | 3-4h | 4-5h |
| Issue 2 (Length) | 2h | 2h |
| Issue 3 (Socratic) | 4-5h | 5-7h |
| Issue 4 (Probe) | 3h | 3-4h |
| Unit tests | not estimated | 2-3h |
| **Total** | **12-14h** | **16-21h** |

---

## Summary of Bugs / Gaps to Fix Before Implementation

1. **🔴 Turn count off-by-one:** `_compute_pacing_directive` checks `turn == 0` but `turn_count` is already 1 on first student message. Use `turn == 1` or check conversation history length.

2. **🔴 Extension mechanism incomplete:** Plan only modifies `process_turn` early return but doesn't prevent `_apply_state_updates` from advancing past final step. Extension would only last one turn.

3. **🔴 Probing question replaces tracked question:** When tutor asks a Socratic follow-up after wrong answer, `output.question_asked` overwrites `last_question`, losing `wrong_attempts` counter.

4. **⚠️ `_apply_state_updates` doesn't receive `student_message`:** Needed for `previous_student_answers` tracking. Use `session.conversation_history[-1].content` or change method signature.

5. **⚠️ No unit tests budgeted.**

6. **⚠️ Prompt length nearly doubles — may reduce model compliance with existing rules.**

---

## Overall Assessment

The plan is **well-reasoned and directionally correct**. The root cause analysis is solid and the proposed changes target the right areas. The main risks are:

- **State management complexity** (Issues 3-4) is underestimated. The interaction between question tracking, wrong attempt counting, and Socratic follow-ups needs careful design.
- **Three specific bugs** would cause issues if implemented as-written (turn count, extension, question replacement).
- **Effort is ~40-50% underestimated** when accounting for tests and edge cases.

**Recommendation:** Implement Issues 1+2 first as planned (they're clean and independent). Before implementing Issues 3+4, write a detailed state machine diagram for the question lifecycle (asked → wrong_attempt → probe → wrong_attempt → hint → wrong_attempt → explain → clear). The current plan treats this as simple field additions but it's actually a state machine change.
