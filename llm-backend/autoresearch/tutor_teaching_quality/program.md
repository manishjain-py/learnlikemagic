# Autoresearch: Tutor Prompt Optimization

Autonomous research loop for improving AI tutor prompts.
Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## The Core Question

**Did the tutor explain concepts in a way that actually helped an average student understand?**

We optimize for ONE persona: Riya, a Grade 5 CBSE student with average IQ. She needs
simple language, everyday examples, patient repetition, and frequent check-ins. She won't
tell you she's confused — she'll just go quiet or guess. She represents our primary target
user: the kid who NEEDS an AI tutor the most because traditional teaching moves too fast
for her. If we get it right for Riya, we serve our core audience.

## How It Works

You are an autonomous AI researcher. You iteratively improve tutor prompts by:
modifying prompt files → running an evaluation → keeping changes that improve the score.
You run **indefinitely** until manually stopped.

## Setup

Work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar14`).
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current branch.
3. **Read the in-scope files** for full context:
   - `autoresearch/tutor_teaching_quality/program.md` — this file (your instructions)
   - `autoresearch/tutor_teaching_quality/run_experiment.py` — the experiment runner
   - `tutor/prompts/master_tutor_prompts.py` — **THE FILE YOU MODIFY** (main teaching prompts)
   - `tutor/prompts/clarify_doubts_prompts.py` — secondary target (clarify mode prompts)
   - `tutor/prompts/orchestrator_prompts.py` — secondary target (welcome messages)
   - `autoresearch/tutor_teaching_quality/evaluation/evaluator.py` — the 5 evaluation dimensions and rubric
   - `autoresearch/tutor_teaching_quality/evaluation/personas/average_student.json` — **READ THIS CAREFULLY** — understand Riya
4. **Verify server is running**: `curl -s http://localhost:8000/health/db` should return OK.
   If not, tell the human to start the server: `cd llm-backend && ./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000`
5. **Set AUTORESEARCH_TOPIC_ID**: Check `.env` or resolve:
   `./venv/bin/python -c "from autoresearch.tutor_teaching_quality.run_experiment import resolve_topic_id; print(resolve_topic_id())"`
6. **Run baseline**: `./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment --skip-server --description "baseline" --iteration 0 --email <email>`
7. **Confirm and go**: Confirm setup with the human, then start the loop.

## Modifiable Surface

**PRIMARY — `tutor/prompts/master_tutor_prompts.py`:**
- `MASTER_TUTOR_SYSTEM_PROMPT` — System prompt: teaching rules, study plan, personalization
- `MASTER_TUTOR_TURN_PROMPT` — Per-turn prompt: session state, pacing, history

Everything is fair game: rewrite teaching rules, change pacing directives, restructure
the prompt layout, add/remove rules, change tone instructions, modify formatting guidance.

**SECONDARY (modify only after several primary iterations):**
- `tutor/prompts/clarify_doubts_prompts.py` — Clarify Doubts mode prompts
- `tutor/prompts/orchestrator_prompts.py` — Welcome message prompts

**DO NOT MODIFY:**
- `autoresearch/tutor_teaching_quality/evaluation/` — The evaluation pipeline is read-only (fixed metric)
- `tutor/agents/`, `tutor/models/`, `tutor/services/` — Code
- `autoresearch/tutor_teaching_quality/run_experiment.py`, `autoresearch/tutor_teaching_quality/email_report.py` — Runner

## The Metric

**Evaluation score (1-10, higher is better)** — averaged across 5 dimensions.

Single persona: `average_student` (Riya, 45% correct, average IQ, needs simple language).

Each session runs 20 turns through the tutor with a simulated student, then an LLM judge
scores the conversation on 5 dimensions (1-10):

1. **Responsiveness** — Did the tutor pick up on Riya's signals? When she said "hmm ok"
   without really understanding, did the tutor probe? When she guessed randomly, did the
   tutor detect it?

2. **Explanation Quality** — Were explanations simple enough for an average student?
   Everyday examples (roti, cricket, pocket money) instead of abstract language?
   When Riya didn't get it, did the tutor try a DIFFERENT approach — not just repeat?

3. **Emotional Attunement** — Did the tutor keep Riya engaged? Calibrated encouragement
   (not over-the-top) when she struggled? Genuine excitement when she had a breakthrough?
   Patient when she got things wrong repeatedly?

4. **Pacing** — Did the tutor go slow enough for Riya? Not rush through concepts?
   Frequent check-ins to make sure she actually understood before moving on?
   Not confusing "she said ok" with "she actually gets it"?

5. **Authenticity** — Did the tutor feel like a real teacher who cares about Riya,
   not a chatbot running through a script?

The composite score = average across all 5 dimensions for this one persona.

## Running an Experiment

```bash
cd llm-backend
./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment \
    --skip-server \
    --description "what this experiment tries" \
    --iteration <N> \
    --email <email> > run.log 2>&1
```

Output:
```
---
avg_score: 7.234567
elapsed_min: 6.2
commit: a1b2c3d
status: pending
```

