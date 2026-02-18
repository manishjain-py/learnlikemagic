# Tutor Workflow Pipeline - Documentation Changes Justification

**Date:** 2026-02-18
**Document Updated:** `docs/TUTOR_WORKFLOW_PIPELINE.md`

---

## Summary of Changes

| # | Change | Evidence |
|---|--------|----------|
| 1 | Frontend uses REST only, not WebSocket | `api.ts` has no WS code; grep for `WebSocket`/`ws://` across frontend returns 0 matches |
| 2 | Phase 2 response: added `mastery_score` field | `api.ts` `Turn` type requires `mastery_score`; `TutorApp.tsx` reads it from `first_turn` |
| 3 | Question model: added `rubric`, `hints`, `hints_used` fields | `session_state.py` lines 34-36 |
| 4 | Pacing directive: added CONSOLIDATE case | `master_tutor.py` lines 145-151 |
| 5 | ACCELERATE pacing: added early fast-track detection | `master_tutor.py` lines 110-117 |
| 6 | Teaching rule 4: added strategy change + prerequisite gap | `master_tutor_prompts.py` lines 52-60 |
| 7 | Teaching rule 8: 0-2 emojis -> 0-1, added praise calibration details | `master_tutor_prompts.py` lines 81-88 |
| 8 | Teaching rule 9: updated session ending behavior | `master_tutor_prompts.py` lines 90-97 |
| 9 | Added 2 new personas: simplicity_seeker, repetition_detector | `evaluation/personas/` directory has 8 files |
| 10 | Report generator: added config.json to artifacts | `report_generator.py` generates config.json |
| 11 | Teaching rules 1, 2, 5: minor wording alignment | `master_tutor_prompts.py` lines 29, 39-43, 68 |

---

## Detailed Justification

### 1. Frontend uses REST only, not WebSocket

**What changed:** Updated architecture diagram ("REST only (frontend)"), Phase 3a label ("eval only"), WebSocket entry point heading, WebSocket response heading, WebSocket endpoint description in API table, and design decisions table.

**Evidence:** `llm-frontend/src/api.ts` contains only REST functions: `getCurriculum()`, `createSession()`, `submitStep()`, `getModelConfig()`, `getSummary()`. Zero WebSocket code. `TutorApp.tsx` calls only `submitStep()` (REST POST `/sessions/{id}/step`) for chat. The WebSocket endpoint `WS /sessions/ws/{session_id}` is only consumed by `llm-backend/evaluation/session_runner.py` for running simulated evaluation sessions.

### 2. Phase 2 response: added `mastery_score`

**What changed:** Added `"mastery_score": 0.0` to the `first_turn` response example.

**Evidence:** `llm-frontend/src/api.ts` defines `Turn` with `mastery_score: number` as a required field. `TutorApp.tsx` reads `data.first_turn.mastery_score` and sets it as state. The doc example was missing this field.

### 3. Question model: added 3 missing fields

**What changed:** Added `rubric: str = ""`, `hints: List[str] = []`, `hints_used: int = 0` to the Question model.

**Evidence:** `llm-backend/tutor/models/session_state.py` lines 34-36:
```python
rubric: str = Field(default="", description="Evaluation criteria")
hints: list[str] = Field(default_factory=list, description="Available hints")
hints_used: int = Field(default=0, description="Number of hints provided")
```

### 4. Pacing directive: added CONSOLIDATE case

**What changed:** Added CONSOLIDATE to the pacing directive list: "avg_mastery 0.4-0.65 & steady & 2+ wrong attempts -> Same-level problem to build confidence."

**Evidence:** `llm-backend/tutor/agents/master_tutor.py` lines 145-151:
```python
if has_real_data and 0.4 <= avg_mastery < 0.65 and trend == "steady":
    if session.last_question and session.last_question.wrong_attempts >= 2:
        return (
            "PACING: CONSOLIDATE — Student is getting it but still shaky. "
            "Give them a similar problem at the SAME level to build confidence. "
            "Don't introduce new concepts yet. Keep it short and encouraging."
        )
```

### 5. ACCELERATE pacing: early fast-track detection

**What changed:** Updated ACCELERATE description to mention the 60%+ strong concepts threshold.

**Evidence:** `llm-backend/tutor/agents/master_tutor.py` lines 110-117: When 60%+ of concepts have mastery >= 0.7, and avg_mastery >= 0.65 with improving trend, the system forces the ACCELERATE path even before the overall average hits 0.8. This is a meaningful detail for understanding when acceleration triggers.

### 6. Teaching rule 4: strategy change + prerequisite gap

