# Technical Implementation Plan: Book Ingestion V2

**Status:** Draft
**Date:** 2026-03-02
**PRD:** `docs/feature-development/book-ingestion-v2/prd.md`

---

## 1. Executive Summary

Book Ingestion V2 replaces AI-inferred book structure with explicit admin-authored Table of Contents (TOC), constrains all AI processing to single chapters, and flattens the output hierarchy to **Book → Chapter → Topic** (no subtopic layer).

**Key architectural shifts from V1:**

| Dimension | V1 (Current) | V2 (New) |
|-----------|-------------|----------|
| Structure source | AI-inferred boundaries | Admin-authored TOC |
| Processing unit | Whole book, page-by-page | Single chapter, 3-page chunks |
| Output hierarchy | Book → Topic → Subtopic | Book → Chapter → Topic |
| AI task per page | Boundary detection + guideline extraction | Topic detection + guideline map update |
| Accumulator | Context pack (5 recent pages + open topics) | Running chapter summary + topic guidelines map |
| Finalization | Book-level dedup + sequencing | Chapter-level consolidation |

**What we reuse from V1:** S3Client, OCRService, JobLockService pattern, BackgroundTaskRunner, LLMConfigService, DB migration approach, frontend hooks/API patterns.

**What we redesign:** S3 structure (chapter-centric), DB schema (new tables), processing pipeline (chunk-based accumulator), frontend admin flow (TOC + chapter workflow).

---

