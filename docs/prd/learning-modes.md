# PRD: Learning Session Modes

**Status:** Draft
**Date:** 2026-02-20

---

## 1. Problem Statement

Today, LearnLikeMagic offers a single learning experience: guided tutoring where the tutor follows a study plan (explain, check, practice). This works well for structured learning but does not cover two important student needs:

1. **Targeted doubt clearing** — A student knows the topic but has specific questions or confusion on certain concepts. They don't want to sit through a full lesson; they want quick, precise answers.
2. **Self-assessment** — A student wants to test their own knowledge before an exam or after studying. They want a score that tells them where they stand.

These are fundamentally different interactions, and forcing them all through a guided lesson creates friction and poor learning outcomes.

---

## 2. Solution Overview

Introduce three distinct **session modes** that students choose after selecting a subtopic:

| Mode | Student Need | Who Leads | Produces |
|------|-------------|-----------|----------|
| **Teach Me** | "Explain this topic to me" | Tutor leads | Mastery score per concept |
| **Clarify Doubts** | "I have specific questions" | Student leads | Understanding assessment per concept |
| **Exam** | "Test my knowledge" | Tutor leads | Numeric exam score + per-question results |

All three modes produce data that feeds into a renamed **Report Card** (currently Scorecard).

---

## 3. User Flow

### 3.1 Mode Selection (New Screen)

After selecting Subject > Topic > Subtopic, instead of immediately starting a session, the student sees a mode selection screen:

```
┌─────────────────────────────────┐
│     What would you like to do?  │
│                                 │
│  ┌───────────┐                  │
│  │  Teach Me  │  "Learn this    │
│  │   (book)   │   topic from    │
│  │            │   scratch"      │
│  └───────────┘                  │
│                                 │
│  ┌───────────┐                  │
│  │  Clarify   │  "I have       │
│  │  Doubts    │   questions"    │
│  │   (chat)   │                 │
│  └───────────┘                  │
│                                 │
│  ┌───────────┐                  │
│  │   Exam     │  "Test my      │
│  │  (check)   │   knowledge"   │
│  └───────────┘                  │
│                                 │
└─────────────────────────────────┘
```

Each card shows a short description so students understand what to expect. The UI follows the existing design language — big tap targets, minimal text, mobile-first.

### 3.2 Teach Me (Existing Behavior)

No changes to the core teaching flow. The tutor follows the study plan, explains concepts, asks questions, tracks mastery. All existing behavior is preserved.

**Progress indicator:** Step X/Y + Mastery bar (unchanged).

### 3.3 Clarify Doubts (New)

**Entry:** Tutor sends a warm welcome inviting questions: *"Hi! I'm here to help with [subtopic]. What's on your mind?"*

**Conversation dynamics:**
- Student asks a question about the subtopic
- Tutor answers clearly using curriculum-appropriate language and the teaching guidelines as context
- After answering, the tutor asks a brief follow-up to check understanding (e.g., "Does that make sense?" or a quick check question)
- Based on the student's response, the tutor assesses understanding of that concept
- Student asks more questions or says they're done

**Tutor behavior:**
- Uses teaching guidelines for accurate, curriculum-aligned answers
- Keeps answers concise — this mode values directness over scaffolded teaching
- If a question reveals a deep misunderstanding, the tutor addresses it directly rather than doing Socratic exploration (unlike Teach Me mode)
- Tracks which concepts/areas from the guidelines are being discussed
- Gently offers related areas if the student seems stuck on what to ask
- If a question falls outside the subtopic scope, the tutor answers briefly and redirects

**Session end:** Student explicitly says they're done, or triggers an end-session action. No study plan completion trigger.

**Progress indicator:** "Topics discussed: X" — no step counter, no mastery bar. Optionally show a list of concepts discussed as chips/tags.

**Data produced:**
- List of concepts discussed (mapped to the teaching guidelines)
- Per-concept understanding assessment (0-1 score, inferred from the Q&A quality)
- Misconceptions surfaced
- Overall understanding score (average of discussed concepts)

