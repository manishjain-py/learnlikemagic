# Book & Guidelines — Technical

Pipeline architecture for book ingestion, OCR, guideline extraction, and study plan generation.

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend: BooksDashboard → BookDetail → PageUploadPanel            │
│            → GuidelinesPanel → GuidelinesReview                      │
│            → useJobPolling (progress polling hook)                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ REST API
┌───────────────────────────────▼─────────────────────────────────────┐
│  Backend: BookService, PageService, GuidelineExtractionOrchestrator │
│           DBSyncService, JobLockService, StudyPlanOrchestrator      │
│           BackgroundTaskRunner (thread-based async execution)        │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│  PostgreSQL: Book, BookJob, BookGuideline, TeachingGuideline,       │
│              StudyPlan, LLMConfig                                   │
│  S3: books/{book_id}/ (pages, raw/, OCR text, guideline shards)    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Phases

| Phase | Action | Endpoint | Key Service |
|-------|--------|----------|-------------|
| 1 | Create Book | `POST /admin/books` | BookService |
| 2a | Upload Single Page + OCR | `POST /admin/books/{id}/pages` | PageService |
| 2b | Bulk Upload Pages + Background OCR | `POST /admin/books/{id}/pages/bulk` | PageService + BackgroundTaskRunner |
| 2c | Retry Failed OCR | `POST /admin/books/{id}/pages/{num}/retry-ocr` | PageService |
| 3 | Approve Pages | `PUT /admin/books/{id}/pages/{num}/approve` | PageService |
| 4 | Generate Guidelines (background) | `POST /admin/books/{id}/generate-guidelines` | GuidelineExtractionOrchestrator |
| 5 | Finalize (background) | `POST /admin/books/{id}/finalize` | Orchestrator (name refinement + dedup) |
| 6 | Sync to DB | `PUT /admin/books/{id}/guidelines/approve` or `POST /admin/guidelines/books/{id}/sync-to-database` | DBSyncService |
| 7 | Review Guidelines | `GET /admin/guidelines/review` | TeachingGuideline queries |
| 8 | Approve Individual | `POST /admin/guidelines/{id}/approve` | TeachingGuideline update |
| 9 | Generate Study Plans | `POST /admin/guidelines/{id}/generate-study-plan` | StudyPlanOrchestrator |

---

## Background Task Infrastructure

Extraction, finalization, and bulk OCR run as background tasks using Python threads. The `background_task_runner` module manages the lifecycle:

```
Request → acquire_lock(pending) → return job_id → background thread
                                                    → start_job(running)
                                                    → update_progress(heartbeat)
                                                    → release_lock(completed|failed)
```

### Job State Machine

```
pending → running → completed
                  → failed
pending → failed (abandoned: never started within heartbeat threshold)
running → failed (stale: heartbeat expired)
```

### Key Design Decisions

- **One job per book**: Partial unique index on `(book_id, status)` WHERE status IN ('pending', 'running') enforces at most one active job per book at the database level.
- **Heartbeat-based stale detection**: Running jobs must update their heartbeat. If no heartbeat for 2 minutes (`HEARTBEAT_STALE_THRESHOLD`), the job is auto-marked failed on the next read.
- **Pending stale detection**: A pending job that was never started within the threshold is auto-marked failed (catches background thread crashes before `start_job`).
- **Row-level locking**: `SELECT ... FOR UPDATE` prevents TOCTOU races between stale detection and `start_job`.
- **Resume support**: `last_completed_item` tracks the last successfully processed page. Callers can resume from this point by passing `resume: true` in the extraction request.
- **Error classification**: `progress_detail` JSON stores per-page errors with `error_type` ("retryable" for rate limits/timeouts, "terminal" for data problems).
- **Independent DB sessions**: Background threads create their own DB session via `get_db_manager().session_factory()` to avoid request-scoped session lifecycle issues.

---

## Phase 1-3: Book & Page Management

### Create Book
```
POST /admin/books → BookService.create_book()
  1. Generate book_id (slug: author_subject_grade_year, uniqueness checked against DB)
  2. Insert Book row in PostgreSQL via BookRepository (created_by defaults to "admin")
  3. Create S3: books/{book_id}/metadata.json (empty pages list, total_pages=0)
```

