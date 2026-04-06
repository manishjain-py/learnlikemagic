# Tech Implementation Plan: Teach Me / Let's Practice Split

**Date:** 2026-04-06
**Status:** Draft
**PRD:** `docs/feature-development/teach-me-practice-split/prd.md`
**Author:** Tech Impl Plan Generator + Manish

---

## 1. Overview

Split the current Teach Me flow into two separate session modes: Teach Me (explanation cards only) and Let's Practice (question-heavy adaptive practice). Teach Me's `complete_card_phase()` is rewritten to end the session instead of transitioning to the interactive phase. A new `practice` mode is added to the orchestrator following the same mode-routing pattern as `clarify_doubts` and `exam`. Practice sessions auto-attach context from prior Teach Me sessions and support pause/resume. Coverage computation is updated to include both modes.

---

## 2. Architecture Changes

### Updated mode routing in orchestrator

```
Student Message
    │
    v
TRANSLATE + SAFETY (parallel)
    │
    v
MODE ROUTER
    ├─ teach_me       → process_turn()      [UNCHANGED — but now only reached for v1 non-card sessions]
    ├─ clarify_doubts → _process_clarify_turn()   [UNCHANGED]
    ├─ exam           → _process_exam_turn()      [UNCHANGED]
    └─ practice       → _process_practice_turn()  [NEW]
```

### Updated Teach Me card phase completion

```
BEFORE: Cards → complete_card_phase("clear") → v2 plan + bridge turn → interactive phase
AFTER:  Cards → complete_card_phase("clear") → summary + CTA → session ends
```

### New modules / major changes

| Change | Type | Files |
|--------|------|-------|
| Practice mode in orchestrator | New method | `tutor/orchestration/orchestrator.py` |
| Practice prompts | New file | `tutor/prompts/practice_prompts.py` |
| Practice plan generation | New method | `study_plans/services/generator_service.py` |
| Card phase completion rewrite | Major modify | `tutor/services/session_service.py` |
| Practice session creation + context handoff | Major modify | `tutor/services/session_service.py` |
| Coverage includes practice | Modify | `tutor/services/report_card_service.py` |
| Practice mode on frontend | Modify | `ModeSelection.tsx`, `ChatSession.tsx`, `ModeSelectPage.tsx`, `App.tsx`, `api.ts` |

---

## 3. Database Changes

### Modified tables

| Table | Change | Details |
|-------|--------|---------|
| `sessions` | Extend `mode` values | Add `'practice'` as valid value. No schema change needed — `mode` is VARCHAR, not an enum. Just update Python `SessionMode` literal |

No new tables. Practice sessions use the existing `sessions` table with `mode='practice'`. Practice-specific state lives in `state_json` (same pattern as exam and clarify_doubts).

### Migration plan

No DB migration needed. The `mode` column is VARCHAR — adding `'practice'` as a value only requires updating the Python `SessionMode` type. The existing partial unique index `idx_sessions_one_paused_per_user_guideline` on `(user_id, guideline_id) WHERE is_paused = TRUE` already supports practice sessions since paused practice sessions will have `is_paused=TRUE`.

**Decision:** No migration script because the DB schema doesn't change. Practice sessions write `mode='practice'` into the existing VARCHAR column.

---

## 4. Backend Changes

### 4.1 Session State Model

**File:** `tutor/models/session_state.py`

Update `SessionMode` type:

```python
SessionMode = Literal["teach_me", "clarify_doubts", "exam", "practice"]
```

Add practice-specific fields to `SessionState`:

```python
# Practice state
practice_source: Optional[Literal["teach_me", "cold"]] = Field(
    default=None, description="How this practice session was initiated"
)
source_session_id: Optional[str] = Field(
    default=None, description="Teach Me session ID that provided context (if any)"
)
practice_questions_answered: int = Field(
    default=0, description="Total questions answered in this practice session"
)
practice_mastery_achieved: bool = Field(
    default=False, description="Whether mastery threshold was met"
)
```

Update `is_complete` property:

```python
@property
def is_complete(self) -> bool:
    if self.mode == "clarify_doubts":
        return self.clarify_complete
    if self.mode == "practice":
        return self.practice_mastery_achieved
    if not self.topic:
        return False
    if self.is_refresher:
        return self.card_phase is not None and self.card_phase.completed
    # teach_me: complete when card phase is completed (no more interactive steps)
    if self.card_phase is not None:
        return self.card_phase.completed
    return self.current_step > self.topic.study_plan.total_steps  # v1 fallback
```

