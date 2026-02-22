# Documentation Update Changelog

**Date:** 2026-02-22
**Trigger:** `/update-all-docs`

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added learning modes (Teach Me, Clarify Doubts, Exam) section; updated student journey from 5→7 steps with mode selection + resume; added voice input, LLM config page, docs viewer to features; updated admin journey with "Configure AI models" and "Browse documentation" steps |
| `docs/technical/architecture-overview.md` | Updated system diagram with llm_config table and services; added Google/Gemini as 3rd LLM provider; added auth module to backend structure; corrected router prefixes and added 3 missing routers (transcription, docs, llm config); expanded frontend structure with admin pages, ModeSelection, OAuthCallbackPage; expanded route map with 8 admin routes; rewrote LLM Provider System for DB-backed config; updated configuration section with new env vars |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Full rewrite: added 3 learning modes section; added mode selection, pause/resume, voice input, coverage tracking, student personalization sections; updated teaching philosophy with escalation strategies, answer change/novel strategy handling |
| `docs/technical/learning-session.md` | Full rewrite: added session modes with routing; updated LLM provider to DB-backed config; added answer_change/novel_strategy intents; expanded orchestration flow with mode routing; added mode-specific prompts section; added 6 REST endpoints (pause, resume, end-exam, resumable, report-card, transcribe); updated WebSocket with error type and mode-specific fields; added CAS concurrency section; added exam state and transcription sections; expanded Key Files with 8 new entries |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | Added two evaluation modes section (existing session vs new simulation); expanded persona response style detail; updated results view with status badges, model badges, expandable analysis, color coding; added re-evaluation feature; added LLM config page reference |
| `docs/technical/evaluation.md` | Expanded simulator (turn directives, retry logic, provider-specific injection); expanded session runner (eval-student user, timeout, WebSocket types, end conditions); expanded judge (input construction, evaluator models, DB config); added model configuration section; updated report generator (directory naming, error artifact, config.json); updated personas table with grade column; expanded API endpoints with concurrency, request bodies, error fields; added frontend section; expanded Key Files |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Added subject-level misconceptions summary; added year-aware date formatting; new sections: coverage & revision nudges (7/14/30-day thresholds), session type tracking (per-mode counts), exam history with AI feedback; added report card alias note |
| `docs/technical/scorecard.md` | Added report-card endpoint; documented all 8 private ScorecardService methods; expanded data flow with mode extraction, concepts accumulation, exam extraction; added cross-session accumulation table; added coverage computation and revision nudge logic sections; added ReportCardResponse schema with all new subtopic fields; added frontend routing and API tables; expanded Key Files from 3→6 |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Added finalization step to overview; expanded page OCR with PageViewPanel; updated guidelines generation with V2 details (summaries, context, boundary detection, AI merge); new sections: finalization process, DB sync; expanded study plan generation with todo format, reviewer loop, step fields, metadata |
| `docs/technical/book-guidelines.md` | Updated pipeline phases with Phase 6 (DB sync); updated S3 paths; rewrote Phase 4 for V2 pipeline (minisummary V2, context packs, boundary detection, guideline merging); added finalize and sync detail; expanded study plan with AI review loop and Pydantic schema; added PageIndex, ContextPack data models; added database tables section; added V1 parked services section; updated LLM calls with config keys; expanded API with job locking; expanded Key Files with repositories, models, prompts |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Added login button labels; expanded email signup (password confirmation, requirements, 6-digit UX, auto-login); expanded phone signup (country code selector, auto-submit OTP); clarified Google redirect flow; added email verification detail; expanded forgot password; updated onboarding wizard (grid, auto-completion); rewrote profile management (view/edit toggle, account info, logout) |
| `docs/technical/auth-and-onboarding.md` | Extended auth diagram with two-phase tokens and JWKS; added JWKS caching detail; expanded email/phone/Google flows; new sections: forgot password, change password, auth provider detection, auth middleware; corrected syncUser signature; added DELETE user endpoint and PUT password endpoint; rewrote onboarding API (auto-completion); added AuthContext syncUser; updated route guards; corrected token function names; expanded Key Files with 8 new entries; added configuration section |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/database.md` | New table: LLMConfig with 6 seeded defaults; added 6 Sessions columns (mode, is_paused, exam_score, exam_total, guideline_id, state_version); added columns to TeachingGuideline, StudyPlan, Books, BookGuideline; documented all indexes including partial indexes; added learning_modes and seed_llm_config migration steps; added CASCADE annotations; added connection management details; added Key Files table |
| `docs/technical/deployment.md` | Updated architecture diagram (PostgreSQL version, all secrets, S3 bucket); documented Dockerfile/entrypoint; expanded Terraform setup with new tfvars; added Cognito and SMTP GitHub secrets; rewrote CI/CD with 4 workflows table; added Terraform modules section; expanded quick commands; expanded troubleshooting; updated infrastructure details; added Key Files table |
| `docs/technical/dev-workflow.md` | Expanded setup with all .env variables; added 9 test markers table; converted fixtures to table; added book_ingestion models location; added db-migrate and ALTER TABLE migration guidance; updated deploy triggers; expanded quick reference; added Key Files table |

---

## Newly Created Docs

None — all coverage gaps were addressed by expanding existing doc sections.

---

## Coverage Matrix

| Feature / Module | Functional Doc | Technical Doc |
|-----------------|---------------|---------------|
| App overview & user journey | `functional/app-overview.md` | `technical/architecture-overview.md` |
| Learning modes (Teach/Clarify/Exam) | `functional/learning-session.md` | `technical/learning-session.md` |
| Session pause/resume | `functional/learning-session.md` | `technical/learning-session.md` |
| Voice input / transcription | `functional/app-overview.md`, `functional/learning-session.md` | `technical/learning-session.md` |
| Master tutor agent | `functional/learning-session.md` | `technical/learning-session.md` |
| Safety agent | `functional/learning-session.md` | `technical/learning-session.md` |
| CAS concurrency | N/A (internal) | `technical/learning-session.md` |
| Evaluation pipeline | `functional/evaluation.md` | `technical/evaluation.md` |
| Personas | `functional/evaluation.md` | `technical/evaluation.md` |
| LLM judge | `functional/evaluation.md` | `technical/evaluation.md` |
| Scorecard | `functional/scorecard.md` | `technical/scorecard.md` |
| Report card | `functional/scorecard.md` | `technical/scorecard.md` |
| Coverage & revision nudges | `functional/scorecard.md` | `technical/scorecard.md` |
| Exam history | `functional/scorecard.md` | `technical/scorecard.md` |
| Book ingestion (V2) | `functional/book-guidelines.md` | `technical/book-guidelines.md` |
| Guideline finalization & sync | `functional/book-guidelines.md` | `technical/book-guidelines.md` |
| Study plan generation | `functional/book-guidelines.md` | `technical/book-guidelines.md` |
| Auth (email/phone/Google) | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| Onboarding wizard | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| Profile management | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| Forgot/change password | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| LLM config (DB-backed) | `functional/app-overview.md` | `technical/architecture-overview.md` |
| Database schema & migrations | N/A (internal) | `technical/database.md` |
| Deployment & Terraform | N/A (ops) | `technical/deployment.md` |
| Dev workflow & testing | N/A (ops) | `technical/dev-workflow.md` |
| Docs viewer (admin) | `functional/app-overview.md` | `technical/architecture-overview.md` |

---

## Intentionally Deferred Items

| Item | Rationale |
|------|-----------|
| V1 book ingestion services | Documented as "parked" in technical/book-guidelines.md — code exists but is not used by the active V2 pipeline |
| Frontend DIMENSIONS constant mismatch | Noted in technical/evaluation.md — frontend lists 10 legacy dimension names while backend returns 5. Not a doc issue, flagged for code cleanup |
| Change password frontend UI | Backend endpoint exists (`PUT /profile/password`) but no frontend UI — documented in technical/auth-and-onboarding.md |
| PageService OCR bug | `get_ocr_service()` singleton factory may not pass model correctly — noted during Agent 5 discovery, not a doc issue |
