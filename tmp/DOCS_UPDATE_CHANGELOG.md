# Docs Update Changelog — 2026-04-29

Run via `/update-all-docs`. 8 parallel agents (7 assigned + 1 added for practice-mode coverage).

---

## Updated Docs

### `docs/functional/app-overview.md`
- Added Teach Me sub-mode (Baatcheet vs Explain) to Core Features and Learning Modes table
- Updated check-in formats: 6 → 11 (added spot-the-error, odd-one-out, predict-then-reveal, swipe-classify, tap-to-eliminate)
- Added admin features: Practice Bank Admin, Topic DAG Dashboard, Visual Render Preview
- Inserted "(Teach Me only) Pick sub-mode" step in user journey

### `docs/technical/architecture-overview.md`
- DB tables: added `topic_dialogues`, `student_topic_cards`
- Routes: added `/learn/.../teach`, `/admin/books-v2/:bookId/pipeline/:chapterId/:topicKey`, `/admin/visual-render-preview/:id`
- `book_ingestion_v2/`: 8 stages enumerated (incl. audio + baatcheet stages); ~10 new services; `dag/` package; `exceptions.py`
- `shared/`: added repositories (dialogue, student_topic_cards, practice_attempt, practice_question), `dialogue_hash` util
- Frontend: added TeachMeSubChooser page, ConfirmDialog, baatcheet/SpeakerAvatar, teach/BaatcheetViewer, 5 new check-in components, QualitySelector, TopicDAGView, PracticeBankAdmin, VisualRenderPreview
- LLM: added `gpt-5.4-nano`, `baatcheet_dialogue_generator` seed; corrected reasoning levels to `low/medium/high/xhigh/max`; clarified `claude_code` admin label vs CLI model

