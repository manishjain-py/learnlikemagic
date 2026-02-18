"""
Comprehensive tests for book_ingestion/api/routes.py

Tests the FastAPI router endpoints for book CRUD, page management,
and guideline generation/approval using mocked service dependencies.
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
]:
    sys.modules.setdefault(mod_name, MagicMock())

# ---------------------------------------------------------------------------
# Now safe to import the actual router
# ---------------------------------------------------------------------------
from fastapi import FastAPI
from fastapi.testclient import TestClient

from book_ingestion.api.routes import router

# Build test app
app = FastAPI()
app.include_router(router)

from database import get_db

_mock_db_session = MagicMock()


def override_get_db():
    return _mock_db_session


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_BOOK_RESPONSE = {
    "id": "ncert_math_3_2024",
    "title": "Math Book",
    "author": "NCERT",
    "edition": "1st",
    "edition_year": 2024,
    "country": "India",
    "board": "CBSE",
    "grade": 3,
    "subject": "Mathematics",
    "cover_image_s3_key": None,
    "s3_prefix": "books/ncert_math_3_2024/",
    "page_count": 0,
    "guideline_count": 0,
    "approved_guideline_count": 0,
    "has_active_job": False,
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00",
    "created_by": "admin",
}


def _book_response_obj(**overrides):
    from book_ingestion.models.schemas import BookResponse
    data = {**SAMPLE_BOOK_RESPONSE, **overrides}
    return BookResponse(**data)


def _book_detail_obj(**overrides):
    from book_ingestion.models.schemas import BookDetailResponse
    data = {
        "id": "ncert_math_3_2024",
        "title": "Math Book",
        "author": "NCERT",
        "edition": "1st",
        "edition_year": 2024,
        "country": "India",
        "board": "CBSE",
        "grade": 3,
        "subject": "Mathematics",
        "pages": [],
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    data.update(overrides)
    return BookDetailResponse(**data)


def _mock_book_orm():
    book = MagicMock()
    book.id = "ncert_math_3_2024"
    book.title = "Math Book"
    book.grade = 3
    book.subject = "Mathematics"
    book.board = "CBSE"
    book.country = "India"
    return book


# ===========================================================================
# Book CRUD tests
# ===========================================================================


class TestCreateBook:
    """POST /admin/books"""

    @patch("book_ingestion.api.routes.BookService")
    def test_create_book_success(self, MockBookService):
        service = MockBookService.return_value
        service.create_book.return_value = _book_response_obj()

        payload = {
            "title": "Math Book",
            "country": "India",
            "board": "CBSE",
            "grade": 3,
            "subject": "Mathematics",
        }
        resp = client.post("/admin/books", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "ncert_math_3_2024"
        assert data["grade"] == 3
        service.create_book.assert_called_once()

    @patch("book_ingestion.api.routes.BookService")
    def test_create_book_validation_error(self, MockBookService):
        service = MockBookService.return_value
        service.create_book.side_effect = ValueError("Duplicate title")

        payload = {
            "title": "Math Book",
            "country": "India",
            "board": "CBSE",
            "grade": 3,
            "subject": "Mathematics",
        }
        resp = client.post("/admin/books", json=payload)
        assert resp.status_code == 400
        assert "Duplicate title" in resp.json()["detail"]

    @patch("book_ingestion.api.routes.BookService")
    def test_create_book_server_error(self, MockBookService):
        service = MockBookService.return_value
        service.create_book.side_effect = RuntimeError("DB connection lost")

        payload = {
            "title": "Math Book",
            "country": "India",
            "board": "CBSE",
            "grade": 3,
            "subject": "Mathematics",
        }
        resp = client.post("/admin/books", json=payload)
        assert resp.status_code == 500
        assert "Failed to create book" in resp.json()["detail"]

    def test_create_book_missing_required_fields(self):
        resp = client.post("/admin/books", json={"grade": 3})
        assert resp.status_code == 422


class TestListBooks:
    """GET /admin/books"""

    @patch("book_ingestion.api.routes.BookService")
    def test_list_books_no_filter(self, MockBookService):
        from book_ingestion.models.schemas import BookListResponse
        service = MockBookService.return_value
        service.list_books.return_value = BookListResponse(
            books=[_book_response_obj()], total=1
        )

        resp = client.get("/admin/books")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["books"]) == 1

    @patch("book_ingestion.api.routes.BookService")
    def test_list_books_with_filters(self, MockBookService):
        from book_ingestion.models.schemas import BookListResponse
        service = MockBookService.return_value
        service.list_books.return_value = BookListResponse(books=[], total=0)

        resp = client.get(
            "/admin/books",
            params={"country": "India", "board": "CBSE", "grade": 3, "subject": "Mathematics"},
        )
        assert resp.status_code == 200
        call_kwargs = service.list_books.call_args[1]
        assert call_kwargs["country"] == "India"
        assert call_kwargs["grade"] == 3

    @patch("book_ingestion.api.routes.BookService")
    def test_list_books_server_error(self, MockBookService):
        service = MockBookService.return_value
        service.list_books.side_effect = RuntimeError("timeout")

        resp = client.get("/admin/books")
        assert resp.status_code == 500

    @patch("book_ingestion.api.routes.BookService")
    def test_list_books_pagination(self, MockBookService):
        from book_ingestion.models.schemas import BookListResponse
        service = MockBookService.return_value
        service.list_books.return_value = BookListResponse(books=[], total=0)

        resp = client.get("/admin/books", params={"limit": 10, "offset": 20})
        assert resp.status_code == 200
        call_kwargs = service.list_books.call_args[1]
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 20


class TestGetBook:
    """GET /admin/books/{book_id}"""

    @patch("book_ingestion.api.routes.BookService")
    def test_get_book_found(self, MockBookService):
        service = MockBookService.return_value
        service.get_book_detail.return_value = _book_detail_obj()

        resp = client.get("/admin/books/ncert_math_3_2024")
        assert resp.status_code == 200
        assert resp.json()["id"] == "ncert_math_3_2024"

    @patch("book_ingestion.api.routes.BookService")
    def test_get_book_not_found(self, MockBookService):
        service = MockBookService.return_value
        service.get_book_detail.return_value = None

        resp = client.get("/admin/books/missing_book")
        assert resp.status_code == 404
        assert "Book not found" in resp.json()["detail"]

    @patch("book_ingestion.api.routes.BookService")
    def test_get_book_server_error(self, MockBookService):
        service = MockBookService.return_value
        service.get_book_detail.side_effect = RuntimeError("unexpected")

        resp = client.get("/admin/books/ncert_math_3_2024")
        assert resp.status_code == 500


class TestDeleteBook:
    """DELETE /admin/books/{book_id}"""

    @patch("book_ingestion.api.routes.BookService")
    def test_delete_book_success(self, MockBookService):
        service = MockBookService.return_value
        service.delete_book.return_value = True

        resp = client.delete("/admin/books/ncert_math_3_2024")
        assert resp.status_code == 204

    @patch("book_ingestion.api.routes.BookService")
    def test_delete_book_not_found(self, MockBookService):
        service = MockBookService.return_value
        service.delete_book.return_value = False

        resp = client.delete("/admin/books/missing_book")
        assert resp.status_code == 404

    @patch("book_ingestion.api.routes.BookService")
    def test_delete_book_server_error(self, MockBookService):
        service = MockBookService.return_value
        service.delete_book.side_effect = RuntimeError("S3 failure")

        resp = client.delete("/admin/books/ncert_math_3_2024")
        assert resp.status_code == 500


# ===========================================================================
# Page management tests
# ===========================================================================


class TestApprovePage:
    """PUT /admin/books/{book_id}/pages/{page_num}/approve"""

    @patch("book_ingestion.api.routes.PageService")
    def test_approve_page_success(self, MockPageService):
        from book_ingestion.models.schemas import PageApproveResponse
        service = MockPageService.return_value
        service.approve_page.return_value = PageApproveResponse(
            page_num=1, status="approved"
        )

        resp = client.put("/admin/books/ncert_math_3_2024/pages/1/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    @patch("book_ingestion.api.routes.PageService")
    def test_approve_page_bad_request(self, MockPageService):
        service = MockPageService.return_value
        service.approve_page.side_effect = ValueError("already approved")

        resp = client.put("/admin/books/ncert_math_3_2024/pages/1/approve")
        assert resp.status_code == 400
        assert "already approved" in resp.json()["detail"]

    @patch("book_ingestion.api.routes.PageService")
    def test_approve_page_server_error(self, MockPageService):
        service = MockPageService.return_value
        service.approve_page.side_effect = RuntimeError("oops")

        resp = client.put("/admin/books/ncert_math_3_2024/pages/1/approve")
        assert resp.status_code == 500


class TestDeletePage:
    """DELETE /admin/books/{book_id}/pages/{page_num}"""

    @patch("book_ingestion.api.routes.PageService")
    def test_delete_page_success(self, MockPageService):
        service = MockPageService.return_value
        service.delete_page.return_value = True

        resp = client.delete("/admin/books/ncert_math_3_2024/pages/1")
        assert resp.status_code == 204

    @patch("book_ingestion.api.routes.PageService")
    def test_delete_page_not_found(self, MockPageService):
        service = MockPageService.return_value
        service.delete_page.return_value = False

        resp = client.delete("/admin/books/ncert_math_3_2024/pages/99")
        assert resp.status_code == 404

    @patch("book_ingestion.api.routes.PageService")
    def test_delete_page_value_error(self, MockPageService):
        service = MockPageService.return_value
        service.delete_page.side_effect = ValueError("Cannot delete approved page")

        resp = client.delete("/admin/books/ncert_math_3_2024/pages/1")
        assert resp.status_code == 400


class TestGetPage:
    """GET /admin/books/{book_id}/pages/{page_num}"""

    @patch("book_ingestion.api.routes.PageService")
    def test_get_page_success(self, MockPageService):
        service = MockPageService.return_value
        service.get_page_with_urls.return_value = {
            "page_num": 1,
            "image_url": "https://s3/image.png",
            "text": "OCR text content",
            "status": "approved",
        }

        resp = client.get("/admin/books/ncert_math_3_2024/pages/1")
        assert resp.status_code == 200
        assert resp.json()["page_num"] == 1

    @patch("book_ingestion.api.routes.PageService")
    def test_get_page_not_found(self, MockPageService):
        service = MockPageService.return_value
        service.get_page_with_urls.side_effect = ValueError("Page not found")

        resp = client.get("/admin/books/ncert_math_3_2024/pages/99")
        assert resp.status_code == 404


class TestUploadPage:
    """POST /admin/books/{book_id}/pages"""

    @patch("book_ingestion.api.routes.PageService")
    def test_upload_page_success(self, MockPageService):
        from book_ingestion.models.schemas import PageUploadResponse
        service = MockPageService.return_value
        service.upload_page.return_value = PageUploadResponse(
            page_num=1,
            image_url="https://s3/image.png",
            ocr_text="Sample OCR text",
            status="pending_review",
        )

        resp = client.post(
            "/admin/books/ncert_math_3_2024/pages",
            files={"image": ("page1.png", b"fake image data", "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["page_num"] == 1

    @patch("book_ingestion.api.routes.PageService")
    def test_upload_page_invalid_format(self, MockPageService):
        service = MockPageService.return_value
        service.upload_page.side_effect = ValueError("Unsupported file format")

        resp = client.post(
            "/admin/books/ncert_math_3_2024/pages",
            files={"image": ("page1.bmp", b"fake", "image/bmp")},
        )
        assert resp.status_code == 400


# ===========================================================================
# Guideline endpoints tests
# ===========================================================================


class TestGetGuidelines:
    """GET /admin/books/{book_id}/guidelines"""

    @patch("book_ingestion.services.index_management_service.IndexManagementService")
    @patch("book_ingestion.api.routes.S3Client")
    @patch("book_ingestion.api.routes.BookService")
    def test_get_guidelines_success(self, MockBookSvc, MockS3Cls, MockIndexMgrCls):
        # Book exists
        svc = MockBookSvc.return_value
        svc.get_book.return_value = _mock_book_orm()

        # Build mock index
        mock_subtopic_entry = MagicMock()
        mock_subtopic_entry.subtopic_key = "adding-fractions"
        mock_subtopic_entry.status = "final"
        mock_topic = MagicMock()
        mock_topic.topic_key = "fractions"
        mock_topic.subtopics = [mock_subtopic_entry]
        mock_index = MagicMock()
        mock_index.topics = [mock_topic]
        MockIndexMgrCls.return_value.load_index.return_value = mock_index

        # Shard data from S3
        MockS3Cls.return_value.download_json.return_value = {
            "topic_key": "fractions",
            "topic_title": "Fractions",
            "subtopic_key": "adding-fractions",
            "subtopic_title": "Adding Fractions",
            "source_page_start": 1,
            "source_page_end": 5,
            "version": 1,
            "guidelines": "Teach adding fractions step by step.",
        }

        resp = client.get("/admin/books/ncert_math_3_2024/guidelines")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_subtopics"] == 1
        assert data["guidelines"][0]["subtopic_key"] == "adding-fractions"
        assert data["guidelines"][0]["status"] == "final"

    @patch("book_ingestion.api.routes.BookService")
    def test_get_guidelines_book_not_found(self, MockBookSvc):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = None

        resp = client.get("/admin/books/missing/guidelines")
        assert resp.status_code == 404

    @patch("book_ingestion.services.index_management_service.IndexManagementService")
    @patch("book_ingestion.api.routes.S3Client")
    @patch("book_ingestion.api.routes.BookService")
    def test_get_guidelines_no_index(self, MockBookSvc, MockS3Cls, MockIndexMgrCls):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = _mock_book_orm()
        MockIndexMgrCls.return_value.load_index.side_effect = FileNotFoundError("no index")

        resp = client.get("/admin/books/ncert_math_3_2024/guidelines")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_subtopics"] == 0
        assert data["guidelines"] == []


class TestGetGuideline:
    """GET /admin/books/{book_id}/guidelines/{topic_key}/{subtopic_key}"""

    @patch("book_ingestion.services.index_management_service.IndexManagementService")
    @patch("book_ingestion.api.routes.S3Client")
    @patch("book_ingestion.api.routes.BookService")
    def test_get_single_guideline_success(self, MockBookSvc, MockS3, MockIndexMgrCls):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = _mock_book_orm()

        # Index with matching entry
        mock_subtopic = MagicMock()
        mock_subtopic.subtopic_key = "adding-fractions"
        mock_subtopic.status = "final"
        mock_topic = MagicMock()
        mock_topic.topic_key = "fractions"
        mock_topic.subtopics = [mock_subtopic]
        mock_index = MagicMock()
        mock_index.topics = [mock_topic]
        MockIndexMgrCls.return_value.load_index.return_value = mock_index

        # Shard data
        MockS3.return_value.download_json.return_value = {
            "topic_key": "fractions",
            "topic_title": "Fractions",
            "subtopic_key": "adding-fractions",
            "subtopic_title": "Adding Fractions",
            "source_page_start": 1,
            "source_page_end": 5,
            "version": 1,
            "guidelines": "Full guidelines text",
        }

        resp = client.get("/admin/books/ncert_math_3_2024/guidelines/fractions/adding-fractions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["subtopic_key"] == "adding-fractions"
        assert data["status"] == "final"

    @patch("book_ingestion.api.routes.BookService")
    def test_get_guideline_book_not_found(self, MockBookSvc):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = None

        resp = client.get("/admin/books/missing/guidelines/t/s")
        assert resp.status_code == 404


class TestGenerateGuidelines:
    """POST /admin/books/{book_id}/generate-guidelines"""

    @patch("book_ingestion.api.routes.GuidelineExtractionOrchestrator")
    @patch("book_ingestion.api.routes.OpenAI")
    @patch("book_ingestion.api.routes.S3Client")
    @patch("book_ingestion.api.routes.BookService")
    def test_generate_guidelines_success(self, MockBookSvc, MockS3, MockOpenAI, MockOrch):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = _mock_book_orm()

        MockS3.return_value.download_json.return_value = {"total_pages": 10}

        orch = MockOrch.return_value
        orch.extract_guidelines_for_book = AsyncMock(
            return_value={
                "pages_processed": 10,
                "subtopics_created": 5,
                "subtopics_merged": 1,
                "subtopics_finalized": 4,
                "duplicates_merged": 0,
                "errors": [],
                "warnings": [],
            }
        )

        resp = client.post(
            "/admin/books/ncert_math_3_2024/generate-guidelines",
            json={"start_page": 1, "end_page": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["pages_processed"] == 10

    @patch("book_ingestion.api.routes.BookService")
    def test_generate_guidelines_book_not_found(self, MockBookSvc):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = None

        resp = client.post(
            "/admin/books/missing/generate-guidelines",
            json={},
        )
        assert resp.status_code == 404


class TestFinalizeGuidelines:
    """POST /admin/books/{book_id}/finalize"""

    @patch("book_ingestion.api.routes.GuidelineExtractionOrchestrator")
    @patch("book_ingestion.api.routes.OpenAI")
    @patch("book_ingestion.api.routes.S3Client")
    @patch("book_ingestion.api.routes.BookService")
    def test_finalize_success(self, MockBookSvc, MockS3, MockOpenAI, MockOrch):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = _mock_book_orm()

        orch = MockOrch.return_value
        orch.finalize_book = AsyncMock(
            return_value={
                "subtopics_finalized": 4,
                "subtopics_renamed": 2,
                "duplicates_merged": 1,
            }
        )

        resp = client.post(
            "/admin/books/ncert_math_3_2024/finalize",
            json={"auto_sync_to_db": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["subtopics_finalized"] == 4


class TestApproveGuidelines:
    """PUT /admin/books/{book_id}/guidelines/approve"""

    @patch("book_ingestion.api.routes.BookService")
    def test_approve_guidelines_success(self, MockBookSvc):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = _mock_book_orm()

        with patch("book_ingestion.api.routes.S3Client") as MockS3, \
             patch("book_ingestion.services.index_management_service.IndexManagementService.__init__", return_value=None), \
             patch("book_ingestion.services.index_management_service.IndexManagementService.load_index") as mock_load, \
             patch("book_ingestion.services.index_management_service.IndexManagementService.update_subtopic_status") as mock_update, \
             patch("book_ingestion.services.index_management_service.IndexManagementService.save_index") as mock_save, \
             patch("book_ingestion.services.db_sync_service.DBSyncService.__init__", return_value=None), \
             patch("book_ingestion.services.db_sync_service.DBSyncService.sync_shard") as mock_sync:

            # Build index with one non-final subtopic
            mock_subtopic = MagicMock()
            mock_subtopic.subtopic_key = "adding-fractions"
            mock_subtopic.status = "stable"
            mock_topic = MagicMock()
            mock_topic.topic_key = "fractions"
            mock_topic.subtopics = [mock_subtopic]
            mock_index = MagicMock()
            mock_index.topics = [mock_topic]
            mock_load.return_value = mock_index

            # After updating, status becomes "final"
            updated_subtopic = MagicMock()
            updated_subtopic.subtopic_key = "adding-fractions"
            updated_subtopic.status = "final"
            updated_topic = MagicMock()
            updated_topic.topic_key = "fractions"
            updated_topic.subtopics = [updated_subtopic]
            updated_index = MagicMock()
            updated_index.topics = [updated_topic]
            mock_update.return_value = updated_index

            # Shard data
            MockS3.return_value.download_json.return_value = {
                "topic_key": "fractions",
                "topic_title": "Fractions",
                "subtopic_key": "adding-fractions",
                "subtopic_title": "Adding Fractions",
                "source_page_start": 1,
                "source_page_end": 5,
                "version": 1,
                "guidelines": "Guidelines text",
            }

            mock_sync.return_value = "guid-1"

            resp = client.put("/admin/books/ncert_math_3_2024/guidelines/approve")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "approved"
            assert data["approved_count"] == 1

    @patch("book_ingestion.api.routes.BookService")
    def test_approve_guidelines_book_not_found(self, MockBookSvc):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = None

        resp = client.put("/admin/books/missing/guidelines/approve")
        assert resp.status_code == 404


class TestRejectGuidelines:
    """DELETE /admin/books/{book_id}/guidelines"""

    @patch("book_ingestion.api.routes.S3Client")
    @patch("book_ingestion.api.routes.BookService")
    def test_reject_guidelines_success(self, MockBookSvc, MockS3):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = _mock_book_orm()

        resp = client.delete("/admin/books/ncert_math_3_2024/guidelines")
        assert resp.status_code == 204

    @patch("book_ingestion.api.routes.BookService")
    def test_reject_guidelines_book_not_found(self, MockBookSvc):
        svc = MockBookSvc.return_value
        svc.get_book.return_value = None

        resp = client.delete("/admin/books/missing/guidelines")
        assert resp.status_code == 404
