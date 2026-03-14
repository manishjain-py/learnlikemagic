# Book Ingestion & Guidelines -- Technical

Pipeline architecture for extracting structured teaching guidelines from textbook page images using OCR + LLM processing.

---

## Pipeline Architecture

```
Create Book (metadata)
    |
    v
Define TOC (manual or OCR+LLM from TOC page images)
    |
    v
Upload Pages (per chapter, inline OCR on each page)
    |
    v
Topic Extraction (3-page chunks, LLM extracts topics + guidelines)
    |
    v
Chapter Finalization (LLM merges, dedup, names, sequences topics)
    |
    v
Sync to teaching_guidelines table
    |
    v
Study Plan Generation (LLM generate -> review -> improve loop)
```

All book ingestion code lives under `book_ingestion_v2/`. Study plan generation is a separate module under `study_plans/`.

---

## Chapter Status Machine

```
toc_defined -> upload_in_progress -> upload_complete -> topic_extraction -> chapter_finalizing -> chapter_completed
                                         |                   |                     |
                                         v                   v                     v
                                       failed <----------  failed <----------    failed
```

| Status | Meaning |
|--------|---------|
| `toc_defined` | Chapter created from TOC, no pages uploaded |
| `upload_in_progress` | Some pages uploaded but not all (or some OCR failed) |
| `upload_complete` | All pages uploaded and OCR complete -- ready for processing |
| `topic_extraction` | Chunk-by-chunk extraction running in background |
| `chapter_finalizing` | Consolidation/finalization running |
| `chapter_completed` | All topics extracted and finalized |
| `failed` | Processing failed (retryable) |

Defined in `book_ingestion_v2/constants.py` as `ChapterStatus` enum.

Topic statuses (`TopicStatus` enum in same file): `draft` -> `consolidated` -> `final` -> `approved`.

---

## Book Management

**Service:** `book_ingestion_v2/services/book_v2_service.py` (`BookV2Service`)

- Creates books with `pipeline_version=2` in the shared `books` table
- Generates book IDs from metadata: `{author}_{subject}_{grade}_{year}` with auto-incrementing suffix for uniqueness
- Initializes S3 metadata at `books/{book_id}/metadata.json`
- Delete cascades to chapters, pages, chunks, topics, processing jobs, and S3 folder

**API routes:** `book_ingestion_v2/api/book_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/v2/books` | Create book |
| GET | `/admin/v2/books` | List books (filterable by country, board, grade, subject) |
| GET | `/admin/v2/books/{book_id}` | Get book detail with chapters |
| DELETE | `/admin/v2/books/{book_id}` | Delete book and all child data |

---

## TOC Management

### TOC Extraction (OCR + LLM)

**Service:** `book_ingestion_v2/services/toc_extraction_service.py` (`TOCExtractionService`)

- Accepts 1-5 images of TOC pages (max 10 MB each)
- Converts all images to PNG format (via Pillow, supports HEIF)
- Runs OCR on each image via `OCRService`
- Sends combined OCR text to LLM with `toc_extraction.txt` prompt template
- Returns structured `TOCEntry` list -- does NOT save to DB (read-only extraction)
- Stores images and extraction result to S3 at `books/{book_id}/toc_pages/`

### TOC CRUD

**Service:** `book_ingestion_v2/services/toc_service.py` (`TOCService`)

- `save_toc`: Creates/replaces full TOC for a book. Validates sequential chapter numbers, positive page ranges, no overlaps. Blocked if any existing chapter has uploaded pages.
- `update_chapter`: Updates a single chapter entry. Blocked if pages uploaded.
- `delete_chapter`: Deletes a single chapter. Blocked if pages uploaded.
- Validation: chapter numbers must be sequential starting from 1, start_page > 0, end_page >= start_page, no range overlaps between chapters.

**API routes:** `book_ingestion_v2/api/toc_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/v2/books/{book_id}/toc/extract` | Extract TOC from images (multipart form) |
| POST | `/admin/v2/books/{book_id}/toc` | Save full TOC |
| GET | `/admin/v2/books/{book_id}/toc` | Get TOC |
| PUT | `/admin/v2/books/{book_id}/toc/{chapter_id}` | Update single chapter |
| DELETE | `/admin/v2/books/{book_id}/toc/{chapter_id}` | Delete single chapter |