**Decision:** Teach Me `is_complete` now checks `card_phase.completed` for card-based sessions. The `current_step > total_steps` check is kept as v1 fallback for topics without cards (out of scope but harmless to keep).

---

### 4.2 Session Service

**File:** `tutor/services/session_service.py`

#### Practice session creation (in `create_new_session`)

Add `practice` branch after existing mode branches (~line 62):

```python
if mode == "practice":
    source_session_id = getattr(request, 'source_session_id', None)
    context_data = self._resolve_practice_context(
        user_id, request.goal.guideline_id, source_session_id
    )
    # Generate practice plan
    practice_plan = self._generate_practice_plan(
        guideline, student_context, context_data
    )
    topic = convert_guideline_to_topic(guideline, study_plan_record, is_refresher=False)
    session = create_session(topic=topic, student_context=student_context, mode="practice")
    session.practice_source = context_data["source"]
    session.source_session_id = context_data.get("source_session_id")
    session.precomputed_explanation_summary = context_data.get("explanation_summary")
    # Set practice plan on session
    topic.study_plan = practice_plan
    # Generate dynamic welcome
    welcome, audio_text = asyncio.run(
        self.orchestrator.generate_practice_welcome(session)
    )
```

New private methods:

- `_resolve_practice_context(user_id, guideline_id, source_session_id) → dict`
  - If `source_session_id` provided: load that session's card phase state + explanation summary
  - Else: query most recent completed `teach_me` session for this user+guideline
  - Returns `{"source": "teach_me"|"cold", "source_session_id": str|None, "explanation_summary": str|None, "check_in_struggles": list|None}`

- `_generate_practice_plan(guideline, student_context, context_data) → StudyPlan`
  - Calls `StudyPlanGeneratorService.generate_practice_plan()`
  - Passes check-in struggles for struggle-weighted plan

- `_find_most_recent_completed_teach_me(user_id, guideline_id) → Optional[SessionState]`
  - Query: `sessions WHERE user_id=? AND guideline_id=? AND mode='teach_me' AND state_json LIKE '%"completed": true%' ORDER BY created_at DESC LIMIT 1`
  - Parse `state_json`, check `card_phase.completed == True`
  - Return the deserialized SessionState or None

**Decision:** The auto-context lookup uses a simple DB query + JSON parsing. No new index needed — the existing `idx_session_user_guideline` index covers `(user_id, guideline_id, mode)`.

#### Card phase completion rewrite

Rewrite `complete_card_phase()` for `action="clear"`:

```python
if action == "clear":
    session.complete_card_phase()
    
    # Build explanation summary for future practice context
    precomputed_summary = self._build_precomputed_summary(session)
    session.precomputed_explanation_summary = precomputed_summary
    
    # Add card concepts to coverage
    if session.card_phase:
        for vk in session.card_phase.variants_shown:
            exp = explanation_repo.get_variant(session.card_phase.guideline_id, vk)
            if exp and exp.cards_json:
                for card in exp.cards_json:
                    concept = card.get("title") or card.get("concept")
                    if concept:
                        session.concepts_covered_set.add(concept)
                        session.card_covered_concepts.add(concept)
    
    # NO v2 plan generation, NO bridge turn
    # Session is now complete — persist and return summary
    self._persist_session_state(session_id, session, expected_version)
    
    return {
        "action": "teach_me_complete",
        "message": summary_message,       # concepts covered recap
        "audio_text": summary_audio,
        "is_complete": True,
        "coverage": session.coverage_percentage,
        "concepts_covered": list(session.concepts_covered_set),
        "guideline_id": session.card_phase.guideline_id if session.card_phase else None,
    }
```

For `action="explain_differently"` when all variants exhausted:

```python
# All variants exhausted — still end the session (no confused bridge)
session.complete_card_phase()
precomputed_summary = self._build_precomputed_summary(session)
session.precomputed_explanation_summary = precomputed_summary
self._persist_session_state(session_id, session, expected_version)

return {
    "action": "teach_me_complete",
    "message": "We've looked at this from a few angles. Let's practice to see what stuck!",
    "audio_text": "We've looked at this from a few angles. Let's practice to see what stuck!",
    "is_complete": True,
    "suggest_practice": True,
}
```

