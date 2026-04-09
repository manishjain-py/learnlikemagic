# Tech Implementation Plan: Teach Me / Let's Practice Split

**Date:** 2026-04-06
**Status:** Draft (v2 — revised after review)
**PRD:** `docs/feature-development/teach-me-practice-split/prd.md`
**Author:** Tech Impl Plan Generator + Manish

---

## 1. Overview

Split the current Teach Me flow into two separate session modes: Teach Me (explanation cards only) and Let's Practice (question-heavy adaptive practice). Teach Me's `complete_card_phase()` is rewritten to end the session instead of transitioning to the interactive phase. A new `practice` mode is added to the orchestrator, reusing the existing `_apply_state_updates()` / `_handle_question_lifecycle()` machinery for scaffolded correction and adding a practice-specific completion check layered on top. Practice sessions auto-attach context from prior Teach Me sessions, support pause/resume, and contribute to coverage alongside Teach Me.

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
    ├─ teach_me       → process_turn() main path (card phase only now)
    ├─ clarify_doubts → _process_clarify_turn()    [UNCHANGED]
    ├─ exam           → _process_exam_turn()       [UNCHANGED]
    └─ practice       → _process_practice_turn()   [NEW — reuses _apply_state_updates + _handle_question_lifecycle]
```

### Updated Teach Me completion

```
BEFORE: Cards → complete_card_phase("clear") → v2 plan + bridge turn → interactive phase → session ends when current_step > total_steps
AFTER:  Cards → complete_card_phase("clear") → summary + CTA → session ends when card_phase.completed == True
```

### Canonical "complete" definition

The new invariant: **A Teach Me session is complete iff `card_phase.completed == True`** (for card-based sessions). This rule must be propagated to all places that classify session completion:

1. `SessionState.is_complete` property (Python)
2. `SessionRepository.list_by_guideline()` inline logic (Python)
3. `ChatSession.tsx` replay hydration (TypeScript)

**Decision:** Centralize completion logic in `SessionState.is_complete`. The repository should call it via the deserialized state model instead of re-implementing the check from raw JSON. The frontend should rely on a new `is_complete` field in the session replay API response (computed server-side) rather than re-implementing the check client-side.

### Canonical coverage denominator

The existing report card uses the latest session's `mastery_estimates` keys as the coverage denominator. This breaks when a practice plan (which is a struggle-weighted subset) becomes the latest session — the denominator shrinks and combined coverage appears inflated.

**Decision:** The denominator must come from the **teaching guideline's full concept list**, not from any individual session's plan. Add a helper that extracts canonical concepts from the guideline and use it as the denominator everywhere coverage is computed.

---

## 3. Database Changes

### Modified tables

| Table | Change | Details |
|-------|--------|---------|
| `sessions` | Extend `mode` values | Add `'practice'` as valid value in Python `SessionMode` literal. The column is VARCHAR, no schema change |
| `sessions` (index) | Rebuild partial unique index | Change `idx_sessions_one_paused_per_user_guideline` from `(user_id, guideline_id) WHERE is_paused = TRUE` to `(user_id, guideline_id, mode) WHERE is_paused = TRUE` — otherwise a paused Teach Me and paused Practice for the same topic collide on the unique constraint |

### Migration plan

Add a new migration function `_apply_practice_mode_support()` in `db.py`:

```python
def _apply_practice_mode_support(db_manager):
    """Rebuild the paused-session unique index to include mode."""
    with db_manager.engine.connect() as conn:
        conn.execute(text(
            "DROP INDEX IF EXISTS idx_sessions_one_paused_per_user_guideline"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_one_paused_per_user_guideline "
            "ON sessions(user_id, guideline_id, mode) WHERE is_paused = TRUE"
        ))
        conn.commit()
```

Register it in the migration runner. Idempotent: DROP IF EXISTS + CREATE IF NOT EXISTS.

**Decision:** This is the only DB change. Practice sessions share the `sessions` table — no new tables, no column additions. Only the partial unique index needs updating so that paused Teach Me and paused Practice sessions for the same topic don't conflict.

---

## 4. Backend Changes

### 4.1 Session State Model

**File:** `tutor/models/session_state.py`

#### Mode + practice fields

```python
SessionMode = Literal["teach_me", "clarify_doubts", "exam", "practice"]
```

Add to `SessionState`:

```python
# Practice mode state
practice_source: Optional[Literal["teach_me", "cold"]] = Field(
    default=None, description="How this practice session was initiated"
)
source_session_id: Optional[str] = Field(
    default=None, description="Teach Me session ID that provided context (if any)"
)
practice_questions_answered: int = Field(
    default=0, description="Total questions answered in this practice session"
)
practice_concept_question_counts: dict[str, int] = Field(
    default_factory=dict,
    description="Questions answered per concept (for 'at least 2 per concept' rule)"
)
practice_mastery_achieved: bool = Field(
    default=False, description="Whether practice mastery threshold was met"
)
```

#### `is_complete` property (single source of truth)

```python
@property
def is_complete(self) -> bool:
    if self.mode == "clarify_doubts":
        return self.clarify_complete
    if self.mode == "exam":
        return self.exam_finished
    if self.mode == "practice":
        return self.practice_mastery_achieved
    # teach_me
    if not self.topic:
        return False
    if self.is_refresher:
        return self.card_phase is not None and self.card_phase.completed
    # Card-based Teach Me (the only path going forward): complete when card phase is done
    if self.card_phase is not None:
        return self.card_phase.completed
    # v1 fallback (non-card sessions, out of scope but preserved for legacy data)
    return self.current_step > self.topic.study_plan.total_steps
```

**Decision:** Exam and practice also route through this property, replacing ad-hoc checks in downstream code. `SessionRepository.list_by_guideline()` will call this via the deserialized state model.

#### `create_session()` — seed mastery for practice

Currently mastery is only seeded for `teach_me`. Update so practice also gets all concepts seeded at 0.0:

```python
def create_session(
    topic: Topic,
    student_context: Optional[StudentContext] = None,
    mode: SessionMode = "teach_me",
) -> SessionState:
    concepts = topic.study_plan.get_concepts()
    # Seed mastery for modes that use per-concept mastery tracking
    if mode in ("teach_me", "practice"):
        mastery_estimates = {concept: 0.0 for concept in concepts}
    else:
        mastery_estimates = {}
    return SessionState(
        topic=topic,
        student_context=student_context or StudentContext(),
        mastery_estimates=mastery_estimates,
        mode=mode,
    )
```

This ensures untouched concepts are visible to the mastery threshold check (otherwise practice could "complete" by mastering a narrow slice of the topic).

---

### 4.2 Session Repository

**File:** `shared/repositories/session_repository.py`

#### `list_by_guideline()` — centralize completion via `SessionState.is_complete`

Replace the inline completion logic (lines ~214-226) with a single call to the model:

```python
def list_by_guideline(
    self, user_id: str, guideline_id: str,
    mode: Optional[str] = None, finished_only: bool = False,
) -> list[dict]:
    from tutor.models.session_state import SessionState
    
    query = (
        self.db.query(SessionModel)
        .filter(SessionModel.user_id == user_id, SessionModel.guideline_id == guideline_id)
    )
    if mode:
        query = query.filter(SessionModel.mode == mode)
    rows = query.order_by(SessionModel.created_at.desc()).all()

    results = []
    for row in rows:
        try:
            session_state = SessionState.model_validate_json(row.state_json)
        except Exception:
            continue  # Skip malformed sessions
        
        is_complete = session_state.is_complete  # Single source of truth
        
        if finished_only and not is_complete:
            continue
        
        # Compute exam score / answered
        exam_questions = session_state.exam_questions if session_state.mode == "exam" else []
        exam_score = (
            round(sum(q.score for q in exam_questions), 1)
            if exam_questions else None
        )
        exam_answered = sum(1 for q in exam_questions if q.student_answer)
        
        # Coverage for teach_me AND practice (but require min 3 questions for practice — FR-30)
        coverage = None
        if session_state.mode in ("teach_me", "practice"):
            if session_state.mode == "practice" and session_state.practice_questions_answered < 3:
                coverage = None  # Too little data to show
            else:
                coverage = self._compute_coverage_from_guideline(
                    session_state, guideline_id
                )
        
        results.append({
            "session_id": row.id,
            "mode": session_state.mode,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "is_complete": is_complete,
            "exam_finished": session_state.exam_finished,
            "exam_score": exam_score if session_state.mode == "exam" else None,
            "exam_total": len(exam_questions) if session_state.mode == "exam" else None,
            "exam_answered": exam_answered if session_state.mode == "exam" else None,
            "coverage": coverage,
            "practice_questions_answered": (
                session_state.practice_questions_answered
                if session_state.mode == "practice" else None
            ),
        })
    return results
