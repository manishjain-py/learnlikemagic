# Database

Schema, tables, migrations, and connection management.

---

## Database Overview

- **Engine:** RDS PostgreSQL 15 (db.t4g.micro, free tier)
- **ORM:** SQLAlchemy (declarative base)
- **Connection:** `DatabaseManager` with `QueuePool` (pool_size=5, max_overflow=10, pre_ping=true)
- **Migrations:** Custom imperative approach (not Alembic)

---

## Tables

### Users

**Table:** `users` | **Model:** `User` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `cognito_sub` | VARCHAR | Cognito user ID (unique) |
| `email` | VARCHAR | Email address (unique, nullable) |
| `phone` | VARCHAR | Phone number (unique, nullable) |
| `auth_provider` | VARCHAR | `email`, `phone`, or `google` |
| `name` | VARCHAR | Display name |
| `age` | INT | Student age |
| `grade` | INT | School grade |
| `board` | VARCHAR | Education board |
| `school_name` | VARCHAR | School name |
| `about_me` | TEXT | Self-description |
| `text_language_preference` | VARCHAR | Preferred language for text content |
| `audio_language_preference` | VARCHAR | Preferred language for audio content |
| `preferred_name` | VARCHAR | Preferred display name (nickname) |
| `focus_mode` | BOOL | Focus mode enabled (default true) |
| `is_active` | BOOL | Account active flag (default true) |
| `onboarding_complete` | BOOL | Onboarding wizard completed (default false) |
| `last_login_at` | DATETIME | Last login timestamp |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_cognito_sub` (cognito_sub), `idx_user_email` (email)

### Sessions

**Table:** `sessions` | **Model:** `Session` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `student_json` | TEXT | Student context (serialized JSON) |
| `goal_json` | TEXT | Session goal (serialized JSON) |
| `state_json` | TEXT | Full TutorState (serialized SessionState) |
| `mastery` | FLOAT | Current mastery score (default 0.0) |
| `step_idx` | INT | Current step index (default 0) |
| `user_id` | VARCHAR | FK --> users (nullable, supports anonymous) |
| `subject` | VARCHAR | Denormalized subject name |
| `mode` | VARCHAR | Learning mode: `teach_me` or `clarify_doubts` (default `teach_me`); legacy `exam`/`practice` rows are deleted by `_cleanup_exam_and_old_practice_data` |
| `teach_me_mode` | VARCHAR | Submode within `teach_me`: `explain` or `baatcheet` (default `explain`) |
| `is_paused` | BOOL | Whether session is paused (default false) |
| `guideline_id` | VARCHAR | Associated teaching guideline ID |
| `state_version` | INT | Optimistic concurrency version (default 1) |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_session_user_guideline` (user_id, guideline_id, mode)

**Partial unique index (migration-created):** `idx_sessions_one_paused_per_user_guideline` on (user_id, guideline_id, mode, teach_me_mode) WHERE is_paused = TRUE -- enforces at most one paused session per (user, guideline, mode, teach_me_mode) so paused Explain + paused Baatcheet + paused Practice can coexist for the same topic. Additional migration-created indexes: `idx_sessions_user_id`, `idx_sessions_subject`, `idx_sessions_mode`, `idx_sessions_guideline_id`, `idx_sessions_user_guideline_teach_mode` (lookup index for resume CTA on (user_id, guideline_id, mode, teach_me_mode, updated_at DESC)).

### Events

**Table:** `events` | **Model:** `Event` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `session_id` | VARCHAR | FK --> sessions |
| `node` | VARCHAR | Event type (Present/Check/Diagnose/Remediate/Advance) |
| `step_idx` | INT | Step index at time of event |
| `payload_json` | TEXT | Event data (serialized JSON) |
| `created_at` | DATETIME | Timestamp |

**Indexes:** `idx_session_step` (session_id, step_idx)

### Contents

**Table:** `contents` | **Model:** `Content` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `topic` | VARCHAR | Topic name |
| `grade` | INT | Grade level |
| `skill` | VARCHAR | Skill identifier |
| `text` | TEXT | Content text |
| `tags` | VARCHAR | Comma-separated tags |

**Indexes:** `idx_topic_grade` (topic, grade)

### Teaching Guidelines

