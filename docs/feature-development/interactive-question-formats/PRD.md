# PRD: Interactive Question Formats

**Status:** Draft
**Date:** 2026-03-19

---

## Context & Problem

### What We Have Today

During teach_me sessions, after the explanation phase, the tutor asks questions to check understanding. These questions fall into several natural categories:

1. **Fill-in-the-blank** — Tutor writes a sentence with blanks (`"addends are __ and __, sum is __"`), student fills in the missing words
2. **Pick-from-options** — Tutor asks "which of these is X?" with a list of choices
3. **Open-ended** — "Explain in your own words why..."

All three are currently rendered as plain markdown text, and the student answers via a single text input box + mic at the bottom of the screen.

### What's Wrong

**Fill-in-the-blank is confusing.** The tutor shows `"addends are __ and __"` but the student has to type their answer in a separate input box. With multiple blanks, there's no clear way to map answers to blanks. Kids don't know how to format multi-blank responses ("do I write them comma-separated? in order?").

**Choice questions require unnecessary typing.** When the tutor presents 3 options, the student has to type "option B" or copy the answer text. Tapping a choice is the obvious interaction — but today the UI doesn't support it.

**One input mode for all question types.** The bottom text bar treats every question the same. This is a missed opportunity — structured questions deserve structured input.

### Why This Matters

The target audience is kids. Every unnecessary keystroke, every moment of "how do I answer this?", every ambiguity in the input format is friction that kills engagement. Fill-in-the-blank and multiple-choice are natural, intuitive formats for kids — but only if the UI matches the question type. A worksheet doesn't have a single text box at the bottom of the page.

---

## Solution Overview

The tutor explicitly tags its questions with a **question format**, and the frontend renders a matching interactive input UI — replacing the generic bottom text bar when appropriate.

| Format | Tutor Output | Frontend Input UI |
|--------|-------------|-------------------|
| **Fill-in-the-blank** | Sentence with numbered blank markers + expected answer per blank | Tappable blanks inline in the text. Tap → popup with text input + mic. Submit button appears when all blanks filled. |
| **Single-select** | Question + list of options | Tappable option chips/buttons. One selectable. Submit button. |
| **Multi-select** | Question + list of options + "select all that apply" | Tappable option chips/buttons. Multiple selectable (toggle). Submit button. |
| **Open-ended** | Plain question text (current behavior) | Current bottom text bar + mic. No changes. |

When a structured format (fill-in-the-blank, single-select, multi-select) is active, the bottom input bar + mic are **hidden**. The interaction happens within the question card itself.

---

## Requirements

### R1: Tutor Response Format — Question Type Metadata

Extend `TutorTurnOutput` with a new field that describes the question format when the tutor asks a question.

**New field on `TutorTurnOutput`:**

```python
question_format: Optional[QuestionFormat] = None
```

**`QuestionFormat` model:**

```python
class BlankItem(BaseModel):
    blank_id: int           # 1-indexed
    hint: str               # Placeholder hint shown in the blank (e.g., "number", "word")
    expected_answer: str    # For evaluation

class OptionItem(BaseModel):
    option_id: str          # "A", "B", "C", "D"
    text: str               # Option text
    is_correct: bool        # For evaluation

class QuestionFormat(BaseModel):
    type: Literal["fill_in_the_blank", "single_select", "multi_select", "open_ended"]

    # Fill-in-the-blank fields
    template: Optional[str] = None  # Sentence with {{1}}, {{2}} markers for blanks
    blanks: Optional[list[BlankItem]] = None

    # Select fields
    options: Optional[list[OptionItem]] = None
```

**How the tutor uses it:**

When `type` is `fill_in_the_blank`:
- `response` contains the student-facing text with blank indicators rendered in markdown (e.g., bold underscores)
- `template` contains the machine-parseable version with `{{1}}`, `{{2}}` markers where blanks go
- `blanks` lists each blank's hint and expected answer
- `question_asked` is set as today (for question tracking)

When `type` is `single_select` or `multi_select`:
- `response` contains the question text (without listing options — frontend renders them)
- `options` lists the choices with correctness flags
- `question_asked` is set as today

When `type` is `open_ended` (or `question_format` is null):
- Current behavior, no changes

**Backward compatibility:** `question_format` is optional and defaults to `None`. All existing question flows work unchanged. Frontend falls back to current text input when `question_format` is absent.

### R2: Frontend — Fill-in-the-Blank Rendering

When a tutor message has `question_format.type == "fill_in_the_blank"`:

1. **Hide** the bottom input bar + mic
2. **Render** the tutor's `template` text with blank markers replaced by **tappable blank chips** — styled as underlined/highlighted inline spans showing the hint text (e.g., `___number___`)
3. **Tap interaction:** Student taps a blank → **popup** appears with:
   - The blank's hint as placeholder text
   - A text input field
   - A mic button (voice input for that blank)
   - A "Done" button to close the popup