### Delete Book
```
DELETE /admin/books/{id} → BookService.delete_book()
  1. Delete all S3 files under books/{book_id}/ prefix
  2. Delete Book row from PostgreSQL (cascades to book_guidelines, book_jobs)
```

### Upload Single Page + OCR
```
POST /admin/books/{id}/pages → PageService.upload_page()
  0. Block if bulk OCR job is running (409 if ocr_batch job is pending/running)
  1. Validate image (png/jpg/jpeg/tiff/webp, max 20MB)
  2. Convert to PNG via PIL, upload to S3 as books/{book_id}/{page_num}.png
  3. OCR via OpenAI Vision (model from DB config, with retry up to 2 attempts)
  4. Save OCR text to S3 as books/{book_id}/{page_num}.txt
  5. Update metadata.json (add page entry with status "pending_review", ocr_status "completed")
```

### Bulk Upload Pages + Background OCR
```
POST /admin/books/{id}/pages/bulk → PageService (request path) + run_bulk_ocr_background (background)

Request path (fast):
  1. Validate all images (metadata only: filename extension + size)
  2. Acquire job lock (type "ocr_batch", 409 if any job running)
  3. Sort files by filename for consistent page ordering
  4. Stream raw files to S3 as books/{book_id}/raw/{page_num}.{ext} (no conversion)
  5. Update metadata.json per page (ocr_status: "pending")
  6. Return BulkUploadResponse with job_id and page_numbers

Background thread (run_bulk_ocr_background):
  For each page:
    1. Load raw image from S3
    2. Convert to PNG, upload as books/{book_id}/{page_num}.png
    3. Run OCR via OpenAI Vision
    4. Save OCR text to S3 as books/{book_id}/{page_num}.txt
    5. Update in-memory metadata (ocr_status: "completed" or "failed")
    6. Update job progress in DB (heartbeat + completed/failed counts)
    7. Flush metadata.json to S3 every 5 pages (METADATA_FLUSH_INTERVAL)
  Final: flush metadata, release lock
```

### Retry Failed OCR
```
POST /admin/books/{id}/pages/{num}/retry-ocr → PageService.retry_page_ocr()
  1. Load image (prefer converted PNG, fall back to raw image)
  2. If raw image only: convert to PNG and upload
  3. Run OCR
  4. Save text, update metadata (ocr_status → completed or failed)
  Runs synchronously (~10s for single page)
```

### Page Operations
- `PUT .../pages/{num}/approve` — Set status to "approved" in metadata.json, records `approved_at` timestamp
- `DELETE .../pages/{num}` — Delete image + text from S3, renumber all remaining pages sequentially, update `total_pages`
- `GET /admin/books/{id}/pages/{num}` — Get page with presigned URLs (image + text), inline OCR text, and status

---

## Phase 4: Guidelines Generation

### Per-Page Processing

```
POST /admin/books/{id}/generate-guidelines
  Body: {start_page, end_page, auto_sync_to_db: false, resume: false}
  Returns: {job_id, status: "started", start_page, end_page, total_pages, message}
```

The endpoint acquires a job lock, reads the LLM model from DB config via `LLMConfigService.get_config("book_ingestion")`, and launches a background thread via `run_in_background(run_extraction_background, ...)`.

**Resume mode**: If `resume: true`, the endpoint reads `last_completed_item` from the latest extraction job and sets `start_page` to `last_completed_item + 1`. Returns `status: "already_complete"` if all pages were already processed.

The background thread creates its own orchestrator instance and processes pages sequentially:

For each page:

| Step | Service | Description |
|------|---------|-------------|
| 1 | - | Load OCR text from S3 (`{page_num:03d}.ocr.txt` or `{page_num}.txt`) |
| 2 | MinisummaryService | Generate detailed summary (5-6 lines, ~150 words) |
| 3 | ContextPackService | Build context: 5 recent page summaries + all open topic guidelines |
| 4 | BoundaryDetectionService | Detect topic boundary + extract guidelines (combined LLM call) |
| 5 | GuidelineMergeService | If continuing: LLM-based intelligent merge into existing shard |
| 6 | TopicSubtopicSummaryService | Generate subtopic summary (15-30 words) |
| 7 | - | Save shard to S3 |
| 8 | TopicSubtopicSummaryService | Generate/update topic summary (20-40 words) |
| 9 | IndexManagementService | Update GuidelinesIndex + PageIndex |
| 10 | - | Save page guideline (minisummary) to S3 for context building |