**Table:** `teaching_guidelines` | **Model:** `TeachingGuideline` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `book_id` | VARCHAR | Source book reference |
| `country` | VARCHAR | Country |
| `board` | VARCHAR | Education board |
| `grade` | INT | Grade level |
| `subject` | VARCHAR | Subject name |
| `chapter` | VARCHAR | Chapter name (e.g., "Fractions") |
| `topic` | VARCHAR | Topic / learning unit name (e.g., "Comparing Like Denominators") |
| `chapter_key` | VARCHAR | Slugified chapter identifier |
| `topic_key` | VARCHAR | Slugified topic identifier |
| `chapter_title` | VARCHAR | Human-readable chapter name |
| `topic_title` | VARCHAR | Human-readable topic name |
| `chapter_summary` | TEXT | Chapter summary (20-40 words) |
| `topic_summary` | TEXT | Topic summary (15-30 words) |
| `guideline` | TEXT | Complete teaching guidelines |
| `chapter_sequence` | INT | Teaching order of chapter within book (1-based) |
| `topic_sequence` | INT | Teaching order of topic within chapter (1-based) |
| `chapter_storyline` | TEXT | Narrative of chapter's teaching progression |
| `teaching_description` | TEXT | Teaching description (used by V2 sync) |
| `description` | TEXT | Fallback for guideline text (used by study plan generation) |
| `source_page_start` | INT | First source page |
| `source_page_end` | INT | Last source page |
| `source_pages` | VARCHAR | Page range string (e.g., "5-8") |
| `metadata_json` | TEXT | JSON: objectives, depth, misconceptions, etc. |
| `status` | VARCHAR | `draft`, `pending_review`, `approved`, `rejected` (default `draft`) |
| `review_status` | VARCHAR | `TO_BE_REVIEWED` or `APPROVED` (default `TO_BE_REVIEWED`) |
| `generated_at` | DATETIME | When guideline was generated |
| `reviewed_at` | DATETIME | When guideline was reviewed |
| `reviewed_by` | VARCHAR | Who reviewed the guideline |
| `prior_topics_context` | TEXT | Context from prior topics in the same chapter (for topic-quality planning) |
| `version` | INT | Version counter (default 1) |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_curriculum` (country, board, grade, subject, chapter)

### Study Plans

**Table:** `study_plans` | **Model:** `StudyPlan` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (CASCADE delete) |
| `user_id` | VARCHAR | FK --> users (CASCADE delete, nullable -- null for generic plans) |
| `plan_json` | TEXT | Study plan steps (serialized JSON) |
| `generator_model` | VARCHAR | Model used to generate |
| `reviewer_model` | VARCHAR | Model used to review |
| `generation_reasoning` | TEXT | Generator's reasoning for the plan |
| `reviewer_feedback` | TEXT | Reviewer's feedback on the plan |
| `was_revised` | INT | Whether plan was revised after review (0=no, 1=yes) |
| `status` | VARCHAR | `generated` or `approved` (default `generated`) |
| `version` | INT | Version counter (default 1) |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_study_plans_guideline` (guideline_id), `idx_study_plans_user_guideline` (user_id, guideline_id) UNIQUE

### LLM Config

**Table:** `llm_config` | **Model:** `LLMConfig` (`shared/models/entities.py`)

Centralized model configuration per component. Single source of truth for which LLM provider and model each component uses. Managed via the `/admin/llm-config` UI. No fallback logic -- missing config raises an error.

| Column | Type | Description |
|--------|------|-------------|
| `component_key` | VARCHAR | Primary key (e.g. `tutor`, `book_ingestion_v2`) |
| `provider` | VARCHAR | LLM provider: `openai`, `anthropic`, `google`, `claude_code` |
| `model_id` | VARCHAR | Model identifier (e.g. `gpt-5.2`, `claude-opus-4-7`) |
| `description` | VARCHAR | Human-readable description |
| `reasoning_effort` | VARCHAR | Reasoning effort: `low`/`medium`/`high`/`xhigh`/`max` (default `max`) |
| `updated_at` | DATETIME | Last update timestamp |
| `updated_by` | VARCHAR | Who last updated the config |

**Seeded defaults** (`_LLM_CONFIG_SEEDS` in `db.py`; inserted only if table is empty):

