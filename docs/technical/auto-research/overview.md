# Auto-Research: Autonomous Tutor Prompt Optimization

Technical documentation for the autoresearch system — an autonomous AI-driven
research loop that iteratively improves tutor prompts.

---

## Concept

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch), which
lets an AI agent autonomously experiment with LLM training code (modify code → train
5 min → check metric → keep/discard → repeat). We apply the same pattern to tutor
prompt optimization:

```
Agent modifies tutor prompts
    → Runs evaluation (simulated session + LLM judge)
    → Score improves? Keep. Worse? Discard.
    → Repeat indefinitely.
```

The human doesn't edit prompts directly. Instead, the human writes `program.md` —
instructions for the AI researcher. The agent does the prompt engineering autonomously.

---

## Architecture

```
autoresearch/
├── program.md           # Agent instructions (the human edits this)
├── run_experiment.py    # Experiment runner (produces a single score)
├── email_report.py      # Sends compact email reports per iteration
└── results.tsv          # Experiment log (created at runtime)
```

### How It Maps to Karpathy's Design

| Karpathy's Autoresearch | Our Autoresearch |
|--------------------------|------------------|
| `train.py` (agent modifies) | `tutor/prompts/master_tutor_prompts.py` |
| `prepare.py` (fixed eval) | `evaluation/` pipeline (evaluator + personas) |
| `program.md` (human writes) | `autoresearch/program.md` |
| `val_bpb` (metric) | Composite eval score (avg across 5 dimensions, 1-10) |
| 5 min training budget | ~5-8 min per experiment (1 session + evaluation) |
| ~12 experiments/hour | ~8-10 experiments/hour |

---

## Target Persona: The Average Student

We optimize for a single persona: **Riya** — a Grade 5 CBSE student with average IQ.

This is a deliberate design decision. When we launch, the students who need our app
the most are average students: kids who CAN learn but need concepts broken down into
simple, concrete steps. If the tutor works well for Riya, it works well for our
primary audience.

### Riya's Profile

| Attribute | Value |
|-----------|-------|
| Grade | 5 (CBSE) |
| Age | 10 |
| Correct answer rate | 45% |
| Language | Simple English with Hindi words mixed in |
| Key need | Very simple explanations, everyday examples, patient repetition |

### Key Behaviors the Tutor Must Handle

1. **False OKs** — Says "hmm ok" without really understanding (35% of the time)
2. **Random guessing** — Guesses when confused instead of asking for help (25%)
3. **Disengagement** — Goes quiet after repeated failure (60% after 3+ wrong)
4. **Breakthrough excitement** — Lights up when something clicks (80%)
5. **Pattern copying** — Repeats tutor's words without understanding
6. **Memorization over understanding** — Memorizes steps without grasping WHY

### Persona File

`evaluation/personas/average_student.json` — full persona definition used by the
student simulator during evaluation.

---

## Evaluation Metric

### 5 Dimensions (1-10 each)

| Dimension | What It Measures (for Riya) |
|-----------|---------------------------|
| **Responsiveness** | Does the tutor detect when Riya says "ok" without understanding? Does it probe when she guesses randomly? |
| **Explanation Quality** | Simple enough language? Everyday examples (roti, cricket, pocket money)? Tries different approaches when she's stuck? |
| **Emotional Attunement** | Patient when she gets things wrong? Calibrated encouragement? Genuine on breakthroughs? |
| **Pacing** | Slow enough for Riya? Frequent check-ins? Doesn't confuse "she said ok" with "she gets it"? |
| **Authenticity** | Feels like a real teacher who cares, not a chatbot running a script? |

### Composite Score

```
composite = (responsiveness + explanation_quality + emotional_attunement + pacing + authenticity) / 5
```

### Evaluation Pipeline

1. **Student Simulator** (`evaluation/student_simulator.py`) — An LLM roleplaying as
   Riya. Correct/incorrect answers are programmatically controlled via dice rolls
   against the persona's `correct_answer_probability` (45%).

2. **Session Runner** (`evaluation/session_runner.py`) — Creates a session via REST API,
   runs the full tutoring conversation over WebSocket (20 turns max).

3. **LLM Judge** (`evaluation/evaluator.py`) — An LLM (GPT-5.2 or Claude Opus) reads
   the full transcript and scores it across the 5 dimensions. Persona-aware: the same
   tutor behavior scores differently depending on the student type.

4. **Report Generator** (`evaluation/report_generator.py`) — Saves conversation transcript,
   evaluation JSON, and formatted reports to the run directory.