---

## Page Upload & OCR

**Service:** `book_ingestion_v2/services/chapter_page_service.py` (`ChapterPageService`)

Each page upload:
1. Validates page number is within chapter's range and not a duplicate
2. Validates file format (PNG, JPG, JPEG, TIFF, WEBP) and size (max 20 MB)
3. Uploads raw image to S3 at `books/{book_id}/chapters/{ch_num}/pages/raw/{page_number}.{ext}`
4. Converts to PNG and uploads to `books/{book_id}/chapters/{ch_num}/pages/{page_number}.png`
5. Runs OCR inline using `OCRService.extract_text_from_image()` with a custom education-focused prompt (`V2_OCR_PROMPT`)
6. Uploads OCR text to `books/{book_id}/chapters/{ch_num}/pages/{page_number}.txt`
7. Creates `ChapterPage` DB record
8. Updates chapter completeness: counts uploaded and OCR-completed pages, transitions status (`toc_defined` / `upload_in_progress` / `upload_complete`)

OCR model is determined by the `book_ingestion_v2` LLM config entry.

**Retry OCR:** Re-downloads PNG from S3, re-runs OCR, updates DB and S3 text file.

**API routes:** `book_ingestion_v2/api/page_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `.../chapters/{chapter_id}/pages` | Upload page (multipart form: image + page_number) |
| GET | `.../chapters/{chapter_id}/pages` | List pages with completeness |
| GET | `.../chapters/{chapter_id}/pages/{page_num}` | Get page metadata |
| GET | `.../chapters/{chapter_id}/pages/{page_num}/detail` | Get page with presigned image URL + OCR text |
| DELETE | `.../chapters/{chapter_id}/pages/{page_num}` | Delete page |
| POST | `.../chapters/{chapter_id}/pages/{page_num}/retry-ocr` | Retry failed OCR |

---

## Topic Extraction Pipeline

### Chunk Builder

**File:** `book_ingestion_v2/utils/chunk_builder.py`

Builds non-overlapping 3-page windows from sorted page numbers. Each window includes a reference to the previous page for context continuity.

```
Pages [1,2,3,4,5,6,7,8,9,10] -> Chunks:
  [0] pages=[1,2,3]  prev=None
  [1] pages=[4,5,6]  prev=3
  [2] pages=[7,8,9]  prev=6
  [3] pages=[10]     prev=9
