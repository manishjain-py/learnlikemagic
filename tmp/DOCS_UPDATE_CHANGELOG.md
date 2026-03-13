# Documentation Update Changelog

**Date:** 2026-03-13
**Trigger:** `/update-all-docs` skill execution

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added "Visual Explanations (PoC)" to Core Features table; added step 7 to Admin user journey for visual explanations |
| `docs/technical/architecture-overview.md` | Updated architecture diagram and module structure for pixi_poc router; added pixi poc to Routers table; added VisualExplanation.tsx and PixiJsPocPage.tsx to frontend components; added /admin/pixi-js-poc to Route Map; documented streaming (call_stream()), fast model (call_fast()), and prompt caching provider features |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Added Visual Illustrations section documenting interactive diagram/animation generation alongside text responses |
| `docs/technical/learning-session.md` | Fixed architecture diagram to show parallel execution (translation + safety via asyncio.gather); added visual_explanation field and VisualExplanation sub-schema to TutorTurnOutput; reordered orchestration flow (post-completion check first); added Streaming Path subsection (process_turn_stream(), 3 yield types); updated teaching rules 12→13 (rule 13: visual explanations); added token and visual_update WebSocket message types; updated Key Files (orchestrator.py, master_tutor.py, messages.py); added pixi_code_generator.py; added Pixi Code Gen to LLM Calls table |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | Updated persona selector: UI now has dropdown (was CLI-only) |
| `docs/technical/evaluation.md` | Added token and visual_update to WebSocket message types; replaced stale root cause suggestion table with current code values; added GET /api/evaluation/personas endpoint; updated frontend persona selector description |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | No changes needed — fully accurate |
| `docs/technical/scorecard.md` | No changes needed — fully accurate |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Added `approved` topic status; added study plan metadata (duration, difficulty, theme); documented mid-session feedback plan regeneration |
| `docs/technical/book-guidelines.md` | Documented TopicStatus enum progression (draft→consolidated→final→approved); added 3 study plan prompt files to LLM Prompts table; expanded Generator section (prompt loading, schema enforcement, output structure, StudentContext, generate_plan_with_feedback()); expanded Orchestrator section (4-step flow, improvement fallback); updated Database Tables for study_plans; updated Key Files (entities.py, generator_service.py, prompt files) |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Fixed onboarding greeting fallback logic (preferredName || name) |
| `docs/technical/auth-and-onboarding.md` | Updated EnrichmentService.has_meaningful_data() field list; added about_me to compute_inputs_hash(); documented should_regenerate() method |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/dev-workflow.md` | Fixed sample_goal fixture description (syllabus field); fixed curl example (topic→chapter, added required fields) |
| `docs/technical/deployment.md` | No changes needed — fully accurate |
| `docs/technical/database.md` | Fixed migration step 15 description: _apply_focus_mode_column() also resets FALSE→TRUE |

---

## Newly Created Docs

None — all changes fit into existing documentation files.

---

## Unchanged Docs (verified current)

| Doc | Reason |
|-----|--------|
| `docs/functional/scorecard.md` | All claims match current code |
| `docs/technical/scorecard.md` | All claims match current code |
| `docs/technical/deployment.md` | All infra details match current Terraform/CI/CD/Docker |
| `docs/DOCUMENTATION_GUIDELINES.md` | Master index unchanged (no new docs added) |

---

## Coverage Matrix

| Feature/Module | Functional Doc | Technical Doc |
|----------------|---------------|---------------|
| App overview & user journey | app-overview.md | architecture-overview.md |
| Learning session / tutor | learning-session.md | learning-session.md |
| Evaluation | evaluation.md | evaluation.md |
| Scorecard / report card | scorecard.md | scorecard.md |
| Book ingestion & guidelines | book-guidelines.md | book-guidelines.md |
| Study plans | book-guidelines.md | book-guidelines.md |
| Auth & onboarding | auth-and-onboarding.md | auth-and-onboarding.md |
| Visual explanations (PoC) | app-overview.md, learning-session.md | architecture-overview.md, learning-session.md |
| LLM providers & streaming | N/A (infra detail) | architecture-overview.md |
| Dev workflow & testing | N/A (dev-facing) | dev-workflow.md |
| Deployment & infrastructure | N/A (dev-facing) | deployment.md |
| Database schema & migrations | N/A (dev-facing) | database.md |

---

## Deferred Items

None — all discovered functionality is now documented.
