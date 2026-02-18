"""
Tests for book_ingestion repositories: BookRepository and BookGuidelineRepository.

All database interactions are tested against a mocked SQLAlchemy session.
No real database is used.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock, call
from datetime import datetime

from book_ingestion.repositories.book_repository import BookRepository
from book_ingestion.repositories.book_guideline_repository import BookGuidelineRepository


# ===== Helper to create a mock Book =====

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


def _make_mock_guideline(**overrides):
    """Create a mock BookGuideline ORM object."""
    guideline = MagicMock()
    defaults = dict(
        id="guid-1",
        book_id="test-book",
        guideline_s3_key="books/test-book/guideline.json",
        status="pending_review",
        review_status="TO_BE_REVIEWED",
        generated_at=datetime(2024, 1, 1),
        reviewed_at=None,
        reviewed_by=None,
        version=1,
        created_at=datetime(2024, 1, 1),
    )
    defaults.update(overrides)
    for key, val in defaults.items():
        setattr(guideline, key, val)
    return guideline


# ===== BookRepository Tests =====

class TestBookRepository:
    """Tests for BookRepository."""

    def _make_repo(self):
        """Create a BookRepository with a mocked session."""
        db = MagicMock()
        repo = BookRepository(db)
        return repo, db

    def test_create_book(self):
        repo, db = self._make_repo()
        book = _make_mock_book()

        result = repo.create(book)

        db.add.assert_called_once_with(book)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(book)
        assert result == book

    def test_get_by_id_found(self):
        repo, db = self._make_repo()
        mock_book = _make_mock_book()
        db.query.return_value.filter.return_value.first.return_value = mock_book

        result = repo.get_by_id("ncert_math_3_2024")

        assert result == mock_book
        db.query.assert_called_once()

    def test_get_by_id_not_found(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.first.return_value = None

        result = repo.get_by_id("nonexistent")

        assert result is None

    def test_get_all_no_filters(self):
        repo, db = self._make_repo()
        mock_books = [_make_mock_book(id=f"book-{i}") for i in range(3)]
        chain = db.query.return_value
        chain.order_by.return_value.limit.return_value.offset.return_value.all.return_value = mock_books

        result = repo.get_all()

        assert len(result) == 3

    def test_get_all_with_country_filter(self):
        repo, db = self._make_repo()
        chain = db.query.return_value
        chain.filter.return_value = chain
        chain.order_by.return_value.limit.return_value.offset.return_value.all.return_value = []

        result = repo.get_all(country="India")

        # filter should have been called at least once
        assert chain.filter.called

    def test_get_all_with_all_filters(self):
        repo, db = self._make_repo()
        chain = db.query.return_value
        chain.filter.return_value = chain
        chain.order_by.return_value.limit.return_value.offset.return_value.all.return_value = []

        result = repo.get_all(country="India", board="CBSE", grade=3, subject="Math")

        assert result == []

    def test_count_no_filters(self):
        repo, db = self._make_repo()
        db.query.return_value.count.return_value = 5

        result = repo.count()

        assert result == 5

    def test_count_with_filters(self):
        repo, db = self._make_repo()
        chain = db.query.return_value
        chain.filter.return_value = chain
        chain.count.return_value = 2

        result = repo.count(country="India", grade=3)

        assert result == 2

    def test_update_book(self):
        repo, db = self._make_repo()
        book = _make_mock_book()

        result = repo.update(book)

        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(book)
        assert result == book

    def test_delete_book_found(self):
        repo, db = self._make_repo()
        mock_book = _make_mock_book()
        db.query.return_value.filter.return_value.first.return_value = mock_book

        result = repo.delete("ncert_math_3_2024")

        assert result is True
        db.delete.assert_called_once_with(mock_book)
        db.commit.assert_called_once()

    def test_delete_book_not_found(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.first.return_value = None

        result = repo.delete("nonexistent")

        assert result is False
        db.delete.assert_not_called()

    def test_get_by_curriculum(self):
        repo, db = self._make_repo()
        mock_books = [_make_mock_book()]
        db.query.return_value.filter.return_value.all.return_value = mock_books

        result = repo.get_by_curriculum("India", "CBSE", 3, "Mathematics")

        assert len(result) == 1

    def test_get_by_curriculum_empty(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.all.return_value = []

        result = repo.get_by_curriculum("India", "CBSE", 3, "History")

        assert result == []


# ===== BookGuidelineRepository Tests =====

class TestBookGuidelineRepository:
    """Tests for BookGuidelineRepository."""

    def _make_repo(self):
        """Create a BookGuidelineRepository with a mocked session."""
        db = MagicMock()
        repo = BookGuidelineRepository(db)
        return repo, db

    def test_create_guideline(self):
        repo, db = self._make_repo()
        guideline = _make_mock_guideline()

        result = repo.create(guideline)

        db.add.assert_called_once_with(guideline)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(guideline)
        assert result == guideline

    def test_get_by_id_found(self):
        repo, db = self._make_repo()
        mock_gl = _make_mock_guideline()
        db.query.return_value.filter.return_value.first.return_value = mock_gl

        result = repo.get_by_id("guid-1")

        assert result == mock_gl

    def test_get_by_id_not_found(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.first.return_value = None

        result = repo.get_by_id("nonexistent")

        assert result is None

    def test_get_by_book_id(self):
        repo, db = self._make_repo()
        guidelines = [_make_mock_guideline(version=v) for v in [2, 1]]
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = guidelines

        result = repo.get_by_book_id("test-book")

        assert len(result) == 2

    def test_get_by_book_id_empty(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = repo.get_by_book_id("nonexistent-book")

        assert result == []

    def test_get_latest_by_book_id_found(self):
        repo, db = self._make_repo()
        latest = _make_mock_guideline(version=3)
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = latest

        result = repo.get_latest_by_book_id("test-book")

        assert result.version == 3

    def test_get_latest_by_book_id_not_found(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = repo.get_latest_by_book_id("test-book")

        assert result is None

    def test_update_status_found(self):
        repo, db = self._make_repo()
        mock_gl = _make_mock_guideline(status="pending_review")
        db.query.return_value.filter.return_value.first.return_value = mock_gl

        result = repo.update_status("guid-1", "approved", reviewed_by="admin")

        assert result is not None
        assert mock_gl.status == "approved"
        assert mock_gl.reviewed_by == "admin"
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(mock_gl)

    def test_update_status_not_found(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.first.return_value = None

        result = repo.update_status("nonexistent", "approved")

        assert result is None
        db.commit.assert_not_called()

    def test_update_status_without_reviewer(self):
        repo, db = self._make_repo()
        mock_gl = _make_mock_guideline()
        db.query.return_value.filter.return_value.first.return_value = mock_gl

        result = repo.update_status("guid-1", "rejected")

        assert mock_gl.status == "rejected"
        db.commit.assert_called_once()
        # result should be the guideline
        assert result is not None

    def test_delete_found(self):
        repo, db = self._make_repo()
        mock_gl = _make_mock_guideline()
        db.query.return_value.filter.return_value.first.return_value = mock_gl

        result = repo.delete("guid-1")

        assert result is True
        db.delete.assert_called_once_with(mock_gl)
        db.commit.assert_called_once()

    def test_delete_not_found(self):
        repo, db = self._make_repo()
        db.query.return_value.filter.return_value.first.return_value = None

        result = repo.delete("nonexistent")

        assert result is False
        db.delete.assert_not_called()
