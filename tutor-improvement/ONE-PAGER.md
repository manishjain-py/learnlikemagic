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
  Analysis doc      Code changes        3 persona convos
  Root cause        Feature branch      Scored report
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

This is the key differentiator. Claude Code **plays the student** and drives real conversations against the tutor API:
- Plays 3 personas (Struggler, Average, Ace) — 10-12 turns each
- Calls `POST /sessions` and `POST /sessions/{id}/step` directly via REST
- Captures full conversation transcripts
- Evaluates each conversation across 5 dimensions: Responsiveness, Explanation Quality, Emotional Attunement, Pacing, Authenticity
- Specifically checks whether the original feedback issue is fixed

Phase 3 runs as a **subagent** — keeping the main context clean while the subagent drives all conversations, evaluates them, and produces the report.

The output is a scored report with a verdict: **SHIP / REVERT / NEEDS-MORE-DATA**.

## What Makes This Different

| | Quick Fix | This Pipeline |
|---|---|---|
| Human oversight | None | Phase 1 review gate |
| Testing | Hope it works | 3 persona conversations, 5 scoring dimensions |
| Confidence | "Probably better" | Scored report with conversation evidence |
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
      phase3-report.md           # Scored report + verdict
      phase3-report.html         # Emailed to you
      conversations/             # Full conversation transcripts
        struggler-conversation.md
        average-conversation.md
        ace-conversation.md
```

## Built On

- **Tutor REST API** (`POST /sessions`, `POST /sessions/{id}/step`) — Claude Code drives conversations directly
- **Claude Code skills** — each phase is a `/slash-command` that runs autonomously
- **Claude as student + judge** — no separate evaluation pipeline; Claude plays the student and evaluates the results
