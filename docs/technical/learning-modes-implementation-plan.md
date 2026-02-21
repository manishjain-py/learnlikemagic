# Technical Implementation Plan: Learning Session Modes

**PRD:** `docs/prd/learning-modes.md`
**Date:** 2026-02-21
**Status:** Draft

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Database Changes](#2-database-changes)
3. [Backend: Models & Types](#3-backend-models--types)
4. [Backend: Session Creation](#4-backend-session-creation)
5. [Backend: Teach Me Mode](#5-backend-teach-me-mode)
6. [Backend: Clarify Doubts Mode](#6-backend-clarify-doubts-mode)
7. [Backend: Exam Mode](#7-backend-exam-mode)
8. [Backend: Coverage Tracking](#8-backend-coverage-tracking)
9. [Backend: Report Card (Scorecard Refactor)](#9-backend-report-card-scorecard-refactor)
10. [Backend: Session History](#10-backend-session-history)
11. [Frontend: Mode Selection](#11-frontend-mode-selection)
12. [Frontend: Teach Me UI](#12-frontend-teach-me-ui)
13. [Frontend: Clarify Doubts UI](#13-frontend-clarify-doubts-ui)
14. [Frontend: Exam UI](#14-frontend-exam-ui)
15. [Frontend: Report Card](#15-frontend-report-card-scorecard-refactor)
16. [Frontend: Session History](#16-frontend-session-history)
17. [API Contract Changes](#17-api-contract-changes)
18. [Migration Strategy](#18-migration-strategy)
19. [Implementation Order](#19-implementation-order)
20. [Risk & Open Questions](#20-risk--open-questions)

---

## 1. Architecture Overview

### Current Architecture
```
Subject → Topic → Subtopic → Chat (single mode: tutor-led lesson)
```

### Target Architecture
```
Subject → Topic → Subtopic → Mode Selection → Mode-Specific Session
                                 ├── Teach Me (tutor-led, study plan, pause/resume)
                                 ├── Clarify Doubts (student-led Q&A)
                                 └── Exam (assessment, scored)
```

### Key Architectural Decisions

1. **Single `MasterTutorAgent` with mode-aware prompts** — rather than creating 3 separate agents, we use the existing `MasterTutorAgent` with mode-specific system prompts and output schemas. This keeps the architecture simple and avoids duplicating safety, logging, and orchestration logic.

2. **Mode stored in `SessionState`** — the mode is a field on the in-memory `SessionState` model and persisted in `state_json`. A denormalized `mode` column on the `sessions` table enables efficient queries (history filtering, finding resumable sessions).

3. **Coverage is computed from study plan concepts** — for Teach Me, coverage = concepts with step advanced / total unique concepts. For Clarify Doubts, coverage = concepts discussed / total concepts in study plan. Both accumulate into a per-guideline coverage record.

4. **Exam results stored as structured data in `state_json`** — exam questions, answers, and scores are part of the session state. A denormalized `exam_score` column on `sessions` enables quick display in history/report card.

5. **Report Card reads from sessions table** — the existing `ScorecardService` pattern (query all user sessions, parse state_json, aggregate) is extended with mode-aware logic. No new tables for coverage/exam aggregation — it's computed from session data.

---

## 2. Database Changes

### 2.1 `sessions` Table — New Columns

```sql
ALTER TABLE sessions ADD COLUMN mode VARCHAR DEFAULT 'teach_me';
ALTER TABLE sessions ADD COLUMN is_paused BOOLEAN DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN exam_score FLOAT DEFAULT NULL;
ALTER TABLE sessions ADD COLUMN exam_total INTEGER DEFAULT NULL;

CREATE INDEX idx_sessions_user_mode ON sessions(user_id, mode);
CREATE INDEX idx_sessions_user_paused ON sessions(user_id, is_paused) WHERE is_paused = TRUE;
```

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `mode` | VARCHAR | `'teach_me'` | Session mode: `teach_me`, `clarify_doubts`, `exam` |
| `is_paused` | BOOLEAN | `FALSE` | Whether a Teach Me session is paused (resumable) |
| `exam_score` | FLOAT | `NULL` | Denormalized exam score (correct count) for quick display |
| `exam_total` | INTEGER | `NULL` | Denormalized exam total questions for quick display |

### 2.2 Entity Model Update

**File:** `llm-backend/shared/models/entities.py`

```python
class Session(Base):
    # ... existing columns ...
    mode = Column(String, default='teach_me')          # NEW
    is_paused = Column(Boolean, default=False)          # NEW
    exam_score = Column(Float, nullable=True)           # NEW
    exam_total = Column(Integer, nullable=True)         # NEW
```

### 2.3 Migration

- Backfill existing sessions: `UPDATE sessions SET mode = 'teach_me' WHERE mode IS NULL`
- All existing sessions become `teach_me` (backward compatible)

---

## 3. Backend: Models & Types

### 3.1 Session Mode Enum

**File:** `llm-backend/tutor/models/session_state.py`

```python
SessionMode = Literal["teach_me", "clarify_doubts", "exam"]
```

### 3.2 SessionState Changes

**File:** `llm-backend/tutor/models/session_state.py`

Add to `SessionState`:

```python
class SessionState(BaseModel):
    # ... existing fields ...

    # NEW: Mode
    mode: SessionMode = Field(default="teach_me", description="Session mode")

    # NEW: Coverage tracking (for teach_me and clarify_doubts)
    concepts_covered_set: set[str] = Field(
        default_factory=set,
        description="Set of concept names covered in this session (for coverage calculation)"
    )

    # NEW: Exam state (for exam mode only)
    exam_questions: list["ExamQuestion"] = Field(default_factory=list)
    exam_current_question_idx: int = Field(default=0)
    exam_total_correct: int = Field(default=0)
    exam_total_partial: int = Field(default=0)
    exam_finished: bool = Field(default=False)
    exam_feedback: Optional["ExamFeedback"] = Field(default=None)

    # NEW: Clarify Doubts state
    concepts_discussed: list[str] = Field(
        default_factory=list,
        description="Concepts discussed in this Clarify Doubts session (shown as chips)"
    )
```

Note: `concepts_covered_set` uses `set[str]` for deduplication but Pydantic will serialize it as a list. We'll use a property/validator to handle this.

### 3.3 Exam Models

**File:** `llm-backend/tutor/models/session_state.py` (add new classes)

```python
class ExamQuestion(BaseModel):
    """A single exam question with its result."""
    question_idx: int
    question_text: str
    concept: str
    difficulty: Literal["easy", "medium", "hard"]
    question_type: Literal["conceptual", "procedural", "application"]
    expected_answer: str
    student_answer: Optional[str] = None
    result: Optional[Literal["correct", "partial", "incorrect"]] = None
    feedback: str = ""  # Brief feedback given after the answer


class ExamFeedback(BaseModel):
    """Post-exam evaluation feedback."""
    score: int  # Number correct
    total: int  # Total questions
    percentage: float
    strengths: list[str]
    weak_areas: list[str]
    patterns: list[str]
    next_steps: list[str]
```

### 3.4 Coverage Properties

Add to `SessionState`:

```python
@property
def coverage_percentage(self) -> float:
    """Coverage = concepts covered / total concepts in study plan."""
    if not self.topic or not self.topic.study_plan:
        return 0.0
    all_concepts = self.topic.study_plan.get_concepts()
    if not all_concepts:
        return 0.0
    covered = len(self.concepts_covered_set & set(all_concepts))
    return round(covered / len(all_concepts) * 100, 1)
```

### 3.5 `create_session` Updates

**File:** `llm-backend/tutor/models/session_state.py`

Update the `create_session` factory:

```python
def create_session(
    topic: Topic,
    student_context: Optional[StudentContext] = None,
    mode: SessionMode = "teach_me",
) -> SessionState:
    """Create a new session for a topic with the specified mode."""
    concepts = topic.study_plan.get_concepts()

    # Only initialize mastery estimates for teach_me (other modes don't use them)
    mastery_estimates = {concept: 0.0 for concept in concepts} if mode == "teach_me" else {}

    return SessionState(
        topic=topic,
        student_context=student_context or StudentContext(),
        mastery_estimates=mastery_estimates,
        mode=mode,
    )
```

---

## 4. Backend: Session Creation

### 4.1 API Request Changes

**File:** `llm-backend/shared/models/schemas.py`

```python
class CreateSessionRequest(BaseModel):
    student: Student
    goal: Goal
    mode: Optional[str] = "teach_me"  # NEW: "teach_me", "clarify_doubts", "exam"
```

### 4.2 API Response Changes

**File:** `llm-backend/shared/models/schemas.py`

```python
class CreateSessionResponse(BaseModel):
    session_id: str
    first_turn: Dict[str, Any]
    mode: str = "teach_me"  # NEW: echo back the mode
```

### 4.3 Resume Session Endpoint

**File:** `llm-backend/tutor/api/sessions.py` — new endpoint

```python
@router.get("/resumable")
def get_resumable_session(
    guideline_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Find a paused Teach Me session for the given subtopic."""
    # Query for paused teach_me session for this user + guideline
    # Return session_id + coverage + step info, or 404 if none
```

This endpoint is called by the frontend when showing the mode selection screen to check if a resumable session exists.

### 4.4 SessionService Changes

**File:** `llm-backend/tutor/services/session_service.py`

The `create_new_session` method branches on mode:

```python
def create_new_session(self, request: CreateSessionRequest, user_id=None):
    mode = request.mode or "teach_me"

    # Common: load guideline, build topic, build student context
    guideline = self.guideline_repo.get_guideline_by_id(request.goal.guideline_id)
    study_plan_record = ...
    topic = convert_guideline_to_topic(guideline, study_plan_record)
    student_context = self._build_student_context_from_profile(user_id, request)

    # Create mode-specific session
    session = create_session(topic=topic, student_context=student_context, mode=mode)

    # Generate mode-specific welcome
    if mode == "teach_me":
        welcome = self.orchestrator.generate_welcome_message(session)
    elif mode == "clarify_doubts":
        welcome = self.orchestrator.generate_clarify_welcome(session)
    elif mode == "exam":
        # Generate exam questions, then welcome
        self.orchestrator.generate_exam_questions(session)
        welcome = self.orchestrator.generate_exam_welcome(session)

    # Persist (include mode and exam columns)
    self._persist_session(session_id, session, request, user_id, subject, mode)

    return CreateSessionResponse(session_id=session_id, first_turn=first_turn, mode=mode)
```

### 4.5 Pause Session Endpoint

**File:** `llm-backend/tutor/api/sessions.py` — new endpoint

```python
@router.post("/{session_id}/pause")
def pause_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Pause a Teach Me session for later resumption."""
    # Validate ownership
    # Validate mode == teach_me
    # Set is_paused = True on sessions table
    # Return summary (coverage so far, concepts covered, step position)
```

### 4.6 Resume Session Flow

When the user clicks "Resume" on the mode selection screen:

1. Frontend calls `GET /sessions/resumable?guideline_id=xxx`
2. Backend returns the paused session's ID + current state summary
3. Frontend opens the chat view with that session ID
4. On WebSocket connect (or first REST call), the orchestrator generates a brief recap message before continuing

The recap is generated by a new orchestrator method:

```python
async def generate_resume_recap(self, session: SessionState) -> str:
    """Generate a brief recap for resuming a paused Teach Me session."""
    # Uses concepts_covered, current_step, topic_name to build a 1-2 sentence recap
    # e.g., "Welcome back! Last time we covered X and Y. Let's pick up with Z."
```

---

## 5. Backend: Teach Me Mode

### 5.1 What Changes

Teach Me is the **existing flow** with these additions:

1. **Coverage tracking** — after each step advance, add the concept to `concepts_covered_set`
2. **Pause capability** — new `/pause` endpoint, `is_paused` flag
3. **Resume with recap** — detect resumed sessions, generate recap
4. **No mastery display to student** — mastery is still tracked internally for pacing decisions, but the frontend shows coverage instead
5. **Session summary shows coverage** — instead of mastery score

### 5.2 Orchestrator Changes

**File:** `llm-backend/tutor/orchestration/orchestrator.py`

In `_apply_state_updates`, after advancing a step:

```python
# Track coverage (NEW)
if output.advance_to_step and output.advance_to_step > session.current_step:
    # Record concepts from the steps being advanced past
    for step_id in range(session.current_step, output.advance_to_step):
        step = session.topic.study_plan.get_step(step_id)
        if step:
            session.concepts_covered_set.add(step.concept)
    # ... existing advance logic ...
```

### 5.3 Session Completion

When Teach Me completes (all steps done):

- Coverage should be 100% (all concepts covered)
- Summary prompts the student to take an exam
- Session is NOT paused (it's complete)

### 5.4 Pause Flow

When the student clicks "Pause":

1. Frontend sends `POST /sessions/{id}/pause`
2. Backend sets `is_paused = True`, generates a pause summary
3. Returns: `{ coverage: 60, concepts_covered: [...], message: "You've covered 60%..." }`
4. Frontend shows the summary and navigates away

When resuming:

1. Frontend detects resumable session via `GET /sessions/resumable?guideline_id=xxx`
2. Shows "Resume — 60% covered" button on mode selection
3. On resume, opens WebSocket/chat with the existing session_id
4. Backend sets `is_paused = False`, generates recap, continues from current step

---

## 6. Backend: Clarify Doubts Mode

### 6.1 Orchestrator Routing

**File:** `llm-backend/tutor/orchestration/orchestrator.py`

In `process_turn`, add mode-aware branching:

```python
async def process_turn(self, session, student_message):
    # ... safety check (same for all modes) ...

    if session.mode == "clarify_doubts":
        return await self._process_clarify_turn(session, context)
    elif session.mode == "exam":
        return await self._process_exam_turn(session, context)
    else:  # teach_me
        # ... existing master tutor flow ...
```

### 6.2 Clarify Doubts Turn Processing

```python
async def _process_clarify_turn(self, session, context):
    """Process a Clarify Doubts turn — student-led Q&A."""
    self.master_tutor.set_session(session)
    # Uses clarify-specific prompts (set via mode on the agent)
    output = await self.master_tutor.execute(context)

    # Track concepts discussed
    if output.concepts_mentioned:
        for concept in output.concepts_mentioned:
            if concept not in session.concepts_discussed:
                session.concepts_discussed.append(concept)
            session.concepts_covered_set.add(concept)

    session.add_message(create_teacher_message(output.response))
    return TurnResult(response=output.response, intent=output.intent, ...)
```

### 6.3 Clarify Doubts Agent Prompt

**File:** `llm-backend/tutor/prompts/clarify_doubts_prompts.py` (NEW)

System prompt key differences from Teach Me:
- **No study plan progression** — tutor answers questions, doesn't follow steps
- **Direct answers** — no Socratic method, no scaffolded discovery
- **Concise** — values directness over long explanations
- **Concept tracking** — agent output includes `concepts_mentioned` field
- **Follow-up checks** — after answering, ask a brief follow-up to check understanding
- **Scope management** — if question is outside subtopic, answer briefly and redirect
- **Suggest related areas** — if student seems unsure what to ask

### 6.4 Clarify Doubts Output Schema

Extend `TutorTurnOutput` or create a mode-specific variant:

```python
class ClarifyTurnOutput(BaseModel):
    response: str
    intent: str  # "question", "followup", "done", "off_topic"
    concepts_mentioned: list[str] = Field(
        default_factory=list,
        description="Concepts from the study plan that were discussed in this turn"
    )
    follow_up_question: Optional[str] = None
    turn_summary: str
    reasoning: str = ""
```

### 6.5 Past Discussion History

When creating a new Clarify Doubts session, the backend queries previous Clarify Doubts sessions for the same guideline_id and user, extracts their `concepts_discussed` lists, and includes a summary in the `CreateSessionResponse`:

```python
class CreateSessionResponse(BaseModel):
    session_id: str
    first_turn: Dict[str, Any]
    mode: str = "teach_me"
    past_discussions: Optional[list[dict]] = None  # NEW: for clarify_doubts
    # Each dict: { session_date, concepts_discussed }
```

This data is shown in the frontend for the student's reference. The tutor does NOT carry context from past sessions (each session is fresh, per PRD).

---

## 7. Backend: Exam Mode

### 7.1 Exam Question Generation

**File:** `llm-backend/tutor/services/exam_service.py` (NEW)

```python
class ExamService:
    """Generates and evaluates exam questions."""

    def generate_questions(self, session: SessionState) -> list[ExamQuestion]:
        """
        Generate 5-10 exam questions for the subtopic.

        Uses the teaching guidelines (learning objectives, concepts) to create:
        - ~30% easy questions
        - ~50% medium questions
        - ~20% hard questions

        Mix of question types: conceptual, procedural, application.
        """
```

Question generation uses a dedicated LLM call with the teaching guidelines + study plan as context. The prompt asks for structured output with questions, expected answers, difficulty, and type.

### 7.2 Exam Question Generation Prompt

**File:** `llm-backend/tutor/prompts/exam_prompts.py` (NEW)

```python
EXAM_QUESTION_GENERATION_PROMPT = PromptTemplate("""
You are generating exam questions for a Grade {grade} student on: {topic_name}

Learning Objectives:
{learning_objectives}

Key Concepts:
{concepts}

Teaching Guidelines:
{teaching_approach}

Generate exactly {num_questions} questions with this distribution:
- ~30% easy (recall, basic understanding)
- ~50% medium (application, comparison)
- ~20% hard (analysis, edge cases, multi-step)

Mix question types: conceptual, procedural, application.

For each question, provide:
1. The question text (clear, unambiguous)
2. The expected correct answer
3. The concept being tested
4. Difficulty level
5. Question type
""")
```

### 7.3 Exam Turn Processing

**File:** `llm-backend/tutor/orchestration/orchestrator.py`

```python
async def _process_exam_turn(self, session, context):
    """Process an exam turn — evaluate answer, move to next question."""
    current_q = session.exam_questions[session.exam_current_question_idx]

    # Use master tutor (with exam prompts) to evaluate the student's answer
    self.master_tutor.set_session(session)
    output = await self.master_tutor.execute(context)
    # output contains: answer_correct, brief feedback, result (correct/partial/incorrect)

    # Update exam question result
    current_q.student_answer = context.student_message
    current_q.result = output.exam_result  # "correct", "partial", "incorrect"
    current_q.feedback = output.exam_feedback_brief

    if output.exam_result == "correct":
        session.exam_total_correct += 1
    elif output.exam_result == "partial":
        session.exam_total_partial += 1

    # Move to next question or finish
    session.exam_current_question_idx += 1
    if session.exam_current_question_idx >= len(session.exam_questions):
        session.exam_finished = True
        # Generate comprehensive exam feedback
        feedback = await self._generate_exam_feedback(session)
        session.exam_feedback = feedback
        # Build final response with score + feedback
        response = self._build_exam_completion_response(output.response, feedback)
    else:
        # Ask next question
        next_q = session.exam_questions[session.exam_current_question_idx]
        response = f"{output.response}\n\n{next_q.question_text}"

    return TurnResult(response=response, intent="exam_answer", ...)
```

### 7.4 Exam Evaluation Prompt

The exam evaluation prompt is simpler than Teach Me — no remediation, just evaluate:

```python
EXAM_EVALUATION_SYSTEM_PROMPT = PromptTemplate("""
You are an exam evaluator for a Grade {grade} student.

Topic: {topic_name}

Rules:
1. Evaluate the student's answer against the expected answer
2. Give brief feedback (1-2 sentences max):
   - Correct: "Right!" or brief acknowledgment. Move on.
   - Partially correct: Acknowledge what's right, note what's missing. Move on.
   - Incorrect: State the correct answer briefly. Move on.
3. Do NOT teach or remediate. This is an assessment.
4. After feedback, present the next question naturally.
5. Be encouraging but honest.
""")
```

### 7.5 Exam Output Schema

```python
class ExamTurnOutput(BaseModel):
    response: str
    exam_result: Literal["correct", "partial", "incorrect"]
    exam_feedback_brief: str  # 1-2 sentence feedback
    reasoning: str = ""
    turn_summary: str
```

### 7.6 Exam Feedback Generation

After all questions are answered, generate comprehensive feedback:

```python
async def _generate_exam_feedback(self, session: SessionState) -> ExamFeedback:
    """Generate structured exam feedback from question results."""
    # Can be done deterministically + LLM for pattern observation:

    correct_concepts = [q.concept for q in session.exam_questions if q.result == "correct"]
    incorrect_concepts = [q.concept for q in session.exam_questions if q.result == "incorrect"]

    # Strengths: concepts where answers were correct
    # Weak areas: concepts where answers were incorrect + brief explanation
    # Patterns: LLM call to identify patterns (optional, can also be rule-based)
    # Next steps: suggest Teach Me / Clarify Doubts for weak areas

    return ExamFeedback(
        score=session.exam_total_correct,
        total=len(session.exam_questions),
        percentage=round(session.exam_total_correct / len(session.exam_questions) * 100, 1),
        strengths=[...],
        weak_areas=[...],
        patterns=[...],
        next_steps=[...],
    )
```

### 7.7 End Early

If the student taps "End Early":
1. Frontend sends a special message or calls a new `POST /sessions/{id}/end-exam` endpoint
2. Backend marks remaining questions as unanswered
3. Score is calculated on answered questions only (e.g., 3/5 if 5 of 7 answered)
4. Feedback is generated on available data

---

## 8. Backend: Coverage Tracking

### 8.1 Coverage Computation

Coverage is computed per guideline_id (subtopic) across ALL learning sessions (Teach Me + Clarify Doubts) for a user.

**Where it lives:** Computed in `ScorecardService` (now `ReportCardService`) by aggregating `concepts_covered_set` from all sessions for a given guideline_id.

```python
def _compute_coverage(self, sessions_for_subtopic: list) -> float:
    """
    Compute coverage for a subtopic by unioning concepts_covered_set
    across all Teach Me and Clarify Doubts sessions.
    """
    all_concepts = set()
    covered_concepts = set()

    for session_state in sessions_for_subtopic:
        if session_state.get("mode") in ("teach_me", "clarify_doubts"):
            topic = session_state.get("topic", {})
            plan_concepts = set()
            for step in topic.get("study_plan", {}).get("steps", []):
                plan_concepts.add(step.get("concept"))
            all_concepts.update(plan_concepts)
            covered_concepts.update(session_state.get("concepts_covered_set", []))

    if not all_concepts:
        return 0.0
    return round(len(covered_concepts & all_concepts) / len(all_concepts) * 100, 1)
```

### 8.2 Coverage Rules

- Coverage **accumulates** across sessions and modes (Teach Me + Clarify Doubts)
- Coverage **never decreases**
- Coverage is computed from the union of `concepts_covered_set` across all sessions
- A concept is "covered" when:
  - **Teach Me:** The step for that concept is advanced past (student demonstrated understanding)
  - **Clarify Doubts:** The concept was discussed (identified by the tutor in `concepts_mentioned`)

### 8.3 Last Studied Timestamp

Computed from the most recent session (any mode) for a given guideline_id:

```python
def _get_last_studied(self, sessions_for_subtopic: list) -> Optional[str]:
    """Most recent session date across all modes for this subtopic."""
    dates = [s.get("updated_at") or s.get("created_at") for s in sessions_for_subtopic]
    return max(dates) if dates else None
```

### 8.4 Revision Nudge Logic

```python
def _get_revision_nudge(self, last_studied: Optional[str], coverage: float) -> Optional[str]:
    """Generate a revision nudge if enough time has passed."""
    if not last_studied or coverage < 20:
        return None

    days_since = (datetime.utcnow() - parse_datetime(last_studied)).days

    if days_since >= 30:
        return "It's been over a month — take a quick exam to check how much you remember"
    elif days_since >= 14:
        return "It's been a while — consider revising"
    elif days_since >= 7 and coverage >= 60:
        return "Time to revisit? A quick exam can show where you stand"
    return None
```

---

## 9. Backend: Report Card (Scorecard Refactor)

### 9.1 Rename

- Rename `ScorecardService` → `ReportCardService` in `llm-backend/tutor/services/scorecard_service.py`
- Rename `ScorecardResponse` → `ReportCardResponse` in `llm-backend/shared/models/schemas.py`
- Update API endpoint path: `GET /sessions/scorecard` → `GET /sessions/report-card` (keep old endpoint as alias for backward compat during migration)
- Update all imports and references

### 9.2 New Response Schema

**File:** `llm-backend/shared/models/schemas.py`

```python
class ReportCardSubtopic(BaseModel):
    subtopic: str
    subtopic_key: str
    guideline_id: Optional[str] = None

    # Learning progress
    coverage: float  # 0-100 percentage
    last_studied: Optional[str] = None
    revision_nudge: Optional[str] = None

    # Exam results
    latest_exam_score: Optional[int] = None  # e.g., 7
    latest_exam_total: Optional[int] = None  # e.g., 10
    latest_exam_feedback: Optional[ExamFeedbackResponse] = None
    exam_count: int = 0
    exam_history: list[ExamHistoryEntry] = []  # For trend graph

    # Session counts
    teach_me_sessions: int = 0
    clarify_sessions: int = 0

    # Legacy (kept for backward compat, can remove later)
    score: float = 0.0
    session_count: int = 0
    concepts: Dict[str, float] = {}
    misconceptions: list[ScorecardMisconception] = []


class ExamFeedbackResponse(BaseModel):
    strengths: list[str]
    weak_areas: list[str]
    patterns: list[str]
    next_steps: list[str]


class ExamHistoryEntry(BaseModel):
    date: str
    score: int
    total: int
    percentage: float
```

### 9.3 Service Changes

**File:** `llm-backend/tutor/services/scorecard_service.py` (renamed to `report_card_service.py`)

Key changes to `_group_sessions`:

1. Parse `mode` from `state_json` (or use the new `sessions.mode` column)
2. Group learning sessions (teach_me + clarify_doubts) for coverage computation
3. Group exam sessions separately for score tracking
4. Compute coverage per subtopic (union of concepts across sessions)
5. Find latest exam + build exam history for trend graph
6. Compute last_studied from most recent session of any mode
7. Generate revision nudges

### 9.4 Aggregation Changes

- **Subject/topic scores:** Shift from mastery-based to coverage-based for the primary metric. The `score` field at topic/subject level becomes an average of subtopic coverage percentages.
- **Strengths/needs-practice:** Based on coverage + exam performance combo. High coverage + high exam score = strength. Low coverage or low exam score = needs practice.
- **Trend data:** Keep existing mastery trend for backward compat, add exam score trend.

---

## 10. Backend: Session History

### 10.1 Repository Changes

**File:** `llm-backend/shared/repositories/session_repository.py`

`list_by_user` now returns mode-specific data:

```python
def list_by_user(self, user_id, ...):
    # ... existing query ...
    for row in rows:
        state = json.loads(row.state_json)
        entry = {
            # ... existing fields ...
            "mode": row.mode or state.get("mode", "teach_me"),  # NEW
        }
        # Mode-specific fields
        if entry["mode"] == "teach_me":
            entry["coverage"] = state.get("coverage_percentage", 0)
        elif entry["mode"] == "clarify_doubts":
            entry["concepts_discussed"] = state.get("concepts_discussed", [])
        elif entry["mode"] == "exam":
            entry["exam_score"] = row.exam_score
            entry["exam_total"] = row.exam_total
        results.append(entry)
```

---

## 11. Frontend: Mode Selection

### 11.1 New Selection Step

**File:** `llm-frontend/src/TutorApp.tsx`

Add a new `selectionStep` value: `'mode'`

```typescript
selectionStep: 'subject' | 'topic' | 'subtopic' | 'mode' | 'chat'
```

Flow: `subject → topic → subtopic → mode → chat`

### 11.2 Mode Selection Screen

After subtopic selection, instead of immediately creating a session, show the mode selection screen:

```tsx
{selectionStep === 'mode' && (
  <ModeSelection
    subtopic={selectedSubtopic}
    resumableSession={resumableSession}  // from GET /sessions/resumable
    onSelectMode={handleModeSelect}
    onResume={handleResume}
    onBack={() => setSelectionStep('subtopic')}
  />
)}
```

### 11.3 ModeSelection Component

**File:** `llm-frontend/src/components/ModeSelection.tsx` (NEW)

```tsx
interface ModeSelectionProps {
  subtopic: SubtopicInfo;
  resumableSession: ResumableSession | null;
  onSelectMode: (mode: 'teach_me' | 'clarify_doubts' | 'exam') => void;
  onResume: (sessionId: string) => void;
  onBack: () => void;
}
```

Three cards:
1. **Teach Me** — book icon, "Learn this topic from scratch"
2. **Clarify Doubts** — chat icon, "I have questions"
3. **Exam** — check icon, "Test my knowledge"

If `resumableSession` exists, show a prominent "Resume" banner above the cards:
- "Resume — 60% covered"
- Tapping resumes the session

### 11.4 API Changes

**File:** `llm-frontend/src/api.ts`

```typescript
// New: Check for resumable session
async function getResumableSession(guidelineId: string): Promise<ResumableSession | null> {
  const res = await apiFetch(`/sessions/resumable?guideline_id=${guidelineId}`);
  if (res.status === 404) return null;
  return res.json();
}

// Updated: createSession now includes mode
async function createSession(request: CreateSessionRequest): Promise<CreateSessionResponse> {
  // request now includes mode field
}

// New: Pause a session
async function pauseSession(sessionId: string): Promise<PauseSummary> {
  const res = await apiFetch(`/sessions/${sessionId}/pause`, { method: 'POST' });
  return res.json();
}

// New: End exam early
async function endExamEarly(sessionId: string): Promise<ExamSummary> {
  const res = await apiFetch(`/sessions/${sessionId}/end-exam`, { method: 'POST' });
  return res.json();
}
```

### 11.5 Types

```typescript
interface ResumableSession {
  session_id: string;
  coverage: number;
  current_step: number;
  total_steps: number;
  concepts_covered: string[];
}

interface CreateSessionRequest {
  student: { id: string; grade: number; prefs?: StudentPrefs };
  goal: { topic: string; syllabus: string; learning_objectives: string[]; guideline_id: string };
  mode?: 'teach_me' | 'clarify_doubts' | 'exam';  // NEW
}
```

---

## 12. Frontend: Teach Me UI

### 12.1 Progress Bar Changes

**File:** `llm-frontend/src/TutorApp.tsx` (chat header area)

Replace the current dual progress bar (steps + mastery) with:
- **Step counter:** "Step {stepIdx}/{totalSteps}" (keep as-is)
- **Coverage:** "{coverage}% covered" (replaces mastery display)

The mastery bar is removed from the student-facing UI. Coverage is shown instead.

### 12.2 Pause Button

Add a "Pause" button in the chat header (next to the back button):

```tsx
{sessionMode === 'teach_me' && !isComplete && (
  <button className="pause-btn" onClick={handlePause}>
    Pause
  </button>
)}
```

`handlePause`:
1. Calls `pauseSession(sessionId)`
2. Shows a pause summary overlay/modal with:
   - Coverage so far
   - Concepts covered
   - "You can pick up where you left off anytime"
3. Navigates back to topic selection

### 12.3 Session Summary Changes

When Teach Me completes, the summary shows:
- Coverage (e.g., "You've covered 100% of Comparing Fractions")
- Concepts covered in this session
- Prompt to take an exam: "Ready to test yourself? Take an exam to see how much you've learned"
- "Take Exam" button (starts exam for same subtopic)
- "Back to Topics" button

When paused, the summary shows:
- Coverage so far
- "You can pick up where you left off anytime"
- "Back to Topics" button

---

## 13. Frontend: Clarify Doubts UI

### 13.1 Progress Indicator

Instead of step counter + mastery, show:
- **Concept chips:** Tags that accumulate as concepts are discussed
- e.g., `[Comparing fractions] [Like denominators] [Unlike denominators]`

### 13.2 End Session Button

Replace the step-driven completion with a manual "End Session" button:

```tsx
{sessionMode === 'clarify_doubts' && (
  <button className="end-session-btn" onClick={handleEndClarifySession}>
    End Session
  </button>
)}
```

### 13.3 Past Discussions

When opening Clarify Doubts, if `past_discussions` is returned in the create response, show a collapsible "Previous Sessions" section above the chat:

```tsx
{pastDiscussions && pastDiscussions.length > 0 && (
  <div className="past-discussions">
    <h4>Previous Questions</h4>
    {pastDiscussions.map(d => (
      <div key={d.session_date}>
        <span>{d.session_date}</span>
        <div>{d.concepts_discussed.map(c => <span className="chip">{c}</span>)}</div>
      </div>
    ))}
  </div>
)}
```

### 13.4 Session Summary

When the student ends the session:
- Concepts discussed in this session
- Updated coverage
- Suggestion to take an exam if coverage is significant

---

## 14. Frontend: Exam UI

### 14.1 Progress Indicator

Replace step counter + mastery with:
- **Question counter:** "Question {current}/{total}"
- **Running score:** "{correct}/{answered} correct" (shown as small text)

### 14.2 End Early Button

```tsx
{sessionMode === 'exam' && !examFinished && (
  <button className="end-early-btn" onClick={handleEndExamEarly}>
    End Early
  </button>
)}
```

### 14.3 Exam Summary Screen

When the exam finishes (all questions answered or ended early), show a comprehensive results screen:

```tsx
<div className="exam-results">
  <h2>Exam Complete</h2>

  {/* Score prominently */}
  <div className="exam-score">
    <span className="score-number">7/10</span>
    <span className="score-percent">70%</span>
  </div>

  {/* Per-question breakdown */}
  <div className="question-breakdown">
    {examQuestions.map(q => (
      <div key={q.idx} className={`question-result ${q.result}`}>
        <span className="result-icon">{resultIcon(q.result)}</span>
        <div>
          <p className="q-text">{q.question_text}</p>
          <p className="q-answer">Your answer: {q.student_answer}</p>
          {q.result !== 'correct' && <p className="q-correct">Correct: {q.expected_answer}</p>}
        </div>
      </div>
    ))}
  </div>

  {/* Strengths */}
  <div className="strengths">
    <h3>Strengths</h3>
    <ul>{feedback.strengths.map(s => <li>{s}</li>)}</ul>
  </div>

  {/* Weak Areas */}
  <div className="weak-areas">
    <h3>Areas to Improve</h3>
    <ul>{feedback.weak_areas.map(w => <li>{w}</li>)}</ul>
  </div>

  {/* Patterns */}
  {feedback.patterns.length > 0 && (
    <div className="patterns">
      <h3>Patterns</h3>
      <ul>{feedback.patterns.map(p => <li>{p}</li>)}</ul>
    </div>
  )}

  {/* Next Steps */}
  <div className="next-steps">
    <h3>What to Do Next</h3>
    <ul>{feedback.next_steps.map(n => <li>{n}</li>)}</ul>
  </div>

  {/* Action buttons */}
  <button onClick={startTeachMe}>Study in Teach Me</button>
  <button onClick={startClarifyDoubts}>Ask Questions</button>
  <button onClick={retakeExam}>Retake Exam</button>
  <button onClick={viewReportCard}>View Report Card</button>
</div>
```

---

## 15. Frontend: Report Card (Scorecard Refactor)

### 15.1 Rename

- Rename route: `/scorecard` → `/report-card` (keep `/scorecard` as redirect)
- Rename in navigation: "Scorecard" → "Report Card"
- Rename component: `ScorecardPage` → `ReportCardPage`
- Rename CSS classes

### 15.2 Subtopic Detail Changes

The subtopic detail view changes from showing mastery to showing:

**Learning Progress Section:**
- Coverage bar: "60% covered"
- Last studied: "Last studied 3 days ago"
- Revision nudge (if applicable): "It's been a while — take a quick exam to check"

**Exam Results Section:**
- Latest exam score: "7/10 — 70%"
- Strengths summary from latest exam
- Weak areas from latest exam
- Score history graph (line chart with all exam scores over time)
- Number of exams taken

If no exams taken: "Take an exam to test your knowledge" with a button.

**Action Buttons:**
- "Continue Learning" → Resumes Teach Me (or starts new)
- "Ask Questions" → Starts Clarify Doubts
- "Take Exam" → Starts Exam

### 15.3 Overview Hero Changes

The overall hero changes from a single mastery score to:
- Overall coverage across all subtopics
- Total sessions
- Total topics studied
- Maybe: latest exam activity summary

### 15.4 Trend Chart

Keep existing trend chart for coverage over time. Add exam score trend as a separate line or separate chart.

---

## 16. Frontend: Session History

### 16.1 Mode Labels

Each session card shows a mode badge:

```tsx
<span className={`mode-badge mode-${session.mode}`}>
  {modeLabels[session.mode]}
</span>
```

Labels: "Teach Me", "Clarify Doubts", "Exam"

### 16.2 Mode-Specific Data

| Mode | Shows |
|------|-------|
| Teach Me | Coverage % achieved |
| Clarify Doubts | Concepts discussed (as chips) |
| Exam | Score (e.g., "7/10") |

### 16.3 Filter by Mode

Add a mode filter dropdown/toggle to the history page:
- All / Teach Me / Clarify Doubts / Exam

---

## 17. API Contract Changes

### 17.1 New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/sessions/resumable?guideline_id=X` | Find paused Teach Me session |
| `POST` | `/sessions/{id}/pause` | Pause a Teach Me session |
| `POST` | `/sessions/{id}/end-exam` | End exam early |
| `GET` | `/sessions/report-card` | Report card (replaces scorecard) |

### 17.2 Modified Endpoints

| Endpoint | Change |
|----------|--------|
| `POST /sessions` | Request gains `mode` field. Response gains `mode`, `past_discussions` |
| `POST /sessions/{id}/step` | Response gains mode-specific fields |
| `GET /sessions/history` | Response entries gain `mode`, mode-specific data |
| `GET /sessions/subtopic-progress` | Response gains `coverage`, `last_studied`, `exam_scores` |
| `GET /sessions/scorecard` | Kept as alias → redirects to report-card |

### 17.3 WebSocket Changes

The WebSocket state update message gains:
```json
{
  "type": "state_update",
  "payload": {
    "mode": "teach_me",
    "coverage": 60.0,
    "concepts_discussed": [],
    "exam_progress": null
  }
}
```

For exam mode, `exam_progress`:
```json
{
  "current_question": 3,
  "total_questions": 7,
  "correct_so_far": 2
}
```

---

## 18. Migration Strategy

### 18.1 Database Migration

1. Add new columns to `sessions` table (all nullable/defaulted — no breaking change)
2. Backfill: `UPDATE sessions SET mode = 'teach_me' WHERE mode IS NULL`
3. Create indexes

### 18.2 Backend Rollout

1. Deploy backend with new columns + mode support
2. Default mode is `teach_me` — all existing flows work unchanged
3. New endpoints are additive (no breaking changes)
4. Old `/sessions/scorecard` endpoint kept as alias

### 18.3 Frontend Rollout

1. Deploy frontend with mode selection
2. Feature flag (optional): `VITE_FEATURE_LEARNING_MODES=true`
3. If flag is off, skip mode selection and go straight to Teach Me (current behavior)

### 18.4 Backward Compatibility

- Existing sessions (no `mode` field in state_json) default to `teach_me`
- Existing API consumers (no `mode` in request) default to `teach_me`
- Scorecard endpoint kept alongside report-card
- Mastery data still computed internally for Teach Me pacing

---

## 19. Implementation Order

### Phase 1: Foundation (Backend)
1. Database migration (add columns)
2. `SessionState` model changes (mode, coverage fields, exam fields)
3. `CreateSessionRequest` / `CreateSessionResponse` changes
4. `SessionService.create_new_session` mode branching
5. Coverage tracking in orchestrator for Teach Me

### Phase 2: Teach Me Enhancements (Backend + Frontend)
6. Pause/resume backend (endpoints, service logic, recap generation)
7. Coverage computation in report card service
8. Frontend: mode selection screen
9. Frontend: Teach Me UI changes (coverage display, pause button)

### Phase 3: Clarify Doubts (Backend + Frontend)
10. Clarify Doubts prompts
11. Clarify Doubts turn processing in orchestrator
12. Clarify Doubts output schema
13. Past discussions query
14. Frontend: Clarify Doubts UI (concept chips, end session, past discussions)

### Phase 4: Exam Mode (Backend + Frontend)
15. Exam question generation (service + prompts)
16. Exam turn processing in orchestrator
17. Exam evaluation and feedback generation
18. End early endpoint
19. Frontend: Exam UI (question counter, running score, results screen)

### Phase 5: Report Card (Backend + Frontend)
20. Report card service (coverage, exam history, last studied, nudges)
21. Report card API endpoint
22. Frontend: Report Card page (rename, coverage display, exam results, trend graph, action buttons)

### Phase 6: Session History & Polish
23. Session history mode labels + mode-specific data
24. Session history mode filter
25. WebSocket state update changes
26. DevTools updates (mode display)
27. End-to-end testing

---

## 20. Risk & Open Questions

### Risks

1. **Exam question quality** — LLM-generated exam questions may be too easy, too hard, or ambiguous. Mitigation: careful prompt engineering, teacher review of sample exams, option to use pre-authored question banks later.

2. **Coverage accuracy in Clarify Doubts** — Mapping free-form student questions to study plan concepts requires the LLM to correctly identify which concepts are being discussed. Mitigation: provide the full concept list in the prompt; accept that coverage tracking in this mode is approximate.

3. **Prompt complexity** — Three sets of prompts to maintain. Mitigation: share common elements (student profile, topic info) via templates; mode-specific parts are isolated.

4. **State migration** — Existing sessions in `state_json` don't have mode/coverage fields. Mitigation: all new fields have defaults; deserialization handles missing fields gracefully (Pydantic defaults).

### Open Questions

1. **Exam question count** — PRD says 5-10 (default 7). Should this be configurable per subtopic or grade level?

2. **Coverage granularity** — Should coverage track at the concept level (current plan) or at the study plan step level? Concepts can appear in multiple steps — do we count once or per step?

3. **Partial credit in exams** — PRD mentions "partially correct." How does this affect the score? Current plan: only fully correct answers count toward the score number, but partial is tracked separately for feedback.

4. **Subject/topic-level aggregation** — PRD says "the exact aggregation approach can be refined." Should subject-level score be average coverage, average exam score, or a weighted combo?

5. **Offline/mobile** — Does the pause/resume flow need to account for unreliable connectivity? Current plan assumes online-only.

---

## Appendix: File Change Map

### New Files
| File | Purpose |
|------|---------|
| `llm-backend/tutor/prompts/clarify_doubts_prompts.py` | Clarify Doubts system + turn prompts |
| `llm-backend/tutor/prompts/exam_prompts.py` | Exam generation + evaluation prompts |
| `llm-backend/tutor/services/exam_service.py` | Exam question generation |
| `llm-frontend/src/components/ModeSelection.tsx` | Mode selection screen component |

### Modified Files (Backend)
| File | Changes |
|------|---------|
| `shared/models/entities.py` | Add `mode`, `is_paused`, `exam_score`, `exam_total` columns |
| `shared/models/schemas.py` | New schemas, rename scorecard → report card |
| `shared/models/domain.py` | Add `SessionMode` type if needed |
| `tutor/models/session_state.py` | Add `mode`, coverage, exam fields, `ExamQuestion`, `ExamFeedback` |
| `tutor/services/session_service.py` | Mode-aware session creation, pause/resume |
| `tutor/services/scorecard_service.py` | Rename, add coverage/exam/nudge logic |
| `tutor/orchestration/orchestrator.py` | Mode-aware turn routing, exam processing |
| `tutor/agents/master_tutor.py` | Mode-aware prompt building, exam/clarify output schemas |
| `tutor/prompts/orchestrator_prompts.py` | Mode-specific welcome messages |
| `tutor/api/sessions.py` | New endpoints (resumable, pause, end-exam, report-card) |
| `shared/repositories/session_repository.py` | Mode-specific data in list_by_user |

### Modified Files (Frontend)
| File | Changes |
|------|---------|
| `src/TutorApp.tsx` | Mode selection step, mode-specific chat UI, pause/resume |
| `src/pages/ScorecardPage.tsx` | Rename to ReportCardPage, coverage/exam display |
| `src/pages/SessionHistoryPage.tsx` | Mode labels, mode-specific data, filters |
| `src/api.ts` | New API methods, updated types |
| `src/App.tsx` | Add `/report-card` route, keep `/scorecard` redirect |
| `src/App.css` | New styles for mode selection, exam results, concept chips |
