# Autoresearch: End-to-End Teaching Experience Optimization

Autonomous research loop for improving the complete "teach me" experience —
from explanation cards through interactive tutoring as one coherent session.
Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## The Core Question

**Does the entire teaching experience — from reading explanation cards to interactive practice — feel like one connected, effective lesson for an average student?**

We optimize for ONE persona: Riya, a Grade 5 CBSE student with average IQ. She needs
simple language, everyday examples, patient repetition, and frequent check-ins. She won't
tell you she's confused — she'll just go quiet or guess. She represents our primary target
user: the kid who NEEDS an AI tutor the most because traditional teaching moves too fast
for her. If we get it right for Riya, we serve our core audience.

## The E2E Teaching Lifecycle

Understanding this lifecycle is critical to your work:

```
1. Student starts "Teach me" session
2. PRE-COMPUTED EXPLANATION CARDS shown (5-11 cards, read passively)
   - Generated offline by a separate pipeline
   - Contain analogies, examples, visuals, step-by-step explanations
   - Student clicks "Clear" when done reading
3. TRANSITION to interactive session
   - Hardcoded message: "Great! Now let's make sure you've got it..."
   - All leading "explain" steps in study plan are SKIPPED (cards covered them)
   - Tutor receives a summary of what cards covered (for context)
4. INTERACTIVE TEACHING begins
   - Tutor should BUILD ON what the cards taught
   - Check understanding, ask questions, address misconceptions
   - Reference the specific analogies/examples from the cards
```

**The problem we're solving:** Steps 2, 3, and 4 are powered by DIFFERENT systems
with DIFFERENT prompts. From Riya's perspective, it should feel like ONE teacher
walking her through a topic. Currently it feels like reading a textbook, then being
handed to a different teacher who doesn't know what she just read.

## How It Works

You are an autonomous AI researcher. You iteratively improve the teaching experience by:
modifying prompts and teaching pipeline code → running an E2E evaluation → keeping changes
that improve the score. You run **indefinitely** until manually stopped.

## Setup

Work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar18`).
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current branch.
3. **Read the in-scope files** for full context:
   - `autoresearch/tutor_teaching_quality/program.md` — this file (your instructions)
   - `autoresearch/tutor_teaching_quality/run_experiment.py` — the experiment runner
   - **Modifiable surface** (see section below) — read ALL of these
   - `autoresearch/tutor_teaching_quality/evaluation/evaluator.py` — the 7 evaluation dimensions and rubric
   - `autoresearch/tutor_teaching_quality/evaluation/personas/average_student.json` — **READ THIS CAREFULLY** — understand Riya
4. **Verify server is running**: `curl -s http://localhost:8000/health/db` should return OK.
   If not, tell the human to start the server: `cd llm-backend && ./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000`
5. **Set AUTORESEARCH_TOPIC_ID**: Must be a topic WITH pre-computed explanations. Use one of:
   - `08ffca67-f71d-40b4-b60d-658bc688f74d` — 3-Digit Addition: Regrouping in One Column
   - `eb64ad64-9ba6-4752-8b72-751baa0c74b5` — 3-Digit Addition: Regrouping in Two Columns
   - `44fd6529-fb7f-4ff2-a2e7-cd598a8b3d4f` — 4-Digit Addition and Checking Your Answer
   - `b8d0b705-7a49-4fe1-bd06-eff6fec0f8b6` — Reviewing 3-Digit Place Value
   - `4220931c-d879-4939-b092-bfbc0ed2f1e3` — Revisiting Addition: Fact Families
   - `206482af-8a3d-4872-a091-2436899b5125` — Structured Problem Solving with Addition
6. **Run baseline**: `./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment --skip-server --description "baseline" --iteration 0 --email <email>`
7. **Confirm and go**: Confirm setup with the human, then start the loop.

## Modifiable Surface

You can modify **anything that shapes the teaching experience**. This includes prompt
templates, transition logic, summary construction, and pacing behavior.

### TIER 1 — Primary Targets (modify freely)

**`tutor/prompts/master_tutor_prompts.py`** — Main teaching prompts
- `MASTER_TUTOR_SYSTEM_PROMPT` — System prompt: teaching rules, study plan, personalization
- `MASTER_TUTOR_TURN_PROMPT` — Per-turn prompt: session state, pacing, history
- Everything is fair game: rewrite teaching rules, change pacing directives, restructure
  layout, add/remove rules, change tone, modify the `{precomputed_explanation_summary_section}`
  placement and surrounding instructions.

