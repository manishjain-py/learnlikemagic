# Book & Guidelines — Technical

Pipeline architecture for book ingestion, OCR, guideline extraction, and study plan generation.

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend: BooksDashboard → BookDetail → PageUploadPanel            │
│            → GuidelinesPanel → GuidelinesReview                      │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ REST API
┌───────────────────────────────▼─────────────────────────────────────┐
│  Backend: BookService, PageService, GuidelineExtractionOrchestrator │
│           DBSyncService, JobLockService, StudyPlanOrchestrator      │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│  PostgreSQL: Book, BookJob, BookGuideline, TeachingGuideline        │
│  S3: books/{book_id}/ (pages, OCR text, guideline shards, index)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Phases

| Phase | Action | Endpoint | Key Service |
|-------|--------|----------|-------------|
| 1 | Create Book | `POST /admin/books` | BookService |
| 2 | Upload Pages + OCR | `POST /admin/books/{id}/pages` | PageService + OCRService |
| 3 | Approve Pages | `PUT /admin/books/{id}/pages/{num}/approve` | PageService |
| 4 | Generate Guidelines | `POST /admin/books/{id}/generate-guidelines` | GuidelineExtractionOrchestrator |
| 5 | Finalize | `POST /admin/books/{id}/finalize` | Orchestrator + Refinement |
| 6 | Approve & Sync to DB | `PUT /admin/books/{id}/guidelines/approve` | DBSyncService |
| 7 | Review Guidelines | `GET /admin/guidelines/review` | TeachingGuideline queries |
| 8 | Approve Individual | `POST /admin/guidelines/{id}/approve` | TeachingGuideline update |
| 9 | Generate Study Plans | `POST /admin/guidelines/{id}/generate-study-plan` | StudyPlanOrchestrator |

---

## Phase 1-3: Book & Page Management

### Create Book
```
POST /admin/books → BookService.create_book()
  1. Generate book_id (slug: author_subject_grade_year)
  2. Insert Book row in PostgreSQL
  3. Create S3: books/{book_id}/metadata.json
```

### Upload Page + OCR
```
POST /admin/books/{id}/pages → PageService.upload_page()
  1. Validate image (png/jpg/jpeg/tiff/webp, max 20MB)
  2. Convert to PNG, upload to S3
  3. OCR via OpenAI Vision (gpt-4o-mini)
  4. Save OCR text to S3
  5. Update metadata.json
```

### Page Operations
- `PUT .../pages/{num}/approve` — Set status to "approved"
- `DELETE .../pages/{num}` — Delete S3 files, renumber remaining
- `GET /admin/books/{id}/pages/{num}` — Get page with presigned URLs

---

## Phase 4: Guidelines Generation

### Per-Page Processing

```
POST /admin/books/{id}/generate-guidelines
  Body: {start_page, end_page, auto_sync_to_db: false}
```

For each page:

| Step | Service | Description |
|------|---------|-------------|
| 1 | - | Load OCR text from S3 |
| 2 | MinisummaryService | Generate 5-6 line summary (~60 words) |
| 3 | ContextPackService | Build context: 5 recent summaries + open topics |
| 4 | BoundaryDetectionService | Detect topic boundary + extract guidelines |
| 5 | GuidelineMergeService | If continuing: LLM-merge into existing shard |
| 6 | TopicSubtopicSummaryService | Generate subtopic summary (15-30 words) |
| 7 | - | Save shard to S3 |
| 8 | TopicSubtopicSummaryService | Generate topic summary (20-40 words) |
| 9 | IndexManagementService | Update GuidelinesIndex + PageIndex |

### Boundary Detection

```python
BoundaryDetectionService.detect(context_pack, page_text)
# Model: gpt-4o-mini, temp=0.2
# Output: {is_new_topic, topic_name, subtopic_name, page_guidelines, reasoning}
```

If `is_new_topic`: create new SubtopicShard. Otherwise: LLM-merge into existing shard.

### Stability

A subtopic is marked "stable" after 5 pages without updates. Status tracked in index only.

---

## Phase 5: Finalize

```
POST /admin/books/{id}/finalize
```

1. Mark all open/stable shards as "final" in index
2. TopicNameRefinementService — LLM refines topic/subtopic names
3. TopicDeduplicationService — LLM identifies duplicate subtopics
4. GuidelineMergeService — Merge duplicate shards
5. TopicSubtopicSummaryService — Regenerate all topic summaries

---

## Phase 6: Approve & DB Sync

```
PUT /admin/books/{id}/guidelines/approve
```

1. Set all non-final shards to "final"
2. **Full snapshot sync**: Delete all existing `teaching_guidelines` rows for this book
3. Insert all shards as new rows with `review_status = "TO_BE_REVIEWED"`

---

## Phase 7-8: Review Workflow

Two-level review:
1. **Book-level** — Approve all → sync to production DB
2. **Guideline-level** — Individual review via `/admin/guidelines`

Review statuses: `TO_BE_REVIEWED` (default), `APPROVED`. Rejecting sets back to `TO_BE_REVIEWED`.

---

## Phase 9: Study Plan Generation

```
POST /admin/guidelines/{id}/generate-study-plan
```

AI-to-AI review loop:
1. Generator creates initial study plan
2. Reviewer reviews and provides feedback
3. Improver refines based on feedback

Bulk: `POST /admin/guidelines/bulk-generate-study-plans`