| Component Key | Provider | Model | Purpose |
|---------------|----------|-------|---------|
| `tutor` | openai | gpt-5.2 | Main tutoring pipeline (safety + master tutor + welcome) |
| `study_plan_generator` | openai | gpt-5.2 | Study plan creation from teaching guidelines |
| `study_plan_reviewer` | openai | gpt-5.2 | Study plan review and improvement |
| `eval_evaluator` | openai | gpt-5.2 | Evaluation judge (scores tutor quality) |
| `eval_simulator` | openai | gpt-5.2 | Student simulator for evaluations |
| `book_ingestion_v2` | openai | gpt-5.2 | Book ingestion V2 pipeline (chunk extraction, consolidation, merge) |
| `personality_derivation` | openai | gpt-5.2 | Kid personality derivation from enrichment profile |
| `explanation_generator` | openai | gpt-5.2 | Pre-computed explanation generation for topics |
| `fast_model` | openai | gpt-4o-mini | Lightweight model for safety checks, translation, fast tasks |
| `check_in_enrichment` | claude_code | claude-opus-4-7 | Check-in card generation (match-the-pairs activities) |
| `practice_bank_generator` | claude_code | claude-opus-4-7 | Practice question bank generation + correctness review |
| `practice_grader` | openai | gpt-4o-mini | Practice free-form grading + per-pick wrong-answer rationales |
| `baatcheet_dialogue_generator` | claude_code | claude-opus-4-7 | Stage 5b — conversational Baatcheet dialogue generation (Mr. Verma + Meera) |

Existing deployments (table non-empty) get individual seeds injected via `_ensure_llm_config()` from per-feature migration steps (e.g. `_apply_topic_explanations_table`, `_apply_topic_dialogues_table`, `_apply_practice_tables`).

### Session Feedback

**Table:** `session_feedback` | **Model:** `SessionFeedback` (`shared/models/entities.py`)

Mid-session feedback from parents/students that can trigger study plan regeneration.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `user_id` | VARCHAR | FK --> users (CASCADE delete) |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (CASCADE delete) |
| `session_id` | VARCHAR | FK --> sessions (SET NULL on delete, nullable) |
| `feedback_text` | TEXT | Feedback content |
| `step_at_feedback` | INT | Step index when feedback was given |
| `total_steps_at_feedback` | INT | Total steps in plan when feedback was given |
| `plan_regenerated` | BOOL | Whether the plan was regenerated (default false) |
| `created_at` | DATETIME | Timestamp |

**Indexes:** `idx_session_feedback_user_guideline` (user_id, guideline_id), `idx_session_feedback_session` (session_id)

### Kid Enrichment Profiles

**Table:** `kid_enrichment_profiles` | **Model:** `KidEnrichmentProfile` (`shared/models/entities.py`)

Raw enrichment data collected from parents (one per kid). Uses JSONB columns for flexible list data.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `user_id` | VARCHAR | FK --> users (unique, 1:1) |
| `interests` | JSONB | String array of interests |
| `learning_styles` | JSONB | String array of learning styles |
| `motivations` | JSONB | String array of motivations |
| `growth_areas` | JSONB | String array of growth areas |
| `parent_notes` | TEXT | Free-text parent notes |
| `attention_span` | VARCHAR | `short`, `medium`, or `long` |
| `pace_preference` | VARCHAR | `slow`, `balanced`, or `fast` |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

### Kid Personalities

**Table:** `kid_personalities` | **Model:** `KidPersonality` (`shared/models/entities.py`)

LLM-derived personality versions (multiple per kid, latest version = active).

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `user_id` | VARCHAR | FK --> users |
| `personality_json` | JSONB | Structured personality data |
| `tutor_brief` | TEXT | Compact tutor-facing personality summary |
| `status` | VARCHAR | `generating`, `ready`, or `failed` |
| `inputs_hash` | VARCHAR | Hash of enrichment inputs (for change detection) |
| `generator_model` | VARCHAR | LLM model used for derivation |
| `version` | INT | Version counter (default 1) |
| `created_at` | DATETIME | Timestamp |

**Indexes:** `idx_kid_personalities_user_version` (user_id, version)

### Books

