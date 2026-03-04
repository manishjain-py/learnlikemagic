# Books and Teaching Guidelines -- Technical

Architecture, services, data flow, and APIs for the book ingestion V2 pipeline and teaching guidelines system.

---

## Architecture

```
Admin UI (React)
    │
    v
FastAPI Routes (/admin/v2/books/...)
    │
    ├── BookV2Service        ── Book CRUD
    ├── TOCService           ── TOC validation & chapter creation
    ├── TOCExtractionService ── OCR + LLM TOC extraction
    ├── ChapterPageService   ── Page upload + inline OCR
    │
    ├── TopicExtractionOrchestrator ── Background extraction pipeline
    │       ├── ChunkProcessorService   ── Per-chunk LLM calls
    │       └── ChapterFinalizationService ── Consolidation + merge
    │
    ├── ChapterJobService    ── Job lock + progress tracking
    └── TopicSyncService     ── Sync to teaching_guidelines table
         │
         v
    TeachingGuideline rows → StudyPlanOrchestrator → Tutor
```

The pipeline is chapter-scoped. Each chapter goes through: TOC definition, page upload with inline OCR, chunk-based topic extraction, AI-powered finalization, and sync to the teaching_guidelines table.

---

## Key Components

### Backend Services (book_ingestion_v2/services/)

| Service | File | Responsibility |
|---------|------|---------------|
| `BookV2Service` | `book_v2_service.py` | Book CRUD, S3 metadata init, cascade delete |
| `TOCService` | `toc_service.py` | TOC validation (ranges, overlaps, sequencing), chapter CRUD, lock enforcement |
| `TOCExtractionService` | `toc_extraction_service.py` | OCR page images, LLM-extract structured TOC, store to S3 |
| `ChapterPageService` | `chapter_page_service.py` | Page upload, PNG conversion, inline OCR, completeness tracking |
| `TopicExtractionOrchestrator` | `topic_extraction_orchestrator.py` | Full extraction pipeline: chunk windows, chunk processing, draft topic persistence, auto-finalization |
| `ChunkProcessorService` | `chunk_processor_service.py` | Single-chunk LLM call with retry (up to 3 attempts, exponential backoff) |
| `ChapterFinalizationService` | `chapter_finalization_service.py` | LLM-merge per-chunk guidelines, consolidation LLM (dedup, naming, sequencing), merge execution |
| `ChapterJobService` | `chapter_job_service.py` | Job lock acquire/release, progress + heartbeat updates, stale detection |
| `TopicSyncService` | `topic_sync_service.py` | Map chapter_topics to teaching_guidelines rows |

### Repositories (book_ingestion_v2/repositories/)

| Repository | File | Table |
|------------|------|-------|
| `ChapterRepository` | `chapter_repository.py` | `book_chapters` |
| `ChapterPageRepository` | `chapter_page_repository.py` | `chapter_pages` |
| `TopicRepository` | `topic_repository.py` | `chapter_topics` |
| `ChunkRepository` | `chunk_repository.py` | `chapter_chunks` |
| `ProcessingJobRepository` | `processing_job_repository.py` | `chapter_processing_jobs` |

### Study Plan Services (study_plans/services/)

| Service | File | Responsibility |
|---------|------|---------------|
| `StudyPlanOrchestrator` | `orchestrator.py` | Generate-review-improve loop, DB persistence |
| `StudyPlanGeneratorService` | `generator_service.py` | LLM call with strict schema output for study plan generation |
| `StudyPlanReviewerService` | `reviewer_service.py` | LLM review of generated plans for quality assurance |

### Shared Components

| Component | File | Responsibility |
|-----------|------|---------------|
| `TeachingGuidelineRepository` | `shared/repositories/guideline_repository.py` | Read-side access: get guidelines by curriculum path, list chapters/topics with sequencing |
| `TeachingGuideline` model | `shared/models/entities.py` | ORM model for teaching_guidelines table |
| `StudyPlan` model | `shared/models/entities.py` | ORM model for study_plans table |
| `BookRepository` | `shared/repositories/book_repository.py` | Shared book CRUD (used by both V2 pipeline and other services) |

### Frontend Pages (llm-frontend/src/features/admin/)

| Page | File | Purpose |
|------|------|---------|
| `BookV2Dashboard` | `pages/BookV2Dashboard.tsx` | List all V2 books with chapter counts |
| `BookV2Detail` | `pages/BookV2Detail.tsx` | Book detail: chapter cards, page grid, upload, processing, topics, sync |
| `CreateBookV2` | `pages/CreateBookV2.tsx` | Two-step wizard: metadata form then TOC (upload or manual) |
| API client | `api/adminApiV2.ts` | All V2 API calls with TypeScript types |

---

## Data Flow

### 1. Book Creation