**`tutor/agents/master_tutor.py`** — Tutor agent logic
- `_build_system_prompt()` — How the system prompt is assembled. In particular:
  - Lines 426-436: The `precomputed_explanation_summary_section` construction — currently
    says "DO NOT repeat these analogies/examples." This is NEGATIVE-ONLY. You can rewrite
    this to be constructive: "Build on these analogies, reference them, extend them."
  - The pacing directive logic (`_build_pacing_directive()`) — how the tutor adjusts speed
    based on mastery, attention span, and explanation phase.

**`tutor/services/session_service.py`** — Session lifecycle
- Line 863: The transition message `"Great! Now let's make sure you've got it. Feel free
  to ask any questions!"` — This is hardcoded and generic. You can make it reference the
  topic, be more engaging, probe understanding, or even make it LLM-generated.
- `_build_precomputed_summary()` method (line 934) — How the card summary is formatted for
  the tutor's context. Currently just lists card titles, analogies, and examples. You can
  make this richer (include key concepts, building blocks, the card's narrative arc).
- `_advance_past_explanation_steps()` method (line 956) — Controls which study plan steps
  are skipped after card phase. Currently skips ALL consecutive leading explain steps.
  You could make this smarter (skip some, keep others).

### TIER 2 — Secondary Targets (modify after several Tier 1 iterations)

**`tutor/prompts/orchestrator_prompts.py`** — Welcome message prompts
**`tutor/prompts/clarify_doubts_prompts.py`** — Clarify Doubts mode prompts
**`tutor/orchestration/orchestrator.py`** — Welcome message generation, post-completion logic

### DO NOT MODIFY

- `autoresearch/tutor_teaching_quality/evaluation/` — The evaluation pipeline (ground truth)
- `autoresearch/tutor_teaching_quality/run_experiment.py`, `email_report.py` — Runner code
- `tutor/models/` — Data models (SessionState, StudyPlan, etc.)
- `tutor/api/` — API endpoints and WebSocket routing
- `shared/` — Shared infrastructure (LLM service, repositories, DB)
- `autoresearch/tutor_teaching_quality/evaluation/session_runner.py` — Session simulation

## The Metric

**Evaluation score (1-10, higher is better)** — averaged across 7 dimensions.

Single persona: `average_student` (Riya, 45% correct, average IQ, needs simple language).

Each session runs the FULL E2E lifecycle: card phase → transition → 20 interactive turns.
An LLM judge scores the entire experience on 7 dimensions (1-10):

### Core Teaching Dimensions (always scored)

1. **Responsiveness** — Did the tutor pick up on Riya's signals? When she said "hmm ok"
   without really understanding, did the tutor probe? When she guessed randomly, did the
   tutor detect it?

2. **Explanation Quality** — Were explanations simple enough for an average student?
   Everyday examples (roti, cricket, pocket money) instead of abstract language?
   When Riya didn't get it, did the tutor try a DIFFERENT approach — not just repeat?

3. **Emotional Attunement** — Did the tutor keep Riya engaged? Calibrated encouragement
   (not over-the-top) when she struggled? Genuine excitement when she had a breakthrough?

4. **Pacing** — Did the tutor go slow enough for Riya? Not rush through concepts?
   Frequent check-ins to make sure she actually understood before moving on?

5. **Authenticity** — Did the tutor feel like a real teacher who cares about Riya,
   not a chatbot running through a script?

### E2E Coherence Dimensions (scored when explanation cards are present)

6. **Card-to-Session Coherence** — Does the interactive session BUILD ON what the
   explanation cards taught? Does the tutor reference the specific analogies and examples
   from the cards? Or does it ignore the cards and start fresh with different framing?

7. **Transition Quality** — How smooth is the bridge from reading cards to interactive
   teaching? Does the tutor check what Riya actually absorbed from the cards? Or does it
   just say "feel free to ask questions" and wait for a student who won't self-direct?

### Root Causes to Watch For

The evaluator identifies problems with root causes. Pay special attention to:
- `card_content_ignored` — Tutor doesn't reference card analogies/examples
- `abrupt_transition` — Generic transition without checking understanding
- `card_repetition` — Tutor re-explains things the cards already covered
- `repetitive_approach` — Same teaching strategy despite repeated failure
- `missed_student_signal` — Missing Riya's false OKs and random guesses

## Running an Experiment

**IMPORTANT: Use `--restart-server` (not `--skip-server`) when modifying Tier 1 agent/service
code.** The server caches Python modules at startup — `--skip-server` reuses the running
server which has the OLD code. `--restart-server` kills + restarts the server each run,
ensuring your code changes take effect.

```bash
cd llm-backend
./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment \
    --restart-server \
    --description "what this experiment tries" \
    --iteration <N> \
    --email <email> > run.log 2>&1
```

**Default: 2 runs per iteration** to reduce stochastic variance from the student simulator.
The dice roll (45% correct probability) means single runs have ~0.5 point variance. With
2 runs averaged, variance drops to ~0.3.

Output:
```
---
avg_score: 5.234567
elapsed_min: 12.4
commit: a1b2c3d
status: pending
```

Extract the metric: `grep "^avg_score:" run.log`

Each experiment takes ~12-16 minutes (2 runs × 20 turns + evaluation).
That's ~4-5 experiments per hour, ~30-40 overnight.

Use `--runs 1` for quick first-pass testing, `--runs 3` for high-confidence decisions.

## Quick Mode

For risky/speculative ideas, run quick mode first (12 turns, 1 run):

```bash
./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment --restart-server --quick --runs 1 \
    --description "risky: remove all teaching rules" --iteration <N>
```

If promising, re-run in full mode (20 turns, 2 runs).

## The Experiment Loop

LOOP FOREVER:

1. **Review state**: Check `results.tsv`. Read current modifiable files.

2. **Form a hypothesis**: Based on evaluation problems and dimension scores, pick
   ONE improvement to try. Think about Riya specifically AND the E2E experience:

   **Card-to-session coherence questions:**
   - Is the tutor building on the card analogies, or introducing completely new ones?
   - Does the transition check what Riya actually understood from the cards?
   - After cards covered "coin jars" for regrouping, does the tutor reference coin jars?
   - Does the precomputed_summary give the tutor enough context to build continuity?

   **Interactive teaching questions:**
   - Is the tutor using language too complex for her?
   - Is it moving on before she actually understands?
   - Is it confusing her "hmm ok" with real understanding?
   - Is it trying different approaches when she's stuck, or just repeating?
   - Is it talking too much without checking in?

3. **Edit files**: Make ONE focused change. Small beats big.
   `git commit` the change.

4. **Run experiment**:
   ```bash
   ./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment --restart-server \
       --description "short description" --iteration <N> \
       --email <email> > run.log 2>&1
   ```

5. **Read results**: `grep "^avg_score:" run.log`

6. **Decide**:
   - Score IMPROVED → **KEEP**. Update results.tsv status to `keep`.
   - Score EQUAL or WORSE → **DISCARD**. `git reset --hard HEAD~1`. Update results.tsv.
   - Exception: significant improvement in one dimension without hurting others → keep.

7. **Simplicity criterion**: simpler code/prompts are better, all else equal.
   Removing something and getting equal results = WIN (simplification).

8. **Topic rotation (every ~10 experiments)**: Rotate across topics that have
   pre-computed explanations (see Setup section for the list). If a change improves
   scores on one topic but tanks another, it's not a real improvement.

9. Repeat.

## Strategy Guide

Think about Riya at every step. Think about the COMPLETE experience from cards to practice.

### CRITICAL LESSON: Weave In, Don't Bolt On

The master tutor system prompt already has detailed, well-structured teaching rules
(explain before testing, check understanding, use everyday examples, pacing directives).
**DO NOT add a separate "how to use cards" instruction block** that competes with these
existing rules. This creates conflicting instructions and hurts scores.

Instead, **modify the existing rules to be card-aware.** For example:
- BAD: Adding a new "Card Phase Rules" section with 5 bullet points
- GOOD: Modifying the existing "FIRST TURN" pacing directive to say "if pre-explained
  content exists, start by checking what the student absorbed using one of those analogies"
- BAD: "Your FIRST message must check card comprehension"
- GOOD: Adjusting the explanation phase opening to reference card content naturally

The tutor already knows how to teach — you're just making it aware of what came before.

**Early experiments (1-10) — Fix the obvious disconnects:**
- Read the E2E conversation transcript first — understand where the experience breaks
- Start with the precomputed summary section (agent code) — make it constructive not negative
- Modify the transition message to be topic-aware and set expectations
- Weave card awareness into the EXISTING pacing/teaching rules — don't add new sections
- Focus on `card_to_session_coherence` and `transition_quality` first

**Mid experiments (10-30) — Strengthen the connection:**
- Make the precomputed summary richer (include key building blocks, not just titles)
- Improve the pacing directive for post-card sessions
- The tutor should reference specific analogies from cards when Riya is confused
- Target the "false OK" problem — Riya clicks "Clear" but didn't really understand
- Test whether keeping some explain steps (instead of skipping all) helps

**Advanced experiments (30+) — Polish the whole experience:**
- Creative approaches: teaching philosophy shifts, novel prompt structures
- The first interactive question should connect to the last card's content
- Revisit early discards with other changes in place
- Try removing card-related instructions and see if the tutor handles it naturally

## Important Constraints

- **NEVER modify evaluation code.** The evaluator is our ground truth.
- **NEVER modify session runner, student simulator, or report generator.**
- **Keep template variables intact.** Variables like `{grade}`, `{topic_name}`,
  `{precomputed_explanation_summary_section}` etc. must stay — the system errors if missing.
- **Don't break structured output.** The master tutor produces structured JSON output
  fields. Don't remove output format instructions — rewrite them if needed.
- **No new dependencies.** Use what's installed.
- **One change at a time.** Two changes + improvement = you don't know which helped.
- **Test with card-phase topics.** Always use topics from the Setup list that have
  pre-computed explanations. Testing without cards misses the E2E coherence dimensions.

## Crash Recovery

If an experiment crashes:
1. Read the last 50 lines of `run.log` for the traceback.
2. If trivial (typo broke a template variable, syntax error): fix and retry.
3. If crash is in evaluation/runner code (not your fault): log as `crash` in
   results.tsv, `git reset --hard HEAD~1`, and move on.
4. Do NOT get stuck retrying the same crash. Two failed attempts → discard and move on.

## NEVER STOP

Once the loop begins, do NOT pause to ask "should I continue?" The human might be
asleep. You are autonomous. If you run out of ideas:
- Re-read the evaluation rubric (`evaluator.py`)
- Re-read Riya's persona for clues
- Read E2E conversation transcripts in run directories — look at where cards end and
  interactive teaching begins
- Try the opposite of what you've been doing
- Try removing things instead of adding
- Think about what a real human tutor would do after handing Riya a set of flashcards

The loop runs until the human interrupts you.

## Email Reports

Every iteration emails a compact report:
- Iteration number and description
- Current score vs baseline (with delta)
- Per-dimension breakdown (all 7 dimensions)
- Top problems identified
- The prompt diff

The human checks these on their phone while away from the computer.

## Template Variables Reference

**System prompt (`MASTER_TUTOR_SYSTEM_PROMPT`):**
- `{grade}`, `{language_level}`, `{preferred_examples}` — student info
- `{personalization_block}` — student personality (injected by agent code)
- `{topic_name}`, `{curriculum_scope}` — topic info
- `{prior_topics_context_section}` — what student learned in prior topics
- `{precomputed_explanation_summary_section}` — **KEY FOR E2E** — summary of explanation
  cards the student read before this interactive session. Built by `master_tutor.py:426-436`.
  Contains card titles, analogies used, examples used.
- `{steps_formatted}` — study plan steps
- `{common_misconceptions}` — topic misconceptions
- `{response_language_instruction}`, `{audio_language_instruction}` — language rules

**Turn prompt (`MASTER_TUTOR_TURN_PROMPT`):**
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

## Key Code Locations (for Tier 1 modifications)

| What | File | Lines | What it does |
|------|------|-------|-------------|
| Teaching rules | `tutor/prompts/master_tutor_prompts.py` | all | System prompt + turn prompt templates |
| Card summary injection | `tutor/agents/master_tutor.py` | 426-436 | Builds the "Pre-Explained Content" section |
| Pacing directives | `tutor/agents/master_tutor.py` | `_build_pacing_directive()` | Dynamic pacing based on mastery/progress |
| Transition message | `tutor/services/session_service.py` | 863 | Hardcoded "Great! Now let's make sure..." |
| Card summary builder | `tutor/services/session_service.py` | 934-952 | Formats card titles/analogies/examples |
| Step skipping | `tutor/services/session_service.py` | 956-969 | Which study plan steps to skip after cards |
