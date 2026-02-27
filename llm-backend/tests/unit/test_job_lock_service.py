"""
Tests for JobLockService state machine, lock lifecycle, and stale detection.

Covers test matrix Categories 1 and 6 (partial) from the tech implementation plan.
"""
import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from book_ingestion.models.database import BookJob, Book
from book_ingestion.services.job_lock_service import (
    JobLockService,
    JobLockError,
    InvalidStateTransition,
    HEARTBEAT_STALE_THRESHOLD,
)


@pytest.fixture
def book(db_session):
    """Create a test book."""
    book = Book(
        id="test-book-1",
        title="Test Book",
        country="India",
        board="CBSE",
        grade=5,
        subject="Mathematics",
        s3_prefix="books/test-book-1/",
    )
    db_session.add(book)
    db_session.commit()
    return book


@pytest.fixture
def job_lock(db_session):
    """Create a JobLockService instance."""
    return JobLockService(db_session)


# ===== Category 1: Job State Machine & Lock Lifecycle =====


class TestAcquireLock:
    """Test 1.1-1.4: Lock acquisition and lifecycle."""

    def test_acquire_creates_pending_job(self, db_session, book, job_lock):
        """1.1: acquire_lock creates a job in pending state."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=100)

        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert job is not None
        assert job.status == "pending"
        assert job.book_id == book.id
        assert job.job_type == "extraction"
        assert job.total_items == 100

    def test_full_lifecycle_completed(self, db_session, book, job_lock):
        """1.1: Full happy path: acquire → start → progress → release(completed)."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=5)

        # Start
        job_lock.start_job(job_id)
        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert job.status == "running"
        assert job.heartbeat_at is not None

        # Progress
        job_lock.update_progress(job_id, current_item=3, completed=2, failed=0, last_completed_item=2)
        db_session.refresh(job)
        assert job.current_item == 3
        assert job.completed_items == 2
        assert job.last_completed_item == 2

        # Complete
        job_lock.release_lock(job_id, status="completed")
        db_session.refresh(job)
        assert job.status == "completed"
        assert job.completed_at is not None

    def test_full_lifecycle_failed(self, db_session, book, job_lock):
        """1.2: acquire → start → release(failed)."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)
        job_lock.release_lock(job_id, status="failed", error="Test error")

        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert job.status == "failed"
        assert job.error_message == "Test error"
        assert job.completed_at is not None

    def test_acquire_twice_raises(self, db_session, book, job_lock):
        """1.3: Second acquire for same book raises JobLockError."""
        job_lock.acquire_lock(book.id, "extraction")

        with pytest.raises(JobLockError, match="already pending"):
            job_lock.acquire_lock(book.id, "extraction")

    def test_acquire_after_completed(self, db_session, book, job_lock):
        """1.4: New lock can be acquired after previous job completed."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)
        job_lock.release_lock(job_id, status="completed")

        # Should succeed
        new_job_id = job_lock.acquire_lock(book.id, "extraction")
        assert new_job_id != job_id

    def test_acquire_after_failed(self, db_session, book, job_lock):
        """1.4: New lock can be acquired after previous job failed."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)
        job_lock.release_lock(job_id, status="failed", error="crashed")

        new_job_id = job_lock.acquire_lock(book.id, "extraction")
        assert new_job_id != job_id


class TestInvalidTransitions:
    """Test 1.5: Invalid state transitions."""

    def test_start_completed_job_raises(self, db_session, book, job_lock):
        """Cannot start a completed job."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)
        job_lock.release_lock(job_id, status="completed")

        with pytest.raises(InvalidStateTransition):
            job_lock.start_job(job_id)

    def test_start_running_job_raises(self, db_session, book, job_lock):
        """Cannot start an already running job."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)

        with pytest.raises(InvalidStateTransition, match="Cannot start job in 'running'"):
            job_lock.start_job(job_id)

    def test_release_completed_is_noop(self, db_session, book, job_lock):
        """Releasing an already-completed job is a silent no-op."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)
        job_lock.release_lock(job_id, status="completed")

        # Should not raise, just log warning
        job_lock.release_lock(job_id, status="failed", error="late error")
        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert job.status == "completed"  # Unchanged


