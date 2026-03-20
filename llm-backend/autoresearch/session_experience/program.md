# Autoresearch: Session Experience Optimization

Autonomous research loop for improving the naturalness and flow of the
complete "teach me" session from the student's perspective.

## How This Differs From tutor_teaching_quality

The `tutor_teaching_quality` pipeline asks: **"Is the tutor good at teaching?"**
It scores 7 quality dimensions (responsiveness, pacing, authenticity, etc.).

This pipeline asks: **"Does this conversation feel natural and appropriate for
an average student?"** It flags specific messages that break the flow, then
traces those issues back to the exact prompt instructions that caused them.

| | tutor_teaching_quality | session_experience |
|---|---|---|
| Evaluates | Tutor quality (7 dimensions) | Conversation naturalness |
| Granularity | Dimension scores (1-10) | Message-level flags |
| Topics | Single topic | Rotating 3 topics per iteration |
| Root cause | Score-based hypothesis | Prompt instruction tracing |
| Metric | Avg dimension score | Naturalness score + weighted issue count |

## The Core Question

**Does this entire session — from the welcome message through every exchange —
feel like a natural conversation between a patient tutor and an average student?**

The student is 8-12 years old, average or below-average, needs simple language,
gets overwhelmed easily, won't say they're confused, and represents the kid who
needs an AI tutor most.

## How It Works

Three stages per iteration:

### Stage 1: SIMULATE
Run full teach-me sessions (welcome → cards → interactive → end) across
3 topics from a rotating pool. Capture:
- Full conversation transcript
- Master tutor prompts (via agent-logs API) for each tutor response

### Stage 2: EVALUATE
A naturalness judge reads each full conversation and flags specific tutor
messages that feel unnatural. For each flagged message:
- Turn number and snippet
- Issue category (forced_transition, overwhelming, complexity_mismatch, etc.)
- Severity (critical/major/minor)
- Why it feels wrong in context

### Stage 3: ANALYZE
For each flagged message, a prompt analyzer receives the flagged message +
the exact master tutor prompt that generated it. It traces the issue to
specific prompt instructions and suggests fixes.

## Setup

1. **Branch**: `git checkout -b autoresearch/session-exp-<tag>` from current branch.
2. **Read files**:
   - `autoresearch/session_experience/program.md` — this file
   - `autoresearch/session_experience/run_experiment.py` — the runner
   - **Modifiable surface** (see below) — read ALL
   - `autoresearch/session_experience/evaluation/experience_evaluator.py` — the naturalness judge
   - `autoresearch/session_experience/evaluation/prompt_analyzer.py` — root cause tracer
3. **Server**: `curl -s http://localhost:8000/health/db` should return OK.
4. **Run baseline**:
   ```bash
   ./venv/bin/python -m autoresearch.session_experience.run_experiment \
       --skip-server --description "baseline" --iteration 0 \
       --email <email>
   ```

## Modifiable Surface

Same as tutor_teaching_quality — anything that shapes the teaching experience.

### TIER 1 — Primary Targets

**`tutor/prompts/master_tutor_prompts.py`** — Teaching rules, system/turn prompts
**`tutor/agents/master_tutor.py`** — Prompt assembly, pacing directives, card summary
**`tutor/services/session_service.py`** — Transition message, card summary builder

### DO NOT MODIFY

- `autoresearch/session_experience/evaluation/` — Ground truth
- `autoresearch/session_experience/run_experiment.py`, `email_report.py`
- `autoresearch/tutor_teaching_quality/` — Separate pipeline
- `tutor/models/`, `tutor/api/`, `shared/`

## The Metrics

**Two metrics, both must improve:**

1. **Naturalness Score (1-10, higher is better)** — Overall conversation naturalness
   averaged across all topics in the iteration.

2. **Weighted Issue Count (lower is better)** — Sum across all topics:
   `critical × 3 + major × 2 + minor × 1`

**Keep threshold**: Naturalness improves by ≥0.2 OR weighted issues decrease by ≥1,
without the other metric getting significantly worse.

## Issue Categories

The naturalness judge flags messages in these categories:
- `forced_transition` — Unnatural shift between phases/topics
- `overwhelming` — Too much info for an average student
- `unnatural_language` — Chatbot-like, not human
- `complexity_mismatch` — Words/concepts too advanced
- `emotional_disconnect` — Praise/tone doesn't match the moment
- `repetitive_pattern` — Same structure every response
- `abrupt_shift` — Ignoring what student said
- `card_disconnect` — Not connecting to explanation cards
- `robotic_structure` — Every response = praise → teach → question
- `false_ok_missed` — Student's vague "ok" not probed
- `information_dump` — Wall of text
- `premature_advance` — Moving on before student is ready

## The Experiment Loop

LOOP FOREVER:

1. **Read results**: Check `results.tsv`, read latest review.md files.

2. **Identify the biggest problem**: Look at the flagged messages and prompt
   analysis. Focus on the most frequent or highest-severity issue category.

3. **Read the prompt analysis**: The analyzer tells you WHICH instruction
   caused WHICH problem. Use this as your guide.

4. **Make ONE change**: Edit the prompt/agent/service code. Small and focused.
   `git commit` the change.

5. **Run experiment**:
   ```bash
   ./venv/bin/python -m autoresearch.session_experience.run_experiment \
       --restart-server --description "what this tries" \
       --iteration <N> --email <email> > run.log 2>&1
   ```

6. **Read results**: `grep "^avg_naturalness:" run.log`

7. **Decide**:
   - Naturalness improved ≥0.2 OR issues decreased ≥1 → **KEEP**
   - Equal/worse → **DISCARD** (`git reset --hard HEAD~1`)

8. **Topic rotation**: Each iteration uses 3 randomly selected topics.
   Changes must generalize across topics to count as improvements.

9. Repeat.

## Strategy

**Follow the prompt analysis.** This pipeline tells you exactly which
instructions cause which problems. Don't guess — read the analysis.

**Common fixes:**
- `forced_transition` → Improve transition message or first-turn pacing directive
- `overwhelming` → Add word limits or "one idea per response" rule
- `robotic_structure` → Strengthen "never repeat" / vary structure rules
- `false_ok_missed` → Improve false OK detection instructions
- `card_disconnect` → Make precomputed summary constructive, not just "don't repeat"
- `complexity_mismatch` → Add grade-level language constraints

## Important Constraints

- NEVER modify evaluation code (ground truth)
- Keep template variables intact
- Don't break structured output
- One change at a time
- Use `--restart-server` for Tier 1 code changes

## NEVER STOP

Autonomous until manually stopped. If stuck:
- Re-read the flagged messages — what would a real teacher do differently?
- Re-read Riya's persona
- Try removing rules instead of adding
- Look at which issue categories keep recurring