4. **After filling:** The blank chip updates to show the student's answer (highlighted, visually distinct from surrounding text). Tapping again reopens the popup for editing.
5. **Submit button:** A "Check my answers" button appears below the question. Disabled until all blanks are filled. Allow partial submit via a separate "I'm stuck" option (submits whatever is filled, tutor can scaffold the rest).
6. **On submit:** Frontend reconstructs the full sentence (template with blanks replaced by student answers) and sends it as the student's message. The tutor evaluates using its existing answer evaluation logic.

**Why popup over inline editing:** Controlled sizing regardless of answer length. Clean placement of mic button. No layout shifts in the question text. Works consistently on all screen sizes.

### R3: Frontend — Single-Select / Multi-Select Rendering

When a tutor message has `question_format.type == "single_select"` or `"multi_select"`:

1. **Hide** the bottom input bar + mic
2. **Render** options as tappable chips/buttons below the question text
3. **Single-select:** Tapping an option highlights it (radio behavior). Tapping another deselects the first.
4. **Multi-select:** Tapping an option toggles it (checkbox behavior). Question text should include "select all that apply" (tutor prompt handles this).
5. **Submit button:** "Check my answer" button, disabled until at least one option selected.
6. **On submit:** Frontend sends the selected option text(s) as the student's message — e.g., `"23 and 14"` for single-select, or `"23 and 14, 37"` for multi-select. Reconstructed as readable text so the tutor's existing evaluation works.

**Styling:** Options should be large, tappable (mobile-first), visually distinct. Selected state uses a clear highlight (filled background or border change). Consider 44px minimum touch target per Apple HIG.

### R4: Tutor Prompt Updates

Update the master tutor system prompt to:

1. **Teach the format field.** Add instructions for when and how to use each question format in structured output.

2. **Encourage fill-in-the-blank for factual recall.** When checking if a student remembers key terms, definitions, or simple computations — use fill-in-the-blank. Examples:
   - "The numbers you add together are called {{1}}" (blank: addends)
   - "In 23 + 14, the addends are {{1}} and {{2}}, and the sum is {{3}}"

3. **Encourage select for identification/recognition.** When the question is "which of these..." or "pick the correct..." — use single-select or multi-select. Examples:
   - "Which of these is an addend in 5 + 3 = 8?" → options: [5, 8, +, =] (single-select)
   - "Which are prime numbers?" → options: [2, 4, 7, 9, 11] (multi-select)

4. **Keep open-ended for deeper thinking.** When the question requires explanation, reasoning, or creative response — use open-ended (current behavior). Examples:
   - "Can you explain why we regroup in this problem?"
   - "What would happen if we changed the order?"

5. **Selection guidelines:**
   - Fill-in-the-blank: Best for recall, definitions, completing patterns, simple computation answers
   - Single/multi-select: Best for identification, classification, recognition, true/false
   - Open-ended: Best for explanation, reasoning, "in your own words", creative thinking
   - When in doubt, prefer structured formats (fill-in-the-blank or select) over open-ended — they're easier for kids

6. **Blank design rules:**
   - Max 3 blanks per question (more is overwhelming)
   - Each blank should be a short answer (1-3 words, a number, or a short phrase)
   - Provide meaningful hints (not just "answer" — use "number", "word", "name", etc.)
   - The surrounding sentence should provide enough context that the blank is solvable

