# Master Tutor Improvement Initiative — Plan

## Overview

A structured, repeatable workflow for improving the master tutor based on feedback. Each feedback item goes through 3 phases with human review gates between them. Multiple feedback items are tracked as separate initiatives over time.

This is the **high-rigor path** — deliberate, tracked improvements with before/after measurement. The existing `/1-percent-better` and `/improve-with-feedback` skills remain as quick-run alternatives.

---

## Core Concept

**Input:** A feedback item (something not working well for the master tutor)

**Output:** A measured, scored report showing whether addressing the feedback improved the student experience

**Flow:**
```
Feedback --> Phase 1 (Analysis) --> [Human Review Gate] --> Phase 2 (Implementation) --> Phase 3 (Measurement & Report)
```

---

## Existing Infrastructure We Build On

### Evaluation Pipeline (`llm-backend/autoresearch/tutor_teaching_quality/evaluation/`)
- Student simulation with personas (struggler, average, ace)
- LLM judge scoring across 5 dimensions: Responsiveness, Explanation Quality, Emotional Attunement, Pacing, Authenticity
- Problem detection with root causes and severity
- Entry point: `python -m autoresearch.tutor_teaching_quality.evaluation.run_evaluation --topic-id <ID> --persona <FILE> --skip-server`

### Master Tutor Architecture (key files)
- `llm-backend/tutor/agents/master_tutor.py` — Single LLM-powered agent
- `llm-backend/tutor/prompts/master_tutor_prompts.py` — System + turn prompts (most sensitive file)
- `llm-backend/tutor/orchestration/orchestrator.py` — Control flow: safety check -> master tutor -> state updates
- `llm-backend/tutor/prompts/orchestrator_prompts.py` — Orchestrator prompts
- `llm-backend/tutor/models/session_state.py` — Session state (mastery, misconceptions, explanation phases)
- `llm-backend/tutor/services/session_service.py` — Business logic

### Existing Related Skills
- `/1-percent-better` — Autonomous: baseline eval -> analyze -> fix -> re-eval -> compare. No feedback input; finds its own problems.
- `/improve-with-feedback` — Autonomous: feedback -> custom persona -> fix -> eval -> report. Single-shot, no baseline comparison.

---

## Folder Structure

```
tutor-improvement/
  README.md                              # Initiative overview, how phases work
  index.md                               # Running index of all initiatives + verdicts
  templates/
    phase1-analysis.md                   # Template for analysis output
    phase2-implementation.md             # Template for implementation log
    phase3-report.md                     # Template for final report
  initiatives/
    INIT-001-<short-name>/
      feedback.md                        # Raw feedback captured
      phase1-analysis.md                 # Analysis output (gate doc)
      phase2-implementation.md           # Implementation log
      phase3-report.md                   # Final report with scores
      phase3-report.html                 # Email-ready HTML version
      baseline-conversations/            # Before-change eval transcripts
      post-change-conversations/         # After-change eval transcripts
    INIT-002-<short-name>/
    ...
```

---

## Phase 1: Analysis (`/tutor-improve-analyze`)

**Input:** `initiative_id: INIT-XXX-<name> feedback: "<feedback text>"`

**Process:**
1. Create initiative folder under `tutor-improvement/initiatives/` + save raw feedback
2. Deep-read master tutor code: `master_tutor.py`, `master_tutor_prompts.py`, `orchestrator.py`, `orchestrator_prompts.py`, session state models
3. Analyze feedback against current architecture
4. Produce `phase1-analysis.md` containing:
   - **Feedback Summary** — what's reported
   - **Current Behavior** — how the code handles this today (with file:line refs)
   - **Root Cause Hypothesis** — why it happens
   - **Proposed Change Strategy** — what to modify and how
   - **Impact Prediction** — High/Medium/Low improvement expected
   - **Risk Assessment** — what could regress, which working behaviors to protect
   - **Recommendation: PROCEED / SKIP / NEEDS-DISCUSSION**
5. Update `index.md` with the new initiative entry