```

#### New method: `find_most_recent_completed_teach_me()`

```python
def find_most_recent_completed_teach_me(
    self, user_id: str, guideline_id: str
) -> Optional[SessionState]:
    """Find the most recent completed Teach Me session for a user+topic (for practice context auto-attach)."""
    from tutor.models.session_state import SessionState
    
    rows = (
        self.db.query(SessionModel)
        .filter(
            SessionModel.user_id == user_id,
            SessionModel.guideline_id == guideline_id,
            SessionModel.mode == "teach_me",
        )
        .order_by(SessionModel.created_at.desc())
        .all()
    )
    for row in rows:
        try:
            state = SessionState.model_validate_json(row.state_json)
            if state.is_complete:
                return state
        except Exception:
            continue
    return None
```

**Decision:** The lookup is O(sessions_per_topic) in Python after fetching all rows, but the existing `idx_session_user_guideline` keeps the DB query fast. We do deserialization in Python instead of adding a JSON-path SQL filter because the latter is brittle across Postgres versions.

#### New helper: `_compute_coverage_from_guideline()`

```python
def _compute_coverage_from_guideline(
    self, session_state: SessionState, guideline_id: str
) -> float:
    """Compute coverage using the guideline's canonical concept list as the denominator."""
    all_concepts = self._get_canonical_concepts(guideline_id)
    if not all_concepts:
        return 0.0
    covered = session_state.concepts_covered_set & set(all_concepts)
    return round(len(covered) / len(all_concepts) * 100, 1)

def _get_canonical_concepts(self, guideline_id: str) -> list[str]:
    """Get the canonical concept list for a topic (from the teaching guideline's most recent full study plan)."""
    # Use the most recent teach_me session's plan as the canonical concept set
    # (teach_me plans cover the full topic, practice plans are subsets)
    from shared.models.entities import Session as SessionModel
    teach_me_row = (
        self.db.query(SessionModel)
        .filter(
            SessionModel.guideline_id == guideline_id,
            SessionModel.mode == "teach_me",
        )
        .order_by(SessionModel.created_at.desc())
        .first()
    )
    if teach_me_row:
        try:
            state = SessionState.model_validate_json(teach_me_row.state_json)
            return list(state.mastery_estimates.keys())
        except Exception:
            pass
    return []