```

Configured via `CHUNK_SIZE=3` and `CHUNK_STRIDE=3` in `constants.py`.

### Chunk Processor

**Service:** `book_ingestion_v2/services/chunk_processor_service.py` (`ChunkProcessorService`)

Processes a single chunk through the LLM:
- Builds prompt from `chunk_topic_extraction.txt` template with book metadata, chapter metadata, current page texts, previous page context, chapter summary so far, and existing topics
- Calls LLM with `json_mode=True` and `reasoning_effort="none"` for speed
- Parses response into `ChunkExtractionOutput`: updated chapter summary + list of `TopicUpdate` (topic_key, title, is_new flag, guidelines for this chunk)
- Retries up to 3 times with exponential backoff (1s, 2s, 4s) on failure
- Tracks prompt hash for audit

### Extraction Orchestrator

**Service:** `book_ingestion_v2/services/topic_extraction_orchestrator.py` (`TopicExtractionOrchestrator`)

Runs the full extraction + auto-finalization pipeline for a chapter:

1. Acquires job lock, builds LLM service from DB config
2. Transitions chapter to `topic_extraction` status
3. Builds chunk windows from OCR'd pages
4. For each chunk:
   - Downloads page texts from S3
   - Builds `ChunkInput` with accumulated state (summary, topic map)
   - Calls `ChunkProcessorService.process_chunk()`
   - Updates running state: chapter summary, topic accumulator map
   - Saves chunk input/output/state to S3 at `books/{book_id}/chapters/{ch_num}/processing/runs/{job_id}/chunks/{idx}/`
   - Creates `ChapterChunk` DB record
5. Persists all accumulated topics as draft `ChapterTopic` records
6. Auto-triggers finalization if no chunks failed
7. On failure: marks chapter as `failed` with `retryable` error type

**Resume support:** When `resume=True`, finds the last completed chunk from the previous job, restores topic map and chapter summary from DB/chunk records, and resumes from the next chunk index.

### Chapter Finalization

**Service:** `book_ingestion_v2/services/chapter_finalization_service.py` (`ChapterFinalizationService`)

Runs after all chunks are extracted:

1. Loads draft topics from DB
2. **LLM-merges** each topic's per-chunk appended guidelines into unified text using `topic_guidelines_merge.txt` prompt
3. **Consolidation LLM call** using `chapter_consolidation.txt` prompt -- analyzes all topics and produces:
   - `merge_actions`: topics that should be combined (dedup)
   - `topic_updates`: new keys, titles, summaries, sequence orders for each topic
   - `chapter_display_name` and `final_chapter_summary`
4. Executes merge actions (appends guidelines, expands page ranges, deletes merged-from topics)
5. Applies topic updates (new key, title, summary, sequence_order, status -> `final`)
6. Updates chapter with display_name and summary
7. Saves final output to S3 at `books/{book_id}/chapters/{ch_num}/output/`

**Refinalization:** The `/refinalize` endpoint re-runs only the finalization step on existing topics without re-extracting from pages. Requires chapter status `chapter_completed` or `failed`.

---

## Job Lock & Progress Tracking

**Service:** `book_ingestion_v2/services/chapter_job_service.py` (`ChapterJobService`)

State machine: `pending -> running -> completed | completed_with_errors | failed`

- Only one active job (pending/running) per chapter, enforced by partial unique index
- Stale detection: running jobs with no heartbeat for 10 minutes are auto-marked failed; pending jobs stuck for 5 minutes are marked abandoned
- Progress updates include `current_item` description, `completed_items`/`failed_items` counts, and heartbeat timestamp
- Jobs track LLM model provider and model ID for audit

**Background task runner:** `run_in_background_v2()` in `processing_routes.py` -- spawns a daemon thread with its own DB session, calls `start_job()`, runs the target function, and releases the lock on completion or failure.

**API routes:** `book_ingestion_v2/api/processing_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `.../chapters/{chapter_id}/process` | Start topic extraction + finalization |
| POST | `.../chapters/{chapter_id}/reprocess` | Wipe topics, reprocess from scratch |
| POST | `.../chapters/{chapter_id}/refinalize` | Re-run finalization only |
| GET | `.../chapters/{chapter_id}/jobs/latest` | Get latest job status |
| GET | `.../chapters/{chapter_id}/jobs/{job_id}` | Get specific job |
| GET | `.../chapters/{chapter_id}/topics` | Get extracted topics |
| GET | `.../chapters/{chapter_id}/topics/{topic_key}` | Get single topic |

---

## Sync to Teaching Guidelines

**Service:** `book_ingestion_v2/services/topic_sync_service.py` (`TopicSyncService`)

Maps V2 data model to the shared `teaching_guidelines` table:
- V2 chapter -> `teaching_guidelines.chapter_key` (format: `chapter-{number}`)
- V2 topic -> one `teaching_guidelines` row per topic

For each topic, creates a `TeachingGuideline` record with:
- Curriculum fields: country, board, grade, subject (from book)
- Chapter fields: chapter_title (display_name or chapter_title), chapter_key, chapter_summary, chapter_sequence
- Topic fields: topic_key, topic_title, topic_summary, topic_sequence, guidelines (full text), source pages
- Status: `approved` / review_status: `APPROVED`
- book_id reference for traceability

Sync is idempotent: deletes existing guidelines for the chapter before creating new ones.

