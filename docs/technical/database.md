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

**Indexes:** `idx_sessions_user_id` (user_id), `idx_sessions_subject` (subject), `idx_sessions_mode` (mode), `idx_sessions_guideline_id` (guideline_id)

**Partial unique index:** `idx_sessions_one_paused_per_user_guideline` on (user_id, guideline_id) WHERE is_paused = TRUE -- enforces at most one paused session per user per guideline.

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
| `topic` | VARCHAR | Legacy topic name (deprecated, use topic_title) |
| `subtopic` | VARCHAR | Legacy subtopic name (deprecated, use subtopic_title) |
| `topic_key` | VARCHAR | Slugified topic identifier |
| `subtopic_key` | VARCHAR | Slugified subtopic identifier |
| `topic_title` | VARCHAR | Human-readable topic name |
| `subtopic_title` | VARCHAR | Human-readable subtopic name |
| `topic_summary` | TEXT | Topic summary (20-40 words) |
| `subtopic_summary` | TEXT | Subtopic summary (15-30 words) |
| `guideline` | TEXT | Complete teaching guidelines |
| `source_page_start` | INT | First source page |
| `source_page_end` | INT | Last source page |
| `status` | VARCHAR | `draft`, `pending_review`, `approved`, `rejected` (default `draft`) |
| `review_status` | VARCHAR | `TO_BE_REVIEWED` or `APPROVED` (default `TO_BE_REVIEWED`) |
| `generated_at` | DATETIME | When guideline was generated |
| `reviewed_at` | DATETIME | When guideline was reviewed |
| `reviewed_by` | VARCHAR | Who reviewed the guideline |
| `version` | INT | Version counter (default 1) |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_curriculum` (country, board, grade, subject, topic)

V1 legacy columns (nullable, not actively used): `objectives_json`, `examples_json`, `misconceptions_json`, `assessments_json`, `teaching_description`, `description`, `evidence_summary`, `confidence`, `metadata_json`, `source_pages`.

### Study Plans

**Table:** `study_plans` | **Model:** `StudyPlan` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `guideline_id` | VARCHAR | FK --> teaching_guidelines (unique, 1:1, CASCADE delete) |
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

**Indexes:** `idx_study_plans_guideline` (guideline_id)

### LLM Config

**Table:** `llm_config` | **Model:** `LLMConfig` (`shared/models/entities.py`)

Centralized model configuration per component. Single source of truth for which LLM provider and model each component uses. Managed via the `/admin/llm-config` UI. No fallback logic -- missing config raises an error.

| Column | Type | Description |
|--------|------|-------------|
| `component_key` | VARCHAR | Primary key (e.g. `tutor`, `book_ingestion`) |
| `provider` | VARCHAR | LLM provider: `openai`, `anthropic`, `google` |
| `model_id` | VARCHAR | Model identifier (e.g. `gpt-5.2`, `claude-opus-4-6`) |
| `description` | VARCHAR | Human-readable description |
| `updated_at` | DATETIME | Last update timestamp |
| `updated_by` | VARCHAR | Who last updated the config |

**Seeded defaults** (inserted on first migration if table is empty):

| Component Key | Provider | Model | Purpose |
|---------------|----------|-------|---------|
| `tutor` | openai | gpt-5.2 | Main tutoring pipeline (safety + master tutor + welcome) |
| `book_ingestion` | openai | gpt-5.2 | All book ingestion services (OCR, boundaries, merge, etc.) |
| `study_plan_generator` | openai | gpt-5.2 | Study plan creation from teaching guidelines |
| `study_plan_reviewer` | openai | gpt-5.2 | Study plan review and improvement |
| `eval_evaluator` | openai | gpt-5.2 | Evaluation judge (scores tutor quality) |
| `eval_simulator` | openai | gpt-5.2 | Student simulator for evaluations |

### Books (Book Ingestion)

**Table:** `books` | **Model:** `Book` (`book_ingestion/models/database.py`)

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
| `s3_prefix` | VARCHAR | `books/{book_id}/` |
| `metadata_s3_key` | VARCHAR | `books/{book_id}/metadata.json` |
| `cover_image_s3_key` | VARCHAR | Optional cover image |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |
| `created_by` | VARCHAR | Creator username (default `admin`) |

**Indexes:** `idx_books_curriculum` (country, board, grade, subject)

### Book Jobs

**Table:** `book_jobs` | **Model:** `BookJob` (`book_ingestion/models/database.py`)

Tracks active jobs per book with progress tracking and stale detection. State machine: `pending` --> `running` --> `completed` | `failed`. Stale detection: running jobs with expired heartbeat are auto-marked failed (see `job_lock_service.py`).

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `book_id` | VARCHAR | FK --> books (CASCADE delete) |
| `job_type` | VARCHAR | `extraction`, `finalization`, `sync`, `ocr_batch` |
| `status` | VARCHAR | `pending`, `running`, `completed`, `failed` (default `pending`) |
| `total_items` | INT | Total pages to process (nullable) |
| `completed_items` | INT | Pages completed so far (default 0) |
| `failed_items` | INT | Pages that errored (default 0) |
| `current_item` | INT | Page currently being processed (nullable) |
| `last_completed_item` | INT | Last successfully processed page, for resume (nullable) |
| `progress_detail` | TEXT | JSON: per-page errors + running stats (nullable) |
| `heartbeat_at` | DATETIME | Last heartbeat from background thread (updated every 30s, nullable) |
| `started_at` | DATETIME | Start timestamp |
| `completed_at` | DATETIME | Completion timestamp |
| `error_message` | TEXT | Error details on failure |

**Partial unique index:** `idx_book_running_job` on (book_id) WHERE status IN ('pending', 'running') -- ensures at most one pending/running job per book.

### Book Guidelines

**Table:** `book_guidelines` | **Model:** `BookGuideline` (`book_ingestion/models/database.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `book_id` | VARCHAR | FK --> books (CASCADE delete) |
| `guideline_s3_key` | VARCHAR | S3 path to guideline JSON |
| `status` | VARCHAR | draft, pending_review, approved, rejected |
| `review_status` | VARCHAR | TO_BE_REVIEWED, APPROVED (default `TO_BE_REVIEWED`) |
| `generated_at` | DATETIME | When guideline was generated |
| `reviewed_at` | DATETIME | When guideline was reviewed |
| `reviewed_by` | VARCHAR | Who reviewed the guideline |
| `version` | INT | Version counter (default 1) |
| `created_at` | DATETIME | Timestamp |