After each page, the orchestrator checks for stable subtopics (5-page gap threshold) and the background runner updates job progress (heartbeat, completed/failed counts, per-page errors).

### Boundary Detection

```python
BoundaryDetectionService.detect(context_pack, page_text)
# Model: from DB config, temp=0.2
# Input: Full page text (not summary), context pack with guidelines
# Output: (is_new, topic_key, topic_title, subtopic_key, subtopic_title, page_guidelines)
# Uses JSON response format with BoundaryDecision Pydantic model
```

If `is_new_topic`: create new SubtopicShard with extracted guidelines.
Otherwise: load existing shard and LLM-merge `page_guidelines` into `shard.guidelines`.

The context pack includes full guidelines text (not just evidence summaries) for all open topics, enabling the LLM to make accurate boundary decisions.

### Guideline Merging

```python
GuidelineMergeService.merge(existing_guidelines, new_page_guidelines, topic_title, subtopic_title, grade, subject)
# Model: from DB config, temp=0.3
# Fallback: simple concatenation if LLM merge fails
```

### Stability

A subtopic is marked "stable" after 5 pages without updates (configurable via `STABILITY_THRESHOLD`). Status is tracked in the GuidelinesIndex only, not in shard files (per GAP-001 design decision).

---

## Phase 5: Finalize

```
POST /admin/books/{id}/finalize
  Body: {auto_sync_to_db: false}
  Returns: {job_id, status: "started", message}
```

Also available via guidelines admin API:
```
POST /admin/guidelines/books/{id}/finalize?auto_sync=false
```

The book routes endpoint acquires a job lock and launches `run_finalization_background` in a background thread. The guidelines admin endpoint runs synchronously with its own job lock.

Finalization steps:

1. Mark all open/stable shards as "final" (update timestamps)
2. **TopicNameRefinementService** — LLM refines topic/subtopic names based on complete guideline content. If names change, shards are saved with new keys and old files are deleted.
3. **TopicDeduplicationService** — LLM analyzes all shards holistically to identify duplicate subtopics
4. **GuidelineMergeService** — Merge each identified duplicate pair (keep first shard, merge second into it, delete second)
5. **TopicSubtopicSummaryService** — Regenerate all topic summaries from updated subtopic summaries
6. Optionally sync to database if `auto_sync_to_db=true`

---

## Phase 6: Sync to DB

Two routes trigger DB sync, using **different mechanisms**:

1. **Book routes**: `PUT /admin/books/{id}/guidelines/approve` — Per-shard upsert sync
2. **Guidelines admin routes**: `POST /admin/guidelines/books/{id}/sync-to-database` — Full snapshot sync

### Sync Mechanism 1: Per-Shard Upsert (Book Routes)

```python
# PUT /admin/books/{id}/guidelines/approve
  1. Update all non-final shards to "final" in GuidelinesIndex
  2. For each final shard: DBSyncService.sync_shard(shard, ...)
     - _find_existing_guideline(book_id, topic_key, subtopic_key)
     - If exists: UPDATE row
     - If new: INSERT row with review_status = "TO_BE_REVIEWED"
```

### Sync Mechanism 2: Full Snapshot (Guidelines Admin Routes)

```python
# POST /admin/guidelines/books/{id}/sync-to-database
DBSyncService.sync_book_guidelines(book_id, s3_client, book_metadata)
  1. Load GuidelinesIndex from S3
  2. Load all SubtopicShard files referenced by the index
  3. DELETE all existing teaching_guidelines rows for this book_id
  4. INSERT all shards as new rows with review_status = "TO_BE_REVIEWED"
```

### Field Mapping (Both Methods)

Each row maps shard fields to the `teaching_guidelines` table:
- `guideline` column receives the single `guidelines` text field from the shard
- `topic` and `subtopic` columns receive `topic_title` and `subtopic_title` (legacy compatibility)
- `topic_key`, `subtopic_key`, `topic_summary`, `subtopic_summary` are stored directly
- Status is set to `"synced"`, review_status to `"TO_BE_REVIEWED"`

---

## Phase 7-8: Review Workflow

Two-level review:
1. **Book-level** — View guidelines by book via `GET /admin/guidelines/books/{id}/review`, filter by status
2. **Cross-book** — Browse all guidelines via `GET /admin/guidelines/review` with filters (country, board, grade, subject, status). Use `GET /admin/guidelines/review/filters` to get available filter options and status counts (total, pending, approved).
3. **Individual** — Approve/reject via `POST /admin/guidelines/{id}/approve` (body: `{approved: bool}`)

