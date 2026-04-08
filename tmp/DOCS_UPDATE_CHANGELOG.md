# Docs Update Changelog

Run date: 2026-04-08
Branch: `claude/update-all-docs-B6qTb`

## Summary

All 7 doc-update agents ran in parallel. 13 docs updated, 0 new docs created.
All coverage gaps closed inside existing docs.

## Updated Docs

### Agent 1 — App Overview & Architecture

**`docs/functional/app-overview.md`**
- Added "Get Ready Refresher" feature row (new prerequisite refresher topic surfaced in TopicSelect/ModeSelection).

**`docs/technical/architecture-overview.md`**
- Added 3 missing book-ingestion services to module tree: `animation_enrichment_service`, `check_in_enrichment_service`, `refresher_topic_generator_service`.
- Corrected `study_plans/` structure (services-only, no `api/`, `models/`, or `orchestrator.py`).
- Noted `study_plans` has no router — called directly by `tutor/services/session_service.py`.
- Documented `animation_enrichment` as runtime-only LLM config key (not in `_LLM_CONFIG_SEEDS`).

### Agent 2 — Learning Session

**`docs/technical/learning-session.md`**
- Added `is_refresher` flag on SessionState + `is_complete` logic (refresher → `card_phase.completed`).
- Added refresher topic detection + mode restriction (HTTP 400 for non-teach_me) in session creation.
- Documented refresher card-phase `clear` short-circuit (returns `session_complete`, blocks simplification).
- Added `CheckInStruggleEvent` pydantic model with `confused_pairs` + `auto_revealed`.
- Documented `check_in_events` on `CardActionRequest`, ingestion order, summary augmentation.
- Added `/card-action` remedial-card reset on variant switch.
- Added safety agent allow-list pre-filter + fail-safe behavior (`is_safe=False` on LLM exception).
- Refreshed Key Files rows: `session_state.py`, `messages.py` (CheckInEventDTO, `card_navigate`), `session_service.py`.

**`docs/functional/learning-session.md`**
- Added refresher completion experience: session ends after refresher cards, no follow-up interactive lesson.

### Agent 3 — Evaluation

**`docs/technical/evaluation.md`**
- Documented evaluator prompt loading: `prompts/evaluator.txt`, `prompts/card_phase_dimensions.txt`, splicing + dynamic schema.
- Corrected `anthropic-haiku` routing: `LLMService` routes correctly, but `EvalConfig.create_llm_service()` falls through to default model, causing Anthropic client + OpenAI model_id mismatch.
- Added Key Files entries for `prompts/evaluator.txt` and `prompts/card_phase_dimensions.txt`.

**`docs/functional/evaluation.md`** — No changes. Fully current.

### Agent 4 — Scorecard

**`docs/technical/scorecard.md`**
- Clarified Topic Progress (Lightweight): backend response keyed by `topic_id` (guideline id), uses `mastery_estimates` as plan denominator, `status="not_started"` is dead code (frontend infers from missing keys).
- Clarified `/resumable` validates via `SessionState.model_validate_json`; `/exam-review` validates `mode == "exam"` + `exam_finished`.
- Added past-exams green/orange/red color coding (>=70/>=40/<40).

**`docs/functional/scorecard.md`**
- Past Exams section: added percentage display + color coding.

### Agent 5 — Book & Guidelines

**`docs/functional/book-guidelines.md`**
- Added Step 6.5: Review and Edit Guidelines (per-chapter CRUD/approval/deletion).
- Rewrote Step 7 explanations: generate → review-and-refine N rounds (was generate → critique → discard); added refine-only mode + stage snapshots.
- Added Step 9: interactive check-ins (6 activity types, placement rules, conflict avoidance).
- Added Step 10: "Get Ready" prerequisite refresher topic generation.
- Updated Study Plans section: on-demand tutor generation, no reviewer loop.
- Added Key Details bullets for check-ins, refresher, per-chapter admin pages.

