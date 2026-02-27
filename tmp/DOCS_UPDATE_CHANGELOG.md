# Documentation Update Changelog

**Date:** 2026-02-27
**Trigger:** `/update-all-docs` skill execution

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added Session History and Profile to Core Features table; added steps 9-10 to student journey |
| `docs/technical/architecture-overview.md` | Added `gpt-5.3-codex` to Available Models; updated Tech Stack; added `/history` route to diagram; added `shared/api/` to module list; expanded backend module structure tree (shared subdirs, middleware, evaluation flat structure); corrected router prefixes (health, LLM config); expanded frontend structure (admin components, devtools files) |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Fixed exam mid-session behavior (correctness NOT revealed mid-exam); added past discussions limit (5 most recent); added per-question review in exam results; added session replay on revisit |
| `docs/technical/learning-session.md` | Rewrote architecture diagram (branching by mode); documented TutorTurnOutput intent values per mode; **CRITICAL: marked mode-specific prompts (clarify_doubts, exam) as defined-but-not-wired** — all modes use master tutor prompts; clarified sanitization is log-only; documented exam mid-turn non-reveal; added concepts_covered_set in clarify doubts; rewrote exam completion logic (is_complete vs exam_finished); added ACCELERATE avg_mastery >= 0.65 condition; clarified SIMPLIFY real-data guard; fixed CONSOLIDATE to current-question wrong attempts; added Prompt Source column to LLM Calls table; clarified WebSocket welcome fallback; updated Key Files (ConfigurationError, extract_json_from_text, merge_misconceptions) |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | No changes needed — fully accurate |
| `docs/technical/evaluation.md` | Added Simulator Models table (gpt-4o / claude-opus-4-6 defaults); added `uses_emoji` to persona field list; expanded provider names with model labels; clarified topic context nested structure (guidelines → learning_objectives, common_misconceptions); documented frontend model badge config source |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Added end-of-session screen as third navigation entry point |
| `docs/technical/scorecard.md` | Updated exam score tracking code snippet with type guards and last_studied; added column selection detail to _load_user_sessions; expanded schema class names (all 6 Pydantic models listed) |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Added Background Jobs & Progress section; added bulk upload option (up to 200 images); added single-page upload block during bulk OCR; added Retry OCR action; updated extraction/finalization as background jobs; added heartbeat monitoring |
| `docs/technical/book-guidelines.md` | Updated architecture diagram (useJobPolling, BackgroundTaskRunner, raw/ S3); split Phase 2 into 2a/2b/2c (single, bulk, retry); marked Phases 4-5 as background; **NEW section: Background Task Infrastructure** (job state machine, heartbeat stale detection, row-level locking, resume support, error classification); added bulk upload request/background thread docs; updated Phase 4 to background job model with resume; updated Phase 5 to background job; added 4 new API endpoints (bulk upload, retry OCR, job polling); added Job Polling section with useJobPolling hook; updated book_jobs table (ocr_batch type, 7 new progress columns); added raw/ to S3 structure; expanded Key Files (background_task_runner, useJobPolling) |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Fixed "first name" → "name" in onboarding; added user menu access (profile, history, scorecard, logout) |
| `docs/technical/auth-and-onboarding.md` | Added post-login navigation flow (/ → /learn → OnboardingGuard); enhanced route guard table (/learn nested routes, /scorecard + /report-card); **NEW section: Student Profile Derivation** (useStudentProfile hook, field mapping, defaults); added ChangePasswordResponse to schemas; added useStudentProfile.ts and LearnLayout.tsx to Key Files |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/dev-workflow.md` | Rewrote frontend testing section (Vitest + React Testing Library now configured); added .coveragerc omissions (database.py, CI usage); updated sample_goal fixture (guideline_id); expanded Playwright config (retries, screenshots, trace, reports); added .coveragerc and frontend test commands to tables |
| `docs/technical/deployment.md` | Corrected Secrets Manager count (3-4, Anthropic conditional); added manual deploy workflow limitation (missing VITE_COGNITO_ vars); documented App Runner health check (/health, 10s interval, 5s timeout); noted CloudFront PriceClass_100; added Dockerfile and .coveragerc to Key Files |
| `docs/technical/database.md` | **Rewrote BookJob table** (default status pending, added ocr_batch type, new state machine pending→running→completed/failed, 7 new progress columns, updated partial index); added migration step 4 (_apply_book_job_columns) |

---

## Newly Created Docs

None — all discovered functionality was adequately covered by existing docs.

---

## Coverage Matrix

| Backend Module | Functional Doc | Technical Doc |
|---------------|---------------|---------------|
| `tutor/` | learning-session.md | learning-session.md |
| `evaluation/` | evaluation.md | evaluation.md |
| `auth/` | auth-and-onboarding.md | auth-and-onboarding.md |
| `book_ingestion/` | book-guidelines.md | book-guidelines.md |
| `study_plans/` | book-guidelines.md | book-guidelines.md |
| `shared/` | app-overview.md | architecture-overview.md |
| `api/` (docs, test_scenarios) | app-overview.md | architecture-overview.md |
| `scripts/` | N/A (dev-only) | dev-workflow.md |
| `tests/` | N/A (dev-only) | dev-workflow.md |

| Frontend Area | Functional Doc | Technical Doc |
|--------------|---------------|---------------|
| Learn flow (subject/topic/subtopic) | learning-session.md | learning-session.md, architecture-overview.md |
| Chat session | learning-session.md | learning-session.md |
| Auth pages | auth-and-onboarding.md | auth-and-onboarding.md |
| Profile/Onboarding | auth-and-onboarding.md | auth-and-onboarding.md |
| Report Card | scorecard.md | scorecard.md |
| Session History | app-overview.md | architecture-overview.md |
| Admin Books/Guidelines | book-guidelines.md | book-guidelines.md |
| Admin Evaluation | evaluation.md | evaluation.md |
| Admin LLM Config | app-overview.md | architecture-overview.md |
| Admin Test Scenarios | app-overview.md | architecture-overview.md |
| Admin Docs Viewer | app-overview.md | architecture-overview.md |

| API Group | Prefix | Technical Doc |
|-----------|--------|--------------|
| health | `/` | architecture-overview.md |
| curriculum | `/curriculum` | learning-session.md |
| sessions | `/sessions` | learning-session.md |
| transcription | `/transcribe` | learning-session.md |
| evaluation | `/api/evaluation` | evaluation.md |
| admin (books) | `/admin` | book-guidelines.md |
| admin/guidelines | `/admin/guidelines` | book-guidelines.md |
| auth | `/auth` | auth-and-onboarding.md |
| profile | `/profile` | auth-and-onboarding.md |
| docs | `/api/docs` | architecture-overview.md |
| llm-config | `/api/admin` | architecture-overview.md |
| test-scenarios | `/api/test-scenarios` | architecture-overview.md |

---

## Intentionally Deferred Items

| Item | Rationale |
|------|-----------|
| Dedicated frontend technical doc | Frontend structure is documented in `architecture-overview.md`. Individual page/component docs would be excessive for current codebase size. |
| Dedicated devtools doc | Dev-only feature, adequately covered in architecture overview's frontend structure tree. |
| Mode-specific prompt wiring | Agent 2 identified that `clarify_doubts_prompts.py` and `exam_prompts.py` define templates never imported outside their files. Documented as a finding — this is a code gap to address separately, not a doc gap. |
