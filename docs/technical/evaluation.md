# Evaluation -- Technical

Pipeline architecture for automated tutor quality measurement using persona-driven simulation and LLM judging.

---

## Pipeline Architecture

```
Load Persona (JSON)
    |
    v
Create Session (REST: POST /sessions)
    |
    v
Run Simulation (WebSocket: /sessions/ws/{id})
    |  Student Simulator <-> Tutor
    v
LLM Judge Evaluates (5 persona-aware dimensions)
    |
    v
Generate Reports (JSON + Markdown artifacts)
```

---

## Student Simulator

**File:** `evaluation/student_simulator.py`

`StudentSimulator` builds a system prompt from persona traits and uses an LLM to roleplay as the student.

- `correct_answer_probability` is **programmatically enforced** -- each turn, a random roll determines correct/incorrect, then injects explicit directives to the LLM (e.g., `[TURN DIRECTIVE: This turn you MUST ANSWER INCORRECTLY]`)
- When answering incorrectly, a specific mistake is randomly selected from the persona's `common_mistakes` list and injected into the directive
- Persona-specific behaviors fire probabilistically (e.g., `boredom_probability: 0.3`) -- these are included in the system prompt as behavioral tendencies
- All turn decisions (correct/incorrect, probability) are tracked in `turn_decisions` for debugging
- A "natural variation" instruction tells the LLM to vary behavior turn-by-turn rather than rigidly following the persona script
- Retry logic: 3 attempts with exponential backoff (5s, 10s, 15s) on rate limit errors

**Provider differences:**
- OpenAI: directive injected as the last `system` message
- Anthropic: directive appended to the last `user` message (more effective for Claude)

---

## Session Runner

**File:** `evaluation/session_runner.py`

- Creates tutoring session via `POST /sessions` REST endpoint with an `eval-student` user
- Runs conversation loop over WebSocket (`/sessions/ws/{session_id}`)
- Uses the **same protocol real students use** -- the tutor does not know it is being evaluated
- Captures all messages with timestamps, turn numbers, and roles
- Configurable max turns (default: 20) and per-turn timeout (default: 90s)
- Handles `typing`, `state_update`, `assistant`, and `error` WebSocket message types
- Session ends when max turns reached, tutor marks session complete (`is_complete: true`), or no tutor response is received
- Fetches final session state via `GET /sessions/{session_id}` after conversation completes
- `on_turn` callback enables live progress reporting (used by API pipeline for status updates)
- All events are logged to `run.log` with millisecond timestamps

**Server management modes:**
- `skip_server_management=True` (API/in-process): verifies server health via `/health/db` endpoint
- `skip_server_management=False` (CLI): starts uvicorn as subprocess, waits for health check, stops on cleanup

---

## LLM Judge

**File:** `evaluation/evaluator.py`

`ConversationEvaluator` sends full transcript plus persona context to an LLM judge and evaluates across 5 persona-aware dimensions.

### 5 Evaluation Dimensions (scored 1-10)

1. **Responsiveness** -- Does the tutor adapt to student signals?
2. **Explanation Quality** -- Does the tutor explain well and try different approaches?
3. **Emotional Attunement** -- Does the tutor read the room emotionally?
4. **Pacing** -- Is the tutor moving at the right speed for this student?
5. **Authenticity** -- Does it feel like a real teacher or a chatbot?

Each dimension has a detailed rubric with score anchors at 1-2, 3-4, 5-6, 7-8, and 9-10.

The same tutor behavior is judged differently based on the student persona. The evaluator prompt includes persona-specific evaluation criteria (e.g., "Ace students: Did the tutor avoid patronizing? Speed up appropriately?").

### Problem Identification

Each evaluation identifies **top 5 problems**:

| Field | Description |
|-------|-------------|
| `title` | Short problem description |
| `turns` | Which conversation turns exhibited the problem |
| `description` | What went wrong in context of this persona |
| `quote` | Exact evidence from conversation |
| `severity` | `critical` / `major` / `minor` |
| `root_cause` | Category (see below) |

**Root cause categories:** `missed_student_signal`, `wrong_pacing`, `repetitive_approach`, `emotional_mismatch`, `missed_misconception`, `over_scaffolding`, `conversation_history_window`, `prompt_quality`, `model_capability`, `other`

### Evaluator Input Construction

The `_build_user_message()` method assembles the evaluator input:
- Full transcript formatted as `[Turn N] TUTOR/STUDENT: ...`
- Persona context: name, ID, description, personality traits, correct answer probability, behavioral tendencies
- Topic context (when available): topic name, grade level, learning objectives, common misconceptions

### Evaluator Models

