# Documentation Update Changelog

**Date:** 2026-03-04
**Trigger:** `/update-all-docs` skill execution

---

## Newly Created Docs

| Doc | Reason |
|-----|--------|
| `docs/functional/book-guidelines.md` | Entire book ingestion V2 module (31 Python files), study plans module, and admin frontend had zero documentation. No existing doc was a fit. Created 119-line functional doc. |
| `docs/technical/book-guidelines.md` | Same module — created 441-line technical doc covering V2 pipeline architecture, 24 API endpoints, 19 services, S3 structure, state machines. |

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added "Parents" as target user (enrichment system); added Voice Output (TTS) feature; added Exam Review feature; renamed "Scorecard" → "Report Card"; added Enrichment Profile feature; added Parents section to user journey; updated student journey (topic → chapter hierarchy, exam review step) |
| `docs/technical/architecture-overview.md` | Updated system architecture diagram (new shared services, DB tables, routes); added Google Cloud TTS to tech stack; updated auth module description (enrichment/personality); added OCR service and S3 client; updated routers table (TTS, enrichment, V2 book sub-routers, removed stale entries); removed stale TutorApp.tsx/LearnLayout.tsx, added AppShell.tsx; added ExamReviewPage, EnrichmentPage, ReportCardPage; updated all routes; added google_cloud_tts_api_key to config; added ocr_service.py to key files |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Expanded exam question types to 6; updated to fractional scoring (0-1 scale); added duplicate exam guard; added exam review feature; added personality profile personalization; added structured explanation lifecycle; added personalized study plans; renamed "Voice Input" → "Voice Input and Output" (TTS); new Language Support section; new Attention Span Awareness section |
| `docs/technical/learning-session.md` | Updated architecture diagram (TRANSLATE step, audio_text); expanded TutorTurnOutput schema (audio_text, answer_score, explanation phases); updated orchestration flow (translation, clarify prompts, fractional scoring); updated system prompt (12 rules, language instructions); clarify prompts now "actively wired"; added EXPLAIN pacing directives and attention span; updated REST endpoints (topic-progress, exam-review, TTS); updated WebSocket (audio_text); updated session creation (personalized plans, explanation init, duplicate guard); added ExplanationPhase model; updated ExamQuestion (fractional scoring); added study plan personalization; split audio into Transcription/TTS; updated key files (report_card, language_utils, tts) |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | No changes needed — already accurate |
| `docs/technical/evaluation.md` | Added missing `GET /api/evaluation/guidelines` endpoint; corrected model badge mapping (tutor vs evaluator badges have different provider sets) |

### Agent 4 — Scorecard → Report Card

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Renamed "topic/subtopic" → "chapter/topic" throughout; updated "My Scorecard" → "My Report Card"; removed `/scorecard` URL alias; updated Practice Again to reference topics |
| `docs/technical/scorecard.md` | Renamed ScorecardService → ReportCardService, file scorecard_service.py → report_card_service.py; renamed methods get_scorecard → get_report_card, get_subtopic_progress → get_topic_progress; corrected API /sessions/subtopic-progress → /sessions/topic-progress; updated hierarchy terminology throughout; updated response schema classes; updated frontend references (ScorecardPage → ReportCardPage); removed /scorecard alias |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | **NEWLY CREATED** — Admin workflow: create book, define TOC, upload pages with OCR, process chapters, review topics, sync to teaching database; chapter status state machine; study plan generation |
| `docs/technical/book-guidelines.md` | **NEWLY CREATED** — Full V2 pipeline architecture; 19 backend services; 24 API endpoints across 5 route groups; 7 data flow diagrams; database tables; state machines; S3 directory structure; processing constants |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Marked phone login as "coming soon" (disabled); added preferred name step (6 steps total); updated progress dots to 6; profile page renamed "Profile & Settings" with focus mode, language prefs; added enrichment CTA on profile; new Enrichment Profile section; new Navigation & User Menu section (AppShell) |
| `docs/technical/auth-and-onboarding.md` | Updated auth diagram (phone disabled); added 4 User model columns (preferred_name, text/audio language, focus_mode); new KidEnrichmentProfile model; new KidPersonality model; added 4 enrichment API endpoints; new Enrichment & Personality data flow; updated onboarding API (preferred_name); documented UserProfile interface; rewrote route guard table (AppShell, new session URLs); added 11 new key files; removed stale LearnLayout |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/database.md` | Added 4 missing User columns; corrected Sessions index to composite; added user_id to Study Plans; added 2 new tables (kid_enrichment_profiles, kid_personalities); added personality_derivation LLM config seed; expanded relationships; added 8 new migration steps |
| `docs/technical/deployment.md` | Updated Secrets Manager label (Gemini/TTS); added App Runner runtime env vars and secrets documentation; updated infrastructure details |
| `docs/technical/dev-workflow.md` | Added GOOGLE_CLOUD_TTS_API_KEY to optional env vars; fixed fixtures table (topic → chapter) |

### Master Index & CLAUDE.md

| Doc | Changes |
|-----|---------|
| `docs/DOCUMENTATION_GUIDELINES.md` | Updated scorecard index entries to "Report card" |
| `CLAUDE.md` | Updated scorecard index entries to "Report card"; book-guidelines entries added by Agent 5 |

---

## Coverage Matrix

| Feature / Module | Functional Doc | Technical Doc |
|---|---|---|
| App overview & user journey | `functional/app-overview.md` | `technical/architecture-overview.md` |
| Learning session (tutor) | `functional/learning-session.md` | `technical/learning-session.md` |
| Evaluation | `functional/evaluation.md` | `technical/evaluation.md` |
| Report card | `functional/scorecard.md` | `technical/scorecard.md` |
| Book ingestion & guidelines | `functional/book-guidelines.md` | `technical/book-guidelines.md` |
| Study plans | `functional/book-guidelines.md` | `technical/book-guidelines.md` |
| Auth & onboarding | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| Enrichment & personality | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| Voice (STT + TTS) | `functional/learning-session.md` | `technical/learning-session.md` |
| Language support | `functional/learning-session.md` | `technical/learning-session.md` |
| Database schema | N/A (infrastructure) | `technical/database.md` |
| Dev workflow & testing | N/A (infrastructure) | `technical/dev-workflow.md` |
| Deployment & CI/CD | N/A (infrastructure) | `technical/deployment.md` |
| Shared services & architecture | N/A (cross-cutting) | `technical/architecture-overview.md` |

---

## Intentionally Deferred Items

| Item | Rationale |
|------|-----------|
| `docs/technical/ai-agent-files.md` | Managed by separate `/update-agent-files` skill |
| `docs/archive/*` | Historical records; not updated by this skill |
| Admin devtools frontend | Internal debugging tool, not user-facing |