Review statuses: `TO_BE_REVIEWED` (default after sync), `APPROVED`. Rejecting sets back to `TO_BE_REVIEWED`.

Guidelines can also be deleted individually from the database via `DELETE /admin/guidelines/{id}`.

Manual editing of guidelines in S3 is disabled for MVP (`PUT /admin/guidelines/books/{id}/subtopics/{key}` returns 501 Not Implemented).

---

## Phase 9: Study Plan Generation

```
POST /admin/guidelines/{id}/generate-study-plan
```

The study plan system uses separate LLM configurations for generator and reviewer, read from DB config:
- `LLMConfigService.get_config("study_plan_generator")` — provider + model for generation
- `LLMConfigService.get_config("study_plan_reviewer")` — provider + model for review

Each config can specify a different provider (OpenAI, Google, Anthropic) and model. The orchestrator is built via the `_build_study_plan_orchestrator(db)` helper in the admin API, which creates two separate `LLMService` instances with the appropriate API keys and configs.

### AI-to-AI Review Loop

```python
StudyPlanOrchestrator.generate_study_plan(guideline_id, force_regenerate=False)
  1. Check if plan exists — return existing if not force_regenerate
  2. Load TeachingGuideline from DB
  3. StudyPlanGeneratorService.generate_plan(guideline)
     - Uses high reasoning effort
     - Strict structured output (Pydantic schema → JSON schema via LLMService.make_schema_strict)
     - Returns: {plan, reasoning, model}
  4. StudyPlanReviewerService.review_plan(plan, guideline)
     - Uses JSON mode
     - Returns: {approved, feedback, suggested_improvements, overall_rating, model}
  5. If not approved: _improve_plan() — single revision pass using reviewer LLM
     - On improvement failure: saves original plan anyway (fail-safe)
  6. Save StudyPlan row to DB (create or update, tracks version, was_revised flag)
```

### Study Plan Schema

```python
class StudyPlan:
    todo_list: List[StudyPlanStep]  # 3-5 steps
    metadata: StudyPlanMetadata

class StudyPlanStep:
    step_id: str          # e.g., "step_1"
    title: str            # Brief, catchy title
    description: str      # Short activity description
    teaching_approach: str # e.g., "Visual + Gamification"
    success_criteria: str  # Observable completion outcome
    status: str           # "pending" (default)

class StudyPlanMetadata:
    plan_version: int
    estimated_duration_minutes: int
    difficulty_level: str
    is_generic: bool      # True (default)
    creative_theme: str   # Optional theme
```

Bulk: `POST /admin/guidelines/bulk-generate-study-plans` with `{guideline_ids, force_regenerate}`

---

## Data Models

### SubtopicShard (S3)

```python
class SubtopicShard:
    # Identifiers
    topic_key, topic_title: str
    subtopic_key, subtopic_title: str
    subtopic_summary: str           # 15-30 words

    # Page range
    source_page_start, source_page_end: int

    # Single guidelines field (V2 — replaces structured objectives/examples/etc.)
    guidelines: str                 # Complete teaching guidelines in natural language

    # Metadata
    version: int
    created_at, updated_at: str     # ISO timestamps

    # NOTE: status is NOT stored in shard — tracked only in index.json (GAP-001)
```

### GuidelinesIndex (S3)

```python
class GuidelinesIndex:
    book_id: str
    topics: List[TopicIndexEntry]   # [{topic_key, topic_title, topic_summary, subtopics}]
    version: int
    last_updated: datetime

class SubtopicIndexEntry:
    subtopic_key, subtopic_title, subtopic_summary: str
    status: "open" | "stable" | "final" | "needs_review"
    page_range: str                 # e.g., "2-6"
```

### PageIndex (S3)

```python
class PageIndex:
    book_id: str
    pages: Dict[int, PageAssignment]  # page_num -> assignment
    version: int
    last_updated: datetime

class PageAssignment:
    topic_key, subtopic_key: str
    confidence: float               # 0.0-1.0 (V2 uses fixed 0.9)
    provisional: bool
```

### ContextPack (in-memory, passed to LLM)

