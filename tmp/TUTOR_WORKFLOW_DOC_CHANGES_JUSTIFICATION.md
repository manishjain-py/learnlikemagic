# Tutor Workflow Pipeline - Documentation Changes Justification

**Date:** 2026-02-14
**Document Updated:** `docs/TUTOR_WORKFLOW_PIPELINE.md`

---

## Summary of Changes

| # | Change | Evidence |
|---|--------|----------|
| 1 | Teaching rules: 11 → 10, updated descriptions to match code | `master_tutor_prompts.py` lines 27-69 |
| 2 | TutorTurnOutput: added `question_concept`, `session_complete` fields | `master_tutor.py` lines 63-71 |
| 3 | Intent values: added `answer_change` and `novel_strategy` | `master_tutor.py` lines 33-34 |
| 4 | Frontend routes: added `/admin/evaluation` | `App.tsx` line 38 |
| 5 | Key Code Locations: added Frontend DevTools path | `llm-frontend/src/features/devtools/` directory |
| 6 | SessionState: added 6 missing fields | `session_state.py` lines 88-101 |
| 7 | Question lifecycle: new section documenting phase progression | `session_state.py` Question model, `orchestrator.py` `_handle_question_lifecycle()` |
| 8 | Dynamic pacing & student style: new section | `master_tutor.py` `_compute_pacing_directive()`, `_compute_student_style()` |
| 9 | Session extension: documented 10-turn extension mechanism | `orchestrator.py` lines 106-108 |
| 10 | `prompt_utils.py`: removed non-existent `build_context_section()` | Grep confirmed 0 results across codebase |
| 11 | `schema_utils.py`: added 3 missing function references | `schema_utils.py` defines all 5 functions |
| 12 | `state_utils.py`: added 2 missing function references | `state_utils.py` defines all 5 functions |
| 13 | Evaluation reports: added `conversation.json` | `report_generator.py` `save_conversation_json()` |
| 14 | Key Design Decisions: added 3 new entries, updated 1 | New code patterns found in exploration |

---

## Detailed Justification

### 1. Teaching rules: 11 → 10, updated descriptions

**Evidence:** `master_tutor_prompts.py` `MASTER_TUTOR_SYSTEM_PROMPT` lines 27-69 defines exactly 10 numbered rules (1-10). The previous doc listed 11 rules where Rule 11 ("Check for misconceptions before ending") was actually a sub-point within Rule 9 in the code: "When the final step is mastered, check for misconceptions first (ask them to demonstrate understanding)."

**Additional corrections:**
- Rule 2: Doc said "Advance when ready + adaptive pacing" — code says just "Advance when ready." Pacing is handled by `_compute_pacing_directive()` dynamically per turn, not as a static prompt rule.
- Rule 4: Doc said "Evaluate answers carefully" — code says "Guide discovery — don't just correct" with graduated scaffolding (1st wrong → probe, 2nd → hint, 3rd+ → explain).

### 2. TutorTurnOutput: added missing fields

**Evidence:** `master_tutor.py` lines 63-71:
```python
question_concept: Optional[str] = Field(default=None, description="Which concept the question tests")
session_complete: bool = Field(default=False, description="Set to true when the student has completed the final step...")
```
Both fields exist in the actual Pydantic model but were missing from the doc's TutorTurnOutput listing.

### 3. Intent values: added `answer_change` and `novel_strategy`

**Evidence:** `master_tutor.py` line 33-34: `intent: str = Field(description="What the student was doing: answer, answer_change, question, confusion, novel_strategy, off_topic, or continuation")`. Doc listed only "answer/question/confusion/off_topic/continuation".

### 4. Frontend routes: added `/admin/evaluation`

**Evidence:** `App.tsx` line 38: `<Route path="/admin/evaluation" element={<EvaluationDashboard />} />`. The Architecture Overview diagram listed only `/ (tutor), /admin/books, /admin/guidelines` — missing the evaluation dashboard route.

### 5. Key Code Locations: added Frontend DevTools

**Evidence:** `llm-frontend/src/features/devtools/` contains:
- `components/DevToolsDrawer.tsx` — slide-out drawer with 3 tabs
- `components/StudyPlanPanel.tsx` — study plan visualization
- `components/GuidelinesPanel.tsx` — guidelines display
- `components/AgentLogsPanel.tsx` — agent log viewer with filters
- `api/devToolsApi.ts` — API client for `/sessions/{id}` and `/sessions/{id}/agent-logs`
- `types/index.ts` — TypeScript types for session state, agent logs

This is a significant developer feature not referenced anywhere in the doc.

### 6. SessionState: added 6 missing fields

**Evidence:** `session_state.py` defines these fields that were absent from the doc's SessionState model:
- `last_concept_taught: Optional[str]` — tracks the current concept being taught
- `allow_extension: bool = True` — controls whether session can extend past study plan
- `weak_areas: list[str]` — areas where student struggles
- `pace_preference: Literal["slow", "normal", "fast"]` — personalization field
- `full_conversation_log: list[Message]` — complete history (no truncation), distinct from the windowed `conversation_history`
- `misconceptions: list[Misconception]` — was in the model but not in doc's SessionState listing

