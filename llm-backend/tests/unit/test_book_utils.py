"""
Tests for book ingestion utilities:
- S3Client
- JobLockService
- StabilityDetectorService

All external dependencies (AWS, DB) are mocked.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from book_ingestion.models.guideline_models import (
    GuidelinesIndex,
    TopicIndexEntry,
    SubtopicIndexEntry,
    PageIndex,
    PageAssignment,
)


# ============================================================================
# S3Client Tests
# ============================================================================

class TestS3Client:
    """Tests for S3Client."""

    @patch("book_ingestion.utils.s3_client.boto3")
    @patch("book_ingestion.utils.s3_client.get_settings")
    def _make_client(self, mock_settings, mock_boto3):
        mock_settings.return_value.aws_s3_bucket = "test-bucket"
        mock_settings.return_value.aws_region = "us-east-1"
        mock_s3_client = MagicMock()
        mock_boto3.client.return_value = mock_s3_client

        from book_ingestion.utils.s3_client import S3Client
        client = S3Client()
        return client, mock_s3_client

    def test_upload_file(self):
        client, mock_s3 = self._make_client()

        result = client.upload_file("/tmp/test.png", "books/test/1.png")

        mock_s3.upload_file.assert_called_once_with(
            "/tmp/test.png", "test-bucket", "books/test/1.png"
        )
        assert "s3://" in result
        assert "test-bucket" in result

    def test_upload_bytes(self):
        client, mock_s3 = self._make_client()

        result = client.upload_bytes(b"hello world", "test/file.txt")

        mock_s3.put_object.assert_called_once()
        assert "s3://" in result

    def test_upload_bytes_with_content_type(self):
        client, mock_s3 = self._make_client()

        result = client.upload_bytes(b"hello", "test/file.txt", content_type="text/plain")

        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["ContentType"] == "text/plain"

    def test_upload_bytes_type_guard_data_not_bytes(self):
        client, _ = self._make_client()

        with pytest.raises(TypeError, match="data must be bytes-like"):
            client.upload_bytes("not bytes", "test/key")

    def test_upload_bytes_type_guard_key_not_str(self):
        client, _ = self._make_client()

        with pytest.raises(TypeError, match="s3_key must be str"):
            client.upload_bytes(b"data", 123)

    def test_download_file(self):
        client, mock_s3 = self._make_client()

        result = client.download_file("books/test/1.png", "/tmp/out.png")

        mock_s3.download_file.assert_called_once_with(
            "test-bucket", "books/test/1.png", "/tmp/out.png"
        )
        assert result == "/tmp/out.png"

    def test_download_bytes(self):
        client, mock_s3 = self._make_client()
        mock_body = MagicMock()
        mock_body.read.return_value = b"file content"
        mock_s3.get_object.return_value = {"Body": mock_body}

        result = client.download_bytes("test/file.txt")

        assert result == b"file content"

    def test_get_presigned_url(self):
        client, mock_s3 = self._make_client()
        mock_s3.generate_presigned_url.return_value = "https://example.com/presigned"

        result = client.get_presigned_url("test/file.txt", expiration=7200)

        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "test/file.txt"},
            ExpiresIn=7200,
        )
        assert result == "https://example.com/presigned"

    def test_delete_file(self):
        client, mock_s3 = self._make_client()

        result = client.delete_file("test/file.txt")

        mock_s3.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="test/file.txt"
        )
        assert result is True

    def test_delete_folder(self):
        client, mock_s3 = self._make_client()
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "books/test/1.png"},
                {"Key": "books/test/2.png"},
            ]
        }

        result = client.delete_folder("books/test/")

        assert result == 2
        mock_s3.delete_objects.assert_called_once()

    def test_delete_folder_empty(self):
        client, mock_s3 = self._make_client()
        mock_s3.list_objects_v2.return_value = {}

        result = client.delete_folder("books/empty/")

        assert result == 0
        mock_s3.delete_objects.assert_not_called()

    def test_file_exists_true(self):
        client, mock_s3 = self._make_client()
        mock_s3.head_object.return_value = {}

        result = client.file_exists("test/file.txt")

        assert result is True

    def test_file_exists_false(self):
        client, mock_s3 = self._make_client()
        from botocore.exceptions import ClientError
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadObject",
        )

        result = client.file_exists("test/nonexistent.txt")

        assert result is False

    def test_file_exists_other_error_raises(self):
        client, mock_s3 = self._make_client()
        from botocore.exceptions import ClientError
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "403", "Message": "Forbidden"}},
            "HeadObject",
        )

        with pytest.raises(ClientError):
            client.file_exists("test/forbidden.txt")

    def test_upload_json(self):
        client, mock_s3 = self._make_client()

        data = {"key": "value", "count": 5}
        result = client.upload_json(data, "test/data.json")

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        body = call_kwargs["Body"]
        parsed = json.loads(body.decode("utf-8"))
        assert parsed["key"] == "value"
        assert call_kwargs["ContentType"] == "application/json"

    def test_upload_json_type_guard_data_not_dict(self):
        client, _ = self._make_client()

        with pytest.raises(TypeError, match="data must be dict"):
            client.upload_json("not a dict", "test/data.json")

    def test_upload_json_type_guard_key_not_str(self):
        client, _ = self._make_client()

        with pytest.raises(TypeError, match="s3_key must be str"):
            client.upload_json({"key": "val"}, 123)

    def test_download_json(self):
        client, mock_s3 = self._make_client()
        data = {"key": "value"}
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(data).encode("utf-8")
        mock_s3.get_object.return_value = {"Body": mock_body}

        result = client.download_json("test/data.json")

        assert result == data

    def test_update_metadata_json(self):
        client, mock_s3 = self._make_client()

        metadata = {"book_id": "test", "pages": [], "total_pages": 0}
        result = client.update_metadata_json("test-book", metadata)

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert "books/test-book/metadata.json" in call_kwargs["Key"]


class TestS3ClientGlobalInstance:
    """Tests for S3 client global instance management."""

    @patch("book_ingestion.utils.s3_client.S3Client")
    def test_get_s3_client_creates_instance(self, MockS3Client):
        from book_ingestion.utils.s3_client import reset_s3_client, get_s3_client
        reset_s3_client()

        client = get_s3_client()

        MockS3Client.assert_called_once()

    @patch("book_ingestion.utils.s3_client.S3Client")
    def test_get_s3_client_returns_same_instance(self, MockS3Client):
        from book_ingestion.utils.s3_client import reset_s3_client, get_s3_client
        reset_s3_client()

        client1 = get_s3_client()
        client2 = get_s3_client()

        # Should be the same instance (singleton)
        assert client1 is client2
        MockS3Client.assert_called_once()

    def test_reset_s3_client(self):
        from book_ingestion.utils.s3_client import reset_s3_client
        # Should not raise
        reset_s3_client()


# ============================================================================
# JobLockService Tests
# ============================================================================

class TestJobLockService:
    """Tests for JobLockService."""

    def _make_service(self):
        mock_db = MagicMock()
        from book_ingestion.services.job_lock_service import JobLockService
        service = JobLockService(db_session=mock_db)
        return service, mock_db

    def test_acquire_lock_success(self):
        service, mock_db = self._make_service()
        # No existing running job
        mock_db.query.return_value.filter.return_value.first.return_value = None

        job_id = service.acquire_lock("test-book", "extraction")

        assert isinstance(job_id, str)
        assert len(job_id) > 0
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_acquire_lock_already_running_raises(self):
        service, mock_db = self._make_service()
        existing_job = MagicMock()
        existing_job.job_type = "extraction"
        existing_job.started_at = datetime(2024, 1, 1)
        mock_db.query.return_value.filter.return_value.first.return_value = existing_job

        from book_ingestion.services.job_lock_service import JobLockError
        with pytest.raises(JobLockError, match="already running"):
            service.acquire_lock("test-book", "extraction")

    def test_acquire_lock_integrity_error(self):
        service, mock_db = self._make_service()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        from sqlalchemy.exc import IntegrityError
        mock_db.commit.side_effect = IntegrityError("race", None, None)

        from book_ingestion.services.job_lock_service import JobLockError
        with pytest.raises(JobLockError, match="race condition"):
            service.acquire_lock("test-book", "extraction")

        mock_db.rollback.assert_called_once()

    def test_acquire_lock_other_error_reraises(self):
        service, mock_db = self._make_service()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit.side_effect = RuntimeError("Unexpected DB error")

        with pytest.raises(RuntimeError, match="Unexpected DB error"):
            service.acquire_lock("test-book", "extraction")

        mock_db.rollback.assert_called_once()

    def test_release_lock_success(self):
        service, mock_db = self._make_service()
        mock_job = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        service.release_lock("job-123", status="completed")

        assert mock_job.status == "completed"
        assert mock_job.completed_at is not None
        mock_db.commit.assert_called_once()

    def test_release_lock_with_error(self):
        service, mock_db = self._make_service()
        mock_job = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        service.release_lock("job-123", status="failed", error="Something went wrong")

        assert mock_job.status == "failed"
        assert mock_job.error_message == "Something went wrong"

    def test_release_lock_not_found(self):
        service, mock_db = self._make_service()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Should not raise
        service.release_lock("nonexistent-job")

    def test_release_lock_db_error_does_not_raise(self):
        service, mock_db = self._make_service()
        mock_db.query.return_value.filter.return_value.first.side_effect = Exception(
            "DB error"
        )

        # Should not raise (errors are suppressed)
        service.release_lock("job-123")

        mock_db.rollback.assert_called_once()


class TestJobLockError:
    """Tests for JobLockError exception."""

    def test_job_lock_error_is_exception(self):
        from book_ingestion.services.job_lock_service import JobLockError
        error = JobLockError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"


# ============================================================================
# StabilityDetectorService Tests
# ============================================================================

class TestStabilityDetectorService:
    """Tests for StabilityDetectorService."""

    def _make_service(self, threshold=3):
        from book_ingestion.services.stability_detector_service import StabilityDetectorService
        return StabilityDetectorService(stability_threshold=threshold)

    def _make_index_and_page_index(self):
        """Create a test index and page index."""
        index = GuidelinesIndex(
            book_id="test",
            topics=[
                TopicIndexEntry(
                    topic_key="fractions",
                    topic_title="Fractions",
                    subtopics=[
                        SubtopicIndexEntry(
                            subtopic_key="adding",
                            subtopic_title="Adding",
                            status="open",
                            page_range="1-3",
                        ),
                        SubtopicIndexEntry(
                            subtopic_key="subtracting",
                            subtopic_title="Subtracting",
                            status="stable",
                            page_range="4-5",
                        ),
                    ],
                )
            ],
        )

        page_index = PageIndex(
            book_id="test",
            pages={
                1: PageAssignment(topic_key="fractions", subtopic_key="adding", confidence=0.9),
                2: PageAssignment(topic_key="fractions", subtopic_key="adding", confidence=0.85),
                3: PageAssignment(topic_key="fractions", subtopic_key="adding", confidence=0.9),
                4: PageAssignment(topic_key="fractions", subtopic_key="subtracting", confidence=0.9),
                5: PageAssignment(topic_key="fractions", subtopic_key="subtracting", confidence=0.8),
            },
        )
        return index, page_index

    def test_detect_stable_subtopics_none_stable(self):
        service = self._make_service(threshold=3)
        index, page_index = self._make_index_and_page_index()

        # Current page is 4 - only 1 page since "adding" was last updated (page 3)
        result = service.detect_stable_subtopics(index, page_index, current_page=4)

        assert result == []

    def test_detect_stable_subtopics_one_stable(self):
        service = self._make_service(threshold=3)
        index, page_index = self._make_index_and_page_index()

        # Current page is 7 - 4 pages since "adding" was last updated (page 3) >= threshold 3
        result = service.detect_stable_subtopics(index, page_index, current_page=7)

        assert len(result) == 1
        assert result[0] == ("fractions", "adding")

    def test_detect_stable_subtopics_skips_non_open(self):
        service = self._make_service(threshold=3)
        index, page_index = self._make_index_and_page_index()

        # "subtracting" is already "stable", should be skipped
        result = service.detect_stable_subtopics(index, page_index, current_page=20)

        # Only "adding" (which is "open") should be detected
        assert len(result) == 1
        assert result[0] == ("fractions", "adding")

    def test_detect_stable_subtopics_empty_index(self):
        service = self._make_service()
        index = GuidelinesIndex(book_id="test")
        page_index = PageIndex(book_id="test")

        result = service.detect_stable_subtopics(index, page_index, current_page=10)

        assert result == []

    def test_detect_stable_subtopics_custom_threshold(self):
        service = self._make_service(threshold=5)
        index, page_index = self._make_index_and_page_index()

        # Current page 7: gap = 7-3 = 4, which is < 5
        result = service.detect_stable_subtopics(index, page_index, current_page=7)
        assert result == []

        # Current page 8: gap = 8-3 = 5, which is >= 5
        result = service.detect_stable_subtopics(index, page_index, current_page=8)
        assert len(result) == 1

    def test_should_mark_stable_true(self):
        service = self._make_service(threshold=3)
        _, page_index = self._make_index_and_page_index()

        result = service.should_mark_stable(
            subtopic_key="adding",
            topic_key="fractions",
            current_page=7,
            page_index=page_index,
        )

        assert result is True

    def test_should_mark_stable_false(self):
        service = self._make_service(threshold=3)
        _, page_index = self._make_index_and_page_index()

        result = service.should_mark_stable(
            subtopic_key="adding",
            topic_key="fractions",
            current_page=4,
            page_index=page_index,
        )

        assert result is False

    def test_should_mark_stable_no_pages_returns_false(self):
        service = self._make_service()
        page_index = PageIndex(book_id="test")

        result = service.should_mark_stable(
            subtopic_key="nonexistent",
            topic_key="fractions",
            current_page=10,
            page_index=page_index,
        )

        assert result is False

    def test_get_stable_status_update(self):
        service = self._make_service()

        result = service.get_stable_status_update("fractions", "adding")

        assert result["topic_key"] == "fractions"
        assert result["subtopic_key"] == "adding"
        assert result["new_status"] == "stable"
        assert "reason" in result

    def test_get_stable_status_update_custom_reason(self):
        service = self._make_service()

        result = service.get_stable_status_update(
            "fractions", "adding", reason="manual_override"
        )

        assert result["reason"] == "manual_override"

    def test_get_unstable_subtopics(self):
        service = self._make_service()
        index, page_index = self._make_index_and_page_index()

        result = service.get_unstable_subtopics(index, page_index, current_page=5)

        # "adding" is open, "subtracting" is stable
        assert len(result) == 1
        topic_key, subtopic_key, pages_since = result[0]
        assert topic_key == "fractions"
        assert subtopic_key == "adding"
        assert pages_since == 2  # current_page 5 - last_update 3

    def test_get_unstable_subtopics_empty(self):
        service = self._make_service()
        index = GuidelinesIndex(book_id="test")
        page_index = PageIndex(book_id="test")

        result = service.get_unstable_subtopics(index, page_index, current_page=10)

        assert result == []

    def test_get_unstable_subtopics_all_open(self):
        service = self._make_service()
        index = GuidelinesIndex(
            book_id="test",
            topics=[
                TopicIndexEntry(
                    topic_key="t1",
                    topic_title="T1",
                    subtopics=[
                        SubtopicIndexEntry(
                            subtopic_key="s1", subtopic_title="S1",
                            status="open", page_range="1-2"
                        ),
                        SubtopicIndexEntry(
                            subtopic_key="s2", subtopic_title="S2",
                            status="open", page_range="3-4"
                        ),
                    ],
                )
            ],
        )
        page_index = PageIndex(
            book_id="test",
            pages={
                1: PageAssignment(topic_key="t1", subtopic_key="s1", confidence=0.9),
                2: PageAssignment(topic_key="t1", subtopic_key="s1", confidence=0.9),
                3: PageAssignment(topic_key="t1", subtopic_key="s2", confidence=0.9),
                4: PageAssignment(topic_key="t1", subtopic_key="s2", confidence=0.9),
            },
        )

        result = service.get_unstable_subtopics(index, page_index, current_page=6)

        assert len(result) == 2
        # s1 last updated page 2, gap=4
        # s2 last updated page 4, gap=2
        keys = {(r[0], r[1]) for r in result}
        assert ("t1", "s1") in keys
        assert ("t1", "s2") in keys

    def test_default_threshold(self):
        from book_ingestion.services.stability_detector_service import StabilityDetectorService
        service = StabilityDetectorService()
        assert service.stability_threshold == 3
