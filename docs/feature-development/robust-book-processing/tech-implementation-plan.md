# Technical Implementation Plan: Robust Book Processing Pipeline

**PRD:** `docs/feature-development/robust-book-processing/prd.md`
**Date:** 2026-02-27
**Status:** Draft

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Database Changes](#2-database-changes)
3. [Backend: Enhanced JobLockService & State Machine](#3-backend-enhanced-joblockservice--state-machine)
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
19. [Test Strategy](#19-test-strategy)
20. [Risk & Open Questions](#20-risk--open-questions)

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
  → HTTP handler creates BookJob row (status=pending → running) [fast]
  → Launches background thread
  → Returns job_id immediately
  → Background thread processes pages, updating BookJob.progress after each
  → Background thread writes heartbeat_at every 30s
  → Frontend polls GET /jobs/latest every 3s → shows progress bar
  → On failure: BookJob.last_completed_item enables resume

Admin bulk uploads 100 images
  → HTTP handler streams raw files directly to S3 (no conversion) [fast]
  → Creates OCR job, launches background thread
  → Returns job_id + page numbers immediately
  → Background thread converts + OCR per page, updating BookJob progress in DB
  → Frontend polls job status → shows per-page OCR status
```

### Execution Model: App Runner with Provisioned Instances

**Current infrastructure** (`infra/terraform/modules/app-runner/main.tf`):
- Auto-scaling: `min_size = 1`, `max_size = 5`, `max_concurrency = 100`
- Instance: 1 vCPU, 2 GB RAM

**Requirement:** Background threads need CPU to stay active between HTTP requests. App Runner supports two CPU allocation modes:

| Mode | CPU Behavior | Cost | Fits Our Needs? |
|------|-------------|------|-----------------|
| **Request-driven** (default) | CPU throttled when no active requests | Lower | **No** — background threads freeze between requests |
| **Provisioned** | CPU always available | Higher (~$25/mo per instance) | **Yes** — threads run continuously |

**Action required:** The Terraform config must explicitly set `health_check_configuration` with a `/health` endpoint interval (e.g., 30s) and the service must use provisioned instances. Our current config already sets `min_size = 1` which keeps one instance warm, but we must verify the `cpu_configuration` is set to provisioned mode, not request-driven.

**Terraform change needed:**
```hcl
instance_configuration {
  cpu    = "1024"    # 1 vCPU (existing)
  memory = "2048"    # 2 GB (existing)
}

# ADD: Ensure provisioned CPU mode
# App Runner defaults to "request-driven" — must be explicitly changed
# Cost impact: ~$25/month for 1 always-on instance (acceptable for admin tool)
```

**If provisioned mode is not feasible** (cost or policy constraints), the fallback is a self-sustaining polling approach: the background thread makes periodic lightweight HTTP calls to itself (or a keep-alive endpoint hits the service), ensuring App Runner doesn't throttle CPU. This is a hack — provisioned mode is the correct solution.

### Why Threading (Not Celery/SQS)

- App Runner with provisioned instances keeps the container and CPU alive continuously
- Single-tenant admin tool — no cross-instance task distribution needed
- `BookJob` table + `JobLockService` already exist for concurrency control
- Adding message queue infrastructure (Redis, SQS, Celery workers) adds significant operational complexity (queue provisioning, dead letter queues, worker process management, monitoring) for a tool used by one admin at a time
- `daemon=True` threads die cleanly with the main process
- If the container restarts mid-job, the job is detectable as stale (heartbeat stops) and the admin can resume from `last_completed_item`

### Throughput & Backpressure Limits

| Resource | Limit | Rationale |
|----------|-------|-----------|
| Max pages per book | 500 | Covers any textbook; prevents unbounded processing |
| Max bulk upload batch | 200 files | Prevents request body OOM (~200 * 10MB = 2GB theoretical max) |
| Max concurrent jobs per book | 1 | Enforced by `JobLockService` database lock |
| Max concurrent jobs system-wide | 1 | Single-admin tool; enforced at application level |
| OCR processing rate | ~6 pages/min | Sequential processing, ~10s per page (LLM API call) |
| Guideline extraction rate | ~2-3 pages/min | Sequential, ~20-30s per page (multiple LLM calls) |

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
    status = Column(String, default='pending')     # pending, running, completed, failed, stale

    # NEW: Progress tracking
    total_items = Column(Integer, nullable=True)           # Total pages to process
    completed_items = Column(Integer, default=0)           # Pages completed so far
    failed_items = Column(Integer, default=0)              # Pages that errored
    current_item = Column(Integer, nullable=True)          # Page currently being processed
    last_completed_item = Column(Integer, nullable=True)   # Last successfully processed page (for resume)
    progress_detail = Column(Text, nullable=True)          # JSON: per-page errors + running stats

    # NEW: Heartbeat for stale detection (background thread updates every 30s)
    heartbeat_at = Column(DateTime, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index('idx_book_running_job', 'book_id', 'status',
              postgresql_where=text("status IN ('pending', 'running')")),
    )
```

**`progress_detail` JSON structure:**
```json
{
  "page_errors": {
    "23": {"error": "OpenAI rate limit exceeded after 3 retries", "error_type": "retryable"},
    "67": {"error": "OCR text was empty after extraction", "error_type": "terminal"}
  },
  "stats": {
    "subtopics_created": 8,
    "subtopics_merged": 34
  }
}
```

**Error taxonomy in `progress_detail`:**

| `error_type` | Meaning | Admin Action |
|-------------|---------|--------------|
| `retryable` | Transient failure (rate limit, timeout, network) | Retry or resume |
| `terminal` | Data problem (empty OCR, corrupt image, malformed content) | Fix input, then retry |

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
            "heartbeat_at": "TIMESTAMP",
        }
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE book_jobs ADD COLUMN {col_name} {col_type}"))

        conn.commit()
```

Call it from `migrate()` alongside existing migration functions.

---

## 3. Backend: Enhanced JobLockService & State Machine

**File:** `llm-backend/book_ingestion/services/job_lock_service.py`

### 3a. Job State Machine

All job state transitions are enforced by the `JobLockService`. No code outside this service may directly update `BookJob.status`.

```
                 acquire_lock()
                      │
                      ▼
    ┌──────────┐  start_job()  ┌──────────┐
    │ pending  │──────────────▶│ running  │
    └──────────┘               └────┬─────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
              release_lock()  release_lock()  detect_stale()
              status=completed status=failed       │
                    │               │               │
                    ▼               ▼               ▼
             ┌───────────┐  ┌───────────┐   ┌───────────┐
             │ completed │  │  failed   │   │   stale   │
             └───────────┘  └───────────┘   └─────┬─────┘
                                                  │
                                            mark_stale_failed()
                                                  │
                                                  ▼
                                            ┌───────────┐
                                            │  failed   │
                                            └───────────┘
```

**Valid transitions:**

| From | To | Trigger | Who |
|------|----|---------|-----|
| (none) | `pending` | `acquire_lock()` | HTTP endpoint |
| `pending` | `running` | `start_job()` | Background thread (first action) |
| `running` | `completed` | `release_lock(status='completed')` | Background thread |
| `running` | `failed` | `release_lock(status='failed')` | Background thread |
| `running` | `stale` | `detect_stale()` | Polling endpoint (server-side) |
| `stale` | `failed` | `mark_stale_failed()` | Polling endpoint (auto) |

**Invalid transitions** (raise `InvalidStateTransition`):
- `completed` → anything
- `failed` → anything (must create new job instead)
- `pending` → `completed`/`failed` (must go through `running` first)

### 3b. Lock Lifecycle

```
1. HTTP request calls acquire_lock(book_id, job_type, total_items)
   → Checks for existing pending/running jobs (409 if found)
   → Creates BookJob with status='pending'
   → Returns job_id

2. HTTP request launches background thread, passes job_id

3. Background thread calls start_job(job_id)
   → Transitions pending → running
   → Sets heartbeat_at = now()

4. Background thread processes items in a loop:
   → After each item: update_progress(job_id, ...)
   → Heartbeat updates automatically (every 30s via progress calls)

5a. On success: background thread calls release_lock(job_id, status='completed')
5b. On failure: background thread calls release_lock(job_id, status='failed', error=str(e))

6. If container dies mid-job:
   → Job stays in 'running' with stale heartbeat_at
   → Next polling request detects heartbeat_at > 2 min ago
   → Server-side detect_stale() transitions running → stale → failed
   → Admin sees "Job interrupted — Resume from page X?"
```

### 3c. Enhanced Methods

```python
HEARTBEAT_STALE_THRESHOLD = timedelta(minutes=2)

def acquire_lock(self, book_id: str, job_type: str, total_items: int = None) -> str:
    """
    Create a new job in 'pending' state. Returns job_id.
    Raises JobLockError if a pending/running job already exists for this book.
    """
    # Check for existing active jobs (pending OR running)
    existing = self.db.query(BookJob).filter(
        BookJob.book_id == book_id,
        BookJob.status.in_(['pending', 'running'])
    ).first()

    if existing:
        # Before raising, check if it's stale
        if existing.status == 'running' and self._is_stale(existing):
            self._mark_stale(existing)
        else:
            raise JobLockError(f"Job {existing.id} is already {existing.status}")

    job = BookJob(
        id=str(uuid.uuid4()),
        book_id=book_id,
        job_type=job_type,
        status='pending',
        total_items=total_items,
    )
    self.db.add(job)
    self.db.commit()
    return job.id

def start_job(self, job_id: str):
    """Transition pending → running. Called by background thread as first action."""
    job = self._get_job_or_raise(job_id)
    if job.status != 'pending':
        raise InvalidStateTransition(f"Cannot start job in '{job.status}' state")
    job.status = 'running'
    job.heartbeat_at = datetime.utcnow()
    self.db.commit()

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
    Update job progress + heartbeat. Called after each page.
    Heartbeat is always refreshed, enabling stale detection.
    """
    job = self.db.query(BookJob).filter(BookJob.id == job_id).first()
    if not job or job.status != 'running':
        return  # Job was cancelled or marked stale externally
    job.current_item = current_item
    job.completed_items = completed
    job.failed_items = failed
    job.heartbeat_at = datetime.utcnow()  # Always refresh heartbeat
    if last_completed_item is not None:
        job.last_completed_item = last_completed_item
    if detail is not None:
        job.progress_detail = detail
    self.db.commit()

def release_lock(self, job_id: str, status: str = 'completed', error: str = None):
    """Transition running → completed/failed. Terminal state."""
    job = self._get_job_or_raise(job_id)
    if job.status not in ('running', 'stale'):
        logger.warning(f"Cannot release job {job_id} in '{job.status}' state")
        return
    job.status = status
    job.completed_at = datetime.utcnow()
    job.error_message = error
    self.db.commit()

def _is_stale(self, job: BookJob) -> bool:
    """A running job is stale if heartbeat hasn't been updated recently."""
    if not job.heartbeat_at:
        # No heartbeat ever written — stale if started > threshold ago
        return (datetime.utcnow() - job.started_at) > HEARTBEAT_STALE_THRESHOLD
    return (datetime.utcnow() - job.heartbeat_at) > HEARTBEAT_STALE_THRESHOLD

def _mark_stale(self, job: BookJob):
    """Transition running → failed with stale error."""
    job.status = 'failed'
    job.completed_at = datetime.utcnow()
    job.error_message = (
        f"Job interrupted (no heartbeat since "
        f"{job.heartbeat_at.isoformat() if job.heartbeat_at else 'never'}). "
        f"Container may have restarted. Resume from page {job.last_completed_item or 'start'}."
    )
    self.db.commit()
    logger.warning(f"Marked job {job.id} as stale/failed")

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
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }

def get_latest_job(self, book_id: str, job_type: Optional[str] = None) -> Optional[dict]:
    """
    Get most recent job for a book.
    Automatically detects and marks stale jobs (server-side, not UI interpretation).
    """
    query = self.db.query(BookJob).filter(BookJob.book_id == book_id)
    if job_type:
        query = query.filter(BookJob.job_type == job_type)
    job = query.order_by(BookJob.started_at.desc()).first()
    if not job:
        return None

    # Server-side stale detection on every read
    if job.status == 'running' and self._is_stale(job):
        self._mark_stale(job)

    return self.get_job(job.id)
```

Also update `acquire_lock` to accept `total_items` (shown above).

### 3d. Race Condition Handling

#### Race 1: `start_job()` vs `_mark_stale()` (TOCTOU on heartbeat)

**Scenario:** A polling request calls `get_latest_job()` at the exact moment a background thread calls `start_job()`. The polling thread reads a stale `heartbeat_at`, decides the job is stale, and marks it `failed` — just as the background thread transitions it to `running`.

**Mitigation:** `start_job()` uses a `SELECT ... FOR UPDATE` row lock:

```python
def start_job(self, job_id: str):
    """Transition pending → running. Uses row-level lock to prevent stale-detection race."""
    job = self.db.query(BookJob).filter(BookJob.id == job_id).with_for_update().first()
    if not job:
        raise InvalidStateTransition(f"Job {job_id} not found")
    if job.status != 'pending':
        raise InvalidStateTransition(f"Cannot start job in '{job.status}' state")
    job.status = 'running'
    job.heartbeat_at = datetime.utcnow()
    self.db.commit()
```

Similarly, `_mark_stale()` must acquire the row lock and re-check status:

```python
def _mark_stale(self, job: BookJob):
    """Transition running → failed. Re-checks under row lock to prevent race with start_job."""
    job = self.db.query(BookJob).filter(BookJob.id == job.id).with_for_update().first()
    if job.status != 'running':
        return  # Another thread already transitioned it
    if not self._is_stale(job):
        return  # Heartbeat was refreshed between our check and lock acquisition
    job.status = 'failed'
    job.completed_at = datetime.utcnow()
    job.error_message = (
        f"Job interrupted (no heartbeat since "
        f"{job.heartbeat_at.isoformat() if job.heartbeat_at else 'never'}). "
        f"Container may have restarted. Resume from page {job.last_completed_item or 'start'}."
    )
    self.db.commit()
    logger.warning(f"Marked job {job.id} as stale/failed")
```

**Key invariant:** Any method that transitions `BookJob.status` must acquire the row lock first (`with_for_update()`), then re-validate the precondition. This eliminates TOCTOU races.

#### Race 2: `release_lock()` failure (DB error during terminal transition)

**Scenario:** The background thread finishes processing and calls `release_lock(status='completed')`, but the DB write fails (connection timeout, full disk, etc.). The job stays in `running` state with a stale heartbeat.

**Mitigation:** The catch-all handler in `background_task_runner.py` retries the `release_lock` call once before giving up:

```python
except Exception as e:
    logger.error(f"Background task failed: {e}", exc_info=True)
    for attempt in range(2):  # Try twice
        try:
            job_lock = JobLockService(session)
            job_lock.release_lock(job_id, status='failed', error=str(e))
            break
        except Exception:
            if attempt == 0:
                logger.warning("First release_lock attempt failed, retrying...")
                time.sleep(1)
            else:
                logger.error(f"Could not mark job {job_id} as failed — will be caught by stale detection")
```

If both attempts fail, the job remains in `running` with a stale heartbeat. The next `get_latest_job()` call will detect it via heartbeat expiry and transition it to `failed`. This is the safety net — stale detection is the ultimate backstop for any incomplete state transition.

#### Race 3: `acquire_lock()` concurrent calls (two admins or double-click)

**Scenario:** Two near-simultaneous `acquire_lock()` calls for the same book. Both read "no active job exists" and both attempt to insert.

**Mitigation:** The partial index `idx_book_running_job` (PostgreSQL `UNIQUE` on `(book_id)` WHERE `status IN ('pending', 'running')`) guarantees at most one active job per book at the database level. The second insert raises `IntegrityError`, which `acquire_lock` catches and converts to `JobLockError`.

```python
try:
    self.db.add(job)
    self.db.commit()
except IntegrityError:
    self.db.rollback()
    raise JobLockError(f"Another job was just created for book {book_id}")
```

### 3e. Concurrency Primitive: Partial Index

The primary concurrency control mechanism is a PostgreSQL partial unique index:

```sql
CREATE UNIQUE INDEX idx_book_running_job ON book_jobs (book_id)
WHERE status IN ('pending', 'running');
```

**What this guarantees:**
- At most **one** job in `pending` or `running` state per `book_id` at any point in time
- This is enforced by the database engine, not application code — immune to application-level race conditions
- Multiple `completed`/`failed` jobs can coexist (they're excluded by the `WHERE` clause)
- Any `INSERT` that would create a second active job for the same book fails with `IntegrityError`

**Why this is sufficient:** Combined with `SELECT ... FOR UPDATE` row locks on state transitions, this gives us:
1. **At-most-one active job** (partial index) — prevents duplicate job creation
2. **Atomic state transitions** (row lock) — prevents TOCTOU races on status changes
3. **Stale detection as backstop** (heartbeat check) — catches leaked `running` jobs from container restarts

No additional application-level mutexes, distributed locks, or advisory locks are needed.

### 3f. Idempotency Guarantees for `update_progress`

`update_progress()` is called after every page. It must be safe to call multiple times with the same arguments (e.g., if the caller retries after a transient DB error):

| Field | Idempotency Behavior |
|-------|---------------------|
| `current_item` | Overwritten — always reflects latest call. Safe to replay. |
| `completed_items` | Overwritten — caller passes cumulative count, not delta. Replaying same value is a no-op. |
| `failed_items` | Same as `completed_items` — cumulative, not delta. |
| `last_completed_item` | Monotonically increasing. A replay with the same value is a no-op. A replay with a lower value is harmless (overwritten by next progress call). |
| `heartbeat_at` | Always set to `now()`. Replaying refreshes the heartbeat — desirable behavior. |
| `progress_detail` | Overwritten entirely. Caller passes full JSON, not a patch. Replaying same JSON is a no-op. |

**Key design choice:** All progress fields use **absolute values** (cumulative counts, full JSON), not **deltas** (increment by 1). This makes every `update_progress` call independently idempotent — the system converges to the correct state regardless of how many times a call is replayed.

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


def run_in_background(target_fn, job_id: str, *args, **kwargs):
    """
    Run a function in a background thread with its own DB session.

    The target function receives db_session as its first argument.
    The session is automatically closed when the function completes.

    The runner handles the pending → running transition via start_job()
    before calling the target function. If the target raises, the job
    is marked failed via release_lock().

    Args:
        target_fn: Function to run. Signature: (db_session, job_id, *args, **kwargs)
        job_id: The BookJob ID to manage lifecycle for
        *args, **kwargs: Additional arguments passed to target_fn

    Returns:
        threading.Thread instance
    """
    def wrapper():
        db_manager = get_db_manager()
        session = db_manager.SessionLocal()
        try:
            from .job_lock_service import JobLockService
            job_lock = JobLockService(session)

            # Transition pending → running (sets initial heartbeat)
            job_lock.start_job(job_id)

            # Run the actual task
            target_fn(session, job_id, *args, **kwargs)

        except Exception as e:
            logger.error(f"Background task {target_fn.__name__} failed: {e}", exc_info=True)
            # Ensure job is marked failed if it's still running
            try:
                from .job_lock_service import JobLockService
                job_lock = JobLockService(session)
                job_lock.release_lock(job_id, status='failed', error=str(e))
            except Exception:
                logger.error(f"Failed to mark job {job_id} as failed", exc_info=True)
        finally:
            session.close()

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    logger.info(f"Launched background task: {target_fn.__name__} (job_id={job_id})")
    return thread
```

**Key decisions:**
- `daemon=True`: Thread dies if the main process dies (clean shutdown)
- Independent DB session: Avoids SQLAlchemy session lifecycle issues between the request thread and background thread
- `start_job()` call: Ensures deterministic `pending → running` transition with initial heartbeat
- Catch-all failure handler: If anything throws, the job is marked `failed` rather than staying `running` forever
- The function signature convention `(db_session, job_id, *args, **kwargs)` makes it clear that the background task gets its own session and manages its own job lifecycle

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

**Async boundary — no signature changes to existing methods:**

The existing `process_page` and `finalize_book` are declared `async`. Rather than changing their signatures (high blast radius — they're called from FastAPI endpoints and tests), the background runner wraps calls with `asyncio.run()`:

```python
import asyncio

# In the background thread:
page_result = asyncio.run(orchestrator.process_page(
    book_id=book_id,
    page_num=page_num,
    book_metadata=book_metadata,
))
```

**Why this is safe:**
- `process_page` (line 231 of `guideline_extraction_orchestrator.py`) is declared `async` but all internal calls are synchronous — no `await` statements on I/O operations. `asyncio.run()` creates a fresh event loop per call, which is fine since there's no actual async I/O to manage.
- `finalize_book` (line 435) does use `await` on `_merge_duplicate_shards`, so `asyncio.run()` is necessary to run it correctly.
- This approach keeps the existing FastAPI `async def` endpoints working unchanged and avoids touching any existing method signatures. The only new code is in `run_extraction_background` and `run_finalization_background`.

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

### 7d. metadata.json Reconciliation on Resume

**Problem:** The background OCR processor uses batched metadata.json writes (every 5 pages). If the process dies between flushes, metadata.json is stale — it may show pages as `"pending"` when they actually completed (per DB progress), or show pages as `"processing"` when they failed.

**Invariant:** The `BookJob` table is the **authoritative source of truth** for progress. metadata.json is a **derived cache** that must be reconciled on resume.

**Reconciliation procedure** (runs at the start of any resume operation):

```python
def _reconcile_metadata_from_db(
    self,
    book_id: str,
    last_job: dict,
    s3_client: S3Client,
) -> dict:
    """
    Reconcile metadata.json with DB state after a crash/resume.
    Returns the reconciled metadata dict (already flushed to S3).
    """
    metadata = s3_client.download_json(f"books/{book_id}/metadata.json")
    progress_detail = json.loads(last_job["progress_detail"] or "{}")
    page_errors = progress_detail.get("page_errors", {})
    last_completed = last_job["last_completed_item"]

    for page_entry in metadata["pages"]:
        page_num = page_entry["page_num"]
        page_str = str(page_num)

        if page_str in page_errors:
            # DB says this page failed
            page_entry["ocr_status"] = "failed"
            page_entry["ocr_error"] = page_errors[page_str].get("error", "Unknown error")
        elif last_completed is not None and page_num <= last_completed:
            # DB says this page completed — verify S3 artifacts exist
            text_key = f"books/{book_id}/{page_num}.txt"
            if s3_client.exists(text_key):
                page_entry["ocr_status"] = "completed"
                page_entry["text_s3_key"] = text_key
                page_entry["ocr_error"] = None
            else:
                # DB says complete but artifact missing — treat as failed
                page_entry["ocr_status"] = "failed"
                page_entry["ocr_error"] = "OCR text missing from S3 (possible partial write)"
        elif page_entry.get("ocr_status") == "processing":
            # Was in-flight when process died — reset to pending for retry
            page_entry["ocr_status"] = "pending"
            page_entry["ocr_error"] = None

    # Flush reconciled state
    metadata["last_updated"] = datetime.utcnow().isoformat()
    metadata["reconciled_from_job"] = last_job["job_id"]
    s3_client.update_metadata_json(book_id, metadata)

    return metadata
```

**When this runs:**
- At the start of `run_bulk_ocr_background` when `start_page > 1` (i.e., this is a resume, not a fresh run)
- At the start of `run_extraction_background` when `start_page > 1`

**What it fixes:**
| metadata.json state | DB state | Reconciled to |
|---------------------|----------|---------------|
| `"processing"` | job failed | `"pending"` (retry eligible) |
| `"pending"` | page completed | `"completed"` (with S3 verification) |
| `"completed"` | page in `page_errors` | `"failed"` (DB is authoritative) |
| `"pending"` | page in `page_errors` | `"failed"` |
| Any status | page > `last_completed_item` | Unchanged (hasn't been processed yet) |

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
    heartbeat_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


### 8b. Backend-Frontend Progress Contract

Every field in `JobStatusResponse` has explicit nullability rules, invariants, and frontend interpretation:

| Field | Type | Null when? | Invariants | Frontend Interpretation |
|-------|------|-----------|------------|------------------------|
| `job_id` | `str` | Never | Always set on creation | Primary key for polling |
| `book_id` | `str` | Never | FK to books table | Used for routing |
| `job_type` | `str` | Never | One of: `extraction`, `finalization`, `ocr_batch` | Determines which progress UI to show |
| `status` | `str` | Never | One of: `pending`, `running`, `completed`, `failed`. `stale` is never returned — always auto-transitioned to `failed` before response. | Controls UI state: progress bar / success banner / error+resume UI |
| `total_items` | `int?` | When job is `pending` and total not yet known | Set by `acquire_lock(total_items=N)`. Immutable after creation. | Denominator for progress bar. If null, show indeterminate spinner. |
| `completed_items` | `int` | Never (default 0) | Monotonically increasing. `0 ≤ completed_items ≤ total_items`. | Numerator for progress bar percentage. |
| `failed_items` | `int` | Never (default 0) | `0 ≤ failed_items`. `completed_items + failed_items ≤ total_items`. | Shown as "N pages had errors" warning text. |
| `current_item` | `int?` | When `pending` or `completed`/`failed` (not currently processing) | Set during `running`. Cleared to last value on terminal state (not nulled). | "Currently processing: Page X" text. Hidden when null. |
| `last_completed_item` | `int?` | When no items have completed yet | Monotonically increasing. The page number of the last successfully processed page. | Used in resume UI: "Resume from Page {last_completed_item + 1}" |
| `progress_detail` | `str?` | When no per-page data yet | JSON string. Frontend must `JSON.parse()` with try/catch (may be malformed in edge cases). | Parsed for per-page errors and stats display. |
| `heartbeat_at` | `str?` | Before first `update_progress` | ISO 8601 timestamp. Not directly displayed to user. | Not displayed. Used internally by backend for stale detection. |
| `started_at` | `str?` | Never (set on creation) | ISO 8601 timestamp. | "Started X minutes ago" elapsed time display. |
| `completed_at` | `str?` | When job not yet terminal | Set when status transitions to `completed` or `failed`. | "Completed X minutes ago" or used to compute total duration. |
| `error_message` | `str?` | When no error | **Non-null if and only if `status == 'failed'`**. Human-readable error description. | Displayed in error banner. For stale jobs, contains resume instructions. |

**Completion semantics:**
- A job is **terminal** when `status ∈ {'completed', 'failed'}`. Terminal jobs are never polled again.
- A `completed` job may still have `failed_items > 0` (some pages had errors but processing continued). The frontend shows a success banner with a warning about failed pages.
- A `failed` job means processing stopped. `error_message` explains why. `last_completed_item` indicates where to resume.

**Frontend polling rules:**
1. On mount: call `getLatestJob(bookId, jobType)` once
2. If result is `null`: no job exists — show default UI
3. If `status == 'pending'` or `status == 'running'`: start `setInterval` polling at 3s
4. If `status == 'completed'` or `status == 'failed'`: show terminal UI, do not poll
5. On each poll response: if status becomes terminal, clear interval immediately
6. On unmount: clear interval (prevent memory leak and state-after-unmount warnings)

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

**Critical design decision:** The request path does ONLY lightweight work (validation, stream to S3). All heavy work (image conversion, OCR) happens in the background thread. This prevents timeouts and OOM on large batches.

```python
from fastapi import UploadFile, File
from typing import List

MAX_BULK_UPLOAD_FILES = 200  # Prevent request body OOM


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
    Images are streamed to S3 as raw files (no conversion in request path).
    Image conversion + OCR runs in the background.
    """
    # Validate book exists
    book_service = BookService(db)
    book = book_service.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

    if not images:
        raise HTTPException(status_code=400, detail="No images provided")

    if len(images) > MAX_BULK_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Max {MAX_BULK_UPLOAD_FILES} files per upload"
        )

    # Lightweight validation only (metadata, not content)
    page_service = PageService(db)
    for img in images:
        page_service._validate_image_metadata(img.filename, img.size)

    # Stream raw files to S3 one at a time (no conversion, no OCR)
    # Each file is read, uploaded to S3 as-is, then discarded from memory
    page_numbers = []
    for img in images:
        data = await img.read()
        page_num = page_service.upload_raw_image(book_id, data, img.filename)
        page_numbers.append(page_num)
        del data  # Free memory immediately

    # Acquire job lock for background processing
    job_lock = JobLockService(db)
    try:
        job_id = job_lock.acquire_lock(
            book_id, job_type="ocr_batch", total_items=len(page_numbers)
        )
    except JobLockError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Launch background thread for conversion + OCR
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
        status="processing",
        message=f"Uploaded {len(page_numbers)} raw images. Conversion + OCR processing in background.",
    )
```

**What stays in the request path vs. what moves to background:**

| Operation | Time per page | Request path? | Background? |
|-----------|---------------|---------------|-------------|
| Metadata validation (size, ext) | <1ms | Yes | — |
| Stream raw bytes to S3 | ~200ms | Yes | — |
| PNG conversion | ~50-200ms | — | Yes |
| OCR (LLM API call) | ~10s | — | Yes |
| metadata.json update | ~50ms | — | Yes (batched) |

### 9c. PageService Raw Upload Method

**File:** `llm-backend/book_ingestion/services/page_service.py`

```python
def upload_raw_image(
    self,
    book_id: str,
    image_data: bytes,
    filename: str,
) -> int:
    """
    Upload a single raw image to S3 without conversion or OCR.
    Assigns a page number and updates metadata.
    Called once per file from the request path — must be fast.
    """
    metadata = self._load_metadata(book_id)
    page_num = self._get_next_page_number(metadata)

    # Determine content type from filename extension
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'png'
    content_type = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'tiff': 'image/tiff', 'tif': 'image/tiff', 'webp': 'image/webp',
    }.get(ext, 'application/octet-stream')

    # Upload raw bytes to S3 (no conversion — fast)
    raw_s3_key = f"books/{book_id}/raw/{page_num}.{ext}"
    self.s3_client.upload_bytes(image_data, raw_s3_key, content_type=content_type)

    # Add to metadata with ocr_status: pending
    page_info = {
        "page_num": page_num,
        "raw_image_s3_key": raw_s3_key,   # Raw upload (not yet converted)
        "image_s3_key": None,              # Set after PNG conversion in background
        "text_s3_key": None,               # Set after OCR in background
        "status": "pending_review",
        "ocr_status": "pending",
        "ocr_error": None,
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    metadata["pages"].append(page_info)
    metadata["total_pages"] = len(metadata["pages"])

    # Save metadata after each page (idempotent — safe if request dies mid-batch)
    metadata["last_updated"] = datetime.utcnow().isoformat()
    self.s3_client.update_metadata_json(book_id, metadata)

    return page_num
```

**Sort order:** Files are sorted by filename alphabetically before upload (handled by the endpoint). This matches how scanners typically name files (`page_001.jpg`, `page_002.jpg`).

---

## 10. Backend: Background OCR Processor

**File:** `llm-backend/book_ingestion/services/page_service.py`

### 10a. metadata.json Update Strategy

**Problem with per-page updates:** The original design called `_update_page_ocr_status()` after every page, which reads and writes the full `metadata.json` from S3 each time. For 100 pages, that's 200+ S3 operations just for status updates — fragile and slow.

**Solution: Batched writes with in-memory state.**

The background thread holds a mutable `page_status` dict in memory and flushes it to `metadata.json` periodically:

| Event | Action |
|-------|--------|
| Start of batch | Load `metadata.json` once into memory |
| After each page | Update in-memory dict + update `BookJob` progress in DB |
| Every N pages (N=5) or 30 seconds | Flush in-memory state to `metadata.json` in S3 |
| On completion or failure | Final flush to `metadata.json` |

**Why this is safe:**
- Only one job per book (enforced by `JobLockService`)
- Single-page upload endpoint returns 409 if a `ocr_batch` job is running (prevents concurrent metadata.json writes)
- If the process dies between flushes, the DB has authoritative progress (`BookJob.completed_items`, `last_completed_item`). On resume, metadata.json is reconciled from DB state.

### 10b. Background Processing Function

```python
METADATA_FLUSH_INTERVAL = 5  # Flush every N pages

@staticmethod
def run_bulk_ocr_background(
    db_session: Session,
    job_id: str,
    book_id: str,
    page_numbers: List[int],
):
    """
    Background task: convert images to PNG + run OCR.
    Progress tracked in BookJob (DB). metadata.json updated in batches.
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
    pages_since_flush = 0

    # Load metadata once into memory
    metadata = s3_client.download_json(f"books/{book_id}/metadata.json")

    def flush_metadata():
        """Write current in-memory metadata to S3."""
        nonlocal pages_since_flush
        metadata["last_updated"] = datetime.utcnow().isoformat()
        s3_client.update_metadata_json(book_id, metadata)
        pages_since_flush = 0

    try:
        for page_num in page_numbers:
            # Update DB progress: currently processing this page
            job_lock.update_progress(
                job_id, current_item=page_num,
                completed=completed, failed=failed,
            )

            # Find this page in metadata (in-memory)
            page_entry = next(
                (p for p in metadata["pages"] if p["page_num"] == page_num), None
            )
            if not page_entry:
                logger.error(f"Page {page_num} not found in metadata")
                failed += 1
                page_errors[str(page_num)] = {
                    "error": "Page not found in metadata",
                    "error_type": "terminal"
                }
                continue

            page_entry["ocr_status"] = "processing"

            try:
                # Step 1: Load raw image from S3
                raw_s3_key = page_entry.get("raw_image_s3_key")
                if not raw_s3_key:
                    raise ValueError("No raw image uploaded for this page")
                raw_bytes = s3_client.download_bytes(raw_s3_key)

                # Step 2: Convert to PNG (heavy — runs in background, not request path)
                png_bytes = PageService._convert_to_png(raw_bytes)
                image_s3_key = f"books/{book_id}/{page_num}.png"
                s3_client.upload_bytes(png_bytes, image_s3_key, content_type="image/png")
                page_entry["image_s3_key"] = image_s3_key
                del raw_bytes, png_bytes  # Free memory

                # Step 3: Run OCR with exponential backoff on rate limits
                ocr_text = ocr_service.extract_text_with_retry(
                    image_bytes=s3_client.download_bytes(image_s3_key)
                )

                # Step 4: Save OCR text to S3
                text_s3_key = f"books/{book_id}/{page_num}.txt"
                s3_client.upload_bytes(
                    ocr_text.encode('utf-8'), text_s3_key, content_type="text/plain"
                )

                # Update in-memory metadata
                page_entry["text_s3_key"] = text_s3_key
                page_entry["ocr_status"] = "completed"
                page_entry["ocr_error"] = None
                completed += 1

            except Exception as e:
                failed += 1
                error_type = "retryable" if _is_retryable(e) else "terminal"
                page_errors[str(page_num)] = {
                    "error": str(e), "error_type": error_type
                }
                page_entry["ocr_status"] = "failed"
                page_entry["ocr_error"] = str(e)
                logger.error(f"OCR failed for page {page_num}: {e}")

            # Update DB progress (authoritative source of truth)
            job_lock.update_progress(
                job_id, current_item=page_num,
                completed=completed, failed=failed,
                last_completed_item=page_num,
                detail=json.dumps({"page_errors": page_errors}),
            )

            # Batched metadata.json flush
            pages_since_flush += 1
            if pages_since_flush >= METADATA_FLUSH_INTERVAL:
                flush_metadata()

        # Final flush + mark complete
        flush_metadata()
        job_lock.release_lock(job_id, status='completed')

    except Exception as e:
        logger.error(f"Bulk OCR job {job_id} failed: {e}", exc_info=True)
        # Best-effort final flush
        try:
            flush_metadata()
        except Exception:
            pass
        job_lock.release_lock(job_id, status='failed', error=str(e))


def _is_retryable(e: Exception) -> bool:
    """Classify errors as retryable (transient) or terminal (data problem)."""
    error_str = str(e).lower()
    retryable_patterns = ['rate limit', '429', 'timeout', 'connection', 'temporary']
    return any(pattern in error_str for pattern in retryable_patterns)
```

### 10c. Rate Limit Handling

The existing `ocr_service.extract_text_with_retry` handles retries internally. For this plan, we add an explicit backoff policy:

| Attempt | Wait | Total Elapsed |
|---------|------|---------------|
| 1 | 0s | 0s |
| 2 | 2s | 2s |
| 3 | 4s | 6s |
| 4 | 8s | 14s |
| 5 (final) | 16s | 30s |

After 5 attempts, the page is marked `failed` with `error_type: "retryable"`. The admin can retry later when rate limits cool down.

### 10d. Concurrency Guard

The single-page upload endpoint (`POST /books/{book_id}/pages`) must check for a running `ocr_batch` job and return 409:

```python
# In the single-page upload endpoint:
job_lock = JobLockService(db)
active = job_lock.get_latest_job(book_id, job_type="ocr_batch")
if active and active["status"] in ("pending", "running"):
    raise HTTPException(
        status_code=409,
        detail="Bulk OCR job in progress. Wait for completion before uploading individual pages."
    )
```

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
  heartbeat_at: string | null;
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

### Phase 0: Infrastructure Prerequisite

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 0 | Verify/configure App Runner provisioned CPU mode | `infra/terraform/modules/app-runner/main.tf` | — |

### Phase 1: Backend Foundation (Enables Everything Else)

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 1 | Add columns + heartbeat_at to `BookJob` model | `database.py` | — |
| 2 | Add migration function | `db.py` | Step 1 |
| 3 | Rewrite `JobLockService` with state machine + stale detection | `job_lock_service.py` | Step 1 |
| 4 | Create `background_task_runner.py` with start_job lifecycle | `background_task_runner.py` (new) | Step 3 |
| 5 | Add job status polling endpoints (with server-side stale check) | `routes.py` | Step 3 |
| 6 | **Write Phase 1 tests** (state machine, lock lifecycle, stale detection) | `tests/` | Steps 3-5 |

### Phase 2: Background Guidelines Generation + Resume

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 7 | Create `run_extraction_background` function (uses `asyncio.run()`) | `guideline_extraction_orchestrator.py` | Steps 3-4 |
| 8 | Refactor generate-guidelines endpoint to return job_id | `routes.py` | Steps 5, 7 |
| 9 | Add `resume` support to request | `routes.py` | Step 8 |
| 10 | Refactor finalize endpoint to return job_id | `routes.py` | Steps 4-5 |
| 11 | **Write Phase 2 tests** (extraction lifecycle, resume, idempotency) | `tests/` | Steps 7-10 |

### Phase 3: Bulk Upload + Background OCR

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 12 | Add `ocr_status` + `raw_image_s3_key` to metadata page schema | `page_service.py` | — |
| 13 | Add `upload_raw_image` method (lightweight, no conversion) | `page_service.py` | Step 12 |
| 14 | Add `run_bulk_ocr_background` with batched metadata writes | `page_service.py` | Steps 3-4, 12 |
| 15 | Add bulk upload endpoint with concurrency guard | `routes.py` | Steps 13-14 |
| 16 | Add retry-ocr endpoint | `routes.py` | Step 12 |
| 17 | **Write Phase 3 tests** (bulk upload, OCR retry, metadata batching) | `tests/` | Steps 13-16 |

### Phase 4: Frontend

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 18 | Add TypeScript types | `types/index.ts` | — |
| 19 | Add API client functions | `adminApi.ts` | Step 18 |
| 20 | Create `useJobPolling` hook | `hooks/useJobPolling.ts` (new) | Step 19 |
| 21 | Update GuidelinesPanel with progress + resume | `GuidelinesPanel.tsx` | Steps 19-20 |
| 22 | Update PageUploadPanel with bulk upload | `PageUploadPanel.tsx` | Steps 19-20 |
| 23 | Update PagesSidebar with OCR status | `PagesSidebar.tsx` | Step 18 |
| 24 | **Write frontend tests** (polling lifecycle, mount/unmount) | `tests/` | Steps 20-23 |

---

## 19. Test Strategy

### 19a. Test Matrix (Merge Gate)

All tests below must pass before merge. Tests are organized by category with explicit pass criteria.

#### Category 1: Job State Machine & Lock Lifecycle

| # | Test | Pass Criteria |
|---|------|---------------|
| 1.1 | `acquire_lock` → `start_job` → `update_progress` → `release_lock(completed)` | Job transitions `pending → running → completed`. `completed_at` is set. |
| 1.2 | `acquire_lock` → `start_job` → `release_lock(failed)` | Job transitions `pending → running → failed`. `error_message` is set. |
| 1.3 | `acquire_lock` twice for same book | Second call raises `JobLockError`. |
| 1.4 | `acquire_lock` after previous job completed | New job created successfully. |
| 1.5 | Invalid state transitions | `start_job` on completed job raises `InvalidStateTransition`. `release_lock` on pending job raises. |
| 1.6 | Stale detection: heartbeat expires | Job with `heartbeat_at` > 2 min ago is auto-marked `failed` on next `get_latest_job` call. |
| 1.7 | Stale detection: no heartbeat ever written | Job with no `heartbeat_at` and `started_at` > 2 min ago is auto-marked `failed`. |
| 1.8 | `acquire_lock` when stale job exists | Stale job is auto-recovered (marked failed), new lock acquired. |
| 1.9 | Progress update after external cancellation | `update_progress` on a job that was externally marked `failed`/`stale` is a no-op (does not crash). |

#### Category 2: Background Extraction Lifecycle

| # | Test | Pass Criteria |
|---|------|---------------|
| 2.1 | Happy path: 5 pages, all succeed | Job completes. `completed_items=5`, `failed_items=0`. S3 artifacts exist for all pages. |
| 2.2 | Partial failure: 5 pages, page 3 fails | Job completes with `completed_items=4`, `failed_items=1`. `progress_detail` contains error for page 3. Pages 1-2, 4-5 have artifacts. |
| 2.3 | Catastrophic failure (exception outside page loop) | Job marked `failed`. `error_message` set. `last_completed_item` reflects last good page. |
| 2.4 | Resume from failure: start at page 4 after pages 1-3 completed | Resume request sets `start_page=4`. New job processes pages 4-5 only. Existing pages 1-3 artifacts are untouched. |
| 2.5 | Resume idempotency: re-process a page that already has artifacts | No duplicate shards. Existing shard is overwritten cleanly. |
| 2.6 | `asyncio.run()` wrapper correctness | Background thread successfully calls async `process_page` via `asyncio.run()`. |

#### Category 3: Bulk Upload & OCR

| # | Test | Pass Criteria |
|---|------|---------------|
| 3.1 | Bulk upload 10 images | 10 raw images in S3 (`raw/` prefix). metadata.json has 10 entries with `ocr_status: "pending"`. |
| 3.2 | Background OCR: 5 pages, all succeed | All pages have `ocr_status: "completed"`, `image_s3_key` (converted PNG), `text_s3_key`. |
| 3.3 | Background OCR: 5 pages, page 2 fails (rate limit) | Page 2: `ocr_status: "failed"`, `error_type: "retryable"`. Pages 1, 3-5: completed. |
| 3.4 | OCR retry for failed page | After retry, page transitions `failed → completed`. Text S3 key populated. |
| 3.5 | Metadata batching: 20 pages | metadata.json written ~4 times (every 5 pages), not 20 times. Verified by S3 write count. |
| 3.6 | Single-page upload blocked during bulk OCR | Returns 409 when `ocr_batch` job is running. |
| 3.7 | Bulk upload > 200 files | Returns 400 with clear error message. |

#### Category 4: Rate Limit & Retry Behavior

| # | Test | Pass Criteria |
|---|------|---------------|
| 4.1 | 429 response triggers exponential backoff | Retries at 2s, 4s, 8s, 16s intervals. After 5 attempts, marked `failed` with `error_type: "retryable"`. |
| 4.2 | Transient network error triggers retry | Same retry behavior as 4.1. |
| 4.3 | Terminal error (corrupt image) does not retry | Immediately marked `failed` with `error_type: "terminal"`. |

#### Category 5: Frontend Polling Lifecycle

| # | Test | Pass Criteria |
|---|------|---------------|
| 5.1 | `useJobPolling` detects running job on mount | Hook fetches `getLatestJob` on mount, starts polling if status is `running`. |
| 5.2 | Polling stops on completion | `setInterval` cleared when job status becomes `completed` or `failed`. |
| 5.3 | Component unmount cleans up interval | No leaked intervals after unmount. No state updates after unmount. |
| 5.4 | Multiple mount/unmount cycles | No duplicate intervals. Each mount starts fresh. |
| 5.5 | Resume button triggers new job | Clicking "Resume" calls `generateGuidelines({ resume: true })` and starts polling new job. |

#### Category 6: Race Conditions, Restart, & Error-Path Verification

| # | Test | Pass Criteria |
|---|------|---------------|
| 6.1 | `start_job` and `_mark_stale` race (concurrent threads) | Run `start_job` and `_mark_stale` concurrently on the same job (use threading + small sleep). Only one wins. Job ends in either `running` (start won) or `failed` (stale won) — never in an inconsistent state. No exceptions raised. |
| 6.2 | `acquire_lock` concurrent double-call (simulate double-click) | Two threads call `acquire_lock` for the same book simultaneously. Exactly one succeeds, the other raises `JobLockError`. Verified by checking that only one `pending`/`running` job exists in DB. |
| 6.3 | `release_lock` fails (DB connection error during terminal transition) | Mock DB commit to raise on first call, succeed on retry. Job transitions to `failed` on second attempt. If both fail, job remains `running` and is caught by stale detection within 2 minutes. |
| 6.4 | Restart during processing: new `generate-guidelines` while job is `running` | Returns 409 Conflict. The running job is not affected. |
| 6.5 | Restart after stale: new job after stale job is auto-recovered | First job goes stale (heartbeat expired). New `acquire_lock` call detects stale, marks it `failed`, and creates new job. Both operations succeed atomically. |
| 6.6 | Duplicate/replayed `update_progress` calls | Call `update_progress(job_id, current_item=5, completed=5, failed=0)` twice with identical arguments. Second call is a no-op. DB state is unchanged after second call. |
| 6.7 | Out-of-order `update_progress` (lower completed count after higher) | Call with `completed=5`, then `completed=3`. DB shows `completed=3` (latest call wins — caller is authoritative). This is harmless because the caller's state is the source of truth; a lower count would only happen in a retry-after-rollback scenario. |
| 6.8 | metadata.json reconciliation after crash | Simulate: process 10 pages, flush metadata at page 5, crash at page 8. Resume: reconciliation marks pages 6-7 as `completed` (DB says so + S3 artifacts exist), page 8 as `pending` (was in-flight). metadata.json matches DB truth. |
| 6.9 | Error-path state invariants after failure | After any job failure (per-page exception, catastrophic exception, stale detection): verify `status == 'failed'`, `error_message IS NOT NULL`, `last_completed_item` reflects last known good page, `completed_at IS NOT NULL`. |
| 6.10 | `update_progress` on externally-cancelled job | Job is marked `failed` by stale detection. Background thread (unaware) calls `update_progress`. Call is a silent no-op (returns without error, does not update DB). |

#### Category 7: Stress / Boundary

| # | Test | Pass Criteria |
|---|------|---------------|
| 7.1 | 100-page extraction (integration) | Completes within expected time (~50 min). Memory stays under 1.5 GB. No leaked DB sessions. |
| 7.2 | 200-page bulk upload (integration) | All images uploaded. OCR completes. metadata.json is consistent at end. |
| 7.3 | Malformed `progress_detail` JSON in DB | Polling endpoint returns job without crashing. Frontend handles gracefully. |
| 7.4 | Job with NULL progress columns | Legacy jobs (pre-migration) don't break polling endpoint. |

### 19b. Test Implementation Approach

- **Unit tests** (Categories 1, 4): Mock S3 and LLM API. Test state machine transitions in isolation.
- **Integration tests** (Categories 2, 3): Use real DB (test database), mock S3 via `moto`, mock LLM responses.
- **Frontend tests** (Category 5): React Testing Library with fake timers for `setInterval`.
- **Race condition & error-path tests** (Category 6): Use real DB with concurrent threads. Mock DB failures where needed. These are CI-gated (fast to run, critical for correctness).
- **Stress tests** (Category 7): Run manually before deploy. Not part of CI gate (too slow).

### 19c. Merge Gate Criteria

The PR is mergeable when:

1. All unit, integration, and race condition tests pass (Categories 1-6)
2. Stress smoke test (7.1 or 7.2) has been run at least once manually
3. App Runner provisioned CPU mode is verified in Terraform config
4. Image conversion and OCR are fully out of the HTTP request path
5. State machine transitions are enforced in `JobLockService` (no direct status updates elsewhere)
6. Stale job detection runs server-side (not only UI interpretation)

---

## 20. Risk & Open Questions

### Risks

| Risk | Mitigation | Status |
|------|------------|--------|
| **Container restart kills background thread** | Heartbeat-based stale detection (server-side, 2-min threshold). Job auto-marked `failed` with resume instructions on next poll. `last_completed_item` enables restart from exact point. | **Resolved in design** |
| **App Runner CPU throttling** | Must use provisioned instances (not request-driven). Terraform change documented in Section 1. Fallback: self-ping keep-alive endpoint. | **Action required: verify Terraform** |
| **metadata.json concurrent writes** | Single-page upload returns 409 during bulk OCR. Only one job per book enforced by DB lock. Batched writes (every 5 pages) reduce S3 write frequency. | **Resolved in design** |
| **metadata.json inconsistency after crash** | DB (`BookJob`) is authoritative for progress. metadata.json is reconciled on resume by replaying completed pages from DB state. | **Resolved in design** |
| **S3 consistency for page_index.json during resume** | Orchestrator already handles "shard exists but not in index" gracefully. Resume reprocesses the failed page, overwriting any partial artifacts. | **Existing behavior** |
| **OpenAI rate limits (429s)** | Exponential backoff: 2s → 4s → 8s → 16s (5 attempts). Pages marked `failed` individually with `error_type: "retryable"`. Admin can retry later. | **Resolved in design** |
| **OOM on large bulk uploads** | Raw file streaming to S3 (no conversion in request path). Files read one at a time with `del data` after each upload. Max 200 files per request. | **Resolved in design** |

### Error-Path State Invariants

After **any** failure path — per-page exception, catastrophic exception, stale detection, or container restart — the following invariants must hold:

| Invariant | Description | Enforced By |
|-----------|-------------|-------------|
| **I1: Terminal status** | `status == 'failed'` | `release_lock(status='failed')` in catch-all handler; `_mark_stale()` for container restarts |
| **I2: Error message present** | `error_message IS NOT NULL` | `release_lock(error=str(e))` always passes the exception message; `_mark_stale()` writes a descriptive message |
| **I3: Completion timestamp** | `completed_at IS NOT NULL` | `release_lock()` sets `completed_at = now()` for both `completed` and `failed` |
| **I4: Last known good page** | `last_completed_item` reflects the last page that fully succeeded (all S3 artifacts written) | `update_progress(last_completed_item=page_num)` only called after successful page processing |
| **I5: No orphaned running state** | No job stays in `running` state indefinitely after its thread dies | Heartbeat-based stale detection (2-min threshold) on every `get_latest_job()` call |
| **I6: Progress detail preserved** | `progress_detail` JSON contains per-page error details for all failed pages up to the crash point | Updated after each page via `update_progress(detail=...)` |

**Verification approach:** Test 6.9 in the test matrix explicitly validates I1-I4 and I6 for each failure mode:
- Per-page exception (caught, continues processing)
- Catastrophic exception (uncaught, hits catch-all in `background_task_runner`)
- Stale detection (container restart simulation)
- DB error during `release_lock` (retry + fallback to stale detection)

**What the admin sees after any failure:**
```
Status: Failed
Error: [specific error message — never generic "Unknown error"]
Pages completed: [last_completed_item] of [total_items]
Failed pages: [list from progress_detail with per-page errors]
→ [Resume from Page X] button (X = last_completed_item + 1)
```

### Observability

| Signal | How | Where |
|--------|-----|-------|
| Job-level logs | Structured logging with `job_id`, `book_id`, `page_num` in every log line | Background thread |
| Per-page progress | `BookJob.completed_items`, `current_item` updated after each page | Database |
| Per-page errors | `BookJob.progress_detail` JSON with error + `error_type` per page | Database |
| Error taxonomy | `retryable` (rate limit, timeout, network) vs `terminal` (corrupt data, empty OCR) | `progress_detail` |
| Heartbeat | `BookJob.heartbeat_at` updated on every `update_progress` call | Database |
| Stale detection | Server-side check on every `get_latest_job` call (2-min threshold) | `JobLockService` |

### Resolved Design Decisions

| Decision | Resolution |
|----------|-----------|
| **Stale job detection** | Server-side heartbeat check (2-min threshold) on every `get_latest_job` call. Not UI interpretation — the backend auto-transitions `running → failed` with a descriptive error message. |
| **Auto-approve bulk uploaded pages?** | No — keep the review step. Add an "Approve All" button that approves all pages with `ocr_status: "completed"` in one click. |
| **Max bulk upload size** | 200 pages max per request. Enforced at endpoint level. |
| **Sort order for bulk upload images** | Sort by filename alphabetically before assigning page numbers. |
| **Async boundary** | Keep existing `async def` signatures. Background thread uses `asyncio.run()` wrapper. No invasive signature changes. |

### Open Questions

| Question | Options | Recommendation |
|----------|---------|----------------|
| **Direct-to-S3 upload (presigned URLs)?** | Option A: Upload through backend (current plan). Option B: Generate presigned S3 URLs, frontend uploads directly to S3, backend only processes. | **Option A for V1** — simpler. Option B is a future optimization for very large batches where backend becomes a bottleneck for transfer. |
| **System-wide concurrency limit?** | Option A: Allow multiple books processing simultaneously. Option B: Only one book processing at a time system-wide. | **Option B for V1** — single admin, single tenant. Simplifies reasoning about resource usage. Can relax later. |
