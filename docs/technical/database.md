# Database

Schema, tables, migrations, and connection management.

---

## Database Overview

- **Engine:** Aurora Serverless v2 (PostgreSQL)
- **ORM:** SQLAlchemy
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
| `email` | VARCHAR | Email address (nullable) |
| `phone` | VARCHAR | Phone number (nullable) |
| `auth_provider` | VARCHAR | `email`, `phone`, or `google` |
| `name` | VARCHAR | Display name |
| `age` | INT | Student age |
| `grade` | INT | School grade |
| `board` | VARCHAR | Education board |
| `school_name` | VARCHAR | School name |
| `about_me` | TEXT | Self-description |
| `is_active` | BOOL | Account active flag |
| `onboarding_complete` | BOOL | Onboarding wizard completed |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

### Sessions

**Table:** `sessions` | **Model:** `Session` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `student_json` | TEXT | Student context (serialized JSON) |
| `goal_json` | TEXT | Session goal (serialized JSON) |
| `state_json` | TEXT | Full TutorState (serialized SessionState) |
| `mastery` | FLOAT | Current mastery score |
| `step_idx` | INT | Current step index |
| `user_id` | VARCHAR | FK → users (nullable, supports anonymous) |
| `subject` | VARCHAR | Denormalized subject name |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

### Events

**Table:** `events` | **Model:** `Event` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `session_id` | VARCHAR | FK → sessions |
| `node` | VARCHAR | Event type (Present/Check/Diagnose/Remediate/Advance) |
| `step_idx` | INT | Step index at time of event |
| `payload_json` | TEXT | Event data (serialized JSON) |
| `created_at` | DATETIME | Timestamp |

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
| `topic` | VARCHAR | Legacy topic name (backward compat) |
| `subtopic` | VARCHAR | Legacy subtopic name (backward compat) |
| `topic_key` | VARCHAR | Slugified topic identifier |
| `subtopic_key` | VARCHAR | Slugified subtopic identifier |
| `topic_title` | VARCHAR | Human-readable topic name |
| `subtopic_title` | VARCHAR | Human-readable subtopic name |
| `topic_summary` | TEXT | Topic summary (20-40 words) |
| `subtopic_summary` | TEXT | Subtopic summary (15-30 words) |
| `guideline` | TEXT | Complete teaching guidelines |
| `source_page_start` | INT | First source page |
| `source_page_end` | INT | Last source page |
| `status` | VARCHAR | `synced` (default after sync) |
| `review_status` | VARCHAR | `TO_BE_REVIEWED` or `APPROVED` |
| `version` | INT | Version counter |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

V1 legacy columns (nullable, not actively used): `objectives_json`, `examples_json`, `misconceptions_json`, `assessments_json`, `teaching_description`, `description`, `evidence_summary`, `confidence`, `metadata_json`, `source_pages`.

### Study Plans

**Table:** `study_plans` | **Model:** `StudyPlan` (`shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `guideline_id` | VARCHAR | FK → teaching_guidelines (unique, 1:1) |
| `plan_json` | TEXT | Study plan steps (serialized JSON) |
| `generator_model` | VARCHAR | Model used to generate |
| `reviewer_model` | VARCHAR | Model used to review |
| `status` | VARCHAR | `generated` or `approved` |
| `version` | INT | Version counter |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

### Books (Book Ingestion)

**Table:** `books` | **Model:** `Book` (`book_ingestion/models/database.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (slug: author_subject_grade_year) |
| `title` | VARCHAR | Book title |
| `author` | VARCHAR | Author name |
| `edition` | VARCHAR | Edition |
| `country` | VARCHAR | Country |
| `board` | VARCHAR | Education board |
| `grade` | INT | Grade level |
| `subject` | VARCHAR | Subject |
| `s3_prefix` | VARCHAR | `books/{book_id}/` |
| `metadata_s3_key` | VARCHAR | `books/{book_id}/metadata.json` |
| `cover_image_s3_key` | VARCHAR | Optional cover image |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |
| `created_by` | VARCHAR | Creator username |

### Book Jobs

**Table:** `book_jobs` | **Model:** `BookJob` (`book_ingestion/models/database.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `book_id` | VARCHAR | FK → books |
| `job_type` | VARCHAR | extraction, finalization, sync |
| `status` | VARCHAR | running, completed, failed |
| `started_at` | DATETIME | Start timestamp |
| `completed_at` | DATETIME | Completion timestamp |
| `error_message` | TEXT | Error details on failure |

### Book Guidelines

**Table:** `book_guidelines` | **Model:** `BookGuideline` (`book_ingestion/models/database.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `book_id` | VARCHAR | FK → books |
| `guideline_s3_key` | VARCHAR | S3 path to guideline JSON |
| `status` | VARCHAR | draft, pending_review, approved, rejected |
| `review_status` | VARCHAR | TO_BE_REVIEWED, APPROVED |
| `version` | INT | Version counter |

---

## Relationships

```
users ──1:N──► sessions ──1:N──► events
teaching_guidelines ──1:1──► study_plans
books ──1:N──► book_jobs
books ──1:N──► book_guidelines
```

- `Session.user_id` → `User.id` (nullable — anonymous sessions supported)
- `Event.session_id` → `Session.id`
- `StudyPlan.guideline_id` → `TeachingGuideline.id` (unique constraint, 1:1)
- `BookJob.book_id` → `Book.id`
- `BookGuideline.book_id` → `Book.id`

---

## Migration Approach

**File:** `db.py`

Custom imperative migration (not Alembic):

1. `Base.metadata.create_all()` — Creates new tables (idempotent for existing)
2. `_apply_session_columns()` — Inspects existing columns, conditionally runs `ALTER TABLE ADD COLUMN` for missing ones

```bash
# Run migrations
cd llm-backend
source venv/bin/activate
python db.py --migrate
```

**Adding new columns to existing tables:**
1. Add column to the SQLAlchemy model in `entities.py`
2. Add an `ALTER TABLE` migration in `db.py` with column existence check
3. Run `python db.py --migrate`

---

## Connection Management

**File:** `database.py`

`DatabaseManager` — Singleton with lazy-initialized engine and session factory.

| Setting | Default | Description |
|---------|---------|-------------|
| `db_pool_size` | 5 | Connection pool size |
| `db_max_overflow` | 10 | Max overflow connections |
| `db_pool_timeout` | 30s | Pool checkout timeout |
| `pool_pre_ping` | true | Verify connections before use |

**FastAPI integration:** `get_db()` dependency yields a session and closes in `finally`.

**Health check:** `health_check()` runs `SELECT 1` to verify connectivity.