```
CreateBookV2 form → POST /admin/v2/books
    → BookV2Service.create_book()
        → Generate book_id from metadata (author_subject_grade_year)
        → Insert Book row (pipeline_version=2)
        → Initialize S3 metadata at books/{book_id}/metadata.json
```

### 2. TOC Definition

Two paths:

**AI extraction:**
```
Upload TOC images → POST /admin/v2/books/{id}/toc/extract
    → TOCExtractionService.extract()
        → Convert images to PNG
        → OCR each image (OCRService)
        → Store PNGs to S3 (books/{id}/toc_pages/)
        → LLM call with combined OCR text → structured chapter list
        → Store extraction result to S3
    → Return TOCExtractionResponse (no DB write)
```

**Save TOC (both paths):**
```
POST /admin/v2/books/{id}/toc
    → TOCService.save_toc()
        → Validate: book exists, is V2, no existing chapters have uploaded pages
        → Validate entries: sequential numbers, valid ranges, no overlaps
        → Delete old chapters, create new BookChapter rows
        → Each chapter: status=toc_defined, total_pages computed
```

### 3. Page Upload + OCR

```
Upload page image → POST /admin/v2/books/{id}/chapters/{ch_id}/pages
    → ChapterPageService.upload_page()
        → Validate: chapter exists, page_number in range, no duplicate
        → Convert to PNG
        → Upload raw + PNG to S3 (books/{id}/chapters/{nn}/pages/)
        → Inline OCR via OCRService (using V2-specific prompt)
        → Upload OCR text to S3
        → Create ChapterPage row
        → _update_chapter_completeness():
            if all pages uploaded + OCR complete → status=upload_complete
            else → status=upload_in_progress
```

### 4. Topic Extraction Pipeline

```
POST /admin/v2/books/{id}/chapters/{ch_id}/process
    → Acquire job lock (ChapterJobService)
    → Launch background thread via run_in_background_v2()
    → TopicExtractionOrchestrator.extract():
        1. Build LLM service from DB config (LLM_CONFIG_KEY="book_ingestion_v2")
        2. Set chapter status → topic_extraction
        3. Build chunk windows (3-page non-overlapping)
        4. If resume: restore state from previous job's last completed chunk
        5. For each chunk:
            a. Load page texts from S3
            b. Load previous page context
            c. Build ChunkInput (book/chapter metadata, pages, running state)
            d. Save input to S3
            e. ChunkProcessorService.process_chunk():
                - Build prompt from template (chunk_topic_extraction.txt)
                - LLM call (json_mode=true, reasoning_effort=none)
                - Parse ChunkExtractionOutput
                - Retry up to 3x with exponential backoff
            f. Update RunningState accumulator (topic map + summary)
            g. Save output + state snapshot to S3
            h. Create ChapterChunk DB record
        6. Persist draft topics to chapter_topics table
        7. If any chunks failed → status=failed, job=completed_with_errors
        8. Otherwise → auto-trigger finalization
```

### 5. Chapter Finalization

```
ChapterFinalizationService.finalize():
    1. Load draft topics from DB
    2. Save pre-consolidation snapshot to S3
    3. For each topic with multi-chunk guidelines ("## Pages" markers):
        → LLM-merge appended guidelines into unified text
          (topic_guidelines_merge.txt prompt)
        → Update topic status → consolidated
    4. Consolidation LLM call (chapter_consolidation.txt prompt):
        → Input: topic previews (key, title, guidelines preview, page range)
        → Output: ConsolidationOutput
            - chapter_display_name, final_chapter_summary
            - merge_actions (merge_from → merge_into)
            - topic_updates (new keys, titles, summaries, sequence order)
    5. Execute merge actions:
        → Append merged topic guidelines, expand page range, delete source topic
    6. Apply topic updates:
        → Rename keys/titles, add summaries, set sequence_order
        → Status → final
    7. Update chapter: display_name, summary
    8. Save final output to S3 (chapter_result.json + per-topic JSONs)
```

### 6. Sync to Teaching Guidelines

```
POST /admin/v2/books/{id}/sync (or /chapters/{ch_id}/sync)
    → TopicSyncService.sync_book() or sync_chapter()
        → For each completed chapter:
            1. Delete existing teaching_guidelines for this chapter_key
            2. For each final topic:
                → Create TeachingGuideline row:
                    - chapter = display_name or chapter_title
                    - topic = topic_title
                    - guideline = full guidelines text
                    - chapter_key = "chapter-{N}"
                    - chapter_sequence, topic_sequence from V2 data
                    - review_status = "APPROVED" (auto-approved)
                    - book_id, source_page_start, source_page_end
```

### 7. Study Plan Generation (Downstream)