```

**Decision:** Canonical concepts come from the latest **teach_me** session's plan (never a practice session, since practice plans are subsets). This prevents denominator shrinkage. If no teach_me session exists yet, coverage is 0 (student has only done practice cold-start, no canonical baseline).

---

### 4.3 Session Service

**File:** `tutor/services/session_service.py`

#### Persistence: allow `is_paused` for practice mode

Two locations need updating:

**`_persist_session()` (line ~528):**
```python
db_record.is_paused = session.is_paused if session.mode in ("teach_me", "practice") else False
```

**`_persist_session_state()` (line ~552):**
```python
is_paused=session.is_paused if session.mode in ("teach_me", "practice") else False,
```

#### `pause_session()` — allow practice

The existing method just calls `_persist_session_state` with `is_paused=True`. No logic change needed, but add a mode check:

```python
def pause_session(self, session_id: str) -> dict:
    db_session = self.session_repo.get_by_id(session_id)
    if not db_session:
        raise SessionNotFoundException(session_id)
    expected_version = db_session.state_version or 1
    session = SessionState.model_validate_json(db_session.state_json)
    
    if session.mode not in ("teach_me", "practice"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Only Teach Me and Practice sessions can be paused")
    
    session.is_paused = True
    self._persist_session_state(session_id, session, expected_version)
    
    # Mode-specific return data
    if session.mode == "teach_me":
        return {
            "coverage": session.coverage_percentage,
            "concepts_covered": list(session.concepts_covered_set),
            "message": f"You've covered {session.coverage_percentage:.0f}% so far. You can pick up where you left off anytime.",
        }
    else:  # practice
        return {
            "questions_answered": session.practice_questions_answered,
            "message": f"Paused after {session.practice_questions_answered} questions. You can pick up where you left off anytime.",
        }
```

#### Practice session creation (in `create_new_session`)

Add `practice` branch:

```python
if mode == "practice":
    source_session_id = getattr(request, 'source_session_id', None)
    context_data = self._resolve_practice_context(
        user_id, request.goal.guideline_id, source_session_id
    )
    
    practice_plan = self._generate_practice_plan(
        guideline, student_context, context_data
    )
    topic = convert_guideline_to_topic(guideline, study_plan_record, is_refresher=False)
    topic.study_plan = practice_plan  # Replace with practice-specific plan
    
    session = create_session(topic=topic, student_context=student_context, mode="practice")
    session_id = str(uuid4())
    session.session_id = session_id
    session.practice_source = context_data["source"]
    session.source_session_id = context_data.get("source_session_id")
    session.precomputed_explanation_summary = context_data.get("explanation_summary")
    
    # Generate dynamic practice welcome
    welcome, audio_text = asyncio.run(
        self.orchestrator.generate_practice_welcome(session)
    )
    
    first_turn = {
        "message": welcome,
        "audio_text": audio_text,
        "hints": [],
        "step_idx": session.current_step,
        "session_phase": "interactive",  # Practice skips card phase
    }
```

#### New: `_resolve_practice_context()`

```python
def _resolve_practice_context(
    self, user_id: Optional[str], guideline_id: str,
    source_session_id: Optional[str] = None,
) -> dict:
    """Resolve context for a practice session (FR-19, FR-21, FR-22).
    
    Priority:
    1. Explicit source_session_id (from Teach Me CTA handoff)
    2. Auto-detect most recent completed Teach Me session
    3. Cold start (no context)
    """
    source_state = None
    
    if source_session_id:
        # Explicit handoff from Teach Me CTA
        db_row = self.session_repo.get_by_id(source_session_id)
        if db_row:
            source_state = SessionState.model_validate_json(db_row.state_json)
    elif user_id:
        # Auto-attach from most recent completed Teach Me (FR-21)
        source_state = self.session_repo.find_most_recent_completed_teach_me(
            user_id, guideline_id
        )
    
    if source_state is None or source_state.card_phase is None:
        # Truly cold start (FR-22)
        return {
            "source": "cold",
            "source_session_id": None,
            "explanation_summary": None,
            "variants_shown": [],
            "remedial_cards": {},
            "check_in_struggles": [],
        }
    
    # Context attached — read from source session's CardPhaseState (FR-19)
    # All data already lives in source_state.card_phase — no new storage needed
    return {
        "source": "teach_me",
        "source_session_id": source_state.session_id,
        "explanation_summary": source_state.precomputed_explanation_summary,
        "variants_shown": list(source_state.card_phase.variants_shown),
        "remedial_cards": {
            idx: [rc.model_dump() for rc in cards]
            for idx, cards in source_state.card_phase.remedial_cards.items()
        },
        "check_in_struggles": [
            evt.model_dump() for evt in source_state.card_phase.check_in_struggles
        ],
    }
```

**Note on FR-19:** All four required data points (variant, summary, check-in struggles, remedial cards) already live in `CardPhaseState` — no new storage is needed. We read them directly from the source session.

#### New: `_generate_practice_plan()`

```python
def _generate_practice_plan(
    self,
    guideline: TeachingGuideline,
    student_context: "StudentContext",
    context_data: dict,
) -> StudyPlan:
    """Generate a practice-focused study plan via StudyPlanGeneratorService."""
    from study_plans.services.generator_service import StudyPlanGeneratorService
    from shared.utils.prompt_loader import PromptLoader
    from tutor.services.topic_adapter import convert_session_plan_to_study_plan
    
    llm_config_service = self._get_llm_config_service()
    llm_service = llm_config_service.get_llm_service("study_plan_generator")
    generator = StudyPlanGeneratorService(llm_service, PromptLoader())
    
    is_cold_start = (context_data["source"] == "cold")
    result = generator.generate_practice_plan(
        guideline=guideline,
        student_context=student_context,
        check_in_struggles=context_data.get("check_in_struggles"),
        is_cold_start=is_cold_start,
    )
    
    return convert_session_plan_to_study_plan(result["plan"])
```

#### `complete_card_phase()` rewrite

```python
def complete_card_phase(self, session_id: str, action: str, check_in_events=None) -> dict:
    db_session = self.session_repo.get_by_id(session_id)
    if not db_session:
        raise SessionNotFoundException(session_id)
    expected_version = db_session.state_version or 1
    session = SessionState.model_validate_json(db_session.state_json)
    
    if not session.is_in_card_phase():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Session is not in card phase")
    
    if session.is_refresher:
        # Refresher handling unchanged
        session.complete_card_phase()
        session.is_paused = False
        self._persist_session_state(session_id, session, expected_version)
        return {
            "action": "session_complete",
            "message": "You've refreshed the basics and are ready to dive into the chapter!",
            "audio_text": "You've refreshed the basics and are ready to dive into the chapter!",
            "is_complete": True,
        }
    
    # Store check-in struggle events from frontend (valuable regardless of action)
    if check_in_events and session.card_phase:
        from tutor.models.session_state import CheckInStruggleEvent
        for evt in check_in_events:
            session.card_phase.check_in_struggles.append(
                CheckInStruggleEvent(
                    card_idx=evt.card_idx,
                    card_title=evt.card_title or f"Check-in at card {evt.card_idx}",
                    activity_type=evt.activity_type,
                    wrong_count=evt.wrong_count,
                    hints_shown=evt.hints_shown,
                    confused_pairs=evt.confused_pairs,
                    auto_revealed=evt.auto_revealed,
                )
            )
    
    if action == "clear":
        return self._finalize_teach_me_session(session, session_id, expected_version)
    
    elif action == "explain_differently":
        # Find next unseen variant
        unseen = [
            k for k in session.card_phase.available_variant_keys
            if k not in session.card_phase.variants_shown
        ]
        if unseen:
            return self._switch_variant_internal(session, session_id, unseen[0], expected_version)
        # All variants exhausted — end session with gentle message (no bridge turn)
        return self._finalize_teach_me_session(
            session, session_id, expected_version,
            custom_message="We've looked at this from a few angles. Let's practice to see what stuck!"
        )
    
    from fastapi import HTTPException
    raise HTTPException(status_code=400, detail=f"Unknown card action: {action}")

def _finalize_teach_me_session(
    self, session: SessionState, session_id: str, expected_version: int,
    custom_message: Optional[str] = None,
) -> dict:
    """End a Teach Me session after card phase. No bridge turn, no v2 plan."""
    session.complete_card_phase()
    
    # Build explanation summary (for future practice context)
    precomputed_summary = self._build_precomputed_summary(session)
    session.precomputed_explanation_summary = precomputed_summary
    
    # Add card concepts to coverage set
    if session.card_phase:
        explanation_repo = ExplanationRepository(self.db)
        for vk in session.card_phase.variants_shown:
            exp = explanation_repo.get_variant(session.card_phase.guideline_id, vk)
            if exp and exp.cards_json:
                for card in exp.cards_json:
                    concept = card.get("concept") or card.get("title")
                    if concept:
                        session.concepts_covered_set.add(concept)
                        session.card_covered_concepts.add(concept)
    
    # Clear paused state (session is now complete)
    session.is_paused = False
    
    self._persist_session_state(session_id, session, expected_version)
    
    message = custom_message or "Nice work! You've covered the key ideas. Ready to practice?"
    
    return {
        "action": "teach_me_complete",
        "message": message,
        "audio_text": message,
        "is_complete": True,
        "coverage": session.coverage_percentage,
        "concepts_covered": list(session.concepts_covered_set),
        "guideline_id": session.card_phase.guideline_id if session.card_phase else None,
    }
```

**Decision:** `_switch_variant_internal()` is unchanged. Only the `"clear"` path and the variants-exhausted path are rewritten. The `generate_bridge_turn()` method in the orchestrator becomes dead code — we can delete it in a follow-up cleanup PR.

#### `process_step()` — support practice mode

The existing `process_step()` already routes through the orchestrator which handles mode routing. The only change is in `is_complete` logic for the response (which now uses the centralized `session.is_complete` property):

```python
next_turn = {
    "message": turn_result.response,
    "audio_text": turn_result.audio_text,
    "hints": [],
    "step_idx": session.current_step,
    "mastery_score": session.overall_mastery,
    "is_complete": session.is_complete,  # Single source of truth (replaces mode-specific checks)
}
```

---

### 4.4 Orchestrator

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

#### `_process_practice_turn()` — REUSES existing state update machinery

**Critical correction from v1 of the plan:** Practice must reuse `_apply_state_updates()` and `_handle_question_lifecycle()` to preserve scaffolded correction (FR-13), misconception tracking (FR-14), and question lifecycle state. It is NOT modeled after `_process_clarify_turn()`.

```python
async def _process_practice_turn(
    self, session: SessionState, context: AgentContext, turn_id: str, start_time: float
) -> TurnResult:
    """Process a Practice turn.
    
    Reuses _apply_state_updates() and _handle_question_lifecycle() from teach_me
    processing for scaffolded correction, misconception tracking, and question lifecycle.
    Adds practice-specific question counting and mastery completion check on top.
    """
    # Count this student turn as an answered question (FR-27 counter logic fix)
    # Increment BEFORE the LLM call, so even if the tutor ends the session this turn,
    # the final answer is counted.
    session.practice_questions_answered += 1
    
    # Track per-concept question count for the "at least 2 per concept" rule
    if session.last_question and session.last_question.concept:
        concept = session.last_question.concept
        session.practice_concept_question_counts[concept] = (
            session.practice_concept_question_counts.get(concept, 0) + 1
        )
    
    # Run master tutor (practice prompts selected via session.mode inside master_tutor)
    tutor_start = time.time()
    self.master_tutor.set_session(session)
    tutor_output: TutorTurnOutput = await self.master_tutor.execute(context)
    tutor_duration = int((time.time() - tutor_start) * 1000)
    
    self._log_agent_event(
        session_id=session.session_id,
        turn_id=turn_id,
        agent_name="master_tutor",
        event_type="completed",
        output=self._extract_output_dict(tutor_output),
        reasoning=tutor_output.reasoning,
        duration_ms=tutor_duration,
        metadata={"mode": "practice", "intent": tutor_output.intent},
    )
    
    # REUSE existing state update machinery for scaffolded correction, misconceptions,
    # question lifecycle, mastery updates, step advancement, coverage tracking
    self._apply_state_updates(session, tutor_output)
    
    # Practice-specific mastery completion check (LAYERED ON TOP of standard updates)
    self._check_practice_mastery(session, tutor_output)
    
    session.add_message(create_teacher_message(
        tutor_output.response, audio_text=tutor_output.audio_text
    ))
    
    duration_ms = int((time.time() - start_time) * 1000)
    self._log_agent_event(
        session_id=session.session_id,
        turn_id=turn_id,
        agent_name="orchestrator",
        event_type="turn_completed",
        duration_ms=duration_ms,
        metadata={
            "mode": "practice",
            "intent": tutor_output.intent,
            "questions_answered": session.practice_questions_answered,
            "mastery_achieved": session.practice_mastery_achieved,
        },
    )
    
    return TurnResult(
        response=tutor_output.response,
        audio_text=tutor_output.audio_text,
        intent=tutor_output.intent,
        specialists_called=["master_tutor"],
        state_changed=True,
        visual_explanation=await self._generate_pixi_code(tutor_output.visual_explanation)
            if tutor_output.visual_explanation else None,
        question_format=tutor_output.question_format.model_dump()
            if tutor_output.question_format else None,
    )
```

**Decision:** The counter is incremented at the TOP of the turn (before the LLM call). This counts student answers (one per inbound turn), not tutor question-asks. It also ensures the final answer is counted even if the tutor ends the session.

**Exception:** The welcome turn does NOT call `_process_practice_turn()` — it goes through `generate_practice_welcome()` at session creation. So the counter correctly tracks only subsequent answer turns.

#### `_check_practice_mastery()` — enforce FR-27 completion rules

```python
def _check_practice_mastery(self, session: SessionState, tutor_output: TutorTurnOutput) -> None:
    """Enforce FR-27: practice session completion criteria.
    
    Rules:
    - Minimum 5 questions answered
    - 70% mastery across ALL canonical concepts (not just touched ones)
    - At least 2 questions per key concept
    - Maximum ~20 questions (hard cap for attention-aware wrap-up)
    """
    MIN_QUESTIONS = 5
    MAX_QUESTIONS = 20
    MASTERY_THRESHOLD = 0.7
    MIN_QUESTIONS_PER_CONCEPT = 2
    
    if session.practice_mastery_achieved:
        return
    
    # Hard cap — force wrap up regardless of mastery state
    if session.practice_questions_answered >= MAX_QUESTIONS:
        session.practice_mastery_achieved = True
        logger.info(f"Practice session {session.session_id} hit max questions cap")
        return
    
    # Minimum gate
    if session.practice_questions_answered < MIN_QUESTIONS:
        return
    
    # All canonical concepts must be at/above threshold
    # (mastery_estimates is seeded with all concepts at 0.0 in create_session for practice)
    if not session.mastery_estimates:
        return
    
    all_mastered = all(
        score >= MASTERY_THRESHOLD
        for score in session.mastery_estimates.values()
    )
    if not all_mastered:
        return
    
    # Each concept must have had at least 2 questions
    all_covered = all(
        session.practice_concept_question_counts.get(concept, 0) >= MIN_QUESTIONS_PER_CONCEPT
        for concept in session.mastery_estimates.keys()
    )
    if not all_covered:
        return
    
    # If LLM also signaled completion, honor it
    if tutor_output.session_complete:
        session.practice_mastery_achieved = True
        logger.info(f"Practice session {session.session_id} reached mastery")
        return
    
    # All rules satisfied but LLM didn't signal — let it run one more turn
    # (the LLM will see high mastery in its prompt context and should wrap up naturally)
```

**Decision:** Mastery is checked against ALL canonical concepts (from seeded `mastery_estimates`), not just touched ones. Combined with the "min 2 questions per concept" rule, this prevents the "completed after mastering a narrow slice" failure mode from reviewer 2.

#### `generate_practice_welcome()` — dedicated path

```python
async def generate_practice_welcome(self, session: SessionState) -> tuple[str, Optional[str]]:
    """Generate a practice-specific welcome message.
    
    Uses master_tutor with practice prompts (selected via session.mode).
    The existing master_tutor.generate_welcome() is explain-oriented;
    this method uses a different call path that loads practice prompts.
    """
    self.master_tutor.set_session(session)
    output = await self.master_tutor.generate_practice_welcome(session)
    return output.response, output.audio_text
```

**Decision:** Add a new method `generate_practice_welcome()` on `MasterTutorAgent` that loads `PRACTICE_WELCOME_PROMPT` (a new prompt in `practice_prompts.py`) instead of the explain-oriented welcome prompt. This keeps teach_me's welcome path completely unchanged.

---

### 4.5 Master Tutor Agent

**File:** `tutor/agents/master_tutor.py`

#### Practice prompt selection

Add practice mode handling in the prompt-building path:

```python
def _build_system_prompt(self, session: SessionState) -> str:
    if session.mode == "clarify_doubts":
        return CLARIFY_DOUBTS_SYSTEM_PROMPT.format(...)
    elif session.mode == "exam":
        return EXAM_SYSTEM_PROMPT.format(...)
    elif session.mode == "practice":
        return PRACTICE_SYSTEM_PROMPT.format(
            grade=session.student_context.grade,
            topic_name=session.topic.topic_name if session.topic else "",
            subject=session.topic.subject if session.topic else "",
            curriculum_scope=...,
            concepts_list=...,
            explanation_context_section=self._build_explanation_context(session),
            card_reference_rule=self._build_card_reference_rule(session),
            difficulty_start="medium" if session.practice_source == "cold" else "easy/medium",
            min_questions=5,
            max_questions=20,
            questions_answered=session.practice_questions_answered,
            personalization_block=...,
            response_language_instruction=...,
            audio_language_instruction=...,
        )
    # teach_me: existing path unchanged
    return MASTER_TUTOR_SYSTEM_PROMPT.format(...)
```

#### New method: `generate_practice_welcome()`

```python
async def generate_practice_welcome(self, session: SessionState) -> TutorTurnOutput:
    """Generate a practice-specific welcome message using PRACTICE_WELCOME_PROMPT."""
    system_prompt = self._build_system_prompt(session)  # Returns practice system prompt
    welcome_prompt = PRACTICE_WELCOME_PROMPT.format(
        topic_name=session.topic.topic_name if session.topic else "",
        has_teach_me_context=(session.practice_source == "teach_me"),
        explanation_summary=session.precomputed_explanation_summary or "",
    )
    # Call LLM with structured output
    return await self._execute_with_prompt(system_prompt, welcome_prompt)
```

**Decision:** The practice welcome uses its own prompt but reuses the same structured output (`TutorTurnOutput`) so the orchestrator path doesn't diverge.

---

### 4.6 Practice Prompts

**New file:** `tutor/prompts/practice_prompts.py`

```python
"""
Practice Mode Prompts
System, turn, and welcome prompts for the Let's Practice (question-heavy) mode.
"""
from tutor.prompts.templates import PromptTemplate


PRACTICE_SYSTEM_PROMPT = PromptTemplate(
    """You are a friendly practice coach helping a Grade {grade} student reinforce their understanding of {topic_name}.

## Your Role
You are in PRACTICE mode. Your primary job is ASKING QUESTIONS (~80% of turns).
You only explain when the student clearly doesn't understand (not on a single wrong answer).

## Subject & Curriculum Scope
Subject: {subject}
Curriculum scope: {curriculum_scope}

## Key Concepts to Practice
{concepts_list}

{explanation_context_section}

## Rules
1. START with a question. Don't explain first — assess what the student knows.
2. Scaffolded correction: 1st wrong → guiding question, 2nd wrong → targeted hint, 3rd+ → explain directly and warmly.
3. After 3+ errors revealing the same gap, PAUSE questioning. Explain that concept. Then resume questions.
4. Question difficulty progresses: start at {difficulty_start}, advance as student demonstrates understanding.
5. Use structured question formats (single_select, fill_in_the_blank, multi_select) for most questions. Open-ended for reasoning checks.
6. Vary question types — never ask the same format twice in a row.
7. {card_reference_rule}
8. Keep it casual and encouraging — this is practice, not an exam. No scores shown. No question counters.
9. If the student struggles on everything (5+ consecutive wrong), gently suggest: "This topic seems new — want to try Teach Me first?"

## Mastery Completion Rules
- Minimum {min_questions} questions before you can end.
- Target: 70% mastery across all concepts, with at least 2 questions per key concept.
- Maximum ~{max_questions} questions — wrap up after that even if mastery is uneven.
- Set session_complete=true when mastery criteria are met.

## Response/Audio Language
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


PRACTICE_WELCOME_PROMPT = PromptTemplate(
    """Generate a warm, brief welcome message (1-2 sentences) to start a practice session for {topic_name}.

{welcome_context_block}

Then ASK the first question. Don't explain anything upfront — the student is here to practice, not to be taught.

Start at medium difficulty. Use a structured question format (single_select or fill_in_the_blank is best for openers).

Be warm and casual: "Let's see what you know!" / "Ready to practice?" — nothing formal.""",
    name="practice_welcome",
)
```

Template variable builders (in `master_tutor.py`):

- `explanation_context_section`: "## Previous Explanation Context\n{explanation_summary}" when `practice_source == "teach_me"`, empty string otherwise
- `card_reference_rule`: "Reference card analogies and examples as shared vocabulary (e.g., 'Remember the pizza slices?')" when post-Teach-Me, "Do NOT reference any cards or prior explanations — the student has not seen them" when cold
- `welcome_context_block`: Summary of what was explained when post-Teach-Me, empty otherwise
- `mastery_summary`: Formatted string of `{concept: score}` pairs
- `struggle_summary`: Recent wrong-attempt patterns for context

---

### 4.7 Study Plan Generator

**File:** `study_plans/services/generator_service.py`

Add new method:

```python
def generate_practice_plan(
    self,
    guideline: TeachingGuideline,
    student_context: Optional["StudentContext"] = None,
    check_in_struggles: Optional[list[dict]] = None,
    is_cold_start: bool = False,
) -> dict:
    """Generate a practice-focused study plan (question-heavy, no explain steps).
    
    Plan structure: 5-8 steps, all question types (check_understanding, guided_practice,
    independent_practice). When check_in_struggles are provided, early steps target
    concepts with the highest struggle counts.
    """
```

Uses a new prompt `PRACTICE_PLAN_PROMPT` (in study_plans prompts dir). Returns a `SessionPlan` with `SessionPlanStep` entries of types `check_understanding`, `guided_practice`, `independent_practice` only.

**Decision:** Reuses existing `SessionPlan` / `SessionPlanStep` models. Just a new method that calls the LLM with different instructions. No new data models needed.

---

### 4.8 API Layer

**File:** `shared/models/schemas.py`

Update `CreateSessionRequest`:

```python
class CreateSessionRequest(BaseModel):
    student: Student
    goal: Goal
    mode: Literal["teach_me", "clarify_doubts", "exam", "practice"] = "teach_me"
    source_session_id: Optional[str] = None  # For Teach Me → Practice handoff
```

Update `ReportCardTopic` to include `last_practiced`:

```python
class ReportCardTopic(BaseModel):
    ...
    last_studied: Optional[str] = None
    last_practiced: Optional[str] = None  # NEW
```

Update `GuidelineSessionEntry`:

```python
class GuidelineSessionEntry(BaseModel):
    ...
    practice_questions_answered: Optional[int] = None  # NEW — for practice sessions
```

Update `TopicProgressEntry`:

```python
class TopicProgressEntry(BaseModel):
    coverage: float
    session_count: int
    status: str
    last_practiced: Optional[str] = None  # NEW
```

**File:** `tutor/api/sessions.py`

Update `/sessions/resumable` endpoint to search for both teach_me AND practice paused sessions:

```python
@router.get("/resumable", response_model=ResumableSessionResponse)
def get_resumable_session(
    guideline_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Find a paused Teach Me or Practice session for the given topic."""
    from shared.models.entities import Session as SessionModel

    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == current_user.id,
            SessionModel.guideline_id == guideline_id,
            SessionModel.is_paused == True,
            SessionModel.mode.in_(["teach_me", "practice"]),  # Both modes
        )
        .order_by(SessionModel.updated_at.desc())
        .first()
    )
    
    if not session:
        raise HTTPException(status_code=404, detail="No resumable session found")
    
    session_state = SessionState.model_validate_json(session.state_json)
    total_steps = session_state.topic.study_plan.total_steps if session_state.topic else 0
    
    return ResumableSessionResponse(
        session_id=session.id,
        mode=session_state.mode,  # Include mode so frontend can route correctly
        coverage=session_state.coverage_percentage,
        current_step=session_state.current_step,
        total_steps=total_steps,
        concepts_covered=list(session_state.concepts_covered_set),
    )
