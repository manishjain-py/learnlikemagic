# Book Ingestion Quality

Optimizes the **topic extraction pipeline** — how book chapters are broken into teachable topics (granularity, coverage, copyright safety).

## What It Improves

Extraction prompts in: `book_ingestion_v2/` pipeline

## How It Works

1. Runs extraction pipeline on a chapter (or loads existing topics from DB)
2. LLM judge reads OCR'd original pages alongside extracted topics
3. Scores across 3 dimensions, identifies root causes of issues
4. Supports multiple runs per experiment to reduce variance (~0.6 → ~0.35)

## Evaluation Dimensions (1-10 each, averaged)

| Dimension | What It Measures |
|-----------|-----------------|
| Granularity | Proper topic splitting — no over/under-splitting |
| Coverage Depth | Guidelines are rich and complete, not shallow summaries |
| Copyright Safety | No verbatim copying, proper paraphrasing |

## Root Cause Categories

over_splitting, under_splitting, missing_coverage, shallow_guidelines, verbatim_copy, paraphrase_copy, wrong_scope, missing_prerequisites, missing_misconceptions, sequence_error

## Key Details

- **No student persona** — evaluates content quality directly
- **Throughput:** ~8-10 experiments/hour
- **Results:** `results.tsv`
