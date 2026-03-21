# Database

Schema, tables, migrations, and connection management.

---

## Database Overview

- **Engine:** Aurora Serverless v2 (PostgreSQL 15.10)
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
| `mode` | VARCHAR | Learning mode: `teach_me` or `exam_me` (default `teach_me`) |
| `is_paused` | BOOL | Whether session is paused (default false) |
| `exam_score` | FLOAT | Score achieved in exam mode |
| `exam_total` | INT | Total possible exam score |
| `guideline_id` | VARCHAR | Associated teaching guideline ID |
| `state_version` | INT | Optimistic concurrency version (default 1) |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_session_user_guideline` (user_id, guideline_id, mode)

**Partial unique index (migration-created):** `idx_sessions_one_paused_per_user_guideline` on (user_id, guideline_id) WHERE is_paused = TRUE -- enforces at most one paused session per user per guideline. Additional migration-created indexes: `idx_sessions_user_id`, `idx_sessions_subject`, `idx_sessions_mode`, `idx_sessions_guideline_id`.

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
| `provider` | VARCHAR | LLM provider: `openai`, `anthropic`, `google` |
| `model_id` | VARCHAR | Model identifier (e.g. `gpt-5.2`, `claude-opus-4-6`) |
| `description` | VARCHAR | Human-readable description |
| `updated_at` | DATETIME | Last update timestamp |
| `updated_by` | VARCHAR | Who last updated the config |

**Seeded defaults** (inserted on first migration if table is empty):

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
| `fast_model` | openai | gpt-4o-mini | Lightweight model for safety checks, translation, and other fast tasks |
| `pixi_code_generator` | openai | gpt-5.3-codex | Pixi.js visual code generation from natural language |

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

### V2 Pipeline Tables

See `book_ingestion_v2/models/database.py` for the full V2 pipeline tables:
- `book_chapters` — chapter definitions from TOC
- `chapter_pages` — uploaded page images with OCR text
- `chapter_chunks` — processing chunk records
- `chapter_topics` — extracted topics with guidelines (includes `prior_topics_context` and `topic_assignment` columns for topic-quality planning)
- `chapter_processing_jobs` — background job tracking (includes `planned_topics_json` column for topic-quality planning)

---

## Relationships

```
users ──1:N──> sessions ──1:N──> events
users ──1:N──> study_plans
users ──1:1──> kid_enrichment_profiles
users ──1:N──> kid_personalities
users ──1:N──> session_feedback
teaching_guidelines ──1:N──> study_plans (per-user plans)
teaching_guidelines ──1:N──> topic_explanations (pre-computed explanation variants)
books ──1:N──> book_chapters ──1:N──> chapter_pages
books ──1:N──> book_chapters ──1:N──> chapter_topics
llm_config (standalone, no FKs)
feature_flags (standalone, no FKs)
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

---

## Migration Approach

**File:** `db.py`

Custom imperative migration (not Alembic):

1. `Base.metadata.create_all()` -- Creates new tables (idempotent for existing)
2. `_apply_session_columns()` -- Adds `user_id` and `subject` columns to sessions if missing
3. `_apply_learning_modes_columns()` -- Adds `mode`, `is_paused`, `exam_score`, `exam_total`, `guideline_id`, `state_version` columns to sessions if missing; creates partial unique index; backfills `mode='teach_me'` for existing rows
4. `_apply_user_language_columns()` -- Adds `text_language_preference` and `audio_language_preference` to users if missing
5. `_apply_user_preferred_name_column()` -- Adds `preferred_name` to users if missing
6. `_apply_sequencing_columns()` -- Adds `chapter_sequence`, `topic_sequence`, `chapter_storyline` to teaching_guidelines if missing
7. `_apply_v2_tables()` -- Creates V2 pipeline tables, unique constraints, and seeds `book_ingestion_v2` LLM config
8. `_rename_topic_subtopic_columns()` -- Renames topic/subtopic columns to chapter/topic in teaching_guidelines (idempotent)
9. `_drop_v1_tables()` -- Drops `book_guidelines` and `book_jobs` tables if they exist
10. `_drop_v1_guideline_columns()` -- Drops unused V1 columns from teaching_guidelines (`objectives_json`, `examples_json`, `misconceptions_json`, `assessments_json`, `evidence_summary`, `confidence`)
11. `_remove_v1_llm_config()` -- Removes the old `book_ingestion` LLM config entry (replaced by `book_ingestion_v2`)
12. `_apply_kid_enrichment_tables()` -- Seeds `personality_derivation` LLM config entry (tables created by `create_all`)
13. `_drop_unused_enrichment_columns()` -- Drops columns removed when enrichment was simplified from 9 to 4 sections
14. `_apply_study_plan_user_column()` -- Adds `user_id` to study_plans, drops old single-column unique constraint on guideline_id, creates composite unique index on (user_id, guideline_id)
15. `_apply_focus_mode_column()` -- Adds `focus_mode` column to users (default true); if column already exists, resets all `focus_mode = FALSE` to `TRUE`
16. `_apply_session_feedback_table()` -- Verifies session_feedback table exists (created by `create_all`)
17. `_apply_topic_planning_columns()` -- Adds `planned_topics_json` to chapter_processing_jobs, `prior_topics_context` and `topic_assignment` to chapter_topics, and `prior_topics_context` to teaching_guidelines (topic-quality planning support)
18. `_apply_topic_explanations_table()` -- Verifies topic_explanations table exists (created by `create_all`); ensures `explanation_generator` LLM config entry exists via `_ensure_llm_config()`
19. `_seed_llm_config()` -- Seeds the `llm_config` table with default rows if empty
20. `_seed_feature_flags()` -- Seeds `feature_flags` table with default flags (insert-if-missing per flag)

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
| `shared/models/entities.py` | All core ORM models (User, Session, Event, Content, TeachingGuideline, StudyPlan, SessionFeedback, Book, LLMConfig, KidEnrichmentProfile, KidPersonality, FeatureFlag, TopicExplanation) |
| `book_ingestion_v2/models/database.py` | V2 pipeline ORM models (BookChapter, ChapterPage, ChapterChunk, ChapterTopic, ChapterProcessingJob) |
| `db.py` | Migration CLI and migration functions |
| `database.py` | DatabaseManager, connection pooling, `get_db()` dependency |
| `config.py` | Database URL and pool settings via pydantic-settings |