## 2. Design Decisions (Open Questions Resolved)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | TOC editing after uploads begin? | **Locked once any page is uploaded for a chapter.** Admin can delete uploaded pages to unlock. | Simplifies page↔chapter invariants. Avoids remapping complexity. |
| 2 | Page number source of truth? | **Absolute page number from TOC range.** Admin defines `start_page`/`end_page`; each upload slot corresponds to an absolute page number. | Deterministic, matches the physical book. |
| 3 | Chunk stride? | **Non-overlapping stride of 3** (pages [1,2,3], [4,5,6], ...) with previous-page context (page n-1 text). Configurable via `CHUNK_SIZE` and `CHUNK_STRIDE` constants. Last chunk may be smaller. | Efficient (each page processed once). Previous-page context prevents boundary artifacts. |
| 4 | Chapter rename policy? | **Store both.** `chapter_title` = original TOC name (immutable). `display_name` = AI-generated from content (nullable, set during finalization). | Preserves admin intent while improving downstream display. |
| 5 | Human approval gate? | **No explicit gate for V2 MVP.** Chapter auto-transitions to `chapter_completed` after finalization. Admin can review/edit topics before DB sync. | Reduces friction. Review happens at DB sync stage (existing pattern). |
| 6 | Cross-page artifacts? | **Handled by 3-page window.** The window naturally captures most cross-page diagrams/tables. Previous-page context helps with boundary cases. | Good enough for MVP. Explicit handling is a future enhancement. |
| 7 | Multi-language? | **English only for V2.** No i18n in prompts or OCR. | Per PRD non-goals. |
| 8 | Backfill? | **Not needed.** V2 is for new books only. V1 books remain on V1 pipeline. | Per PRD non-goals. |

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Frontend: /admin/books-v2/*                                                │
│  BookV2Dashboard → CreateBookV2 → BookV2Detail                              │
│    └─ TOCEditor → ChapterUpload → ChapterProcessing → ChapterResults       │
│  useJobPolling (reused)                                                     │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ REST API (/admin/v2/books/*)
┌────────────────────────────────▼─────────────────────────────────────────────┐
│  Backend: book_ingestion_v2/                                                │
│                                                                             │
│  API Layer:                                                                 │
│    book_routes.py, chapter_routes.py, page_routes.py, processing_routes.py  │
│                                                                             │
│  Service Layer:                                                             │
│    BookV2Service, TOCService, ChapterPageService                            │
│    ChunkProcessorService, TopicExtractionOrchestrator                       │
│    ChapterFinalizationService, TopicSyncService                             │
│                                                                             │
│  Shared (reused):                                                           │
│    OCRService, S3Client, JobLockService, BackgroundTaskRunner               │
│    LLMConfigService, LLMService                                             │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────────────┐
│  PostgreSQL: books (+ pipeline_version), book_chapters, chapter_pages,      │
│              chapter_processing_jobs, chapter_chunks, chapter_topics         │
│  S3: books/{book_id}/chapters/{ch_num}/ (pages, processing, output)         │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Database Schema

### 4.1 Existing Table Modification

**`books` table** — Add one column:

```sql
ALTER TABLE books ADD COLUMN IF NOT EXISTS pipeline_version INTEGER DEFAULT 1;
```

- V1 books: `pipeline_version = 1` (default, no V1 behavior change)
- V2 books: `pipeline_version = 2` (set at creation)

### 4.2 New Tables

#### `book_chapters` — TOC entries and chapter-level state

```sql
CREATE TABLE book_chapters (
    id              VARCHAR PRIMARY KEY,            -- UUID
    book_id         VARCHAR NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_number  INTEGER NOT NULL,               -- Sequence index (1-based)
    chapter_title   VARCHAR NOT NULL,               -- Admin-entered TOC title
    start_page      INTEGER NOT NULL,               -- Inclusive start (absolute page #)
    end_page        INTEGER NOT NULL,               -- Inclusive end (absolute page #)

    -- AI-generated (set during finalization)
    display_name    VARCHAR,                        -- Content-derived chapter name
    summary         TEXT,                           -- Final chapter summary

    -- Status tracking (see ChapterStatus enum in Appendix B)
    status          VARCHAR NOT NULL DEFAULT 'toc_defined',
    -- Values: toc_defined | upload_in_progress | upload_complete |
    --         topic_extraction | chapter_finalizing |
    --         chapter_completed | failed

    -- Denormalized count for fast UI display
    total_pages         INTEGER NOT NULL,           -- end_page - start_page + 1
    uploaded_page_count INTEGER NOT NULL DEFAULT 0,

    -- Error state
    error_message   TEXT,
    error_type      VARCHAR,                        -- retryable | terminal | validation

    -- Audit
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    created_by      VARCHAR DEFAULT 'admin',

    CONSTRAINT uq_book_chapter UNIQUE (book_id, chapter_number),
    CONSTRAINT chk_page_range CHECK (end_page >= start_page AND start_page > 0)
);

CREATE INDEX idx_book_chapters_book ON book_chapters(book_id);
CREATE INDEX idx_book_chapters_status ON book_chapters(book_id, status);
```

#### `chapter_pages` — Individual pages within chapters

```sql
CREATE TABLE chapter_pages (
    id                  VARCHAR PRIMARY KEY,        -- UUID
    book_id             VARCHAR NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id          VARCHAR NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
    page_number         INTEGER NOT NULL,           -- Absolute page number

    -- S3 references
    raw_image_s3_key    VARCHAR,                    -- Original upload (jpg/tiff/webp before conversion)
    image_s3_key        VARCHAR,                    -- Converted PNG used for OCR and display
    text_s3_key         VARCHAR,                    -- OCR extracted text file

    -- OCR tracking
    ocr_status          VARCHAR DEFAULT 'pending',  -- pending | processing | completed | failed
    ocr_error           TEXT,
    ocr_model           VARCHAR,                    -- Model used for OCR (audit)

    -- Timestamps
    uploaded_at         TIMESTAMP,
    ocr_completed_at    TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    -- Defense-in-depth: TOC validation already prevents range overlaps, but this
    -- constraint catches any bugs that would assign the same page to two chapters.
    CONSTRAINT uq_book_page UNIQUE (book_id, page_number),
    CONSTRAINT uq_chapter_page UNIQUE (chapter_id, page_number)
);

CREATE INDEX idx_chapter_pages_chapter ON chapter_pages(chapter_id);
CREATE INDEX idx_chapter_pages_ocr ON chapter_pages(chapter_id, ocr_status);
```

#### `chapter_processing_jobs` — Background job tracking per chapter

```sql
CREATE TABLE chapter_processing_jobs (
    id                  VARCHAR PRIMARY KEY,        -- UUID
    book_id             VARCHAR NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id          VARCHAR NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,

    -- Job definition (see V2JobType and V2JobStatus enums in Appendix B)
    job_type            VARCHAR NOT NULL,            -- v2_topic_extraction | v2_refinalization
    status              VARCHAR DEFAULT 'pending',   -- pending | running | completed | completed_with_errors | failed

    -- Progress
    total_items         INTEGER,
    completed_items     INTEGER DEFAULT 0,
    failed_items        INTEGER DEFAULT 0,
    current_item        VARCHAR,                     -- Human-readable current work description
    last_completed_item VARCHAR,                     -- For resume support
    progress_detail     TEXT,                        -- JSON: per-item errors, stats

    -- Heartbeat (stale detection)
    heartbeat_at        TIMESTAMP,

    -- LLM audit
    model_provider      VARCHAR,
    model_id            VARCHAR,

    -- Timestamps
    started_at          TIMESTAMP DEFAULT NOW(),
    completed_at        TIMESTAMP,
    error_message       TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- At most one active job per chapter
CREATE UNIQUE INDEX idx_chapter_active_job
    ON chapter_processing_jobs(chapter_id)
    WHERE status IN ('pending', 'running');

CREATE INDEX idx_chapter_jobs_book ON chapter_processing_jobs(book_id);
CREATE INDEX idx_chapter_jobs_chapter ON chapter_processing_jobs(chapter_id);
```

#### `chapter_chunks` — Per-chunk processing audit trail

```sql
CREATE TABLE chapter_chunks (
    id                      VARCHAR PRIMARY KEY,    -- UUID
    chapter_id              VARCHAR NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
    processing_job_id       VARCHAR NOT NULL REFERENCES chapter_processing_jobs(id) ON DELETE CASCADE,

    -- Chunk definition
    chunk_index             INTEGER NOT NULL,        -- 0-based within chapter
    page_start              INTEGER NOT NULL,        -- First page in chunk (absolute)
    page_end                INTEGER NOT NULL,        -- Last page in chunk (absolute)

    -- Input context (captured for reproducibility)
    previous_page_text      TEXT,                    -- Page n-1 text (NULL for first chunk)
    chapter_summary_before  TEXT,                    -- chapter_summary_so_far before processing
    topic_map_before_s3_key VARCHAR,                 -- S3 key to topic_map_so_far snapshot

    -- LLM output
    raw_llm_response        TEXT,                    -- Full LLM response (audit)
    topics_detected_json    TEXT,                    -- JSON: [{topic_key, title, is_new, reasoning}]
    chapter_summary_after   TEXT,                    -- Updated summary after this chunk
    topic_map_after_s3_key  VARCHAR,                 -- S3 key to updated topic_map snapshot

    -- Status
    status                  VARCHAR DEFAULT 'pending', -- pending | completed | failed
    error_message           TEXT,

    -- LLM metrics (audit)
    model_provider          VARCHAR,
    model_id                VARCHAR,
    prompt_hash             VARCHAR,                 -- Hash of prompt template version
    latency_ms              INTEGER,
    input_tokens            INTEGER,
    output_tokens           INTEGER,

    -- Timestamps
    created_at              TIMESTAMP DEFAULT NOW(),
    completed_at            TIMESTAMP,

    CONSTRAINT uq_chunk_per_job UNIQUE (processing_job_id, chunk_index)
);

CREATE INDEX idx_chunks_chapter ON chapter_chunks(chapter_id);
CREATE INDEX idx_chunks_job ON chapter_chunks(processing_job_id);
```

#### `chapter_topics` — Extracted topics (final output per chapter)

```sql
CREATE TABLE chapter_topics (
    id                  VARCHAR PRIMARY KEY,        -- UUID
    book_id             VARCHAR NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id          VARCHAR NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,

    -- Topic identification
    topic_key           VARCHAR NOT NULL,            -- kebab-case slug
    topic_title         VARCHAR NOT NULL,            -- Human-readable title

    -- Content
    guidelines          TEXT NOT NULL,               -- Complete teaching guidelines
    summary             TEXT,                        -- Topic summary (20-40 words)

    -- Source tracking
    source_page_start   INTEGER,
    source_page_end     INTEGER,

    -- Sequencing
    sequence_order      INTEGER,                     -- Teaching order within chapter (1-based)

    -- Status
    status              VARCHAR DEFAULT 'draft',     -- draft | consolidated | final | approved

    -- Version
    version             INTEGER DEFAULT 1,

    -- Audit
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_chapter_topic UNIQUE (chapter_id, topic_key)
);

CREATE INDEX idx_chapter_topics_book ON chapter_topics(book_id);
CREATE INDEX idx_chapter_topics_chapter ON chapter_topics(chapter_id);
```

### 4.3 Entity Relationships

```
books (pipeline_version=2)
  └── 1:N ── book_chapters
                ├── 1:N ── chapter_pages
                ├── 1:N ── chapter_processing_jobs
                │            └── 1:N ── chapter_chunks
                └── 1:N ── chapter_topics

Downstream sync:
  chapter_topics ──sync──> teaching_guidelines (chapter→topic, topic→subtopic)
                              └── 1:1 ── study_plans
```

### 4.4 Mapping V2 Output → `teaching_guidelines` (Existing Tutor Table)

When syncing V2 output to the existing tutor pipeline:

| V2 Entity | teaching_guidelines Column | Mapping |
|-----------|--------------------------|---------|
| `book_chapters.chapter_title` | `topic` (legacy) | Direct |
| `book_chapters.chapter_number` | `topic_key` | `chapter-{num}` or slugified title |
| `book_chapters.display_name` or `chapter_title` | `topic_title` | Prefer display_name |
| `book_chapters.summary` | `topic_summary` | Direct |
| `book_chapters.chapter_number` | `topic_sequence` | Direct |
| `chapter_topics.topic_key` | `subtopic_key` | Direct |
| `chapter_topics.topic_title` | `subtopic` (legacy), `subtopic_title` | Direct |
| `chapter_topics.guidelines` | `guideline` | Direct |
| `chapter_topics.summary` | `subtopic_summary` | Direct |
| `chapter_topics.sequence_order` | `subtopic_sequence` | Direct |
| `chapter_topics.source_page_start/end` | `source_page_start/end` | Direct |

This mapping means the student navigation stays: **Subject → Chapter (as "Topic") → Topic (as "Subtopic") → Mode**. No tutor runtime changes needed.

---

## 5. S3 Storage Structure

```
books/{book_id}/
├── metadata.json                                   # Book metadata (title, author, grade, etc.)
│
├── chapters/
│   └── {chapter_number}/                            # Zero-padded: 01, 02, ...
│       │
│       ├── pages/
│       │   ├── raw/
│       │   │   └── {page_number}.{ext}              # Original uploaded image
│       │   ├── {page_number}.png                    # Converted PNG
│       │   └── {page_number}.txt                    # OCR extracted text
│       │
│       ├── processing/
│       │   └── runs/
│       │       └── {job_id}/                        # One dir per processing run
│       │           ├── config.json                  # Run config: model, prompts, params
│       │           ├── chunks/
│       │           │   └── {chunk_index}/           # Zero-padded: 000, 001, ...
│       │           │       ├── input.json           # Pages text, context, summary_so_far
│       │           │       ├── output.json          # Raw LLM response
│       │           │       └── state_after.json     # Accumulated state after this chunk
│       │           ├── pre_consolidation.json       # Topic map before consolidation
│       │           ├── consolidation_output.json    # Consolidation LLM response
│       │           └── final_result.json            # Final chapter output
│       │
│       └── output/
│           ├── chapter_result.json                  # Final: display_name, summary, topic_count
│           └── topics/
│               └── {topic_key}.json                 # Individual topic guideline
```

**Key design properties:**
- **Run isolation:** Each processing run (`runs/{job_id}/`) is self-contained. Comparing runs, debugging, or replaying is trivial.
- **Run retention:** Old processing runs are **retained indefinitely** for audit. Reprocessing a chapter creates a new run directory; previous runs remain in S3 and their `chapter_processing_jobs`/`chapter_chunks` DB records are preserved. The `output/` directory is overwritten to always reflect the latest finalized result.
- **Chunk-level traceability:** Every chunk's input, output, and resulting state are captured.
- **Output stability:** `output/` always contains the latest finalized result, independent of processing history.
- **No metadata.json for page inventory:** V2 tracks pages in the DB (`chapter_pages` table), not in S3 metadata. S3 is just storage.

---

## 6. Backend Module Structure

```
llm-backend/book_ingestion_v2/
├── __init__.py
├── api/
│   ├── __init__.py
│   ├── book_routes.py              # Book CRUD (V2)
│   ├── toc_routes.py               # TOC authoring endpoints
│   ├── chapter_routes.py           # Chapter-level operations
│   ├── page_routes.py              # Page upload within chapter
│   └── processing_routes.py        # Processing trigger + status
│
├── services/
│   ├── __init__.py
│   ├── book_v2_service.py          # Book CRUD with pipeline_version=2
│   ├── toc_service.py              # TOC validation, chapter creation
│   ├── chapter_page_service.py     # Page upload, inline OCR, conversion, status
│   ├── chunk_processor_service.py  # Single chunk processing (LLM call)
│   ├── topic_extraction_orchestrator.py  # Full chapter extraction + auto-finalization
│   ├── chapter_finalization_service.py   # Consolidation, dedup, LLM merge, sequencing
│   ├── topic_sync_service.py       # Sync chapter_topics → teaching_guidelines
│   └── chapter_job_service.py      # Job lock + progress (adapts V1 pattern)
│
├── models/
│   ├── __init__.py
│   ├── database.py                 # SQLAlchemy: BookChapter, ChapterPage, etc.
│   ├── schemas.py                  # Pydantic API request/response models
│   └── processing_models.py        # Pydantic: ChunkInput, ChunkOutput, TopicMap, etc.
│
├── repositories/
│   ├── __init__.py
│   ├── chapter_repository.py       # BookChapter CRUD
│   ├── chapter_page_repository.py  # ChapterPage CRUD
│   ├── processing_job_repository.py # ChapterProcessingJob CRUD
│   ├── chunk_repository.py         # ChapterChunk CRUD
│   └── topic_repository.py         # ChapterTopic CRUD
│
├── prompts/
│   ├── chunk_topic_extraction.txt  # Per-chunk topic detection + guidelines
│   ├── chapter_consolidation.txt   # End-of-chapter dedup + naming + sequencing
│   └── topic_guidelines_merge.txt  # Merge new chunk guidelines into existing topic
│
└── utils/
    ├── __init__.py
    └── chunk_builder.py            # Build chunk windows from page list
```

### 6.1 Service Responsibilities

| Service | Responsibility | Reuse from V1 |
|---------|---------------|---------------|
| `BookV2Service` | Book CRUD with `pipeline_version=2`, list V2 books | Adapts `BookService` |
| `TOCService` | Validate TOC entries, create `book_chapters` rows, check range overlaps | New |
| `ChapterPageService` | Upload pages within chapter context, validate against TOC range, inline OCR on upload, track completeness | Adapts `PageService`, reuses `OCRService` |
| `ChunkProcessorService` | Process single 3-page chunk: build prompt, call LLM, parse response, return structured output | New (core V2 logic) |
| `TopicExtractionOrchestrator` | Orchestrate chunk-by-chunk processing for a chapter, manage accumulator state, persist chunks, auto-trigger finalization | New (replaces `GuidelineExtractionOrchestrator`) |
| `ChapterFinalizationService` | Consolidation: LLM-merge accumulated guidelines per topic, dedup topics, normalize names, generate summaries, assign sequence | Adapts from V1 finalization services |
| `TopicSyncService` | Sync `chapter_topics` → `teaching_guidelines` table with V2→V1 field mapping | Adapts `DBSyncService` |
| `ChapterJobService` | Job lock, progress tracking, stale detection per chapter | Adapts `JobLockService` |

---

## 7. API Design

### 7.1 Book Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/v2/books` | Create V2 book (sets `pipeline_version=2`) |
| `GET` | `/admin/v2/books` | List V2 books with filters |
| `GET` | `/admin/v2/books/{book_id}` | Get V2 book with chapters summary |
| `DELETE` | `/admin/v2/books/{book_id}` | Delete V2 book + all S3 data + all DB cascade |

### 7.2 TOC Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/v2/books/{book_id}/toc` | Create/replace full TOC (array of chapters) |
| `GET` | `/admin/v2/books/{book_id}/toc` | Get all TOC entries |
| `PUT` | `/admin/v2/books/{book_id}/toc/{chapter_id}` | Update single chapter entry (blocked if pages uploaded) |
| `DELETE` | `/admin/v2/books/{book_id}/toc/{chapter_id}` | Delete chapter (blocked if pages uploaded) |

**TOC Create/Replace Request:**
```json
{
  "chapters": [
    {
      "chapter_number": 1,
      "chapter_title": "Introduction to Fractions",
      "start_page": 1,
      "end_page": 15
    },
    {
      "chapter_number": 2,
      "chapter_title": "Adding and Subtracting Fractions",
      "start_page": 16,
      "end_page": 32
    }
  ]
}
```

**Validation rules:**
- Ranges cannot overlap
- All ranges must be positive, `end_page >= start_page`
- Chapter numbers must be sequential (1, 2, 3, ...)
- Cannot modify/delete chapter if any pages uploaded (409 Conflict)

### 7.3 Page Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/pages` | Upload single page (with page_number). Inline OCR. |
| `POST` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/pages/bulk` | Bulk upload pages. Inline OCR per page. |
| `GET` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/pages` | List pages for chapter |
| `GET` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/pages/{page_num}` | Get page detail + presigned URLs |
| `DELETE` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/pages/{page_num}` | Delete page |
| `POST` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/pages/{page_num}/retry-ocr` | Retry failed OCR |

**Upload single page request:** `multipart/form-data` with `image` file and `page_number` field.

**OCR strategy:** OCR runs **inline on every upload** (single or bulk). No separate batch OCR phase. This eliminates the ambiguous `ocr_processing` state from V1 and guarantees that when `uploaded_page_count == total_pages`, all pages have been OCR'd. Failed OCR pages can be retried via the retry endpoint.

**Validation rules:**
- `page_number` must be within chapter's `[start_page, end_page]` range
- Reject duplicate page_number within chapter (409 unless explicit replace)
- Chapter status transitions: `toc_defined → upload_in_progress` on first upload
- Chapter status transitions: `upload_in_progress → upload_complete` when all pages present and all OCR complete

### 7.4 Processing

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/process` | Start extraction + auto-finalization (requires upload_complete) |
| `POST` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/refinalize` | Re-run finalization only (e.g., after prompt changes) |
| `POST` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/reprocess` | Wipe topics and reprocess from scratch |
| `GET` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/jobs/latest` | Get latest job status |
| `GET` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/jobs/{job_id}` | Get specific job status |
| `GET` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics` | Get extracted topics |
| `GET` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}` | Get specific topic with guidelines |

**Process request:**
```json
{
  "resume": false,
  "auto_sync_to_db": false
}
```
- Runs extraction (all chunks) then **auto-triggers finalization** in the same background job. No manual gate between extraction and finalization.
- Returns `409` if chapter is not in `upload_complete` status (or later if resuming)
- Returns `409` if a job is already running for this chapter
- `resume: true` picks up from `last_completed_chunk + 1`

**Reprocess request:**
```json
{
  "auto_sync_to_db": false
}
```
- Resets chapter to `upload_complete`, creates new `chapter_topics` rows (old topics soft-deleted via version increment). Old processing runs and chunks in DB/S3 are retained for audit.

**Refinalize request:**
```json
{
  "auto_sync_to_db": false
}
```
- Re-runs only the finalization step (consolidation, dedup, naming, sequencing) on existing draft topics. Useful after prompt improvements without re-extracting.

### 7.5 Sync & Review

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/v2/books/{book_id}/sync` | Sync all completed chapters to teaching_guidelines |
| `POST` | `/admin/v2/books/{book_id}/chapters/{chapter_id}/sync` | Sync single chapter to teaching_guidelines |
| `GET` | `/admin/v2/books/{book_id}/results` | Book-level results overview (all chapters) |

---

## 8. Processing Pipeline

### 8.1 Chapter State Machine

```
toc_defined
    │ (first page uploaded + OCR'd inline)
    ▼
upload_in_progress
    │ (all pages in range uploaded, all OCR complete)
    ▼
upload_complete
    │ (POST .../process)
    ▼
topic_extraction ──────────────┐
    │ (all chunks processed)   │ (chunk failure after retries)
    ▼                          ▼
chapter_finalizing          failed (retryable)
    │ (consolidation done)     │
    ▼                          │ (POST .../process with resume:true)
chapter_completed              └──► topic_extraction
```

Notes:
- **No `ocr_processing` state.** OCR is always inline on upload. A page with `ocr_status=failed` can be retried, but doesn't block the chapter state — only `uploaded_page_count == total_pages` AND `all ocr_status == completed` triggers the transition to `upload_complete`.
- **Auto-finalization.** The `/process` endpoint runs extraction and finalization as a single background job. No manual gate between them.
- **`failed` with retry.** A failed chapter can be resumed (`resume: true`) or fully reprocessed (`/reprocess`).
- **Reprocessing.** The `/reprocess` endpoint resets status to `upload_complete`, creates a fresh processing run, and retains old runs for audit.

### 8.2 Topic Extraction Pipeline (per chapter)

```
TopicExtractionOrchestrator.extract(chapter_id)
│
├── 1. Validate: chapter.status == upload_complete, all pages OCR'd
├── 2. Acquire job lock (chapter_processing_jobs)
├── 3. Build chunk windows from page list
│      Pages [1,2,3,4,5,6,7,8,9,10] → Chunks [[1,2,3], [4,5,6], [7,8,9], [10]]
├── 4. Initialize accumulator:
│      chapter_summary_so_far = ""
│      topic_guidelines_map_so_far = {}
│
├── 5. For each chunk [n, n+1, n+2]:
│   ├── a. Load OCR text for pages in chunk
│   ├── b. Load previous-page text (page n-1) if exists
│   ├── c. Snapshot current accumulator state → S3 (chunk input)
│   ├── d. Build prompt with: pages, prev context, summary_so_far, topic_map_so_far
│   ├── e. Call LLM (ChunkProcessorService)
│   ├── f. Parse structured JSON response
│   ├── g. Validate response schema
│   │      On failure: retry up to 3 times with exponential backoff.
│   │      If all retries fail: mark chunk as failed, log error,
│   │      skip to next chunk. Accumulator state is unchanged.
│   │      Job continues with failed_items count incremented.
│   ├── h. Update accumulator:
│   │   ├── chapter_summary_so_far = response.updated_chapter_summary
│   │   └── For each topic in response.topics:
│   │       ├── If is_new: add to topic_guidelines_map_so_far
│   │       └── If existing: merge guidelines_for_this_chunk into existing
│   ├── i. Save chunk record to DB (chapter_chunks)
│   ├── j. Save state snapshot → S3 (state_after.json)
│   └── k. Update job progress (heartbeat + completed count)
│
├── 6. Save pre-consolidation topic map → S3
├── 7. Persist draft topics to chapter_topics table
├── 8. If failed_chunks > 0: mark job as partial_failure, set chapter to failed
│      (admin can resume with resume:true to retry failed chunks)
├── 9. If all chunks succeeded: auto-trigger finalization (Section 8.5)
├── 10. On finalization complete: release job lock, set chapter → chapter_completed
└── 11. If auto_sync_to_db: trigger TopicSyncService
```

**Chunk failure policy:** Each chunk gets **3 retries** with exponential backoff (1s, 2s, 4s). On 3 consecutive failures, the chunk is marked `failed` in `chapter_chunks` with the error message, and the orchestrator continues to the next chunk. The accumulator state is unchanged for failed chunks (the topic map proceeds as if those pages don't exist). After all chunks, if `failed_items > 0`, the job is marked `completed_with_errors` and the admin can either resume (retries only the failed chunks) or reprocess the entire chapter.

### 8.3 Chunk Processing Detail

**Input to LLM (per chunk):**

```json
{
  "book_metadata": {
    "title": "NCERT Mathematics",
    "grade": 6,
    "subject": "Mathematics",
    "board": "CBSE"
  },
  "chapter": {
    "number": 3,
    "title": "Playing with Numbers",
    "page_range": "45-72"
  },
  "current_pages": [
    {"page_number": 50, "text": "...OCR text..."},
    {"page_number": 51, "text": "...OCR text..."},
    {"page_number": 52, "text": "...OCR text..."}
  ],
  "previous_page_context": "...page 49 OCR text...",
  "chapter_summary_so_far": "This chapter covers factors, multiples, and divisibility rules...",
  "topics_so_far": [
    {
      "topic_key": "factors-and-multiples",
      "topic_title": "Factors and Multiples",
      "guidelines": "...accumulated guidelines..."
    }
  ]
}
```

**Expected LLM output:**

```json
{
  "updated_chapter_summary": "This chapter covers factors, multiples, divisibility rules, and prime numbers...",
  "topics": [
    {
      "topic_key": "factors-and-multiples",
      "topic_title": "Factors and Multiples",
      "is_new": false,
      "guidelines_for_this_chunk": "Additional teaching points from these pages: ...",
      "reasoning": "Continues the discussion of factor pairs with larger numbers"
    },
    {
      "topic_key": "prime-and-composite-numbers",
      "topic_title": "Prime and Composite Numbers",
      "is_new": true,
      "guidelines_for_this_chunk": "Teaching guidelines for prime vs composite: ...",
      "reasoning": "New learning objective introduced: identifying prime numbers"
    }
  ]
}
```

### 8.4 Guideline Merging Strategy

**During extraction (per-chunk):** Guidelines are **appended** with a page-range header, not LLM-merged. This is fast (no extra LLM call per topic per chunk) and preserves the raw per-chunk contributions for audit.

```
## Pages 50-52
Teaching guidelines from this chunk...

## Pages 53-55
Additional teaching points from this chunk...
```

**During finalization:** The `ChapterFinalizationService` performs a **single LLM merge per topic** on the accumulated append-style guidelines. The merge prompt consolidates all chunk contributions into a unified, non-redundant guideline text. This means a chapter with 10 chunks and 5 topics produces at most 5 merge calls during finalization, not 50 during extraction.

**Cost analysis:** For a 30-page chapter (10 chunks, ~5 topics): extraction = 10 LLM calls (one per chunk). Finalization = 1 consolidation call + 5 merge calls + any dedup merges. Total ≈ 16-18 calls vs the alternative of 10 + 50 = 60 calls with inline merging.

### 8.5 Chapter Finalization Pipeline

```
ChapterFinalizationService.finalize(chapter_id)
│
├── 1. Load all draft topics from chapter_topics (with appended guidelines)
├── 2. Save pre-consolidation snapshot → S3
├── 3. LLM-merge each topic's guidelines:
│      For each topic: call merge prompt to consolidate the appended
│      per-chunk guidelines into a single unified guideline text.
│      (One LLM call per topic — see Section 8.4 for cost analysis)
├── 4. Call consolidation LLM:
│   ├── Input: all topics with merged guidelines
│   ├── Output:
│   │   ├── chapter_display_name (AI-generated chapter title)
│   │   ├── final_chapter_summary
│   │   ├── merge_actions: [{merge_from, merge_into, reasoning}]
│   │   ├── topic_updates: [{key, new_title, summary, sequence, reasoning}]
│   └── Validate output schema
├── 5. Execute dedup merge actions:
│   ├── For each merge: LLM-merge guidelines of two topics
│   ├── Delete merged-from topic
│   └── Update merged-into topic
├── 6. Apply topic updates (rename, resequence, add summaries)
├── 7. Update chapter: display_name, summary
├── 8. Mark all topics as 'final'
├── 9. Save final output → S3 (chapter_result.json + topics/*.json)
└── 10. Update chapter status → chapter_completed
```

---

## 9. LLM Prompt Contracts

### 9.1 LLM Configuration

Add a new component key to `llm_config`:

| Component Key | Default Provider | Default Model | Purpose |
|---------------|-----------------|---------------|---------|
| `book_ingestion_v2` | openai | gpt-5.2 | All V2 pipeline LLM calls |

This keeps V1 and V2 model configuration independent.

**Concurrency note:** Multiple chapters can be processed simultaneously (each has its own job lock). The `BackgroundTaskRunner` spawns one thread per chapter. LLM rate limits are handled by the existing retry-with-backoff logic in `LLMService` (3 retries, exponential backoff). For very large books (20+ chapters), consider processing in batches of 3-5 chapters to avoid rate limit saturation. This can be enforced at the API level or left as an admin best practice for MVP.

### 9.2 Chunk Topic Extraction Prompt

**File:** `book_ingestion_v2/prompts/chunk_topic_extraction.txt`

**Contract:**
- Input: book metadata, chapter context, 3 pages of OCR text, previous page context, running summary, running topic map
- Output: strict JSON matching `ChunkExtractionOutput` Pydantic model
- Temperature: 0.2
- Granularity heuristic embedded in prompt: 10-20 minute learning units, conceptually atomic

**Output schema (Pydantic):**
```python
class TopicUpdate(BaseModel):
    topic_key: str          # kebab-case
    topic_title: str        # Human readable
    is_new: bool
    guidelines_for_this_chunk: str   # Teaching content from these pages
    reasoning: str          # Why new/existing

class ChunkExtractionOutput(BaseModel):
    updated_chapter_summary: str
    topics: List[TopicUpdate]
```

### 9.3 Chapter Consolidation Prompt

**File:** `book_ingestion_v2/prompts/chapter_consolidation.txt`

**Contract:**
- Input: all topics with full guidelines, chapter metadata
- Output: strict JSON matching `ConsolidationOutput` Pydantic model
- Temperature: 0.2

**Output schema:**
```python
class MergeAction(BaseModel):
    merge_from: str         # topic_key to absorb
    merge_into: str         # topic_key to keep
    reasoning: str

class TopicFinalUpdate(BaseModel):
    original_key: str
    new_key: str            # May be same as original
    new_title: str
    summary: str            # 20-40 word summary
    sequence_order: int     # 1-based teaching order
    name_change_reasoning: str

class ConsolidationOutput(BaseModel):
    chapter_display_name: str
    final_chapter_summary: str
    merge_actions: List[MergeAction]
    topic_updates: List[TopicFinalUpdate]
```

### 9.4 Topic Guidelines Merge Prompt

**File:** `book_ingestion_v2/prompts/topic_guidelines_merge.txt`

Reuse the pattern from V1's `guideline_merge_v2.txt` with minor adaptations:
- Input: existing guidelines text + new chunk guidelines text + topic context
- Output: merged guidelines text (single string)
- Temperature: 0.3

---

## 10. Frontend Design

### 10.1 New Pages & Routes

| Route | Component | Description |
|-------|-----------|-------------|
| `/admin/books-v2` | `BookV2Dashboard` | List V2 books with status |
| `/admin/books-v2/new` | `CreateBookV2` | Create book + TOC in one flow |
| `/admin/books-v2/:id` | `BookV2Detail` | Book hub with chapter workflow |

### 10.2 BookV2Detail — Multi-Step Chapter Workflow

The `BookV2Detail` page is the main hub. It shows book metadata at the top and a chapter list below. Each chapter is an expandable card showing its current state.

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  ← Back    Book: NCERT Mathematics Grade 6    [Delete]  │
│  Author: NCERT  |  Grade: 6  |  Subject: Mathematics   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [TOC Editor Tab]  [Chapters Tab]  [Results Tab]        │
│                                                         │
│  ┌─── Chapter 1: Knowing Our Numbers (pp. 1-28) ────┐  │
│  │  Status: upload_complete  [28/28 pages]           │  │
│  │  [Start Processing]                               │  │
│  │                                                   │  │
│  │  Pages: ■■■■■■■■■■■■■■■■■■■■■■■■■■■■ 28/28       │  │
│  │  Upload: [Drop files here]                        │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── Chapter 2: Whole Numbers (pp. 29-48) ──────────┐  │
│  │  Status: topic_extraction  [Processing...]        │  │
│  │  Progress: ████████░░ 6/7 chunks                  │  │
│  │  Topics found: 4                                  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── Chapter 3: Playing with Numbers (pp. 49-72) ───┐  │
│  │  Status: chapter_completed                        │  │
│  │  Display Name: "Factors, Multiples & Divisibility"│  │
│  │  Topics: 5  [View Topics]  [Sync to DB]           │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 10.3 Tab Breakdown

**TOC Editor Tab:**
- Table with columns: #, Title, Start Page, End Page, Actions
- Add/edit/delete rows (inline editing)
- Validation feedback (overlaps, gaps, invalid ranges)
- Save TOC button (calls `POST /admin/v2/books/{id}/toc`)
- Locked indicator on chapters with uploaded pages

**Chapters Tab:**
- Expandable chapter cards (as shown above)
- Each card shows: status badge, page progress, action buttons
- Expanded view: page grid with upload, OCR status, approve/reject
- Processing progress bar with chunk-level detail
- Reuse `useJobPolling` hook for progress tracking

**Results Tab:**
- Shows completed chapters with their topics
- Topic list per chapter: key, title, summary, page range, sequence
- Expand topic to see full guidelines
- "Sync All to DB" and per-chapter sync buttons

### 10.4 Reusable Components

| Component | Reuse from V1 | Notes |
|-----------|--------------|-------|
| `useJobPolling` hook | Direct reuse | Same polling pattern, different endpoint |
| Page upload (drag-drop) | Adapt `PageUploadPanel` | Add page_number assignment within range |
| Page viewer | Reuse `PageViewPanel` | Same image + OCR text display |
| Status badges | Adapt `BookStatusBadge` | New status values for chapters |
| Job progress bar | Extract from `GuidelinesPanel` | Same pattern |
| API client pattern | Extend `adminApi.ts` | Add V2 endpoints |

### 10.5 New API Client Functions

Add to a new file `llm-frontend/src/features/admin/api/adminApiV2.ts`:

```typescript
// Book management
createBookV2(data: CreateBookV2Request): Promise<BookV2Response>
listBooksV2(filters?: BookFilters): Promise<BookV2ListResponse>
getBookV2(bookId: string): Promise<BookV2DetailResponse>
deleteBookV2(bookId: string): Promise<void>

// TOC
saveTOC(bookId: string, chapters: TOCEntry[]): Promise<TOCResponse>
getTOC(bookId: string): Promise<TOCEntry[]>
updateChapter(bookId: string, chapterId: string, data: Partial<TOCEntry>): Promise<TOCEntry>
deleteChapter(bookId: string, chapterId: string): Promise<void>

// Pages (per chapter)
uploadPage(bookId: string, chapterId: string, pageNum: number, file: File): Promise<PageResponse>
bulkUploadPages(bookId: string, chapterId: string, files: File[]): Promise<BulkUploadResponse>
getChapterPages(bookId: string, chapterId: string): Promise<ChapterPageInfo[]>
approvePage(bookId: string, chapterId: string, pageNum: number): Promise<void>
deletePage(bookId: string, chapterId: string, pageNum: number): Promise<void>

// Processing
startProcessing(bookId: string, chapterId: string, resume?: boolean): Promise<JobResponse>
startFinalization(bookId: string, chapterId: string): Promise<JobResponse>
getLatestJob(bookId: string, chapterId: string): Promise<JobStatus>
getChapterTopics(bookId: string, chapterId: string): Promise<ChapterTopicResponse[]>

// Sync
syncChapter(bookId: string, chapterId: string): Promise<SyncResponse>
syncBook(bookId: string): Promise<SyncResponse>
```

---

## 11. Reuse Analysis

### 11.1 Direct Reuse (No Changes)

| Component | File | Usage in V2 |
|-----------|------|-------------|
| `S3Client` | `book_ingestion/utils/s3_client.py` | All S3 operations |
| `OCRService` | `book_ingestion/services/ocr_service.py` | Page OCR (same Vision API call) |
| `BackgroundTaskRunner` | `book_ingestion/services/background_task_runner.py` | Background jobs |
| `LLMConfigService` | `shared/services/llm_config_service.py` | Model selection |
| `LLMService` | `shared/services/llm_service.py` | LLM API calls |
| `DatabaseManager` | `database.py` | DB connections |
| `PromptTemplate` | `tutor/prompts/templates.py` | Prompt rendering |
| `useJobPolling` hook | `features/admin/hooks/useJobPolling.ts` | Frontend polling |

### 11.2 Adapt (Pattern Reuse, V2 Implementation)

| V1 Component | V2 Adaptation | What Changes |
|-------------|---------------|-------------|
| `JobLockService` | `ChapterJobService` | Scope changes from book-level to chapter-level. Same state machine, heartbeat, stale detection. |
| `BookService` | `BookV2Service` | Adds `pipeline_version=2` on creation. Filters by version. |
| `PageService` | `ChapterPageService` | Pages scoped to chapter. Validates against TOC range. Inline OCR (no batch). |
| `GuidelineMergeService` | Reuse in `ChapterFinalizationService` | Same merge prompt pattern. Called once per topic during finalization, not per-chunk. |
| `DBSyncService` | `TopicSyncService` | Maps chapter→topic, topic→subtopic when writing to teaching_guidelines. |
| `PageUploadPanel` | Adapt for V2 | Add page number assignment within chapter range. |

### 11.3 New (V2 Only)

| Component | Purpose |
|-----------|---------|
| `TOCService` | TOC validation, chapter creation, range checks |
| `ChunkProcessorService` | Core V2 logic: single chunk processing |
| `TopicExtractionOrchestrator` | Chapter-level extraction pipeline |
| `ChapterFinalizationService` | Consolidation, dedup, naming |
| `chunk_topic_extraction.txt` | New prompt for chunk processing |
| `chapter_consolidation.txt` | New prompt for chapter finalization |
| TOC Editor UI | New frontend component |
| Chapter workflow UI | New frontend component |

---

## 12. Migration & Deployment

### 12.1 Database Migration

Add to `db.py`:

```python
def _apply_v2_tables():
    """Create V2 book ingestion tables."""
    # 1. Add pipeline_version column to books
    # 2. CREATE TABLE IF NOT EXISTS for all V2 tables
    # 3. Seed llm_config with book_ingestion_v2 component key
```

**Migration is additive only** — no existing table modifications beyond adding `pipeline_version` column (nullable, default 1). Fully backward-compatible.

### 12.2 Route Registration

In `main.py`, register V2 routers under `/admin/v2`:

```python
from book_ingestion_v2.api import book_routes, toc_routes, chapter_routes, page_routes, processing_routes

app.include_router(book_routes.router, prefix="/admin/v2")
app.include_router(toc_routes.router, prefix="/admin/v2")
app.include_router(chapter_routes.router, prefix="/admin/v2")
app.include_router(page_routes.router, prefix="/admin/v2")
app.include_router(processing_routes.router, prefix="/admin/v2")
```

### 12.3 Frontend Route Registration

In `App.tsx`, add V2 admin routes:

```tsx
<Route path="/admin/books-v2" element={<BookV2Dashboard />} />
<Route path="/admin/books-v2/new" element={<CreateBookV2 />} />
<Route path="/admin/books-v2/:id" element={<BookV2Detail />} />
```

### 12.4 LLM Config Seed

Add to `_seed_llm_config()`:

```python
{"component_key": "book_ingestion_v2", "provider": "openai", "model_id": "gpt-5.2"}
```

---

## 13. Testing Strategy

### 13.1 Unit Tests

| Layer | What to Test | Approach |
|-------|-------------|----------|
| `TOCService` | Range overlap detection, gap detection, sequential numbering, lock-after-upload | Pure unit tests |
| `ChunkBuilder` | Window construction from page list, edge cases (< 3 pages, exact multiples, remainders) | Pure unit tests |
| `ChunkProcessorService` | Prompt construction, response parsing, accumulator updates | Mock LLM, validate I/O |
| `TopicExtractionOrchestrator` | Multi-chunk flow, resume from checkpoint, error handling | Mock services |
| `ChapterFinalizationService` | Merge execution, rename application, sequence assignment | Mock LLM |
| `TopicSyncService` | V2→V1 field mapping correctness | Mock DB |
| `Repositories` | CRUD operations, unique constraints, cascades | Test DB |

### 13.2 Integration Tests

| Scenario | Coverage |
|----------|----------|
| Full chapter pipeline | Upload → OCR → Extract → Finalize → Sync |
| Resume after failure | Inject failure at chunk N, resume, verify continuity |
| TOC validation edge cases | Overlapping ranges, gaps, single-page chapters |
| Concurrent chapter processing | Two chapters processing simultaneously |
| DB sync correctness | Verify teaching_guidelines rows match chapter_topics |

### 13.3 E2E Tests

| Scenario | Coverage |
|----------|----------|
| Create book + TOC + upload + process | Full admin workflow |
| Student can learn from V2 book | V2 sync → tutor session works |

---

## 14. Implementation Phases

### Phase 1: Foundation — DB + Models + S3 Structure
**Estimated scope: ~8 files**

- [ ] Add `pipeline_version` column to `books` table in `db.py`
- [ ] Create SQLAlchemy models in `book_ingestion_v2/models/database.py`
- [ ] Create Pydantic schemas in `book_ingestion_v2/models/schemas.py`
- [ ] Create processing models in `book_ingestion_v2/models/processing_models.py`
- [ ] Create all 5 repository classes
- [ ] Add `book_ingestion_v2` to `llm_config` seed
- [ ] Write migration function and test

### Phase 2: Book + TOC Management
**Estimated scope: ~6 files**

- [ ] `BookV2Service` — create/list/get/delete V2 books
- [ ] `TOCService` — validate + create TOC entries
- [ ] `book_routes.py` — book CRUD endpoints
- [ ] `toc_routes.py` — TOC CRUD endpoints
- [ ] Unit tests for TOC validation
- [ ] Register routes in `main.py`

### Phase 3: Chapter Page Management
**Estimated scope: ~4 files**

- [ ] `ChapterPageService` — upload with inline OCR, delete, retry-ocr, completeness tracking
- [ ] `page_routes.py` — page management endpoints
- [ ] `ChapterJobService` — job lock + progress (adapt V1 pattern)
- [ ] Unit tests for page service

### Phase 4: Topic Extraction + Finalization Pipeline (Core V2)
**Estimated scope: ~8 files**

- [ ] `chunk_builder.py` — build 3-page windows from page list
- [ ] `chunk_topic_extraction.txt` — LLM prompt for per-chunk topic detection
- [ ] `topic_guidelines_merge.txt` — merge prompt (adapt from V1, used in finalization)
- [ ] `chapter_consolidation.txt` — consolidation prompt (dedup, naming, sequencing)
- [ ] `ChunkProcessorService` — single chunk processing with retry logic
- [ ] `TopicExtractionOrchestrator` — full chapter pipeline (extraction + auto-finalization)
- [ ] `ChapterFinalizationService` — LLM merge per topic, dedup, rename, sequence, summarize
- [ ] `processing_routes.py` — process/reprocess/refinalize trigger + status endpoints
- [ ] Unit + integration tests

### Phase 5: DB Sync
**Estimated scope: ~2 files**

- [ ] `TopicSyncService` — sync chapter_topics → teaching_guidelines
- [ ] Sync endpoint + integration test
- [ ] Verify tutor can use V2-synced guidelines

### Phase 6: Frontend — TOC + Book Creation
**Estimated scope: ~6 files**

- [ ] `adminApiV2.ts` — V2 API client
- [ ] V2 TypeScript types
- [ ] `BookV2Dashboard` page
- [ ] `CreateBookV2` page (book metadata + TOC authoring)
- [ ] Register routes in `App.tsx`

### Phase 7: Frontend — Chapter Upload + Processing
**Estimated scope: ~5 files**

- [ ] `BookV2Detail` page with chapter cards
- [ ] Chapter upload UI (adapt PageUploadPanel)
- [ ] Processing progress UI (reuse useJobPolling)
- [ ] Results/topics viewer

### Phase 8: Polish + Testing
**Estimated scope: ~varies**

- [ ] E2E test: full pipeline
- [ ] E2E test: V2 book → tutor session
- [ ] Error handling edge cases
- [ ] Admin UX polish

---

## Appendix A: Pydantic Model Reference

### Processing Models (`processing_models.py`)

```python
class ChunkWindow(BaseModel):
    """Definition of a processing chunk."""
    chunk_index: int
    pages: List[int]           # Absolute page numbers in this chunk
    previous_page: Optional[int]  # Page n-1 for context

class RunningState(BaseModel):
    """Accumulator state between chunks."""
    chapter_summary_so_far: str
    topic_guidelines_map: Dict[str, TopicAccumulator]  # topic_key → accumulator

class TopicAccumulator(BaseModel):
    """Running state for a single topic."""
    topic_key: str
    topic_title: str
    guidelines: str
    source_page_start: int
    source_page_end: int

class ChunkInput(BaseModel):
    """Full input for a chunk processing call."""
    book_metadata: Dict[str, Any]
    chapter_metadata: Dict[str, Any]
    current_pages: List[Dict[str, Any]]  # [{page_number, text}]
    previous_page_context: Optional[str]
    chapter_summary_so_far: str
    topics_so_far: List[TopicAccumulator]

class TopicUpdate(BaseModel):
    """Single topic detected/updated in a chunk."""
    topic_key: str
    topic_title: str
    is_new: bool
    guidelines_for_this_chunk: str
    reasoning: str

class ChunkExtractionOutput(BaseModel):
    """LLM output for a single chunk."""
    updated_chapter_summary: str
    topics: List[TopicUpdate]

class MergeAction(BaseModel):
    merge_from: str
    merge_into: str
    reasoning: str

class TopicFinalUpdate(BaseModel):
    original_key: str
    new_key: str
    new_title: str
    summary: str
    sequence_order: int
    name_change_reasoning: str

class ConsolidationOutput(BaseModel):
    """LLM output for chapter finalization."""
    chapter_display_name: str
    final_chapter_summary: str
    merge_actions: List[MergeAction]
    topic_updates: List[TopicFinalUpdate]
```

### API Schemas (`schemas.py`)

```python
class CreateBookV2Request(BaseModel):
    title: str
    author: Optional[str]
    edition: Optional[str]
    edition_year: Optional[int]
    country: str
    board: str
    grade: int
    subject: str

class TOCEntry(BaseModel):
    chapter_number: int
    chapter_title: str
    start_page: int
    end_page: int

class SaveTOCRequest(BaseModel):
    chapters: List[TOCEntry]

class ChapterResponse(BaseModel):
    id: str
    chapter_number: int
    chapter_title: str
    start_page: int
    end_page: int
    display_name: Optional[str]
    summary: Optional[str]
    status: str
    total_pages: int
    uploaded_page_count: int

class BookV2DetailResponse(BaseModel):
    id: str
    title: str
    author: Optional[str]
    grade: int
    subject: str
    board: str
    country: str
    pipeline_version: int
    chapters: List[ChapterResponse]

class ChapterTopicResponse(BaseModel):
    id: str
    topic_key: str
    topic_title: str
    guidelines: str
    summary: Optional[str]
    source_page_start: Optional[int]
    source_page_end: Optional[int]
    sequence_order: Optional[int]
    status: str

class ProcessingJobResponse(BaseModel):
    job_id: str
    chapter_id: str
    job_type: str
    status: str
    total_items: Optional[int]
    completed_items: int
    failed_items: int
    current_item: Optional[str]
    progress_detail: Optional[Dict]
```

---

## Appendix B: Constants & Configuration

```python
# book_ingestion_v2/constants.py
from enum import Enum

CHUNK_SIZE = 3                    # Pages per chunk
CHUNK_STRIDE = 3                  # Non-overlapping (stride == size)
CHUNK_MAX_RETRIES = 3             # Retries per chunk on LLM failure
HEARTBEAT_STALE_THRESHOLD = 120   # Seconds (2 minutes)
PENDING_STALE_THRESHOLD = 120     # Seconds

class ChapterStatus(str, Enum):
    TOC_DEFINED = "toc_defined"
    UPLOAD_IN_PROGRESS = "upload_in_progress"
    UPLOAD_COMPLETE = "upload_complete"
    TOPIC_EXTRACTION = "topic_extraction"
    CHAPTER_FINALIZING = "chapter_finalizing"
    CHAPTER_COMPLETED = "chapter_completed"
    FAILED = "failed"

class V2JobType(str, Enum):
    TOPIC_EXTRACTION = "v2_topic_extraction"       # Extraction + auto-finalization
    REFINALIZATION = "v2_refinalization"            # Re-run finalization only

class V2JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # Some chunks failed
    FAILED = "failed"

class OCRStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class TopicStatus(str, Enum):
    DRAFT = "draft"
    CONSOLIDATED = "consolidated"
    FINAL = "final"
    APPROVED = "approved"

# LLM config component key
LLM_CONFIG_KEY = "book_ingestion_v2"
```
