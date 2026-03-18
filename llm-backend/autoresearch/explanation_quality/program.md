# Autoresearch: Explanation Quality Optimization

Autonomous research loop for improving pre-computed explanation card quality.
Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## The Core Question

**Do these explanation cards actually help a struggling student understand the concept?**

We generate explanation cards that students read BEFORE interactive tutoring begins.
These cards must be crystal clear for an average or below-average student — simple words,
everyday examples, one idea at a time, building progressively. If a student reads the
cards and still doesn't understand, the explanation has failed.

## How It Works

You are an autonomous AI researcher. You iteratively improve explanation prompts by:
modifying prompt files → generating explanation cards → evaluating card quality → keeping
changes that improve the score. You run **indefinitely** until manually stopped.

## Setup

Work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar18-expl`).
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current branch.
3. **Read the in-scope files** for full context:
   - `autoresearch/explanation_quality/program.md` — this file (your instructions)
   - `autoresearch/explanation_quality/run_experiment.py` — the experiment runner
   - `book_ingestion_v2/prompts/explanation_generation.txt` — **THE FILE YOU MODIFY** (generation prompt)
   - `book_ingestion_v2/prompts/explanation_critique.txt` — secondary target (critique prompt)
   - `autoresearch/explanation_quality/evaluation/evaluator.py` — the 5 evaluation dimensions
   - `docs/principles/how-to-explain.md` — the explanation principles document
4. **Run baseline**:
   ```bash
   ./venv/bin/python -m autoresearch.explanation_quality.run_experiment \
       --description "baseline" --iteration 0 --email <email>
   ```
5. **Confirm and go**: Confirm setup with the human, then start the loop.

## Modifiable Surface

**PRIMARY — `book_ingestion_v2/prompts/explanation_generation.txt`:**
The main prompt that generates explanation cards. Everything is fair game: rewrite
principles, change tone instructions, add/remove guidelines, restructure the prompt,
change how card types are used, modify the opening persona framing.

**SECONDARY (modify only after several primary iterations):**
- `book_ingestion_v2/prompts/explanation_critique.txt` — the critique prompt that
  reviews generated cards against principles

**DO NOT MODIFY:**
- `autoresearch/explanation_quality/evaluation/` — The evaluation pipeline is read-only
- `book_ingestion_v2/services/` — Service code
- `autoresearch/explanation_quality/run_experiment.py` — Runner code

## The Metric

**Evaluation score (1-10, higher is better)** — averaged across 5 dimensions and 3 variants.

Each experiment generates cards for a randomly-selected topic (from a pool of 4 diverse
topics), evaluates all 3 explanation variants (Analogies, Visual, Procedural), and
averages the scores.

**5 Dimensions:**

1. **Simplicity** — Would a struggling student understand every word and sentence
   without re-reading? Are words grade-appropriate? Sentences short and direct?

2. **Concept Clarity** — After reading all cards, would a struggling student actually
   understand the concept — the WHY, not just the WHAT? Could they explain it to a friend?

3. **Examples & Analogies** — Are examples concrete, everyday, relatable (food, games,
   money, sports)? Do analogies map precisely? Examples before rules?

4. **Structure & Flow** — Does each card build naturally on the previous? One idea per
   card? No leaps? Perfect for a beginner?

5. **Overall Effectiveness** — Would a struggling student walk away feeling "I can do this"?

## Running an Experiment

```bash
cd llm-backend
./venv/bin/python -m autoresearch.explanation_quality.run_experiment \
    --description "what this experiment tries" \
    --iteration <N> \
    --email <email> > run.log 2>&1
```

Output:
```
---
avg_score: 7.234567
elapsed_min: 4.2
commit: a1b2c3d
status: pending
```

Extract the metric: `grep "^avg_score:" run.log`

Each experiment takes ~3-5 minutes (3 variants × generation + evaluation).
That's ~12-15 experiments per hour, ~100+ overnight.

## Quick Mode

For risky/speculative ideas, run quick mode first (1 variant):

```bash
./venv/bin/python -m autoresearch.explanation_quality.run_experiment --quick \
    --description "risky: remove all principles" --iteration <N>
