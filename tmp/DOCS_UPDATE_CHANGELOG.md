# Documentation Update Changelog

**Date:** 2026-03-15
**Trigger:** `/update-all-docs` skill execution

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added "Feature Flags" to Core Features; added feature flag step to admin journey |
| `docs/technical/architecture-overview.md` | Updated OpenAI models (added gpt-5.4, gpt-5.3-codex); added feature_flags to DB diagram, shared module, routers table; expanded frontend admin structure; fixed admin route map (AdminLayout wrapper); added full "Feature Flag System" section |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Added Rule 5: "Checks for real understanding" (detect false OKs) |
| `docs/technical/learning-session.md` | Updated teaching rule count 13→14 (4 locations); updated model list (added gpt-5.4, gpt-5.3-codex); added `show_visuals_in_tutor_flow` feature flag docs (3 locations); added `feature_flag_service.py` to Key Files |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | No changes needed — fully accurate |
| `docs/technical/evaluation.md` | Fixed `max_tokens` → `max_completion_tokens`; changed "silently skipped" to "logged as warnings"; added note about frontend model badge reading legacy field |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Fixed empty state nav target: "topic selection" → "subject selection" |
| `docs/technical/scorecard.md` | Added `ChapterSelect.tsx` and `TopicSelect.tsx` as topic-progress consumers |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Added version field to topic listing |
| `docs/technical/book-guidelines.md` | Added new "Ingestion Quality Evaluation" section (was missing); added 7 evaluation pipeline files + judge prompt to Key Files |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | No changes needed — fully accurate |
| `docs/technical/auth-and-onboarding.md` | No changes needed — fully accurate |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/dev-workflow.md` | No changes needed — paths already updated |
| `docs/technical/deployment.md` | No changes needed — fully accurate |
| `docs/technical/database.md` | Added "Feature Flags" table section; added to relationships diagram; added migration step 18 |

---

## Newly Created Docs

None — all changes fit into existing documentation files.

---

## Unchanged Docs (verified current)

| Doc | Reason |
|-----|--------|
| `docs/functional/evaluation.md` | All 8 personas, 5 dimensions, dashboard features verified correct |
| `docs/functional/auth-and-onboarding.md` | All flows, route guards, enrichment verified correct |
| `docs/technical/auth-and-onboarding.md` | All 34 key files, endpoints, Cognito verified correct |
| `docs/technical/dev-workflow.md` | All paths and configs verified correct |
| `docs/technical/deployment.md` | All infra details verified correct |
| `docs/technical/auto-research/overview.md` | Already updated with centralized structure |
| `docs/DOCUMENTATION_GUIDELINES.md` | Master index unchanged (no new docs added) |

---

## Coverage Matrix

| Feature/Module | Functional Doc | Technical Doc |
|---|---|---|
| App overview & user journey | `app-overview.md` | `architecture-overview.md` |
| Learning sessions (tutor) | `learning-session.md` | `learning-session.md` |
| Evaluation pipeline | `evaluation.md` | `evaluation.md` |
| Scorecard / report card | `scorecard.md` | `scorecard.md` |
| Book ingestion & guidelines | `book-guidelines.md` | `book-guidelines.md` |
| Auth & onboarding | `auth-and-onboarding.md` | `auth-and-onboarding.md` |
| Feature flags | `app-overview.md` (brief) | `architecture-overview.md` (full section) |
| LLM config admin | N/A (admin tool) | `architecture-overview.md` |
| Autoresearch (tutor) | N/A | `auto-research/overview.md` |
| Autoresearch (book ingestion) | N/A | `book-guidelines.md` (new section) |
| Database schema | N/A | `database.md` |
| Dev workflow & testing | N/A | `dev-workflow.md` |
| Deployment & infra | N/A | `deployment.md` |

---

## Deferred Items

| Item | Rationale |
|---|---|
| `docs_router` (API docs endpoint) | Internal tooling, not a user/developer feature |
| `test_scenarios_router` / `TestScenariosPage` | Development helper, not production |
| `ExamReviewPage.tsx` | Early-stage page; will document when stabilized |
| `PixiJsPocPage.tsx` | Proof-of-concept, minimal mention in learning-session tech doc is sufficient |
| `DocsViewer.tsx` admin page | Internal admin tool for browsing docs |
