# Claude Code CLI Issue — Simplicity Pipeline Evaluator

## Problem

The simplicity pipeline's evaluator calls the Claude Code CLI (`claude`) via subprocess (using `shared/services/claude_code_adapter.py`). Simple prompts work fine, but the evaluator's prompt consistently returns `"Credit balance is too low"` with `duration_api_ms: 0` (meaning the API is never called — the CLI rejects it pre-flight).

## What Works

```bash
# Simple prompts — all work fine
claude -p "say hello" --output-format json --dangerously-skip-permissions --no-session-persistence --max-turns 1
# Returns: {"is_error": false, "result": "Hello!", "duration_api_ms": 2659}

# Long prompts with padding — works up to 20K+ chars
claude -p "Say hello. Ignore padding: AAAA....(20K chars)" --output-format json ...
# Returns: {"is_error": false, "result": "Hello!", "duration_api_ms": 2324}
```

## What Fails

```bash
# The evaluator system prompt — even just line 1 + short conversation
claude -p "You are an expert evaluator of educational content simplicity. Your ONE job: determine whether every explanation card and every tutor message is simple enough... [full prompt from simplicity_evaluator.py] Return JSON: {}" --output-format json --dangerously-skip-permissions --no-session-persistence --max-turns 1
# Returns: {"is_error": true, "result": "Credit balance is too low", "duration_api_ms": 0, "subtype": "success"}
```

Key observations:
- `duration_api_ms: 0` — the API is NEVER called. The CLI rejects before making the request.
- `is_error: true` but `subtype: "success"` — contradictory.
- The user's Claude Code usage shows 7% session / 10% weekly — plenty of capacity.
- The error is NOT length-dependent (20K padding works, 4K evaluator prompt fails).
- The error IS content-dependent — something in the evaluator prompt content triggers it.
- Passing via stdin (`cat file | claude -p -`) also fails with the same error.
- Results were inconsistent during rapid testing (possible rate limiting on top of the content issue).

## The Evaluator Prompt

The full prompt is in: `llm-backend/autoresearch/simplicity_quality/evaluation/simplicity_evaluator.py`

It's the `SIMPLICITY_EVALUATOR_PROMPT` constant (~4.5K chars). It asks Claude to score tutoring sessions for simplicity on a 1-10 scale and flag complex messages.

## How the CLI Is Invoked

File: `shared/services/claude_code_adapter.py`, line 80-96:

```python
cmd = [
    "claude",
    "-p", full_prompt,          # prompt as CLI argument
    "--output-format", "json",
    "--dangerously-skip-permissions",
    "--no-session-persistence",
    "--max-turns", "1",
]
# If reasoning_effort is "high":
cmd.extend(["--effort", "high"])
```

## What to Investigate

1. Why does the CLI return "Credit balance is too low" when the user clearly has capacity?
2. Is there a content-based pre-flight check that's incorrectly rejecting the prompt?
3. Does the `--effort high` flag affect the credit check calculation?
4. Is there a per-session or per-minute rate limit on subprocess CLI invocations?

## Workaround That Works (but user doesn't want)

Running with `--provider openai` bypasses the CLI entirely and uses the OpenAI API (gpt-5.2). This works perfectly:

```bash
./venv/bin/python -m autoresearch.simplicity_quality.run_experiment --skip-server --quick --provider openai --description "baseline" --iteration 0 --email manish@simplifyloop.com
# Result: Simplicity 8/10, cards=7, tutor=8, 12 weighted issues — works end-to-end
```

## What's Ready Once This Is Fixed

Everything else works:
- Session simulation runs fine (captures conversation + prompts)
- Report generation works
- Email reports work
- The full pipeline (simulate → evaluate → report → email) is end-to-end functional
- Just need the claude_code evaluator call to succeed
