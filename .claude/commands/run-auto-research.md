# Run Auto-Research — Autonomous Prompt Optimization Loop

You are an autonomous AI researcher running the autoresearch loop. You iteratively improve
prompts by: reading evaluation feedback → forming a hypothesis → modifying prompt files →
running an evaluation → keeping changes that improve the score → repeating.

## Input

**Arguments format:** `<pipeline> <iterations> [email]`

- `pipeline`: which pipeline to optimize — `tutor` or `topic-extraction`
- `iterations`: number of experiment iterations to run (e.g., `3`, `10`, `overnight`)
  - `overnight` = run indefinitely (loop forever until stopped)
- `email`: optional override — defaults to `manish@simplifyloop.com`

**Examples:**
- `/run-auto-research tutor 5`
- `/run-auto-research topic-extraction 3 manish@simplifyloop.com`
- `/run-auto-research tutor overnight`

Parse `$ARGUMENTS` to extract these. If pipeline is missing, ask the user which one.

---

## Pipeline Registry

### Pipeline: `tutor` (Tutor Teaching Quality)

| Setting | Value |
|---------|-------|
| Program file | `llm-backend/autoresearch/tutor_teaching_quality/program.md` |
| Run command | `cd llm-backend && ./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment --skip-server --description "<DESC>" --iteration <N> --email <EMAIL>` |
| Results file | `llm-backend/autoresearch/tutor_teaching_quality/results.tsv` |
| Modifiable (primary) | `llm-backend/tutor/prompts/master_tutor_prompts.py` |
| Modifiable (secondary) | `llm-backend/tutor/prompts/clarify_doubts_prompts.py`, `llm-backend/tutor/prompts/orchestrator_prompts.py` |
| Read-only | `llm-backend/autoresearch/tutor_teaching_quality/evaluation/` — fixed metric |
| Metric | 5-dimension avg (responsiveness, explanation_quality, emotional_attunement, pacing, authenticity) |
| Time per experiment | ~5-8 minutes |
| Prerequisite | Server running: `curl -s http://localhost:8000/health/db` must return OK |

### Pipeline: `topic-extraction` (Book Ingestion Quality)

| Setting | Value |
|---------|-------|
| Run command | `cd llm-backend && ./venv/bin/python -m autoresearch.book_ingestion_quality.run_experiment --chapter-id <CHAPTER_ID> --description "<DESC>" --email <EMAIL>` |
| Results file | `llm-backend/autoresearch/book_ingestion_quality/evaluation/results.tsv` |
| Modifiable (primary) | `llm-backend/book_ingestion_v2/prompts/chunk_topic_extraction.txt` |
| Modifiable (secondary) | `llm-backend/book_ingestion_v2/prompts/chapter_consolidation.txt`, `llm-backend/book_ingestion_v2/prompts/topic_guidelines_merge.txt` |
| Read-only | `llm-backend/autoresearch/book_ingestion_quality/evaluation/` — fixed metric |
| Metric | 3-dimension avg (granularity, coverage_depth, copyright_safety) |
| Time per experiment | ~10-15 minutes |
| Chapter ID | Resolve from most recent run config in `llm-backend/autoresearch/book_ingestion_quality/evaluation/runs/` — read `config.json` from the latest run directory to get `chapter_id` |

---

## Process

### Step 0: Parse arguments and validate

Parse `$ARGUMENTS` into `pipeline`, `iterations`, and `email` (default: `manish@simplifyloop.com`).

If `iterations` is `overnight`, set a very large number (999) and loop until stopped.

### Step 1: Read current state

1. **Read the results file** for the pipeline to understand the experiment history:
   - What's the current best score (the last `keep` or `baseline` entry)?
   - What experiments were tried recently? What was kept vs discarded?
   - What's the score variance? (Look for `variance-check` entries)

2. **Read the latest evaluation** to understand what's wrong:
   - Find the most recent run directory with an `evaluation.json`
   - Read the problems, per-topic assessment, and dimension analysis
   - Identify the weakest dimension — that's your primary target

3. **Read the modifiable prompt files** — understand what you're working with.

4. **Read the evaluation rubric** to understand what scores 9-10 vs 7-8 for each dimension:
   - Tutor: `llm-backend/autoresearch/tutor_teaching_quality/evaluation/evaluator.py`
   - Topic extraction: `llm-backend/autoresearch/book_ingestion_quality/evaluation/prompts/judge.txt`

5. **For tutor pipeline**: Read Riya's persona file:
   `llm-backend/autoresearch/tutor_teaching_quality/evaluation/personas/average_student.json`

### Step 2: Check prerequisites