### `docs/functional/learning-session.md` — rewritten
- Documented Teach Me sub-chooser (Baatcheet vs Explain)
- Removed stale post-card flow (Check Understanding / Guided Practice — don't exist live)
- Removed "Pause Session" button claim (auto-saves only)
- "I didn't understand" simplified — removed 4-reason picker, single unified path
- Documented Baatcheet per-line MP3 + typewriter sync + embedded check-ins
- Updated completion model: cards/dialogue end → "Let's Practice" CTA, no v2 study plan

### `docs/technical/learning-session.md` — rewritten
- Three independent paths: Baatcheet (card-based, no LLM), Explain (card-based + simplify), Clarify (chat). Card-based makes ZERO LLM calls.
- Replaced stale "process_turn pipeline for teach_me" with REST endpoints (`/card-progress`, `/card-action`, `/simplify-card`); only Clarify uses `process_turn` + WebSocket
- Documented `DialoguePhaseState`, `teach_me_mode` field, `BaatcheetUnavailableError` (HTTP 409), `/teach-me-options` aggregator, `_finalize_teach_me_session` / `_finalize_baatcheet_session`
- Marked vestigial code: `_generate_v2_session_plan`, `generate_bridge_turn`, `process_turn_stream` for teach_me, `MASTER_TUTOR_BRIDGE_PROMPT`
- Added `answer_score` / `marks_rationale` (exam partial-credit fields) to schema
- Rewrote Key Files tables (incl. TeachMeSubChooser, ChatSession, BaatcheetViewer, api.ts)

### `docs/functional/evaluation.md`
- No edits — verified accurate (8 personas, 5 core + 2 card-phase dimensions, two modes, dashboard behaviors, status banner)

### `docs/technical/evaluation.md`
- New **Autoresearch Integration** section (`run_experiment.py`, `--quick`/`--runs`/`--restart-server`, `results.tsv`, `email_report.py`)
- Noted `simulator_temperature` / `simulator_max_tokens` are dead config (defined on `EvalConfig` but unused)
- Server management: tightened (`uvicorn main:app` from PROJECT_ROOT, `lsof -ti :PORT`, `restart_server=True` users)
- Clarified `anthropic-haiku` failure path
- Key Files: added `run_experiment.py`, `results.tsv`; expanded persona list (all 8 ids); expanded TS types entry

### `docs/functional/scorecard.md`
- No edits — verified accurate (coverage, practice score, badges, Get Ready, Practice Again, empty state)

### `docs/technical/scorecard.md`
- Removed nonexistent `PracticeAttemptRepository.list_graded_for_user()`; service queries `PracticeAttempt` directly
- Added `mode` + `teach_me_mode` to `ResumableSessionResponse`
- Added `teach_me_mode` to `GuidelineSessionsResponse.sessions[]`
- Corrected `is_complete` to delegate to `SessionState.is_complete`
- Added `_get_canonical_concepts()` reference for coverage denominator
- Clarified `_load_user_practice_attempts` filters (`graded_at IS NOT NULL`, `total_score IS NOT NULL`)
- Noted `_group_sessions` accumulates coverage from teach_me only (not Clarify)
- ChapterSelect excludes `refresher_guideline_id` from chapter-status averaging
- TopicSelect renders `get-ready` refresher separately (chapter-landing CTA)
- Practice Again starts a fresh Teach Me session, not a practice attempt

### `docs/functional/book-guidelines.md`
- Restructured Step 7 into 8-stage post-sync pipeline (7.1–7.8): Explanations, Visuals, Check-ins, Practice Bank, Baatcheet Dialogue, Baatcheet Visuals, Audio Review, Audio Synthesis
- New Step 9: Topic Pipeline Dashboard (React Flow DAG)
- New Step 10: Cross-DAG warnings ("chapter content changed" banner)
- Updated guideline-deletion cascade copy (mentions dialogues + practice questions)
- Removed defunct claim that explanations generate three variants by default
- Updated Key Details (topic-vs-chapter job locking, audio guardrails, halt-on-failure, auto-clearing banner)

### `docs/technical/book-guidelines.md` — extensive rewrite
- Pipeline architecture diagram now two-phase with explicit DAG arrows
- New **Topic Pipeline DAG** section: 8 stages with deps, soft-join `audio_synthesis ↔ baatcheet_dialogue`, per-topic serialization, staleness anchoring, `Stage` dataclass + `StatusContext`, two orchestrators (`TopicPipelineOrchestrator` synchronous + `CascadeOrchestrator` event-driven), `QUALITY_ROUNDS` (now incl. `baatcheet_dialogue`), `/admin/v2/dag/...` endpoints, cross-DAG warnings, fan-out, stage launchers, `topic_stage_runs`, lazy backfill
- New sections: Practice Bank Generation, Baatcheet Dialogue (Stage 5b), Baatcheet Visuals (Stage 5c), Baatcheet Audio Review (opt-in)
- Audio Synthesis updated for variant A + dialogue + check-in fields, per-speaker voice routing (Mr. Verma / Meera), counting helpers, dialogue S3 namespace
- Visual Rendering Review updated to current vision-LLM gate (replaces removed Python overlap detector)
- Job-type list refreshed: 13 V2 job types
- Sync API table expanded (practice bank, audio review, audio synthesis, baatcheet dialogue/visuals/audio review endpoints)
- DB Tables added: `topic_stage_runs`, `topic_content_hashes`, `topic_dialogues`, `practice_questions`, `practice_attempts`
- LLM Prompts rewritten (audio_text_review, baatcheet plan/dialogue/refine/visual intent/visual pass, check-in review-refine, practice bank, `_system.txt` split convention)
- Configuration reorganized into per-key LLM config + constants table (Baatcheet card-count bounds, practice bank target/max, parallelism, poll bounds)
- Frontend updated: PracticeBankAdmin, TopicDAGView, QualitySelector, VisualRenderPreview, practice-banks + pipeline DAG routes
- Key Files reorganized into 6 sections (Constants & models, DAG package, Stages, Services, Repositories, API routes, Other)

### `docs/functional/auth-and-onboarding.md`
- No edits — verified accurate

### `docs/technical/auth-and-onboarding.md`
- Added `TeachMeSubChooser` route (`/learn/:subject/:chapter/:topic/teach`) to per-route guard table

### `docs/functional/practice-mode.md`
- Clarified history list interactivity (graded/grading-failed rows tappable, in-progress/grading read-only)
- Fixed grading state UI string ("Grading your answers...")
- Added 5-min stuck-grading state on results page

### `docs/technical/practice-mode.md`
- Schema: removed phantom `idx_practice_questions_guideline_difficulty`; added `generator_model` column
- `PracticeAttempt`: renamed `viewed_at` → `results_viewed_at`; added `question_ids`, `grading_attempts` columns
- Partial unique index name → `uq_practice_attempts_one_inprogress_per_topic`
- LLM config: `claude-opus-4-6` → `claude-opus-4-7` (3 places)
- Redaction list corrected (removed phantom `correct_answer`, added `error_index`/`odd_index`, `sequence`/`match_pairs`/`bucket_items` shape transforms)
- Variety < 4 case is logger warning, not enforced rule
- Service public methods: `list_for_topic` → `list_attempts`; `mark_viewed`/`list_recent_unread` reference `results_viewed_at`
- Atomic submit snippet aligned with real `PracticeService.submit()` flow
- Added `FF_CORRECT_THRESHOLD = 0.75` rule for free-form correct flag
- Rationale prompts produce 2-3 sentences (not 1)
- Results page: 150-poll/~5-min stuck-grading guard; Practice-again behavior
- DTOs corrected (`PracticeAvailability` lives in api file)
- Key Files refreshed (added `stage_launchers.py`, DAG `practice_bank.py`, unit-test files, `capture/types.ts`, primitives, `AppShell.tsx`, `ModeSelection.tsx`, App.tsx routes)

### `docs/technical/database.md`
- Sessions: added `teach_me_mode` column; 4-col paused-session unique index; added `idx_sessions_user_guideline_teach_mode`; noted exam/practice cleanup
- LLM Config: added `reasoning_effort` column; refreshed seed defaults (claude-opus-4-7; removed `pixi_code_generator`; added `baatcheet_dialogue_generator`); noted `claude_code` provider; documented `_ensure_llm_config` injection
- Practice Questions: removed phantom index; added `generator_model`; reordered to schema
- Practice Attempts: added `question_ids`, `grading_attempts`; renamed `viewed_at` → `results_viewed_at`; corrected partial-unique index name
- New sections: `topic_dialogues`, `student_topic_cards`
- V2 Pipeline Tables expanded: `chapter_processing_jobs` partial unique indexes, `topic_stage_runs.content_anchor` + partial index, `topic_content_hashes` columns
- Migration Approach: rewrote 29-step ordered list to match `migrate()` call order in `db.py` (incl. all new helpers)
- Relationships diagram + bullets: added topic_dialogues, student_topic_cards, topic_stage_runs, topic_content_hashes
- Key Files: added new ORM tables, V2 tables, `_LLM_CONFIG_SEEDS`, `cleanup_v1_data.py`

### `docs/technical/deployment.md`
- Clarified `GOOGLE_CLOUD_TTS_API_KEY` reuses Gemini secret ARN at App Runner runtime
- Key Files: added 6 Terraform sub-modules, `terraform.tfvars.example`, repo-root `docker-compose.yml`

### `docs/technical/dev-workflow.md`
- Required env vars: corrected to `DATABASE_URL` + `OPENAI_API_KEY` only (matches `entrypoint.sh` + `validate_required_settings`)
- Local DB: pointer to repo-root `docker-compose.yml`
- E2E: action timeout, expect timeout, viewport, JSON+list reporters, test-output dir, `.env` dotenv, all 5 test files (auth.setup, scenarios, check-in-cards, practice-v2, cross-dag-warning)
- Adding DB Models: V2 models go in `book_ingestion_v2/models/database.py`; `_ensure_llm_config()` helper
- Key Files: added repo-root `docker-compose.yml`

### `docs/DOCUMENTATION_GUIDELINES.md`
- Master index updated to include `llm-prompts.md`, `audio-typewriter-bug-analysis.md`, `aws-cost-optimization.md` (previously unindexed)

---

## Newly Created Docs
None. All updates fit existing structure. No coverage gaps required new files.

---

## Coverage Matrix

| Module / Feature | Functional | Technical |
|---|---|---|
| App shell, routes, tech stack | `functional/app-overview.md` | `technical/architecture-overview.md` |
| Tutor (Teach Me / Baatcheet / Clarify) | `functional/learning-session.md` | `technical/learning-session.md` |
| Practice mode | `functional/practice-mode.md` | `technical/practice-mode.md` |
| Scorecard | `functional/scorecard.md` | `technical/scorecard.md` |
| Evaluation (admin) | `functional/evaluation.md` | `technical/evaluation.md` |
| Book ingestion + Topic Pipeline DAG | `functional/book-guidelines.md` | `technical/book-guidelines.md` |
| Auth + Onboarding | `functional/auth-and-onboarding.md` | `technical/auth-and-onboarding.md` |
| Autoresearch (dev tool) | N/A (no end-user UI) | `technical/auto-research/overview.md` |
| LLM prompt catalog | N/A | `technical/llm-prompts.md` |
| Database schema | N/A | `technical/database.md` |
| Deployment / infra | N/A | `technical/deployment.md` |
| Dev workflow | N/A | `technical/dev-workflow.md` |
| New machine setup | N/A | `technical/new-machine-setup.md` |
| AI agent context files | N/A | `technical/ai-agent-files.md` |
| AWS cost log (historical) | N/A | `technical/aws-cost-optimization.md` |
| Audio bug analysis (historical) | N/A | `technical/audio-typewriter-bug-analysis.md` |

All major backend modules (`tutor/`, `book_ingestion_v2/`, `auth/`, `autoresearch/`, `study_plans/`, `shared/`) and frontend areas (pages, features/admin, features/devtools) are mapped to at least one technical doc. Student-facing features have functional docs; admin/dev tools that have no end-user UI (autoresearch, infra, prompts catalog) intentionally lack functional docs.

---

## Deferred / Notes

- **`docs/principles/practice-mode.md`** — left untouched. Two minor tensions with code (no-consecutive-format strictness, variety<4 enforcement) but principles describe policy intent, not runtime behavior. No actual disagreement.
- **`docs/principles/*` (13 other principle docs)** — not in scope; principles are stable design intent, not code-tracking docs.
- **`docs/feature-development/*`** — active PRDs/trackers, not master-index docs.
- **`docs/archive/*`** — preserved historical docs, not master-index docs.
- **`tmp/GUIDELINES_WORKFLOW_DOC_CHANGES_JUSTIFICATION.md`** and **`tmp/TUTOR_WORKFLOW_DOC_CHANGES_JUSTIFICATION.md`** — prior-run artifacts; not touched.
- **`docs/technical/audio-typewriter-bug-analysis.md`** and **`docs/technical/aws-cost-optimization.md`** — historical one-offs, now indexed but content not edited (point-in-time records).