**API routes:** `book_ingestion_v2/api/sync_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/v2/books/{book_id}/sync` | Sync all completed chapters |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/sync` | Sync single chapter |
| GET | `/admin/v2/books/{book_id}/results` | Book-level results overview |

---

## Study Plan Generation

**Module:** `study_plans/`

Study plans are generated from teaching guidelines and used by the tutor during sessions.

### Generator

**Service:** `study_plans/services/generator_service.py` (`StudyPlanGeneratorService`)

- Loads `study_plan_generator` prompt template via `shared/prompts/loader.py` (`PromptLoader`)
- Calls LLM with `reasoning_effort="high"` and strict JSON schema (`StudyPlan` Pydantic model via `LLMService.make_schema_strict()`)
- Output structure (`StudyPlan` model in `generator_service.py`):
  - `todo_list`: 3-5 `StudyPlanStep` items, each with step_id, title, description, teaching_approach, success_criteria, building_blocks, analogy, status
  - `metadata`: `StudyPlanMetadata` with plan_version, estimated_duration_minutes, difficulty_level, is_generic, creative_theme
- Validates output against both Pydantic model and legacy schema checks (`_validate_plan_schema()`)
- Supports optional student personalization via `StudentContext` (imported from `tutor.models.messages`) with fields: student_name, student_age, preferred_examples, attention_span, tutor_brief
- `generate_plan_with_feedback()`: generates adjusted plan mid-session based on parent/student feedback. Appends feedback context (feedback text, concepts already covered, progress) to the prompt. Skips the reviewer pass for speed.

### Reviewer

**Service:** `study_plans/services/reviewer_service.py` (`StudyPlanReviewerService`)

- Reviews generated plans using `study_plan_reviewer` prompt
- Returns approved/rejected with feedback and suggested improvements

### Orchestrator

**Service:** `study_plans/services/orchestrator.py` (`StudyPlanOrchestrator`)

- Takes separate `generator_llm` and `reviewer_llm` `LLMService` instances (can be different models)
- Generate -> Review -> (optional) Improve loop:
  1. `generator.generate_plan(guideline)` produces initial plan
  2. `reviewer.review_plan(plan, guideline)` returns approved/rejected with feedback and suggested_improvements
  3. If rejected, `_improve_plan()` calls the reviewer LLM with `study_plan_improve` prompt for a single revision pass
  4. If improvement fails, saves the original plan anyway
- Persists to `study_plans` table with generator_model, reviewer_model, generation_reasoning, reviewer_feedback, was_revised flag, version tracking
- `get_study_plan()` returns cached plan if exists; `generate_study_plan(force_regenerate=True)` regenerates

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `books` | Shared book table (V2 uses `pipeline_version=2`) |
| `book_chapters` | TOC entries and chapter state |
| `chapter_pages` | Individual pages with OCR tracking |
| `chapter_processing_jobs` | Background job tracking with heartbeat |
| `chapter_chunks` | Per-chunk processing audit trail |
| `chapter_topics` | Extracted topics (draft -> consolidated -> final) |
| `teaching_guidelines` | Synced guidelines used by the tutor |
| `study_plans` | Generated study plans (per-guideline, optionally per-user) |

See `book_ingestion_v2/models/database.py` for V2 ORM models. Study plan ORM model is in `shared/models/entities.py` (`StudyPlan`).

---

## S3 Storage Layout

```
books/{book_id}/
  metadata.json
  toc_pages/
    page_1.png, page_2.png, ...
    extraction_result.json
  chapters/{ch_num}/
    pages/
      raw/{page_number}.{ext}      # Original upload
      {page_number}.png             # Converted PNG
      {page_number}.txt             # OCR text
    processing/
      runs/{job_id}/
        config.json
        chunks/{idx}/
          input.json
          output.json
          state_after.json
        pre_consolidation.json
        consolidation_output.json
    output/
      chapter_result.json
      topics/{topic_key}.json
