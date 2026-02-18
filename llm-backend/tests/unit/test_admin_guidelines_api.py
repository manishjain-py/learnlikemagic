"""
Comprehensive tests for study_plans/api/admin.py

Tests the FastAPI router endpoints for guideline review, approval, deletion,
study plan generation, and book-level guideline management.
"""
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

import pytest

# ---------------------------------------------------------------------------
# Pre-import mocking: prevent real database/config/S3 from being loaded
# ---------------------------------------------------------------------------
_mock_settings = MagicMock()
_mock_settings.openai_api_key = "fake-key"
_mock_settings.gemini_api_key = "fake-key"
_mock_settings.aws_region = "us-east-1"
_mock_settings.aws_s3_bucket = "test-bucket"
_mock_settings.database_url = "postgresql://user:pass@localhost:5432/testdb"
_mock_settings.db_pool_size = 5
_mock_settings.db_max_overflow = 10
_mock_settings.db_pool_timeout = 30
_mock_settings.log_level = "INFO"
_mock_settings.environment = "test"

_mock_config = MagicMock()
_mock_config.get_settings = MagicMock(return_value=_mock_settings)
sys.modules.setdefault("config", _mock_config)

_mock_db_module = MagicMock()
_mock_db_module.get_db = MagicMock()
sys.modules.setdefault("database", _mock_db_module)

for mod_name in [
    "openai",
    "boto3",
    "botocore",
    "botocore.exceptions",
    "PIL",
    "PIL.Image",
    "google",
    "google.generativeai",
]:
    sys.modules.setdefault(mod_name, MagicMock())

# ---------------------------------------------------------------------------
# Now safe to import the actual router
# ---------------------------------------------------------------------------
from fastapi import FastAPI
from fastapi.testclient import TestClient

from study_plans.api.admin import router, get_llm_service

# Build test app
app = FastAPI()
app.include_router(router)

# Override get_db
from database import get_db

_mock_db_session = MagicMock()


def override_get_db():
    return _mock_db_session


def override_llm_service():
    return MagicMock()


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_llm_service] = override_llm_service

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_book(book_id="book-1", title="Math Book", grade=3, subject="Mathematics",
               board="CBSE", country="India", status="active"):
    book = MagicMock()
    book.id = book_id
    book.title = title
    book.grade = grade
    book.subject = subject
    book.board = board
    book.country = country
    book.status = status
    return book


def _mock_guideline(guideline_id="g-1", topic="Fractions", subtopic="Adding",
                     guideline_text="Teach step by step", review_status="TO_BE_REVIEWED",
                     book_id="book-1", country="India", board="CBSE", grade=3,
                     subject="Mathematics"):
    g = MagicMock()
    g.id = guideline_id
    g.topic = topic
    g.subtopic = subtopic
    g.guideline = guideline_text
    g.review_status = review_status
    g.book_id = book_id
    g.country = country
    g.board = board
    g.grade = grade
    g.subject = subject
    g.created_at = datetime(2024, 1, 1)
    g.updated_at = datetime(2024, 1, 2)
    return g


def _setup_query_for_guidelines(mock_db, guidelines):
    """Set up a mock DB session that returns guidelines on query chains."""
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.all.return_value = guidelines
    mock_query.first.return_value = guidelines[0] if guidelines else None
    mock_query.count.return_value = len(guidelines)
    mock_db.query.return_value = mock_query
    return mock_query


# ===========================================================================
# Book guideline listing
# ===========================================================================