**Tutor pipeline:**
```bash
curl -s http://localhost:8000/health/db
```
If not running, tell the user: "Start the server first: `cd llm-backend && ./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000`"
Do NOT proceed until the server is healthy.

**Topic extraction pipeline:**
No server needed. Verify DB access:
```bash
cd llm-backend && ./venv/bin/python -c "from database import get_db_manager; db = get_db_manager().session_factory(); print('DB OK'); db.close()"
```

### Step 3: Create branch

```bash
TAG=$(date +%b%d | tr '[:upper:]' '[:lower:]')
git checkout -b autoresearch/$TAG 2>/dev/null || echo "Branch exists, continuing"
```

### Step 4: The Experiment Loop

For each iteration (1 to N):

#### 4a. Form a hypothesis

Based on the evaluation feedback, pick ONE focused improvement:
- Target the **weakest dimension** first
- Read the specific problems and per-topic assessments
- Think about what ONE prompt change could address the top problem
- **Small beats big** — one focused rule change, not a rewrite

Strategy progression:
- **Early iterations**: Target the lowest-scoring dimension. Fix the most critical problem.
- **Mid iterations**: Target specific patterns from evaluation (e.g., false OK detection, umbrella topics)
- **Late iterations**: Try creative approaches, removal experiments, phrasing variations

#### 4b. Edit prompt file(s)

Make ONE focused change to a modifiable prompt file. Commit it:
```bash
git add <changed-files>
git commit -m "<short description of the hypothesis>"
```

#### 4c. Run experiment

**Tutor:**
```bash
cd llm-backend && ./venv/bin/python -m autoresearch.tutor_teaching_quality.run_experiment \
    --skip-server \
    --description "<hypothesis description>" \
    --iteration <N> \
    --email <EMAIL> 2>&1
```

**Topic extraction:**
```bash
cd llm-backend && ./venv/bin/python -m autoresearch.book_ingestion_quality.run_experiment \
    --chapter-id <CHAPTER_ID> \
    --description "<hypothesis description>" \
    --email <EMAIL> 2>&1
```

**IMPORTANT**: Always use `./venv/bin/python`, NOT bare `python`. The system `python` alias lacks project dependencies.

The experiment will take 5-15 minutes. Wait for it to complete.

#### 4d. Read results

Extract `avg_score` from the output. Compare to the current best score.

#### 4e. Keep or discard

**KEEP** when:
- Score improved (even by 0.01)
- Significant improvement in one dimension without hurting others
- Simplification win: removing prompt content and getting equal score

**DISCARD** when:
- Score equal or worse (and not a simplification)

If DISCARD:
```bash
git reset --hard HEAD~1
```

Log the result to the pipeline's results.tsv (the experiment runner logs a `pending` entry; update the status to `keep` or `discard` by appending a new row with the correct status).

#### 4f. Read the new evaluation

After each experiment, read the evaluation.json from the latest run directory to understand:
- What improved or regressed
- What problems remain
- What to try next

This feeds back into step 4a for the next iteration.

### Step 5: Report

After all iterations complete, print a summary table:

```
| # | Hypothesis | Score | Dims | Verdict |
|---|-----------|-------|------|---------|
| 1 | description | 7.5   | g:7 c:8 s:9 | KEEP |
| 2 | description | 7.0   | g:6 c:7 s:8 | DISCARD |
```

And a summary: how many iterations, how many kept, final best score, what the main bottleneck is.

---

## Key Rules

1. **NEVER modify evaluation code.** The evaluator is the ground truth.
2. **ONE change per iteration.** Two changes + improvement = you don't know which helped.
3. **Always use `./venv/bin/python`** — bare `python` is system Python without dependencies.
4. **Always include `--email`** — the human monitors progress via email on their phone.
5. **Read evaluation feedback between iterations** — don't just blindly try things.
6. **Keep template variables intact** — `{grade}`, `{topic_name}`, `{chapter_page_range}` etc. must stay.
7. **Don't break JSON output format** in prompts that produce structured output.
8. **If you run out of ideas**: re-read the evaluation rubric, read conversation transcripts, try the opposite of what you've been doing, try removing things instead of adding.

## NEVER STOP (for overnight runs)

Once the loop begins, do NOT pause to ask "should I continue?" The human might be
asleep. You are autonomous. The loop runs until the iteration count is reached or
the human interrupts you.

## Automation Rules

- Do NOT use EnterPlanMode or AskUserQuestion during the loop
- Do NOT pause for confirmation between iterations
- Execute everything end-to-end autonomously
- If an experiment crashes, log it and move to the next iteration
- If git operations fail, investigate and fix before continuing
