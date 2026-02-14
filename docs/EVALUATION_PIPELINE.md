# Evaluation Pipeline

---

## Document Purpose

**Dedicated reference** for the automated evaluation/QA pipeline that measures tutor teaching quality.

| Aspect | Details |
|--------|---------|
| **What it captures** | End-to-end evaluation flow: persona simulation, session execution, LLM judging, report generation, viewing results |
| **Audience** | Developers working on evaluation, tutor prompt improvements, or QA |
| **Scope** | Student simulator, evaluator, report artifacts, frontend dashboard, API, CLI |
| **Maintenance** | Update when evaluation code changes |

**Key Code Locations:**
- Backend: `llm-backend/evaluation/` (config, simulator, runner, evaluator, reporter, API, personas)
- Frontend: `llm-frontend/src/features/admin/pages/EvaluationDashboard.tsx`
- API client: `llm-frontend/src/features/admin/api/adminApi.ts`

---

## Architecture Overview

The evaluation pipeline is an **automated QA system** that simulates tutoring sessions with AI-powered student personas and evaluates the tutor's teaching quality using an LLM judge.

```
Load Persona (JSON) -> Create Session (REST) -> Run Simulation (WebSocket) -> LLM Judge Evaluates -> Generate Reports
```

```
+-------------------+     +------------------+     +-------------------+
|  Student Persona  |     |  Session Runner  |     |    Evaluator      |
|  (JSON config)    |---->|  (REST + WS)     |---->|  (LLM Judge)      |
|                   |     |                   |     |                   |
|  - personality    |     |  Creates session  |     |  5 dimensions     |
|  - correct_prob   |     |  via POST /sessions|    |  Problem ID       |
|  - behaviors      |     |  Chats via WS     |     |  Root causes      |
+-------------------+     +------------------+     +-------------------+
                                                          |
                                                          v
                                                   +-------------------+
                                                   | Report Generator  |
                                                   |                   |
                                                   | evaluation.json   |
                                                   | review.md         |
                                                   | problems.md       |
                                                   | conversation.md   |
                                                   +-------------------+
```

---

## Pipeline Steps

### Step 1: Persona Loading

- Location: `evaluation/config.py`, `evaluation/personas/*.json`
- Loads persona JSON defining student behavior, personality, and correct answer probability
- Creates `EvalConfig` with server settings, topic ID, max turns, LLM providers

### Step 2: Student Simulation

- Location: `evaluation/student_simulator.py`
- `StudentSimulator` builds a system prompt from persona traits
- Uses GPT-4o or Claude Opus 4.6 to roleplay as the student
- `correct_answer_probability` is **programmatically enforced** — each turn, a random roll determines correct/incorrect, then injects explicit directives to the LLM

### Step 3: Session Execution

- Location: `evaluation/session_runner.py`
- Creates tutoring session via `POST /sessions` REST endpoint
- Runs conversation loop over WebSocket (`/sessions/ws/{session_id}`)
- Uses the **same protocol real students use**
- Captures all messages with timestamps, turn numbers, and roles
- Configurable max turns (default: 20)

### Step 4: Evaluation

- Location: `evaluation/evaluator.py`
- `ConversationEvaluator` sends full transcript to LLM judge
- Scores across 5 persona-aware teaching-craft dimensions (1-10 scale)
- Identifies top 5 problems with severity and root causes
- Evaluation criteria adapt based on student persona

### Step 5: Report Generation

- Location: `evaluation/report_generator.py`
- Generates multiple output files per run in `evaluation/runs/run_{timestamp}_{persona}/`

---

## 5 Evaluation Dimensions (Persona-Aware)

Each dimension scored 1-10. The same tutor behavior is judged differently based on the student persona.

### 1. Responsiveness
*Does the tutor adapt to student signals?*

Persona-specific examples:
- **Ace students:** Did tutor notice mastery and skip ahead?
- **Struggling students:** Did tutor try different approaches when first explanation failed?
- **Quiet students:** Did tutor notice minimal responses and draw them out?
- **Distracted students:** Did tutor handle tangents gracefully?
- **Confused-but-confident:** Did tutor probe confident wrong answers?

