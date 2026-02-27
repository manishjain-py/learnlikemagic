# Technical Implementation Plan: Robust Book Processing Pipeline

**PRD:** `docs/feature-development/robust-book-processing/prd.md`
**Date:** 2026-02-27
**Status:** Draft

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Database Changes](#2-database-changes)
3. [Backend: Enhanced JobLockService](#3-backend-enhanced-joblockservice)
4. [Backend: Background Task Runner](#4-backend-background-task-runner)
5. [Backend: Background Guidelines Generation](#5-backend-background-guidelines-generation)
6. [Backend: Background Finalization](#6-backend-background-finalization)
7. [Backend: Resume from Failure](#7-backend-resume-from-failure)
8. [Backend: Job Status Polling Endpoints](#8-backend-job-status-polling-endpoints)
9. [Backend: Bulk Page Upload](#9-backend-bulk-page-upload)
10. [Backend: Background OCR Processor](#10-backend-background-ocr-processor)
11. [Backend: OCR Retry Endpoint](#11-backend-ocr-retry-endpoint)
12. [Frontend: Types & API Client](#12-frontend-types--api-client)
13. [Frontend: Guidelines Progress UI](#13-frontend-guidelines-progress-ui)
14. [Frontend: Bulk Upload UI](#14-frontend-bulk-upload-ui)
15. [Frontend: Pages Sidebar OCR Status](#15-frontend-pages-sidebar-ocr-status)
16. [API Contract Changes](#16-api-contract-changes)
17. [Migration Strategy](#17-migration-strategy)
18. [Implementation Order](#18-implementation-order)
19. [Risk & Open Questions](#19-risk--open-questions)

---

## 1. Architecture Overview

### Current Architecture (Problematic)

```
Admin clicks "Generate" → HTTP handler runs 100-page loop → Times out / drops on disconnect
Admin uploads page → Synchronous OCR → Wait → Approve → Repeat x100
```

### Target Architecture

```
Admin clicks "Generate"
  → HTTP handler creates BookJob row (fast)
  → Launches background thread
  → Returns job_id immediately
  → Background thread processes pages, updating BookJob.progress after each
  → Frontend polls GET /jobs/latest every 3s → shows progress bar
  → On failure: BookJob.last_completed_item enables resume

Admin bulk uploads 100 images
  → HTTP handler uploads all to S3 (fast, no OCR)
  → Creates OCR job, launches background thread
  → Returns job_id + page numbers immediately
  → Background thread runs OCR per page, updating metadata.json
  → Frontend polls job status → shows per-page OCR status
```

### Why Threading (Not Celery/SQS)

- App Runner keeps the container alive between requests (not Lambda)
- Single-tenant admin tool — no cross-instance task distribution needed
- `BookJob` table + `JobLockService` already exist for concurrency control
- Adding message queue infrastructure (Redis, SQS, Celery workers) is significant operational overhead for a tool used by one admin
- `daemon=True` threads die cleanly with the main process
- If the container restarts mid-job, the job stays `running` with `last_completed_item` set — admin can resume

---

## 2. Database Changes

### 2a. Enhance `BookJob` Model

**File:** `llm-backend/book_ingestion/models/database.py` (lines 65-85)

Add columns to the existing `BookJob` class:

```python
class BookJob(Base):
    __tablename__ = "book_jobs"

    id = Column(String, primary_key=True)
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    job_type = Column(String, nullable=False)     # extraction, finalization, ocr_batch
    status = Column(String, default='running')     # pending, running, completed, failed

    # NEW: Progress tracking
    total_items = Column(Integer, nullable=True)           # Total pages to process
    completed_items = Column(Integer, default=0)           # Pages completed so far
    failed_items = Column(Integer, default=0)              # Pages that errored
    current_item = Column(Integer, nullable=True)          # Page currently being processed
    last_completed_item = Column(Integer, nullable=True)   # Last successfully processed page (for resume)
    progress_detail = Column(Text, nullable=True)          # JSON: per-page errors + running stats

    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index('idx_book_running_job', 'book_id', 'status',
              postgresql_where=text("status = 'running'")),
    )
```

**`progress_detail` JSON structure:**
```json
{
  "page_errors": {
    "23": "OpenAI rate limit exceeded after 3 retries",
    "67": "OCR text was empty"
  },
  "stats": {
    "subtopics_created": 8,
    "subtopics_merged": 34
  }
}
```

### 2b. Database Migration

**File:** `llm-backend/db.py`

Add `_apply_book_job_columns(db_manager)` function, called from `migrate()`:

```python
def _apply_book_job_columns(db_manager):
    """Add progress tracking columns to book_jobs table if they don't exist."""
    inspector = inspect(db_manager.engine)

    if "book_jobs" not in inspector.get_table_names():
        return  # Table doesn't exist yet, create_all will handle it

    existing_columns = {col["name"] for col in inspector.get_columns("book_jobs")}

    with db_manager.engine.connect() as conn:
        new_columns = {
            "total_items": "INTEGER",
            "completed_items": "INTEGER DEFAULT 0",
            "failed_items": "INTEGER DEFAULT 0",
            "current_item": "INTEGER",
            "last_completed_item": "INTEGER",
            "progress_detail": "TEXT",
        }
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE book_jobs ADD COLUMN {col_name} {col_type}"))

        conn.commit()
```

Call it from `migrate()` alongside existing migration functions.

---

## 3. Backend: Enhanced JobLockService

**File:** `llm-backend/book_ingestion/services/job_lock_service.py`

Add methods to the existing `JobLockService` class:

```python
def update_progress(
    self,
    job_id: str,
    current_item: int,
    completed: int,
    failed: int = 0,
    last_completed_item: Optional[int] = None,
    detail: Optional[str] = None
):
    """
    Update job progress. Called after each page.
    Uses a fresh query to avoid stale session issues in background threads.
    """
    job = self.db.query(BookJob).filter(BookJob.id == job_id).first()
    if job:
        job.current_item = current_item
        job.completed_items = completed
        job.failed_items = failed
        if last_completed_item is not None:
            job.last_completed_item = last_completed_item
        if detail is not None:
            job.progress_detail = detail
        self.db.commit()

def get_job(self, job_id: str) -> Optional[dict]:
    """Return job as dict with all progress fields."""
    job = self.db.query(BookJob).filter(BookJob.id == job_id).first()
    if not job:
        return None
    return {
        "job_id": job.id,
        "book_id": job.book_id,
        "job_type": job.job_type,
        "status": job.status,
        "total_items": job.total_items,
        "completed_items": job.completed_items,
        "failed_items": job.failed_items,
        "current_item": job.current_item,
        "last_completed_item": job.last_completed_item,
        "progress_detail": job.progress_detail,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }

def get_active_job(self, book_id: str) -> Optional[dict]:
    """Get currently running job for a book."""
    job = self.db.query(BookJob).filter(
        BookJob.book_id == book_id,
        BookJob.status == 'running'
    ).first()
    return self.get_job(job.id) if job else None

def get_latest_job(self, book_id: str, job_type: Optional[str] = None) -> Optional[dict]:
    """Get most recent job for a book, optionally filtered by type."""
    query = self.db.query(BookJob).filter(BookJob.book_id == book_id)
    if job_type:
        query = query.filter(BookJob.job_type == job_type)
    job = query.order_by(BookJob.started_at.desc()).first()
    return self.get_job(job.id) if job else None
```

Also update `acquire_lock` to accept `total_items`:

```python
def acquire_lock(self, book_id: str, job_type: str, total_items: int = None) -> str:
    # ... existing check for running job ...
    job = BookJob(
        id=job_id,
        book_id=book_id,
        job_type=job_type,
        status='running',
        total_items=total_items,  # NEW
    )
    # ... rest unchanged ...
```

---

## 4. Backend: Background Task Runner

**File:** `llm-backend/book_ingestion/services/background_task_runner.py` (NEW)

```python
"""
Background task runner using Python threads.

Uses independent DB sessions for background work to avoid
session lifecycle issues with the request-scoped session.
"""
import logging
import threading
from database import get_db_manager

logger = logging.getLogger(__name__)


def run_in_background(target_fn, *args, **kwargs):
    """
    Run a function in a background thread with its own DB session.

    The target function receives db_session as its first argument.
    The session is automatically closed when the function completes.

    Args:
        target_fn: Function to run. Signature: (db_session, *args, **kwargs)
        *args, **kwargs: Additional arguments passed to target_fn

    Returns:
        threading.Thread instance
    """
    def wrapper():
        db_manager = get_db_manager()
        session = db_manager.SessionLocal()
        try:
            target_fn(session, *args, **kwargs)
        except Exception as e:
            logger.error(f"Background task failed: {e}", exc_info=True)
        finally:
            session.close()

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    logger.info(f"Launched background task: {target_fn.__name__}")
    return thread
```

**Key decisions:**
- `daemon=True`: Thread dies if the main process dies (clean shutdown)
- Independent DB session: Avoids SQLAlchemy session lifecycle issues between the request thread and background thread
- The function signature convention `(db_session, *args, **kwargs)` makes it clear that the background task gets its own session

---

## 5. Backend: Background Guidelines Generation

### 5a. New Background Extraction Function

**File:** `llm-backend/book_ingestion/services/guideline_extraction_orchestrator.py`

Add a new top-level function (not a method on the orchestrator class) that:
1. Creates the orchestrator with its own dependencies
2. Processes pages one by one
3. Updates job progress after each page
4. Handles completion and failure

```python
def run_extraction_background(
    db_session: Session,
    job_id: str,
    book_id: str,
    book_metadata: dict,
    start_page: int,
    end_page: int,
    model: str,
):
    """
    Background task: extract guidelines for a range of pages.
    Called by background_task_runner with its own DB session.
    """
    from .job_lock_service import JobLockService
    import json

    job_lock = JobLockService(db_session)
    s3_client = S3Client()
    openai_client = OpenAI()

    orchestrator = GuidelineExtractionOrchestrator(
        s3_client=s3_client,
        openai_client=openai_client,
        db_session=db_session,
        model=model,
    )

    completed = 0
    failed = 0
    page_errors = {}
    stats = {"subtopics_created": 0, "subtopics_merged": 0}

    try:
        for page_num in range(start_page, end_page + 1):
            # Update: currently processing this page
            job_lock.update_progress(
                job_id,
                current_item=page_num,
                completed=completed,
                failed=failed,
                detail=json.dumps({"page_errors": page_errors, "stats": stats}),
            )

            try:
                page_result = orchestrator.process_page(
                    book_id=book_id,
                    page_num=page_num,
                    book_metadata=book_metadata,
                )

                completed += 1
                if page_result.get("is_new_topic"):
                    stats["subtopics_created"] += 1
                else:
                    stats["subtopics_merged"] += 1

                # Check stability
                orchestrator._check_and_mark_stable_subtopics(
                    book_id=book_id,
                    current_page=page_num,
                )

            except Exception as e:
                failed += 1
                page_errors[str(page_num)] = str(e)
                logger.error(f"Page {page_num} failed: {e}")

            # Update progress (including last_completed_item for resume)
            job_lock.update_progress(
                job_id,
                current_item=page_num,
                completed=completed,
                failed=failed,
                last_completed_item=page_num if page_errors.get(str(page_num)) is None else None,
                detail=json.dumps({"page_errors": page_errors, "stats": stats}),
            )

        # All pages processed — mark complete
        job_lock.release_lock(
            job_id,
            status='completed',
            error=None if not page_errors else f"{len(page_errors)} pages had errors",
        )

    except Exception as e:
        # Catastrophic failure — mark failed with last progress
        logger.error(f"Extraction job {job_id} failed catastrophically: {e}", exc_info=True)
        job_lock.release_lock(job_id, status='failed', error=str(e))
```

**Important note on `process_page`:** The existing `process_page` method is `async`. Since we're running in a thread (not an async event loop), we need to either:
- Option A: Make `process_page` synchronous (it only calls synchronous OpenAI SDK methods anyway — the `async` is superficial)
- Option B: Run it with `asyncio.run(orchestrator.process_page(...))`

**Recommended: Option A** — audit `process_page` and its callees. The OpenAI SDK calls are all synchronous. The `async` on `extract_guidelines_for_book` and `process_page` appears to be there for FastAPI compatibility but doesn't actually use `await` on I/O operations. Remove `async` from these methods and the thread can call them directly. This is cleaner than wrapping with `asyncio.run()`.

### 5b. Update `generate-guidelines` Endpoint

**File:** `llm-backend/book_ingestion/api/routes.py` (lines 382-476)

Replace the current synchronous implementation:

```python
@router.post("/books/{book_id}/generate-guidelines")
def generate_guidelines(
    book_id: str,
    request: GenerateGuidelinesRequest,
    db: Session = Depends(get_db)
):
    """
    Start guideline generation as a background job.
    Returns immediately with job_id. Poll GET /jobs/latest for progress.
    """
    # Validate book exists (fast)
    book_service = BookService(db)
    book = book_service.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

    # Load total_pages from S3 metadata
    s3_client = S3Client()
    try:
        metadata = s3_client.download_json(f"books/{book_id}/metadata.json")
        total_pages = metadata.get("total_pages", 0)
    except Exception:
        total_pages = 0

    if total_pages == 0:
        raise HTTPException(status_code=400, detail="No pages uploaded for this book")

    start_page = request.start_page or 1
    end_page = request.end_page or total_pages

    # Handle resume
    if request.resume:
        job_lock_svc = JobLockService(db)
        latest = job_lock_svc.get_latest_job(book_id, job_type="extraction")
        if latest and latest["last_completed_item"]:
            start_page = latest["last_completed_item"] + 1
            if start_page > end_page:
                return {"job_id": None, "status": "already_complete",
                        "message": "All pages already processed"}

    total_to_process = end_page - start_page + 1

    # Acquire job lock (409 if already running)
    job_lock_svc = JobLockService(db)
    try:
        job_id = job_lock_svc.acquire_lock(
            book_id, job_type="extraction", total_items=total_to_process
        )
    except JobLockError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Read model config
    from shared.services.llm_config_service import LLMConfigService
    ingestion_config = LLMConfigService(db).get_config("book_ingestion")

    book_metadata = {
        "grade": book.grade,
        "subject": book.subject,
        "board": book.board,
        "total_pages": total_pages,
    }

    # Launch background task
    from .services.background_task_runner import run_in_background
    from .services.guideline_extraction_orchestrator import run_extraction_background

    run_in_background(
        run_extraction_background,
        job_id=job_id,
        book_id=book_id,
        book_metadata=book_metadata,
        start_page=start_page,
        end_page=end_page,
        model=ingestion_config["model_id"],
    )

    return {
        "job_id": job_id,
        "status": "started",
        "start_page": start_page,
        "end_page": end_page,
        "total_pages": total_to_process,
        "message": f"Guideline generation started for pages {start_page}-{end_page}",
    }
```

**Updated request model:**

```python
class GenerateGuidelinesRequest(BaseModel):
    start_page: Optional[int] = 1
    end_page: Optional[int] = None
    auto_sync_to_db: bool = False
    resume: bool = False  # NEW: auto-resume from last failure point
```

---

## 6. Backend: Background Finalization

**File:** `llm-backend/book_ingestion/api/routes.py` (lines 494-575)

Same pattern as guidelines generation. Create a `run_finalization_background` function and update the endpoint to return immediately with a job_id.

The finalization pipeline has fewer steps (mark final → refine names → deduplicate → merge), so the progress tracking uses subtopics as items rather than pages. The `total_items` is the number of subtopics, and `completed_items` increments as each subtopic is processed.

---

## 7. Backend: Resume from Failure

### 7a. Resume Logic

Already shown in section 5b. When `request.resume == True`:

1. Load the latest `extraction` job for this book via `job_lock_svc.get_latest_job(book_id, "extraction")`
2. Read `last_completed_item` — this is the last page that successfully completed
3. Set `start_page = last_completed_item + 1`
4. Create a new job starting from there

### 7b. Why This Works

The guideline extraction pipeline is **idempotent per-page** in the forward direction:
- Each page's result is saved to S3 (shard files, page_guideline files, indices) before moving to the next page
- If processing stops at page 50, pages 1-49 have their artifacts safely in S3
- When processing resumes at page 50, the context pack service loads the existing index and shards from S3, so the new page gets the right context
- The only edge case: if page 50 partially wrote (e.g., shard saved but index not updated). The orchestrator handles this by treating "shard exists but not in index" gracefully

### 7c. `last_completed_item` Tracking

After each successful page, the background function updates `last_completed_item`. If a page fails (per-page exception caught), it's recorded in `page_errors` but `last_completed_item` stays at the previous page. If the entire process crashes, the DB has the last known good page.

---

## 8. Backend: Job Status Polling Endpoints

**File:** `llm-backend/book_ingestion/api/routes.py`

### 8a. Get Latest Job

```python
class JobStatusResponse(BaseModel):
    job_id: str
    book_id: str
    job_type: str
    status: str  # pending, running, completed, failed
    total_items: Optional[int] = None
    completed_items: int = 0
    failed_items: int = 0
    current_item: Optional[int] = None
    last_completed_item: Optional[int] = None
    progress_detail: Optional[str] = None  # JSON string
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


@router.get("/books/{book_id}/jobs/latest", response_model=Optional[JobStatusResponse])
def get_latest_job(
    book_id: str,
    job_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get the latest job for a book. Used by frontend to:
    - Detect if a job is running when page loads
    - Poll for progress during active jobs
    - Show failure details for resume
    """
    job_lock = JobLockService(db)
    result = job_lock.get_latest_job(book_id, job_type)
    if not result:
        return None
    return JobStatusResponse(**result)


@router.get("/books/{book_id}/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    book_id: str,
    job_id: str,
    db: Session = Depends(get_db)
):
    """Get specific job status."""
    job_lock = JobLockService(db)
    result = job_lock.get_job(job_id)
    if not result or result["book_id"] != book_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(**result)
```

---

## 9. Backend: Bulk Page Upload

### 9a. Enhanced Metadata Schema

**File:** `llm-backend/book_ingestion/services/page_service.py`

Page entries in `metadata.json` gain an `ocr_status` field:

```python
page_info = {
    "page_num": page_num,
    "image_s3_key": image_s3_key,
    "text_s3_key": None,         # Set after OCR completes
    "status": "pending_review",
    "ocr_status": "pending",     # NEW: "pending" | "processing" | "completed" | "failed"
    "ocr_error": None,           # NEW: error message if OCR failed
    "uploaded_at": datetime.utcnow().isoformat(),
}
```

For backward compatibility, pages uploaded via the existing single-page endpoint (which does inline OCR) will have `ocr_status: "completed"` set immediately.

### 9b. Bulk Upload Endpoint

**File:** `llm-backend/book_ingestion/api/routes.py`

```python
from fastapi import UploadFile, File
from typing import List


class BulkUploadResponse(BaseModel):
    job_id: str
    pages_uploaded: List[int]
    total_pages: int
    status: str
    message: str


@router.post("/books/{book_id}/pages/bulk", response_model=BulkUploadResponse)
async def bulk_upload_pages(
    book_id: str,
    images: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload multiple page images at once.
    Images are uploaded to S3 immediately (fast).
    OCR runs in the background.
    """
    # Validate book exists
    book_service = BookService(db)
    book = book_service.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

    if not images:
        raise HTTPException(status_code=400, detail="No images provided")

    # Validate all images first (fail fast)
    page_service = PageService(db)
    for img in images:
        page_service._validate_image_metadata(img.filename, img.size)

    # Read all image data
    image_data_list = []
    for img in images:
        data = await img.read()
        page_service._validate_image(data, img.filename)
        image_data_list.append((data, img.filename))

    # Upload all images to S3 (fast, no OCR)
    page_numbers = page_service.bulk_upload_images(book_id, image_data_list)

    # Acquire OCR job lock
    job_lock = JobLockService(db)
    try:
        job_id = job_lock.acquire_lock(
            book_id, job_type="ocr_batch", total_items=len(page_numbers)
        )
    except JobLockError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Launch background OCR
    from .services.background_task_runner import run_in_background
    run_in_background(
        page_service.run_bulk_ocr_background,
        job_id=job_id,
        book_id=book_id,
        page_numbers=page_numbers,
    )

    return BulkUploadResponse(
        job_id=job_id,
        pages_uploaded=page_numbers,
        total_pages=len(page_numbers),
        status="ocr_processing",
        message=f"Uploaded {len(page_numbers)} pages. OCR processing in background.",
    )
```

### 9c. PageService Bulk Upload Method

**File:** `llm-backend/book_ingestion/services/page_service.py`

```python
def bulk_upload_images(
    self,
    book_id: str,
    image_data_list: List[tuple],  # [(bytes, filename), ...]
) -> List[int]:
    """
    Upload multiple images to S3 without running OCR.
    Returns list of assigned page numbers.
    """
    metadata = self._load_metadata(book_id)
    page_numbers = []

    for image_data, filename in image_data_list:
        page_num = self._get_next_page_number(metadata)
        image_s3_key = f"books/{book_id}/{page_num}.png"

        # Convert to PNG
        image_bytes = self._convert_to_png(image_data)

        # Upload to S3
        self.s3_client.upload_bytes(image_bytes, image_s3_key, content_type="image/png")

        # Add to metadata with ocr_status: pending
        page_info = {
            "page_num": page_num,
            "image_s3_key": image_s3_key,
            "text_s3_key": None,
            "status": "pending_review",
            "ocr_status": "pending",
            "ocr_error": None,
            "uploaded_at": datetime.utcnow().isoformat(),
        }
        metadata["pages"].append(page_info)
        metadata["total_pages"] = len(metadata["pages"])
        page_numbers.append(page_num)

    # Save metadata once after all uploads
    metadata["last_updated"] = datetime.utcnow().isoformat()
    self.s3_client.update_metadata_json(book_id, metadata)

    return page_numbers
```

---

## 10. Backend: Background OCR Processor

**File:** `llm-backend/book_ingestion/services/page_service.py`

```python
@staticmethod
def run_bulk_ocr_background(
    db_session: Session,
    job_id: str,
    book_id: str,
    page_numbers: List[int],
):
    """
    Background task: run OCR on multiple pages.
    Updates job progress and per-page ocr_status after each page.
    """
    from .job_lock_service import JobLockService
    from .ocr_service import get_ocr_service
    from shared.services.llm_config_service import LLMConfigService

    job_lock = JobLockService(db_session)
    ingestion_config = LLMConfigService(db_session).get_config("book_ingestion")
    ocr_service = get_ocr_service(model=ingestion_config["model_id"])
    s3_client = get_s3_client()

    completed = 0
    failed = 0
    page_errors = {}

    try:
        for page_num in page_numbers:
            # Update: processing this page
            job_lock.update_progress(
                job_id, current_item=page_num,
                completed=completed, failed=failed,
            )

            # Update metadata: ocr_status = "processing"
            _update_page_ocr_status(s3_client, book_id, page_num, "processing")

            try:
                # Load image from S3
                image_s3_key = f"books/{book_id}/{page_num}.png"
                image_bytes = s3_client.download_bytes(image_s3_key)

                # Run OCR
                ocr_text = ocr_service.extract_text_with_retry(image_bytes=image_bytes)

                # Save OCR text to S3
                text_s3_key = f"books/{book_id}/{page_num}.txt"
                s3_client.upload_bytes(
                    ocr_text.encode('utf-8'), text_s3_key, content_type="text/plain"
                )

                # Update metadata: ocr_status = "completed"
                _update_page_ocr_status(
                    s3_client, book_id, page_num, "completed",
                    text_s3_key=text_s3_key
                )
                completed += 1

            except Exception as e:
                failed += 1
                page_errors[str(page_num)] = str(e)
                _update_page_ocr_status(
                    s3_client, book_id, page_num, "failed",
                    ocr_error=str(e)
                )
                logger.error(f"OCR failed for page {page_num}: {e}")

            # Update job progress
            job_lock.update_progress(
                job_id, current_item=page_num,
                completed=completed, failed=failed,
                last_completed_item=page_num,
                detail=json.dumps({"page_errors": page_errors}),
            )

        job_lock.release_lock(job_id, status='completed')

    except Exception as e:
        logger.error(f"Bulk OCR job {job_id} failed: {e}", exc_info=True)
        job_lock.release_lock(job_id, status='failed', error=str(e))


def _update_page_ocr_status(
    s3_client, book_id: str, page_num: int,
    ocr_status: str, text_s3_key: str = None, ocr_error: str = None
):
    """Update a single page's ocr_status in metadata.json."""
    metadata_key = f"books/{book_id}/metadata.json"
    metadata = s3_client.download_json(metadata_key)

    for page in metadata["pages"]:
        if page["page_num"] == page_num:
            page["ocr_status"] = ocr_status
            if text_s3_key:
                page["text_s3_key"] = text_s3_key
            if ocr_error:
                page["ocr_error"] = ocr_error
            elif ocr_status != "failed":
                page["ocr_error"] = None
            break

    metadata["last_updated"] = datetime.utcnow().isoformat()
    s3_client.update_metadata_json(book_id, metadata)
```

**Concurrency note on metadata.json:** Since only one job runs per book (enforced by `JobLockService`), there's no concurrent write contention on `metadata.json`. The single-page upload endpoint could theoretically conflict, but in practice admins won't be single-uploading while a bulk OCR job is running.

---

## 11. Backend: OCR Retry Endpoint

**File:** `llm-backend/book_ingestion/api/routes.py`

```python
@router.post("/books/{book_id}/pages/{page_num}/retry-ocr")
def retry_page_ocr(
    book_id: str,
    page_num: int,
    db: Session = Depends(get_db)
):
    """
    Retry OCR for a single page that previously failed.
    Runs synchronously since it's a single page (~10s).
    """
    service = PageService(db)
    # Verify page exists and has an uploaded image
    # Load image from S3 → run OCR → save text → update metadata
    # Return { page_num, ocr_status: "completed", ocr_text: "..." }
```

This runs synchronously since it's a single page (~10 seconds). No need for background processing.

---

## 12. Frontend: Types & API Client

### 12a. New Types

**File:** `llm-frontend/src/features/admin/types/index.ts`

Add after existing types:

```typescript
// ===== Job Status Types =====

export interface JobStatus {
  job_id: string;
  book_id: string;
  job_type: 'extraction' | 'finalization' | 'ocr_batch';
  status: 'pending' | 'running' | 'completed' | 'failed';
  total_items: number | null;
  completed_items: number;
  failed_items: number;
  current_item: number | null;
  last_completed_item: number | null;
  progress_detail: string | null;  // JSON string
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface JobProgressDetail {
  page_errors: Record<string, string>;  // page_num → error message
  stats?: {
    subtopics_created: number;
    subtopics_merged: number;
  };
}

export interface BulkUploadResponse {
  job_id: string;
  pages_uploaded: number[];
  total_pages: number;
  status: string;
  message: string;
}

// ===== Enhanced PageInfo with OCR status =====

export interface PageInfo {
  page_num: number;
  image_s3_key: string;
  text_s3_key: string | null;
  status: 'pending_review' | 'approved';
  approved_at: string | null;
  ocr_status?: 'pending' | 'processing' | 'completed' | 'failed';  // NEW
  ocr_error?: string | null;  // NEW
}
```

Update `GenerateGuidelinesRequest`:

```typescript
export interface GenerateGuidelinesRequest {
  start_page?: number;
  end_page?: number;
  auto_sync_to_db?: boolean;
  resume?: boolean;  // NEW
}
```

Update `GenerateGuidelinesResponse` (endpoint now returns job info instead of final stats):

```typescript
export interface GenerateGuidelinesStartResponse {
  job_id: string;
  status: string;
  start_page: number;
  end_page: number;
  total_pages: number;
  message: string;
}
```

### 12b. New API Functions

**File:** `llm-frontend/src/features/admin/api/adminApi.ts`

```typescript
// ===== Job Status =====

export async function getLatestJob(
  bookId: string,
  jobType?: string
): Promise<JobStatus | null> {
  const params = jobType ? `?job_type=${jobType}` : '';
  return apiFetch<JobStatus | null>(`/admin/books/${bookId}/jobs/latest${params}`);
}

export async function getJobStatus(
  bookId: string,
  jobId: string
): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/admin/books/${bookId}/jobs/${jobId}`);
}

// ===== Bulk Upload =====

export async function bulkUploadPages(
  bookId: string,
  imageFiles: File[]
): Promise<BulkUploadResponse> {
  const formData = new FormData();
  imageFiles.forEach(file => {
    formData.append('images', file);
  });

  const response = await fetch(`${API_BASE_URL}/admin/books/${bookId}/pages/bulk`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ===== OCR Retry =====

export async function retryPageOcr(
  bookId: string,
  pageNum: number
): Promise<{ page_num: number; ocr_status: string }> {
  return apiFetch(`/admin/books/${bookId}/pages/${pageNum}/retry-ocr`, {
    method: 'POST',
  });
}
```

Update existing `generateGuidelines` to return the new response type:

```typescript
export async function generateGuidelines(
  bookId: string,
  request: GenerateGuidelinesRequest
): Promise<GenerateGuidelinesStartResponse> {
  return apiFetch<GenerateGuidelinesStartResponse>(
    `/admin/books/${bookId}/generate-guidelines`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}
```

---

## 13. Frontend: Guidelines Progress UI

### 13a. Polling Hook

**File:** `llm-frontend/src/features/admin/hooks/useJobPolling.ts` (NEW)

```typescript
import { useState, useEffect, useRef, useCallback } from 'react';
import { getLatestJob, getJobStatus } from '../api/adminApi';
import { JobStatus } from '../types';

const POLL_INTERVAL_MS = 3000;

export function useJobPolling(bookId: string, jobType?: string) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startPolling = useCallback((jobId?: string) => {
    setIsPolling(true);

    intervalRef.current = setInterval(async () => {
      try {
        const result = jobId
          ? await getJobStatus(bookId, jobId)
          : await getLatestJob(bookId, jobType);

        setJob(result);

        // Stop polling when job completes or fails
        if (result && (result.status === 'completed' || result.status === 'failed')) {
          setIsPolling(false);
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch {
        // Silently handle polling errors
      }
    }, POLL_INTERVAL_MS);
  }, [bookId, jobType]);

  const stopPolling = useCallback(() => {
    setIsPolling(false);
    if (intervalRef.current) clearInterval(intervalRef.current);
  }, []);

  // Check for active job on mount
  useEffect(() => {
    const checkActiveJob = async () => {
      const result = await getLatestJob(bookId, jobType);
      if (result && result.status === 'running') {
        setJob(result);
        startPolling(result.job_id);
      } else {
        setJob(result);
      }
    };
    checkActiveJob();

    return () => stopPolling();
  }, [bookId, jobType]);

  return { job, isPolling, startPolling, stopPolling, setJob };
}
```

### 13b. GuidelinesPanel Changes

**File:** `llm-frontend/src/features/admin/components/GuidelinesPanel.tsx`

**Key changes:**

1. **Import and use `useJobPolling`:**
   ```typescript
   const { job: extractionJob, isPolling, startPolling } = useJobPolling(bookId, 'extraction');
   ```

2. **Modify `handleGenerateGuidelines`:**
   - Call API → get `{ job_id, status: "started" }`
   - Start polling: `startPolling(result.job_id)`
   - No longer `await` the entire operation

3. **Add progress bar component** (shown when `isPolling` or `extractionJob?.status === 'running'`):
   ```
   ████████████████░░░░  78/100 pages (78%)
   Currently processing: Page 79
   Subtopics found: 14 | Failed: 1
   Elapsed: 12m 34s
   ⚠ You can leave this page — processing continues in the background.
   ```

4. **Add failure + resume UI** (shown when `extractionJob?.status === 'failed'`):
   ```
   ⚠ Generation stopped at page 78/100
   Error: [error_message]
   [Resume from Page 78]  [Restart from Page 1]
   ```

5. **On completion** (shown when `extractionJob?.status === 'completed'`):
   - Parse `progress_detail` JSON for stats
   - Show existing generation stats UI
   - Reload guidelines list

6. **On page load with running job:**
   - The `useJobPolling` hook auto-detects running jobs on mount
   - Progress bar appears immediately if a job is running
   - Admin can leave and return — progress is shown

**Progress bar component:**

```typescript
const JobProgressBar: React.FC<{ job: JobStatus }> = ({ job }) => {
  const total = job.total_items || 1;
  const done = job.completed_items;
  const pct = Math.round((done / total) * 100);
  const detail: JobProgressDetail | null = job.progress_detail
    ? JSON.parse(job.progress_detail)
    : null;

  return (
    <div style={{ padding: '16px', backgroundColor: '#EFF6FF', borderRadius: '8px', border: '1px solid #BFDBFE' }}>
      {/* Progress bar */}
      <div style={{ height: '8px', backgroundColor: '#DBEAFE', borderRadius: '4px', overflow: 'hidden', marginBottom: '12px' }}>
        <div style={{ height: '100%', width: `${pct}%`, backgroundColor: '#3B82F6', borderRadius: '4px', transition: 'width 0.3s' }} />
      </div>

      {/* Stats */}
      <div style={{ fontSize: '14px', color: '#1E40AF', fontWeight: '600', marginBottom: '4px' }}>
        {done}/{total} pages ({pct}%)
      </div>
      {job.current_item && (
        <div style={{ fontSize: '13px', color: '#6B7280' }}>
          Currently processing: Page {job.current_item}
        </div>
      )}
      {detail?.stats && (
        <div style={{ fontSize: '13px', color: '#6B7280', marginTop: '4px' }}>
          Subtopics: {detail.stats.subtopics_created} created, {detail.stats.subtopics_merged} merged
        </div>
      )}
      {job.failed_items > 0 && (
        <div style={{ fontSize: '13px', color: '#DC2626', marginTop: '4px' }}>
          {job.failed_items} page(s) had errors
        </div>
      )}

      <div style={{ fontSize: '12px', color: '#9CA3AF', marginTop: '8px', fontStyle: 'italic' }}>
        You can leave this page — processing continues in the background.
      </div>
    </div>
  );
};
```

---

## 14. Frontend: Bulk Upload UI

### 14a. PageUploadPanel Changes

**File:** `llm-frontend/src/features/admin/components/PageUploadPanel.tsx`

**Two modes** in the same component:

1. **Bulk upload** (new default): Multi-file select or drag-drop
2. **Single upload** (existing): Preserved for individual corrections

**Key changes:**

1. **Multi-file input:**
   ```html
   <input type="file" accept="image/*" multiple onChange={handleFilesSelect} />
   ```

2. **Drag-and-drop for multiple files:**
   - `onDrop` handler collects `e.dataTransfer.files` (multiple)

3. **Bulk upload flow:**
   - Show file count: "Selected: 85 images"
   - "Upload All & Start OCR" button
   - Call `bulkUploadPages(bookId, files)` → get `{ job_id, pages_uploaded }`
   - Start polling for OCR job progress
   - Show OCR progress bar + per-page status list

4. **Per-page OCR status list:**
   ```typescript
   {pages.map(page => (
     <div key={page.page_num}>
       Page {page.page_num}
       {page.ocr_status === 'completed' && '✅ OCR Complete'}
       {page.ocr_status === 'processing' && '⏳ Processing...'}
       {page.ocr_status === 'failed' && (
         <>❌ Failed <button onClick={() => retryPageOcr(bookId, page.page_num)}>Retry</button></>
       )}
       {page.ocr_status === 'pending' && '⬜ Pending'}
     </div>
   ))}
   ```

5. **Single-page mode** accessible via "Upload single page" link below the bulk upload area.

---

## 15. Frontend: Pages Sidebar OCR Status

**File:** `llm-frontend/src/features/admin/components/PagesSidebar.tsx`

Add OCR status indicators to each page entry:
- Pages with `ocr_status: "completed"` → green check icon
- Pages with `ocr_status: "processing"` → spinner/pulse animation
- Pages with `ocr_status: "failed"` → red X with retry action
- Pages with `ocr_status: "pending"` → gray circle

The sidebar already shows pages — this change adds visual status indicators and a retry action for failed pages.

---

## 16. API Contract Changes

### New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/books/{book_id}/jobs/latest` | Get latest job (poll for progress) |
| GET | `/admin/books/{book_id}/jobs/{job_id}` | Get specific job status |
| POST | `/admin/books/{book_id}/pages/bulk` | Bulk upload images |
| POST | `/admin/books/{book_id}/pages/{page_num}/retry-ocr` | Retry failed OCR |

### Modified Endpoints

| Method | Path | Change |
|--------|------|--------|
| POST | `/admin/books/{book_id}/generate-guidelines` | Returns immediately with `{ job_id }` instead of blocking. Accepts `resume: bool`. |
| POST | `/admin/books/{book_id}/finalize` | Returns immediately with `{ job_id }` instead of blocking. |

### Backward Compatibility

The `generate-guidelines` and `finalize` endpoints change from synchronous to async response. The frontend must be updated simultaneously — there is no backward-compatible way to do this since the response shape changes from final-stats to job-started.

**Deploy strategy:** Backend and frontend deploy together. This is already the pattern for this project.

---

## 17. Migration Strategy

### Database

1. Run `python db.py --migrate` — this adds the new columns to `book_jobs` via `_apply_book_job_columns()`
2. Existing `book_jobs` rows (if any) get `NULL` for new columns — this is fine, they're historical records
3. No data migration needed — new columns are all nullable or have defaults

### S3 Metadata

Pages uploaded via the existing single-page endpoint won't have `ocr_status` in their metadata entry. The frontend and backend should treat missing `ocr_status` as `"completed"` (since OCR was already done inline during upload).

### Frontend

The `PageInfo` type adds `ocr_status` and `ocr_error` as optional fields. Existing pages without these fields render normally.

---

## 18. Implementation Order

### Phase 1: Backend Foundation (Enables Everything Else)

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 1 | Add columns to `BookJob` model | `database.py` | — |
| 2 | Add migration function | `db.py` | Step 1 |
| 3 | Enhance `JobLockService` with progress methods | `job_lock_service.py` | Step 1 |
| 4 | Create `background_task_runner.py` | `background_task_runner.py` (new) | — |
| 5 | Add job status polling endpoints | `routes.py` | Step 3 |

### Phase 2: Background Guidelines Generation + Resume

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 6 | Create `run_extraction_background` function | `guideline_extraction_orchestrator.py` | Steps 3-4 |
| 7 | Make `process_page` synchronous (remove superficial async) | `guideline_extraction_orchestrator.py` | — |
| 8 | Refactor generate-guidelines endpoint to async | `routes.py` | Steps 5-6 |
| 9 | Add `resume` support to request | `routes.py` | Step 8 |
| 10 | Refactor finalize endpoint to async | `routes.py` | Steps 4-5 |

### Phase 3: Bulk Upload + Background OCR

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 11 | Add `ocr_status` to metadata page schema | `page_service.py` | — |
| 12 | Add `bulk_upload_images` method | `page_service.py` | Step 11 |
| 13 | Add `run_bulk_ocr_background` method | `page_service.py` | Steps 3-4, 11 |
| 14 | Add bulk upload endpoint | `routes.py` | Steps 12-13 |
| 15 | Add retry-ocr endpoint | `routes.py` | Step 11 |

### Phase 4: Frontend

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 16 | Add TypeScript types | `types/index.ts` | — |
| 17 | Add API client functions | `adminApi.ts` | Step 16 |
| 18 | Create `useJobPolling` hook | `hooks/useJobPolling.ts` (new) | Step 17 |
| 19 | Update GuidelinesPanel with progress + resume | `GuidelinesPanel.tsx` | Steps 17-18 |
| 20 | Update PageUploadPanel with bulk upload | `PageUploadPanel.tsx` | Steps 17-18 |
| 21 | Update PagesSidebar with OCR status | `PagesSidebar.tsx` | Step 16 |

---

## 19. Risk & Open Questions

### Risks

| Risk | Mitigation |
|------|------------|
| **Background thread dies if container restarts** | Job stays in `running` state with `last_completed_item`. Admin sees stale "running" job. Need a mechanism to detect stale jobs (e.g., `started_at` > 2 hours ago + no progress update). Frontend can show "This job may have been interrupted — Resume?" |
| **metadata.json concurrent writes** | `JobLockService` ensures only one job per book. Single-page upload during bulk OCR could conflict. Mitigate: check for running `ocr_batch` job and return 409 from single-page upload. |
| **S3 consistency for page_index.json during resume** | `page_index.json` tracks page→subtopic mapping. If a page was partially processed (shard saved but index not updated), resume may create a duplicate shard. Mitigate: the orchestrator already handles "shard exists but not in index" gracefully. |
| **OpenAI rate limits during bulk OCR** | OCR processes pages sequentially (not parallel), which helps. The existing retry logic (3 attempts) also helps. For persistent rate limits, pages fail individually and can be retried later. |

### Open Questions

| Question | Options |
|----------|---------|
| **Stale job detection** | Option A: Background thread writes a heartbeat timestamp to `BookJob`. Frontend considers a job stale if heartbeat > 60s ago. Option B: Simpler — if `started_at` > 2 hours ago and status is still `running`, treat as stale. **Recommendation: Option B** for simplicity. |
| **Auto-approve bulk uploaded pages?** | Currently, each page must be manually approved after OCR. For bulk upload, should pages be auto-approved? **Recommendation: No** — keep the review step. But add a "Approve All" button that approves all pages with `ocr_status: "completed"` in one click. |
| **Max bulk upload size?** | Should there be a limit on number of files per bulk upload? **Recommendation: 200 pages max** (covers most textbooks). This prevents request size issues. |
| **Sort order for bulk upload images** | When admin selects 100 files, what page order? **Recommendation: Sort by filename alphabetically** (e.g., `page_001.jpg`, `page_002.jpg`). This is the most intuitive and matches how scanners typically name files. |
