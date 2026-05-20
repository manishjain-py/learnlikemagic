# Principles: Autoresearch

Autonomous AI-driven experimentation to continuously improve any LLM-powered prompt in the app. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## The Idea

Karpathy's insight: **humans write the meta-program, not the code.** Instead of hand-tuning prompts, you write instructions (`program.md`) that tell an AI agent how to conduct research. The agent modifies the prompt, runs an evaluation, keeps what works, discards what doesn't — and repeats indefinitely while you sleep.

Each run defines its own input set, rubric, and judge.

## Core Principles

### 1. The Metric is Sacred

The evaluation pipeline is **read-only**. The agent never modifies how we measure — only what we measure. If it could change the rubric, it would optimize the rubric instead of the prompt.

### 2. One Change, One Experiment

Each experiment modifies one thing. Two changes + improvement = you don't know which helped. Small focused edits beat big rewrites.

### 3. Simplicity Wins

At equal scores, the simpler prompt wins. Removing a rule that doesn't help = a win. Adding 10 lines for 0.05 improvement = not worth it. The best prompt is the shortest one that meets the bar.

### 4. Never Stop

The agent runs autonomously until interrupted. No pausing to ask "should I continue?" The human reviews via email reports. When stuck, the agent re-reads the rubric, tries the opposite approach, or removes instead of adds.

### 5. Git is the Experiment Log

Every change is a commit. Improvements advance the branch; failures get reset. The branch history is a linear chain of validated improvements. `results.tsv` logs everything, including discards.

### 6. Guard Against Overfitting

A prompt tuned on one input may fail on others. Validate against multiple inputs to ensure the prompt generalizes — not just memorizes one case.

# review status: reviewed by Manish on 20-05-2026