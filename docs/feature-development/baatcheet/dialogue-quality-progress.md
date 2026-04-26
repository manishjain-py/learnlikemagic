# Baatcheet Dialogue Quality — Progress Tracker

**Plan:** `dialogue-quality-impl-plan.md`
**Last updated:** 2026-04-26
**Branch:** `docs/baatcheet-dialogue-quality-plan`
**PR:** #122

## Status

| # | Item | Status |
|---|---|---|
| 1 | Plan doc | done |
| 2 | Progress tracker | done |
| 3 | Principles doc — `docs/principles/baatcheet-dialogue-craft.md` | pending |
| 4 | CLAUDE.md — index entry for new principles doc | pending |
| 5 | Layer 1 — adapter `effort_map` fix (5 distinct levels) | pending |
| 6 | Layer 1 — Baatcheet service bump to `reasoning_effort="max"` | pending |
| 7 | Layer 4 — `reasoning_effort` schema migration on `llm_config` | pending |
| 8 | Layer 4 — `LLMConfigService` returns `reasoning_effort` | pending |
| 9 | Layer 4 — `LLMService.from_config()` plumbs `reasoning_effort` | pending |
| 10 | Layer 4 — LLM Config admin UI dropdown | pending |
| 11 | Layer 4 — `review_rounds` surfaced on topic pipeline admin | pending |
| 12 | Few-shot exemplars draft (1 GOOD annotated + 1 BAD) | pending |
| 13 | Layer 2 — generation prompt craft directives | pending |
| 14 | Layer 2 — exemplars wired into prompt file | pending |
| 15 | Layer 2 — decouple inputs (key concepts list, no variant A spine) | pending |
| 16 | Layer 3 — refine prompt rewrite (defects + coverage + naturalness) | pending |
| 17 | Unit tests | pending |
| 18 | Local regen + manual review (Math G4 Ch1 T1) | pending |
| 19 | PR title/body update to reflect full scope | pending |

## Updates

### 2026-04-26 — Interview alignment + plan locked
- 12 alignment Qs answered. Decisions locked in `dialogue-quality-impl-plan.md` §2.
- Plan doc + tracker created.
- Single-PR strategy locked. All four layers + docs ride on PR #122.
- Next: principles doc, then Layer 1.