| Provider | Model | Config |
|----------|-------|--------|
| OpenAI | GPT-5.2 | Responses API, reasoning effort: `high`, JSON output mode |
| Anthropic | Claude Opus 4.6 | Messages API with streaming, extended thinking (20,000 token budget) |

The evaluator and simulator models are configured independently. When run from the API, models are read from the DB `llm_config` table (`eval_evaluator` and `eval_simulator` keys). When run from the CLI, models fall back to `EVAL_LLM_PROVIDER` env var.

---

## Report Generator

**File:** `evaluation/report_generator.py`

Each run creates a directory: `evaluation/runs/run_{YYYYMMDD}_{HHMMSS}[_{persona_id}][_r{N}]/`

The directory name includes the persona ID when run from CLI, and a `_r{N}` suffix for multi-run mode.

| File | Format | Contents |
|------|--------|----------|
| `config.json` | JSON | Topic ID, tutor model, evaluator model, persona, max turns, timestamp, provider config |
| `conversation.json` | JSON | Machine-readable transcript with messages, session metadata, config |
| `conversation.md` | Markdown | Human-readable transcript with persona info header |
| `evaluation.json` | JSON | Scores (5 dimensions + avg), dimension analysis, problems with severity/root cause, summary |
| `review.md` | Markdown | Formatted report with score bars, detailed analysis per dimension, problems |
| `problems.md` | Markdown | Problem-focused report with overview table, root cause distribution, suggested fixes |
| `run.log` | Text | Timestamped execution log from session runner |
| `error.txt` | Text | Written only on pipeline failure -- contains timestamp, error message, and traceback |

The `problems.md` report includes suggested fixes for certain root causes (e.g., "Increase the conversation history window" for `conversation_history_window`, "Improve session summary to capture narrative context" for `session_summary_lossy`).

Multi-persona comparison (`--persona all`): `comparison_{timestamp}/comparison.md` + `comparison.json`. When `--runs-per-persona` > 1, the comparison report includes per-run detail tables and averaged scores across runs.

---

## Personas

**Location:** `evaluation/personas/*.json`

| Persona ID | Name | Grade | Correct% | Key Trait |
|------------|------|-------|----------|-----------|
| `ace` | Arjun | 5 | 90% | Quick learner, gets bored easily |
| `average_student` | Riya | 5 | 60% | Attentive but confused by new concepts |
| `confused_confident` | Dev | 5 | 45% | Confident wrong answers |
| `distractor` | Kabir | 5 | 65% | Bright but scattered, goes off-topic |
| `quiet_one` | Meera | 5 | 60% | Shy, minimal responses |
| `repetition_detector` | Vikram | 3 | 70% | Notices repetitive patterns |
| `simplicity_seeker` | Aanya | 3 | 50% | Easily overwhelmed |
| `struggler` | Priya | 5 | 30% | Hardworking but confused |

Each persona JSON includes:
- `persona_id`, `name`, `grade`, `age`, `description`
- `correct_answer_probability` -- programmatically enforced per-turn
- `personality_traits` -- list of character traits for the system prompt
- `common_mistakes` -- specific errors the persona makes when answering incorrectly
- `response_style` -- `max_words`, `language`, `examples` for tone calibration
- `behavioral_notes` -- guidelines for the LLM roleplay
- `persona_specific_behaviors` (optional) -- probability-based behavioral tendencies (e.g., `boredom_probability: 0.3`, `minimal_response_probability: 0.8`)

---

## Model Configuration

Evaluator and simulator models can be set independently via two mechanisms:

**DB config (used by API pipeline):** `EvalConfig.from_db()` reads from the `llm_config` table:
- `eval_evaluator` -- provider and model for the LLM judge
- `eval_simulator` -- provider and model for the student simulator

**Environment variables (used by CLI):**
- `EVAL_LLM_PROVIDER` -- fallback provider for both evaluator and simulator when DB config is not used
- CLI `--provider` flag overrides both evaluator and simulator provider