```

Add `mode` field to `ResumableSessionResponse` in schemas.

---

### 4.9 Report Card Service

**File:** `tutor/services/report_card_service.py`

#### `_group_sessions()` — include practice, with 3-question gate

Replace the `if mode == "teach_me":` check (line ~239):

```python
# Only teach_me and practice contribute to coverage
contributes_to_coverage = False
if mode == "teach_me":
    contributes_to_coverage = True
elif mode == "practice":
    # FR-30: Practice contributes to coverage only if min 3 questions answered
    questions_answered = state.get("practice_questions_answered", 0)
    contributes_to_coverage = questions_answered >= 3

if contributes_to_coverage:
    concepts_covered = state.get("concepts_covered_set", [])
    if isinstance(concepts_covered, list):
        existing_covered.update(concepts_covered)
    existing_last_studied = session_date
    
    # For plan_concepts denominator, ONLY use teach_me sessions (not practice)
    # to avoid denominator shrinkage from struggle-weighted practice plans
    if mode == "teach_me":
        mastery_estimates = state.get("mastery_estimates", {})
        if isinstance(mastery_estimates, dict) and mastery_estimates:
            existing_plan = set(mastery_estimates.keys())

# Track last_practiced separately (FR-30)
if mode == "practice":
    questions_answered = state.get("practice_questions_answered", 0)
    if questions_answered >= 3:
        existing_last_practiced = existing.get("last_practiced")
        if not existing_last_practiced or session_date > existing_last_practiced:
            existing["last_practiced"] = session_date
