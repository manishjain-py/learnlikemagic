# Master Tutor Improvement Initiative — One Pager

## The Problem

Our AI tutor gets feedback from real usage ("tutor praises too much", "moves too fast for struggling students", etc.). We need a structured way to turn feedback into measurable improvements — not just code changes we *hope* work.

## The Solution: 3-Phase Improvement Pipeline

Every feedback item goes through three phases, with a human review gate after analysis.

```
  FEEDBACK
     |
     v
 +-----------+      +-----------+      +-----------+
 | Phase 1   | ---> | Phase 2   | ---> | Phase 3   |
 | ANALYZE   | gate | IMPLEMENT |      | MEASURE   |
 +-----------+      +-----------+      +-----------+
     |                   |                   |
  Analysis doc      Code changes        Before/after
  Root cause        Feature branch      score report
  Recommendation    Tests passing       SHIP/REVERT
```

### Phase 1: Analyze (`/tutor-improve-analyze`)

Claude reads the entire tutor codebase, maps the feedback to specific code/prompt issues, and produces an analysis doc with:
- Root cause hypothesis
- Proposed change strategy
- Risk assessment (what could break)
- Recommendation: **PROCEED / SKIP / NEEDS-DISCUSSION**

**You review this before anything changes.** This is the human gate.

### Phase 2: Implement (`/tutor-improve-implement`)

Claude creates a feature branch, makes the targeted code/prompt changes following the Phase 1 strategy, runs tests, and documents everything.

### Phase 3: Measure (`/tutor-improve-measure`)

This is the key differentiator. Claude runs the same evaluation pipeline on **both** the old code (main) and the new code (feature branch):
- 3 simulated student personas: Struggler, Average, Ace
- 5 scoring dimensions: Responsiveness, Explanation Quality, Emotional Attunement, Pacing, Authenticity
- LLM judge scores each conversation

The output is a before/after score table with a verdict: **SHIP / REVERT / NEEDS-MORE-DATA**.

## What Makes This Different

| | Quick Fix | This Pipeline |
|---|---|---|
| Human oversight | None | Phase 1 review gate |
| Baseline measurement | None | Before/after scores |
| Confidence | "Probably better" | Scored across 3 personas, 5 dimensions |
| Traceability | Ad hoc | Initiative folder with full history |
| Reversibility | Unclear | Clear verdict, feature branch |

## How to Use It

```
/tutor-improve-analyze   initiative_id: INIT-001-praise-cal feedback: "tutor praises every answer even when wrong"
                         --> review the analysis doc
/tutor-improve-implement initiative_id: INIT-001-praise-cal
/tutor-improve-measure   initiative_id: INIT-001-praise-cal
                         --> review the final report, merge or discard
```

## Where Things Live

```
tutor-improvement/
  index.md                       # All initiatives at a glance
  initiatives/
    INIT-001-praise-cal/
      feedback.md                # Original feedback
      phase1-analysis.md         # Analysis (review this!)
      phase2-implementation.md   # What changed
      phase3-report.md           # Before/after scores + verdict
      phase3-report.html         # Emailed to you
```

## Built On

- **Evaluation pipeline** (`llm-backend/evaluation/`) — student simulation with personas + LLM judge scoring
- **Claude Code skills** — each phase is a `/slash-command` that runs autonomously
- **Git worktrees** — Phase 3 runs baseline evals on `main` in parallel with post-change evals on the feature branch
