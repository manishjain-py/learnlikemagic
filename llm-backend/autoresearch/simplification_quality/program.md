# Simplification Quality Auto-Research

## Goal
Improve the quality of simplified explanation cards generated when students tap "I didn't understand."

## What you're optimizing
The prompt and directives that control how the tutor generates re-explanations:
- `tutor/prompts/master_tutor_prompts.py` → `SIMPLIFY_CARD_PROMPT`
- `tutor/agents/master_tutor.py` → `REASON_MAP` directives

## What you MUST NOT modify
- `autoresearch/simplification_quality/evaluation/` — the evaluator is sacred
- `autoresearch/simplification_quality/run_experiment.py` — the runner is sacred
- `autoresearch/simplification_quality/email_report.py` — reports are sacred

## Scoring dimensions (each 1-10)
1. **reason_adherence** — Does the simplified card address the student's specific feedback?
2. **content_differentiation** — Is it genuinely different from the original (and previous attempts)?
3. **simplicity** — Simple enough for the grade level?
4. **concept_accuracy** — Still explains the same concept correctly?
5. **presentation_quality** — Clean title, no meta-commentary, good structure?

## Experiment command
```bash
cd llm-backend && ./venv/bin/python -m autoresearch.simplification_quality.run_experiment \
  --skip-server --email manish@simplifyloop.com --iteration {N} --description "{hypothesis}"
```

## Iteration protocol
1. Read the latest `evaluation.json` from the most recent run in `/tmp/simplification_quality_runs/`.
2. Identify the weakest dimension and specific issues.
3. Form ONE focused hypothesis (e.g., "Add explicit instruction to include a concrete example when reason is 'example'").
4. Make ONE edit to the prompt files. `git add` + `git commit`.
5. Run the experiment command. Wait for completion.
6. Read the `---` block output. Extract `avg_score`.
7. If score improved → KEEP. If not → `git reset --hard HEAD~1` (DISCARD).
8. Update `results.tsv`: change `pending` → `keep` or `discard`.
9. Read the new `evaluation.json` to inform the next iteration.
10. Repeat.