### 3.4 Exam Mode (New)

**Entry:** Tutor welcomes and sets expectations: *"Let's test your knowledge of [subtopic]! I'll ask you [N] questions. Ready?"*

**Exam structure:**
- Tutor generates questions dynamically from the teaching guidelines
- Target: 5-10 questions per exam (configurable, default 7)
- Questions cover key concepts from the subtopic's learning objectives
- Mix of difficulty levels: ~30% easy, ~50% medium, ~20% hard
- Question types: conceptual, procedural, application (matching existing study plan question types)

**Conversation dynamics:**
- Tutor asks one question at a time
- Student answers
- Tutor evaluates: correct, partially correct, or incorrect
- Brief feedback after each answer (1-2 sentences max — this is an exam, not a teaching session)
- If correct: "Right!" + move to next question
- If partially correct: Acknowledge what's right, note what's missing, move on
- If incorrect: State the correct answer briefly, move on
- Tutor does NOT teach or remediate during the exam — it just assesses
- After all questions, tutor provides a score summary

**Key distinction from Teach Me:** In Teach Me, wrong answers trigger remediation (probe → hint → explain). In Exam mode, wrong answers get brief feedback and the exam moves on. The goal is assessment, not teaching.

**Session end:** All questions answered, or student ends early.

**Progress indicator:** "Question X of Y" + running score (e.g., "3/5 correct").

**Data produced:**
- Total questions asked
- Total correct / partially correct / incorrect
- Per-question record: question text, student answer, correct answer, score (0/0.5/1), concept tested
- Overall exam score (percentage)
- Weak areas (concepts where questions were answered incorrectly)

---

## 4. Report Card (Renamed from Scorecard)

### 4.1 Renaming

"Scorecard" → "Report Card" throughout the app (UI labels, navigation, code references).

### 4.2 Aggregation Changes

**Current rule:** Subtopic score = mastery from latest session.

**New rule:** Each mode contributes data differently, but all produce a 0-1 score:

| Mode | Score Source | How It Contributes |
|------|------------|-------------------|
| **Teach Me** | Overall mastery (existing) | Directly sets subtopic score |
| **Clarify Doubts** | Average understanding of discussed concepts | Sets subtopic score, but only for concepts discussed (partial coverage expected) |
| **Exam** | Exam percentage (correct/total) | Directly sets subtopic score |

The **latest session** per subtopic still wins for the subtopic score, regardless of mode. This keeps the existing logic simple while accommodating new modes.

### 4.3 New Report Card Data

**Per subtopic, the Report Card now shows:**

- Mastery score (unchanged)
- Mastery label and badge (unchanged)
- Concepts and their scores (unchanged)
- Misconceptions (unchanged)
- Session count (unchanged)
- **NEW:** Latest session mode label (Teach Me / Clarify Doubts / Exam)
- **NEW:** Exam results section (if any exam sessions exist):
  - Latest exam score
  - Number of exams taken
  - "Take Exam" quick action

**Per subject overview (unchanged structure):**
- Subject score, topic scores, trend — all computed the same way from subtopic scores

### 4.4 Action Buttons

Currently "Practice Again" starts a Teach Me session. New behavior:

- **"Practice Again"** → Starts a **Teach Me** session (unchanged)
- **"Take Exam"** → Starts an **Exam** session (new button, shown when exam data exists or alongside Practice Again)

Both buttons appear on the subtopic detail in the Report Card.

---

## 5. Backend Changes

### 5.1 Database

**Sessions table — add `mode` column:**

```sql
ALTER TABLE sessions ADD COLUMN mode VARCHAR(20) DEFAULT 'teach';
```

Values: `teach`, `clarify`, `exam`. Default `teach` for backward compatibility with existing sessions.

No new tables needed. All session data is stored in `state_json` (existing pattern).

### 5.2 Session State Model