**`docs/technical/book-guidelines.md`**
- Updated pipeline diagram: check-in enrichment, refresher, review-and-refine.
- Fixed `HEARTBEAT_STALE_THRESHOLD`: 600s → 1800s.
- Replaced `StudyPlanOrchestrator` section (file doesn't exist) with `tutor/services/session_service.py` invocation note. Marked `StudyPlanReviewerService` legacy/unused.
- Rewrote Pre-Computed Explanations: review-and-refine flow, `mode=refine_only`, `review_rounds`, `stage_collector`, claude_code system file split, default variant 1.
- New Check-In Enrichment section: 6 activity types, validation, placement, pre-flight conflict, LLM config fallback.
- New Refresher Topic Generation section: idempotent, `topic_key="get-ready"`, `metadata_json.is_refresher=true`.
- Replaced single endpoint table with grouped tables covering guidelines CRUD, explanation stages, visual status/jobs/strip, check-in generate/status/jobs, refresher generate/jobs, landing.
- Clarified bulk OCR routes live in `processing_routes.py`.
- Updated LLM Prompts table: added new prompt files, flagged legacy ones, removed nonexistent `study_plan_improve.txt`.
- Added `check_in_enrichment`, `study_plan_generator` config keys, `DEFAULT_VARIANT_COUNT`, `DEFAULT_REVIEW_ROUNDS`, check-in placement constants.
- Expanded Frontend section: 5 per-chapter admin pages (OCRAdmin, TopicsAdmin, GuidelinesAdmin, ExplanationAdmin, VisualsAdmin).
- Rewrote Key Files table: new services, 5 API route files, removed nonexistent `study_plans/services/orchestrator.py`.
- Added DB table note for refresher rows in `teaching_guidelines`.
- Added job type enum entries: `v2_check_in_enrichment`, `v2_refresher_generation`, `v2_refinalization`.

### Agent 6 — Auth & Onboarding

**`docs/technical/auth-and-onboarding.md`**
- Corrected ProfilePage.tsx description: no frontend focus_mode toggle (backend supports it).
- Clarified Cognito signup `name` attribute uses `email.split('@')[0]` placeholder (real name collected in onboarding).

**`docs/functional/auth-and-onboarding.md`** — No substantive changes. Fully current.

### Agent 7 — Infrastructure

**`docs/technical/database.md`**
- Added `check_in_enrichment` to seeded LLM config table (provider `claude_code`, model `claude-opus-4-6`).
- Updated migration step 18 to note it seeds both `explanation_generator` and `check_in_enrichment`.

**`docs/technical/deployment.md`**
- Fixed Terraform `database/` module description: RDS PostgreSQL 15 instance (`db.t4g.micro`), not Aurora Serverless v2.
- Fixed manual backup command: `aws rds create-db-snapshot --db-instance-identifier` (instance API, not cluster).
- Corrected Terraform variable required/optional lists: `gemini_api_key` required (no default), `llm_model` optional (defaults to `gpt-4o-mini`).

**`docs/technical/dev-workflow.md`** — No changes. Fully current.

## New Docs Created

None. All coverage gaps fit cleanly into existing docs.

## Coverage Matrix

| Feature/Module | Functional Doc | Technical Doc |
|---|---|---|
| App overview, routes, tech stack | `functional/app-overview.md` | `technical/architecture-overview.md` |
| Tutor pipeline (`tutor/`, TutorApp) | `functional/learning-session.md` | `technical/learning-session.md` |
| Evaluation (`autoresearch/tutor_teaching_quality`) | `functional/evaluation.md` | `technical/evaluation.md` |
| Report Card / Scorecard | `functional/scorecard.md` | `technical/scorecard.md` |
| Book ingestion v2, study plans | `functional/book-guidelines.md` | `technical/book-guidelines.md` |
| Auth, Cognito, onboarding, profile, enrichment | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| Dev setup, testing, git | N/A (dev-only) | `technical/dev-workflow.md` |
| AWS infra, Terraform, CI/CD | N/A (dev-only) | `technical/deployment.md` |
| DB schema, migrations, ORM models | N/A (dev-only) | `technical/database.md` |
| Autoresearch (autonomous prompt opt) | N/A | `technical/auto-research/overview.md` (unchanged this run) |
| DevTools drawer (frontend) | N/A | Covered in `technical/architecture-overview.md` + `technical/dev-workflow.md` |
| Admin dashboard pages | Split across book/eval/app-overview | Split across book/eval/architecture |

## Deferred Items

- `docs/technical/auto-research/overview.md` — not in scope for this run (not assigned to any agent). Re-run with a dedicated autoresearch agent if code drift suspected.
- `docs/principles/*` — principles docs describe design intent, not code. Not touched this run.
- `docs/technical/ai-agent-files.md` — agent context file inventory. Run `/update-agent-files` separately.

## Master Index

No changes required. All updated docs already present in `docs/DOCUMENTATION_GUIDELINES.md` master index.