```python
class ContextPack:
    book_id: str
    current_page: int
    book_metadata: dict             # grade, subject, board, total_pages
    open_topics: List[OpenTopicInfo]  # Topics with full guidelines text
    recent_page_summaries: List[RecentPageSummary]  # Last 5 pages
    toc_hints: ToCHints             # current_chapter, next_section_candidate
```

### S3 Structure

```
books/{book_id}/
  metadata.json                     # Book metadata + page list
  {page_num}.png                    # Page image (converted to PNG)
  {page_num}.txt                    # OCR text
  raw/
    {page_num}.{ext}                # Raw uploaded images (bulk upload, pre-conversion)
  pages/
    {page_num:03d}.ocr.txt          # Alternative OCR text path
    {page_num:03d}.page_guideline.json  # Page minisummary (for context building)
  guidelines/
    index.json                      # Topics/subtopics registry with statuses
    page_index.json                 # Page-to-subtopic mapping
    topics/{topic_key}/subtopics/{subtopic_key}.latest.json  # Shard files
```

### Database Tables

#### `books`
Core book metadata. Key fields: `id`, `title`, `author`, `edition`, `edition_year`, `country`, `board`, `grade`, `subject`, `cover_image_s3_key`, `s3_prefix`, `metadata_s3_key`, `created_by`. Index on `(country, board, grade, subject)`.

#### `book_guidelines`
AI-generated guideline versions for review tracking. Fields: `id`, `book_id` (FK), `guideline_s3_key`, `status`, `review_status`, `version`. Index on `book_id`.

#### `book_jobs`
Active job tracking for concurrency control. Fields: `id`, `book_id` (FK), `job_type` (extraction/finalization/sync/ocr_batch), `status` (pending/running/completed/failed), `total_items`, `completed_items`, `failed_items`, `current_item`, `last_completed_item`, `progress_detail` (JSON text), `heartbeat_at`, `started_at`, `completed_at`, `error_message`. Partial unique index on `(book_id, status)` with `WHERE status IN ('pending', 'running')` ensures at most one active job per book at the database level.

#### `teaching_guidelines`
Production guidelines used by the tutor. Created by DB sync. Key fields: `id`, `book_id`, `country`, `board`, `grade`, `subject`, `topic`, `subtopic`, `guideline` (text), `topic_key`, `subtopic_key`, `topic_title`, `subtopic_title`, `topic_summary`, `subtopic_summary`, `source_page_start`, `source_page_end`, `status`, `version`, `review_status`.

#### `teaching_guidelines` — V1/V2 Column Coexistence

The table currently has both V1 structured fields and V2 fields. V1 columns remain in the schema for backward compatibility but are not populated by the V2 pipeline:

**V2 columns (active):** `id`, `country`, `board`, `grade`, `subject`, `book_id`, `topic`, `subtopic`, `guideline`, `topic_key`, `subtopic_key`, `topic_title`, `subtopic_title`, `topic_summary`, `subtopic_summary`, `source_page_start`, `source_page_end`, `status`, `version`, `review_status`, `created_at`, `updated_at`.

**V1 columns (deprecated, nullable):** `objectives_json`, `examples_json`, `misconceptions_json`, `assessments_json`, `teaching_description`, `description`, `evidence_summary`, `confidence`, `metadata_json`, `source_pages`.

#### `study_plans`

Pre-generated study plans with a 1:1 relationship to `teaching_guidelines`. Fields: `id`, `guideline_id` (FK, unique), `plan_json` (JSON string), `generator_model`, `reviewer_model`, `generation_reasoning`, `reviewer_feedback`, `was_revised` (0/1), `status` (generated/approved), `version`, `created_at`, `updated_at`. Index on `guideline_id`.

#### `llm_config`

Centralized LLM model configuration per component. Key: `component_key` (e.g., `"book_ingestion"`, `"study_plan_generator"`, `"study_plan_reviewer"`). Fields: `provider` (openai/anthropic/google), `model_id`, `description`, `updated_at`, `updated_by`.

### Derived Book Status

Status computed at runtime from counts (no stored status field):

```
NO_PAGES → READY_FOR_EXTRACTION → PROCESSING → PENDING_REVIEW → APPROVED
```

Computed from: `page_count` (from S3 metadata), `guideline_count` (from `book_guidelines` table), `approved_guideline_count`, `has_active_job` (from `book_jobs` table).

---

## LLM Calls