```
StudyPlanOrchestrator.generate_study_plan(guideline_id):
    1. Load TeachingGuideline from DB
    2. StudyPlanGeneratorService.generate_plan():
        → LLM call with strict StudyPlan schema (high reasoning effort)
        → Returns 3-5 teaching steps with titles, descriptions, approaches
    3. StudyPlanReviewerService.review_plan():
        → LLM review with quality criteria
    4. If not approved → _improve_plan() single revision pass
    5. Save StudyPlan row (plan_json, generator_model, reviewer_feedback, version)
```

---

## API Endpoints

### Book Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/v2/books` | Create V2 book |
| `GET` | `/admin/v2/books` | List V2 books (filters: country, board, grade, subject) |
| `GET` | `/admin/v2/books/{id}` | Get book with chapters |
| `DELETE` | `/admin/v2/books/{id}` | Delete book + all data (DB + S3) |

### TOC Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/v2/books/{id}/toc/extract` | OCR + LLM extract TOC from images (multipart) |
| `POST` | `/admin/v2/books/{id}/toc` | Save/replace full TOC |
| `GET` | `/admin/v2/books/{id}/toc` | Get TOC entries |
| `PUT` | `/admin/v2/books/{id}/toc/{ch_id}` | Update single chapter (blocked if pages uploaded) |
| `DELETE` | `/admin/v2/books/{id}/toc/{ch_id}` | Delete single chapter (blocked if pages uploaded) |

### Page Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/v2/books/{id}/chapters/{ch_id}/pages` | Upload page (multipart: image + page_number) |
| `GET` | `/admin/v2/books/{id}/chapters/{ch_id}/pages` | List pages with completeness |
| `GET` | `/admin/v2/books/{id}/chapters/{ch_id}/pages/{num}` | Get page metadata |
| `GET` | `/admin/v2/books/{id}/chapters/{ch_id}/pages/{num}/detail` | Get page with presigned image URL + OCR text |
| `DELETE` | `/admin/v2/books/{id}/chapters/{ch_id}/pages/{num}` | Delete page |
| `POST` | `/admin/v2/books/{id}/chapters/{ch_id}/pages/{num}/retry-ocr` | Retry failed OCR |

### Processing

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/v2/books/{id}/chapters/{ch_id}/process` | Start extraction + finalization (body: `{resume: bool}`) |
| `POST` | `/admin/v2/books/{id}/chapters/{ch_id}/reprocess` | Wipe topics, reprocess from scratch |
| `POST` | `/admin/v2/books/{id}/chapters/{ch_id}/refinalize` | Re-run finalization only |
| `GET` | `/admin/v2/books/{id}/chapters/{ch_id}/jobs/latest` | Get latest job status |
| `GET` | `/admin/v2/books/{id}/chapters/{ch_id}/jobs/{job_id}` | Get specific job status |
| `GET` | `/admin/v2/books/{id}/chapters/{ch_id}/topics` | Get extracted topics |
| `GET` | `/admin/v2/books/{id}/chapters/{ch_id}/topics/{key}` | Get single topic with guidelines |

### Sync and Results

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/v2/books/{id}/sync` | Sync all completed chapters |
| `POST` | `/admin/v2/books/{id}/chapters/{ch_id}/sync` | Sync single chapter |
| `GET` | `/admin/v2/books/{id}/results` | Book-level results overview |

---

## Database Tables

### V2 Pipeline Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `books` | Book metadata (shared with V1) | id, title, country, board, grade, subject, pipeline_version=2 |
| `book_chapters` | Chapter definitions from TOC | book_id, chapter_number, chapter_title, start_page, end_page, status, display_name, summary |
| `chapter_pages` | Uploaded page images + OCR | chapter_id, page_number, raw_image_s3_key, image_s3_key, text_s3_key, ocr_status |
| `chapter_processing_jobs` | Background job tracking | chapter_id, job_type, status, progress fields, heartbeat_at |
| `chapter_chunks` | Per-chunk processing audit | chapter_id, processing_job_id, chunk_index, page_start/end, raw_llm_response, topics_detected_json |
| `chapter_topics` | Extracted topics per chapter | chapter_id, topic_key, topic_title, guidelines, summary, sequence_order, status |
| `teaching_guidelines` | Final synced guidelines (tutor reads from here) | country, board, grade, subject, chapter, topic, guideline, chapter_key, topic_key, book_id |
| `study_plans` | Generated study plans per guideline | guideline_id, plan_json, generator_model, reviewer_model, version |

### Chapter Status State Machine

```
toc_defined → upload_in_progress → upload_complete
    → topic_extraction → chapter_finalizing → chapter_completed
                                           → failed (retryable)
```

### Topic Status Progression

```
draft → consolidated → final → approved
```

### Job Status State Machine

```
pending → running → completed | completed_with_errors | failed
```

Stale detection: running jobs with no heartbeat for 10 minutes are auto-marked failed. Pending jobs stuck for 5 minutes are marked abandoned.

---

## S3 Structure