### 2. Explanation Quality
*Does the tutor explain well and try different approaches when needed?*

### 3. Emotional Attunement
*Does the tutor read the room emotionally?*

### 4. Pacing
*Is the tutor moving at the right speed for this student?*

### 5. Authenticity
*Does this feel like a real teacher or a chatbot?*

---

## Problem Identification

Each evaluation identifies **top 5 problems** with:

| Field | Description |
|-------|-------------|
| `title` | Short problem description |
| `turns` | Which conversation turns exhibited the problem |
| `description` | What went wrong in context of this persona |
| `quote` | Exact evidence from conversation |
| `severity` | `critical` / `major` / `minor` |
| `root_cause` | One of the root cause categories below |

### Root Cause Categories

| Root Cause | Description |
|------------|-------------|
| `missed_student_signal` | Didn't pick up on student cues |
| `wrong_pacing` | Too fast/slow for this student |
| `repetitive_approach` | Tried same thing when not working |
| `emotional_mismatch` | Wrong tone/energy |
| `missed_misconception` | Didn't catch underlying confusion |
| `over_scaffolding` | Too structured |
| `conversation_history_window` | Lost earlier context |
| `prompt_quality` | Tutor prompt needs improvement |
| `model_capability` | LLM limitation |
| `other` | Other |

---

## Student Personas

Location: `evaluation/personas/*.json`

| Persona ID | Name | Correct% | Key Trait |
|------------|------|----------|-----------|
| `ace` | Arjun | 90% | Quick learner, gets bored easily, asks for harder problems |
| `average_student` | Riya | 60% | Attentive but sometimes confused, relates to food/games |
| `confused_confident` | Dev | 45% | Confident wrong answers, systematic misconceptions |
| `distractor` | Kabir | 65% | Bright but scattered, goes off-topic |
| `quiet_one` | Meera | 60% | Shy, minimal responses, needs to be drawn out |
| `struggler` | Priya | 30% | Hardworking but confused, asks for help |

Each persona includes:
- `correct_answer_probability` — programmatically enforced
- `personality_traits` — behavioral characteristics
- `common_mistakes` — specific errors this student makes
- `response_style` — max words, language register
- `persona_specific_behaviors` — probability-driven tendencies (e.g., `boredom_probability: 0.3`)

---

## Evaluator Models

| Provider | Model | Config |
|----------|-------|--------|
| OpenAI | GPT-5.2 | reasoning effort: `high` |
| Anthropic | Claude Opus 4.6 | 20,000 token thinking budget |

Set via `EVAL_LLM_PROVIDER` env var (defaults to `anthropic`).

---

## Output Artifacts

Each run creates: `evaluation/runs/run_{YYYYMMDD}_{HHMMSS}_{persona_id}/`

| File | Format | Contents |
|------|--------|----------|
| `config.json` | JSON | Topic ID, tutor model, evaluator model, persona file, max turns, timestamp, source |
| `conversation.json` | JSON | Machine-readable transcript with message count, roles, turn numbers, timestamps |
| `conversation.md` | Markdown | Human-readable transcript with turn numbers and persona info |
| `evaluation.json` | JSON | Scores (5 dimensions + avg), dimension analysis, problems with severity/root cause, summary |
| `review.md` | Markdown | Formatted evaluation report with score bars, analysis per dimension, top problems |
| `problems.md` | Markdown | Problem-focused report: overview table, root cause distribution, detailed descriptions with fixes |
| `run.log` | Text | Timestamped execution log: simulator decisions, turn timing |

### Multi-Persona Comparison

When using `--persona all`, an additional directory is created: `comparison_{YYYYMMDD}_{HHMMSS}/`

| File | Contents |
|------|----------|
| `comparison.md` | Markdown table comparing all personas side-by-side |
| `comparison.json` | Raw comparison data with all results |