All book ingestion services use the same model from DB config (`LLMConfigService.get_config("book_ingestion")`). Study plan services use separate generator and reviewer configs.

| Service | Config Key | Purpose | Temp |
|---------|-----------|---------|------|
| OCRService | `book_ingestion` | Extract text from images | - |
| MinisummaryService | `book_ingestion` | Detailed page summary (5-6 lines, ~150 words, no hard token cap) | 0.3 |
| BoundaryDetectionService | `book_ingestion` | Topic detection + guidelines extraction | 0.2 |
| GuidelineMergeService | `book_ingestion` | LLM-based intelligent merge | 0.3 |
| TopicSubtopicSummaryService | `book_ingestion` | Generate subtopic/topic summaries | 0.3 |
| TopicNameRefinementService | `book_ingestion` | Polish names during finalization | 0.3 |
| TopicDeduplicationService | `book_ingestion` | Find duplicate subtopics | 0.2 |
| StudyPlanGeneratorService | `study_plan_generator` | Generate study plans (high reasoning) | - |
| StudyPlanReviewerService | `study_plan_reviewer` | Review study plans | - |

Book ingestion prompt templates are stored in `llm-backend/book_ingestion/prompts/` as `.txt` files and loaded at service initialization. The MinisummaryService specifically loads `minisummary_v2.txt` (not the V1 `minisummary.txt`). Study plan prompts are stored in `llm-backend/shared/prompts/templates/` (`study_plan_generator.txt`, `study_plan_reviewer.txt`, `study_plan_improve.txt`) and loaded via the shared `PromptLoader`.

The study plan generator uses `LLMService` which supports multiple providers (OpenAI, Google, Anthropic). The reviewer calls the LLM with `json_mode=True`. The improvement step also uses the reviewer LLM with `json_mode=True`.

---

## API Endpoints

### Book Management (`/admin/books/*`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/books` | Create book |
| `GET` | `/admin/books` | List books with filters (country, board, grade, subject) |
| `GET` | `/admin/books/{id}` | Get book details with pages |
| `DELETE` | `/admin/books/{id}` | Delete book + all S3 data |
| `POST` | `/admin/books/{id}/pages` | Upload single page + inline OCR |
| `POST` | `/admin/books/{id}/pages/bulk` | Bulk upload pages (up to 200) + background OCR |
| `POST` | `/admin/books/{id}/pages/{num}/retry-ocr` | Retry OCR for a failed page |
| `GET` | `/admin/books/{id}/pages/{num}` | Get page with presigned URLs + OCR text |
| `PUT` | `/admin/books/{id}/pages/{num}/approve` | Approve page |
| `DELETE` | `/admin/books/{id}/pages/{num}` | Delete page + renumber |
| `POST` | `/admin/books/{id}/generate-guidelines` | Start extraction (background, returns job_id) |
| `GET` | `/admin/books/{id}/guidelines` | List all generated guidelines |
| `GET` | `/admin/books/{id}/guidelines/{topic}/{subtopic}` | Get specific guideline |
| `POST` | `/admin/books/{id}/finalize` | Finalize guidelines (background, returns job_id) |
| `PUT` | `/admin/books/{id}/guidelines/approve` | Approve all + sync to DB |
| `DELETE` | `/admin/books/{id}/guidelines` | Reject (delete) all guidelines |
| `GET` | `/admin/books/{id}/jobs/latest` | Get latest job status (with stale detection) |
| `GET` | `/admin/books/{id}/jobs/{job_id}` | Get specific job status |

### Guidelines Management (`/admin/guidelines/*`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/review` | List all guidelines with filters (country, board, grade, subject, status) |
| `GET` | `/review/filters` | Filter options + counts (total, pending, approved) |
| `GET` | `/books` | List books with extraction status |
| `GET` | `/books/{id}/topics` | Topic structure for book |
| `GET` | `/books/{id}/subtopics/{key}?topic_key=` | Full guideline details |
| `GET` | `/books/{id}/page-assignments` | Page-to-subtopic mapping |
| `GET` | `/books/{id}/review` | Guidelines for review by book |
| `POST` | `/books/{id}/extract?start_page=&end_page=` | Extract for page range (with job lock) |
| `POST` | `/books/{id}/finalize?auto_sync=` | Finalize book (with job lock) |
| `POST` | `/books/{id}/sync-to-database` | Full snapshot sync to DB |
| `PUT` | `/books/{id}/subtopics/{key}?topic_key=` | Update guideline (returns 501 — disabled for MVP) |
| `POST` | `/{id}/approve` | Approve/reject guideline (body: `{approved: bool}`) |
| `DELETE` | `/{id}` | Delete guideline from DB |
| `POST` | `/{id}/generate-study-plan?force_regenerate=` | Generate study plan |
| `GET` | `/{id}/study-plan` | Get study plan |
| `POST` | `/bulk-generate-study-plans` | Bulk generate (body: `{guideline_ids, force_regenerate}`) |