### 7. Question lifecycle: new documentation section

**Evidence:** `session_state.py` `Question` class includes:
- `wrong_attempts: int = 0`
- `previous_student_answers: list[str] = []`
- `phase: str = "asked"` (values: "asked", "probe", "hint", "explain")

`orchestrator.py` `_handle_question_lifecycle()` manages phase progression across 5 cases: wrong answer on pending → increment attempts; correct answer → clear; new question → track; different concept → replace; same concept follow-up → keep existing. This is a core pedagogical mechanism that was entirely undocumented.

### 8. Dynamic pacing & student style: new documentation section

**Evidence:** `master_tutor.py` defines:
- `_compute_pacing_directive(session)` — returns one of 5 directives (TURN 1, ACCELERATE, EXTEND, SIMPLIFY, STEADY) based on turn_count, avg_mastery, progress_trend, and is_complete
- `_compute_student_style(session)` — analyzes word count patterns, emoji usage, question-asking behavior, and detects disengagement (responses getting shorter over 4+ messages)

These are injected into the turn prompt via `{pacing_directive}` and `{student_style}` placeholders in `master_tutor_prompts.py` lines 85-86. This is a core adaptive mechanism: the tutor adjusts response length and complexity per turn based on student signals.

### 9. Session extension: documented mechanism

**Evidence:** `orchestrator.py` lines 106-108:
```python
max_extension_turns = 10
extension_turns = session.turn_count - (session.topic.study_plan.total_steps * 2)
if session.is_complete and (not session.allow_extension or extension_turns > max_extension_turns):
```
Advanced students can continue up to 10 turns beyond `total_steps * 2`. The EXTEND pacing directive pushes them to harder territory. Post-completion handler only fires after extension is exhausted. This was undocumented — the doc previously implied sessions end immediately when `is_complete` is true.

### 10. Removed non-existent `build_context_section()` from prompt_utils.py

**Evidence:** Grep for `build_context_section` across the entire codebase returned 0 results. `prompt_utils.py` only contains `format_conversation_history()`. The function was likely removed in a previous refactor but the doc reference was never cleaned up.

### 11. Added missing `schema_utils.py` function references

**Evidence:** `schema_utils.py` defines 5 functions, doc only listed 2:
- `get_strict_schema()` — was documented
- `make_schema_strict()` — was documented
- `validate_agent_output()` — used by `BaseAgent.execute()` to validate LLM output
- `parse_json_safely()` — used for safe JSON parsing with error context
- `extract_json_from_text()` — extracts JSON from mixed text/code blocks

### 12. Added missing `state_utils.py` function references

**Evidence:** `state_utils.py` defines 5 functions, doc only listed 3:
- `update_mastery_estimate()` — was documented
- `calculate_overall_mastery()` — was documented
- `should_advance_step()` — was documented
- `get_mastery_level()` — converts scores to categorical levels (mastered/strong/adequate/developing/needs_work)
- `merge_misconceptions()` — merges misconception lists with dedup and max_count

### 13. Evaluation reports: added `conversation.json`

**Evidence:** `report_generator.py` `save_conversation_json()` method generates `conversation.json` with config, message_count, messages, and session_metadata. Doc only listed `conversation.md` — the JSON variant provides machine-readable conversation data used for re-evaluation.

### 14. Key Design Decisions: added 3 new entries

**Evidence:**
- **Session extension (10 turns)**: `orchestrator.py` extension logic (lines 106-108)
- **Dynamic pacing & style**: `master_tutor.py` `_compute_pacing_directive()` and `_compute_student_style()` methods
- **Question lifecycle phases**: `orchestrator.py` `_handle_question_lifecycle()` + `session_state.py` Question model with `phase` field
- **Updated**: Conversation window decision now notes the dual-store pattern (`conversation_history` windowed + `full_conversation_log` complete)

---

## Verified Accurate (No Changes Needed)

- Pipeline phases table: matches code endpoints and handlers
- Phase 1 selection flow: matches `TutorApp.tsx` and curriculum API
- Phase 2 session creation flow: matches `session_service.py`
- Study plan conversion: matches `topic_adapter.py`
- REST/WebSocket response formats: match code DTOs
- Agent system table: matches code (Safety + Master Tutor)
- Provider support description: matches `llm_service.py` and `anthropic_adapter.py`
- Evaluation pipeline section: dimensions, personas, CLI args, env vars all match code
- Database tables: match `entities.py`
- API endpoints reference: all endpoints verified against code routes
- LLM calls summary: matches code
- Configuration/env vars: match code

---

## Previous Changes (preserved from earlier updates)

- 2026-02-13: Teaching rules 8→11, agent model corrections, evaluation dimensions 10→5, persona documentation, API endpoints additions
- 2025-12-30: Backend path corrections after folder reorganization
- 2025-12-28: Pre-Built Study Plans section, Phase 2 flow with plan loading
