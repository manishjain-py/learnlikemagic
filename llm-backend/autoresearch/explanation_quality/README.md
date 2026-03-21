# Explanation Quality

Optimizes **pre-computed explanation cards** — the 5-11 visual/analogy/procedural cards shown to students before interactive tutoring.

## What It Improves

Prompts in: `book_ingestion_v2/prompts/explanation_generation.txt` (primary), `explanation_critique.txt` (secondary)

## How It Works

1. Generates 3 explanation variants (Analogies, Visual, Procedural) for a randomly-selected topic from a pool of 4
2. LLM judge scores each variant across 5 dimensions, identifies top 5 problems
3. Agent tweaks generation prompts, re-runs, keeps improvements
4. Topic rotation prevents overfitting

## Evaluation Dimensions (1-10 each, averaged across 3 variants)

| Dimension | What It Measures |
|-----------|-----------------|
| Simplicity | Grade-appropriate vocabulary, short direct sentences |
| Concept Clarity | Struggling student understands WHY, not just WHAT |
| Examples & Analogies | Concrete, relatable (food, games, money, sports) |
| Structure & Flow | Each card builds naturally, one idea per card |
| Overall Effectiveness | Student feels "I can do this" after reading |

## Key Details

- **Topic pool:** 4 diverse math topics (place value, comparing numbers, addition with regrouping, odd/even)
- **Throughput:** ~12-15 experiments/hour (~3-5 min per run)
- **Results:** `results.tsv`