### Job Polling

The frontend polls `GET /admin/books/{id}/jobs/latest` every 3 seconds (via the `useJobPolling` hook) to track progress of background operations. The endpoint performs server-side stale detection on every read.

Response shape (`JobStatusResponse`):
- `job_id`, `book_id`, `job_type` (extraction/finalization/ocr_batch)
- `status` (pending/running/completed/failed)
- `total_items`, `completed_items`, `failed_items`, `current_item`
- `last_completed_item` (resume point)
- `progress_detail` (JSON string: `{page_errors, stats}`)
- `heartbeat_at`, `started_at`, `completed_at`, `error_message`

### Job Locking

The extraction and finalization endpoints acquire job locks via `JobLockService`. A `409 Conflict` is returned if a job is already running for the book. Locks are released on completion or failure. Single-page uploads also check for active `ocr_batch` jobs and return `409` to prevent metadata.json conflicts during bulk OCR.

---

## V1 Services (Parked / Not Used in V2 Pipeline)

The following services exist in the codebase but are NOT used by the current V2 `GuidelineExtractionOrchestrator`. They represent the V1 structured-facts approach and are preserved for potential future use:

| File | Purpose | V2 Replacement |
|------|---------|----------------|
| `services/facts_extraction_service.py` | Extract structured facts (objectives, examples, misconceptions, assessments) | Boundary detection extracts guidelines directly |
| `services/reducer_service.py` | Deterministic merge of PageFacts into shards | GuidelineMergeService (LLM-based) |
| `services/teaching_description_generator.py` | Generate 3-6 line teaching descriptions | Single guidelines field replaces this |
| `services/description_generator.py` | Generate 200-300 word comprehensive descriptions | Single guidelines field replaces this |
| `services/quality_gates_service.py` | Rule-based quality validation of shards | Parked for V2 |
| `services/stability_detector_service.py` | Detect stable subtopics (K=3 threshold) | Inline check in orchestrator (K=5) |

---

## Key Files

### Frontend (`llm-frontend/src/features/admin/`)

| File | Purpose |
|------|---------|
| `api/adminApi.ts` | API client (books + guidelines + study plans + job polling) |
| `types/index.ts` | TypeScript interfaces (Book, PageInfo, JobStatus, BulkUploadResponse, etc.) |
| `hooks/useJobPolling.ts` | React hook for polling job progress (3s interval, auto-start on mount) |
| `pages/BooksDashboard.tsx` | Books list with filters |
| `pages/BookDetail.tsx` | Book management hub |
| `pages/CreateBook.tsx` | Book creation form |
| `pages/GuidelinesReview.tsx` | Individual guideline review |
| `components/PageUploadPanel.tsx` | Drag-drop upload + OCR review |
| `components/PageViewPanel.tsx` | View approved page image + OCR text |
| `components/PagesSidebar.tsx` | Navigate approved pages list |
| `components/BookStatusBadge.tsx` | Derived status badge display |
| `components/GuidelinesPanel.tsx` | Generate/approve/reject guidelines |
| `utils/bookStatus.ts` | Derived status logic + labels + colors |

### Backend — Book Ingestion (`llm-backend/book_ingestion/`)