**Indexes:** `idx_book_guidelines_book` (book_id)

---

## Relationships

```
users ──1:N──> sessions ──1:N──> events
teaching_guidelines ──1:1──> study_plans
books ──1:N──> book_jobs
books ──1:N──> book_guidelines
llm_config (standalone, no FKs)
```

- `Session.user_id` --> `User.id` (nullable -- anonymous sessions supported)
- `Event.session_id` --> `Session.id`
- `StudyPlan.guideline_id` --> `TeachingGuideline.id` (unique constraint, 1:1, CASCADE delete)
- `BookJob.book_id` --> `Book.id` (CASCADE delete)
- `BookGuideline.book_id` --> `Book.id` (CASCADE delete)

---

## Migration Approach

**File:** `db.py`

Custom imperative migration (not Alembic):

1. `Base.metadata.create_all()` -- Creates new tables (idempotent for existing)
2. `_apply_session_columns()` -- Adds `user_id` and `subject` columns to sessions if missing
3. `_apply_learning_modes_columns()` -- Adds `mode`, `is_paused`, `exam_score`, `exam_total`, `guideline_id`, `state_version` columns to sessions if missing; creates partial unique index; backfills `mode='teach_me'` for existing rows
4. `_apply_book_job_columns()` -- Adds progress tracking columns to book_jobs if they exist (`total_items`, `completed_items`, `failed_items`, `current_item`, `last_completed_item`, `progress_detail`, `heartbeat_at`); backfills legacy running jobs without heartbeat to `failed`; recreates partial unique index to cover both `pending` and `running` statuses
5. `_seed_llm_config()` -- Seeds the `llm_config` table with default rows if empty

```bash
# Run migrations
cd llm-backend
source venv/bin/activate
python db.py --migrate
```

**Adding new columns to existing tables:**
1. Add column to the SQLAlchemy model in `entities.py` (or `book_ingestion/models/database.py`)
2. Add an `ALTER TABLE` migration in `db.py` with column existence check via `inspect()`
3. Run `python db.py --migrate`

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
| `echo` | false | SQL logging (enabled when `LOG_LEVEL=DEBUG`) |

**FastAPI integration:** `get_db()` dependency yields a session and closes in `finally`.

**Transaction scope:** `session_scope()` context manager provides automatic commit/rollback -- commits on success, rolls back on exception, always closes.

**Health check:** `health_check()` runs `SELECT 1` to verify connectivity.

**Testing:** `reset_db_manager()` disposes the engine and resets the singleton (used in test teardown).

---

## Key Files

| File | Purpose |
|------|---------|
| `shared/models/entities.py` | All core ORM models (User, Session, Event, Content, TeachingGuideline, StudyPlan, LLMConfig) |
| `book_ingestion/models/database.py` | Book ingestion ORM models (Book, BookGuideline, BookJob) |
| `db.py` | Migration CLI and migration functions |
| `database.py` | DatabaseManager, connection pooling, `get_db()` dependency |
| `config.py` | Database URL and pool settings via pydantic-settings |