7. **Option design rules:**
   - 3-4 options for single-select (not more)
   - Distractors should be plausible but clearly wrong with understanding
   - Options should be short (one line each)
   - Randomize correct option position (don't always put it first or last)

### R5: Answer Submission & Evaluation

The student's response must be sent back to the tutor in a way that's compatible with the existing evaluation flow.

**Fill-in-the-blank submission:**
- Frontend substitutes blanks with student answers in the template
- Sends as a single message: `"The addends are 23 and 14, and the sum is 37"`
- Tutor evaluates against `expected_answer` per blank using existing `answer_correct` / `mastery_signal` logic
- If partial submit ("I'm stuck"): unfilled blanks are sent as `"___"` — tutor sees which blanks the student couldn't answer and scaffolds accordingly

**Select submission:**
- Frontend sends selected option text(s) as a message
- Single-select: `"23 and 14"`
- Multi-select: `"2, 7, 11"` (comma-separated)
- Tutor evaluates against `is_correct` flags

**Tutor-side evaluation:** No new evaluation logic needed. The tutor already evaluates free-text answers against `expected_answer` / `question_asked`. The structured submission just makes the student's answer cleaner and more predictable, which should improve evaluation accuracy.

### R6: Interaction State Management

**Active question state:** When a structured question is displayed, the session UI is in "question mode":
- Bottom input bar hidden
- Blank/option interaction active
- Submit button visible

**State transitions:**
- Tutor sends structured question → enter question mode
- Student submits answer → exit question mode, send message, show loading
- Tutor responds → may enter new question mode (if follow-up is structured) or return to normal input bar

**Session pause/resume:** If a session is paused while a structured question is active, on resume:
- The question is re-rendered with any partially filled blanks/selections intact
- State stored in frontend session state (not backend — this is purely UI state)

### R7: Accessibility & Edge Cases

- **Voice input in popup:** The mic button in the fill-in-the-blank popup uses the same transcription flow as the main input. Transcribed text fills the blank.
- **Long answers in blanks:** If a student types a long answer, the blank chip truncates with ellipsis but the popup shows the full text. The reconstructed submission includes the full text.
- **Empty submit prevention:** Submit button stays disabled until all blanks filled (fill-in-the-blank) or at least one option selected (select). "I'm stuck" is the escape hatch for partial answers.
- **Tutor doesn't use format field:** If the tutor asks a question but doesn't set `question_format` (prompt non-compliance), frontend falls back to current text input. No crash, no broken UI.

---

## Non-Goals

- **Drag-and-drop or matching questions.** V1 covers fill-in-the-blank, select, and open-ended. More complex formats (matching, ordering, drawing) are future work.
- **Gamification / scoring animation.** No points, streaks, or animations on correct answers in this PRD. That's a separate feature.
- **Changing exam mode.** Exam questions keep their current per-question text input format. This PRD only affects teach_me mode interactive questions.
- **Backend answer validation.** The tutor LLM evaluates answers (as today). No deterministic backend validation of select/blank answers — the tutor's judgment handles edge cases (partial credit, alternative phrasings).
- **Analytics on question format usage.** Future work — tracking which formats the tutor uses, success rates per format, etc.

---

## Technical Approach (High-Level)

### Backend Changes

**New models** (`llm-backend/tutor/agents/master_tutor.py`):
- `BlankItem`, `OptionItem`, `QuestionFormat` Pydantic models
- New optional `question_format` field on `TutorTurnOutput`

**Prompt updates** (`llm-backend/tutor/prompts/master_tutor_prompts.py`):
- Add question format instructions to system prompt (when to use each type, blank/option design rules)
- Add `question_format` to the structured output schema description
- Examples of each format in the prompt

**No new API endpoints.** The existing `/sessions/{id}/turn` endpoint handles everything. The tutor response now optionally includes `question_format` in its structured output. The student's answer is still sent as a text message.

**Message DTO** (`llm-backend/tutor/models/messages.py`):
- Add `question_format` to the tutor message DTO so frontend receives it

### Frontend Changes

**New components:**
- `FillInTheBlank` — Renders template with tappable blank chips. Manages popup state.
- `BlankPopup` — Text input + mic popup for a single blank.
- `SelectOptions` — Renders option chips for single/multi-select.
- `StructuredSubmitButton` — "Check my answers" / "I'm stuck" buttons.

**Modified components:**
- `ChatSession.tsx` — Detect `question_format` on tutor messages. When present, hide bottom input bar and render appropriate structured input component within the message card. Handle structured submission (reconstruct answer text, call existing `handleSubmit` flow).

**State:**
- `activeQuestionFormat: QuestionFormat | null` — tracks whether a structured question is active
- `blankAnswers: Record<number, string>` — current blank values (fill-in-the-blank)
- `selectedOptions: Set<string>` — selected option IDs (select)

### Data Flow

```
Tutor LLM → TutorTurnOutput (with question_format)
  → Session service passes through (no special handling)
  → Frontend receives tutor message with question_format
  → Frontend hides input bar, renders structured UI
  → Student interacts (fills blanks / selects options)
  → Student taps "Check my answers"
  → Frontend reconstructs answer as text message
  → Sent to /sessions/{id}/turn as normal student message
  → Tutor evaluates as today (answer_correct, mastery_signal, etc.)
```

---

## Success Criteria

1. **Fill-in-the-blank works end-to-end.** Student sees blanks in question text, taps to fill, submits, tutor evaluates correctly.
2. **Select questions work end-to-end.** Student sees options, taps to select, submits, tutor evaluates correctly.
3. **Bottom input bar hides/shows correctly.** Hidden during structured questions, visible for open-ended.
4. **Tutor uses formats appropriately.** Fill-in-the-blank for recall, select for identification, open-ended for reasoning. Not 100% of questions are structured — the mix is natural.
5. **No regression.** Open-ended questions and exam mode work exactly as before. `question_format: null` falls back to current behavior.
6. **Mobile UX.** Blank chips and option buttons are easily tappable on phone screens. Popup is usable with on-screen keyboard.
7. **Qualitative.** A kid answering a fill-in-the-blank question doesn't hesitate about how to input their answer.