| File | Purpose |
|------|---------|
| **API** | |
| `api/routes.py` | FastAPI endpoints for books, pages, guidelines, job polling (under `/admin`) |
| **Services (V2 Pipeline — Active)** | |
| `services/guideline_extraction_orchestrator.py` | Main V2 pipeline coordinator + `run_extraction_background` / `run_finalization_background` top-level functions |
| `services/background_task_runner.py` | Thread-based background task runner with job lifecycle management |
| `services/book_service.py` | Book CRUD + derived status counts (uses BookRepository) |
| `services/page_service.py` | Page upload, OCR, approval, deletion, bulk upload + `run_bulk_ocr_background` top-level function |
| `services/ocr_service.py` | OpenAI Vision API wrapper (model from DB config, retry support) |
| `services/boundary_detection_service.py` | Topic detection + guidelines extraction (combined LLM call) |
| `services/guideline_merge_service.py` | LLM-based intelligent guideline merging |
| `services/context_pack_service.py` | Build LLM context (5 recent pages + full guidelines) |
| `services/minisummary_service.py` | Detailed page summaries (5-6 lines) |
| `services/index_management_service.py` | GuidelinesIndex + PageIndex CRUD, snapshots |
| `services/db_sync_service.py` | Sync to PostgreSQL teaching_guidelines (per-shard upsert + full snapshot) |
| `services/topic_name_refinement_service.py` | LLM-based name polishing during finalization |
| `services/topic_deduplication_service.py` | LLM-based duplicate subtopic detection |
| `services/topic_subtopic_summary_service.py` | LLM-generated subtopic/topic summaries |
| `services/job_lock_service.py` | Job concurrency control (state machine, heartbeat, stale detection) |
| **Services (V1 — Parked)** | |
| `services/facts_extraction_service.py` | V1: Extract structured facts from pages |
| `services/reducer_service.py` | V1: Deterministic shard merge |
| `services/teaching_description_generator.py` | V1: Generate teaching descriptions |
| `services/description_generator.py` | V1: Generate comprehensive descriptions |
| `services/quality_gates_service.py` | V1: Rule-based quality validation |
| `services/stability_detector_service.py` | V1: Stability detection (K=3) |
| **Models** | |
| `models/guideline_models.py` | Pydantic models: SubtopicShard, GuidelinesIndex, PageIndex, ContextPack, BoundaryDecision, etc. |
| `models/database.py` | SQLAlchemy ORM: Book, BookGuideline, BookJob |
| `models/schemas.py` | Pydantic API schemas: CreateBookRequest, BookResponse, PageInfo, etc. |
| **Repositories** | |
| `repositories/book_repository.py` | Book table data access (CRUD, filters, pagination) |
| `repositories/book_guideline_repository.py` | BookGuideline table data access |
| **Utils** | |
| `utils/s3_client.py` | S3 operations (upload, download, presigned URLs, delete) |
| **Prompts (V2 — Active)** | |
| `prompts/boundary_detection.txt` | Boundary detection + guidelines extraction prompt |
| `prompts/guideline_merge_v2.txt` | LLM-based guideline merge prompt |
| `prompts/minisummary_v2.txt` | Detailed page summary prompt (5-6 lines) |
| `prompts/subtopic_summary.txt` | Subtopic summary generation prompt |
| `prompts/topic_summary.txt` | Topic summary generation prompt |
| `prompts/topic_name_refinement.txt` | Name refinement prompt |
| `prompts/topic_deduplication_v2.txt` | Duplicate detection prompt |
| **Prompts (V1 — Parked)** | |
| `prompts/minisummary.txt` | V1: Compact summary prompt (60 words) |
| `prompts/facts_extraction.txt` | V1: Structured facts extraction prompt |
| `prompts/description_generation.txt` | V1: Comprehensive description prompt |
| `prompts/teaching_description.txt` | V1: Teaching description prompt |

### Backend — Study Plans (`llm-backend/study_plans/`)

| File | Purpose |
|------|---------|
| `api/admin.py` | Guidelines review + study plan endpoints (under `/admin/guidelines`) |
| `services/orchestrator.py` | AI-to-AI review loop coordinator |
| `services/generator_service.py` | Study plan generation with strict structured output (Pydantic models: `StudyPlan`, `StudyPlanStep`, `StudyPlanMetadata`) |
| `services/reviewer_service.py` | Study plan review and quality assessment |

### Backend — Shared (`llm-backend/shared/`)

| File | Purpose |
|------|---------|
| `models/entities.py` | SQLAlchemy ORM: `TeachingGuideline`, `StudyPlan`, `LLMConfig` |
| `services/llm_config_service.py` | LLM config CRUD — reads provider + model per component key |
| `services/llm_service.py` | `LLMService` — multi-provider LLM wrapper (OpenAI, Google, Anthropic) |
| `prompts/loader.py` | `PromptLoader` — loads `.txt` prompt templates from `shared/prompts/templates/` |