Supported providers: `openai`, `anthropic`, `anthropic-haiku`

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/evaluation/start` | Start evaluation run in background |
| `GET` | `/api/evaluation/status` | Get current evaluation status (polling) |
| `GET` | `/api/evaluation/runs` | List all evaluation runs |
| `GET` | `/api/evaluation/runs/{id}` | Get specific run details |
| `POST` | `/api/evaluation/evaluate-session` | Evaluate an existing session from DB |
| `POST` | `/api/evaluation/runs/{id}/retry-evaluation` | Re-evaluate existing conversation |

Only one evaluation can run at a time (enforced via threading lock; returns 409 if already running).

### Start evaluation request

```json
{
  "topic_id": "<guideline_id>",
  "persona_file": "average_student.json",
  "max_turns": 20
}
```

### Evaluate session request

```json
{
  "session_id": "<session_uuid>"
}
```

Session evaluation extracts messages from `full_conversation_log` (preferred) or `conversation_history`, converts `teacher` role to `tutor`, and extracts topic context (name, learning objectives, misconceptions) from the session state.

### Status response

```json
{
  "status": "idle|loading_persona|running_session|evaluating|generating_reports|complete|failed",
  "run_id": "run_...",
  "detail": "Turn 5/20",
  "turn": 5,
  "max_turns": 20,
  "error": null
}
```

The `error` field is populated when `status` is `failed`.

### Run list response

Each run includes:

```json
{
  "run_id": "run_20260222_143000",
  "timestamp": "2026-02-22T14:30:00",
  "topic_id": "...",
  "message_count": 24,
  "avg_score": 7.2,
  "scores": { "responsiveness": 8, "explanation_quality": 7, ... },
  "source": "simulated",
  "source_session_id": null
}
```

The `source` field is `"simulated"` for new simulations or `"existing_session"` for evaluated real sessions. When source is `"existing_session"`, `source_session_id` contains the original session UUID.

---

## CLI Usage

```bash
cd llm-backend

# Single persona
python -m evaluation.run_evaluation --topic-id <guideline_id> --persona ace.json --skip-server

# All personas
python -m evaluation.run_evaluation --topic-id <guideline_id> --persona all --skip-server

# Multiple runs per persona for noise reduction
python -m evaluation.run_evaluation --topic-id <guideline_id> --persona all --runs-per-persona 3 --skip-server
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--topic-id` | (required) | Guideline ID for the topic |
| `--persona` | average_student.json | Persona file or `all` |
| `--runs-per-persona` | 1 | Runs per persona for noise reduction (only with `--persona all`) |
| `--skip-server` | false | Use already-running server |
| `--max-turns` | 20 | Max conversation turns |
| `--grade` | 3 | Student grade |
| `--provider` | (from env) | LLM provider override (sets both evaluator and simulator) |

The CLI validates API key availability based on selected providers before starting.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TUTOR_LLM_PROVIDER` | (falls back to `APP_LLM_PROVIDER`) | Tutor provider (for reporting labels only) |
| `APP_LLM_PROVIDER` | `openai` | Fallback for tutor provider label |
| `EVAL_LLM_PROVIDER` | `openai` | Default evaluator/simulator provider (CLI mode) |
| `OPENAI_API_KEY` | (required if using OpenAI) | OpenAI API key |
| `ANTHROPIC_API_KEY` | `""` | Anthropic API key |

---

## Frontend

**Route:** `/admin/evaluation`

The `EvaluationDashboard` component provides the full evaluation UI:

- **Run list** -- cards with run ID, timestamp, source badge (Simulated/Session), topic, message count, avg score badge, mini score bars
- **Start form** -- tabbed panel with two modes:
  - "Evaluate Existing Session" -- dropdown of sessions from DB (shows topic, message count, date)
  - "New Simulated Session" -- dropdown of approved guidelines, max turns slider (5-40)
- **Detail view** -- full scores, expandable dimension analysis, overall summary, problems with evidence, conversation transcript with markdown rendering
- **Status polling** -- 2-second polling interval while evaluation is running, auto-refreshes runs list on completion

**Note:** The frontend `DIMENSIONS` constant currently lists 10 legacy dimension names for display. The backend evaluator produces 5 dimensions. Score bars render correctly for whichever dimensions are present in the evaluation data.

---

## Key Files

| File | Purpose |
|------|---------|
| `evaluation/config.py` | `EvalConfig` dataclass, persona loading, paths, DB config integration |
| `evaluation/student_simulator.py` | LLM-powered student with persona-driven behavior and per-turn correctness enforcement |
| `evaluation/session_runner.py` | Session lifecycle: REST creation, WebSocket conversation, server management |
| `evaluation/evaluator.py` | LLM judge with 5-dimension persona-aware rubric, structured JSON output |
| `evaluation/report_generator.py` | Markdown + JSON report generation, comparison reports |
| `evaluation/run_evaluation.py` | CLI entry point, single-persona and multi-persona orchestration |
| `evaluation/api.py` | FastAPI endpoints, background thread execution, status polling, session evaluation |
| `evaluation/personas/*.json` | 8 student persona definitions |
| `llm-frontend/src/features/admin/pages/EvaluationDashboard.tsx` | Evaluation UI: run list, detail view, start form, status polling |
| `llm-frontend/src/features/admin/api/adminApi.ts` | API client functions for evaluation endpoints |
| `llm-frontend/src/features/admin/types/index.ts` | TypeScript types for evaluation data |