class TestStaleDetection:
    """Tests 1.6-1.8: Stale job detection."""

    def test_stale_heartbeat_expired(self, db_session, book, job_lock):
        """1.6: Job with expired heartbeat is auto-marked failed."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)

        # Manually expire the heartbeat
        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        job.heartbeat_at = datetime.utcnow() - HEARTBEAT_STALE_THRESHOLD - timedelta(seconds=10)
        db_session.commit()

        # get_latest_job should detect and mark it failed
        result = job_lock.get_latest_job(book.id)
        assert result["status"] == "failed"
        assert "interrupted" in result["error_message"].lower()

    def test_stale_no_heartbeat(self, db_session, book, job_lock):
        """1.7: Job with no heartbeat and old started_at is marked failed."""
        job_id = job_lock.acquire_lock(book.id, "extraction")

        # Manually set to running without heartbeat (simulate edge case)
        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        job.status = "running"
        job.heartbeat_at = None
        job.started_at = datetime.utcnow() - HEARTBEAT_STALE_THRESHOLD - timedelta(seconds=10)
        db_session.commit()

        result = job_lock.get_latest_job(book.id)
        assert result["status"] == "failed"

    def test_acquire_when_stale_job_exists(self, db_session, book, job_lock):
        """1.8: Stale job is auto-recovered, new lock acquired."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)

        # Expire heartbeat
        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        job.heartbeat_at = datetime.utcnow() - HEARTBEAT_STALE_THRESHOLD - timedelta(seconds=10)
        db_session.commit()

        # New acquire should detect stale, mark it failed, and create new
        new_job_id = job_lock.acquire_lock(book.id, "extraction")
        assert new_job_id != job_id

        # Old job should be failed
        old_job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert old_job.status == "failed"


class TestProgressUpdate:
    """Test 1.9 and 6.6: Progress update behavior."""

    def test_progress_on_cancelled_job_is_noop(self, db_session, book, job_lock):
        """1.9: update_progress on failed job does not crash."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)
        job_lock.release_lock(job_id, status="failed", error="cancelled")

        # Should not raise
        job_lock.update_progress(job_id, current_item=5, completed=5, failed=0)

        # Status should remain failed
        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert job.status == "failed"

    def test_duplicate_progress_update_is_idempotent(self, db_session, book, job_lock):
        """6.6: Duplicate update_progress calls with same args are idempotent."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=10)
        job_lock.start_job(job_id)

        detail = json.dumps({"page_errors": {}, "stats": {"subtopics_created": 3}})

        job_lock.update_progress(job_id, current_item=5, completed=5, failed=0, detail=detail)
        job_lock.update_progress(job_id, current_item=5, completed=5, failed=0, detail=detail)

        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert job.completed_items == 5
        assert job.current_item == 5

    def test_progress_updates_heartbeat(self, db_session, book, job_lock):
        """Each progress update refreshes the heartbeat."""
        job_id = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id)

        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        first_heartbeat = job.heartbeat_at

        # Small delay to ensure different timestamp
        time.sleep(0.01)
        job_lock.update_progress(job_id, current_item=1, completed=1, failed=0)

        db_session.refresh(job)
        assert job.heartbeat_at >= first_heartbeat

    def test_progress_with_last_completed_item(self, db_session, book, job_lock):
        """last_completed_item is tracked correctly for resume."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=10)
        job_lock.start_job(job_id)

        job_lock.update_progress(job_id, current_item=3, completed=3, failed=0, last_completed_item=3)
        job_lock.update_progress(job_id, current_item=5, completed=4, failed=1, last_completed_item=4)

        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        assert job.last_completed_item == 4
        assert job.failed_items == 1

    def test_progress_detail_json(self, db_session, book, job_lock):
        """progress_detail stores full JSON for per-page errors."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=10)
        job_lock.start_job(job_id)

        detail = json.dumps({
            "page_errors": {"5": {"error": "Rate limit", "error_type": "retryable"}},
            "stats": {"subtopics_created": 2, "subtopics_merged": 1},
        })
        job_lock.update_progress(job_id, current_item=6, completed=4, failed=1, detail=detail)

        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        parsed = json.loads(job.progress_detail)
        assert "5" in parsed["page_errors"]
        assert parsed["page_errors"]["5"]["error_type"] == "retryable"