---

## Experiment Loop

### Single Iteration (~5-8 minutes)

```
1. Agent reads evaluation feedback from previous run
2. Forms hypothesis: "If I change X in the prompt, dimension Y should improve"
3. Edits tutor/prompts/master_tutor_prompts.py (ONE focused change)
4. git commit
5. Runs: ./venv/bin/python -m autoresearch.run_experiment --skip-server
6. Reads result: avg_score from output
7. avg_score improved? → KEEP (advance branch)
   avg_score worse?   → DISCARD (git reset --hard HEAD~1)
8. Logs to results.tsv
9. Emails compact report
10. Repeat
```

### Throughput

| Metric | Value |
|--------|-------|
| Time per experiment | ~5-8 min (1 persona × 20 turns + eval) |
| Experiments per hour | ~8-10 |
| Experiments overnight (8 hrs) | ~60-80 |

### Keep/Discard Rules

- Score improved (even by 0.01) → **KEEP**
- Score equal or worse → **DISCARD** (git reset)
- Simplicity tiebreak: removing code that gets equal score = KEEP (simplification win)
- Dimension exception: significant improvement in one dimension without hurting others = KEEP

---

## Modifiable Surface

### Primary: `tutor/prompts/master_tutor_prompts.py`

Contains `MASTER_TUTOR_SYSTEM_PROMPT` and `MASTER_TUTOR_TURN_PROMPT`. Everything in
these templates is fair game:
- Teaching rules (currently 13 rules)
- Tone and language instructions
- Formatting guidance
- Pacing directives
- Explanation phase tracking

### Secondary (after several primary iterations):
- `tutor/prompts/clarify_doubts_prompts.py`
- `tutor/prompts/orchestrator_prompts.py`

### Read-Only (never modify):
- `evaluation/` — Fixed metric
- `tutor/agents/`, `tutor/models/`, `tutor/services/` — Application code
- `autoresearch/run_experiment.py`, `autoresearch/email_report.py` — Runner code

---

## Email Reports

Each iteration sends a compact HTML email with:
- Iteration number, status (KEEP/DISCARD/CRASH), description
- Current score vs baseline (with +/- delta)
- Per-dimension score breakdown (current vs baseline)
- Top 5 problems identified by the evaluator
- Prompt diff (truncated to 2000 chars)

Requires `SMTP_USER` and `SMTP_PASSWORD` env vars (Gmail app password).

---

## Running It

### Prerequisites

1. Backend server running: `./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000`
2. `AUTORESEARCH_TOPIC_ID` set in `.env` (or resolvable via DB)
3. `SMTP_USER` and `SMTP_PASSWORD` in env (for email reports)

### Launch

Point an AI coding agent (Claude Code, Codex, etc.) at the repo and prompt:

```
Read autoresearch/program.md and let's kick off a new experiment!
Email reports to <your-email>.
```

The agent handles everything autonomously from there.

### Monitor

- Check email on your phone for per-iteration reports
- Review `autoresearch/results.tsv` for the full experiment log
- Browse `evaluation/runs/autoresearch_*` directories for detailed transcripts

---

## Results Format

`autoresearch/results.tsv` (tab-separated):

```
commit  avg_score  elapsed_min  status   description                        scores_json
a1b2c3d 6.8000     7.2          baseline baseline                           {"responsiveness": 7, ...}
b2c3d4e 7.0000     6.8          keep     simplify explanation language rules {"responsiveness": 7.5, ...}
c3d4e5f 6.7000     7.1          discard  remove all formatting guidance     {"responsiveness": 6, ...}
```

---

## Key Design Decisions

### Why one persona?

Speed and focus. Each additional persona adds ~5-8 minutes per experiment. With one
persona we get ~10 experiments/hour. With three, we'd get ~3/hour. Since our primary
goal is optimizing for the average student (our core audience at launch), one persona
gives us faster iteration cycles and a clearer signal.

### Why not optimize the evaluation code too?

Same reason autoresearch keeps `prepare.py` fixed: the evaluation is the ground truth.
If you optimize both the prompts AND the evaluation, you don't know if you're actually
improving or just gaming the metric. Fixed evaluation = honest signal.

### Why prompts only, not code?

Prompts are the highest-leverage surface for teaching quality. The orchestration code
handles mechanics (state management, step advancement, etc.) — the prompts control
the actual teaching behavior. Prompt changes are also safe to experiment with: they
can't break the application, only change the LLM's output quality.
