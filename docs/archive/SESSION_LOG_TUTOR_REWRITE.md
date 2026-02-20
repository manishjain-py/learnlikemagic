# Session Log: Tutor Workflow Rewrite

**Date:** February 11, 2026
**Branch:** `feature/new-tutor-workflow`
**Status:** All phases complete, not yet committed

---

## Problem Statement

The existing tutor workflow used a **3-agent LangGraph pipeline** (PLANNER -> EXECUTOR -> EVALUATOR) that produced unnatural, robotic tutoring sessions. Key issues:

1. **Disconnected responses** — Three separate agents stitching outputs together created visible seams in conversation flow
2. **Repetitive content** — Agents had no shared memory of what was already said, leading to repeated explanations
3. **Mechanical pacing** — Rigid step progression with no ability for the tutor to fluidly adapt
4. **Context amnesia** — Each agent processed only its narrow slice, losing the narrative thread
5. **Unnatural tone** — Multi-agent composition produced responses that felt assembled rather than spoken

A prototype in `/Users/manishjain/repos/tutor-test` demonstrated that a **single Master Tutor agent** handling all teaching in one LLM call produced significantly more natural conversations, scoring 9.2/10 on naturalness in evaluation runs (vs ~3.6/10 for the old pipeline).

---

## What Changed

### Approach

Replace the 3-agent LangGraph pipeline with the single Master Tutor architecture from tutor-test, keeping the existing PostgreSQL database, REST API contract, and frontend unchanged. Add WebSocket support for real-time chat and an automated evaluation pipeline.

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Keep PostgreSQL for session storage | Existing infrastructure, no migration needed |
| Keep DB for topic/guideline loading | Teaching guidelines and study plans already in DB |
| Add topic adapter (DB -> new models) | Bridges existing DB schema to new Pydantic models |
| Add WebSocket alongside REST | REST for backward compatibility, WebSocket for real-time chat and evaluation |
| Add Anthropic Claude support | Multi-provider flexibility for both tutoring and evaluation |

---

## Implementation Phases

### Phase 0: Create Branch
- Created `feature/new-tutor-workflow` from `main`

### Phase 1: Delete Old Tutor Workflow (16 files deleted)

Removed the entire LangGraph pipeline:

| Deleted File | What It Was |
|-------------|-------------|
| `tutor/agents/planner_agent.py` | Planner agent (study plan decisions) |
| `tutor/agents/executor_agent.py` | Executor agent (content delivery) |
| `tutor/agents/evaluator_agent.py` | Evaluator agent (answer grading) |
| `tutor/agents/base.py` | Old agent base class |
| `tutor/agents/schemas.py` | Old agent schemas |
| `tutor/agents/prompts/*.txt` | Old prompt templates (4 files) |
| `tutor/agents/prompts/__init__.py` | Prompt loader |
| `tutor/orchestration/tutor_workflow.py` | LangGraph workflow definition |
| `tutor/orchestration/workflow_bridge.py` | Bridge between workflow and service |
| `tutor/orchestration/state_converter.py` | State conversion for LangGraph |
| `tutor/orchestration/schemas.py` | Orchestration schemas |
| `tutor/models/state.py` | Old TutorState/SimplifiedState |
| `tutor/models/helpers.py` | State helper functions |
| `tutor/api/logs.py` | Deprecated log endpoints |
| `visualize_graph.py` | LangGraph visualization |
| `test_evaluator_accuracy.py` | Old evaluator test |
| `tests/integration/test_tutor_workflow.py` | Old workflow integration test |
| `scripts/test_gpt_5_2_agents.py` | Old agent test script |

### Phase 2: Create New Tutor Architecture (28 new files)

#### Agents (`tutor/agents/`)
| File | Purpose |
|------|---------|
| `base_agent.py` | Abstract base: `execute()`, `build_prompt()`, LLM call with strict JSON schema, timeout, retry, logging |
| `master_tutor.py` | Single agent for all teaching. Returns `TutorTurnOutput` with response, intent, mastery signals, step advancement |
| `safety.py` | Fast content moderation gate before master tutor runs |

#### Orchestration (`tutor/orchestration/`)
| File | Purpose |
|------|---------|
| `orchestrator.py` | `TeacherOrchestrator`: safety -> master_tutor -> apply_state_updates. Central coordinator |

#### Models (`tutor/models/`)
| File | Purpose |
|------|---------|
| `session_state.py` | `SessionState` Pydantic model: session identification, topic/plan, progress tracking, assessment, memory (conversation history + summary), behavioral tracking |
| `study_plan.py` | `Topic`, `TopicGuidelines`, `StudyPlan`, `StudyPlanStep` models |
| `messages.py` | `Message`, `StudentContext`, WebSocket protocol (ClientMessage/ServerMessage), DTOs, factory functions |
| `agent_logs.py` | `AgentLogEntry`, `AgentLogStore` (thread-safe in-memory) |

#### Prompts (`tutor/prompts/`)
| File | Purpose |
|------|---------|
| `master_tutor_prompts.py` | System prompt (study plan + guidelines + 8 teaching rules) and per-turn prompt |
| `orchestrator_prompts.py` | Welcome message and session summary prompts |
| `templates.py` | `PromptTemplate` class with variable interpolation, agent-specific templates |

#### Utils (`tutor/utils/`)
| File | Purpose |
|------|---------|
| `schema_utils.py` | `get_strict_schema()`: Pydantic model -> OpenAI strict JSON schema |
| `prompt_utils.py` | `format_conversation_history()`, `build_context_section()` |
| `state_utils.py` | `update_mastery_estimate()` (exponential moving average), `calculate_overall_mastery()`, `should_advance_step()` |