---

## Data Models

### SubtopicShard

```python
class SubtopicShard:
    topic_key, topic_title: str
    subtopic_key, subtopic_title: str
    subtopic_summary: str           # 15-30 words
    source_page_start, source_page_end: int
    guidelines: str                 # Single comprehensive text field
    version: int
    # Status NOT stored here — tracked only in index.json
```

### GuidelinesIndex

```python
class GuidelinesIndex:
    book_id: str
    topics: List[TopicIndexEntry]   # [{topic_key, topic_title, topic_summary, subtopics}]

class SubtopicIndexEntry:
    subtopic_key, subtopic_title, subtopic_summary: str
    status: "open" | "stable" | "final" | "needs_review"
    page_range: str
```

### S3 Structure

```
books/{book_id}/
  metadata.json
  pages/
    001.png, 001.ocr.txt
  guidelines/
    index.json
    page_index.json
    topics/{topic_key}/subtopics/{subtopic_key}.latest.json
```

### Derived Book Status

Status computed at runtime from counts (no stored status field):

```
NO_PAGES → READY_FOR_EXTRACTION → PROCESSING → PENDING_REVIEW → APPROVED
```

Computed from: `page_count`, `guideline_count`, `approved_guideline_count`, `has_active_job`.

---

## LLM Calls

| Service | Model | Purpose |
|---------|-------|---------|
| OCRService | gpt-4o-mini | Extract text from images |
| MinisummaryService | gpt-4o-mini | Page summary |
| BoundaryDetectionService | gpt-4o-mini | Topic detection + guidelines extraction |
| GuidelineMergeService | gpt-4o-mini | Merge page into shard |
| TopicSubtopicSummaryService | gpt-4o-mini | Generate summaries |
| TopicNameRefinementService | gpt-4o-mini | Polish names |
| TopicDeduplicationService | gpt-4o-mini | Find duplicates |

---

## API Endpoints

### Book Management (`/admin/books/*`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/books` | Create book |
| `GET` | `/admin/books/{id}` | Get book details |
| `DELETE` | `/admin/books/{id}` | Delete book + S3 data |
| `POST` | `/admin/books/{id}/pages` | Upload page + OCR |
| `GET` | `/admin/books/{id}/pages/{num}` | Get page details |
| `PUT` | `/admin/books/{id}/pages/{num}/approve` | Approve page |
| `DELETE` | `/admin/books/{id}/pages/{num}` | Delete page |
| `POST` | `/admin/books/{id}/generate-guidelines` | Start extraction |
| `POST` | `/admin/books/{id}/finalize` | Finalize guidelines |
| `PUT` | `/admin/books/{id}/guidelines/approve` | Approve & sync to DB |

### Guidelines Management (`/admin/guidelines/*`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/review` | List guidelines with filters |
| `GET` | `/review/filters` | Filter options + counts |
| `GET` | `/books` | List books with extraction status |
| `GET` | `/books/{id}/topics` | Topic structure for book |
| `GET` | `/books/{id}/subtopics/{key}` | Full guideline details |
| `GET` | `/books/{id}/page-assignments` | Page-to-subtopic mapping |
| `GET` | `/books/{id}/review` | Guidelines for review by book |
| `POST` | `/books/{id}/extract` | Extract for page range |
| `POST` | `/books/{id}/finalize` | Finalize book |
| `POST` | `/books/{id}/sync-to-database` | Sync to DB |
| `POST` | `/{id}/approve` | Approve/reject guideline |
| `DELETE` | `/{id}` | Delete guideline |
| `POST` | `/{id}/generate-study-plan` | Generate study plan |
| `GET` | `/{id}/study-plan` | Get study plan |
| `POST` | `/bulk-generate-study-plans` | Bulk generate study plans |

---

## Key Files

### Frontend (`llm-frontend/src/features/admin/`)

| File | Purpose |
|------|---------|
| `api/adminApi.ts` | API client (books + guidelines + study plans) |
| `types/index.ts` | TypeScript interfaces |
| `pages/BooksDashboard.tsx` | Books list with filters |
| `pages/BookDetail.tsx` | Book management hub |
| `pages/CreateBook.tsx` | Book creation form |
| `pages/GuidelinesReview.tsx` | Individual guideline review |
| `components/PageUploadPanel.tsx` | Drag-drop upload + OCR review |
| `components/GuidelinesPanel.tsx` | Generate/approve/reject guidelines |
| `utils/bookStatus.ts` | Derived status logic |

### Backend — Book Ingestion (`llm-backend/book_ingestion/`)

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
| `services/db_sync_service.py` | PostgreSQL sync |
| `services/topic_name_refinement_service.py` | Name polishing |
| `services/topic_deduplication_service.py` | Duplicate detection |
| `services/topic_subtopic_summary_service.py` | Summary generation |
| `services/job_lock_service.py` | Job concurrency control |
| `models/guideline_models.py` | Pydantic models (SubtopicShard, Index, etc.) |
| `models/database.py` | SQLAlchemy ORM (Book, BookJob, BookGuideline) |
| `utils/s3_client.py` | S3 operations |

### Backend — Study Plans (`llm-backend/study_plans/`)

| File | Purpose |
|------|---------|
| `api/admin.py` | Guidelines review + study plan endpoints |
| `services/orchestrator.py` | AI-to-AI review loop for study plans |