**Decision:** The "all variants exhausted" case now also ends the session (instead of generating a "confused" bridge turn). The practice mode handles confused students via its adaptive question → explain flow. The `generate_bridge_turn()` method becomes dead code.

---

### 4.3 Orchestrator

**File:** `tutor/orchestration/orchestrator.py`

#### Mode routing (in `process_turn`, ~line 262)

Add practice branch:

```python
if session.mode == "clarify_doubts":
    return await self._process_clarify_turn(session, context, turn_id, start_time)
elif session.mode == "exam":
    return await self._process_exam_turn(session, context, turn_id, start_time)
elif session.mode == "practice":
    return await self._process_practice_turn(session, context, turn_id, start_time)
```

#### New method: `_process_practice_turn()`

Follows `_process_clarify_turn()` pattern:

```python
async def _process_practice_turn(
    self, session: SessionState, context: AgentContext, turn_id: str, start_time: float
) -> TurnResult:
    tutor_start = time.time()
    self.master_tutor.set_session(session)
    tutor_output: TutorTurnOutput = await self.master_tutor.execute(context)
    
    # Track mastery updates
    if tutor_output.mastery_updates:
        for update in tutor_output.mastery_updates:
            session.update_mastery(update.concept, update.score)
            session.concepts_covered_set.add(update.concept)
    
    # Track questions answered
    if tutor_output.question_asked:
        # Previous question was answered — increment counter
        session.practice_questions_answered += 1
    
    # Check mastery completion (FR-27)
    self._check_practice_mastery(session, tutor_output)
    
    session.add_message(create_teacher_message(tutor_output.response, audio_text=tutor_output.audio_text))
    
    return TurnResult(
        response=tutor_output.response,
        audio_text=tutor_output.audio_text,
        intent=tutor_output.intent,
        specialists_called=["master_tutor"],
        state_changed=True,
        visual_explanation=await self._generate_pixi_code(tutor_output.visual_explanation) if tutor_output.visual_explanation else None,
        question_format=tutor_output.question_format.model_dump() if tutor_output.question_format else None,
    )
```

#### New method: `_check_practice_mastery()`

```python
def _check_practice_mastery(self, session: SessionState, tutor_output: TutorTurnOutput):
    """Check if practice session has reached mastery threshold (FR-27)."""
    if session.practice_mastery_achieved:
        return  # Already done
    
    min_questions = 5
    mastery_threshold = 0.7
    max_questions = 20
    
    if session.practice_questions_answered < min_questions:
        return
    
    # Force wrap up at max questions
    if session.practice_questions_answered >= max_questions:
        session.practice_mastery_achieved = True
        return
    
    # Check if tutor signaled completion
    if tutor_output.session_complete:
        session.practice_mastery_achieved = True
        return
    
    # Check mastery across all tested concepts
    if session.mastery_estimates:
        avg_mastery = sum(session.mastery_estimates.values()) / len(session.mastery_estimates)
        all_above_threshold = all(v >= mastery_threshold for v in session.mastery_estimates.values())
        if avg_mastery >= mastery_threshold and all_above_threshold:
            session.practice_mastery_achieved = True
```

#### New method: `generate_practice_welcome()`

```python
async def generate_practice_welcome(self, session: SessionState) -> tuple[str, Optional[str]]:
    """Generate a dynamic welcome for practice mode."""
    self.master_tutor.set_session(session)
    output = await self.master_tutor.generate_welcome(session)
    return output.response, output.audio_text
```

**Decision:** Reuses `master_tutor.generate_welcome()` with practice-specific prompts set by the session's mode. No new agent needed.

---

### 4.4 Practice Prompts

**New file:** `tutor/prompts/practice_prompts.py`

Follows the pattern of `clarify_doubts_prompts.py`:

```python
PRACTICE_SYSTEM_PROMPT = PromptTemplate(
    """You are a friendly practice coach helping a Grade {grade} student reinforce their understanding of {topic_name}.

## Your Role
You are in PRACTICE mode. Your primary job is ASKING QUESTIONS (~80% of turns). 
You only explain when the student clearly doesn't understand (not on a single wrong answer).

## Subject & Curriculum Scope
Subject: {subject}
Curriculum scope: {curriculum_scope}

## Study Plan Concepts
{concepts_list}

{explanation_context_section}

## Rules
1. START with a question. Don't explain first — assess what the student knows.
2. Scaffolded correction: 1st wrong → guiding question, 2nd wrong → targeted hint, 3rd+ → explain directly and warmly.
3. After 3+ errors revealing the same gap, PAUSE questioning. Explain that concept. Then resume questions.
4. Question difficulty progresses: {difficulty_start} first, advance as student demonstrates understanding.
5. Use structured question formats (single_select, fill_in_the_blank, multi_select) for most questions. Open-ended for reasoning checks.
6. Vary question types — never ask the same format twice in a row.
7. {card_reference_rule}
8. Keep it casual and encouraging — this is practice, not an exam. No scores shown. No question counters.
9. When the student has demonstrated mastery across key concepts (minimum {min_questions} questions), wrap up warmly.
10. If the student struggles on everything (5+ consecutive wrong), gently suggest: "This topic seems new — want to try Teach Me first?"

## Mastery Completion Rules
- Minimum {min_questions} questions before you can end.
- Target: 70% mastery across all concepts, with at least 2 questions per key concept.
- Maximum ~{max_questions} questions — wrap up after that even if mastery is uneven.
- Set session_complete=true when mastery criteria are met.

## Language
{response_language_instruction}
{audio_language_instruction}

{personalization_block}""",
    name="practice_system",
)

PRACTICE_TURN_PROMPT = PromptTemplate(
    """## Practice Turn
Questions answered so far: {questions_answered}
Current mastery: {mastery_summary}
Known misconceptions: {misconceptions}
{struggle_summary}

## Conversation History
{conversation_history}

## Student's Message
{student_message}""",
    name="practice_turn",
)
```

Template variables:
- `explanation_context_section`: Filled with precomputed_explanation_summary when available (post-Teach-Me), empty when cold
- `card_reference_rule`: "Reference card analogies/examples as shared vocabulary" (post-Teach-Me) or "Do NOT reference any cards or prior explanations — the student hasn't seen them" (cold)
- `difficulty_start`: "medium" for cold start, "easy/medium" for post-Teach-Me
- `min_questions`: 5
- `max_questions`: 20

---

### 4.5 Study Plan Generator

**File:** `study_plans/services/generator_service.py`

New method:

```python
def generate_practice_plan(
    self,
    guideline: TeachingGuideline,
    student_context: Optional["StudentContext"] = None,
    check_in_struggles: Optional[list] = None,
    is_cold_start: bool = False,
) -> dict:
    """Generate a practice-focused study plan (question-heavy, no explain steps)."""
```

Practice plans use the same `SessionPlanStep` model but with different step types:
- Steps are all question types: `check_understanding`, `guided_practice`, `independent_practice`
- No `explain` or `extend` steps upfront
- When check-in struggles are available, early steps target those concepts
- Cold-start plans start at medium difficulty
- 5-8 steps total

