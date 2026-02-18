"""
Tests for BookService - book CRUD, status transitions, metadata management.

All DB, S3, and external dependencies are mocked.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from book_ingestion.models.schemas import CreateBookRequest, BookResponse, BookListResponse


# ===== Helper Factories =====

def _make_mock_book(**overrides):
    """Create a mock Book ORM object with sensible defaults."""
    book = MagicMock()
    defaults = dict(
        id="ncert_math_3_2024",
        title="Math Book",
        author="NCERT",
        edition="1st",
        edition_year=2024,
        country="India",
        board="CBSE",
        grade=3,
        subject="Mathematics",
        cover_image_s3_key=None,
        s3_prefix="books/ncert_math_3_2024/",
        metadata_s3_key="books/ncert_math_3_2024/metadata.json",
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
        created_by="admin",
    )
    defaults.update(overrides)
    for key, val in defaults.items():
        setattr(book, key, val)
    return book


def _make_service():
    """Create a BookService with mocked DB and S3 dependencies."""
    mock_db = MagicMock()
    mock_s3 = MagicMock()

    with patch("book_ingestion.services.book_service.BookRepository") as MockRepo, \
         patch("book_ingestion.services.book_service.get_s3_client", return_value=mock_s3):
        from book_ingestion.services.book_service import BookService
        service = BookService(mock_db)
        mock_repo = MockRepo.return_value
        return service, mock_db, mock_s3, mock_repo


class TestBookServiceCreate:
    """Tests for BookService.create_book."""

    def test_create_book_happy_path(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None  # No existing book with that ID
        created_book = _make_mock_book()
        mock_repo.create.return_value = created_book
        mock_s3.download_json.return_value = {"pages": []}

        # Mock the DB queries for guideline_count etc.
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        request = CreateBookRequest(
            title="Math Book",
            author="NCERT",
            edition_year=2024,
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )

        result = service.create_book(request, created_by="admin")

        assert isinstance(result, BookResponse)
        mock_repo.create.assert_called_once()
        mock_s3.update_metadata_json.assert_called_once()

    def test_create_book_generates_unique_id(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        # First call returns existing, second returns None
        mock_repo.get_by_id.side_effect = [MagicMock(), None]
        created_book = _make_mock_book(id="ncert_mathematics_3_2024_1")
        mock_repo.create.return_value = created_book
        mock_s3.download_json.return_value = {"pages": []}
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        request = CreateBookRequest(
            title="Math Book",
            author="NCERT",
            edition_year=2024,
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )

        result = service.create_book(request)

        # Should have checked ID uniqueness twice
        assert mock_repo.get_by_id.call_count == 2

    def test_create_book_without_author(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None
        created_book = _make_mock_book(author=None, id="unknown_mathematics_3_2024")
        mock_repo.create.return_value = created_book
        mock_s3.download_json.return_value = {"pages": []}
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        request = CreateBookRequest(
            title="Math Book",
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )

        result = service.create_book(request)

        assert isinstance(result, BookResponse)

    def test_create_book_initializes_metadata(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None
        created_book = _make_mock_book()
        mock_repo.create.return_value = created_book
        mock_s3.download_json.return_value = {"pages": []}
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        request = CreateBookRequest(
            title="Math Book",
            author="NCERT",
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )

        service.create_book(request)

        # Should call update_metadata_json to initialize metadata
        mock_s3.update_metadata_json.assert_called_once()
        call_args = mock_s3.update_metadata_json.call_args
        metadata = call_args[0][1]
        assert "pages" in metadata
        assert metadata["pages"] == []


class TestBookServiceGet:
    """Tests for BookService.get_book and get_book_detail."""

    def test_get_book_found(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_book = _make_mock_book()
        mock_repo.get_by_id.return_value = mock_book
        mock_s3.download_json.return_value = {"pages": [{"page_num": 1}, {"page_num": 2}]}
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        result = service.get_book("ncert_math_3_2024")

        assert result is not None
        assert isinstance(result, BookResponse)
        assert result.id == "ncert_math_3_2024"

    def test_get_book_not_found(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None

        result = service.get_book("nonexistent")

        assert result is None

    def test_get_book_detail_found(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_book = _make_mock_book()
        mock_repo.get_by_id.return_value = mock_book
        mock_s3.download_json.return_value = {
            "pages": [
                {
                    "page_num": 1,
                    "image_s3_key": "books/test/pages/001.png",
                    "text_s3_key": "books/test/pages/001.ocr.txt",
                    "status": "approved",
                }
            ]
        }

        result = service.get_book_detail("ncert_math_3_2024")

        assert result is not None
        assert len(result.pages) == 1
        assert result.pages[0].page_num == 1

    def test_get_book_detail_not_found(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None

        result = service.get_book_detail("nonexistent")

        assert result is None

    def test_get_book_detail_s3_error_returns_empty_pages(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_book = _make_mock_book()
        mock_repo.get_by_id.return_value = mock_book
        mock_s3.download_json.side_effect = Exception("S3 error")

        result = service.get_book_detail("ncert_math_3_2024")

        assert result is not None
        assert result.pages == []

    def test_get_book_page_count_from_metadata(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_book = _make_mock_book()
        mock_repo.get_by_id.return_value = mock_book
        mock_s3.download_json.return_value = {
            "pages": [{"p": 1}, {"p": 2}, {"p": 3}]
        }
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        result = service.get_book("ncert_math_3_2024")

        assert result.page_count == 3

    def test_get_book_s3_error_page_count_zero(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_book = _make_mock_book()
        mock_repo.get_by_id.return_value = mock_book
        mock_s3.download_json.side_effect = Exception("S3 error")
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        result = service.get_book("ncert_math_3_2024")

        assert result.page_count == 0


class TestBookServiceList:
    """Tests for BookService.list_books."""

    def test_list_books_no_filters(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        books = [_make_mock_book(id=f"book-{i}") for i in range(3)]
        mock_repo.get_all.return_value = books
        mock_repo.count.return_value = 3
        mock_s3.download_json.return_value = {"pages": []}
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        result = service.list_books()

        assert isinstance(result, BookListResponse)
        assert result.total == 3
        assert len(result.books) == 3

    def test_list_books_with_filters(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_all.return_value = []
        mock_repo.count.return_value = 0

        result = service.list_books(country="India", grade=3)

        assert result.total == 0
        mock_repo.get_all.assert_called_once_with(
            country="India", board=None, grade=3, subject=None,
            limit=100, offset=0
        )

    def test_list_books_with_pagination(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_all.return_value = []
        mock_repo.count.return_value = 50

        result = service.list_books(limit=10, offset=20)

        mock_repo.get_all.assert_called_once_with(
            country=None, board=None, grade=None, subject=None,
            limit=10, offset=20
        )


class TestBookServiceDelete:
    """Tests for BookService.delete_book."""

    def test_delete_book_found(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_book = _make_mock_book()
        mock_repo.get_by_id.return_value = mock_book
        mock_repo.delete.return_value = True

        result = service.delete_book("ncert_math_3_2024")

        assert result is True
        mock_s3.delete_folder.assert_called_once_with("books/ncert_math_3_2024/")
        mock_repo.delete.assert_called_once_with("ncert_math_3_2024")

    def test_delete_book_not_found(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None

        result = service.delete_book("nonexistent")

        assert result is False
        mock_s3.delete_folder.assert_not_called()
        mock_repo.delete.assert_not_called()


class TestBookServiceIDGeneration:
    """Tests for BookService._generate_book_id."""

    def test_id_format(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None  # No collision

        request = CreateBookRequest(
            title="Math Book",
            author="NCERT",
            edition_year=2024,
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )

        book_id = service._generate_book_id(request)

        assert "ncert" in book_id
        assert "mathematics" in book_id
        assert "3" in book_id
        assert "2024" in book_id

    def test_id_without_author(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        mock_repo.get_by_id.return_value = None

        request = CreateBookRequest(
            title="Math Book",
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )

        book_id = service._generate_book_id(request)

        assert "unknown" in book_id

    def test_id_collision_handling(self):
        service, mock_db, mock_s3, mock_repo = _make_service()
        # First ID exists, second does not
        mock_repo.get_by_id.side_effect = [MagicMock(), MagicMock(), None]

        request = CreateBookRequest(
            title="Math Book",
            author="NCERT",
            edition_year=2024,
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )

        book_id = service._generate_book_id(request)

        # Should have appended a counter
        assert book_id.endswith("_2")
