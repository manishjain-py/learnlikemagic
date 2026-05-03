# Docs Update Changelog

Run date: 2026-05-03
Branch: `claude/update-all-docs-HlD8l`
Skill: `/update-all-docs`

## Summary

8 specialized agents (7 main + 1 gap-fill for Practice Mode) audited their assigned docs against current code. Most docs were already current after recent refresh commits (`123bb9a`, `1b552b8`). Only minor targeted edits applied — no rewrites, no new docs created.

## Updated Docs

| Doc | Change | Why |
|-----|--------|-----|
| `docs/functional/scorecard.md` | Clarified `total_sessions` counts teach_me + clarify_doubts (not practice attempts) | Removed ambiguity vs. practice attempts |
| `docs/functional/practice-mode.md` | Updated review-card description: 2-3 sentence rationale (≤60 words) targeting misconception, with anchor | Matches commit `9e5b6c3` (richer practice-grading feedback) |
| `docs/technical/architecture-overview.md` | Refined autoresearch flat-layout exception note (file set varies per pipeline) | Pipeline-specific filenames (`pipeline_runner.py`, `simplicity_evaluator.py`, etc.) vary |
| `docs/technical/book-guidelines.md` | Added `DELETE .../chapters/{chapter_id}/topics/{topic_id}` to endpoints table | Endpoint exists in `processing_routes.py:435` for pre-sync topic cleanup |
| `docs/technical/evaluation.md` | Noted `EvalConfig.evaluator_reasoning_effort` is unread (hardcoded `"high"` in `evaluator.py`) | Matches existing parallel note for unused simulator fields |
| `docs/technical/learning-session.md` | 4 edits: post-completion gating (is_complete + extension exhausted), `llm.call_fast()` translation, visuals_enabled flag wiring, Baatcheet welcome-skip in WS flow | Matches refactored orchestrator + flag plumbing |
| `docs/technical/practice-mode.md` | Corrected prompt-vs-schema location (`FREE_FORM_GRADING_PROMPT` + `PER_PICK_RATIONALE_PROMPT`; Pydantic schemas in service file) | File-layout accuracy |
| `docs/technical/scorecard.md` | Clarified `get_report_card` and `get_topic_progress` scope (teach_me+clarify, no practice; teach_me-only) | Method-doc precision |

## Newly Created Docs

None. All discovered functionality already covered by existing docs.

## Coverage Matrix

| Feature / Module | Functional Doc | Technical Doc |
|-----------------|----------------|---------------|
| App overview, routes, tech stack | `app-overview.md` | `architecture-overview.md` |
| Tutor / learning sessions (teach_me, baatcheet, clarify) | `learning-session.md` | `learning-session.md` |
| Tutor evaluation pipeline | `evaluation.md` | `evaluation.md` |
| Student progress / report card | `scorecard.md` | `scorecard.md` |
| Let's Practice (drill flow, grading) | `practice-mode.md` | `practice-mode.md` |
| Book ingestion / guideline → study plan | `book-guidelines.md` | `book-guidelines.md` |
| Auth + onboarding (Cognito, signup, profile, enrichment) | `auth-and-onboarding.md` | `auth-and-onboarding.md` |
| Local dev + testing | N/A (developer-only) | `dev-workflow.md` |
| AWS infra + Terraform + CI/CD | N/A | `deployment.md` |
| DB schema + migrations | N/A | `database.md` |
| LLM prompt catalog | N/A | `llm-prompts.md` |
| Agent context files | N/A | `ai-agent-files.md` |
| Autoresearch | N/A | `auto-research/overview.md` |
| New machine setup | N/A | `new-machine-setup.md` |

## Master Index

No changes required — all updated docs already listed in `docs/DOCUMENTATION_GUIDELINES.md`. No new files, no renames.

## Deferred Items

- `tutor/services/practice_grading_service.py` lines 39, 43: stale "One-sentence" Pydantic field docstrings (code-side drift, not doc). Out of scope.
- `docs/technical/llm-prompts.md`, `ai-agent-files.md`, `audio-typewriter-bug-analysis.md`, `aws-cost-optimization.md`, `auto-research/overview.md`, `new-machine-setup.md`: not assigned to any agent this run. Last touched 2026-04-27. Spot-check shows no major drift; full audit deferred to next run.

## Files Modified

```
docs/functional/practice-mode.md
docs/functional/scorecard.md
docs/technical/architecture-overview.md
docs/technical/book-guidelines.md
docs/technical/evaluation.md
docs/technical/learning-session.md
docs/technical/practice-mode.md
docs/technical/scorecard.md
```

8 files, 14 insertions(+), 14 deletions(-)
