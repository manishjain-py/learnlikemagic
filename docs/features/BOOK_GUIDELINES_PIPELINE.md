# Book Upload → Guidelines Generation Pipeline

---

## Document Purpose

**This is the Single Source of Truth (SSOT)** for the book upload and guidelines generation pipeline.

| Aspect | Details |
|--------|---------|
| **What it captures** | End-to-end workflow from book creation → page upload → OCR → guidelines generation → review → approval → database sync |
| **Audience** | New and existing developers needing complete context on this feature |
| **Scope** | Frontend components, backend services, API endpoints, data models, S3 storage, LLM calls |
| **Maintenance** | Update this doc whenever pipeline code changes to keep it accurate |

**Key Code Locations:**
- Frontend: `llm-frontend/src/features/admin/`
- Backend Book Ingestion: `llm-backend/features/book_ingestion/`
- Backend Guidelines Router: `llm-backend/routers/admin_guidelines.py`

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (React)                                  │
│   BooksDashboard → BookDetail → PageUploadPanel → GuidelinesPanel           │
│         │             ↳ BookStatusBadge (derived from counts)               │
│         └──────────→ GuidelinesReview (review/approve individual guidelines)│
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ REST API
┌─────────────────────────────────▼───────────────────────────────────────────┐
│                          BACKEND (FastAPI)                                   │
│   Routes: /admin/books/*, /admin/guidelines/*                               │
│                                                                              │
│   ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────────────┐   │
│   │ BookService │  │ PageService │  │ GuidelineExtractionOrchestrator  │   │
│   └─────────────┘  └─────────────┘  └──────────────────────────────────┘   │
│                                                                              │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │ DBSyncService (sync to teaching_guidelines) │ JobLockService       │   │
│   └────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────────┐
│   PostgreSQL: Book, BookJob, BookGuideline, TeachingGuideline │ S3: shards  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Pipeline Phases

| Phase | Action | Endpoint | Key Service |
|-------|--------|----------|-------------|
| 1 | Create Book | `POST /admin/books` | BookService |
| 2 | Upload Pages + OCR | `POST /admin/books/{id}/pages` | PageService + OCRService |
| 3 | Approve Pages | `PUT /admin/books/{id}/pages/{num}/approve` | PageService |
| 4 | Generate Guidelines | `POST /admin/books/{id}/generate-guidelines` | GuidelineExtractionOrchestrator |
| 5 | Refine & Consolidate | `POST /admin/books/{id}/finalize` | Orchestrator + Refinement Services |
| 6 | Approve & Sync to DB | `PUT /admin/books/{id}/guidelines/approve` | DBSyncService |
| 7 | Review Guidelines | `GET /admin/guidelines/review` | TeachingGuideline queries |
| 8 | Approve Individual | `POST /admin/guidelines/{id}/approve` | TeachingGuideline update |

---

## Phase 1-3: Book & Page Management

### Create Book
```
POST /admin/books → BookService.create_book()
  1. Generate book_id (slug: title-edition-year-grade-subject)
  2. Insert Book row in PostgreSQL
  3. Create S3: books/{book_id}/metadata.json
```

### Upload Page + OCR
```
POST /admin/books/{id}/pages → PageService.upload_page()
  1. Validate image (png/jpg/jpeg/tiff/webp, max 20MB)
  2. Convert to PNG, upload to S3: books/{id}/pages/{page_num:03d}.png
  3. OCR via OpenAI Vision (gpt-4o-mini):
     - Extracts: text, headings, diagrams, equations, labels
  4. Save OCR: books/{id}/pages/{page_num:03d}.ocr.txt
  5. Update metadata.json with page entry (status: "pending_review")
  6. Return: {page_num, image_url (presigned), ocr_text, status}
```

### Approve/Reject Page
```
PUT  .../pages/{num}/approve → Update metadata: status = "approved"
DELETE .../pages/{num}       → Delete S3 files, renumber remaining pages
```

### Get Page Details
```
GET /admin/books/{id}/pages/{num} → PageService.get_page_with_urls()
  Returns: {page_num, status, image_url, text_url, ocr_text}
```

**S3 Structure (Post-Upload):**
```
books/{book_id}/
  metadata.json                 # {pages: [{page_num, image_s3_key, text_s3_key, status}...]}
  pages/
    001.png, 001.ocr.txt        # Page image + OCR text
    002.png, 002.ocr.txt
    ...
```

---

## Phase 4: Guidelines Generation (V2 Pipeline)

### Entry Point
```
POST /admin/books/{id}/generate-guidelines
  Body: {start_page: 1, end_page: N, auto_sync_to_db: false}
  Handler: GuidelineExtractionOrchestrator.extract_guidelines_for_book()
```

### Per-Page Processing Loop

```python
for page_num in range(start_page, end_page + 1):
    orchestrator.process_page(book_id, page_num, book_metadata)
```

**`process_page()` Steps:**

| Step | Service | Description |
|------|---------|-------------|
| 1 | - | Load OCR text from `books/{id}/pages/{page_num:03d}.ocr.txt` |
| 2 | MinisummaryService | Generate 5-6 line summary (~60 words) via LLM |
| 3 | ContextPackService | Build context: 5 recent summaries + open topics with guidelines |
| 4 | BoundaryDetectionService | Detect boundary + extract guidelines (single LLM call) |
| 5 | GuidelineMergeService | If continuing: LLM-merge new guidelines into existing shard |
| 6 | - | Save shard to S3 |
| 7 | IndexManagementService | Update GuidelinesIndex + PageIndex |
| 8 | - | Save page guideline (minisummary) |
| 9 | - | Check stability (5-page threshold) |

### Boundary Detection (Core Logic)

```python
# BoundaryDetectionService.detect(context_pack, page_text)
# Model: gpt-4o-mini, temp=0.2, max_tokens=1000

Output (JSON):
  is_new_topic: bool      # True = new topic/subtopic, False = continue existing
  topic_name: str         # Slugified topic key
  subtopic_name: str      # Slugified subtopic key
  page_guidelines: str    # Extracted teaching content from this page
  reasoning: str          # Decision explanation
```

### Shard Creation vs Merge

```python
if is_new_topic:
    # CREATE new SubtopicShard
    shard = SubtopicShard(
        topic_key, topic_title, subtopic_key, subtopic_title,
        source_page_start=page_num, source_page_end=page_num,
        guidelines=page_guidelines, version=1
    )
else:
    # MERGE into existing shard
    existing_shard = load_shard(book_id, topic_key, subtopic_key)
    merged = GuidelineMergeService.merge(existing_shard.guidelines, page_guidelines)
    existing_shard.guidelines = merged
    existing_shard.source_page_end = page_num
    existing_shard.version += 1
```

### Stability Detection
A subtopic is marked "stable" when `current_page - shard.source_page_end >= 5` (no updates for 5 pages = content complete). Status tracked in index only, not in shard files.

**S3 Structure (Post-Generation):**
```
books/{book_id}/
  guidelines/
    index.json                              # GuidelinesIndex (status tracked here)
    page_index.json                         # PageIndex (page → topic/subtopic mapping)
    topics/
      {topic_key}/
        subtopics/
          {subtopic_key}.latest.json        # SubtopicShard (no status field)
  pages/
    001.page_guideline.json                 # {page, summary, version}
```

---

## Phase 5: Finalize & Consolidate

```
POST /admin/books/{id}/finalize
  Body: {auto_sync_to_db: false}
  Handler: GuidelineExtractionOrchestrator.finalize_book()
```

| Step | Service | Action |
|------|---------|--------|
| 1 | - | Mark all open/stable shards as "final" in index |
| 2 | TopicNameRefinementService | LLM refines topic/subtopic names (cleaner titles) |
| 3 | TopicDeduplicationService | LLM identifies duplicate subtopics |
| 4 | GuidelineMergeService | Merge duplicate shards, delete redundant |

---

## Phase 6: Approve & Database Sync

```
PUT /admin/books/{id}/guidelines/approve
  Handler: routes.py (inline logic)
```

**Steps:**
1. Set all non-final shards to "final" status (in index)
2. **Full snapshot sync**: Delete all existing `teaching_guidelines` rows for this book
3. Insert all shards as new rows with `review_status = "TO_BE_REVIEWED"`

```python
# DBSyncService.sync_shard() maps SubtopicShard → teaching_guidelines table
INSERT INTO teaching_guidelines (
    id, book_id, country, grade, subject, board,
    topic, subtopic,                      # Legacy columns (for backward compatibility)
    topic_key, subtopic_key,              # Slugified identifiers
    topic_title, subtopic_title,          # Human-readable names
    guideline,                            # Complete guidelines text
    source_page_start, source_page_end,
    status, review_status, version
)
```

---

## Phase 7-8: Guidelines Review Workflow

After sync to database, guidelines need individual review before becoming active.

### Review Endpoints (`/admin/guidelines/*`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/review` | GET | List all guidelines with filters (country, board, grade, subject, status) |
| `/review/filters` | GET | Get available filter options and counts |
| `/books/{book_id}/topics` | GET | Get topics/subtopics structure for a book |
| `/books/{book_id}/subtopics/{key}` | GET | Get full guideline details (requires `topic_key` query param) |
| `/books/{book_id}/page-assignments` | GET | Get page-to-subtopic assignments for a book |
| `/books/{book_id}/review` | GET | List guidelines for review (by book) |
| `/books/{book_id}/extract` | POST | Extract guidelines for specific page range |
| `/books/{book_id}/finalize` | POST | Finalize book guidelines |
| `/books/{book_id}/sync-to-database` | POST | Sync guidelines to DB (full snapshot) |
| `/{guideline_id}/approve` | POST | Approve or reject individual guideline |
| `/{guideline_id}` | DELETE | Delete individual guideline |
| `/books` | GET | List all books with guideline extraction status |

### Review Statuses
- `TO_BE_REVIEWED` - Default after sync, needs admin review
- `APPROVED` - Admin approved, available for tutor workflow

### Bulk Operations
- **Approve All**: Frontend iterates and calls `/approve` for each pending guideline

---

## Data Models

### SubtopicShard (V2)
```python
class SubtopicShard:
    topic_key: str              # "adding-like-fractions"
    topic_title: str            # "Adding Like Fractions"
    subtopic_key: str           # "same-denominator-addition"
    subtopic_title: str         # "Same Denominator Addition"
    source_page_start: int      # First page
    source_page_end: int        # Last page
    guidelines: str             # Single comprehensive text field
    version: int                # Increment on each update
    created_at, updated_at: str
    # NOTE: status field REMOVED - tracked only in index.json
```

### GuidelinesIndex
```python
class GuidelinesIndex:
    book_id: str
    topics: List[TopicIndexEntry]  # [{topic_key, topic_title, subtopics: [...]}]
    version: int
    last_updated: datetime

class SubtopicIndexEntry:
    subtopic_key, subtopic_title: str
    status: "open" | "stable" | "final" | "needs_review"  # Status tracked HERE only
    page_range: str             # "5-8"
```

### PageIndex
```python
class PageIndex:
    book_id: str
    pages: Dict[int, PageAssignment]  # Page number → assignment
    version: int
    last_updated: datetime

class PageAssignment:
    topic_key: str
    subtopic_key: str
    confidence: float           # 0.0-1.0
```

### ContextPack (LLM Input)
```python
class ContextPack:
    book_id: str
    current_page: int
    book_metadata: dict         # {grade, subject, board}
    recent_page_summaries: List # Last 5 page summaries
    open_topics: List           # Active topics with full guidelines text
    toc_hints: ToCHints         # Table of contents hints
```

### Database Tables

**Book** (`llm-backend/features/book_ingestion/models/database.py`)
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR | Primary key (slug) |
| title, author, edition | VARCHAR | Book metadata |
| country, board, grade, subject | VARCHAR/INT | Curriculum info |
| s3_prefix | VARCHAR | `books/{book_id}/` |
| metadata_s3_key | VARCHAR | `books/{book_id}/metadata.json` |
| created_at, updated_at | DATETIME | Timestamps |
| created_by | VARCHAR | Creator username |

**BookJob** (tracks active operations)
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR | Primary key |
| book_id | VARCHAR | FK to books |
| job_type | VARCHAR | extraction, finalization, sync |
| status | VARCHAR | running, completed, failed |
| started_at, completed_at | DATETIME | Timestamps |
| error_message | TEXT | Error details on failure |

**BookGuideline** (S3 guideline references for book status)
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR | Primary key |
| book_id | VARCHAR | FK to books |
| guideline_s3_key | VARCHAR | S3 path to guideline JSON |
| status | VARCHAR | draft, pending_review, approved, rejected |
| review_status | VARCHAR | TO_BE_REVIEWED, APPROVED |
| version | INT | Increment on regeneration |

**TeachingGuideline** (`llm-backend/models/database.py`) - Production guidelines for tutor
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR | Primary key |
| book_id | VARCHAR | Book reference |
| country, board, grade, subject | VARCHAR/INT | Curriculum filters |
| topic, subtopic | VARCHAR | Legacy names (display) - for backward compatibility |
| topic_key, subtopic_key | VARCHAR | Slugified identifiers (primary) |
| topic_title, subtopic_title | VARCHAR | Human-readable names |
| guideline | TEXT | Complete teaching guidelines |
| source_page_start/end | INT | Page range |
| status | VARCHAR | synced (default after sync) |
| review_status | VARCHAR | TO_BE_REVIEWED, APPROVED |
| version | INT | Tracks updates |

---

## LLM Calls Summary

| Service | Model | Purpose | Output |
|---------|-------|---------|--------|
| OCRService | gpt-4o-mini | Extract text from images | Full page text |
| MinisummaryService | gpt-4o-mini | Page summary | 5-6 lines (~60 words) |
| BoundaryDetectionService | gpt-4o-mini | Detect topic + extract guidelines | BoundaryDecision JSON |
| GuidelineMergeService | gpt-4o-mini | Merge page into shard | Merged guidelines text |
| TopicNameRefinementService | gpt-4o-mini | Polish names | Refined titles/keys |
| TopicDeduplicationService | gpt-4o-mini | Find duplicates | List of duplicate pairs |

---

## Key Files Reference

### Frontend (`llm-frontend/src/features/admin/`)
| File | Purpose |
|------|---------|
| `api/adminApi.ts` | All API client functions (books + guidelines review) |
| `types/index.ts` | TypeScript interfaces |
| `pages/BookDetail.tsx` | Book management hub |
| `pages/BooksDashboard.tsx` | Books list with filters |
| `pages/GuidelinesReview.tsx` | **Review/approve individual guidelines** |
| `components/PageUploadPanel.tsx` | Drag-drop upload + OCR review |
| `components/GuidelinesPanel.tsx` | Generate/approve/reject guidelines |
| `components/BookStatusBadge.tsx` | Status badge display |
| `utils/bookStatus.ts` | **Derived status logic** (no stored status) |

### Backend - Book Ingestion (`llm-backend/features/book_ingestion/`)
| File | Purpose |
|------|---------|
| `api/routes.py` | FastAPI endpoints for books/pages/guidelines |
| `services/book_service.py` | Book CRUD + status counts |
| `services/page_service.py` | Page upload, OCR, approval |
| `services/ocr_service.py` | OpenAI Vision API wrapper |
| `services/guideline_extraction_orchestrator.py` | Main pipeline coordinator |
| `services/boundary_detection_service.py` | Topic detection + guidelines extraction |
| `services/guideline_merge_service.py` | LLM-based guideline merging |
| `services/context_pack_service.py` | Build LLM context |
| `services/minisummary_service.py` | Page summaries |
| `services/index_management_service.py` | Index CRUD |
| `services/stability_detector_service.py` | Detect stable subtopics (5-page threshold) |
| `services/db_sync_service.py` | PostgreSQL sync |
| `services/topic_name_refinement_service.py` | Name polishing |
| `services/topic_deduplication_service.py` | Duplicate detection |
| `services/job_lock_service.py` | Job concurrency control |
| `models/guideline_models.py` | Pydantic models (SubtopicShard, Index, etc.) |
| `models/database.py` | SQLAlchemy ORM (Book, BookJob, BookGuideline) |
| `utils/s3_client.py` | S3 operations |

### Backend - Guidelines Review (`llm-backend/routers/admin_guidelines.py`)
| Endpoint | Purpose |
|----------|---------|
| `GET /books` | List all books with guideline extraction status |
| `GET /books/{id}/topics` | Get topic structure for book |
| `GET /books/{id}/subtopics/{key}` | Get full guideline details |
| `GET /books/{id}/page-assignments` | Get page-to-subtopic assignments |
| `GET /books/{id}/review` | List guidelines for review (by book) |
| `POST /books/{id}/extract` | Extract guidelines for page range |
| `POST /books/{id}/finalize` | Finalize book guidelines |
| `POST /books/{id}/sync-to-database` | Sync to DB (full snapshot) |
| `PUT /books/{id}/subtopics/{key}` | Update guideline (DISABLED for MVP) |
| `GET /review` | List all guidelines with filters |
| `GET /review/filters` | Get filter options + counts |
| `POST /{id}/approve` | Approve/reject guideline |
| `DELETE /{id}` | Delete guideline |

### Backend - Core Models (`llm-backend/models/database.py`)
| Model | Purpose |
|-------|---------|
| `TeachingGuideline` | Production guidelines for tutor workflow |

---

## V2 Design Decisions

1. **Single `guidelines` field** - Replaced structured fields (objectives, examples, misconceptions) with one comprehensive text field
2. **Status in Index only** - Shard files don't store status; only `index.json` tracks open/stable/final
3. **5-page stability threshold** - Subtopic marked stable after 5 pages without updates
4. **LLM-based merging** - Intelligent merge via GuidelineMergeService (not concatenation)
5. **Separate finalization** - Refine & Consolidate is distinct from generation
6. **Full DB snapshot** - Approve deletes all existing rows and re-inserts (clean slate)
7. **Derived book status** - Frontend computes status from counts (`page_count`, `guideline_count`, `approved_guideline_count`, `has_active_job`)
8. **Legacy column support** - `topic` and `subtopic` columns maintained for backward compatibility

---

## Workflow States (Derived)

Book status is **computed at runtime** from counts stored in BookService:

```typescript
// utils/bookStatus.ts - Frontend derives status from counts
type DisplayStatus = 'no_pages' | 'ready_for_extraction' | 'processing' | 'pending_review' | 'approved';

function getDisplayStatus(book: Book): DisplayStatus {
    if (book.has_active_job) return 'processing';
    if (book.page_count === 0) return 'no_pages';
    if (book.guideline_count === 0) return 'ready_for_extraction';
    if (book.approved_guideline_count === book.guideline_count && book.guideline_count > 0)
        return 'approved';
    return 'pending_review';
}
```

**Count Sources (BookService._to_book_response):**
- `page_count`: From S3 metadata.json pages array length
- `guideline_count`: From BookGuideline table count
- `approved_guideline_count`: From BookGuideline where review_status='APPROVED'
- `has_active_job`: From BookJob where status='running'

**State Transitions:**
```
NO_PAGES ──upload──▶ READY_FOR_EXTRACTION ──generate──▶ PROCESSING
       (page_count=0)    (guideline_count=0)         (has_active_job=true)
                                                              │
                                                           complete
                                                              │
                                                              ▼
                     ┌──────────────────────────────── PENDING_REVIEW
                     │                                        │
                  refine/reject                            approve
                     │                                        │
                     ▼                                        ▼
            READY_FOR_EXTRACTION                         APPROVED
                                                    (Synced to TeachingGuideline)
```

**Two-Level Review:**
1. **Book-level**: Approve all guidelines for a book → Sync to `teaching_guidelines` table
2. **Guideline-level**: Individual review via GuidelinesReview page → Set `review_status='APPROVED'`