**Key:** This skill does NOT implement anything. Purely analytical. Human reviews the output and decides whether to proceed.

**Sub-agents:** None (single agent — analysis is sequential reading + reasoning)

---

## Phase 2: Implementation (`/tutor-improve-implement`)

**Input:** `initiative_id: INIT-XXX-<name>`

**Process:**
1. Read `phase1-analysis.md` — verify recommendation is PROCEED
2. Create branch `tutor-improve/INIT-XXX-<name>`
3. Implement changes following the Phase 1 strategy
4. Self code-review (check for regressions against Phase 1 risk assessment)
5. Run `pytest tests/ -x -q`
6. Produce `phase2-implementation.md` containing:
   - Files changed + diffs summary
   - Code review findings
   - Test results
   - Deviations from Phase 1 plan (if any)
7. Commit changes on branch

**Sub-agents:** None (single agent — implementation needs tight context)

---

## Phase 3: Measurement & Report (`/tutor-improve-measure`)

**Input:** `initiative_id: INIT-XXX-<name>`

**Process:**
1. Read Phase 1 + Phase 2 docs for context
2. Run 3 baseline eval sessions on `main` (via worktree isolation) — struggler, average, ace personas
3. Run 3 post-change eval sessions on feature branch — same personas
4. Uses existing evaluation pipeline (`run_evaluation.py`) for all runs
5. Collect full conversation transcripts into `baseline-conversations/` and `post-change-conversations/`
6. Compare scores across all 5 dimensions
7. Produce `phase3-report.md` containing:
   - **End-to-End Summary** — feedback -> analysis -> implementation -> measurement
   - **Before/After Score Table** (per persona, per dimension)
   - **Key Conversation Evidence** — excerpts showing the feedback issue before vs. after
   - **Feedback-Specific Assessment** — was the original issue fixed?
   - **Improvement Score** — average delta across dimensions
   - **Confidence Level** — High (consistent improvement across all personas), Medium (improvement in most), Low (mixed/inconsistent)
   - **Verdict: SHIP / REVERT / NEEDS-MORE-DATA**
8. Generate HTML report, email it
9. Update `index.md` with final verdict + scores

**Sub-agents:** 2 parallel agents
- Agent A (worktree on main): Run 3 baseline eval sessions
- Agent B (current branch): Run 3 post-change eval sessions
- Main agent: Wait for both, then compare and produce final report

---

## Sub-Agent Strategy Summary

| Phase | Sub-Agents | Reasoning |
|-------|-----------|-----------|
| Phase 1 | None (single) | Analysis is sequential reading + reasoning |
| Phase 2 | None (single) | Implementation needs tight context of changes |
| Phase 3 | 2 parallel | Baseline (worktree) + post-change can run simultaneously |

---

## Relationship to Existing Skills

| Skill | Purpose | When to Use |
|-------|---------|-------------|
| `/1-percent-better` | Quick autonomous improvement loop | Hands-off; finds its own problems |
| `/improve-with-feedback` | Quick single-shot fix | Fast turnaround on specific feedback |
| New 3-phase initiative | Deliberate tracked improvement | Important feedback requiring rigor, measurement, and human review gates |

---

## Open Design Decisions

1. **Eval sessions per phase:** Currently 3 (one per persona). Could increase to 2 runs x 3 personas = 6 for noise reduction.
2. **Hard gate on Phase 1:** If analysis says SKIP, should Phase 2 skill refuse to run? Or trust user to decide?
3. **Email frequency:** Currently only Phase 3. Could also email Phase 1 analysis for async review.
4. **Initiative naming:** Using `INIT-001-<name>` format. Open to alternatives.

---

## To Build (When Resuming)

1. Create `tutor-improvement/` folder structure with README, index, templates
2. Create `.claude/commands/tutor-improve-analyze.md` (Phase 1 skill)
3. Create `.claude/commands/tutor-improve-implement.md` (Phase 2 skill)
4. Create `.claude/commands/tutor-improve-measure.md` (Phase 3 skill)
5. Test with a real feedback item end-to-end
