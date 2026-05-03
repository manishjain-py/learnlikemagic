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
[If cards exist] Handle Card Phase (read cards, POST /card-action)
    |
    v
Run Simulation (WebSocket: /sessions/ws/{id})
    |  Student Simulator <-> Tutor
    v
LLM Judge Evaluates (5 core + 2 conditional card-phase dimensions)
    |
    v
Generate Reports (JSON + Markdown artifacts)
```

---

## Student Simulator

**File:** `autoresearch/tutor_teaching_quality/evaluation/student_simulator.py`

`StudentSimulator` builds a system prompt from persona traits and uses `LLMService` to roleplay as the student.

- `correct_answer_probability` is **programmatically enforced** -- each turn, a random roll determines correct/incorrect, then injects explicit directives to the LLM (e.g., `[TURN DIRECTIVE: This turn you MUST ANSWER INCORRECTLY]`)
- When answering incorrectly, a specific mistake is randomly selected from the persona's `common_mistakes` list and injected into the directive
- Persona-specific behaviors fire probabilistically (e.g., `boredom_probability: 0.3`) -- these are included in the system prompt as behavioral tendencies
- All turn decisions (correct/incorrect, probability) are tracked in `turn_decisions` for debugging
- A "natural variation" instruction tells the LLM to vary behavior turn-by-turn rather than rigidly following the persona script
- If cards were shown, card content is included in the prompt so the simulated student can reference what they read
- Builds a single flat prompt string (system context + conversation history + turn directive) passed to `self.llm.call()` with `reasoning_effort="low"`, `json_mode=False`
- Note: `EvalConfig.simulator_temperature` (0.8) and `simulator_max_tokens` (150) exist on the dataclass but are **not currently read** by the simulator -- generation is governed by the underlying `LLMService` defaults

---

## Session Runner

**File:** `autoresearch/tutor_teaching_quality/evaluation/session_runner.py`

- Creates tutoring session via `POST /sessions` REST endpoint with an `eval-student` user
- **Card phase handling:** if the session response includes `session_phase: "card_phase"`, the runner reads all explanation cards, adds them to the transcript as `explanation_card` entries, then calls `POST /sessions/{id}/card-action` with `action: "clear"` to transition to interactive teaching. Card phase metadata (cards, variant key, total variants) stored in `self.card_phase_data` for the evaluator.
- Runs conversation loop over WebSocket (`/sessions/ws/{session_id}`)
- Uses the **same protocol real students use** -- the tutor does not know it is being evaluated
- Captures all messages with timestamps, turn numbers, roles, and phase labels (e.g., `welcome`, `card_phase_welcome`, `card_to_interactive_transition`)
- Configurable max turns (default: 20) and per-turn timeout (default: 90s)
- Handles `typing`, `token`, `visual_update`, `state_update`, `assistant`, and `error` WebSocket message types
- Session ends when max turns reached, tutor marks session complete (`is_complete: true`), or no tutor response is received
- Fetches final session state via `GET /sessions/{session_id}` after conversation completes
- `on_turn` callback enables live progress reporting (used by API pipeline for status updates)
- All events are logged to `run.log` with millisecond timestamps

**Server management modes:**
- `skip_server_management=True` (API path + CLI `--skip-server`): verifies server health via `/health/db`, does not start/stop the server
- `skip_server_management=False` (CLI default): starts `uvicorn main:app` as a subprocess from `PROJECT_ROOT`, waits up to `server_startup_timeout=30s`, terminates on cleanup
- `restart_server=True` (used by `run_experiment.py`): kills any existing process on `server_port` via `lsof -ti :PORT`, then starts a fresh subprocess (ensures code changes take effect across iterations)

---

## LLM Judge

**File:** `autoresearch/tutor_teaching_quality/evaluation/evaluator.py`

`ConversationEvaluator` sends full transcript plus persona context to an LLM judge. Uses `config.create_llm_service("evaluator")` for provider-agnostic LLM calls with `reasoning_effort="high"` and `json_mode=True`. The `EvalConfig.evaluator_reasoning_effort` field (default `"high"`) exists but is **not read** -- the value is hardcoded in `evaluator.py`.

The system prompt is loaded at module import time from `prompts/evaluator.txt`; the card-phase dimensions block is loaded from `prompts/card_phase_dimensions.txt` and spliced in via `{card_phase_dimensions}` only when the conversation contains `explanation_card` messages. The schema (scores + analysis fields) is generated dynamically per call based on which dimensions apply.

### 7 Evaluation Dimensions (scored 1-10)

**Core dimensions (always scored):**

1. **Responsiveness** -- Does the tutor adapt to student signals?
2. **Explanation Quality** -- Does the tutor explain well and try different approaches?
3. **Emotional Attunement** -- Does the tutor read the room emotionally?
4. **Pacing** -- Is the tutor moving at the right speed for this student?
5. **Authenticity** -- Does it feel like a real teacher or a chatbot?

**Card phase dimensions (only when `explanation_card` entries exist in conversation):**

6. **Card-to-Session Coherence** -- Does the interactive session build on explanation card content?
7. **Transition Quality** -- How smooth is the bridge from cards to interactive teaching?

`_has_card_phase()` checks for `role == "explanation_card"` messages. When absent, dimensions 6-7 are excluded from the prompt schema and scoring.

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

**Root cause categories:** `missed_student_signal`, `wrong_pacing`, `repetitive_approach`, `emotional_mismatch`, `missed_misconception`, `over_scaffolding`, `conversation_history_window`, `prompt_quality`, `model_capability`, `card_content_ignored`, `abrupt_transition`, `card_repetition`, `other`

### Evaluator Input Construction

The `_build_user_message()` method assembles the evaluator input:
- Full transcript formatted as `[Turn N] TUTOR/STUDENT: ...` (explanation cards formatted as `[EXPLANATION CARD] ...`)
- Card phase context (when cards present): number of cards, variant key, total variants, note that student clicked "Clear"
- Persona context: name, ID, description, personality traits, correct answer probability, behavioral tendencies
- Topic context (when available): topic name, grade level, and nested `guidelines` containing `learning_objectives` and `common_misconceptions`

**Note:** Topic context is only provided in the session evaluation path (`_run_session_evaluation`), where it is extracted from the session state via `hasattr` lookups on `topic.grade_level`, `topic.learning_objectives`, and `topic.common_misconceptions`. Simulated evaluation (both API and CLI) does not pass `topic_info` to the evaluator -- the judge evaluates based on the transcript and persona alone.

### Model Configuration

Both evaluator and simulator use `config.create_llm_service(component)` which routes through the unified `LLMService` abstraction. Supported providers: `openai`, `anthropic`, `claude_code`.

**Evaluator defaults:**

| Provider | Default Model | Config |
|----------|---------------|--------|
| `openai` | gpt-5.2 | reasoning effort: `high`, JSON output mode |
| `anthropic` | claude-opus-4-6 | extended thinking (20,000 token budget) |
| `anthropic-haiku` | (model id from DB) | requires DB config to set haiku model id |
| `claude_code` | claude-code | no API key needed |

**Simulator defaults:**

| Provider | Default Model | Config |
|----------|---------------|--------|
| `openai` | gpt-4o | reasoning effort: `low` |
| `anthropic` | claude-opus-4-6 | reasoning effort: `low` |
| `anthropic-haiku` | (model id from DB) | requires DB config to set haiku model id |
| `claude_code` | claude-code | no API key needed |

The evaluator and simulator models are configured independently. When run from the API, models are read from the DB `llm_config` table (`eval_evaluator` and `eval_simulator` keys). When run from the CLI, models fall back to `EVAL_LLM_PROVIDER` env var. The `claude_code` provider requires no API key.

---

## Report Generator

**File:** `autoresearch/tutor_teaching_quality/evaluation/report_generator.py`

Each run creates a directory: `autoresearch/tutor_teaching_quality/evaluation/runs/run_{YYYYMMDD}_{HHMMSS}[_{persona_id}][_r{N}]/`

The directory name includes the persona ID when run from CLI, and a `_r{N}` suffix for multi-run mode.

| File | Format | Contents |
|------|--------|----------|
| `config.json` | JSON | Topic ID, tutor model, evaluator model, persona, max turns, timestamp, provider config |
| `conversation.json` | JSON | Machine-readable transcript with messages, session metadata, config, `has_card_phase`, `card_phase_data` |
| `conversation.md` | Markdown | Human-readable transcript with persona info header |
| `evaluation.json` | JSON | Scores (5-7 dimensions), `avg_score` (mean across all present dimensions, rounded to 2 decimals), dimension analysis, problems with severity/root cause, summary |
| `review.md` | Markdown | Formatted report with score bars, detailed analysis per dimension, problems |
| `problems.md` | Markdown | Problem-focused report with overview table, root cause distribution, suggested fixes |
| `run.log` | Text | Timestamped execution log from session runner |
| `error.txt` | Text | Written only on pipeline failure -- contains timestamp, error message, and traceback |

The `problems.md` report includes suggested fixes for certain root causes. The suggestion map in `_root_cause_suggestion()` covers:

| Root Cause | Suggested Fix |
|------------|---------------|
| `missed_student_signal` | Review tutor prompt handling of student cues (confusion, boredom, confidence) |
| `wrong_pacing` | Adjust pacing directive logic -- check mastery thresholds and attention span handling |
| `repetitive_approach` | Strengthen the "never repeat" teaching rule, add variety tracking |
| `emotional_mismatch` | Improve emotional attunement instructions, calibrate praise to match difficulty |
| `missed_misconception` | Enhance misconception detection, ensure tutor probes confident wrong answers |
| `over_scaffolding` | Reduce hand-holding for students showing mastery |
| `conversation_history_window` | Increase the conversation history window or improve turn summary |
| `prompt_quality` | Review and improve relevant agent prompts |
| `model_capability` | Consider testing with different models or adjusting temperature/sampling |
| `card_content_ignored` | Improve the pre-computed explanation summary injection -- tutor should actively reference card content |
| `abrupt_transition` | Replace hardcoded transition message with LLM-generated bridge that references card content |
| `card_repetition` | Strengthen the "DO NOT repeat" instruction in the precomputed explanation summary |
| `other` | Investigate specific turns to determine whether prompt, model, or architectural issue |

Multi-persona comparison (`--persona all`): `comparison_{timestamp}/comparison.md` + `comparison.json`. When `--runs-per-persona` > 1, the comparison report includes per-run detail tables and averaged scores across runs.

---

## Personas

**Location:** `autoresearch/tutor_teaching_quality/evaluation/personas/*.json`

| Persona ID | Name | Grade | Correct% | Key Trait |
|------------|------|-------|----------|-----------|
| `ace` | Arjun | 5 | 90% | Quick learner, gets bored easily |
| `average_student` | Riya | 5 | 45% | Truly average, needs simple language and concrete examples |
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
- `response_style` -- `max_words`, `language`, `uses_emoji`, `examples` for tone calibration (note: `uses_emoji` is defined in persona files but not currently read by the simulator code)
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

Supported providers: `openai` (GPT-5.2), `anthropic` (Claude Opus 4.6), `anthropic-haiku` (Claude Haiku 4.5), `claude_code` (no API key needed). When sourced via `EvalConfig.from_db()`, the haiku model id from the DB `llm_config` row is written into `evaluator_model`/`simulator_model` (the `anthropic` branch is only taken for the `"anthropic"` provider string), and `LLMService.call()` routes `anthropic-haiku` through the Anthropic client using that model id. The CLI default-constructed `EvalConfig` (without `from_db`) does not have a haiku model id set, so selecting `--provider anthropic-haiku` from the CLI will misroute (Anthropic client called with the default `gpt-5.2` model id). Prefer DB config (admin LLM config page) when using haiku.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/evaluation/personas` | List all available student personas |
| `GET` | `/api/evaluation/guidelines` | List teaching guidelines (filterable by country, board, grade, subject, status) |
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

**Note:** The `GET /api/evaluation/runs` endpoint parses run directory names to extract timestamps using the format `run_{YYYYMMDD}_{HHMMSS}`. CLI-generated multi-persona runs with persona ID suffixes (e.g., `run_20260222_143000_ace`) and comparison directories will fail timestamp parsing; these are logged as warnings on the server and omitted from the API response. Only API-generated runs (which use the plain timestamp format) and single-persona CLI runs appear in the API listing. Run directories are stored under `autoresearch/tutor_teaching_quality/evaluation/runs/`.

---

## Running an End-to-End Evaluation

### Prerequisites

1. **Database running** -- The evaluation CLI needs DB access to resolve topics and read LLM config. Ensure your local database is up (see `docs/technical/dev-workflow.md`).
2. **API keys** -- `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` must be set in `llm-backend/.env`, depending on which providers are configured for the tutor, evaluator, and simulator.
3. **Backend server running** -- The evaluation creates a real tutoring session against your running server, so the tutor being tested is whatever code is currently running.

### Step-by-step

```bash
cd llm-backend

# Step 1: Browse available topics
python -m autoresearch.tutor_teaching_quality.evaluation.run_evaluation --list-topics
python -m autoresearch.tutor_teaching_quality.evaluation.run_evaluation --list-topics --subject Mathematics

# Step 2: Start the backend server (if not already running)
python -m uvicorn main:app --port 8000 &

# Step 3: Run a single evaluation (quick check)
python -m autoresearch.tutor_teaching_quality.evaluation.run_evaluation \
  --subject Mathematics --chapter Fractions \
  --skip-server

# Step 4: Run all 8 personas for a comprehensive sweep
python -m autoresearch.tutor_teaching_quality.evaluation.run_evaluation \
  --subject Mathematics --chapter Fractions \
  --persona all --skip-server

# Step 5: Multiple runs per persona for statistical reliability
python -m autoresearch.tutor_teaching_quality.evaluation.run_evaluation \
  --subject Mathematics --chapter Fractions \
  --persona all --runs-per-persona 3 --skip-server
```

### What happens

1. The CLI resolves your `--subject`/`--chapter`/`--topic` to a guideline ID from the database
2. Creates a tutoring session via `POST /sessions` (the tutor doesn't know it's being evaluated)
3. If the topic has pre-computed explanation cards, the runner reads them, adds to transcript, and calls `/card-action` to transition to interactive teaching
4. A simulated student persona converses with the tutor over WebSocket (up to `--max-turns` turns)
5. An LLM judge evaluates the transcript on 5-7 dimensions (1-10 each) and identifies problems
6. Reports are saved to `autoresearch/tutor_teaching_quality/evaluation/runs/run_<timestamp>/`

### Output files (per run)

| File | Contents |
|------|----------|
| `config.json` | Run configuration (topic, models, persona) |
| `conversation.json` | Machine-readable transcript |
| `conversation.md` | Human-readable transcript |
| `evaluation.json` | Scores, dimension analysis, problems |
| `review.md` | Formatted evaluation report with score bars |
| `problems.md` | Problem-focused report with root cause suggestions |
| `run.log` | Timestamped execution log |

For `--persona all` runs, a `comparison_<timestamp>/` directory is also created with `comparison.md` (cross-persona summary table) and `comparison.json`.

### Comparing before/after code changes

1. Run evaluation **before** your change -- note the run directory name
2. Make your tutor code changes and restart the server
3. Run evaluation **after** your change with the same topic and personas
4. Compare `evaluation.json` scores between the two run directories

### CLI reference

| Argument | Default | Description |
|----------|---------|-------------|
| `--subject` | -- | Subject name, e.g., `Mathematics` (case-insensitive) |
| `--chapter` | -- | Chapter name, e.g., `Fractions` (optional, narrows match) |
| `--topic` | -- | Topic name, e.g., `Comparing Like Denominators` (optional) |
| `--topic-id` | -- | Guideline ID directly (alternative to name-based lookup) |
| `--list-topics` | -- | List available topics and exit |
| `--persona` | `average_student.json` | Persona file or `all` for all 8 personas |
| `--runs-per-persona` | 1 | Runs per persona for noise reduction (only with `--persona all`) |
| `--skip-server` | false | Use already-running server (recommended) |
| `--max-turns` | 20 | Max conversation turns |
| `--grade` | 3 | Student grade |
| `--provider` | (from DB/env) | LLM provider override for evaluator and simulator |

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
  - "Evaluate Existing Session" -- dropdown of sessions from DB (shows topic, message count, date); warns if the selected session has zero messages
  - "New Simulated Session" -- dropdown of approved guidelines (filtered by `status=APPROVED`), student persona dropdown (loaded from `GET /api/evaluation/personas`, auto-selects `average_student.json` as default), max turns slider (5-40). The start request sends `persona_file` alongside `topic_id` and `max_turns`.
- **Detail view** -- full scores, expandable dimension analysis, overall summary, problems with evidence, conversation transcript with markdown rendering
- **Status polling** -- 2-second polling interval while evaluation is running, auto-refreshes runs list on completion

The frontend `DIMENSIONS` constant hardcodes the 5 core evaluation dimensions: responsiveness, explanation_quality, emotional_attunement, pacing, authenticity. Card-phase dimensions (card_to_session_coherence, transition_quality) are **not shown** in the dashboard even when present in evaluation data. Model badges in the detail view read from `tutor_llm_provider` and `eval_llm_provider` fields in the run's saved `config.json` and map them to display labels. Note that `eval_llm_provider` is the legacy provider field (default from `EVAL_LLM_PROVIDER` env var), not the per-component `evaluator_provider` field -- when evaluator and simulator providers are set independently via DB config, the badge may show the legacy default rather than the actual evaluator provider. The tutor badge maps `openai` to "GPT-5.2", `anthropic` to "Claude Opus 4.6", and `anthropic-haiku` to "Claude Haiku 4.5". The evaluator badge maps only `openai` to "GPT-5.2" and `anthropic` to "Claude Opus 4.6" (no `anthropic-haiku` or `claude_code` mapping). The backend retry-evaluation endpoint (`POST /runs/{id}/retry-evaluation`) exists but is **not wired** to the frontend -- re-evaluation can only be triggered via direct API call.

---

## Autoresearch Integration

**File:** `autoresearch/tutor_teaching_quality/run_experiment.py`

The autoresearch loop reuses this pipeline as its fixed evaluator (analogous to `prepare.py` in DSPy). One command produces a composite quality score for the current commit.

- Wraps `EvalConfig.from_db()` + `StudentSimulator` + `SessionRunner` + `ConversationEvaluator` + `ReportGenerator`
- Default persona: `average_student.json` only (`DEFAULT_PERSONAS`); `--quick` shortens to `QUICK_MAX_TURNS=12`
- Default `--runs=2` averages across stochastic simulator variance (~0.6 single-run noise → ~0.35 with 3 runs)
- Run directories are named `autoresearch_{timestamp}_{persona_id}` to distinguish from manual runs
- `--restart-server` flag triggers `SessionRunner(restart_server=True)` so iterative tutor-prompt edits take effect each run
- Appends a row to `autoresearch/tutor_teaching_quality/results.tsv` (`commit \t avg_score \t elapsed_min \t status \t description \t scores_json`)
- Optional `--email` invokes `autoresearch/tutor_teaching_quality/email_report.py` for HTML iteration reports
- Topic resolution: `AUTORESEARCH_TOPIC_ID` env var overrides; otherwise DB lookup by `--subject`/`--chapter` (defaults: Mathematics / Fractions)

Used by the autoresearch agent (see `docs/technical/auto-research/overview.md`) to score prompt edits.

---

## Key Files

| File | Purpose |
|------|---------|
| `autoresearch/tutor_teaching_quality/evaluation/config.py` | `EvalConfig` dataclass, persona loading, paths, DB config integration |
| `autoresearch/tutor_teaching_quality/evaluation/student_simulator.py` | LLM-powered student with persona-driven behavior and per-turn correctness enforcement |
| `autoresearch/tutor_teaching_quality/evaluation/session_runner.py` | Session lifecycle: REST creation, card phase handling, WebSocket conversation, server management |
| `autoresearch/tutor_teaching_quality/evaluation/evaluator.py` | LLM judge with 7-dimension persona-aware rubric (5 core + 2 card-phase), structured JSON output |
| `autoresearch/tutor_teaching_quality/evaluation/report_generator.py` | Markdown + JSON report generation, card-phase-aware reports, comparison reports |
| `autoresearch/tutor_teaching_quality/evaluation/run_evaluation.py` | CLI entry point, single-persona and multi-persona orchestration |
| `autoresearch/tutor_teaching_quality/evaluation/api.py` | FastAPI endpoints, background thread execution, status polling, session evaluation |
| `autoresearch/tutor_teaching_quality/evaluation/personas/*.json` | 8 student persona definitions (`ace`, `average_student`, `confused_confident`, `distractor`, `quiet_one`, `repetition_detector`, `simplicity_seeker`, `struggler`) |
| `autoresearch/tutor_teaching_quality/evaluation/prompts/evaluator.txt` | LLM judge system prompt with 5 core dimension rubrics, persona-aware criteria, and JSON output schema templates |
| `autoresearch/tutor_teaching_quality/evaluation/prompts/card_phase_dimensions.txt` | Two card-phase dimension rubrics, spliced into evaluator prompt only when cards present |
| `autoresearch/tutor_teaching_quality/run_experiment.py` | Autoresearch experiment runner — wraps the eval pipeline, averages multiple runs, appends to `results.tsv`, optional email report |
| `autoresearch/tutor_teaching_quality/results.tsv` | Append-only experiment log: commit, avg_score, elapsed_min, status, description, scores_json |
| `llm-frontend/src/features/admin/pages/EvaluationDashboard.tsx` | Evaluation UI: run list, detail view, start form, status polling |
| `llm-frontend/src/features/admin/api/adminApi.ts` | API client functions for evaluation endpoints |
| `llm-frontend/src/features/admin/types/index.ts` | TypeScript types for evaluation data (`EvalRunSummary`, `EvalRunDetail`, `EvalStatus`, `EvalProblem`, `EvalResult`, `EvalPersona`) |
