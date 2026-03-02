# Technical Implementation Plan: Book Ingestion Pipeline V2

**PRD:** `docs/feature-development/book-ingestion-v2/prd.md`
**Date:** 2026-03-02
**Status:** Draft

---

## Table of Contents

1. [Design Philosophy & Key Decisions](#1-design-philosophy--key-decisions)
2. [Architecture Overview](#2-architecture-overview)
3. [S3 Structure](#3-s3-structure)
4. [Database Schema](#4-database-schema)
5. [Pipeline Phases](#5-pipeline-phases)
6. [Chunk Processing Deep Dive](#6-chunk-processing-deep-dive)
7. [Chapter Finalization Deep Dive](#7-chapter-finalization-deep-dive)
8. [DB Sync & Tutor Integration](#8-db-sync--tutor-integration)
9. [API Contracts](#9-api-contracts)
10. [Prompt Contracts](#10-prompt-contracts)
11. [Module & File Layout](#11-module--file-layout)
12. [Reuse vs Redesign Inventory](#12-reuse-vs-redesign-inventory)
13. [Migration Strategy](#13-migration-strategy)
14. [Implementation Order](#14-implementation-order)
15. [Test Strategy](#15-test-strategy)
16. [Open Questions & Decisions](#16-open-questions--decisions)

---

## 1. Design Philosophy & Key Decisions

### 1.1 Core Principle: Chapter as Processing Boundary

V1 tried to infer structure across the entire book, making boundary detection brittle. V2 inverts this: **the admin provides the chapter structure via TOC, and AI only operates within chapter boundaries**. This eliminates the hardest problem (cross-chapter boundary detection) and constrains AI to a single, well-scoped task: topic detection within a known chapter.

### 1.2 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Hierarchy** | Book → Chapter → Topic (no subtopic) | Simpler, maps to 10-20 min learning units directly |
| **TOC mutability** | Locked after first page upload | Prevents inconsistency; admin must delete chapter to re-define |
| **Page indexing** | Admin-entered page numbers (absolute) | Source of truth matches the physical book |
| **Chunk stride** | Non-overlapping (pages 1-3, 4-6, 7-9...) with previous-page context | Simpler than sliding window; prev-page context prevents boundary artifacts |
| **Chapter display name** | Store both TOC title and AI-generated `display_name` | Admin's TOC title is canonical; AI suggestion is advisory |
| **Approval gate** | Existing review workflow (TO_BE_REVIEWED → APPROVED) | Consistency with V1; tutor only sees APPROVED guidelines |
| **Backward compat** | None required for V1 books | User directive; V1 pipeline remains intact for existing books |
| **Parallel system** | New `book_ingestion_v2/` package, new DB tables | Zero risk to V1; clean separation |

### 1.3 What V2 Changes in the Tutor Contract

V2 produces the same output contract that the tutor already consumes:

| V2 Concept | Maps to `teaching_guidelines` Column | Tutor Consumption |
|------------|--------------------------------------|-------------------|
| Chapter title | `topic_title`, `topic_key` | Displayed as topic grouping |
| Topic title | `subtopic_title`, `subtopic_key` | Displayed as learning unit name |
| Topic guidelines | `guideline` | Teaching approach text |
| Chapter sequence | `topic_sequence` | Curriculum ordering |
| Topic sequence | `subtopic_sequence` | Within-chapter ordering |

The `topic_adapter.py` already handles this mapping. V2 simply produces better-quality data in the same columns.

### 1.4 Topic Adapter Enhancement

Currently `topic_adapter.py` uses `guideline.guideline[:500]` as a fallback for `teaching_approach`. With V2's comprehensive guideline text (1000-3000 words), this truncation loses critical content. The adapter should be updated to pass the **full guideline text** as `teaching_approach`, not just 500 chars. This is a small but important change.

---

## 2. Architecture Overview

### 2.1 Current V1 Architecture

```
Admin uploads pages → Per-page OCR → Per-page boundary detection + extraction
→ Merge into SubtopicShards → Book-level finalization → DB sync
```

**Problems:** Book-wide boundary detection is brittle; page-by-page processing loses chapter context; topic/subtopic hierarchy is inferred.

### 2.2 V2 Target Architecture

```
Admin enters book metadata
  → Admin defines TOC (chapters + page ranges)
  → Admin uploads pages per chapter
  → Per-chapter OCR (batch, all pages)
  → Per-chapter topic extraction (3-page rolling chunks with running state)
  → Per-chapter finalization (consolidation, dedup, naming, sequencing)
  → Book-level sequencing (order chapters, order topics across book)
  → DB sync to teaching_guidelines
  → Study plan generation (reuse existing orchestrator)
```

### 2.3 Execution Model

Reuse V1's background task runner pattern:
- HTTP endpoint creates job row, launches daemon thread, returns job_id immediately
- Background thread processes chunks, updates progress in DB
- Frontend polls job status endpoint every 3s
- Heartbeat-based stale detection (30s interval)
- Resume from last checkpoint on failure

### 2.4 Data Flow Diagram

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  Admin UI   │────→│  TOC + Pages │────→│  S3 Storage    │
│  (Frontend) │     │  (API)       │     │  (per chapter) │
└─────────────┘     └──────────────┘     └────────────────┘
                                                │
                           ┌────────────────────┘
                           ▼
                    ┌──────────────┐     ┌────────────────────┐
                    │  OCR Job     │────→│  chapter pages/    │
                    │  (per ch.)   │     │  {page}.txt        │
                    └──────────────┘     └────────────────────┘
                                                │
                           ┌────────────────────┘
                           ▼
                    ┌──────────────────────┐     ┌─────────────────────┐
                    │  Topic Extraction    │────→│  processing/chunks/ │
                    │  (3-page chunks)     │     │  processing/states/ │
                    │  Running state:      │     │  output/topics/     │
                    │  - summary_so_far    │     └─────────────────────┘
                    │  - topic_map_so_far  │
                    └──────────────────────┘
                                │
                           ┌────┘
                           ▼
                    ┌──────────────────────┐     ┌─────────────────────┐
                    │  Finalization        │────→│  output/ (final)    │
                    │  - Dedup             │     │  consolidation/     │
                    │  - Name refinement   │     └─────────────────────┘
                    │  - Sequencing        │
                    └──────────────────────┘
                                │
                           ┌────┘
                           ▼
                    ┌──────────────────────┐     ┌─────────────────────┐
                    │  DB Sync             │────→│  teaching_guidelines│
                    │  chapter_topics →    │     │  study_plans        │
                    │  teaching_guidelines │     └─────────────────────┘
                    └──────────────────────┘
```

---

## 3. S3 Structure

### 3.1 Complete S3 Layout

```
books/{book_id}/
├── metadata.json                              # Book-level metadata (title, author, grade, subject, board)
├── toc.json                                   # TOC definition (chapters, page ranges)
│
├── chapters/
│   └── ch_{chapter_number:03d}/               # e.g., ch_001, ch_002
│       │
│       ├── meta.json                          # Chapter metadata + current processing state
│       │
│       ├── pages/
│       │   ├── raw/
│       │   │   └── {page_num}.{ext}           # Raw uploaded image (original format)
│       │   ├── {page_num}.png                 # Converted page image (standardized PNG)
│       │   └── {page_num}.txt                 # OCR text output
│       │
│       ├── processing/
│       │   ├── config.json                    # Snapshot: model config + prompt versions used
│       │   │
│       │   ├── chunks/
│       │   │   ├── chunk_000_input.json       # Input to LLM for chunk 0 (pages, context, state)
│       │   │   ├── chunk_000_output.json      # Raw LLM response for chunk 0
│       │   │   ├── chunk_001_input.json
│       │   │   ├── chunk_001_output.json
│       │   │   └── ...
│       │   │
│       │   ├── states/
│       │   │   ├── state_after_chunk_000.json # Running state snapshot after chunk 0
│       │   │   ├── state_after_chunk_001.json # Running state snapshot after chunk 1
│       │   │   └── ...                        # (chapter_summary + topic_map at each point)
│       │   │
│       │   └── consolidation/
│       │       ├── pre_consolidation.json     # All topics before consolidation pass
│       │       ├── consolidation_actions.json # LLM decisions: what was merged/renamed/kept
│       │       └── post_consolidation.json    # Final topics after consolidation
│       │
│       └── output/
│           ├── chapter_summary.txt            # Final chapter summary
│           ├── topics_index.json              # Topic registry for this chapter
│           └── topics/
│               └── {topic_key}.json           # Individual topic guideline (final)
```

### 3.2 Key S3 Artifacts Explained

**`toc.json`** — Admin-entered table of contents:
```json
{
  "book_id": "ncert_math_3_2024",
  "chapters": [
    {
      "chapter_number": 1,
      "chapter_title": "Where to Look From",
      "start_page": 1,
      "end_page": 14
    },
    {
      "chapter_number": 2,
      "chapter_title": "Fun with Numbers",
      "start_page": 15,
      "end_page": 30
    }
  ],
  "created_at": "2026-03-01T10:00:00Z",
  "created_by": "admin"
}
```

**`meta.json`** (per chapter) — Chapter state + metadata:
```json
{
  "chapter_number": 1,
  "chapter_title": "Where to Look From",
  "start_page": 1,
  "end_page": 14,
  "status": "topic_extraction_processing",
  "total_pages": 14,
  "uploaded_pages": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
  "ocr_completed_pages": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
  "last_processed_chunk": 2,
  "total_chunks": 5,
  "updated_at": "2026-03-01T12:30:00Z"
}
```

**`chunk_NNN_input.json`** — Full audit of what went into the LLM:
```json
{
  "chunk_index": 0,
  "pages": [1, 2, 3],
  "page_texts": {
    "1": "Page 1 OCR text...",
    "2": "Page 2 OCR text...",
    "3": "Page 3 OCR text..."
  },
  "previous_page_text": null,
  "chapter_summary_so_far": "",
  "topic_guidelines_map_so_far": {},
  "chapter_metadata": {
    "chapter_title": "Where to Look From",
    "book_grade": 3,
    "book_subject": "Mathematics",
    "book_board": "CBSE"
  }
}
```

**`chunk_NNN_output.json`** — Raw LLM response + validation:
```json
{
  "chunk_index": 0,
  "raw_llm_response": "...",
  "parsed_output": {
    "topics": [
      {
        "topic_key": "shapes-around-us",
        "topic_title": "Shapes Around Us",
        "is_new": true,
        "guidelines_for_chunk": "Students learn to identify...",
        "page_range": "1-3"
      }
    ],
    "chapter_summary_update": "This chapter introduces spatial reasoning..."
  },
  "model_used": "gpt-4o",
  "token_count": 2450,
  "processing_time_ms": 3200,
  "validation_passed": true
}
```

**`state_after_chunk_NNN.json`** — Running state snapshot (enables resume):
```json
{
  "chunk_index": 0,
  "chapter_summary_so_far": "This chapter introduces spatial reasoning...",
  "topic_guidelines_map_so_far": {
    "shapes-around-us": {
      "topic_key": "shapes-around-us",
      "topic_title": "Shapes Around Us",
      "guidelines": "Students learn to identify common 2D shapes...",
      "source_page_start": 1,
      "source_page_end": 3,
      "contributing_chunks": [0]
    }
  },
  "saved_at": "2026-03-01T12:00:05Z"
}
```

**`topics/{topic_key}.json`** — Final topic guideline (post-consolidation):
```json
{
  "topic_key": "shapes-around-us",
  "topic_title": "Shapes Around Us",
  "topic_summary": "Identifying and classifying 2D shapes in everyday objects using observation and comparison.",
  "guidelines": "Students learn to identify common 2D shapes in their surroundings. Begin with...",
  "source_page_start": 1,
  "source_page_end": 6,
  "contributing_chunks": [0, 1],
  "sequence_number": 1,
  "version": 2,
  "created_at": "2026-03-01T12:00:05Z",
  "updated_at": "2026-03-01T13:15:00Z"
}
```

### 3.3 Design Rationale

- **Chapter isolation**: Each chapter is fully self-contained in S3. Can reprocess one chapter without touching others.
- **Full audit trail**: Every chunk's input AND output preserved. Can reconstruct exactly what the LLM saw and produced.
- **State snapshots**: Can resume from any chunk. If chunk 3 fails, load `state_after_chunk_002.json` and continue.
- **Consolidation transparency**: Before/after consolidation visible for debugging.
- **Clean output directory**: Final topics in `output/topics/` are the canonical result, easily consumed by DB sync.

---

## 4. Database Schema

### 4.1 Schema Changes Overview

| Table | Action | Purpose |
|-------|--------|---------|
| `books` | **Extend** (add `pipeline_version`) | Distinguish V1 vs V2 books |
| `book_chapters` | **New** | TOC entries + chapter state machine |
| `chapter_pages` | **New** | Per-page tracking within chapters |
| `chapter_processing_jobs` | **New** | Job tracking per chapter (replaces `book_jobs` for V2) |
| `chapter_topics` | **New** | Final topic output per chapter (pre-sync staging) |
| `chunk_processing_log` | **New** | Audit trail of every chunk processed |
| `teaching_guidelines` | **Keep** | Final sync destination (tutor contract) |
| `study_plans` | **Keep** | Generated from synced guidelines |
| `book_guidelines` | **Keep** (V1 only) | V1 guideline review; unused by V2 |
| `book_jobs` | **Keep** (V1 only) | V1 job tracking; unused by V2 |

### 4.2 `books` Table Extension

```sql
-- Add pipeline_version to existing books table
ALTER TABLE books ADD COLUMN pipeline_version VARCHAR(10) DEFAULT 'v1' NOT NULL;

-- V2 books will be created with pipeline_version = 'v2'
-- V1 books remain unchanged
```

### 4.3 `book_chapters` Table (New)

```sql
CREATE TABLE book_chapters (
    id VARCHAR PRIMARY KEY,                    -- UUID
    book_id VARCHAR NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,           -- 1-based sequence from TOC
    chapter_title VARCHAR NOT NULL,            -- Admin-entered title from TOC
    display_name VARCHAR,                      -- AI-suggested name (optional, advisory)
    start_page INTEGER NOT NULL,               -- First page (inclusive, from TOC)
    end_page INTEGER NOT NULL,                 -- Last page (inclusive, from TOC)

    -- Chapter summary (built incrementally, finalized at end)
    chapter_summary TEXT,

    -- State machine
    -- toc_defined → uploading → upload_complete → ocr_processing →
    -- ocr_complete → topic_extraction → finalizing → completed | failed
    status VARCHAR NOT NULL DEFAULT 'toc_defined',

    -- Progress counters
    total_pages INTEGER NOT NULL,              -- end_page - start_page + 1
    uploaded_pages INTEGER DEFAULT 0,
    ocr_completed_pages INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR DEFAULT 'admin',

    -- Constraints
    UNIQUE(book_id, chapter_number),
    CHECK(start_page > 0),
    CHECK(end_page >= start_page)
);

CREATE INDEX idx_book_chapters_book ON book_chapters(book_id);
CREATE INDEX idx_book_chapters_status ON book_chapters(book_id, status);
```

**State Machine Transitions:**

```
toc_defined ──[first page uploaded]──→ uploading
uploading ──[all pages uploaded]──→ upload_complete
upload_complete ──[start OCR job]──→ ocr_processing
ocr_processing ──[all OCR done]──→ ocr_complete
ocr_complete ──[start extraction job]──→ topic_extraction
topic_extraction ──[all chunks done]──→ finalizing
finalizing ──[consolidation done]──→ completed
Any state ──[unrecoverable error]──→ failed
```

### 4.4 `chapter_pages` Table (New)

```sql
CREATE TABLE chapter_pages (
    id VARCHAR PRIMARY KEY,                    -- UUID
    chapter_id VARCHAR NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
    book_id VARCHAR NOT NULL,                  -- Denormalized for queries
    page_number INTEGER NOT NULL,              -- Absolute page number in book
    chapter_page_index INTEGER NOT NULL,       -- 0-based index within chapter

    -- S3 keys
    raw_image_s3_key VARCHAR,                  -- books/{book_id}/chapters/ch_{N}/pages/raw/{page}.{ext}
    image_s3_key VARCHAR,                      -- books/{book_id}/chapters/ch_{N}/pages/{page}.png
    ocr_text_s3_key VARCHAR,                   -- books/{book_id}/chapters/ch_{N}/pages/{page}.txt

    -- Status tracking
    upload_status VARCHAR DEFAULT 'pending',   -- pending, uploaded, failed
    ocr_status VARCHAR DEFAULT 'pending',      -- pending, processing, completed, failed
    ocr_error TEXT,                            -- Error message if OCR failed

    -- Timestamps
    uploaded_at TIMESTAMP,
    ocr_completed_at TIMESTAMP,

    UNIQUE(chapter_id, page_number)
);

CREATE INDEX idx_chapter_pages_chapter ON chapter_pages(chapter_id);
CREATE INDEX idx_chapter_pages_ocr ON chapter_pages(chapter_id, ocr_status);
```

### 4.5 `chapter_processing_jobs` Table (New)

```sql
CREATE TABLE chapter_processing_jobs (
    id VARCHAR PRIMARY KEY,                    -- UUID
    chapter_id VARCHAR NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
    book_id VARCHAR NOT NULL,                  -- Denormalized

    job_type VARCHAR NOT NULL,                 -- 'ocr', 'topic_extraction', 'finalization'
    status VARCHAR NOT NULL DEFAULT 'pending', -- pending, running, completed, failed

    -- Progress
    total_items INTEGER,                       -- Total pages (OCR) or chunks (extraction)
    completed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    current_item VARCHAR,                      -- Current page/chunk being processed
    last_checkpoint VARCHAR,                   -- JSON: resume point (chunk index, state ref)

    -- Detail
    progress_detail TEXT,                      -- JSON: per-item errors, running stats

    -- Config snapshot (reproducibility)
    model_config_json TEXT,                    -- Model provider + ID used for this job
    prompt_version VARCHAR,                    -- Prompt template version

    -- Heartbeat for stale detection
    heartbeat_at TIMESTAMP,

    -- Timestamps
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    error_message TEXT,

    CONSTRAINT uq_chapter_active_job UNIQUE (chapter_id, job_type, status)
);

-- Partial index: at most one pending/running job per chapter+type
CREATE INDEX idx_chapter_jobs_active ON chapter_processing_jobs(chapter_id, job_type)
    WHERE status IN ('pending', 'running');
```

### 4.6 `chapter_topics` Table (New)

This is the **staging table** for finalized topics before they're synced to `teaching_guidelines`. It captures V2-specific context that doesn't belong in the tutor-facing table.

```sql
CREATE TABLE chapter_topics (
    id VARCHAR PRIMARY KEY,                    -- UUID
    chapter_id VARCHAR NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
    book_id VARCHAR NOT NULL,                  -- Denormalized

    -- Topic identity
    topic_key VARCHAR NOT NULL,                -- Slugified (e.g., "shapes-around-us")
    topic_title VARCHAR NOT NULL,              -- Human-readable (e.g., "Shapes Around Us")
    topic_summary TEXT,                        -- 15-30 word summary

    -- Teaching content
    guidelines TEXT NOT NULL,                  -- Full teaching guidelines (1000-3000 words)

    -- Source tracking
    source_page_start INTEGER,
    source_page_end INTEGER,
    contributing_chunks TEXT,                   -- JSON array: which chunk indices contributed

    -- Sequencing
    sequence_number INTEGER,                   -- Teaching order within chapter (1-based)

    -- Version tracking
    version INTEGER DEFAULT 1,

    -- Consolidation audit
    pre_consolidation_snapshot TEXT,            -- JSON: topic state before consolidation
    consolidation_actions Text,                -- JSON: merge/rename/dedup actions applied

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(chapter_id, topic_key)
);

CREATE INDEX idx_chapter_topics_chapter ON chapter_topics(chapter_id);
CREATE INDEX idx_chapter_topics_book ON chapter_topics(book_id);
```

### 4.7 `chunk_processing_log` Table (New)

Full audit trail for every chunk processed. This is write-heavy, read-rarely (debugging/audit only).

```sql
CREATE TABLE chunk_processing_log (
    id VARCHAR PRIMARY KEY,                    -- UUID
    job_id VARCHAR NOT NULL REFERENCES chapter_processing_jobs(id) ON DELETE CASCADE,
    chapter_id VARCHAR NOT NULL,               -- Denormalized
    book_id VARCHAR NOT NULL,                  -- Denormalized

    chunk_index INTEGER NOT NULL,              -- 0-based within chapter
    page_range VARCHAR NOT NULL,               -- e.g., "1-3", "4-6"

    -- S3 references (input/output stored in S3, not DB)
    input_s3_key VARCHAR,                      -- chunks/chunk_NNN_input.json
    output_s3_key VARCHAR,                     -- chunks/chunk_NNN_output.json
    state_s3_key VARCHAR,                      -- states/state_after_chunk_NNN.json

    -- Metrics
    processing_time_ms INTEGER,
    input_token_count INTEGER,
    output_token_count INTEGER,
    model_used VARCHAR,

    -- Topics detected in this chunk
    topics_detected TEXT,                      -- JSON: [{topic_key, is_new}]

    -- Status
    status VARCHAR DEFAULT 'pending',          -- pending, completed, failed
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_chunk_log_job ON chunk_processing_log(job_id);
CREATE INDEX idx_chunk_log_chapter ON chunk_processing_log(chapter_id, chunk_index);
```

### 4.8 `teaching_guidelines` Table (V2 Cleanup)

For V2 books, we write to the existing `teaching_guidelines` table with a cleaner field set. The V1 deprecated fields are ignored (NULL) for V2 rows.

```
V2 chapter_topics → teaching_guidelines mapping:
- chapter.chapter_title     → topic_title, topic (legacy), topic_key
- topic.topic_title         → subtopic_title, subtopic (legacy), subtopic_key
- topic.guidelines          → guideline
- topic.topic_summary       → subtopic_summary
- chapter.chapter_summary   → topic_summary
- chapter.sequence          → topic_sequence
- topic.sequence_number     → subtopic_sequence
- chapter.chapter_summary   → topic_storyline
- topic.source_page_start   → source_page_start
- topic.source_page_end     → source_page_end
- book.country/board/grade/subject → country, board, grade, subject
- book.id                   → book_id
```

V1 fields left NULL for V2 rows: `metadata_json`, `objectives_json`, `examples_json`, `misconceptions_json`, `assessments_json`, `teaching_description`, `description`, `evidence_summary`, `confidence`, `source_pages`.

### 4.9 Entity Relationship Diagram

```
books (extended with pipeline_version)
  │
  ├── 1:N → book_chapters
  │           │
  │           ├── 1:N → chapter_pages
  │           │
  │           ├── 1:N → chapter_processing_jobs
  │           │           │
  │           │           └── 1:N → chunk_processing_log
  │           │
  │           └── 1:N → chapter_topics
  │
  └── (via book_id) → teaching_guidelines  ←── DB sync from chapter_topics
                         │
                         └── 1:1 → study_plans
```

---

## 5. Pipeline Phases

### Phase 1: Book Creation + TOC Definition

**Trigger:** Admin creates a new V2 book.

**Steps:**
1. Admin enters book metadata (title, author, grade, subject, board, country)
2. System creates `books` row with `pipeline_version = 'v2'`
3. System creates S3 prefix: `books/{book_id}/metadata.json`
4. Admin enters TOC entries (chapter_number, chapter_title, start_page, end_page)
5. System validates:
   - No overlapping page ranges
   - All ranges are positive and bounded (start ≤ end)
   - Chapter numbers are sequential starting from 1
6. System creates `book_chapters` rows (status = `toc_defined`)
7. System saves `books/{book_id}/toc.json` to S3

**Validation Rules:**
```python
def validate_toc(chapters: list[TocEntry]) -> list[str]:
    errors = []
    # Sort by start_page for overlap detection
    sorted_chapters = sorted(chapters, key=lambda c: c.start_page)
    for i in range(len(sorted_chapters) - 1):
        if sorted_chapters[i].end_page >= sorted_chapters[i+1].start_page:
            errors.append(f"Chapter {sorted_chapters[i].chapter_number} overlaps with {sorted_chapters[i+1].chapter_number}")
    for ch in chapters:
        if ch.start_page < 1:
            errors.append(f"Chapter {ch.chapter_number}: start_page must be >= 1")
        if ch.end_page < ch.start_page:
            errors.append(f"Chapter {ch.chapter_number}: end_page must be >= start_page")
    return errors
```

**TOC Lock Policy:** Once the first page is uploaded to any chapter, the TOC is locked. To change page ranges, the admin must delete the chapter (which cascades to delete pages, jobs, and topics) and re-create it.

---

### Phase 2: Page Upload (per chapter)

**Trigger:** Admin selects a chapter and uploads page images.

**Steps:**
1. Validate page number is within chapter's [start_page, end_page] range
2. Save raw image to S3: `chapters/ch_{N}/pages/raw/{page_num}.{ext}`
3. Convert to PNG (if not already): `chapters/ch_{N}/pages/{page_num}.png`
4. Create/update `chapter_pages` row (upload_status = `uploaded`)
5. Increment `book_chapters.uploaded_pages`
6. If `uploaded_pages == total_pages`, transition chapter to `upload_complete`

**Bulk Upload:** Reuse V1's bulk upload pattern — stream raw files to S3 first (fast), then convert in background. Return immediately with page numbers.

**Duplicate Handling:** If page already uploaded, replace the image (overwrite S3 key, reset OCR status to pending).

---

### Phase 3: OCR Processing (per chapter)

**Trigger:** Admin clicks "Start OCR" on a chapter with status `upload_complete`.

**Precondition:** Chapter status is `upload_complete` (all pages present).

**Steps:**
1. Create `chapter_processing_jobs` row (job_type = `ocr`, status = `running`)
2. Transition chapter status to `ocr_processing`
3. Launch background thread
4. For each page in chapter (ordered by page_number):
   a. Read PNG from S3
   b. Call OpenAI Vision API for OCR (reuse `OCRService` from V1)
   c. Save OCR text to S3: `chapters/ch_{N}/pages/{page_num}.txt`
   d. Update `chapter_pages.ocr_status = 'completed'`
   e. Update job progress
   f. Update heartbeat
5. On completion: transition chapter to `ocr_complete`, mark job `completed`
6. On failure: mark page as `ocr_status = 'failed'`, continue with remaining pages

**Resume:** If job fails mid-way, next run skips pages where `ocr_status = 'completed'`.

---

### Phase 4: Topic Extraction (per chapter)

**Trigger:** Admin clicks "Extract Topics" on a chapter with status `ocr_complete`.

**Precondition:** Chapter status is `ocr_complete` (all pages OCR'd).

This is the core of V2. See [Section 6: Chunk Processing Deep Dive](#6-chunk-processing-deep-dive).

---

### Phase 5: Chapter Finalization

**Trigger:** Automatic after all chunks complete in Phase 4, OR admin triggers manually.

See [Section 7: Chapter Finalization Deep Dive](#7-chapter-finalization-deep-dive).

---

### Phase 6: Book-Level Sequencing

**Trigger:** After all chapters reach `completed` status (or admin triggers on subset).

**Steps:**
1. Collect all chapters with their topics
2. LLM orders chapters by pedagogical progression (may differ from textbook order)
3. LLM orders topics across the full book for curriculum flow
4. Update `chapter_topics.sequence_number` and chapter sequence

This mirrors V1's `PedagogicalSequencingService` but operates on the chapter→topic hierarchy.

---

### Phase 7: DB Sync + Study Plan Generation

See [Section 8: DB Sync & Tutor Integration](#8-db-sync--tutor-integration).

---

## 6. Chunk Processing Deep Dive

### 6.1 Chunk Formation

Given a chapter with pages [start_page ... end_page], form non-overlapping chunks of size 3:

```python
def form_chunks(start_page: int, end_page: int, chunk_size: int = 3) -> list[list[int]]:
    pages = list(range(start_page, end_page + 1))
    chunks = []
    for i in range(0, len(pages), chunk_size):
        chunks.append(pages[i:i + chunk_size])
    return chunks

# Example: pages 1-14 → [[1,2,3], [4,5,6], [7,8,9], [10,11,12], [13,14]]
```

The last chunk may have fewer than 3 pages. This is fine — the LLM handles variable-size input.

### 6.2 Running State Model

```python
class ChunkRunningState(BaseModel):
    """Accumulated state carried across chunks within a chapter."""
    chapter_summary_so_far: str = ""
    topic_guidelines_map_so_far: dict[str, TopicAccumulator] = {}

class TopicAccumulator(BaseModel):
    """Incrementally built topic within a chapter."""
    topic_key: str                    # Slugified
    topic_title: str                  # Human-readable
    guidelines: str                   # Accumulated guidelines text
    source_page_start: int
    source_page_end: int
    contributing_chunks: list[int]    # Which chunk indices contributed
```

### 6.3 Per-Chunk Processing Flow

For each chunk `[page_n, page_n+1, page_n+2]`:

```
Step 1: Build chunk input
  ├── Load OCR text for each page in chunk
  ├── Load previous page OCR text (page n-1) for continuity context
  ├── Load current running state (summary + topic map)
  └── Assemble into ChunkInput

Step 2: Save chunk input to S3 (audit trail)
  └── chunks/chunk_{NNN}_input.json

Step 3: Call LLM with chunk processing prompt
  ├── Input: page texts + previous page context + running state + chapter metadata
  ├── Output: JSON with topic updates + summary update
  └── Validate output against schema

Step 4: Save chunk output to S3 (audit trail)
  └── chunks/chunk_{NNN}_output.json

Step 5: Apply updates to running state
  ├── For each topic in LLM output:
  │   ├── If is_new: create new TopicAccumulator
  │   └── If existing: merge guidelines into existing TopicAccumulator
  ├── Update chapter_summary_so_far
  └── Record contributing_chunks

Step 6: Save state snapshot to S3 (resume point)
  └── states/state_after_chunk_{NNN}.json

Step 7: Update job progress in DB
  ├── chunk_processing_log row
  ├── chapter_processing_jobs.completed_items++
  └── chapter_processing_jobs.last_checkpoint = chunk_index

Step 8: Continue to next chunk
```

### 6.4 Guideline Merging Within Chunks

When a topic continues across chunks, the LLM produces `guidelines_for_chunk` — new content from the current pages. This must be merged with existing accumulated guidelines.

**Strategy: LLM-based merge** (reuse concept from V1's `GuidelineMergeService`):

```python
async def merge_topic_guidelines(
    existing_guidelines: str,
    new_chunk_guidelines: str,
    topic_title: str,
    chapter_context: str
) -> str:
    """Intelligently consolidate new chunk content into existing guidelines."""
    # LLM prompt: "Merge new teaching content into existing guidelines.
    # Avoid repetition. Preserve unique insights. Maintain flow."
    # Temperature: 0.3
    # Fallback: simple concatenation with separator
```

**Why not just concatenate?** Raw concatenation produces repetitive, poorly structured text. LLM merging deduplicates overlapping content and maintains natural prose flow. V1 proved this approach works well.

### 6.5 Resume Capability

If the extraction job fails at chunk N:

1. Next job run detects `last_checkpoint` in the failed job
2. Loads `states/state_after_chunk_{N-1}.json` from S3
3. Reconstructs `ChunkRunningState`
4. Continues from chunk N

This is why state snapshots are critical — they're the resume mechanism.

### 6.6 Chunk Processing Service Interface

```python
class ChunkProcessingService:
    """Processes a single chunk within a chapter."""

    async def process_chunk(
        self,
        chapter: BookChapter,
        chunk_pages: list[int],
        previous_page_text: str | None,
        running_state: ChunkRunningState,
        chunk_index: int,
        job_id: str,
    ) -> ChunkRunningState:
        """Process one chunk and return updated running state."""
        ...

class TopicExtractionOrchestrator:
    """Orchestrates chunk-by-chunk processing for a chapter."""

    async def extract_topics(
        self,
        chapter_id: str,
        resume: bool = False,
    ) -> None:
        """Process all chunks in a chapter sequentially."""
        # 1. Load chapter metadata
        # 2. Form chunks
        # 3. Load or initialize running state (resume support)
        # 4. For each chunk: call ChunkProcessingService
        # 5. After all chunks: trigger finalization
        ...
```

---

## 7. Chapter Finalization Deep Dive

### 7.1 Purpose

After all chunks are processed, the topic map contains "raw" topics accumulated page-by-page. Finalization polishes them into production-quality output.

### 7.2 Finalization Steps

```
Step 1: Snapshot pre-consolidation state
  └── Save all topics as-is to consolidation/pre_consolidation.json

Step 2: Topic deduplication
  ├── LLM analyzes all topic titles + guidelines previews
  ├── Identifies semantically overlapping pairs
  ├── For each pair: merge guidelines (LLM-based)
  ├── Delete the absorbed topic
  └── Record actions in consolidation/consolidation_actions.json

Step 3: Topic name refinement
  ├── For each remaining topic:
  │   ├── LLM reviews full guidelines text
  │   └── Suggests improved topic_title and topic_key
  ├── If name changes: update topic_key, save under new key
  └── Record renames

Step 4: Topic sequencing within chapter
  ├── LLM receives all topics with summaries
  ├── Determines pedagogical teaching order
  ├── Returns sequence_number for each topic
  └── Update chapter_topics.sequence_number

Step 5: Chapter summary generation
  ├── LLM receives all final topic summaries
  ├── Generates coherent chapter summary (50-100 words)
  └── Save to chapter_summary.txt and book_chapters.chapter_summary

Step 6: Chapter display name (optional)
  ├── LLM suggests a display_name based on actual chapter content
  ├── Stored alongside TOC title (advisory, not replacing)
  └── Save to book_chapters.display_name

Step 7: Topic summary generation
  ├── For each topic: generate 15-30 word summary
  └── Update chapter_topics.topic_summary

Step 8: Save final output
  ├── topics_index.json with all topics
  ├── Individual {topic_key}.json files
  └── post_consolidation.json (audit)

Step 9: Write to chapter_topics table
  ├── Upsert all finalized topics
  ├── Include consolidation audit data
  └── Transition chapter status to 'completed'
```

### 7.3 Reuse from V1

| V1 Service | V2 Usage |
|------------|----------|
| `TopicDeduplicationService` | Reuse concept + prompt; adapt input format |
| `TopicNameRefinementService` | Reuse concept + prompt; adapt for topics (not subtopics) |
| `PedagogicalSequencingService` | Reuse for within-chapter + across-book sequencing |
| `TopicSubtopicSummaryService` | Reuse for topic + chapter summary generation |
| `GuidelineMergeService` | Reuse for dedup merging |

---

## 8. DB Sync & Tutor Integration

### 8.1 Sync Flow: `chapter_topics` → `teaching_guidelines`

```python
class V2DBSyncService:
    """Sync V2 chapter topics to teaching_guidelines table."""

    async def sync_book(self, book_id: str) -> SyncResult:
        """Sync all completed chapters for a V2 book."""

        # 1. Load book metadata
        book = self.book_repo.get_book(book_id)

        # 2. Load all completed chapters + their topics
        chapters = self.chapter_repo.get_completed_chapters(book_id)

        # 3. Delete existing teaching_guidelines for this book
        #    (cascade deletes study_plans)
        self.guideline_repo.delete_by_book_id(book_id)

        # 4. Insert new guidelines from chapter_topics
        count = 0
        for chapter in chapters:
            topics = self.topic_repo.get_topics_by_chapter(chapter.id)
            for topic in topics:
                guideline = TeachingGuideline(
                    id=str(uuid4()),
                    country=book.country,
                    board=book.board,
                    grade=book.grade,
                    subject=book.subject,
                    book_id=book.id,

                    # V2 mapping: chapter → topic level, topic → subtopic level
                    topic=chapter.chapter_title,          # Legacy field
                    topic_title=chapter.chapter_title,
                    topic_key=slugify(chapter.chapter_title),
                    subtopic=topic.topic_title,           # Legacy field
                    subtopic_title=topic.topic_title,
                    subtopic_key=topic.topic_key,

                    guideline=topic.guidelines,

                    topic_summary=chapter.chapter_summary,
                    subtopic_summary=topic.topic_summary,
                    topic_sequence=chapter.chapter_number,  # Or pedagogical sequence
                    subtopic_sequence=topic.sequence_number,
                    topic_storyline=chapter.chapter_summary,

                    source_page_start=topic.source_page_start,
                    source_page_end=topic.source_page_end,

                    status='draft',
                    review_status='TO_BE_REVIEWED',
                    version=topic.version,
                )
                self.session.add(guideline)
                count += 1

        self.session.commit()
        return SyncResult(synced_count=count)
```

### 8.2 Study Plan Generation

After DB sync, reuse the existing `StudyPlanOrchestrator` to generate study plans for each new guideline. No changes needed — the orchestrator works off `teaching_guidelines` rows, which V2 populates in the same format.

```python
# After sync completes:
for guideline_id in synced_guideline_ids:
    await study_plan_orchestrator.generate_for_guideline(guideline_id)
```

### 8.3 Topic Adapter Compatibility

The existing `topic_adapter.py` works with V2 output because:
- `guideline.topic` → chapter title (used in topic_name display)
- `guideline.subtopic` → topic title (used in topic_name display)
- `guideline.guideline` → full teaching text (used as teaching_approach fallback)

**Required fix:** Update the fallback from `guideline.guideline[:500]` to use the full text:

```python
# Current (problematic):
teaching_approach = "\n".join(guideline.metadata.scaffolding_strategies or []) \
                    or guideline.guideline[:500]

# Updated:
teaching_approach = "\n".join(guideline.metadata.scaffolding_strategies or []) \
                    or guideline.guideline  # Full text, not truncated
```

### 8.4 Metadata JSON for V2

V2 can optionally produce `metadata_json` for richer tutor context. This is generated during finalization:

```json
{
  "learning_objectives": ["<extracted from guidelines>"],
  "depth_level": "intermediate",
  "prerequisites": ["<inferred from chapter context>"],
  "common_misconceptions": ["<extracted from guidelines>"],
  "scaffolding_strategies": []
}
```

This is a nice-to-have for V2 launch. The tutor has robust fallbacks when metadata is absent. We can add structured metadata extraction as a follow-up enhancement.

---

## 9. API Contracts

### 9.1 Book + TOC Management

```
POST /admin/v2/books
  Request:  { title, author, edition, country, board, grade, subject }
  Response: { book_id, s3_prefix, pipeline_version: "v2" }

POST /admin/v2/books/{book_id}/toc
  Request:  {
    chapters: [
      { chapter_number: 1, chapter_title: "...", start_page: 1, end_page: 14 },
      { chapter_number: 2, chapter_title: "...", start_page: 15, end_page: 30 }
    ]
  }
  Response: { book_id, chapters: [{ id, chapter_number, status: "toc_defined", total_pages }] }
  Errors:   400 if ranges overlap or invalid; 409 if TOC locked (pages exist)

GET /admin/v2/books/{book_id}/toc
  Response: { book_id, locked: true/false, chapters: [...] }

DELETE /admin/v2/books/{book_id}/toc/chapters/{chapter_number}
  Response: 204 (cascades: pages, jobs, topics)
  Errors:   409 if chapter is being processed (running job)
```

### 9.2 Page Upload

```
POST /admin/v2/books/{book_id}/chapters/{chapter_number}/pages
  Request:  multipart/form-data with images; each file named as page number
  Response: {
    chapter_id, uploaded_count, total_pages,
    pages: [{ page_number, upload_status, s3_key }],
    chapter_status: "uploading" | "upload_complete"
  }

GET /admin/v2/books/{book_id}/chapters/{chapter_number}/pages
  Response: {
    chapter_id, total_pages, uploaded_count,
    pages: [{ page_number, upload_status, ocr_status, uploaded_at }]
  }
```

### 9.3 Processing Jobs

```
POST /admin/v2/books/{book_id}/chapters/{chapter_number}/ocr
  Request:  {}  (or { resume: true } to resume failed job)
  Response: { job_id, status: "started", total_pages }
  Errors:   409 if already running; 400 if chapter not upload_complete

POST /admin/v2/books/{book_id}/chapters/{chapter_number}/extract-topics
  Request:  { resume: false }
  Response: { job_id, status: "started", total_chunks }
  Errors:   409 if already running; 400 if chapter not ocr_complete

POST /admin/v2/books/{book_id}/chapters/{chapter_number}/finalize
  Request:  {}
  Response: { job_id, status: "started" }

GET /admin/v2/books/{book_id}/chapters/{chapter_number}/jobs/latest
  Response: {
    job_id, job_type, status, total_items, completed_items,
    failed_items, current_item, started_at, completed_at,
    error_message
  }
```

### 9.4 Results & Review

```
GET /admin/v2/books/{book_id}/chapters/{chapter_number}/topics
  Response: {
    chapter_id, chapter_title, chapter_summary, status,
    topics: [
      {
        topic_key, topic_title, topic_summary,
        guidelines, source_page_start, source_page_end,
        sequence_number, version
      }
    ]
  }

GET /admin/v2/books/{book_id}/overview
  Response: {
    book_id, title, pipeline_version: "v2",
    chapters: [
      {
        chapter_number, chapter_title, status,
        total_pages, uploaded_pages, ocr_completed_pages,
        topic_count
      }
    ]
  }
```

### 9.5 Book-Level Operations

```
POST /admin/v2/books/{book_id}/sequence
  Request:  {}
  Response: { job_id, status: "started" }
  (Runs book-level sequencing across all completed chapters)

POST /admin/v2/books/{book_id}/sync
  Request:  { generate_study_plans: true }
  Response: {
    synced_count, study_plans_generated,
    guidelines_by_chapter: [{ chapter_title, topic_count }]
  }

POST /admin/v2/books/{book_id}/approve
  Request:  {}
  Response: { approved_count }
  (Sets review_status = 'APPROVED' on all synced teaching_guidelines)
```

---

## 10. Prompt Contracts

### 10.1 Chunk Topic Extraction Prompt

This is the core prompt — called once per chunk. Must produce structured JSON output.

**Input variables:**
- `chapter_title`: TOC chapter name
- `book_metadata`: grade, subject, board
- `previous_page_text`: Last page of previous chunk (for continuity)
- `page_texts`: Dict of page_number → OCR text for this chunk
- `chapter_summary_so_far`: Running chapter summary
- `topic_guidelines_map_so_far`: Current topic map (keys + titles + guidelines preview)

**Output schema:**
```json
{
  "topics": [
    {
      "topic_key": "string (kebab-case, slugified)",
      "topic_title": "string (human-readable)",
      "is_new": "boolean",
      "guidelines_for_chunk": "string (500-1500 words, teaching guidelines from these pages)",
      "page_range": "string (e.g., '1-3')"
    }
  ],
  "chapter_summary_update": "string (updated chapter summary incorporating these pages)"
}
```

**Prompt design principles:**
- Temperature: 0.2 (consistent topic detection)
- Include explicit topic granularity heuristics from PRD section 5.3
- For `is_new: false`, `topic_key` MUST match an existing key in the map
- Guidelines should cover: what's taught, how to teach it, examples, common errors, practice suggestions
- Chapter summary should be cumulative, not just about current pages

### 10.2 Guideline Merge Prompt

Called when a topic continues across chunks.

**Input:** existing guidelines + new chunk guidelines + topic context
**Output:** merged guidelines (deduplicated, coherent)
**Temperature:** 0.3

### 10.3 Topic Deduplication Prompt

Called during finalization. Identifies semantically overlapping topics.

**Input:** all topics with titles + guidelines previews (first 200 words each)
**Output:** list of merge pairs `[{keep: topic_key_1, absorb: topic_key_2, reason: "..."}]`
**Temperature:** 0.2

### 10.4 Topic Name Refinement Prompt

Called during finalization. Improves topic names based on full guidelines.

**Input:** topic_key, topic_title, full guidelines text
**Output:** `{refined_topic_key, refined_topic_title}`
**Temperature:** 0.3

### 10.5 Topic Sequencing Prompt

Called during finalization. Orders topics within a chapter.

**Input:** all topics with titles + summaries + page ranges
**Output:** `[{topic_key, sequence_number}]`
**Temperature:** 0.2

### 10.6 Chapter Summary Prompt

Called during finalization. Generates final chapter summary.

**Input:** chapter title + all topic summaries
**Output:** 50-100 word chapter summary
**Temperature:** 0.3

### 10.7 Model Configuration

Register a new component key in `llm_config`:

```
component_key: "book_ingestion_v2"
provider: configurable (default: "openai")
model_id: configurable (default: "gpt-4o")
```

All V2 prompts use this single config. No per-prompt model overrides (keep it simple).

---

## 11. Module & File Layout

### 11.1 Backend Package Structure

```
llm-backend/
├── book_ingestion_v2/                    # NEW: V2 pipeline package
│   ├── __init__.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py                     # All V2 admin endpoints
│   │   └── schemas.py                    # Request/response Pydantic models
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py                   # SQLAlchemy ORM: BookChapter, ChapterPage, etc.
│   │   ├── domain.py                     # Domain models: ChunkRunningState, TopicAccumulator, etc.
│   │   └── s3_models.py                  # S3 JSON schemas: TocJson, ChunkInput, ChunkOutput, etc.
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── chapter_repository.py         # CRUD for book_chapters
│   │   ├── chapter_page_repository.py    # CRUD for chapter_pages
│   │   ├── chapter_topic_repository.py   # CRUD for chapter_topics
│   │   ├── chapter_job_repository.py     # CRUD for chapter_processing_jobs
│   │   └── chunk_log_repository.py       # CRUD for chunk_processing_log
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── toc_service.py                # TOC validation, creation, locking
│   │   ├── page_upload_service.py        # Page upload, conversion, S3 storage
│   │   ├── ocr_service.py               # Chapter-level OCR orchestration
│   │   ├── chunk_processing_service.py   # Single chunk LLM processing
│   │   ├── guideline_merge_service.py    # LLM-based guideline merging
│   │   ├── topic_extraction_orchestrator.py  # Chapter-level chunk orchestration
│   │   ├── chapter_finalization_service.py   # Dedup, naming, sequencing, summaries
│   │   ├── book_sequencing_service.py    # Book-level topic/chapter ordering
│   │   ├── db_sync_service.py            # Sync chapter_topics → teaching_guidelines
│   │   ├── job_service.py                # Job lifecycle, heartbeat, progress
│   │   └── background_task_runner.py     # Thread-based background execution
│   │
│   ├── prompts/
│   │   ├── chunk_topic_extraction.txt
│   │   ├── guideline_merge.txt
│   │   ├── topic_deduplication.txt
│   │   ├── topic_name_refinement.txt
│   │   ├── topic_sequencing.txt
│   │   ├── chapter_sequencing.txt
│   │   └── chapter_summary.txt
│   │
│   └── utils/
│       ├── __init__.py
│       ├── s3_client.py                  # Reuse from V1 (import shared)
│       └── slugify.py                    # Topic key slugification
│
├── book_ingestion/                       # EXISTING: V1 pipeline (untouched)
│   └── ...
│
├── shared/
│   ├── models/
│   │   └── entities.py                   # Extended: add pipeline_version to Book
│   ├── repositories/
│   │   └── guideline_repository.py       # Existing: used by tutor (no changes)
│   └── utils/
│       └── s3_client.py                  # Existing: reused by V2
│
└── tutor/
    └── services/
        └── topic_adapter.py              # MODIFY: fix guideline[:500] truncation
```

### 11.2 Key Design Principles

- **V2 is a separate package** (`book_ingestion_v2/`), not modifications to V1
- **Shared code stays in `shared/`** (S3 client, entities, repositories)
- **V2 has its own repositories** — new tables, new query patterns
- **Prompts are text files** — easy to iterate without code changes
- **Single entry point** — `routes.py` registers all V2 endpoints

---

## 12. Reuse vs Redesign Inventory

### 12.1 Reuse As-Is

| Component | V1 Location | V2 Usage |
|-----------|-------------|----------|
| `S3Client` | `shared/utils/s3_client.py` | Direct import, no changes |
| `books` table | `book_ingestion/models/database.py` | Add `pipeline_version` column |
| `teaching_guidelines` table | `shared/models/entities.py` | Sync destination (same schema) |
| `study_plans` table | `shared/models/entities.py` | Generated from synced guidelines |
| `LLMConfig` system | `shared/models/entities.py` | New component key `book_ingestion_v2` |
| `BackgroundTaskRunner` pattern | `book_ingestion/services/background_task_runner.py` | Reuse execution pattern |
| `StudyPlanOrchestrator` | `study_plans/services/orchestrator.py` | Reuse for V2 topics |
| `GuidelineRepository` | `shared/repositories/guideline_repository.py` | Tutor reads from here (no changes) |

### 12.2 Reuse with Adaptation

| V1 Component | What to Reuse | What Changes |
|-------------- |-------------- |--------------|
| `OCRService` (OpenAI Vision) | OCR logic, API call, error handling | Called per-chapter batch instead of per-page |
| `PageService` (image conversion) | PNG conversion, S3 upload | Different S3 paths (chapter-based) |
| `GuidelineMergeService` | LLM merge concept + prompt structure | Input model changes (no SubtopicShard) |
| `TopicDeduplicationService` | Dedup concept + prompt structure | Input model changes (topics, not subtopics) |
| `TopicNameRefinementService` | Refinement concept + prompt | Input model changes |
| `PedagogicalSequencingService` | Sequencing concept + prompt | Two-level: within chapter + across book |
| `TopicSubtopicSummaryService` | Summary generation concept | Applied to chapters + topics |
| `JobLockService` | Concurrency control, heartbeat | New table, same pattern |
| `DBSyncService` | Sync concept + transaction pattern | Different source table (chapter_topics) |

### 12.3 Redesign (New)

| Component | Why New |
|-----------|---------|
| TOC management | New concept (V1 has no TOC) |
| Chapter state machine | New concept (V1 has book-level states) |
| Chunk processing pipeline | Fundamentally different from V1's page-by-page approach |
| Running state management | New concept (V1 uses context packs) |
| Per-chunk audit trail | New concept (V1 tracks per-page, not per-chunk) |
| Chapter finalization orchestrator | New orchestration order (V1 does book-level) |
| All new DB tables | New data model |
| All new API endpoints | New routes under `/admin/v2/` |

---

## 13. Migration Strategy

### 13.1 Database Migration

Single migration file that:

1. Adds `pipeline_version` column to `books` (default `'v1'`)
2. Creates `book_chapters` table
3. Creates `chapter_pages` table
4. Creates `chapter_processing_jobs` table
5. Creates `chapter_topics` table
6. Creates `chunk_processing_log` table
7. Adds `llm_config` row for `book_ingestion_v2`

**No data migration needed.** V1 books remain as-is. V2 is for new books only.

### 13.2 S3 Structure

V2 uses a different directory structure under `books/{book_id}/chapters/`. No migration of existing S3 data needed — V1 books use `books/{book_id}/guidelines/` which is a different path.

### 13.3 Feature Flag

V2 is available under `/admin/v2/books` routes. No feature flag needed at the backend level — the frontend controls which flow the admin sees. V1 routes remain at `/admin/books`.

---

## 14. Implementation Order

### Phase A: Foundation (Backend)

```
A1. Database migration (new tables + books.pipeline_version)
A2. ORM models (book_ingestion_v2/models/database.py)
A3. Domain models (ChunkRunningState, TopicAccumulator, S3 schemas)
A4. Repositories (all CRUD operations)
A5. TOC service (validation, creation, locking)
A6. Book creation API (POST /admin/v2/books, POST .../toc, GET .../toc)
```

### Phase B: Upload + OCR

```
B1. Page upload service (adapted from V1 PageService)
B2. Chapter OCR orchestration service
B3. Job service (lifecycle, heartbeat, progress)
B4. Background task runner (reuse V1 pattern)
B5. Upload + OCR API endpoints
B6. Job status polling endpoint
```

### Phase C: Core Pipeline

```
C1. Chunk processing service (LLM call + output validation)
C2. Chunk topic extraction prompt (design + test)
C3. Guideline merge service (adapted from V1)
C4. Guideline merge prompt
C5. Topic extraction orchestrator (chunk loop + state management + resume)
C6. Extraction API endpoint
```

### Phase D: Finalization

```
D1. Topic deduplication (adapted from V1)
D2. Topic name refinement (adapted from V1)
D3. Topic sequencing within chapter (adapted from V1)
D4. Chapter summary generation
D5. Topic summary generation
D6. Chapter finalization service (orchestrates D1-D5)
D7. Finalization API endpoint
```

### Phase E: Sync + Integration

```
E1. Book-level sequencing service
E2. DB sync service (chapter_topics → teaching_guidelines)
E3. Topic adapter fix (remove [:500] truncation)
E4. Study plan generation trigger (reuse existing)
E5. Book overview + approval endpoints
E6. Sequencing + sync + approve API endpoints
```

### Phase F: Frontend

```
F1. V2 book creation + TOC authoring UI
F2. Chapter page upload UI (with progress, missing-page indicators)
F3. Chapter processing UI (OCR + extraction progress bars)
F4. Chapter results preview UI (topics, summaries)
F5. Book overview dashboard (all chapters, statuses)
F6. Approval + sync controls
```

### Phase G: Quality & Polish

```
G1. Unit tests (services, repositories, domain models)
G2. Integration tests (full pipeline end-to-end)
G3. Prompt tuning (iterate on extraction quality with real books)
G4. Error handling hardening
G5. Logging + observability
```

---

## 15. Test Strategy

### 15.1 Unit Tests

| Component | Test Focus |
|-----------|------------|
| `TocService` | Validation rules (overlap, bounds, lock policy) |
| `ChunkProcessingService` | Output parsing, state update logic, merge logic |
| `TopicExtractionOrchestrator` | Chunk formation, resume logic, state snapshots |
| `ChapterFinalizationService` | Dedup decisions, sequencing, summary generation |
| `DBSyncService` | Mapping correctness (chapter_topics → teaching_guidelines) |
| `JobService` | State transitions, heartbeat, stale detection |
| Domain models | Serialization/deserialization, validation |
| Repositories | CRUD operations (use test DB) |

### 15.2 Integration Tests

| Scenario | What It Tests |
|----------|---------------|
| Happy path: 1 chapter, 6 pages, 2 topics | Full pipeline end-to-end |
| Resume: fail at chunk 2, resume | State restore, chunk skip, correct final output |
| Deduplication: 2 overlapping topics | Merge produces single coherent topic |
| Edge case: 1-page chapter | Single chunk, single topic |
| Edge case: 30-page chapter | 10 chunks, many topics, consolidation handles scale |
| DB sync: verify tutor contract | teaching_guidelines fields match expected values |
| Study plan: generated from V2 guideline | StudyPlanOrchestrator works with V2 data |

### 15.3 Prompt Quality Testing

Test with representative chapters from real books:
- Short chapter (5 pages): expect 2-4 topics
- Medium chapter (15 pages): expect 5-10 topics
- Long chapter (30+ pages): expect 8-15 topics

Evaluate:
- Topic coherence (each topic is a teachable 10-20 min unit)
- No duplicate topics post-consolidation
- Guidelines are comprehensive (1000+ words) and actionable
- Correct page attribution
- Chapter summary is accurate

---

## 16. Open Questions & Decisions

### 16.1 Resolved (Design Decisions Made)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | TOC flexibility after upload? | Locked after first upload. Delete chapter to change. | Simplicity; prevents inconsistent state |
| 2 | Page indexing source of truth? | Admin-entered absolute page numbers | Matches physical book; unambiguous |
| 3 | Chunk stride? | Non-overlapping with previous-page context | Simpler; context prevents boundary artifacts |
| 4 | Chapter rename policy? | Store both TOC title + AI display_name | Admin's title is authoritative; AI is advisory |
| 5 | Human approval gate? | Reuse TO_BE_REVIEWED → APPROVED workflow | Consistency with V1 |
| 8 | Backfill plan? | No backfill needed | User said no backward compatibility |

### 16.2 Remaining Open Questions

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 6 | Cross-page artifacts (diagrams/tables spanning chunks)? | (a) Note in prompt to handle gracefully (b) Overlap chunks by 1 page | (a) — keep non-overlapping; prompt instructs LLM to note "continued from previous page" artifacts |
| 7 | Multi-language support? | (a) Not in V2 (b) Language field in book metadata | (a) — not in scope per PRD non-goals |
| 9 | Should OCR + topic extraction be a single "process chapter" button? | (a) Separate buttons (b) Combined | (a) — separate gives admin control; OCR can be verified before extraction |
| 10 | Should we generate `metadata_json` for V2 guidelines? | (a) At launch (b) Follow-up | (b) — tutor has good fallbacks; extract structured metadata later |
| 11 | Chunk size configurable or fixed at 3? | (a) Fixed at 3 (b) Configurable per book | (a) — fixed; 3 is well-tested in PRD; avoid premature configurability |

---

*End of Technical Implementation Plan*