```

Store `last_practiced` in the grouped dict output.

#### `_build_report()` — include `last_practiced`

```python
topics_data.append({
    "topic": topic_info["topic_name"],
    "topic_key": topic_key,
    "guideline_id": topic_info.get("guideline_id"),
    "coverage": coverage,
    "latest_exam_score": topic_info.get("latest_exam_score"),
    "latest_exam_total": topic_info.get("latest_exam_total"),
    "last_studied": topic_info.get("last_studied"),
    "last_practiced": topic_info.get("last_practiced"),  # NEW
})
```

#### `get_topic_progress()` — include practice + last_practiced

```python
if mode not in ("teach_me", "practice"):
    continue

# For practice, require min 3 questions
if mode == "practice":
    questions_answered = state.get("practice_questions_answered", 0)
    if questions_answered < 3:
        continue
```

Add `last_practiced` to the output dict.

**Decision:** The coverage NUMERATOR includes practice (concepts covered). The coverage DENOMINATOR stays teach_me-only (canonical concept list from the full topic plan). This matches reviewer 2's concern — practice plans are struggle-weighted subsets and should never shrink the denominator.

---

## 5. Frontend Changes

### New route

**File:** `llm-frontend/src/App.tsx`

```tsx
<Route path="/learn/:subject/:chapter/:topic/practice/:sessionId" element={
  <ChatSession key="practice" />
} />
```

### `api.ts` type updates

```typescript
export interface CreateSessionRequest {
  student: Student;
  goal: Goal;
  mode?: 'teach_me' | 'clarify_doubts' | 'exam' | 'practice';
  source_session_id?: string;
}

