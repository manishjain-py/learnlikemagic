# Session Experience

Optimizes **end-to-end session naturalness** — how the full flow (welcome → cards → interactive → end) feels from the student's perspective.

## What It Improves

Same surface as tutor_teaching_quality: `master_tutor_prompts.py`, `master_tutor.py`, `session_service.py`

## How It Works (3-stage evaluation)

1. **Simulate** — Run full sessions across 3 rotating topics, capture transcript + prompts
2. **Evaluate** — Naturalness judge flags specific unnatural messages with severity + category
3. **Analyze** — Prompt analyzer traces each flagged message back to the prompt instruction causing it

## Metrics (both must improve to keep a change)

| Metric | Direction | What It Measures |
|--------|-----------|-----------------|
| Naturalness Score | Higher (1-10) | Overall conversation flow across all topics |
| Weighted Issue Count | Lower | `critical×3 + major×2 + minor×1` |

## Issue Categories (12)

forced_transition, overwhelming, unnatural_language, complexity_mismatch, emotional_disconnect, repetitive_pattern, abrupt_shift, card_disconnect, robotic_structure, false_ok_missed, information_dump, premature_advance

## Key Details

- **Topic pool:** 6 topics with pre-computed explanations (3-/4-digit addition, place value, fact families, problem solving)
- **Throughput:** ~8-10 experiments/hour (3 topics per iteration)
- **Results:** `results.tsv`