```

---

## LLM Prompts

| Prompt File | Used By | Purpose |
|-------------|---------|---------|
| `prompts/toc_extraction.txt` | `TOCExtractionService` | Extract structured TOC from OCR text |
| `prompts/chunk_topic_extraction.txt` | `ChunkProcessorService` | Extract/update topics from a 3-page chunk |
| `prompts/topic_guidelines_merge.txt` | `ChapterFinalizationService` | Merge per-chunk appended guidelines into unified text |
| `prompts/chapter_consolidation.txt` | `ChapterFinalizationService` | Dedup, rename, sequence, summarize topics |
| `shared/prompts/templates/study_plan_generator.txt` | `StudyPlanGeneratorService` | Generate 3-5 step study plan from guideline |
| `shared/prompts/templates/study_plan_reviewer.txt` | `StudyPlanReviewerService` | Review plan quality, approve/reject with feedback |
| `shared/prompts/templates/study_plan_improve.txt` | `StudyPlanOrchestrator._improve_plan()` | Revise rejected plan using reviewer feedback |

---

## Configuration

- **LLM config key:** `book_ingestion_v2` -- stored in the `llm_configs` table, specifies provider and model_id
- **Chunk size:** 3 pages (`CHUNK_SIZE` in `constants.py`)
- **Chunk retries:** 3 attempts with exponential backoff (`CHUNK_MAX_RETRIES`)
- **Heartbeat stale threshold:** 600 seconds / 10 minutes (`HEARTBEAT_STALE_THRESHOLD`)
- **Pending stale threshold:** 300 seconds / 5 minutes (`PENDING_STALE_THRESHOLD`)
- **Max TOC images:** 5
- **Max TOC image size:** 10 MB
- **Max page image size:** 20 MB
- **Supported page formats:** PNG, JPG, JPEG, TIFF, WEBP

---

## Frontend

| Component | File | Purpose |
|-----------|------|---------|
| BookV2Dashboard | `llm-frontend/src/features/admin/pages/BookV2Dashboard.tsx` | Lists all V2 books with card grid |
| CreateBookV2 | `llm-frontend/src/features/admin/pages/CreateBookV2.tsx` | Two-step wizard: metadata form, then TOC editor (upload or manual) |
| BookV2Detail | `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | Book detail with expandable chapters, page grid, upload, processing, topics, sync |
| Admin API V2 | `llm-frontend/src/features/admin/api/adminApiV2.ts` | TypeScript API client for all V2 endpoints |

**Routes:** `/admin/books-v2`, `/admin/books-v2/new`, `/admin/books-v2/{id}`

**Polling:** BookV2Detail polls `GET .../jobs/latest` every 3 seconds for chapters in `topic_extraction` or `chapter_finalizing` status. Polling stops when job reaches a terminal state.

---

## Key Files

| File | Purpose |
|------|---------|
| `book_ingestion_v2/constants.py` | Enums (ChapterStatus, V2JobType, V2JobStatus, OCRStatus, TopicStatus), config constants |
| `book_ingestion_v2/models/database.py` | ORM models: BookChapter, ChapterPage, ChapterProcessingJob, ChapterChunk, ChapterTopic |
| `book_ingestion_v2/models/schemas.py` | Pydantic request/response schemas for all V2 APIs |
| `book_ingestion_v2/models/processing_models.py` | Internal pipeline models: ChunkWindow, TopicAccumulator, RunningState, ChunkInput, ChunkExtractionOutput, ConsolidationOutput |
| `book_ingestion_v2/services/book_v2_service.py` | Book CRUD with cascade delete |
| `book_ingestion_v2/services/toc_extraction_service.py` | OCR + LLM TOC extraction |
| `book_ingestion_v2/services/toc_service.py` | TOC CRUD with validation |
| `book_ingestion_v2/services/chapter_page_service.py` | Page upload with inline OCR |
| `book_ingestion_v2/services/chunk_processor_service.py` | Single-chunk LLM processing |
| `book_ingestion_v2/services/topic_extraction_orchestrator.py` | Full extraction + finalization pipeline |
| `book_ingestion_v2/services/chapter_finalization_service.py` | Topic merge, consolidation, sequencing |
| `book_ingestion_v2/services/topic_sync_service.py` | Sync to teaching_guidelines table |
| `book_ingestion_v2/services/chapter_job_service.py` | Job lock, progress tracking, stale detection |
| `book_ingestion_v2/utils/chunk_builder.py` | Build 3-page processing windows |
| `book_ingestion_v2/repositories/` | Data access: chapter_repository, chapter_page_repository, chunk_repository, topic_repository, processing_job_repository |
| `shared/repositories/book_repository.py` | Shared book data access |
| `study_plans/services/orchestrator.py` | Study plan generate -> review -> improve loop |
| `study_plans/services/generator_service.py` | LLM-based study plan generation with strict schema; also defines `StudyPlan`, `StudyPlanStep`, `StudyPlanMetadata` Pydantic models |
| `study_plans/services/reviewer_service.py` | LLM-based study plan quality review |
| `shared/models/entities.py` (StudyPlan class) | ORM model for `study_plans` table (guideline_id, user_id, plan_json, version) |
| `shared/prompts/templates/study_plan_*.txt` | Prompts for study plan generation, review, and improvement |
