# Master Tutor Improvement Initiative

A structured, repeatable workflow for improving the master tutor based on feedback.

## How It Works

Each feedback item goes through 3 phases with a human review gate after Phase 1:

```
Feedback --> Phase 1 (Analysis) --> [Human Review] --> Phase 2 (Implementation) --> Phase 3 (Measurement)
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

### Phase 3: Measurement (`/tutor-improve-measure`)
- Runs 3 baseline evals on `main` (via worktree) in parallel with 3 post-change evals
- Compares scores across 5 dimensions (Responsiveness, Explanation Quality, Emotional Attunement, Pacing, Authenticity)
- Produces before/after report with verdict: SHIP / REVERT / NEEDS-MORE-DATA
- Emails HTML report

## Initiative Folder Structure

Each initiative lives under `initiatives/`:

```
initiatives/
  INIT-001-<short-name>/
    feedback.md                    # Raw feedback
    phase1-analysis.md             # Analysis (gate doc)
    phase2-implementation.md       # Implementation log
    phase3-report.md               # Final report with scores
    phase3-report.html             # Email-ready HTML
    baseline-conversations/        # Before-change eval transcripts
    post-change-conversations/     # After-change eval transcripts
```

## Quick Start

1. **Analyze:** `/tutor-improve-analyze` with `initiative_id: INIT-001-my-issue feedback: "tutor does X wrong"`
2. **Review** the generated `phase1-analysis.md` — decide to proceed or not
3. **Implement:** `/tutor-improve-implement` with `initiative_id: INIT-001-my-issue`
4. **Measure:** `/tutor-improve-measure` with `initiative_id: INIT-001-my-issue`
5. **Review** the final report and verdict

## Relationship to Other Skills

| Skill | Rigor | Human Gates | Use When |
|-------|-------|-------------|----------|
| `/1-percent-better` | Low | None | Hands-off; finds its own problems |
| `/improve-with-feedback` | Medium | None | Quick fix for specific feedback |
| `/tutor-improve-*` (this) | High | Phase 1 review | Important feedback needing measurement |