**`SessionState` additions (in `tutor/models/session_state.py`):**

```python
class SessionState(BaseModel):
    # ... existing fields ...
    mode: Literal["teach", "clarify", "exam"] = "teach"

    # Exam-specific state (only populated in exam mode)
    exam_state: Optional[ExamState] = None

class ExamState(BaseModel):
    total_questions: int = 7
    questions_asked: list[ExamQuestion] = []
    current_question_index: int = 0

class ExamQuestion(BaseModel):
    question_text: str
    expected_answer: str
    concept: str
    difficulty: Literal["easy", "medium", "hard"]
    student_answer: Optional[str] = None
    score: Optional[float] = None  # 0, 0.5, or 1.0
    feedback: Optional[str] = None
```

### 5.3 API Changes

**Session creation — add `mode` to request:**

```python
class Goal(BaseModel):
    topic: str
    syllabus: str
    learning_objectives: list[str]
    guideline_id: Optional[str] = None
    mode: Literal["teach", "clarify", "exam"] = "teach"  # NEW
```

Or alternatively, add `mode` as a top-level field in `CreateSessionRequest`. The `Goal` model is the more natural fit since mode relates to how the goal is pursued.

**Session creation flow changes:**
- For `teach` mode: Load study plan (existing behavior)
- For `clarify` mode: Skip study plan loading. Create a minimal topic context with guidelines only. Generate a different welcome message.
- For `exam` mode: Skip study plan. Generate an exam question plan from the guidelines. Generate exam-specific welcome message.

**Step response — add mode-specific data:**

```python
class StepResponse(BaseModel):
    next_turn: dict
    routing: str
    last_grading: Optional[GradingResult] = None
    exam_progress: Optional[dict] = None  # NEW: {current: 3, total: 7, score: 2}
```

**Summary response — add mode-specific data:**

```python
class SummaryResponse(BaseModel):
    steps_completed: int
    mastery_score: float
    misconceptions_seen: list[str]
    suggestions: list[str]
    mode: str = "teach"  # NEW
    # Exam-specific summary
    exam_results: Optional[ExamSummary] = None

class ExamSummary(BaseModel):
    total_questions: int
    correct: int
    partially_correct: int
    incorrect: int
    score_percentage: float
    per_question: list[dict]  # [{question, answer, correct_answer, score, concept}]
    weak_areas: list[str]
```

### 5.4 Orchestrator Changes

**`TeacherOrchestrator.process_turn` needs mode-aware routing:**

```python
async def process_turn(self, session, student_message):
    # Safety check (all modes)
    # ...

    if session.mode == "teach":
        return await self._process_teach_turn(session, student_message, context)
    elif session.mode == "clarify":
        return await self._process_clarify_turn(session, student_message, context)
    elif session.mode == "exam":
        return await self._process_exam_turn(session, student_message, context)
```

Each mode handler uses the master tutor agent but with different system prompts and different state update logic.

### 5.5 Prompt Changes

Three variants of the system prompt, one per mode:

**Teach Me system prompt:** Existing `MASTER_TUTOR_SYSTEM_PROMPT` (unchanged).

**Clarify Doubts system prompt:** New prompt emphasizing:
- Student leads the conversation
- Answer questions directly and clearly
- Use teaching guidelines as knowledge base
- After answering, ask brief follow-up to check understanding
- Track which concepts are being discussed
- Output: response + concept_discussed + understanding_assessment

**Exam system prompt:** New prompt emphasizing:
- Ask one question at a time from the exam plan
- Evaluate answers strictly (correct / partially correct / incorrect)
- Give brief feedback only — do not teach
- Track per-question scores
- Output: response + question_evaluation + exam_progress

### 5.6 Agent Output Schema Changes

**New output schemas for each mode:**