**Table:** `books` | **Model:** `Book` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (slug: author_subject_grade_year) |
| `title` | VARCHAR | Book title |
| `author` | VARCHAR | Author name |
| `edition` | VARCHAR | Edition |
| `edition_year` | INT | Edition year |
| `country` | VARCHAR | Country |
| `board` | VARCHAR | Education board |
| `grade` | INT | Grade level |
| `subject` | VARCHAR | Subject |
| `pipeline_version` | INT | Pipeline version (default 1) |
| `s3_prefix` | VARCHAR | `books/{book_id}/` |
| `metadata_s3_key` | VARCHAR | `books/{book_id}/metadata.json` |
| `cover_image_s3_key` | VARCHAR | Optional cover image |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |
| `created_by` | VARCHAR | Creator username (default `admin`) |

**Indexes:** `idx_books_curriculum` (country, board, grade, subject)

### Feature Flags

**Table:** `feature_flags` | **Model:** `FeatureFlag` (`shared/models/entities.py`)

Runtime feature flags toggled via the `/admin/feature-flags` UI. Each row is a named boolean switch. New flags are seeded in `db.py` via `_seed_feature_flags()`.

| Column | Type | Description |
|--------|------|-------------|
| `flag_name` | VARCHAR | Primary key (e.g. `show_visuals_in_tutor_flow`) |
| `enabled` | BOOL | Whether the flag is on (default false) |
| `description` | VARCHAR | Human-readable description |
| `updated_at` | DATETIME | Last update timestamp |
| `updated_by` | VARCHAR | Who last toggled the flag |

**Seeded defaults** (inserted if the flag does not yet exist):

| Flag Name | Default | Description |
|-----------|---------|-------------|
| `show_visuals_in_tutor_flow` | true | Show Pixi.js visual explanations during tutoring sessions |

### Practice Questions

**Table:** `practice_questions` | **Model:** `PracticeQuestion` (`shared/models/entities.py`)

Offline-generated question bank for Let's Practice. One row per question. Populated by `PracticeBankGeneratorService` during ingestion; read-only at runtime (practice attempts snapshot questions into their own row at creation time).

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (UUID) |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (CASCADE delete) |
| `format` | VARCHAR | One of: `pick_one`, `true_false`, `fill_blank`, `match_pairs`, `sort_buckets`, `sequence`, `spot_the_error`, `odd_one_out`, `predict_then_reveal`, `swipe_classify`, `tap_to_eliminate`, `free_form` |
| `difficulty` | VARCHAR | `easy`, `medium`, or `hard` |
| `concept_tag` | VARCHAR | Concept label from the topic's guideline |
| `question_json` | JSONB | Full question payload (text, options, correct answer, rubric, `explanation_why`) |
| `generator_model` | VARCHAR | LLM model used to generate |
| `created_at` | DATETIME | Timestamp |

**Indexes:** `idx_practice_questions_guideline` (guideline_id).

### Practice Attempts

**Table:** `practice_attempts` | **Model:** `PracticeAttempt` (`shared/models/entities.py`)

One row per practice attempt. Self-contained — snapshots the 10 selected questions at creation so bank regeneration never orphans history.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (UUID) |
| `user_id` | VARCHAR | FK --> users (CASCADE delete) |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (CASCADE delete) |
| `status` | VARCHAR | `in_progress`, `grading`, `graded`, or `grading_failed` (default `in_progress`) |
| `question_ids` | JSONB | Ordered list of selected `practice_questions.id` values |
| `questions_snapshot_json` | JSONB | 10 question payloads + per-q `_id`, `_format`, `_difficulty`, `_concept_tag`, `_presentation_seed` |
| `answers_json` | JSONB | `{q_idx (string): answer}` map written by PATCH /answer and final submit |
| `grading_json` | JSONB | Per-question grading rows. Null until graded. |
| `total_score` | FLOAT | Aggregate score, half-point-rounded at write-time. Null until graded. |
| `total_possible` | INT | Always 10 in v1 (default 10) |
| `grading_error` | TEXT | Exception text if grading failed |
| `grading_attempts` | INT | Retry counter for grading (default 0) |
| `results_viewed_at` | DATETIME | Set by POST /mark-viewed to clear the banner |
| `created_at`, `submitted_at`, `graded_at` | DATETIME | Timestamps |

**Indexes:**
- `idx_practice_attempts_user_guideline` (user_id, guideline_id)
- `idx_practice_attempts_user_status` (user_id, status) — drives `/attempts/recent`

