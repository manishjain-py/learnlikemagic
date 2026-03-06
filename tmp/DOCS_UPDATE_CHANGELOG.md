# Documentation Update Changelog

**Date:** 2026-03-06
**Trigger:** `/update-all-docs` skill execution

---

## Newly Created Docs

| Doc | Reason |
|-----|--------|
| `docs/functional/book-guidelines.md` | Previously missing; V2 book ingestion pipeline needed user-facing documentation |
| `docs/technical/book-guidelines.md` | Previously missing; V2 book ingestion pipeline needed comprehensive technical documentation |

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added Parents as user role; added Voice Output (TTS), Exam Review, Enrichment Profile features; renamed Scorecard to Report Card; fixed hierarchy to subject > chapter > topic; updated admin journey for V2 book pipeline |
| `docs/technical/architecture-overview.md` | Updated route map with mode-specific session URLs; added TTS router, enrichment router, V2 book routes (5 separate entries); updated module structure for tutor/, book_ingestion_v2/, auth/; added Google Cloud TTS to tech stack; added 5 new DB tables; replaced LearnLayout with AppShell; added ExamReviewPage, EnrichmentPage; added google_cloud_tts_api_key config |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Added Mid-Session Feedback section (continue/restart, 3-per-session limit); added Language Support section (English, Hindi, Hinglish); expanded Voice Input to include TTS and translation; updated Exam with duplicate guard, new question types (real_world, error_spotting, reasoning), fractional scoring, exam review; updated Teaching Philosophy with enrichment personality and attention-span awareness; documented structured explanation lifecycle |
| `docs/technical/learning-session.md` | Added explanation phases model and lifecycle; added mid-session feedback; added fractional exam scoring (0.8/0.2 thresholds); added input translation step; added TTS endpoint; updated orchestration flow with 12 teaching rules; added ExamQuestion score/rationale fields; updated key files (report_card_service, tts, language_utils); corrected clarify doubts prompts to actively wired; added pacing directive EXPLAIN states |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | No changes needed — fully accurate |
| `docs/technical/evaluation.md` | Fixed provider routing documentation (anthropic-haiku only in PROVIDER_LABELS); added missing GET /api/evaluation/guidelines endpoint; improved model badge documentation accuracy |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Fixed hierarchy terminology throughout: Subject > Chapter > Topic (was Topic > Subtopic); changed "My Scorecard" to "My Report Card"; fixed routing to /report-card only |
| `docs/technical/scorecard.md` | Renamed ScorecardService to ReportCardService; fixed all method names (get_report_card, get_topic_progress, _empty_report_card); fixed endpoint /sessions/topic-progress; fixed response models (TopicProgressResponse, ReportCardChapter, ReportCardTopic); updated frontend references (ReportCardPage, AppShell); fixed test file name |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | **Created from scratch.** 6-step workflow: create book, define TOC, upload pages, process chapters, review topics, sync to DB. Recovery/reprocessing options. Study plan generation. |
| `docs/technical/book-guidelines.md` | **Created from scratch.** Chapter status state machine (7 states); 8 services documented; 25+ API endpoints; database tables and S3 layout; LLM prompts inventory; configuration constants; frontend components and polling behavior; 20+ key files |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Marked phone login as disabled ("coming soon"); added preferred name onboarding step; added Enrichment Profile section (parent-facing); added Navigation & User Menu section; updated Profile Management with language preferences, focus mode |
| `docs/technical/auth-and-onboarding.md` | Marked phone auth as disabled on frontend; added enrichment & personality pipeline section; added 4 enrichment API endpoints; updated User model (preferred_name, language prefs, focus_mode); added kid_enrichment_profiles and kid_personalities tables; updated route table with AppShell; added profile update personality trigger; added enrichment key files |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/dev-workflow.md` | Added GOOGLE_CLOUD_TTS_API_KEY to optional env vars; updated sample_goal fixture for chapter field naming |
| `docs/technical/deployment.md` | Added GOOGLE_CLOUD_TTS_API_KEY reusing Gemini secret ARN |
| `docs/technical/database.md` | Added session_feedback, kid_enrichment_profiles, kid_personalities tables; added preferred_name, language preferences, focus_mode to users; added user_id to study_plans with composite index; documented all 17 migration steps |

### Master Index

| Doc | Changes |
|-----|---------|
| `docs/DOCUMENTATION_GUIDELINES.md` | Added `docs/technical/new-machine-setup.md` to master index and structure tree |

---

## Coverage Matrix

| Backend Module | Functional Doc | Technical Doc |
|---------------|---------------|---------------|
| `tutor/` | learning-session.md | learning-session.md |
| `evaluation/` | evaluation.md | evaluation.md |
| `auth/` | auth-and-onboarding.md | auth-and-onboarding.md |
| `book_ingestion_v2/` | book-guidelines.md | book-guidelines.md |
| `study_plans/` | book-guidelines.md | book-guidelines.md |
| `shared/` | app-overview.md | architecture-overview.md |
| `api/` (sessions, curriculum, transcription, tts) | learning-session.md | learning-session.md |
| `api/` (docs, test_scenarios, llm_config) | app-overview.md | architecture-overview.md |
| `scripts/` | N/A (dev-only) | dev-workflow.md |
| `tests/` | N/A (dev-only) | dev-workflow.md |

| Frontend Area | Functional Doc | Technical Doc |
|--------------|---------------|---------------|
| Learn flow (subject/chapter/topic) | learning-session.md | learning-session.md, architecture-overview.md |
| Chat session | learning-session.md | learning-session.md |
| Auth pages | auth-and-onboarding.md | auth-and-onboarding.md |
| Profile/Onboarding/Enrichment | auth-and-onboarding.md | auth-and-onboarding.md |
| Report Card | scorecard.md | scorecard.md |
| Session History | app-overview.md | architecture-overview.md |
| Admin Books V2 | book-guidelines.md | book-guidelines.md |
| Admin Evaluation | evaluation.md | evaluation.md |
| Admin LLM Config | app-overview.md | architecture-overview.md |

| API Group | Prefix | Technical Doc |
|-----------|--------|--------------|
| health | `/` | architecture-overview.md |
| curriculum | `/curriculum` | learning-session.md |
| sessions | `/sessions` | learning-session.md |
| transcription | `/transcribe` | learning-session.md |
| tts | `/text-to-speech` | learning-session.md |
| evaluation | `/api/evaluation` | evaluation.md |
| admin v2 books | `/admin/v2/books` | book-guidelines.md |
| auth | `/auth` | auth-and-onboarding.md |
| profile | `/profile` | auth-and-onboarding.md |
| enrichment | `/profile/enrichment`, `/profile/personality` | auth-and-onboarding.md |
| docs | `/api/docs` | architecture-overview.md |
| llm-config | `/api/admin/llm-config` | architecture-overview.md |
| test-scenarios | `/api/test-scenarios` | architecture-overview.md |

---

## Intentionally Deferred Items

| Item | Rationale |
|------|-----------|
| `docs/technical/learning-modes-implementation-plan.md` | Historical implementation plan, not active documentation. Could be moved to `docs/archive/` in a future cleanup. |
| Dedicated frontend technical doc | Frontend structure is documented in `architecture-overview.md`. Individual page/component docs would be excessive for current codebase size. |