class TestGetJob:
    """Test get_job and get_latest_job."""

    def test_get_job_returns_dict(self, db_session, book, job_lock):
        """get_job returns full dict with all fields."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=50)
        result = job_lock.get_job(job_id)

        assert result["job_id"] == job_id
        assert result["book_id"] == book.id
        assert result["job_type"] == "extraction"
        assert result["status"] == "pending"
        assert result["total_items"] == 50
        assert result["completed_items"] == 0
        assert result["failed_items"] == 0

    def test_get_job_not_found(self, db_session, book, job_lock):
        """get_job returns None for nonexistent job."""
        assert job_lock.get_job("nonexistent") is None

    def test_get_latest_job_by_type(self, db_session, book, job_lock):
        """get_latest_job filters by job_type."""
        job_id1 = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id1)
        job_lock.release_lock(job_id1, status="completed")

        job_id2 = job_lock.acquire_lock(book.id, "finalization")
        job_lock.start_job(job_id2)
        job_lock.release_lock(job_id2, status="completed")

        result = job_lock.get_latest_job(book.id, job_type="extraction")
        assert result["job_id"] == job_id1

        result = job_lock.get_latest_job(book.id, job_type="finalization")
        assert result["job_id"] == job_id2

    def test_get_latest_job_returns_most_recent(self, db_session, book, job_lock):
        """get_latest_job returns the most recently started job."""
        job_id1 = job_lock.acquire_lock(book.id, "extraction")
        job_lock.start_job(job_id1)
        job_lock.release_lock(job_id1, status="completed")

        job_id2 = job_lock.acquire_lock(book.id, "extraction")

        result = job_lock.get_latest_job(book.id)
        assert result["job_id"] == job_id2

    def test_get_latest_job_no_jobs(self, db_session, book, job_lock):
        """get_latest_job returns None when no jobs exist."""
        assert job_lock.get_latest_job(book.id) is None


class TestErrorPathInvariants:
    """Test 6.9: Error-path state invariants."""

    def test_failed_job_has_required_fields(self, db_session, book, job_lock):
        """After failure: status=failed, error_message set, completed_at set."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=10)
        job_lock.start_job(job_id)
        job_lock.update_progress(job_id, current_item=3, completed=3, failed=0, last_completed_item=3)
        job_lock.release_lock(job_id, status="failed", error="OpenAI rate limit")

        result = job_lock.get_job(job_id)
        assert result["status"] == "failed"
        assert result["error_message"] is not None
        assert result["completed_at"] is not None
        assert result["last_completed_item"] == 3

    def test_stale_job_has_required_fields(self, db_session, book, job_lock):
        """After stale detection: status=failed, error_message set."""
        job_id = job_lock.acquire_lock(book.id, "extraction", total_items=10)
        job_lock.start_job(job_id)
        job_lock.update_progress(job_id, current_item=5, completed=5, failed=0, last_completed_item=5)

        # Expire heartbeat
        job = db_session.query(BookJob).filter(BookJob.id == job_id).first()
        job.heartbeat_at = datetime.utcnow() - HEARTBEAT_STALE_THRESHOLD - timedelta(seconds=10)
        db_session.commit()

        result = job_lock.get_latest_job(book.id)
        assert result["status"] == "failed"
        assert result["error_message"] is not None
        assert "interrupted" in result["error_message"].lower()
        assert result["completed_at"] is not None
        assert result["last_completed_item"] == 5