**Partial unique index (migration-created):** `uq_practice_attempts_one_inprogress_per_topic` on `(user_id, guideline_id) WHERE status='in_progress'` — enforces "at most one resumable attempt per topic."

### Topic Explanations

**Table:** `topic_explanations` | **Model:** `TopicExplanation` (`shared/models/entities.py`)

Pre-computed explanation variants for teaching guidelines. Each guideline can have multiple variants (A, B, C), each representing a different pedagogical approach. Cards are stored as JSONB for queryability. Cascade-deleted when the parent guideline is deleted (e.g., during re-sync).

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (auto-generated UUID) |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (CASCADE delete) |
| `variant_key` | VARCHAR | Variant identifier: `A`, `B`, `C` |
| `variant_label` | VARCHAR | Human-readable label (e.g., "Everyday Analogies") |
| `cards_json` | JSONB | Ordered list of ExplanationCard objects |
| `summary_json` | JSONB | Pre-computed summary for tutor context (nullable) |
| `generator_model` | VARCHAR | LLM model used to generate the explanation |
| `created_at` | DATETIME | Timestamp |

**Unique constraint:** `uq_explanation_guideline_variant` (guideline_id, variant_key) -- at most one variant per key per guideline.

### Topic Dialogues

**Table:** `topic_dialogues` | **Model:** `TopicDialogue` (`shared/models/entities.py`)

Pre-computed Baatcheet dialogue per teaching guideline. One row per guideline (V1: single dialogue per topic). Cascade-deleted with the parent guideline. `source_content_hash` snapshots variant A's semantic identity so staleness can be detected without timestamps.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (auto UUID) |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (CASCADE delete, unique 1:1) |
| `cards_json` | JSONB | Ordered Baatcheet card list |
| `plan_json` | JSONB | V2 designed-lesson plan (misconceptions, spine, macro_structure, card_plan); nullable for V1 rows |
| `generator_model` | VARCHAR | LLM model used to generate |
| `source_variant_key` | VARCHAR | Variant key the dialogue was derived from (default `A`) |
| `source_explanation_id` | VARCHAR | Source `topic_explanations.id` reference (nullable) |
| `source_content_hash` | VARCHAR | Semantic-identity hash of the source variant at generation |
| `created_at`, `updated_at` | DATETIME | Timestamps |

**Indexes (migration-created):** `idx_topic_dialogues_guideline` (UNIQUE on guideline_id).

### Student Topic Cards

**Table:** `student_topic_cards` | **Model:** `StudentTopicCards` (`shared/models/entities.py`)

Per-student, per-variant simplification overlays for explanation cards. One row per (user, guideline, variant); `simplifications` is a JSONB map keyed by card id.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (auto UUID) |
| `user_id` | VARCHAR | FK --> users (CASCADE delete) |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (CASCADE delete) |
| `variant_key` | VARCHAR | Variant key (`A`, `B`, `C`) |
| `explanation_id` | VARCHAR | Source `topic_explanations.id` reference |
| `simplifications` | JSONB | Per-card simplification overlay (default `{}`) |
| `updated_at` | DATETIME | Timestamp |

**Unique constraint:** `uq_student_topic_cards_user_guideline_variant` (user_id, guideline_id, variant_key).

### Issues

**Table:** `issues` | **Model:** `Issue` (`shared/models/entities.py`)