**Decision:** Reuses the existing `SessionPlanStep` model and `StudyPlanGeneratorService` class. Adding a new method rather than modifying `generate_session_plan()` keeps the existing v2 plan generation intact (it's still used for non-card Teach Me sessions and may be needed for backwards compatibility).

---

### 4.6 Report Card Service

**File:** `tutor/services/report_card_service.py`

#### `_group_sessions()`: Include practice in coverage

Change line 239 from:

```python
if mode == "teach_me":
```

to:

```python
if mode in ("teach_me", "practice"):
```

This makes practice sessions contribute their `concepts_covered_set` and `mastery_estimates` to coverage, alongside teach_me sessions.

#### `get_topic_progress()`: Include practice in coverage

Change line 78 from:

```python
if mode != "teach_me":
    continue
```

to:

```python
if mode not in ("teach_me", "practice"):
    continue
```

#### Track `last_practiced` date

In `_group_sessions()`, add tracking for practice-specific last date:

```python
if mode == "practice":
    # Track last_practiced separately
    existing_last_practiced = existing.get("last_practiced")
    if not existing_last_practiced or session_date > existing_last_practiced:
        existing["last_practiced"] = session_date
```

#### `_build_report()`: Include last_practiced in output

Add `"last_practiced"` field to the per-topic dict in `_build_report()`.

#### Response schema update

**File:** `shared/models/schemas.py`

Add `last_practiced: Optional[str] = None` to `ReportCardTopic`.

Add `last_practiced: Optional[str] = None` to `TopicProgressEntry` (for mode selection indicators).

---

### 4.7 API Layer

**File:** `shared/models/schemas.py`

Update `CreateSessionRequest`:

```python
class CreateSessionRequest(BaseModel):
    student: Student
    goal: Goal
    mode: Literal["teach_me", "clarify_doubts", "exam", "practice"] = "teach_me"
    source_session_id: Optional[str] = None  # For Teach Me → Practice handoff
```

**File:** `tutor/api/sessions.py`

The existing `POST /sessions` and `POST /{session_id}/step` endpoints work as-is — they pass mode through to `SessionService` which handles routing.

Add pause support for practice in `POST /{session_id}/pause` (currently only checks `teach_me`):

```python
if session_state.mode not in ("teach_me", "practice"):
    raise HTTPException(status_code=400, detail="Only Teach Me and Practice sessions can be paused")
```

**File:** `shared/repositories/session_repository.py`

Update `list_by_guideline()` to include practice sessions and return `last_practiced` date.

---

## 5. Frontend Changes

### New route

**File:** `llm-frontend/src/App.tsx`

```tsx
<Route path="/learn/:subject/:chapter/:topic/practice/:sessionId" element={
  <ChatSession key="practice" />
} />
```

### Modified pages

| Component | Changes |
|-----------|---------|
| `ModeSelection.tsx` | Add 4th mode card (Let's Practice). Show "Last practiced" indicator. Update `ModeSelectionProps` to accept `'practice'` mode. Add `practice` to `MODE_LOADING_MESSAGES`. |
| `ModeSelectPage.tsx` | Handle `onSelectMode('practice')` — create practice session via API, navigate to practice route. |
| `ChatSession.tsx` | Handle `sessionPhase` for practice (straight to interactive, no card carousel). Handle card phase completion returning `action: "teach_me_complete"` — show summary + Practice CTA instead of transitioning to interactive. |
| `api.ts` | Update `CreateSessionRequest` type to include `'practice'` mode and `source_session_id?`. Update `GuidelineSessionEntry` type with `last_practiced?`. |

### ModeSelection.tsx changes

Add 4th mode card:

```tsx
<button className="selection-card" onClick={() => onSelectMode('practice')}>
  <strong>Let's Practice</strong>
  <span>Practice what you learned</span>
</button>
```

Show practice indicator when `sessions` includes completed practice sessions:

```tsx
const lastPracticed = sessions
  .filter(s => s.mode === 'practice' && s.is_complete)
  .sort((a, b) => /* latest first */)
  [0]?.created_at;

{lastPracticed && (
  <span className="practice-indicator">Practiced {formatRelativeDate(lastPracticed)}</span>
)}
```

### ChatSession.tsx changes

Card phase completion handler update — when `cardAction()` returns `action: "teach_me_complete"`:

```tsx
if (result.action === 'teach_me_complete') {
  // Show summary + CTA instead of transitioning to interactive
  setTeachMeComplete(true);
  setCoverage(result.coverage);
  setConceptsCovered(result.concepts_covered);
  // Don't transition to interactive phase
  return;
}
```

New state and UI for Teach Me completion with Practice CTA:

```tsx
const [teachMeComplete, setTeachMeComplete] = useState(false);

// In render — show summary + CTA when teachMeComplete
{teachMeComplete && (
  <div className="teach-me-complete">
    <h3>Great job!</h3>
    <p>You've covered {conceptsCovered.length} concepts</p>
    <button className="primary-cta" onClick={handleStartPractice}>
      Let's Practice — put what you learned to work!
    </button>
    <button className="secondary-action" onClick={handleDone}>
      I'm done for now
    </button>
  </div>
)}
```

`handleStartPractice` creates a practice session via API with `source_session_id` and navigates to the practice route.

### api.ts changes

```typescript
export interface CreateSessionRequest {
  student: Student;
  goal: Goal;
  mode?: 'teach_me' | 'clarify_doubts' | 'exam' | 'practice';
  source_session_id?: string;
}

export interface GuidelineSessionEntry {
  // ... existing fields ...
  last_practiced?: string | null;
}
```

---

## 6. LLM Integration

### Practice prompts

Practice mode reuses the existing `MasterTutorAgent` with practice-specific system and turn prompts loaded from `tutor/prompts/practice_prompts.py`. The agent selection in `MasterTutorAgent.execute()` checks `session.mode` and loads the appropriate prompt templates.

**File:** `tutor/agents/master_tutor.py`

Add practice mode prompt selection in the method that builds system/turn prompts:

```python
if session.mode == "practice":
    system_prompt = PRACTICE_SYSTEM_PROMPT.format(...)
    turn_prompt = PRACTICE_TURN_PROMPT.format(...)
```

### Practice plan generation

Uses the same LLM config as `study_plan_generator` component. Single LLM call with structured output (`SessionPlan` schema). Low reasoning effort (practice plans are simpler than full study plans).

### Cost and latency

- Practice welcome: 1 LLM call (~2s). Same as current clarify_doubts welcome.
- Per-turn: 1 LLM call (~2-4s). Same as current teach_me turns.
- Practice plan generation: 1 LLM call at session creation (~3s). Same as current v2 plan generation.
- No additional cost beyond what the current interactive phase already incurs (the cost just moves from Teach Me to Practice).

---

## 7. Configuration & Environment

No new environment variables. No config changes. Practice mode uses the existing `tutor` LLM config for the master tutor and `study_plan_generator` for plan generation.

---

## 8. Implementation Order

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1 | Add `"practice"` to `SessionMode`, add practice fields to `SessionState`, update `is_complete` | `tutor/models/session_state.py` | — | Unit test: create practice session state, verify is_complete logic |
| 2 | Create practice prompts (system + turn) | `tutor/prompts/practice_prompts.py` | — | Manual: review prompt text |
| 3 | Add `generate_practice_plan()` to study plan generator | `study_plans/services/generator_service.py` | — | Unit test: generate practice plan, verify no explain steps |
| 4 | Add `_process_practice_turn()`, `_check_practice_mastery()`, `generate_practice_welcome()` to orchestrator | `tutor/orchestration/orchestrator.py` | Steps 1-2 | Unit test: mock LLM, verify mastery check logic |
| 5 | Add practice session creation + `_resolve_practice_context()` + `_find_most_recent_completed_teach_me()` to session service | `tutor/services/session_service.py` | Steps 1-4 | Integration test: create practice session with/without source |
| 6 | Rewrite `complete_card_phase()` — return `teach_me_complete` instead of bridge turn | `tutor/services/session_service.py` | Step 1 | Integration test: complete card phase returns summary, no bridge |
| 7 | Update `CreateSessionRequest` schema, add `source_session_id`. Update pause endpoint to accept practice. | `shared/models/schemas.py`, `tutor/api/sessions.py` | Step 5 | API test: create practice session via REST |
| 8 | Update report card: coverage includes practice, add `last_practiced` tracking | `tutor/services/report_card_service.py`, `shared/models/schemas.py` | Step 1 | Unit test: coverage from teach_me + practice combined |
| 9 | Add master tutor practice prompt selection | `tutor/agents/master_tutor.py` | Step 2 | Integration test: practice turn uses correct prompts |
| 10 | Frontend: Add practice route in `App.tsx` | `App.tsx` | — | Manual: route resolves |
| 11 | Frontend: Update `api.ts` types | `api.ts` | — | TypeScript compile |
| 12 | Frontend: Add practice mode to `ModeSelection.tsx` + `ModeSelectPage.tsx` | `ModeSelection.tsx`, `ModeSelectPage.tsx` | Steps 10-11 | Manual: 4th mode card appears, creates practice session |
| 13 | Frontend: Rewrite card phase completion in `ChatSession.tsx` — summary + CTA | `ChatSession.tsx` | Steps 6, 11 | Manual: Teach Me ends with CTA, clicking starts practice |
| 14 | Frontend: Practice session UI in `ChatSession.tsx` — interactive-only, pause support | `ChatSession.tsx` | Steps 10-12 | Manual: full practice flow works |

**Rationale:** Backend first (models → prompts → orchestrator → service → API → report card), then frontend. Each backend step is independently testable. Frontend steps are ordered by dependency (routing → API types → components).

---

## 9. Testing Plan

### Unit tests

| Test | What it Verifies | Key Mocks |
|------|------------------|-----------|
| `test_session_state_practice_mode` | Practice fields serialize/deserialize correctly. `is_complete` returns True when `practice_mastery_achieved=True` | None |
| `test_teach_me_is_complete_card_phase` | Teach Me `is_complete` returns True when `card_phase.completed=True` (new behavior) | None |
| `test_check_practice_mastery_min_questions` | Mastery not triggered before 5 questions | None |
| `test_check_practice_mastery_threshold` | Mastery triggered at 70% across all concepts | None |
| `test_check_practice_mastery_max_questions` | Mastery forced at 20 questions | None |
| `test_resolve_practice_context_with_source` | Context loaded from specified source session | Mock session_repo |
| `test_resolve_practice_context_auto_attach` | Context auto-loaded from most recent completed Teach Me | Mock session_repo |
| `test_resolve_practice_context_cold` | Returns cold context when no prior Teach Me exists | Mock session_repo |
| `test_complete_card_phase_returns_summary` | `complete_card_phase("clear")` returns `teach_me_complete` action, no bridge turn | Mock orchestrator |
| `test_report_card_coverage_includes_practice` | Coverage computed from both teach_me and practice `concepts_covered_set` | Mock DB |
| `test_report_card_last_practiced` | `last_practiced` date returned for topics with practice sessions | Mock DB |

### Integration tests

| Test | What it Verifies |
|------|------------------|
| `test_create_practice_session_from_teach_me` | Full flow: create Teach Me → complete cards → create practice with source_session_id → context attached |
| `test_create_practice_session_cold` | Create practice without prior Teach Me → no explanation context in state |
| `test_practice_turn_processing` | Submit answer to practice session → orchestrator routes to `_process_practice_turn` → mastery updated |
| `test_practice_pause_resume` | Pause practice session → resume → state preserved |
| `test_complete_card_phase_no_bridge` | Complete card phase → returns summary, no interactive transition |

### Manual verification

1. Start Teach Me → go through cards → verify summary + CTA appears (not bridge turn)
2. Click "Let's Practice" CTA → verify practice session starts with context-aware welcome
3. Answer questions in practice → verify mastery tracking, scaffolded correction
4. End practice via mastery → verify summary with concepts and Exam nudge
5. Start Let's Practice from mode selection (cold) → verify no card references in tutor messages
6. Start Let's Practice from mode selection after prior Teach Me → verify auto-context (card references present)
7. Check report card → verify coverage includes both Teach Me and Practice data
8. Check mode selection → verify 4th mode card + "Last practiced" indicator

---

## 10. Deployment Considerations

- **No infrastructure changes.** No Terraform, no new environment variables, no new secrets.
- **No DB migration.** The `mode` column is VARCHAR — `'practice'` is just a new value.
- **Backwards compatibility:** Existing sessions are unaffected. The `is_complete` change for teach_me mode only affects sessions with `card_phase` (which always have `card_phase.completed` set correctly). The v1 fallback (`current_step > total_steps`) handles legacy sessions.
- **Deployment order:** Deploy backend first (it handles both old and new clients). Then deploy frontend.
- **Rollback:** If practice mode has issues, disable the frontend mode card. Backend continues to work — practice sessions just won't be created. No data corruption risk.
- **Feature flag (optional):** Could add a `practice_mode_enabled` flag to gate the feature. Not strictly necessary since the frontend controls visibility. Decide based on rollout strategy.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `complete_card_phase` rewrite breaks existing Teach Me flow | Medium | High | Thorough integration tests for both old (v1) and new (card-based) Teach Me sessions. Verify existing tests pass |
| `is_complete` change for teach_me causes stale sessions to appear complete/incomplete | Low | Medium | The new check (`card_phase.completed`) only applies when `card_phase is not None`. v1 sessions without card_phase fall through to original logic |
| Practice mastery threshold too low/high for real students | Medium | Medium | Make thresholds configurable via constants (not hardcoded in orchestrator). Tunable without code change |
| Auto-context query is slow on large session tables | Low | Low | Existing `idx_session_user_guideline` index covers the query. Single row returned (LIMIT 1) |
| LLM generates poor practice questions (too easy/hard) | Medium | Medium | Practice prompts include explicit difficulty progression rules. Same scaffolded correction as current interactive teaching |
| Students don't click Practice CTA after Teach Me | Medium | Medium | UX: Primary button, warm copy, prominent placement. Track CTA click rate as success metric |

---

## 12. Open Questions

None — all technical decisions resolved above. Key decisions documented in each section with rationale.