class TestListBooksWithGuidelines:
    """GET /admin/guidelines/books"""

    @patch("study_plans.api.admin.S3Client")
    def test_list_books_success(self, MockS3):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [book]

        # For TeachingGuideline count query
        mock_tg_query = MagicMock()
        mock_tg_query.filter.return_value = mock_tg_query
        mock_tg_query.count.return_value = 2

        # Switch behavior based on the model being queried
        def query_side_effect(model):
            from book_ingestion.models.database import Book as BookModel
            from shared.models.entities import TeachingGuideline
            if model is BookModel:
                return mock_query
            elif model is TeachingGuideline:
                return mock_tg_query
            return MagicMock()

        _mock_db_session.query.side_effect = query_side_effect

        # S3 returns index and page index
        s3 = MockS3.return_value
        s3.download_json.side_effect = [
            # index.json
            {
                "book_id": "book-1",
                "topics": [
                    {
                        "topic_key": "fractions",
                        "topic_title": "Fractions",
                        "subtopics": [
                            {
                                "subtopic_key": "adding",
                                "subtopic_title": "Adding",
                                "status": "final",
                                "page_range": "1-5",
                            }
                        ],
                    }
                ],
                "version": 1,
                "last_updated": "2024-01-01T00:00:00",
            },
            # page_index.json
            {
                "book_id": "book-1",
                "pages": {
                    "1": {"topic_key": "fractions", "subtopic_key": "adding", "confidence": 0.9}
                },
                "version": 1,
                "last_updated": "2024-01-01T00:00:00",
            },
        ]

        resp = client.get("/admin/guidelines/books")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["book_id"] == "book-1"
        assert data[0]["topics_count"] == 1

    @patch("study_plans.api.admin.S3Client")
    def test_list_books_empty(self, MockS3):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        _mock_db_session.query.side_effect = None
        _mock_db_session.query.return_value = mock_query

        resp = client.get("/admin/guidelines/books")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetBookTopics:
    """GET /admin/guidelines/books/{book_id}/topics"""

    @patch("study_plans.api.admin.S3Client")
    def test_get_topics_success(self, MockS3):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        s3 = MockS3.return_value
        s3.download_json.return_value = {
            "book_id": "book-1",
            "topics": [
                {
                    "topic_key": "fractions",
                    "topic_title": "Fractions",
                    "subtopics": [
                        {
                            "subtopic_key": "adding",
                            "subtopic_title": "Adding Fractions",
                            "status": "final",
                            "page_range": "1-5",
                        }
                    ],
                }
            ],
            "version": 1,
            "last_updated": "2024-01-01T00:00:00",
        }

        resp = client.get("/admin/guidelines/books/book-1/topics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["topic_key"] == "fractions"
        assert len(data[0]["subtopics"]) == 1

    @patch("study_plans.api.admin.S3Client")
    def test_get_topics_book_not_found(self, MockS3):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.get("/admin/guidelines/books/missing/topics")
        assert resp.status_code == 404

    @patch("study_plans.api.admin.S3Client")
    def test_get_topics_no_guidelines(self, MockS3):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        s3 = MockS3.return_value
        s3.download_json.side_effect = Exception("Not found")

        resp = client.get("/admin/guidelines/books/book-1/topics")
        assert resp.status_code == 404
        assert "Guidelines not found" in resp.json()["detail"]


class TestGetSubtopicGuideline:
    """GET /admin/guidelines/books/{book_id}/subtopics/{subtopic_key}"""

    @patch("study_plans.api.admin.S3Client")
    def test_get_subtopic_success(self, MockS3):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        s3 = MockS3.return_value
        s3.download_json.return_value = {
            "topic_key": "fractions",
            "topic_title": "Fractions",
            "subtopic_key": "adding",
            "subtopic_title": "Adding Fractions",
            "subtopic_summary": "Learn to add fractions",
            "source_page_start": 1,
            "source_page_end": 5,
            "guidelines": "Full teaching guidelines text.",
            "version": 1,
        }

        resp = client.get(
            "/admin/guidelines/books/book-1/subtopics/adding",
            params={"topic_key": "fractions"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["subtopic_key"] == "adding"
        assert "guidelines" in data

    @patch("study_plans.api.admin.S3Client")
    def test_get_subtopic_book_not_found(self, MockS3):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.get(
            "/admin/guidelines/books/missing/subtopics/adding",
            params={"topic_key": "fractions"},
        )
        assert resp.status_code == 404

    @patch("study_plans.api.admin.S3Client")
    def test_get_subtopic_shard_not_found(self, MockS3):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        s3 = MockS3.return_value
        s3.download_json.side_effect = Exception("Key not found")

        resp = client.get(
            "/admin/guidelines/books/book-1/subtopics/missing",
            params={"topic_key": "fractions"},
        )
        assert resp.status_code == 404


class TestUpdateSubtopicDisabled:
    """PUT /admin/guidelines/books/{book_id}/subtopics/{subtopic_key}"""

    def test_update_subtopic_returns_501(self):
        resp = client.put(
            "/admin/guidelines/books/book-1/subtopics/adding",
            params={"topic_key": "fractions"},
            json={"teaching_description": "Updated text"},
        )
        assert resp.status_code == 501
        assert "Manual editing disabled" in resp.json()["detail"]


# ===========================================================================
# Page assignments
# ===========================================================================


class TestGetPageAssignments:
    """GET /admin/guidelines/books/{book_id}/page-assignments"""

    @patch("study_plans.api.admin.S3Client")
    def test_page_assignments_success(self, MockS3):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        s3 = MockS3.return_value
        s3.download_json.return_value = {
            "book_id": "book-1",
            "pages": {
                "1": {"topic_key": "fractions", "subtopic_key": "adding", "confidence": 0.95},
                "2": {"topic_key": "fractions", "subtopic_key": "adding", "confidence": 0.88},
            },
            "version": 1,
            "last_updated": "2024-01-01T00:00:00",
        }

        resp = client.get("/admin/guidelines/books/book-1/page-assignments")
        assert resp.status_code == 200
        data = resp.json()
        assert "1" in data
        assert data["1"]["topic_key"] == "fractions"

    @patch("study_plans.api.admin.S3Client")
    def test_page_assignments_book_not_found(self, MockS3):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.get("/admin/guidelines/books/missing/page-assignments")
        assert resp.status_code == 404


# ===========================================================================
# Review endpoints
# ===========================================================================


class TestListGuidelinesForReview:
    """GET /admin/guidelines/review"""

    def test_list_guidelines_success(self):
        g1 = _mock_guideline(guideline_id="g-1")
        g2 = _mock_guideline(guideline_id="g-2", review_status="APPROVED")

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [g1, g2]
        _mock_db_session.query.return_value = mock_query

        resp = client.get("/admin/guidelines/review")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "g-1"

    def test_list_guidelines_with_filters(self):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []
        _mock_db_session.query.return_value = mock_query

        resp = client.get(
            "/admin/guidelines/review",
            params={"country": "India", "grade": 3, "status": "APPROVED"},
        )
        assert resp.status_code == 200


class TestGetGuidelineFilterOptions:
    """GET /admin/guidelines/review/filters"""

    def test_filter_options(self):
        from sqlalchemy import distinct

        mock_query = MagicMock()
        mock_query.all.return_value = [("India",)]
        mock_query.count.return_value = 5
        mock_query.filter.return_value = mock_query
        _mock_db_session.query.return_value = mock_query

        resp = client.get("/admin/guidelines/review/filters")
        assert resp.status_code == 200
        data = resp.json()
        assert "countries" in data
        assert "counts" in data


class TestReviewBookGuidelines:
    """GET /admin/guidelines/books/{book_id}/review"""

    def test_review_guidelines_success(self):
        g = _mock_guideline()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [g]
        _mock_db_session.query.return_value = mock_query

        resp = client.get("/admin/guidelines/books/book-1/review")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "g-1"

    def test_review_guidelines_with_status_filter(self):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        _mock_db_session.query.return_value = mock_query

        resp = client.get(
            "/admin/guidelines/books/book-1/review",
            params={"status": "APPROVED"},
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# Approve / Delete guideline
# ===========================================================================


class TestApproveGuideline:
    """POST /admin/guidelines/{guideline_id}/approve"""

    def test_approve_guideline_success(self):
        g = _mock_guideline(review_status="TO_BE_REVIEWED")
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = g
        _mock_db_session.query.return_value = mock_query

        resp = client.post(
            "/admin/guidelines/g-1/approve",
            json={"approved": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["review_status"] == "APPROVED"
        _mock_db_session.commit.assert_called()

    def test_reject_guideline(self):
        g = _mock_guideline(review_status="APPROVED")
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = g
        _mock_db_session.query.return_value = mock_query

        resp = client.post(
            "/admin/guidelines/g-1/approve",
            json={"approved": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["review_status"] == "TO_BE_REVIEWED"

    def test_approve_guideline_not_found(self):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.post(
            "/admin/guidelines/missing/approve",
            json={"approved": True},
        )
        assert resp.status_code == 404
        assert "Guideline not found" in resp.json()["detail"]


class TestDeleteGuideline:
    """DELETE /admin/guidelines/{guideline_id}"""

    def test_delete_guideline_success(self):
        g = _mock_guideline()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = g
        _mock_db_session.query.return_value = mock_query

        resp = client.delete("/admin/guidelines/g-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "g-1"
        _mock_db_session.delete.assert_called_once_with(g)
        _mock_db_session.commit.assert_called()

    def test_delete_guideline_not_found(self):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.delete("/admin/guidelines/missing")
        assert resp.status_code == 404
        assert "Guideline not found" in resp.json()["detail"]


# ===========================================================================
# Study plan endpoints
# ===========================================================================


class TestGenerateStudyPlan:
    """POST /admin/guidelines/{guideline_id}/generate-study-plan"""

    @patch("study_plans.api.admin.StudyPlanOrchestrator")
    def test_generate_study_plan_success(self, MockOrch):
        g = _mock_guideline()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = g
        _mock_db_session.query.return_value = mock_query

        orch = MockOrch.return_value
        orch.generate_study_plan.return_value = {"steps": [{"title": "Step 1"}]}

        resp = client.post("/admin/guidelines/g-1/generate-study-plan")
        assert resp.status_code == 200
        assert "steps" in resp.json()

    @patch("study_plans.api.admin.StudyPlanOrchestrator")
    def test_generate_study_plan_not_found(self, MockOrch):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.post("/admin/guidelines/missing/generate-study-plan")
        assert resp.status_code == 404

    @patch("study_plans.api.admin.StudyPlanOrchestrator")
    def test_generate_study_plan_error(self, MockOrch):
        g = _mock_guideline()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = g
        _mock_db_session.query.return_value = mock_query

        orch = MockOrch.return_value
        orch.generate_study_plan.side_effect = RuntimeError("LLM timeout")

        resp = client.post("/admin/guidelines/g-1/generate-study-plan")
        assert resp.status_code == 500


class TestGetStudyPlan:
    """GET /admin/guidelines/{guideline_id}/study-plan"""

    @patch("study_plans.api.admin.StudyPlanOrchestrator")
    def test_get_study_plan_success(self, MockOrch):
        orch = MockOrch.return_value
        orch.get_study_plan.return_value = {"steps": [{"title": "Step 1"}]}

        resp = client.get("/admin/guidelines/g-1/study-plan")
        assert resp.status_code == 200
        assert "steps" in resp.json()

    @patch("study_plans.api.admin.StudyPlanOrchestrator")
    def test_get_study_plan_not_found(self, MockOrch):
        orch = MockOrch.return_value
        orch.get_study_plan.return_value = None

        resp = client.get("/admin/guidelines/missing/study-plan")
        assert resp.status_code == 404


class TestBulkGenerateStudyPlans:
    """POST /admin/guidelines/bulk-generate-study-plans"""

    @patch("study_plans.api.admin.StudyPlanOrchestrator")
    def test_bulk_generate_success(self, MockOrch):
        orch = MockOrch.return_value
        orch.generate_study_plan.return_value = {"steps": []}

        resp = client.post(
            "/admin/guidelines/bulk-generate-study-plans",
            json={"guideline_ids": ["g-1", "g-2"], "force_regenerate": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["success"]) == 2
        assert len(data["failed"]) == 0

    @patch("study_plans.api.admin.StudyPlanOrchestrator")
    def test_bulk_generate_partial_failure(self, MockOrch):
        orch = MockOrch.return_value
        orch.generate_study_plan.side_effect = [
            {"steps": []},
            RuntimeError("fail"),
        ]

        resp = client.post(
            "/admin/guidelines/bulk-generate-study-plans",
            json={"guideline_ids": ["g-1", "g-2"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["success"]) == 1
        assert len(data["failed"]) == 1


# ===========================================================================
# Extract and finalize endpoints
# ===========================================================================


class TestExtractGuidelinesForPages:
    """POST /admin/guidelines/books/{book_id}/extract"""

    @patch("book_ingestion.services.job_lock_service.JobLockService")
    @patch("book_ingestion.services.guideline_extraction_orchestrator.GuidelineExtractionOrchestrator")
    @patch("study_plans.api.admin.S3Client")
    def test_extract_success(self, MockS3, MockOrch, MockJobLock):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        # Job lock
        job_svc = MockJobLock.return_value
        job_svc.acquire_lock.return_value = "job-1"

        # S3 page index
        s3 = MockS3.return_value
        s3.download_json.return_value = {
            "book_id": "book-1",
            "pages": {"1": {"topic_key": "t", "subtopic_key": "s", "confidence": 0.9}},
            "version": 1,
            "last_updated": "2024-01-01T00:00:00",
        }

        orch = MockOrch.return_value
        orch.extract_guidelines_for_book.return_value = {
            "pages_processed": 5,
            "subtopics_created": 3,
            "subtopics_merged": 1,
        }

        resp = client.post(
            "/admin/guidelines/books/book-1/extract",
            params={"start_page": 1, "end_page": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["pages_processed"] == 5

    @patch("study_plans.api.admin.S3Client")
    def test_extract_book_not_found(self, MockS3):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.post(
            "/admin/guidelines/books/missing/extract",
            params={"start_page": 1, "end_page": 5},
        )
        assert resp.status_code == 404


class TestFinalizeBookGuidelines:
    """POST /admin/guidelines/books/{book_id}/finalize"""

    @patch("book_ingestion.services.job_lock_service.JobLockService")
    @patch("book_ingestion.services.guideline_extraction_orchestrator.GuidelineExtractionOrchestrator")
    @patch("study_plans.api.admin.S3Client")
    def test_finalize_success(self, MockS3, MockOrch, MockJobLock):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        job_svc = MockJobLock.return_value
        job_svc.acquire_lock.return_value = "job-1"

        s3 = MockS3.return_value
        s3.download_json.return_value = {
            "book_id": "book-1",
            "pages": {},
            "version": 1,
            "last_updated": "2024-01-01T00:00:00",
        }

        orch = MockOrch.return_value
        orch.finalize_book.return_value = {
            "subtopics_finalized": 4,
            "subtopics_renamed": 2,
            "duplicates_merged": 1,
        }

        resp = client.post("/admin/guidelines/books/book-1/finalize")
        assert resp.status_code == 200

    @patch("study_plans.api.admin.S3Client")
    def test_finalize_book_not_found(self, MockS3):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.post("/admin/guidelines/books/missing/finalize")
        assert resp.status_code == 404


class TestSyncToDatabase:
    """POST /admin/guidelines/books/{book_id}/sync-to-database"""

    @patch("book_ingestion.services.db_sync_service.DBSyncService")
    @patch("study_plans.api.admin.S3Client")
    def test_sync_success(self, MockS3, MockDBSync):
        book = _mock_book()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = book
        _mock_db_session.query.return_value = mock_query

        sync_svc = MockDBSync.return_value
        sync_svc.sync_book_guidelines.return_value = {"synced_count": 10}

        resp = client.post("/admin/guidelines/books/book-1/sync-to-database")
        assert resp.status_code == 200
        data = resp.json()
        assert "10" in data["message"]

    @patch("study_plans.api.admin.S3Client")
    def test_sync_book_not_found(self, MockS3):
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        _mock_db_session.query.return_value = mock_query

        resp = client.post("/admin/guidelines/books/missing/sync-to-database")
        assert resp.status_code == 404
