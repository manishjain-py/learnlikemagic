# Evaluation — Technical

Pipeline architecture for automated tutor quality measurement using persona-driven simulation and LLM judging.

---

## Pipeline Architecture

```
Load Persona (JSON)
    │
    v
Create Session (REST: POST /sessions)
    │
    v
Run Simulation (WebSocket: /sessions/ws/{id})
    │  Student Simulator ←→ Tutor
    v
LLM Judge Evaluates (5 persona-aware dimensions)
    │
    v
Generate Reports (JSON + Markdown artifacts)
```

---

## Student Simulator

**File:** `evaluation/student_simulator.py`

`StudentSimulator` builds a system prompt from persona traits and uses an LLM to roleplay as the student.

- `correct_answer_probability` is **programmatically enforced** — each turn, a random roll determines correct/incorrect, then injects explicit directives to the LLM
- Persona-specific behaviors fire probabilistically (e.g., `boredom_probability: 0.3`)
- Models: GPT-4o or Claude Opus 4.6

---

## Session Runner

**File:** `evaluation/session_runner.py`

- Creates tutoring session via `POST /sessions` REST endpoint
- Runs conversation loop over WebSocket (`/sessions/ws/{session_id}`)
- Uses the **same protocol real students use**
- Captures all messages with timestamps, turn numbers, and roles
- Configurable max turns (default: 20)

---

## LLM Judge

**File:** `evaluation/evaluator.py`

`ConversationEvaluator` sends full transcript to LLM judge and evaluates across 5 persona-aware dimensions.

### 5 Evaluation Dimensions (scored 1-10)

1. **Responsiveness** — Does the tutor adapt to student signals?
2. **Explanation Quality** — Does the tutor explain well and try different approaches?
3. **Emotional Attunement** — Does the tutor read the room emotionally?
4. **Pacing** — Is the tutor moving at the right speed for this student?
5. **Authenticity** — Does it feel like a real teacher or a chatbot?

The same tutor behavior is judged differently based on the student persona.

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

### Evaluator Models

| Provider | Model | Config |
|----------|-------|--------|
| OpenAI | GPT-5.2 | reasoning effort: `high` |
| Anthropic | Claude Opus 4.6 | 20,000 token thinking budget |

Set via `EVAL_LLM_PROVIDER` env var (defaults to `anthropic`).

---

## Report Generator

**File:** `evaluation/report_generator.py`

Each run creates: `evaluation/runs/run_{YYYYMMDD}_{HHMMSS}_{persona_id}/`

| File | Format | Contents |
|------|--------|----------|
| `config.json` | JSON | Topic ID, tutor model, evaluator model, persona, max turns, timestamp |
| `conversation.json` | JSON | Machine-readable transcript |
| `conversation.md` | Markdown | Human-readable transcript |
| `evaluation.json` | JSON | Scores (5 dimensions + avg), problems with severity/root cause |
| `review.md` | Markdown | Formatted report with score bars and analysis |
| `problems.md` | Markdown | Problem-focused report with root cause distribution |
| `run.log` | Text | Timestamped execution log |

Multi-persona comparison (`--persona all`): `comparison_{timestamp}/comparison.md` + `comparison.json`

---

## Personas

**Location:** `evaluation/personas/*.json`

| Persona ID | Name | Correct% | Key Trait |
|------------|------|----------|-----------|
| `ace` | Arjun | 90% | Quick learner, gets bored easily |
| `average_student` | Riya | 60% | Attentive but confused by new concepts |
| `confused_confident` | Dev | 45% | Confident wrong answers |
| `distractor` | Kabir | 65% | Bright but scattered, goes off-topic |
| `quiet_one` | Meera | 60% | Shy, minimal responses |
| `repetition_detector` | Vikram | 70% | Notices repetitive patterns |
| `simplicity_seeker` | Aanya | 50% | Easily overwhelmed |
| `struggler` | Priya | 30% | Hardworking but confused |

Each persona includes: `correct_answer_probability`, `personality_traits`, `common_mistakes`, `response_style`, `persona_specific_behaviors`.

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

Status response during a run:
```json
{
  "status": "idle|loading_persona|running_session|evaluating|generating_reports|complete|failed",
  "run_id": "run_...",
  "detail": "Turn 5/20",
  "turn": 5,
  "max_turns": 20
}
```

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
| `--runs-per-persona` | 1 | Runs per persona for noise reduction |
| `--skip-server` | false | Use already-running server |
| `--max-turns` | 20 | Max conversation turns |
| `--grade` | 3 | Student grade |
| `--provider` | (from env) | Evaluator LLM provider |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_LLM_PROVIDER` | `openai` | Tutor provider |
| `EVAL_LLM_PROVIDER` | `anthropic` | Evaluator provider |
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `ANTHROPIC_API_KEY` | `""` | Anthropic API key |

---

## Key Files

| File | Purpose |
|------|---------|
| `evaluation/config.py` | EvalConfig, persona loading, paths |
| `evaluation/student_simulator.py` | LLM-powered student with persona-driven behavior |
| `evaluation/session_runner.py` | Session lifecycle: REST creation, WebSocket conversation |
| `evaluation/evaluator.py` | LLM judge with 5-dimension persona-aware rubric |
| `evaluation/report_generator.py` | Markdown + JSON report generation |
| `evaluation/run_evaluation.py` | CLI entry point, multi-persona orchestration |
| `evaluation/api.py` | FastAPI endpoints, background execution |
| `evaluation/personas/*.json` | 8 student persona definitions |
| `llm-frontend/src/features/admin/pages/EvaluationDashboard.tsx` | Evaluation UI |
| `llm-frontend/src/features/admin/api/adminApi.ts` | API client |