```
books/{book_id}/
    metadata.json
    toc_pages/
        page_1.png, page_2.png, ...
        extraction_result.json
    chapters/{nn}/
        pages/
            raw/{page_number}.{ext}
            {page_number}.png
            {page_number}.txt
        processing/
            runs/{job_id}/
                config.json
                pre_consolidation.json
                consolidation_output.json
                chunks/{nnn}/
                    input.json
                    output.json
                    state_after.json
        output/
            chapter_result.json
            topics/{topic_key}.json
```

---

## Processing Configuration

| Constant | Value | Description |
|----------|-------|-------------|
| `CHUNK_SIZE` | 3 | Pages per chunk |
| `CHUNK_STRIDE` | 3 | Non-overlapping stride |
| `CHUNK_MAX_RETRIES` | 3 | LLM retries per chunk |
| `HEARTBEAT_STALE_THRESHOLD` | 600s (10 min) | Running job stale timeout |
| `PENDING_STALE_THRESHOLD` | 300s (5 min) | Pending job abandon timeout |
| `LLM_CONFIG_KEY` | `"book_ingestion_v2"` | DB config key for LLM provider/model |
| `MAX_IMAGES` (TOC) | 5 | Max TOC page images |
| `MAX_IMAGE_SIZE` (TOC) | 10 MB | Per-image size limit for TOC extraction |
| `MAX_FILE_SIZE` (pages) | 20 MB | Per-page upload size limit |

### LLM Prompt Templates

| Prompt | File | Used By |
|--------|------|---------|
| Chunk topic extraction | `book_ingestion_v2/prompts/chunk_topic_extraction.txt` | `ChunkProcessorService` |
| TOC extraction | `book_ingestion_v2/prompts/toc_extraction.txt` | `TOCExtractionService` |
| Topic guidelines merge | `book_ingestion_v2/prompts/topic_guidelines_merge.txt` | `ChapterFinalizationService` |
| Chapter consolidation | `book_ingestion_v2/prompts/chapter_consolidation.txt` | `ChapterFinalizationService` |

---

## Key Files

### Backend

```
llm-backend/book_ingestion_v2/
    constants.py                          # Enums, processing constants
    models/
        database.py                       # ORM: BookChapter, ChapterPage, ChapterProcessingJob, ChapterChunk, ChapterTopic
        schemas.py                        # Pydantic API schemas
        processing_models.py              # Internal pipeline models: ChunkWindow, RunningState, ChunkInput, ChunkExtractionOutput, ConsolidationOutput
    api/
        book_routes.py                    # /admin/v2/books CRUD
        toc_routes.py                     # TOC extract/save/update/delete
        page_routes.py                    # Page upload/list/detail/delete/retry-ocr
        processing_routes.py              # Process/reprocess/refinalize, job status, topics
        sync_routes.py                    # Sync + results
    services/
        book_v2_service.py                # Book CRUD + cascade delete
        toc_service.py                    # TOC validation + chapter management
        toc_extraction_service.py         # OCR + LLM TOC extraction
        chapter_page_service.py           # Page upload + inline OCR + completeness
        topic_extraction_orchestrator.py  # Full extraction pipeline
        chunk_processor_service.py        # Single chunk LLM processing
        chapter_finalization_service.py   # Consolidation + merge + naming
        chapter_job_service.py            # Job lock + progress + stale detection
        topic_sync_service.py             # chapter_topics → teaching_guidelines
    repositories/
        chapter_repository.py             # BookChapter CRUD
        chapter_page_repository.py        # ChapterPage CRUD
        topic_repository.py               # ChapterTopic CRUD
        chunk_repository.py               # ChapterChunk CRUD
        processing_job_repository.py      # ChapterProcessingJob CRUD
    prompts/
        chunk_topic_extraction.txt        # Per-chunk extraction prompt
        toc_extraction.txt                # TOC extraction prompt
        topic_guidelines_merge.txt        # Multi-chunk guidelines merge prompt
        chapter_consolidation.txt         # Chapter consolidation prompt
    utils/
        chunk_builder.py                  # build_chunk_windows() utility

llm-backend/study_plans/
    services/
        orchestrator.py                   # Generate-review-improve loop
        generator_service.py              # LLM study plan generation (strict schema)
        reviewer_service.py               # LLM study plan review

llm-backend/shared/
    models/entities.py                    # TeachingGuideline, StudyPlan ORM models
    repositories/
        book_repository.py                # Shared Book CRUD
        guideline_repository.py           # Read-side guideline access (chapters, topics, sequencing)
```

### Frontend

```
llm-frontend/src/features/admin/
    api/adminApiV2.ts                     # V2 API client + TypeScript types
    pages/
        BookV2Dashboard.tsx               # Book list dashboard
        BookV2Detail.tsx                   # Book detail with chapter management
        CreateBookV2.tsx                   # Book creation wizard
```
