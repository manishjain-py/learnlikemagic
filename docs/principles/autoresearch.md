# Principles: Autoresearch

Autonomous AI-driven experimentation to continuously improve tutor quality. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## The Idea

Karpathy's insight: **humans write the meta-program, not the code.** Instead of hand-tuning prompts, you write instructions (`program.md`) that tell an AI agent how to conduct research. The agent modifies prompts, runs evaluations, keeps what works, discards what doesn't — and repeats indefinitely while you sleep.

We apply this to tutor prompt optimization. The agent modifies teaching prompts, a simulated student converses with the tutor, an LLM judge scores the conversation, and the agent decides keep or discard. ~8 experiments/hour, ~60-80 overnight.

## Core Principles

### 1. The Metric is Sacred

The evaluation pipeline is **read-only**. The agent never modifies how we measure — only what we measure. If the agent could change the rubric, it would optimize the rubric instead of the tutor.

### 2. One Change, One Experiment

Each experiment modifies one thing. Two changes + improvement = you don't know which helped. Small focused edits beat big rewrites.

### 3. Simplicity Wins

At equal scores, simpler prompts are better. Removing a rule that doesn't help = a win. Adding 10 lines for 0.05 improvement = probably not worth it. The best prompt is the shortest one that produces great teaching.

### 4. Optimize for the Struggling Student

We optimize for Riya — an average/below-average Grade 5 student who says "hmm ok" without understanding, guesses when confused, and goes quiet when frustrated. If the tutor works for Riya, it works for everyone. If it only works for top students, it's failed.

### 5. Never Stop

The agent runs autonomously until interrupted. No pausing to ask "should I continue?" The human reviews via email reports on their phone. When stuck, the agent re-reads the rubric, tries the opposite approach, removes instead of adds, or thinks about what a real human tutor would do.

### 6. Git is the Experiment Log

Every change is a commit. Improvements advance the branch. Failures get reset. The branch history is a linear chain of validated improvements. `results.tsv` provides the detailed log including discards.

### 7. Guard Against Overfitting

A prompt tuned for "fractions with Riya" might fail on "geometry with a different student." Periodically validate against multiple topics and personas to ensure the prompt generalizes — not just memorizes one scenario.

## Architecture (Karpathy → Ours)

| Karpathy | Ours | Role |
|----------|------|------|
| `train.py` | `tutor/prompts/master_tutor_prompts.py` | The thing the agent modifies |
| `prepare.py` | `evaluation/` pipeline | Fixed evaluation (read-only) |
| `program.md` | `program.md` | Human-written agent instructions |
| val_bpb (lower = better) | 5-dimension avg score (higher = better) | The metric |
| 5 min training run | ~5-8 min simulated session + LLM judge | One experiment cycle |
| `results.tsv` | `results.tsv` | Experiment log |
| `analysis.ipynb` | Email reports | Human reviews results |

## What We Added Beyond Karpathy's

- **Multi-run averaging** — run 3x and average to reduce variance (~0.6 → ~0.35)
- **Quick mode** — 12-turn runs for speculative ideas before committing to full evaluation
- **Email reports** — per-iteration HTML reports with scores, conversation, prompt diff
- **Rich evaluation** — 5 teaching dimensions with problem analysis, not just a single number
- **Strategy guide** — phased approach (early: fix basics, mid: target patterns, advanced: creative shifts)
- **Student simulator** — programmatic correct/incorrect enforcement via dice roll, not just LLM roleplay