User-reported issues tracked by status. Supports screenshot attachments stored in S3.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (auto-generated UUID) |
| `user_id` | VARCHAR | FK --> users (SET NULL on delete, nullable) |
| `reporter_name` | VARCHAR | Reporter's display name (nullable) |
| `title` | VARCHAR | Issue title |
| `description` | TEXT | LLM-interpreted issue text |
| `original_input` | TEXT | Raw user input (text/transcription, nullable) |
| `screenshot_s3_keys` | JSONB | Array of S3 keys for screenshots (nullable) |
| `status` | VARCHAR | `open`, `in_progress`, or `closed` (default `open`) |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_issues_status` (status), `idx_issues_user` (user_id)

### V2 Pipeline Tables

See `book_ingestion_v2/models/database.py` for the full V2 pipeline tables:
- `book_chapters` — chapter definitions from TOC (UC `(book_id, chapter_number)`)
- `chapter_pages` — uploaded page images with OCR text (UC `(chapter_id, page_number)`)
- `chapter_chunks` — per-chunk LLM processing audit trail with input/output, tokens, latency
- `chapter_topics` — extracted topics with guidelines (UC `(chapter_id, topic_key)`; includes `prior_topics_context` and `topic_assignment` for topic-quality planning)
- `chapter_processing_jobs` — background job tracking (chapter-level OR topic-level via `guideline_id`; includes `planned_topics_json` for planning, `stage_snapshots_json` for intermediate card sets, `heartbeat_at` for stale-job detection). Two partial unique indexes enforce one active job per scope:
  - `idx_chapter_active_chapter_job` on `(chapter_id) WHERE status IN ('pending','running') AND guideline_id IS NULL` (chapter-level: OCR, extraction, finalization, refresher)
  - `idx_chapter_active_topic_job` on `(chapter_id, guideline_id) WHERE status IN ('pending','running') AND guideline_id IS NOT NULL` (topic-level: explanations, visuals, check-ins, practice, audio, baatcheet)
- `topic_stage_runs` — latest-only per-stage state for the topic-pipeline DAG. PK `(guideline_id, stage_id)`; FK guideline_id (CASCADE), FK last_job_id. Columns: `state`, `is_stale`, `started_at`, `completed_at`, `duration_ms`, `last_job_id`, `content_anchor` (snapshots staleness signal at `done`), `summary_json`. Indexes: `idx_topic_stage_runs_state`, partial `idx_topic_stage_runs_is_stale WHERE is_stale=TRUE`.
- `topic_content_hashes` — durable hash store for the cross-DAG warning. PK `(book_id, chapter_key, topic_key)` — the stable curriculum tuple (NOT `guideline_id`, which dies on `topic_sync` resync). Stores `explanations_input_hash` + `last_explanations_at`.

---

## Relationships

```
users ──1:N──> sessions ──1:N──> events
users ──1:N──> study_plans
users ──1:1──> kid_enrichment_profiles
users ──1:N──> kid_personalities
users ──1:N──> session_feedback
users ──1:N──> issues
users ──1:N──> practice_attempts
users ──1:N──> student_topic_cards
teaching_guidelines ──1:N──> study_plans (per-user plans)
teaching_guidelines ──1:N──> topic_explanations (pre-computed explanation variants)
teaching_guidelines ──1:1──> topic_dialogues (Baatcheet dialogue per topic)
teaching_guidelines ──1:N──> student_topic_cards (per-student simplification overlays)
teaching_guidelines ──1:N──> practice_questions (offline question bank)
teaching_guidelines ──1:N──> practice_attempts (student attempts)
teaching_guidelines ──1:N──> topic_stage_runs (per-stage DAG state)
books ──1:N──> book_chapters ──1:N──> chapter_pages
books ──1:N──> book_chapters ──1:N──> chapter_topics
chapter_processing_jobs ──1:N──> topic_stage_runs.last_job_id (latest job per stage)
llm_config (standalone, no FKs)
feature_flags (standalone, no FKs)
topic_content_hashes (standalone — keyed on stable curriculum tuple, no FKs)
```

- `Session.user_id` --> `User.id` (nullable -- anonymous sessions supported)
- `Event.session_id` --> `Session.id`
- `StudyPlan.guideline_id` --> `TeachingGuideline.id` (CASCADE delete)
- `StudyPlan.user_id` --> `User.id` (CASCADE delete, nullable -- null for generic plans; unique on user_id + guideline_id)
- `SessionFeedback.user_id` --> `User.id` (CASCADE delete)
- `SessionFeedback.guideline_id` --> `TeachingGuideline.id` (CASCADE delete)
- `SessionFeedback.session_id` --> `Session.id` (SET NULL on delete, nullable)
- `KidEnrichmentProfile.user_id` --> `User.id` (unique, 1:1)
- `KidPersonality.user_id` --> `User.id`
- `TopicExplanation.guideline_id` --> `TeachingGuideline.id` (CASCADE delete; unique on guideline_id + variant_key)
- `TopicDialogue.guideline_id` --> `TeachingGuideline.id` (CASCADE delete, unique 1:1)
- `StudentTopicCards.user_id` --> `User.id` (CASCADE delete); `StudentTopicCards.guideline_id` --> `TeachingGuideline.id` (CASCADE delete); unique on (user_id, guideline_id, variant_key)
- `Issue.user_id` --> `User.id` (SET NULL on delete, nullable)
- `PracticeQuestion.guideline_id` --> `TeachingGuideline.id` (CASCADE delete)
- `PracticeAttempt.user_id` --> `User.id` (CASCADE delete)
- `PracticeAttempt.guideline_id` --> `TeachingGuideline.id` (CASCADE delete); partial unique on (user_id, guideline_id) WHERE status='in_progress'
- `TopicStageRun.guideline_id` --> `TeachingGuideline.id` (CASCADE delete; PK with stage_id); `TopicStageRun.last_job_id` --> `ChapterProcessingJob.id` (nullable)

---

## Migration Approach

**File:** `db.py`

Custom imperative migration (not Alembic). `migrate()` runs `Base.metadata.create_all()` first (idempotent — creates new tables) then applies these helpers in order:

1. `_apply_session_columns()` — adds `user_id` + `subject` to sessions
2. `_apply_learning_modes_columns()` — adds `mode`, `is_paused`, `guideline_id`, `state_version` to sessions; creates legacy `(user_id, guideline_id) WHERE is_paused` partial unique index (rebuilt later); backfills `mode='teach_me'`
3. `_apply_user_language_columns()` — adds `text_language_preference`, `audio_language_preference` to users
4. `_apply_user_preferred_name_column()` — adds `preferred_name` to users
5. `_apply_sequencing_columns()` — adds `chapter_sequence`, `topic_sequence`, `chapter_storyline` to teaching_guidelines
6. `_apply_v2_tables()` — adds `pipeline_version` to books, creates V2 tables (book_chapters, chapter_pages, chapter_chunks, chapter_topics, chapter_processing_jobs, topic_stage_runs, topic_content_hashes), dedups + adds V2 unique constraints, seeds `book_ingestion_v2` LLM config
7. `_rename_topic_subtopic_columns()` — renames teaching_guidelines columns from `topic_*` → `chapter_*` and `subtopic_*` → `topic_*` (idempotent)
8. `_drop_v1_tables()` — drops legacy `book_guidelines`, `book_jobs`
9. `_drop_v1_guideline_columns()` — drops V1 `objectives_json`, `examples_json`, `misconceptions_json`, `assessments_json`, `evidence_summary`, `confidence`
10. `_remove_v1_llm_config()` — removes legacy `book_ingestion` llm_config entry
11. `_apply_kid_enrichment_tables()` — seeds `personality_derivation` config (copies provider/model from `tutor`)
12. `_drop_unused_enrichment_columns()` — drops `my_world`, `strengths`, `personality_traits`, `favorite_media`, `favorite_characters`, `memorable_experience`, `aspiration` from kid_enrichment_profiles
13. `_apply_study_plan_user_column()` — adds `user_id` to study_plans (CASCADE), drops legacy single-column unique on guideline_id, creates composite unique on (user_id, guideline_id)
14. `_apply_focus_mode_column()` — adds `focus_mode` (default TRUE); resets pre-existing FALSE values to TRUE
15. `_apply_session_feedback_table()` — verification only (table created by create_all)
16. `_apply_topic_planning_columns()` — adds `planned_topics_json` to chapter_processing_jobs, `prior_topics_context` + `topic_assignment` to chapter_topics, `prior_topics_context` to teaching_guidelines
17. `_apply_topic_explanations_table()` — verifies + seeds `explanation_generator` and `check_in_enrichment` configs via `_ensure_llm_config`
18. `_apply_topic_dialogues_table()` — verifies topic_dialogues; adds `idx_topic_dialogues_guideline` unique index + `plan_json` column (V2 designed lesson); seeds `baatcheet_dialogue_generator` config
19. `_apply_sessions_teach_me_mode_column()` — adds `teach_me_mode` to sessions (default `explain`), backfills from `state_json::jsonb`, rebuilds `idx_sessions_one_paused_per_user_guideline` to 4-col `(user_id, guideline_id, mode, teach_me_mode)`, adds `idx_sessions_user_guideline_teach_mode` lookup
20. `_apply_issues_table()` — verification only
21. `_apply_practice_mode_support()` — defensively rebuilds the paused-session unique index to include `teach_me_mode` (or fall back to 3-col if column missing)
22. `_apply_chapter_jobs_guideline_id()` — adds `guideline_id` to chapter_processing_jobs, backfills historical post-sync rows, drops legacy `idx_chapter_active_job`, creates split partial unique indexes (`idx_chapter_active_chapter_job` + `idx_chapter_active_topic_job`) + lookup `idx_chapter_jobs_guideline`
23. `_apply_topic_stage_runs_table()` — verifies + ensures `idx_topic_stage_runs_state` and partial `idx_topic_stage_runs_is_stale WHERE is_stale=TRUE`
24. `_apply_topic_content_hashes_table()` — drops legacy `teaching_guidelines.explanations_input_hash` column (broken — keyed on guideline_id which dies on resync); verifies `topic_content_hashes` table (curriculum-tuple keyed)
25. `_apply_practice_tables()` — creates partial unique index `uq_practice_attempts_one_inprogress_per_topic`; seeds `practice_bank_generator` + `practice_grader` configs
26. `_cleanup_exam_and_old_practice_data()` — destructive lets-practice-v2 step 12: in a single `engine.begin()` transaction deletes child events, deletes `sessions WHERE mode IN ('exam','practice')`, drops `sessions.exam_score` + `sessions.exam_total`. Idempotent
27. `_apply_llm_config_reasoning_effort_column()` — adds `reasoning_effort VARCHAR NOT NULL DEFAULT 'max'` to llm_config
28. `_seed_llm_config()` — seeds defaults from `_LLM_CONFIG_SEEDS` (only when table is empty)
29. `_seed_feature_flags()` — inserts `_FEATURE_FLAG_SEEDS` rows that don't yet exist

```bash
# Run migrations
cd llm-backend
source venv/bin/activate
python db.py --migrate
```

**Adding new columns to existing tables:**
1. Add column to the SQLAlchemy model in `entities.py`
2. Add an `ALTER TABLE` migration in `db.py` with column existence check via `inspect()`
3. Run `python db.py --migrate`

**V1 data cleanup** (one-time, after migration):
```bash
python scripts/cleanup_v1_data.py              # dry run — shows what would be deleted
python scripts/cleanup_v1_data.py --execute    # actually delete V1 books, guidelines, study plans
```

---

## Connection Management

**File:** `database.py`

`DatabaseManager` -- Singleton with lazy-initialized engine and session factory.

| Setting | Default | Description |
|---------|---------|-------------|
| `db_pool_size` | 5 | Connection pool size |
| `db_max_overflow` | 10 | Max overflow connections |
| `db_pool_timeout` | 30s | Pool checkout timeout |
| `pool_pre_ping` | true | Verify connections before use |
| `pool_recycle` | 280s | Recycle connections before server-side idle timeout |
| `echo` | false | SQL logging (enabled when `LOG_LEVEL=DEBUG`) |

**FastAPI integration:** `get_db()` dependency yields a session and closes in `finally`.

**Transaction scope:** `session_scope()` context manager provides automatic commit/rollback -- commits on success, rolls back on exception, always closes.

**Health check:** `health_check()` runs `SELECT 1` to verify connectivity.

**Testing:** `reset_db_manager()` disposes the engine and resets the singleton (used in test teardown).

---

## Key Files

| File | Purpose |
|------|---------|
| `shared/models/entities.py` | Core ORM models (User, Session, Event, Content, TeachingGuideline, StudyPlan, SessionFeedback, Book, LLMConfig, KidEnrichmentProfile, KidPersonality, FeatureFlag, TopicExplanation, TopicDialogue, StudentTopicCards, Issue, PracticeQuestion, PracticeAttempt) |
| `book_ingestion_v2/models/database.py` | V2 pipeline ORM models (BookChapter, ChapterPage, ChapterChunk, ChapterTopic, ChapterProcessingJob, TopicStageRun, TopicContentHash) |
| `db.py` | Migration CLI + helpers (`_LLM_CONFIG_SEEDS`, `_FEATURE_FLAG_SEEDS`, `_ensure_llm_config`) |
| `database.py` | `DatabaseManager` (lazy engine, QueuePool, pool_pre_ping, pool_recycle=280s), `get_db()` FastAPI dependency, `session_scope()` context manager, `health_check()`, `reset_db_manager()` |
| `config.py` | Database URL and pool settings via pydantic-settings |
| `scripts/cleanup_v1_data.py` | One-time V1 data cleanup script (`--execute` to delete) |