```python
# Teach Me: TutorTurnOutput (existing, unchanged)

# Clarify Doubts:
class ClarifyTurnOutput(BaseModel):
    response: str
    concepts_discussed: list[str]
    understanding_signal: Optional[Literal["strong", "adequate", "weak"]] = None
    mastery_updates: list[MasteryUpdate]
    misconceptions_detected: list[str]
    session_complete: bool
    turn_summary: str
    reasoning: str

# Exam:
class ExamTurnOutput(BaseModel):
    response: str
    question_evaluation: Optional[QuestionEvaluation] = None
    next_question: Optional[str] = None
    session_complete: bool
    turn_summary: str
    reasoning: str

class QuestionEvaluation(BaseModel):
    score: float  # 0, 0.5, 1.0
    is_correct: bool
    feedback: str
    concept: str
```

### 5.7 Scorecard Service Changes

**`ScorecardService` (renamed to `ReportCardService`):**

- `_group_sessions()`: Include session mode in the grouping data
- Each subtopic entry now includes: `latest_mode`, `exam_scores` (list of exam scores), `exam_count`
- Exam data is extracted from `state_json.exam_state` when mode is "exam"
- The subtopic score is still the latest session's score (regardless of mode)

### 5.8 Session History Changes

- Session history list should display the mode label per session
- Filter by mode (optional enhancement)

---

## 6. Frontend Changes

### 6.1 Mode Selection Screen

New step in the `TutorApp` selection flow:

```
subject → topic → subtopic → mode → chat
```

`selectionStep` state gains a new value: `'mode'`.

After subtopic selection, show three cards for the three modes. Tapping a card starts the session with the selected mode.

### 6.2 Chat Screen (Mode-Aware)

**Header:** Show mode label alongside topic info: `Grade 3 • Mathematics • Fractions • Comparing Fractions • Teach Me`

**Progress bar:**
- Teach Me: Step X/Y + Mastery (existing)
- Clarify Doubts: No step counter. Optional "Concepts discussed" chips. "End Session" button visible.
- Exam: Question X/Y + Score display (e.g., "3/5 correct")

**Input area:**
- Teach Me: "Type your answer..." (existing)
- Clarify Doubts: "Ask your question..."
- Exam: "Type your answer..."

**End-session button:** Clarify Doubts mode needs a visible "I'm done" button since there's no natural endpoint. Exam mode could also have an "End early" option.

### 6.3 Session Summary Screen (Mode-Aware)

**Teach Me:** Existing summary (steps, mastery, misconceptions, suggestions).

**Clarify Doubts:**
- "Concepts discussed" with understanding levels
- Misconceptions addressed
- Suggestions for what to study next

**Exam:**
- Score prominently displayed: "7/10 — 70%"
- Per-question breakdown with correct/incorrect indicators
- Weak areas highlighted
- "Practice these topics" suggestions

### 6.4 Report Card Page

- Rename from "My Scorecard" to "My Report Card" in navigation and headers
- Per-subtopic: show latest session mode as a small label
- Add "Take Exam" button alongside "Practice Again"
- If exam data exists, show latest exam score in the subtopic detail
- Style: exam score shown as a distinct badge/indicator separate from the mastery score

### 6.5 API Client Changes

- `CreateSessionRequest.goal` gets a `mode` field
- New TypeScript interfaces for exam-specific data
- Report Card API response includes new mode-related fields

---

## 7. What Does NOT Change

Keeping scope clear — these areas are explicitly **not** affected:

| Area | Impact |
|------|--------|
| **Book ingestion pipeline** | No changes. Guidelines and study plans are generated the same way. |
| **Teaching guidelines** | No changes to the data model or admin workflow. |
| **Study plan generation** | No changes. Study plans are used only in Teach Me mode. |
| **Admin evaluation system** | No changes for V1. Can be extended later to test Clarify/Exam modes. |
| **Authentication & onboarding** | No changes. |
| **User profile** | No changes. |
| **Safety agent** | No changes. Works the same across all modes. |

---

## 8. Migration & Backward Compatibility