#### Other
| File | Purpose |
|------|---------|
| `tutor/exceptions.py` | Custom exception hierarchy: AgentError, SessionError, LLMError, PromptError |

### Phase 3: Integration Layer (DB <-> New Models)

| File | Action | Purpose |
|------|--------|---------|
| `tutor/services/topic_adapter.py` | Created | Converts DB `TeachingGuideline` + `StudyPlan` -> new `Topic` model |
| `tutor/services/session_service.py` | Rewritten | Uses new `TeacherOrchestrator` and `SessionState` instead of old LangGraph workflow |
| `tutor/api/sessions.py` | Modified | Added WebSocket endpoint (`/sessions/ws/{id}`), agent logs endpoint, preserved REST contract |

### Phase 4: Extend LLM Service

| File | Action | Purpose |
|------|--------|---------|
| `shared/services/anthropic_adapter.py` | Created | Claude API wrapper: thinking budgets, tool_use structured output, async/sync support |
| `shared/services/llm_service.py` | Modified | Added Anthropic provider switching, `call_anthropic()` method |
| `config.py` | Modified | Added `anthropic_api_key`, `app_llm_provider` settings |

### Phase 5: Evaluation Pipeline (9 new files)

| File | Purpose |
|------|---------|
| `evaluation/__init__.py` | Package init |
| `evaluation/config.py` | `EvalConfig` dataclass: server, session, simulation, LLM settings |
| `evaluation/student_simulator.py` | LLM-powered student with persona (OpenAI gpt-4o or Anthropic) |
| `evaluation/session_runner.py` | Session lifecycle: create via REST, converse via WebSocket, capture messages |
| `evaluation/evaluator.py` | 10-dimension LLM judge (coherence, non-repetition, natural flow, engagement, responsiveness, pacing, grade appropriateness, topic coverage, session arc, overall naturalness) |
| `evaluation/report_generator.py` | Generates conversation.md, evaluation.json, review.md, problems.md |
| `evaluation/run_evaluation.py` | CLI entry point: `python -m evaluation.run_evaluation` |
| `evaluation/api.py` | FastAPI endpoints for starting/monitoring evaluation runs |
| `evaluation/personas/average_student.json` | Default student persona "Riya" (grade 5, age 10, 60% correct probability) |

### Phase 6: Cleanup & Dependencies

| Change | Details |
|--------|---------|
| `requirements.txt` | Removed: `langgraph`, `langgraph-checkpoint-postgres`, `langchain-core`, `psycopg[binary]`. Added: `anthropic>=0.39.0`, `httpx>=0.27.0`, `websockets>=12.0` |
| `main.py` | Updated router imports: removed `logs`, added `evaluation_router` |
| `tutor/api/__init__.py` | Removed `logs` import |

### Phase 7: Documentation Updates

| File | Action |
|------|--------|
| `docs/TUTOR_WORKFLOW_PIPELINE.md` | Complete rewrite (~560 lines) documenting new single master tutor architecture, all APIs, evaluation pipeline |
| `CLAUDE.md` | Updated project overview ("LangGraph agents" -> "single master tutor agent"), file naming conventions |

---

## By the Numbers

| Metric | Count |
|--------|-------|
| Files deleted | 18 |
| Files created | 28 |
| Files modified | 9 |
| Lines removed | ~5,400 |
| Lines added | ~800 (modified files) + new files |
| Old dependencies removed | 4 (langgraph, langgraph-checkpoint-postgres, langchain-core, psycopg) |
| New dependencies added | 3 (anthropic, httpx, websockets) |

---

## Architecture Before & After

### Before (3-agent LangGraph)
```
Student Message
    |
    v
PLANNER AGENT (GPT-5.2)     -> decides what to teach next
    |
    v
EXECUTOR AGENT (GPT-5.2)    -> generates content/questions
    |
    v
EVALUATOR AGENT (GPT-5.2)   -> grades answers
    |
    v
LangGraph State Machine     -> routes between agents
    |
    v
Response to Student
```
- 3 LLM calls per turn
- Each agent sees only its slice of context
- LangGraph manages state transitions
- Responses feel stitched together

### After (single Master Tutor)
```
Student Message
    |
    v
SAFETY AGENT (GPT-5.2)      -> fast content check (1 call)
    |
    v
MASTER TUTOR (GPT-5.2)      -> everything in 1 call (1 call)
    |
    v
State Updates Applied        -> mastery, misconceptions, step advance
    |
    v
Response to Student
```
- 2 LLM calls per turn (safety + master tutor)
- Master tutor sees full session context
- No state machine needed — tutor decides everything
- Responses feel natural and coherent

---

## New Capabilities Added

1. **WebSocket real-time chat** — `WS /sessions/ws/{session_id}` for live tutoring
2. **Anthropic Claude support** — Configurable via `APP_LLM_PROVIDER` env var
3. **Evaluation pipeline** — Automated quality measurement with 10-dimension LLM judge
4. **Student simulator** — Persona-based simulated student for testing
5. **Agent execution logs** — In-memory log store accessible via API
6. **Report generation** — Conversation transcripts, scores, problem analysis

---

## Remaining Steps

1. Run `pip install -r requirements.txt` to install new dependencies
2. Start server: `cd llm-backend && python -m uvicorn main:app --reload`
3. Test session creation with a known guideline_id
4. Test WebSocket chat flow
5. Run evaluation: `python -m evaluation.run_evaluation`
6. Commit changes to the branch
