# Master Tutor Improvement Initiative

A structured, repeatable workflow for improving the master tutor based on feedback.

## How It Works

Each feedback item goes through 4 phases with human review gates:

```
Feedback --> Phase 1 (Analysis) --> [Human Review] --> Phase 2 (Implementation) --> Phase 2.5 (Code Review) --> Phase 3 (Measurement)
```

### Phase 1: Analysis (`/tutor-improve-analyze`)
- Deep-reads the tutor codebase
- Produces root cause hypothesis, proposed change strategy, risk assessment
- Outputs `phase1-analysis.md` with recommendation: PROCEED / SKIP / NEEDS-DISCUSSION
- **No code changes** — purely analytical

### Phase 2: Implementation (`/tutor-improve-implement`)
- Creates a feature branch
- Implements changes per Phase 1 strategy
- Runs tests, self code-review
- Outputs `phase2-implementation.md`

### Phase 2.5: Code Review (`/tutor-improve-review`)
- Reads all changed files in full + diffs
- Reviews for functional correctness (logic errors, edge cases, type safety, async issues)
- Reviews for regression risks (broken callers, state loss, logging gaps, API contract changes)
- Cross-checks against Phase 1 risk predictions
- Outputs `phase2.5-review.md` with verdict: PASS / PASS WITH FIXES / FAIL
- **No code changes** — purely a review

### Phase 3: Measurement (`/tutor-improve-measure`)
- Claude Code plays 3 student personas (Struggler, Average, Ace) by calling the tutor REST API directly
- Drives 10-12 turn conversations per persona, captures full transcripts
- Evaluates each conversation across 5 dimensions (Responsiveness, Explanation Quality, Emotional Attunement, Pacing, Authenticity)
- Assesses whether the original feedback issue is fixed
- Produces scored report with verdict: SHIP / REVERT / NEEDS-MORE-DATA
- Emails HTML report

## Initiative Folder Structure

Each initiative lives under `initiatives/`:

```
initiatives/
  INIT-001-<short-name>/
    feedback.md                    # Raw feedback
    phase1-analysis.md             # Analysis (gate doc)
    phase2-implementation.md       # Implementation log
    phase2.5-review.md             # Code review (correctness + regression)
    phase3-report.md               # Final report with scores
    phase3-report.html             # Email-ready HTML
    conversations/                 # Phase 3 eval transcripts
      struggler-conversation.md
      average-conversation.md
      ace-conversation.md
```

## Quick Start

1. **Analyze:** `/tutor-improve-analyze` with `initiative_id: INIT-001-my-issue feedback: "tutor does X wrong"`
2. **Review** the generated `phase1-analysis.md` — decide to proceed or not
3. **Implement:** `/tutor-improve-implement` with `initiative_id: INIT-001-my-issue`
4. **Code Review:** `/tutor-improve-review` with `initiative_id: INIT-001-my-issue`
5. **Fix** any required issues from the review, then proceed
6. **Measure:** `/tutor-improve-measure` with `initiative_id: INIT-001-my-issue`
7. **Review** the final report and verdict

## Relationship to Other Skills

| Skill | Rigor | Human Gates | Use When |
|-------|-------|-------------|----------|
| `/tutor-improve-*` (this) | High | Phase 1 review | Important feedback needing measurement |
