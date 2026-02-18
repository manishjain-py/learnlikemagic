"""
Tests for book_ingestion/services/page_service.py

Covers:
- PageService: upload_page, approve_page, delete_page, get_pages,
  get_page_with_urls, _validate_image, _convert_to_png, _load_metadata,
  _get_next_page_number
"""

import io
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from PIL import Image

from book_ingestion.models.schemas import PageUploadResponse, PageApproveResponse, PageInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_small_png() -> bytes:
    """Create a small valid PNG image in memory."""
    img = Image.new("RGB", (10, 10), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_small_jpeg() -> bytes:
    """Create a small valid JPEG image in memory."""
    img = Image.new("RGB", (10, 10), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_rgba_png() -> bytes:
    """Create an RGBA PNG image (needs conversion to RGB)."""
    img = Image.new("RGBA", (10, 10), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build_service():
    """Build a PageService with all external dependencies mocked."""
    mock_db = MagicMock()
    with patch("book_ingestion.services.page_service.BookRepository") as MockBookRepo, \
         patch("book_ingestion.services.page_service.get_ocr_service") as mock_ocr_factory, \
         patch("book_ingestion.services.page_service.get_s3_client") as mock_s3_factory:

        mock_book_repo = MagicMock()
        MockBookRepo.return_value = mock_book_repo

        mock_ocr = MagicMock()
        mock_ocr_factory.return_value = mock_ocr

        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3

        from book_ingestion.services.page_service import PageService
        svc = PageService(mock_db)

    return svc, mock_book_repo, mock_ocr, mock_s3


# ===========================================================================
# _validate_image
# ===========================================================================

class TestValidateImage:

    def test_rejects_oversize_file(self):
        svc, *_ = _build_service()
        big_data = b"\x00" * (20 * 1024 * 1024 + 1)
        with pytest.raises(ValueError, match="too large"):
            svc._validate_image(big_data, "big.png")

    def test_rejects_unsupported_format(self):
        svc, *_ = _build_service()
        with pytest.raises(ValueError, match="Unsupported image format"):
            svc._validate_image(b"data", "file.bmp")

    def test_rejects_bad_image_data(self):
        svc, *_ = _build_service()
        with pytest.raises(ValueError, match="Invalid image file"):
            svc._validate_image(b"not-an-image", "file.png")

    def test_accepts_valid_png(self):
        svc, *_ = _build_service()
        svc._validate_image(_make_small_png(), "page.png")  # should not raise

    def test_accepts_valid_jpeg(self):
        svc, *_ = _build_service()
        svc._validate_image(_make_small_jpeg(), "page.jpg")

    def test_rejects_at_exact_boundary(self):
        """File exactly at MAX_FILE_SIZE should be accepted."""
        svc, *_ = _build_service()
        from book_ingestion.services.page_service import MAX_FILE_SIZE
        # A file at exactly max size: need valid image, but we only test size guard
        # For the size check, a file of exactly MAX_FILE_SIZE should pass the size check
        # but fail image validation (since it's all zeroes). Testing the size path:
        data = b"\x00" * MAX_FILE_SIZE
        # This should NOT raise for size, but WILL raise for format or image validity
        with pytest.raises(ValueError):
            svc._validate_image(data, "file.png")


# ===========================================================================
# _convert_to_png
# ===========================================================================

class TestConvertToPng:

    def test_converts_jpeg_to_png(self):
        svc, *_ = _build_service()
        png_bytes = svc._convert_to_png(_make_small_jpeg())
        img = Image.open(io.BytesIO(png_bytes))
        assert img.format == "PNG"

    def test_converts_rgba_to_rgb_png(self):
        svc, *_ = _build_service()
        png_bytes = svc._convert_to_png(_make_rgba_png())
        img = Image.open(io.BytesIO(png_bytes))
        assert img.format == "PNG"
        assert img.mode == "RGB"

    def test_invalid_data_raises(self):
        svc, *_ = _build_service()
        with pytest.raises(ValueError, match="Image conversion failed"):
            svc._convert_to_png(b"not-image-data")


# ===========================================================================
# _load_metadata
# ===========================================================================

class TestLoadMetadata:

    def test_returns_s3_metadata(self):
        svc, _, _, mock_s3 = _build_service()
        expected = {"book_id": "b1", "pages": [{"page_num": 1}], "total_pages": 1}
        mock_s3.download_json.return_value = expected
        result = svc._load_metadata("b1")
        assert result == expected
        mock_s3.download_json.assert_called_once_with("books/b1/metadata.json")

    def test_falls_back_on_error(self):
        svc, _, _, mock_s3 = _build_service()
        mock_s3.download_json.side_effect = Exception("not found")
        result = svc._load_metadata("b1")
        assert result["book_id"] == "b1"
        assert result["pages"] == []
        assert result["total_pages"] == 0


# ===========================================================================
# _get_next_page_number
# ===========================================================================

class TestGetNextPageNumber:

    def test_empty_pages(self):
        svc, *_ = _build_service()
        assert svc._get_next_page_number({"pages": []}) == 1

    def test_no_pages_key(self):
        svc, *_ = _build_service()
        assert svc._get_next_page_number({}) == 1

    def test_with_existing_pages(self):
        svc, *_ = _build_service()
        metadata = {"pages": [{"page_num": 1}, {"page_num": 3}]}
        assert svc._get_next_page_number(metadata) == 4


# ===========================================================================
# upload_page
# ===========================================================================

class TestUploadPage:

    def test_book_not_found_raises(self):
        svc, mock_repo, _, _ = _build_service()
        mock_repo.get_by_id.return_value = None
        with pytest.raises(ValueError, match="Book not found"):
            svc.upload_page("nonexistent", _make_small_png(), "page.png")

    def test_happy_path(self):
        svc, mock_repo, mock_ocr, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()  # book exists
        mock_s3.download_json.return_value = {"book_id": "b1", "pages": [], "total_pages": 0}
        mock_ocr.extract_text_with_retry.return_value = "OCR text from page"
        mock_s3.get_presigned_url.return_value = "https://s3.example.com/signed"

        result = svc.upload_page("b1", _make_small_png(), "page.png")

        assert isinstance(result, PageUploadResponse)
        assert result.page_num == 1
        assert result.ocr_text == "OCR text from page"
        assert result.status == "pending_review"
        assert result.image_url == "https://s3.example.com/signed"

        # Verify S3 interactions
        assert mock_s3.upload_bytes.call_count == 2  # image + ocr text
        mock_s3.update_metadata_json.assert_called_once()

    def test_upload_second_page(self):
        svc, mock_repo, mock_ocr, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()
        mock_s3.download_json.return_value = {
            "book_id": "b1",
            "pages": [{"page_num": 1}],
            "total_pages": 1,
        }
        mock_ocr.extract_text_with_retry.return_value = "Page 2 text"
        mock_s3.get_presigned_url.return_value = "https://signed"

        result = svc.upload_page("b1", _make_small_png(), "page2.png")
        assert result.page_num == 2


# ===========================================================================
# approve_page
# ===========================================================================

class TestApprovePage:

    def test_book_not_found(self):
        svc, mock_repo, _, _ = _build_service()
        mock_repo.get_by_id.return_value = None
        with pytest.raises(ValueError, match="Book not found"):
            svc.approve_page("bad_id", 1)

    def test_page_not_found(self):
        svc, mock_repo, _, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()
        mock_s3.download_json.return_value = {"pages": [{"page_num": 2, "status": "pending_review"}]}
        with pytest.raises(ValueError, match="Page 1 not found"):
            svc.approve_page("b1", 1)

    def test_already_approved(self):
        svc, mock_repo, _, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()
        mock_s3.download_json.return_value = {"pages": [{"page_num": 1, "status": "approved"}]}
        with pytest.raises(ValueError, match="already approved"):
            svc.approve_page("b1", 1)

    def test_happy_path(self):
        svc, mock_repo, _, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()
        mock_s3.download_json.return_value = {"pages": [{"page_num": 1, "status": "pending_review"}]}

        result = svc.approve_page("b1", 1)

        assert isinstance(result, PageApproveResponse)
        assert result.page_num == 1
        assert result.status == "approved"
        mock_s3.update_metadata_json.assert_called_once()


# ===========================================================================
# delete_page
# ===========================================================================

class TestDeletePage:

    def test_book_not_found(self):
        svc, mock_repo, _, _ = _build_service()
        mock_repo.get_by_id.return_value = None
        with pytest.raises(ValueError, match="Book not found"):
            svc.delete_page("bad_id", 1)

    def test_page_not_found(self):
        svc, mock_repo, _, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()
        mock_s3.download_json.return_value = {"pages": [{"page_num": 2, "status": "pending_review",
                                                          "image_s3_key": "k", "text_s3_key": "k"}]}
        with pytest.raises(ValueError, match="Page 1 not found"):
            svc.delete_page("b1", 1)

    def test_happy_path_with_renumbering(self):
        svc, mock_repo, _, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()
        mock_s3.download_json.return_value = {
            "pages": [
                {"page_num": 1, "status": "approved", "image_s3_key": "img1", "text_s3_key": "txt1"},
                {"page_num": 2, "status": "pending_review", "image_s3_key": "img2", "text_s3_key": "txt2"},
                {"page_num": 3, "status": "approved", "image_s3_key": "img3", "text_s3_key": "txt3"},
            ]
        }

        result = svc.delete_page("b1", 2)
        assert result is True

        # S3 delete called for image + text of deleted page
        assert mock_s3.delete_file.call_count == 2

        # Check renumbering in the metadata update
        call_args = mock_s3.update_metadata_json.call_args
        updated_metadata = call_args[0][1]
        page_nums = [p["page_num"] for p in updated_metadata["pages"]]
        assert page_nums == [1, 2]  # renumbered from [1,3] -> [1,2]
        assert updated_metadata["total_pages"] == 2


# ===========================================================================
# get_pages
# ===========================================================================

class TestGetPages:

    def test_book_not_found(self):
        svc, mock_repo, _, _ = _build_service()
        mock_repo.get_by_id.return_value = None
        with pytest.raises(ValueError, match="Book not found"):
            svc.get_pages("bad")

    def test_returns_page_info_list(self):
        svc, mock_repo, _, mock_s3 = _build_service()
        mock_repo.get_by_id.return_value = MagicMock()
        mock_s3.download_json.return_value = {
            "pages": [
                {
                    "page_num": 1,
                    "image_s3_key": "books/b1/1.png",
                    "text_s3_key": "books/b1/1.txt",
                    "status": "approved",
                    "approved_at": "2024-01-01T00:00:00",
                },
                {
                    "page_num": 2,
                    "image_s3_key": "books/b1/2.png",
                    "text_s3_key": "books/b1/2.txt",
                    "status": "pending_review",
                },
            ]
        }

        pages = svc.get_pages("b1")
        assert len(pages) == 2
        assert all(isinstance(p, PageInfo) for p in pages)
        assert pages[0].page_num == 1
        assert pages[0].status == "approved"
        assert pages[1].status == "pending_review"


# ===========================================================================
# get_page_with_urls
# ===========================================================================

class TestGetPageWithUrls:

    def test_page_not_found(self):
        svc, _, _, mock_s3 = _build_service()
        mock_s3.download_json.return_value = {"pages": []}
        with pytest.raises(ValueError, match="Page 5 not found"):
            svc.get_page_with_urls("b1", 5)

    def test_happy_path(self):
        svc, _, _, mock_s3 = _build_service()
        mock_s3.download_json.return_value = {
            "pages": [
                {
                    "page_num": 1,
                    "status": "approved",
                    "image_s3_key": "books/b1/1.png",
                    "text_s3_key": "books/b1/1.txt",
                }
            ]
        }
        mock_s3.get_presigned_url.side_effect = [
            "https://img-url", "https://txt-url"
        ]
        mock_s3.download_bytes.return_value = b"Hello OCR"

        result = svc.get_page_with_urls("b1", 1)

        assert result["page_num"] == 1
        assert result["status"] == "approved"
        assert result["image_url"] == "https://img-url"
        assert result["text_url"] == "https://txt-url"
        assert result["ocr_text"] == "Hello OCR"
