# Docs Update Changelog — 2026-03-17

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added **Pre-Computed Explanations** to Core Features table |
| `docs/technical/architecture-overview.md` | Added Claude Code as 4th LLM provider (tech stack, provider table, key files, features); updated backend module structure with `pixi_code_generator`, `explanation_generator_service`, `chapter_topic_planner_service`, Claude Code adapter, explanation repository; added `ExplanationViewer.tsx` to frontend; added `topic_explanations` to DB tables |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Added "Pre-Computed Explanations (Card Phase)" subsection under Teach Me mode |
| `docs/technical/learning-session.md` | Added card phase architecture; added `prior_topics_context_section` and `precomputed_explanation_summary_section` to system prompt docs; added `POST /sessions/{id}/card-action` endpoint; restructured session creation flow for card phase branching; added `CardPhaseState` and `precomputed_explanation_summary` to SessionState; added card phase state management subsection; added `TopicGuidelines.prior_topics_context`; updated Key Files (session_state.py, messages.py, session_service.py, sessions.py, explanation_repository.py) |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | Updated Riya persona description to match revised `average_student.json`; clarified correct answer probability (45%) |
| `docs/technical/evaluation.md` | Fixed Riya persona row: probability 0.6→0.45, updated description |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Added "Progress Badges" section; added "Past Exams and Exam Review" section; added "Resuming Sessions" section; fixed empty state text (subject→topic selection); removed file path from Key Details |
| `docs/technical/scorecard.md` | Added 2 missing endpoints (`GET /sessions/guideline/{id}`, `GET /sessions/{id}/exam-review`); added "Guideline Sessions" section; added "Exam Review" section; added `GuidelineSessionsResponse` and `ExamReviewResponse` schemas; expanded Frontend section; updated Key Files (session_repository.py, ExamReviewPage.tsx, ModeSelection.tsx, ModeSelectPage.tsx) |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Rewrote Step 4 for two-phase planning approach; updated Step 5 with topic assignment and prior topics context; updated Step 6 for needs_review chapters; added new Step 7 (Generate Explanations — variants, cards, pipeline); updated Recovery section and Key Details |
| `docs/technical/book-guidelines.md` | Added Chapter Topic Planning section; added `needs_review` status; documented guided vs. unguided extraction; rewrote Extraction Orchestrator for planning flow; added deviation tracking and curriculum context generation; added Pre-Computed Explanations section; added `POST .../generate-explanations` endpoint; added `topic_explanations` table docs; added 4 new LLM prompts; updated Key Files (chapter_topic_planner_service.py, explanation_generator_service.py, explanation_repository.py) |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | No changes needed — fully accurate |
| `docs/technical/auth-and-onboarding.md` | Expanded `personality_json` to list all 10 fields (was 4); added `personality_prompts.py` to Key Files; expanded personality generation pipeline docs (LLM config, prompt building, force_regenerate) |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/dev-workflow.md` | No changes needed — fully accurate |
| `docs/technical/deployment.md` | No changes needed — fully accurate |
| `docs/technical/database.md` | Added `TopicExplanation` table docs (8 columns, FK, unique constraint); added `prior_topics_context` to TeachingGuideline; added `explanation_generator` to LLM Config seeds; added migration steps 17-18; added `pool_recycle=280s` to Connection Management; updated Relationships section |

### Master Index

| Doc | Changes |
|-----|---------|
| `docs/DOCUMENTATION_GUIDELINES.md` | Added `ai-agent-files.md` to structure tree; added `auto-research/overview.md` to tree + master index; added `principles/` and `feature-development/` to structure tree |

---

## Newly Created Docs

None — all functionality was adequately covered by existing docs.

---

## Unchanged Docs (verified current)

| Doc | Reason |
|-----|--------|
| `docs/functional/auth-and-onboarding.md` | All flows, route guards, enrichment verified correct |
| `docs/technical/dev-workflow.md` | All env vars, Makefile targets, pytest config verified correct |
| `docs/technical/deployment.md` | All CI/CD workflows, Terraform, infra details verified correct |

---

## Coverage Matrix

| Feature/Module | Functional Doc | Technical Doc |
|---|---|---|
| App overview & user journey | `app-overview.md` | `architecture-overview.md` |
| Learning sessions (tutor) | `learning-session.md` | `learning-session.md` |
| Pre-computed explanations | `learning-session.md` + `book-guidelines.md` | `learning-session.md` + `book-guidelines.md` |
| Evaluation pipeline | `evaluation.md` | `evaluation.md` |
| Scorecard / report card | `scorecard.md` | `scorecard.md` |
| Book ingestion & guidelines | `book-guidelines.md` | `book-guidelines.md` |
| Auth & onboarding | `auth-and-onboarding.md` | `auth-and-onboarding.md` |
| Feature flags | `app-overview.md` (brief) | `architecture-overview.md` (full section) |
| LLM config admin | N/A (admin tool) | `architecture-overview.md` |
| Autoresearch | N/A (internal tool) | `auto-research/overview.md` |
| Database schema | N/A (dev-facing) | `database.md` |
| Dev workflow & testing | N/A (dev-facing) | `dev-workflow.md` |
| Deployment & infra | N/A (ops-facing) | `deployment.md` |
| AI agent files | N/A (internal) | `ai-agent-files.md` |
| New machine setup | N/A (dev-facing) | `new-machine-setup.md` |

---

## Deferred Items

| Item | Rationale |
|---|---|
| Pixi.js PoC (`pixi_poc_router`, `PixiJsPocPage`) | Proof-of-concept, not a major feature |
| DevTools panel (`features/devtools/`) | Internal debugging tooling, mentioned in architecture overview |
| Docs viewer (`docs_router`, `DocsViewer`) | Admin utility, covered within book-guidelines docs |
| Test scenarios (`test_scenarios_router`, `TestScenariosPage`) | Development helper, not production feature |