**What changed:** Added "2+ same: change strategy fundamentally; prerequisite gap detection after 3+ turns" to the rule 4 summary.

**Evidence:** `llm-backend/tutor/prompts/master_tutor_prompts.py`:
- Lines 52-56: "After 2+ wrong answers on the SAME question: CHANGE STRATEGY fundamentally. Don't reframe the same explanation — try a completely different approach."
- Lines 57-60: "PREREQUISITE GAP: If repeated errors across 3+ turns reveal the student lacks a foundational skill...STOP the current topic."

### 7. Teaching rule 8: emoji count and praise calibration

**What changed:** Changed "0-2 emojis" to "0-1 emojis", added "no ALL CAPS, no stock phrases", changed "proportional praise" to "calibrate praise to difficulty and student level".

**Evidence:** `llm-backend/tutor/prompts/master_tutor_prompts.py` lines 87-88: "Emojis: 0-1 per response. No ALL CAPS. No stock phrases." Line 81: "Be real — calibrate praise to difficulty and student level."

### 8. Teaching rule 9: session ending behavior

**What changed:** Changed "check for misconceptions first, personalized closing" to "check if student wants to continue, respect goodbye".

**Evidence:** `llm-backend/tutor/prompts/master_tutor_prompts.py` lines 90-97: "first check if the student wants to continue ('Want to try something harder?' or similar). If they do, keep going with extension material." And: "If the student says goodbye, RESPECT IT — don't reverse course and add more problems after they've signed off."

### 9. Added 2 new student personas

**What changed:** Updated persona count from 6 to 8. Added `simplicity_seeker` (Aanya, 50%) and `repetition_detector` (Vikram, 70%).

**Evidence:** `llm-backend/evaluation/personas/` directory listing:
```
ace.json, average_student.json, confused_confident.json, distractor.json,
quiet_one.json, repetition_detector.json, simplicity_seeker.json, struggler.json
```
- `simplicity_seeker.json`: persona_id "simplicity_seeker", name "Aanya", correct_answer_probability 0.5, key trait: "easily overwhelmed student who needs simple, concrete explanations"
- `repetition_detector.json`: persona_id "repetition_detector", name "Vikram", correct_answer_probability 0.7, key trait: "notices and gets bored when the tutor keeps asking the same type of question"

### 10. Report generator: added config.json

**What changed:** Added `config.json` to report artifacts list in both the file reference table and the eval flow description.

**Evidence:** `llm-backend/evaluation/report_generator.py` generates `config.json` via `EvalConfig.to_dict()` which serializes all config settings excluding API keys.

### 11. Teaching rules: minor wording alignment

**What changed:** Updated rule 1 to add "start simple", rule 2 to add "skip aggressively for strong students", rule 5 to say "vary structure AND question formats".

**Evidence:** `llm-backend/tutor/prompts/master_tutor_prompts.py`:
- Rule 1 (line 29): "Follow the plan, hide the scaffolding. Start simple."
- Rule 2 (lines 39-43): "Don't linger. If the student explicitly requests harder material, HONOR IT — skip multiple steps if needed"
- Rule 5 (line 68): "Never repeat yourself — vary your structure AND your questions formats."

---

## Verified Accurate (No Changes Needed)

- Pipeline phases table: matches code endpoints and handlers
- Phase 1 selection flow: matches `TutorApp.tsx` and curriculum API
- Phase 2 session creation flow: matches `session_service.py`
- Study plan conversion: matches `topic_adapter.py`
- Orchestrator flow: matches `orchestrator.py`
- REST response format: matches code DTOs
- Session completion logic: matches code
- SessionState model: matches `session_state.py` (all fields correct)
- StudyPlan/StudyPlanStep models: match `study_plan.py`
- Agent system table: matches code (Safety + Master Tutor)
- Provider support: matches `llm_service.py` and `anthropic_adapter.py`
- LLM calls summary: matches code
- Evaluation dimensions (5): match `evaluator.py` EVALUATION_DIMENSIONS list
- CLI arguments: match `run_evaluation.py`
- API endpoints reference: all endpoints verified
- Database tables: match code
- Key files reference: correct
- Configuration/env vars: match code

---

## Previous Justification Records

- 2026-02-14: Teaching rules 11->10, TutorTurnOutput fields, intent values, routes, DevTools, SessionState fields, question lifecycle, pacing/style, session extension, utils cleanup, eval reports, design decisions
- 2026-02-13: Teaching rules 8->11, agent model corrections, evaluation dimensions 10->5, persona docs, API endpoints