---

## How to Trigger Evaluations

### CLI (Manual)

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
| `--persona` | average_student.json | Persona file or `all` for all personas |
| `--runs-per-persona` | 1 | Runs per persona for noise reduction |
| `--skip-server` | false | Use already-running server |
| `--max-turns` | 20 | Max conversation turns |
| `--grade` | 3 | Student grade |
| `--provider` | (from env) | LLM provider for evaluator: `openai` or `anthropic` |

### REST API (Programmatic)

```
POST /api/evaluation/start
Body: { "topic_id": "<guideline_id>", "persona_file": "ace.json", "max_turns": 20 }
```

### Frontend Admin Dashboard (UI)

Route: `/admin/evaluation`

Two evaluation modes:
1. **Evaluate Existing Session** — select from real tutoring sessions in database
2. **New Simulated Session** — choose guideline + persona + max turns

---

## How to View Results

### 1. Admin Dashboard (Primary UI)

Route: `/admin/evaluation`

**List View:**
- All evaluation runs with run ID, timestamp, topic
- Color-coded average score badge (green >= 7, yellow >= 4, red < 4)
- Message count, source indicator (Simulated vs Session)
- Mini score bars showing all 5 dimensions

**Detail View** (click any run):
- Full conversation transcript (chat bubble UI)
- Score bars for all 5 dimensions (expandable to show analysis)
- Overall assessment summary
- Problems list with severity badges
- Configuration details (tutor model, evaluator model)

**Live Status Banner:**
- Real-time polling during evaluation
- Shows current status, turn progress, run ID
- Auto-refreshes list when complete

### 2. REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/evaluation/runs` | List all run summaries with scores |
| `GET` | `/api/evaluation/runs/{run_id}` | Full run detail (config, messages, evaluation) |
| `GET` | `/api/evaluation/status` | Live polling status during evaluation |
| `POST` | `/api/evaluation/evaluate-session` | Evaluate an existing real session from DB |
| `POST` | `/api/evaluation/runs/{run_id}/retry-evaluation` | Re-run evaluation on existing conversation |

Status response during a run:
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

### 3. Direct File Access

Browse `llm-backend/evaluation/runs/` directly:
- `review.md` — comprehensive formatted report
- `problems.md` — action-oriented problem list
- `evaluation.json` — raw scores for programmatic analysis
- `conversation.md` — readable transcript

### 4. CLI Output

Results are printed to console after a run:
```
RESULTS
  Average Score: 7.4/10
  Problems Found: 5

  Scores:
    Responsiveness................... 8/10
    Explanation Quality.............. 8/10
    Emotional Attunement............. 7/10
    Pacing........................... 6/10
    Authenticity..................... 8/10

  Top Problems:
    1. [MAJOR] Difficulty ceiling never reached
       Root cause: wrong_pacing
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_LLM_PROVIDER` | `openai` | Tutor provider: `openai`, `anthropic`, `anthropic-haiku` |
| `EVAL_LLM_PROVIDER` | `anthropic` | Evaluator provider (defaults to `anthropic`) |
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `ANTHROPIC_API_KEY` | `""` | Anthropic API key |

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `evaluation/config.py` | EvalConfig, persona loading, paths |
| `evaluation/student_simulator.py` | LLM-powered student with persona-driven behavior |
| `evaluation/session_runner.py` | Session lifecycle: REST creation, WebSocket conversation |
| `evaluation/evaluator.py` | LLM judge with 5-dimension persona-aware rubric |
| `evaluation/report_generator.py` | Markdown + JSON report generation |
| `evaluation/run_evaluation.py` | CLI entry point, multi-persona orchestration |
| `evaluation/api.py` | FastAPI endpoints, background execution |
| `evaluation/personas/*.json` | 6 student persona definitions |
| `llm-frontend/src/features/admin/pages/EvaluationDashboard.tsx` | Full evaluation UI |
| `llm-frontend/src/features/admin/api/adminApi.ts` | API client for evaluation endpoints |