export interface GuidelineSessionEntry {
  session_id: string;
  mode: string;
  created_at: string | null;
  is_complete: boolean;
  exam_finished: boolean;
  exam_score?: number | null;
  exam_total?: number | null;
  exam_answered?: number | null;
  coverage?: number | null;
  practice_questions_answered?: number | null;  // NEW
}

export interface ResumableSessionResponse {
  session_id: string;
  mode: 'teach_me' | 'practice';  // NEW
  coverage: number;
  current_step: number;
  total_steps: number;
  concepts_covered: string[];
}

export interface ReportCardTopic {
  ...
  last_studied?: string | null;
  last_practiced?: string | null;  // NEW
}
```

### `ModeSelection.tsx` changes

**Key fix:** Resume detection must include practice, and the practice indicator must read `last_practiced` directly from the backend (not filter frontend-side).

```tsx
interface ModeSelectionProps {
  topic: TopicInfo;
  onSelectMode: (mode: 'teach_me' | 'clarify_doubts' | 'exam' | 'practice') => void;
  onResume: (sessionId: string, mode: string) => void;
  ...
}

const MODE_LOADING_MESSAGES: Record<string, string> = {
  teach_me: 'Creating your personalized lesson plan...',
  clarify_doubts: 'Getting ready for your questions...',
  exam: 'Preparing your question paper...',
  practice: 'Setting up your practice session...',  // NEW
};
```

Resume detection — include practice:

```tsx
const incompletePractice = sessions.find(
  s => s.mode === 'practice' && !s.is_complete && (s.practice_questions_answered ?? 0) > 0
);
const incompleteTeachMe = sessions.find(
  s => s.mode === 'teach_me' && !s.is_complete
);
```

Add Practice mode card (4th option):

```tsx
<button 
  className="selection-card" 
  onClick={() => onSelectMode('practice')}
  disabled={!!creatingMode}
>
  <strong>Let's Practice</strong>
  <span>Practice what you learned</span>
  {lastPracticedDate && (
    <span className="practice-indicator">
      Practiced {formatRelativeDate(lastPracticedDate)}
    </span>
  )}
</button>
```

Update existing mode descriptions (per PRD Section 6):

- Teach Me: "Learn this topic step by step"
- Let's Practice: "Practice what you learned"
- Clarify Doubts: "Ask me anything about this topic"
- Exam: "Formal test with a score"

Read `lastPracticedDate` from the topic progress API (which now includes `last_practiced` with backend-enforced 3-question gate):

```tsx
const lastPracticedDate = topicProgress?.[topic.guideline_id]?.last_practiced;
```

Add "Resume Practice" card when `incompletePractice` exists (mirroring existing "Continue Lesson" styling).

### `ChatSession.tsx` changes

#### Replay hydration — use backend `is_complete`

Replace the inline completion check (line ~500) with the backend-provided value:

```tsx
// Before:
const completed = state.clarify_complete
  || state.exam_finished
  || (state.topic && state.current_step > (state.topic?.study_plan?.steps?.length ?? Infinity));

// After: Use the is_complete field from the session replay response
// The backend now returns is_complete (computed via SessionState.is_complete property)
const completed = state.is_complete ?? false;
```

This requires the `/sessions/{id}/replay` or `/sessions/{id}` GET endpoint to include `is_complete` in its response. Update the endpoint to call `session_state.is_complete` and include it.

#### Card phase completion — summary + Practice CTA

When `cardAction()` returns `action: "teach_me_complete"`:

```tsx
const handleCardPhaseClear = async () => {
  try {
    const result = await cardAction(sessionId, 'clear', checkInEvents);
    
    if (result.action === 'teach_me_complete') {
      // NEW: Show summary + CTA instead of transitioning to interactive phase
      setTeachMeComplete(true);
      setCoverageAtCompletion(result.coverage);
      setConceptsCovered(result.concepts_covered || []);
      setCompletionMessage(result.message);
      setGuidelineIdForPractice(result.guideline_id);
      return;
    }
    
    // Legacy paths (refresher etc.) — unchanged
    ...
  } catch (err) {
    showError(err);
  }
};

const handleStartPractice = async () => {
  // Create practice session with source_session_id for context handoff
  setCreatingPractice(true);
  try {
    const response = await createSession({
      student: student,
      goal: goal,
      mode: 'practice',
      source_session_id: sessionId,  // FR-10: explicit handoff
    });
    // Navigate to practice route
    navigate(
      `/learn/${subject}/${chapter}/${topic}/practice/${response.session_id}`,
      { state: { firstTurn: response.first_turn, mode: 'practice' } }
    );
  } catch (err) {
    showError(err);
  } finally {
    setCreatingPractice(false);
  }
};

const handleDoneForNow = () => {
  navigate(`/learn/${subject}/${chapter}/${topic}`);
};
```

New UI section for Teach Me completion:

```tsx
{teachMeComplete && (
  <div className="teach-me-complete-screen">
    <h3>Nice work!</h3>
    <p>You've covered:</p>
    <ul>
      {conceptsCovered.map(c => <li key={c}>{c}</li>)}
    </ul>
    <p className="completion-message">{completionMessage}</p>
    
    <button 
      className="primary-cta large" 
      onClick={handleStartPractice}
      disabled={creatingPractice}
    >
      {creatingPractice ? 'Setting up...' : "Let's Practice — put it to work!"}
    </button>
    
    <button 
      className="secondary-action" 
      onClick={handleDoneForNow}
    >
      I'm done for now
    </button>
  </div>
)}
```

#### Practice session completion — summary + Exam nudge (FR-33, FR-35)

New state + UI for practice completion:

```tsx
const [practiceComplete, setPracticeComplete] = useState(false);
const [practiceSummary, setPracticeSummary] = useState<string | null>(null);

// In the step response handler:
if (sessionMode === 'practice' && response.next_turn.is_complete) {
  setPracticeComplete(true);
  setPracticeSummary(response.next_turn.message);  // Tutor's qualitative summary
}
```

UI:

```tsx
{practiceComplete && sessionMode === 'practice' && (
  <div className="practice-complete-screen">
    <h3>Great practice session!</h3>
    <p className="summary-text">{practiceSummary}</p>
    
    <button className="primary-cta" onClick={handleStartExam}>
      Make it official — take the exam
    </button>
    
    <button className="secondary-action" onClick={handleBackToTopic}>
      I'm done for now
    </button>
  </div>
)}
```

#### End Practice button (FR-16)

Add to the chat session header when `sessionMode === 'practice'`:

```tsx
{sessionMode === 'practice' && !practiceComplete && (
  <>
    <button className="header-button" onClick={handlePauseSession}>
      Pause
    </button>
    <button className="header-button end-button" onClick={handleEndPractice}>
      End Practice
    </button>
  </>
)}

const handleEndPractice = async () => {
  if (!confirm("End this practice session? You'll see your progress.")) return;
  // Call backend to mark practice complete early
  // Reuse the clarify_doubts pattern: POST /sessions/{id}/end-practice
  // OR just set local state + trigger summary — simpler
  setPracticeComplete(true);
  setPracticeSummary("Session ended. You answered " + questionsAnswered + " questions.");
};
```

**Decision:** Adding a new `/sessions/{id}/end-practice` endpoint mirrors the existing `/end-clarify` pattern. It marks `practice_mastery_achieved = True` server-side so the session is properly saved as complete.

**File:** `tutor/api/sessions.py`

```python
@router.post("/{session_id}/end-practice")
def end_practice_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    service = SessionService(db)
    return service.end_practice_session(session_id)