Extract the metric: `grep "^avg_score:" run.log`

Each experiment takes ~5-8 minutes (1 persona × 20 turns + evaluation).
That's ~8-10 experiments per hour, ~60-80 overnight.

## Quick Mode

For risky/speculative ideas, run quick mode first (12 turns):

```bash
./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment --skip-server --quick \
    --description "risky: remove all teaching rules" --iteration <N>
```

If promising, re-run in full mode.

## The Experiment Loop

LOOP FOREVER:

1. **Review state**: Check `results.tsv`. Read current prompt files.

2. **Form a hypothesis**: Based on evaluation problems and dimension scores, pick
   ONE improvement to try. Think about Riya specifically:
   - Is the tutor using language too complex for her?
   - Is it moving on before she actually understands?
   - Is it confusing her "hmm ok" with real understanding?
   - Is it trying different approaches when she's stuck, or just repeating?
   - Is it using abstract explanations instead of everyday examples?
   - Is it talking too much without checking in?
   - Is it detecting when she's randomly guessing vs. genuinely trying?

3. **Edit prompt files**: Make ONE focused change. Small beats big.
   `git commit` the change.

4. **Run experiment**:
   ```bash
   ./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment --skip-server \
       --description "short description" --iteration <N> \
       --email <email> > run.log 2>&1
   ```

5. **Read results**: `grep "^avg_score:" run.log`

6. **Decide**:
   - Score IMPROVED → **KEEP**. Update results.tsv status to `keep`.
   - Score EQUAL or WORSE → **DISCARD**. `git reset --hard HEAD~1`. Update results.tsv.
   - Exception: significant improvement in one dimension without hurting others → keep.

7. **Simplicity criterion**: simpler prompts are better, all else equal.
   Removing something and getting equal results = WIN (simplification).
   Adding complexity for < 0.1 improvement = probably not worth it.

8. Repeat.

## Strategy Guide

Think about Riya at every step. Ask yourself: "Would this change help an average
10-year-old who needs simple language and patient explanations?"

**Early experiments (1-10):**
- Look at baseline evaluation problems — what went wrong for Riya?
- Focus on the lowest-scoring dimension first
- Common early wins: simplify language rules, add "check understanding" rules,
  emphasize concrete examples over abstract explanations
- Read the conversation transcript to see where Riya got lost

**Mid experiments (10-30):**
- Target specific problem patterns (e.g., tutor talks too long, doesn't detect false OKs)
- Experiment with phrasing variations of existing rules
- Test removing rules that don't help Riya
- Focus on the "false OK" problem — Riya saying she understands when she doesn't

**Advanced experiments (30+):**
- Creative approaches: teaching philosophy shifts, novel prompt structures
- Revisit early discards with other changes in place
- Minimal vs. detailed prompts
- Meta-instructions (how to interpret student signals)

## Important Constraints

- **NEVER modify evaluation code.** The evaluator is our ground truth.
- **NEVER modify orchestration logic, agents, or models.** Only prompts.
- **Keep template variables intact.** Variables like `{grade}`, `{topic_name}` etc.
  must stay — the system errors if missing.
- **Don't break structured output.** Rules 3, 7, 12, 13 in the system prompt produce
  structured output fields. Don't remove these — rewrite them if needed.
- **No new dependencies.** Use what's installed.
- **One change at a time.** Two changes + improvement = you don't know which helped.

## NEVER STOP

Once the loop begins, do NOT pause to ask "should I continue?" The human might be
asleep. You are autonomous. If you run out of ideas:
- Re-read the evaluation rubric (`evaluator.py`)
- Re-read Riya's persona for clues
- Read conversation transcripts in run directories
- Try the opposite of what you've been doing
- Try removing things instead of adding
- Think about what a real human tutor would do with a student like Riya

The loop runs until the human interrupts you.

## Email Reports

Every iteration emails a compact report:
- Iteration number and description
- Current score vs baseline (with delta)
- Per-dimension breakdown
- Top problems identified
- The prompt diff

The human checks these on their phone while away from the computer.

## Template Variables Reference

**System prompt:**
- `{grade}`, `{language_level}`, `{preferred_examples}` — student info
- `{personalization_block}` — student personality (injected by agent code)
- `{topic_name}`, `{curriculum_scope}` — topic info
- `{steps_formatted}` — study plan steps
- `{common_misconceptions}` — topic misconceptions
- `{response_language_instruction}`, `{audio_language_instruction}` — language rules

**Turn prompt:**
- `{current_step}`, `{total_steps}`, `{current_step_info}`, `{content_hint}` — step info
- `{explanation_context}` — explanation phase details
- `{mastery_formatted}` — current mastery scores
- `{misconceptions}` — detected misconceptions
- `{turn_timeline}` — session narrative
- `{pacing_directive}` — dynamic pacing signal
- `{student_style}` — student communication style analysis
- `{awaiting_answer_section}` — pending question context
- `{conversation_history}` — recent messages
- `{student_message}` — current student input