1. **Database:** `ALTER TABLE sessions ADD COLUMN mode VARCHAR(20) DEFAULT 'teach'` — all existing sessions default to `teach`. Non-breaking.
2. **API:** `mode` field defaults to `"teach"` — existing clients that don't send `mode` get Teach Me behavior. Non-breaking.
3. **Report Card rename:** UI-only change. Backend endpoint paths stay the same (`/sessions/scorecard`). Add alias `/sessions/report-card` pointing to the same handler for clean URLs.
4. **State JSON:** New fields (`exam_state`, `mode`) are optional. Existing session deserialization is unaffected.

---

## 9. Implementation Phases

### Phase 1: Foundation (Backend Core)

1. Add `mode` column to sessions table (migration)
2. Add `mode` field to `SessionState`, `Goal`, `CreateSessionRequest`
3. Add `ExamState` and `ExamQuestion` models
4. Refactor `TeacherOrchestrator` to route by mode (extract current logic into `_process_teach_turn`)
5. Ensure Teach Me mode works identically after refactor (regression safety)

### Phase 2: Clarify Doubts Mode (Backend + Frontend)

1. Write Clarify Doubts system prompt and turn prompt
2. Create `ClarifyTurnOutput` schema
3. Implement `_process_clarify_turn` in orchestrator
4. Implement Clarify Doubts welcome message
5. Implement Clarify Doubts session completion and summary
6. Add mode selection screen in frontend
7. Wire Clarify Doubts chat UI (no step counter, "End Session" button)
8. Wire Clarify Doubts session summary

### Phase 3: Exam Mode (Backend + Frontend)

1. Write Exam system prompt and turn prompt
2. Create `ExamTurnOutput` and `QuestionEvaluation` schemas
3. Implement `_process_exam_turn` in orchestrator
4. Implement exam question generation from guidelines
5. Implement exam scoring and summary
6. Wire Exam chat UI (question counter, score display)
7. Wire Exam session summary with per-question breakdown

### Phase 4: Report Card

1. Rename Scorecard → Report Card (UI labels, navigation)
2. Update `ScorecardService` to extract mode and exam data from sessions
3. Add exam score display to subtopic detail in Report Card
4. Add "Take Exam" button alongside "Practice Again"
5. Show session mode labels in session history
6. Update Report Card API response schema

### Phase 5: Polish & Testing

1. End-to-end testing of all three modes
2. Report Card aggregation testing with mixed-mode sessions
3. Mobile UX polish for mode selection
4. Update documentation

---

## 10. Key Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| **Mode is per-session, not per-subtopic** | A student might want Teach Me on Monday and Exam on Friday for the same subtopic. Modes are about *what you want to do right now*, not a property of the content. |
| **No pre-generated exam plans** | Exam questions are generated dynamically by the tutor agent using teaching guidelines. This avoids another generation pipeline and leverages the existing guidelines content. |
| **Latest session score wins (regardless of mode)** | Keeps aggregation simple. A student who scores 90% on an exam after a 60% Teach Me session should see 90%. Modes are different ways to arrive at a score, not different score types. |
| **Clarify Doubts still tracks mastery** | Even in a Q&A format, the tutor can assess understanding. This data is valuable for the Report Card. Without it, Clarify Doubts sessions would create "holes" in the progress data. |
| **Exam feedback is brief, not remedial** | An exam that teaches defeats the purpose of assessment. Students who want to learn should use Teach Me or Clarify Doubts. Clear separation of concerns. |
| **Report Card, not separate exam results page** | One place for all progress data. Avoids fragmenting the student experience. Exam data is a section within the Report Card, not a separate destination. |
| **Reuse existing sessions table with mode column** | Adding a column is simpler than new tables. `state_json` already handles arbitrary session state. Mode-specific data (like `ExamState`) lives inside the JSON. |
| **Safety agent applies to all modes** | Content moderation is mode-independent. No reason to skip it. |
| **Default to Teach Me for backward compat** | Existing API callers, "Practice Again" buttons, and evaluation pipeline all continue working without changes. |