```

**File:** `tutor/services/session_service.py`

```python
def end_practice_session(self, session_id: str) -> dict:
    """End a practice session early (FR-16)."""
    db_session = self.session_repo.get_by_id(session_id)
    if not db_session:
        raise SessionNotFoundException(session_id)
    expected_version = db_session.state_version or 1
    session = SessionState.model_validate_json(db_session.state_json)
    
    if session.mode != "practice":
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Only practice sessions can be ended this way")
    
    session.practice_mastery_achieved = True  # Marks session complete
    session.is_paused = False
    self._persist_session_state(session_id, session, expected_version)
    
    return {
        "is_complete": True,
        "questions_answered": session.practice_questions_answered,
        "message": f"Session ended. You answered {session.practice_questions_answered} questions.",
    }
```

---

## 6. LLM Integration

### Practice prompts

Practice mode reuses the existing `MasterTutorAgent` with practice-specific system/turn/welcome prompts loaded from `tutor/prompts/practice_prompts.py`. Prompt selection happens in `master_tutor._build_system_prompt()` based on `session.mode`.

### Practice plan generation

Single LLM call at session creation time via `StudyPlanGeneratorService.generate_practice_plan()`. Uses the `study_plan_generator` LLM config. Structured output via `SessionPlan` schema.

### Practice welcome

Dynamic, generated via `master_tutor.generate_practice_welcome()` which uses `PRACTICE_WELCOME_PROMPT`. Latency target: <2s (same as current clarify_doubts welcome).

### Cost and latency

- Practice plan generation: ~3s (one-time per session, same as v2 plan today)
- Practice welcome: ~2s (same as clarify_doubts welcome)
- Per-turn processing: ~2-4s (same as teach_me, reuses same agent and state update machinery)

No net cost increase — work just moves from Teach Me to Practice.

---

## 7. Configuration & Environment

No new environment variables. No new config settings. Practice mode uses existing `tutor` and `study_plan_generator` LLM configs.

---

## 8. Implementation Order

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1 | Add `practice` to `SessionMode`, add practice fields to `SessionState`, rewrite `is_complete`, seed mastery for practice in `create_session()` | `tutor/models/session_state.py` | — | Unit: serialize/deserialize, is_complete for all modes |
| 2 | Migration: rebuild `idx_sessions_one_paused_per_user_guideline` to include `mode` | `db.py` | — | Run migration, verify index def |
| 3 | Create practice prompts (system, turn, welcome) | `tutor/prompts/practice_prompts.py` | — | Manual prompt review |
| 4 | Add `generate_practice_plan()` to study plan generator | `study_plans/services/generator_service.py` | — | Unit: plan has no explain steps |
| 5 | Add practice prompt selection + `generate_practice_welcome()` to master tutor agent | `tutor/agents/master_tutor.py` | Steps 1, 3 | Unit: mock LLM, verify prompt used |
| 6 | Add `_process_practice_turn()`, `_check_practice_mastery()`, `generate_practice_welcome()` (orchestrator method) | `tutor/orchestration/orchestrator.py` | Steps 1, 5 | Unit: reuses state updates, mastery check enforces rules |
| 7 | Update `SessionRepository.list_by_guideline()` to use `SessionState.is_complete`, add `find_most_recent_completed_teach_me()`, add `_compute_coverage_from_guideline()` helper | `shared/repositories/session_repository.py` | Step 1 | Unit: completion detection for all modes, auto-attach |
| 8 | Update `_persist_session` + `_persist_session_state` to allow `is_paused` for practice | `tutor/services/session_service.py` | Step 1 | Unit: persist practice with is_paused=True |
| 9 | Add practice session creation, `_resolve_practice_context()`, `_generate_practice_plan()` | `tutor/services/session_service.py` | Steps 4, 5, 7 | Integration: create with/without source |
| 10 | Rewrite `complete_card_phase()` + add `_finalize_teach_me_session()` | `tutor/services/session_service.py` | Step 1 | Integration: card phase ends, no bridge |
| 11 | Add `end_practice_session()` service method + `/end-practice` endpoint | `tutor/services/session_service.py`, `tutor/api/sessions.py` | Step 9 | Integration: end practice early |
| 12 | Update `/sessions/resumable` to include practice, add `mode` to response | `tutor/api/sessions.py`, `shared/models/schemas.py` | Steps 8, 9 | API: resume practice session |
| 13 | Update `pause_session()` to allow practice, return mode-specific data | `tutor/services/session_service.py` | Step 8 | Integration: pause/resume practice |
| 14 | Update `CreateSessionRequest` with `practice` mode + `source_session_id` | `shared/models/schemas.py` | — | Schema validation |
| 15 | Update report card: `_group_sessions` includes practice (with 3-question gate), canonical denominator, `last_practiced`. Update `get_topic_progress` | `tutor/services/report_card_service.py`, `shared/models/schemas.py` | Step 1 | Unit: coverage from combined modes, min 3 questions |
| 16 | Update session replay API to include `is_complete` field computed from `SessionState.is_complete` | `tutor/api/sessions.py` | Step 1 | API: replay returns is_complete |
| 17 | Frontend: add practice route in `App.tsx` | `llm-frontend/src/App.tsx` | — | Manual: route resolves |
| 18 | Frontend: update `api.ts` types (CreateSessionRequest, GuidelineSessionEntry, ResumableSessionResponse, ReportCardTopic) | `llm-frontend/src/api.ts` | — | TS compile |
| 19 | Frontend: add practice mode card + resume detection + `last_practiced` indicator in `ModeSelection.tsx` | `llm-frontend/src/components/ModeSelection.tsx`, `ModeSelectPage.tsx` | Steps 17, 18 | Manual: 4 modes shown, resume works |
| 20 | Frontend: rewrite card phase completion handler in `ChatSession.tsx` — show summary + Practice CTA | `llm-frontend/src/pages/ChatSession.tsx` | Steps 10, 18 | Manual: Teach Me ends with CTA |
| 21 | Frontend: practice session chat flow, End Practice button, pause button | `llm-frontend/src/pages/ChatSession.tsx` | Steps 11, 17-19 | Manual: full practice flow |
| 22 | Frontend: practice completion screen with Exam nudge (FR-33, FR-35) | `llm-frontend/src/pages/ChatSession.tsx` | Steps 6, 21 | Manual: practice ends → exam CTA |
| 23 | Frontend: update replay hydration to use backend `is_complete` | `llm-frontend/src/pages/ChatSession.tsx` | Step 16 | Manual: completed sessions show summary |

**Rationale:** Backend first (models → migration → prompts → generators → agents → orchestrator → repositories → services → APIs → report card → replay), then frontend. Key ordering decisions:
- Step 2 (migration) early — everything else assumes the new index
- Step 7 (repository) before Step 9 (service) because service depends on `find_most_recent_completed_teach_me`
- Step 10 (card phase rewrite) can happen in parallel with steps 4-9 since it's a contained change
- Step 16 (replay API) before Step 23 (frontend hydration) because frontend reads the new field

---

## 9. Testing Plan

### Unit tests

| Test | What it Verifies |
|------|------------------|
| `test_session_state_practice_is_complete` | `is_complete` returns True for practice when `practice_mastery_achieved=True` |
| `test_session_state_teach_me_is_complete_card_phase` | `is_complete` returns True when `card_phase.completed=True` |
| `test_create_session_seeds_mastery_for_practice` | Practice sessions get all concepts seeded at 0.0 in `mastery_estimates` |
| `test_check_practice_mastery_min_questions` | Mastery NOT triggered before 5 questions |
| `test_check_practice_mastery_max_questions` | Mastery FORCED at 20 questions |
| `test_check_practice_mastery_all_concepts` | Mastery requires ALL canonical concepts >= 0.7, not just touched ones |
| `test_check_practice_mastery_min_per_concept` | Mastery requires at least 2 questions per concept |
| `test_process_practice_turn_reuses_apply_state_updates` | Question lifecycle, mastery updates, misconception tracking all work |
| `test_process_practice_turn_counter_increments_once` | Counter increments per student turn, not per tutor question |
| `test_resolve_practice_context_explicit_source` | Context loaded from specified session_id |
| `test_resolve_practice_context_auto_attach` | Context loaded from most recent completed Teach Me when no source given |
| `test_resolve_practice_context_cold` | Empty context when no prior Teach Me exists |
| `test_resolve_practice_context_includes_variants_and_remedial` | FR-19: All 4 data points present in context (variants, summary, struggles, remedial cards) |
| `test_complete_card_phase_returns_summary_not_bridge` | Card phase completion returns `teach_me_complete`, no bridge turn |
| `test_complete_card_phase_variants_exhausted` | "Explain differently" with no more variants also finalizes the session |
| `test_session_repository_is_complete_all_modes` | `list_by_guideline()` correctly reports is_complete for teach_me, practice, exam, clarify |
| `test_find_most_recent_completed_teach_me` | Returns most recent completed Teach Me, None if none exists |
| `test_compute_coverage_canonical_denominator` | Denominator uses teach_me plan concepts, not practice plan (prevents shrinkage) |
| `test_report_card_practice_min_3_questions_gate` | Practice with <3 questions does NOT contribute to coverage or `last_practiced` |
| `test_report_card_coverage_combines_modes` | Coverage numerator includes teach_me + practice concepts |
| `test_report_card_last_practiced_field` | `last_practiced` date returned for topics with qualifying practice sessions |
| `test_pause_session_supports_practice` | `pause_session()` accepts practice mode |
| `test_end_practice_session` | `end_practice_session()` marks mastery_achieved=True, clears is_paused |
| `test_persist_session_state_practice_is_paused` | Paused state persists for practice mode |
| `test_resumable_endpoint_finds_practice` | `/sessions/resumable` returns paused practice sessions |

### Integration tests

| Test | What it Verifies |
|------|------------------|
| `test_e2e_teach_me_completion_no_bridge` | Start Teach Me → complete cards → returns summary + CTA data, session marked complete |
| `test_e2e_practice_from_teach_me_handoff` | Teach Me → complete → create practice with source_session_id → context auto-attached |
| `test_e2e_practice_cold_start` | Create practice without source → no explanation context in state |
| `test_e2e_practice_auto_attach_from_prior_teach_me` | Create practice without source on topic with prior Teach Me → context auto-attached |
| `test_e2e_practice_mastery_completion` | Run practice session to mastery → session ends at correct threshold |
| `test_e2e_practice_max_questions_cap` | Run practice past max questions → force-ends |
| `test_e2e_practice_pause_resume` | Pause practice → resume → full state preserved |
| `test_e2e_practice_end_early` | End practice early via endpoint → session marked complete |
| `test_e2e_coverage_combines_teach_me_and_practice` | Coverage reflects concepts from both modes |
| `test_e2e_mode_selection_shows_all_4_modes` | API returns data needed for 4-mode selection |

### Manual verification

1. Start Teach Me → complete cards → verify summary + "Let's Practice" CTA appears (no bridge turn)
2. Click CTA → verify practice session starts with context-aware welcome
3. Answer 5+ questions correctly → verify session wraps up, shows summary + Exam nudge
4. Pause mid-practice → verify "Resume Practice" appears in mode selection
5. Resume → verify full conversation history restored
6. End Practice early via button → verify session ends, appears as complete in history
7. Start Let's Practice cold (no prior Teach Me) → verify no card references in tutor messages
8. Start Let's Practice from mode selection after prior completed Teach Me → verify tutor references card content
9. Check report card → verify coverage includes both Teach Me and Practice, denominator doesn't shrink
10. Answer 1-2 questions and abandon practice → verify no `last_practiced` indicator (3-question gate)
11. Check mode selection screen → verify 4 mode cards shown with correct copy

---

## 10. Deployment Considerations

- **Migration:** The partial unique index rebuild must run before the code deploys. The migration is idempotent and non-blocking (DROP+CREATE IF NOT EXISTS). Run `python db.py --migrate` before rolling out code.
- **Backwards compatibility:** 
  - Existing Teach Me sessions with `card_phase.completed=True` will correctly report `is_complete=True` under the new rule
  - Existing incomplete Teach Me sessions (in the interactive phase) will correctly report `is_complete=False` — they'll just stay as legacy v1 sessions forever (out of scope to migrate)
  - Existing exam and clarify_doubts sessions unaffected
- **Deployment order:** Migration → backend → frontend. Backend is forward compatible (accepts old frontend requests unchanged).
- **Rollback:** If practice mode breaks, remove the frontend mode card (one-line change). Backend continues to function — no corrupt data possible since practice sessions are isolated in their own rows.
- **Feature flag (optional):** Could gate the whole feature behind `practice_mode_enabled`. Not strictly needed since frontend controls visibility. Skip unless we want gradual rollout.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `is_complete` change breaks existing Teach Me resume flow | Medium | High | Centralize in `SessionState.is_complete` + update all call sites in one PR. Tests cover teach_me/practice/exam/clarify completion detection |
| Partial unique index migration fails on prod due to existing conflicting rows | Low | High | Pre-migration audit query: `SELECT user_id, guideline_id, COUNT(*) FROM sessions WHERE is_paused=TRUE GROUP BY 1,2 HAVING COUNT(*)>1`. Resolve any before migration |
| `_process_practice_turn()` doesn't preserve scaffolded correction | Medium | High | Integration tests verify question lifecycle (wrong → probe → hint → explain) works in practice mode, just like teach_me |
| Mastery completion too strict (student can't finish) | Medium | Medium | Max-questions hard cap (20) always kicks in. Thresholds are constants at top of method — easy to tune |
| Auto-context attach picks wrong Teach Me session | Low | Low | Uses `ORDER BY created_at DESC` — most recent wins. Test covers multi-session case |
| Frontend fails to read new `is_complete` / `last_practiced` fields (stale cache) | Low | Medium | Field additions are additive — old frontend ignores them. New frontend reads them |
| Coverage denominator wrong for students with no Teach Me history (practice-only) | Low | Low | If no teach_me session exists, `_get_canonical_concepts()` returns empty list → coverage is 0. Acceptable — practice-only students get no coverage indicator until they also do Teach Me |
| Practice welcome prompt is too casual for the student's personality profile | Low | Low | Welcome prompt inherits `personalization_block` from system prompt. Same personalization as all other modes |

---

## 12. Open Questions

None — all technical decisions resolved above with explicit rationale. Key decisions:
- Centralize completion in `SessionState.is_complete`
- Canonical coverage denominator from teach_me plans only (never practice)
- Reuse `_apply_state_updates()` + `_handle_question_lifecycle()` for practice turns
- Practice counter increments at top of `_process_practice_turn()` (on student turn, not tutor question_asked)
- Seed `mastery_estimates` for practice mode in `create_session()`
- Practice mastery check uses canonical concept list (not just touched concepts)
- Partial unique index rebuilt to include `mode` column
- `/sessions/resumable` searches both teach_me and practice
- FR-19 data (variants_shown, remedial_cards, check_in_struggles) read directly from source session's `CardPhaseState` — no new storage needed
- `generate_practice_welcome()` uses its own prompt, not the explain-oriented master tutor welcome
