# Documentation Update Changelog

**Date:** 2026-02-26
**Trigger:** `/update-all-docs` skill execution

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added **Test Scenarios** to core features table; added test scenarios step to admin user journey |
| `docs/technical/architecture-overview.md` | Rewrote frontend route map (`/` → `/learn` redirect, `/learn/*` nested routes, `/session/:sessionId`); updated `TutorApp.tsx` as legacy redirect; added learn-flow pages (LearnLayout, SubjectSelect, TopicSelect, SubtopicSelect, ModeSelectPage, ChatSession); added test-scenarios router; fixed admin books router prefix `/admin/books` → `/admin`; added `hooks/` directory and `TestScenariosPage` to frontend structure |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Added 3 missing clarify-doubts behaviors (suggestions when unsure, natural ending, single closure question); added partial scoring and patterns to exam results; added prerequisite gap detection and unexpected-ideas-as-teaching-moments to philosophy; restructured "Ending a Session" into mode-specific subsections (Teach Me, Clarify Doubts, Exam); clarified pause summary shows concept list alongside coverage |
| `docs/technical/learning-session.md` | Added `POST /sessions/{id}/end-clarify` endpoint; removed stale `GET /sessions/scorecard` (actual: `GET /sessions/report-card`); added Completion column to Session Modes table; documented `clarify_complete` flag, partial scoring logic; added `clarify_complete: bool` to SessionState; added `rubric`, `hints`, `hints_used` to Question model; expanded WebSocket docs (SessionStateDTO, get_state, connection flow, Cognito auth); documented CAS conflict detail; split Welcome LLM call into 3 mode-specific rows; updated Key Files throughout |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | Clarified re-evaluation is API-only (no dashboard button) |
| `docs/technical/evaluation.md` | Added complete table of 7 root cause-to-suggestion mappings; expanded frontend section with all 10 legacy dimension names and retry-evaluation note; added CLI multi-persona run directory parsing note |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | **Complete rewrite** — renamed to "Report Card"; removed all AI-mastery concepts (overall score, mastery labels, trends, strengths/weaknesses, misconceptions, exam history); added deterministic coverage and latest-exam-score sections; documented empty state |
| `docs/technical/scorecard.md` | **Complete rewrite** — renamed to "Report Card -- Technical"; removed deleted methods (`_compute_scores`, `_attach_trends`, `_get_revision_nudge`); documented `_build_report`; rewrote cross-session accumulation fields; updated response schemas; updated frontend (removed `getScorecard()`, updated Practice Again flow); added navigation entry points |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Added edition year to Create Book; added OCR retry and PNG conversion; added page renumbering on deletion; rewrote sync section (per-shard upsert + full snapshot); rewrote review section (book-level vs cross-book); added "Deleting a Book" section; added fail-safe for study plan improvement |
| `docs/technical/book-guidelines.md` | Added Delete Book flow; added PIL conversion and retry to OCR; expanded page operations (approve timestamp, delete renumbering, presigned URLs); rewrote Phase 6 sync with two mechanisms; rewrote Phase 7-8 review with specific endpoints; added `PUT /books/{id}/subtopics/{key}` (501); added V1/V2 column coexistence; added `study_plans` and `llm_config` DB tables; added book fields; updated MinisummaryService calls; added orchestrator pattern and AI review loop; added V1 parked prompts and shared key files |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Added button labels to forgot password; added dynamic button text to onboarding step 5; added personalized greeting to done step; added profile details (success message, dropdowns, back button); added ToS notice and onboarding-gated routes to key details |
| `docs/technical/auth-and-onboarding.md` | Added phone/OTP placeholder email format and idempotency; added OAuth processing delay and username claim; clarified ForgotPasswordPage own CognitoUserPool; added guard-usage-per-route table; added token management details (getAccessToken, 401 intercept, transcribeAudio); added token verification details (at_hash skip, verify_aud disable); updated OAuthCallbackPage description |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/database.md` | Added `session_scope()` context manager documentation |
| `docs/technical/dev-workflow.md` | Added missing env vars (API_HOST, API_PORT); fixed frontend testing section (removed nonexistent npm scripts); added E2E Tests (Playwright) section; added coverage omissions; updated deploy triggers; updated Quick Reference and Key Files |
| `docs/technical/deployment.md` | Added `e2e/scenarios.json` to triggers and build context; fixed `index.html` cache header (added `no-store`); added manual deploy architecture warning; added Daily Coverage Details section (priority tiers, SMTP, artifacts); added 3 Terraform Makefile targets; added scripts/e2e to Key Files |

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

None — all discovered functionality has been documented.