```

## The Experiment Loop

LOOP FOREVER:

1. **Review state**: Check `results.tsv`. Read current prompt files.

2. **Form a hypothesis**: Based on evaluation problems and dimension scores, pick
   ONE improvement to try. Think about a struggling student specifically:
   - Are the words too complex for the grade level?
   - Are explanations too abstract — missing concrete examples?
   - Are cards trying to teach too much at once?
   - Is the progression too fast — are there leaps between cards?
   - Are analogies precise or could they create misconceptions?
   - Does it feel like a textbook or like a favourite older sibling explaining?
   - Are visuals used where they'd help?
   - Are misconceptions addressed proactively?

3. **Edit prompt files**: Make ONE focused change. Small beats big.
   `git commit` the change.

4. **Run experiment**:
   ```bash
   ./venv/bin/python -m autoresearch.explanation_quality.run_experiment \
       --description "short description" --iteration <N> \
       --email <email> > run.log 2>&1
   ```

5. **Read results**: `grep "^avg_score:" run.log`

6. **Decide**:
   - Score IMPROVED → **KEEP**. Update results.tsv status to `keep`.
   - Score EQUAL or WORSE → **DISCARD**. `git reset --hard HEAD~1`. Update results.tsv.
   - Exception: significant improvement in one dimension without hurting others → keep.

7. **Simplicity criterion**: simpler prompts are better, all else equal.
   Removing a principle and getting equal results = WIN (simplification).
   Adding complexity for < 0.1 improvement = probably not worth it.

8. Repeat.

## Strategy Guide

Think about a struggling Grade 1 student at every step. Ask yourself: "Would this
change make the explanation clearer for a kid who finds math hard?"

**Early experiments (1-10):**
- Look at baseline evaluation problems — what confused the evaluator?
- Focus on the lowest-scoring dimension first
- Common early wins: simplify word choices in principles, strengthen the "one idea
  per card" rule, add more emphasis on concrete examples before rules
- Read the generated cards to see where they feel too complex

**Mid experiments (10-30):**
- Target specific problem patterns (e.g., cards too dense, analogies too abstract)
- Experiment with phrasing variations of existing principles
- Test removing principles that don't help
- Try restructuring the prompt layout (principles order, grouping)

**Advanced experiments (30+):**
- Creative approaches: different persona framings, novel prompt structures
- Revisit early discards with other changes in place
- Test minimal vs. detailed prompts
- Experiment with different card type guidance

## Important Constraints

- **NEVER modify evaluation code.** The evaluator is our ground truth.
- **NEVER modify service code.** Only prompts.
- **Keep template variables intact.** Variables like `{grade}`, `{topic_name}`,
  `{subject}`, `{guideline_text}`, `{variant_approach}`, `{output_schema}`,
  `{prior_topics_section}` must stay.
- **One change at a time.** Two changes + improvement = you don't know which helped.
- **No new dependencies.**

## Crash Recovery

If an experiment crashes:
1. Read the last 50 lines of `run.log` for the traceback.
2. If trivial (broke a template variable, JSON format issue): fix and retry.
3. If the crash is in evaluation/generation code (not your fault): log as `crash`
   in results.tsv, `git reset --hard HEAD~1`, and move on.
4. Two failed attempts → discard and move on.

## NEVER STOP

Once the loop begins, do NOT pause to ask "should I continue?" The human might be
asleep. You are autonomous. If you run out of ideas:
- Re-read the evaluation rubric (`evaluator.py`)
- Re-read the how-to-explain principles (`docs/principles/how-to-explain.md`)
- Read generated cards in run directories — find what feels wrong
- Try the opposite of what you've been doing
- Try removing things instead of adding
- Think about what a real human tutor would write on flashcards for a struggling kid

The loop runs until the human interrupts you.

## Email Reports

Every iteration emails a compact report:
- Iteration number, topic, and description
- Current score vs baseline (with delta)
- Per-dimension breakdown
- The prompt diff

The human checks these on their phone while away from the computer.

## Template Variables Reference

**Generation prompt:**
- `{grade}` — student grade level
- `{topic_name}` — topic being explained
- `{subject}` — subject (e.g., Mathematics)
- `{guideline_text}` — teaching guideline content
- `{prior_topics_section}` — context from earlier topics
- `{variant_approach}` — which variant style to use
- `{output_schema}` — JSON output format
