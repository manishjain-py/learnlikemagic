"""
Book service - business logic for book management.

Handles book CRUD operations, status transitions, and metadata management.
"""
import json
import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from features.book_ingestion.models.database import Book
from features.book_ingestion.models.schemas import (
    CreateBookRequest,
    BookResponse,
    BookListResponse,
    BookDetailResponse,
    PageInfo
)
from features.book_ingestion.repositories.book_repository import BookRepository
from features.book_ingestion.utils.s3_client import get_s3_client

logger = logging.getLogger(__name__)


# Valid status transitions
STATUS_TRANSITIONS = {
    "draft": ["uploading_pages"],
    "uploading_pages": ["pages_complete"],
    "pages_complete": ["generating_guidelines"],
    "generating_guidelines": ["guidelines_pending_review"],
    "guidelines_pending_review": ["approved", "pages_complete"],  # Can go back to retry
    "approved": []  # Terminal state
}


class BookService:
    """
    Service for book management operations.

    Provides business logic layer between API routes and repositories.
    """

    def __init__(self, db: Session):
        """
        Initialize service with database session.

        Args:
            db: SQLAlchemy session
        """
        self.db = db
        self.repository = BookRepository(db)
        self.s3_client = get_s3_client()

    def create_book(self, request: CreateBookRequest, created_by: str = "admin") -> BookResponse:
        """
        Create a new book.

        Args:
            request: Book creation request
            created_by: Username of creator

        Returns:
            Created book response

        Raises:
            ValueError: If book creation fails
        """
        # Generate book ID
        book_id = self._generate_book_id(request)
        s3_prefix = f"books/{book_id}/"

        # Create book instance
        book = Book(
            id=book_id,
            title=request.title,
            author=request.author,
            edition=request.edition,
            edition_year=request.edition_year,
            country=request.country,
            board=request.board,
            grade=request.grade,
            subject=request.subject,
            s3_prefix=s3_prefix,
            metadata_s3_key=f"{s3_prefix}metadata.json",
            status="draft",
            created_by=created_by
        )

        # Save to database
        book = self.repository.create(book)

        # Initialize metadata.json in S3
        self._initialize_metadata(book_id)

        logger.info(f"Created book: {book_id}")
        return self._to_book_response(book)

    def get_book(self, book_id: str) -> Optional[BookResponse]:
        """
        Get book by ID.

        Args:
            book_id: Book identifier

        Returns:
            Book response or None if not found
        """
        book = self.repository.get_by_id(book_id)
        if not book:
            return None
        return self._to_book_response(book)

    def get_book_detail(self, book_id: str) -> Optional[BookDetailResponse]:
        """
        Get detailed book information including pages.

        Args:
            book_id: Book identifier

        Returns:
            Detailed book response with pages or None if not found
        """
        book = self.repository.get_by_id(book_id)
        if not book:
            return None

        # Load pages from metadata.json
        pages = self._load_pages(book_id)

        return BookDetailResponse(
            id=book.id,
            title=book.title,
            author=book.author,
            edition=book.edition,
            edition_year=book.edition_year,
            country=book.country,
            board=book.board,
            grade=book.grade,
            subject=book.subject,
            status=book.status,
            pages=pages,
            created_at=book.created_at,
            updated_at=book.updated_at
        )

    def list_books(
        self,
        country: Optional[str] = None,
        board: Optional[str] = None,
        grade: Optional[int] = None,
        subject: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> BookListResponse:
        """
        List books with optional filters.

        Args:
            country: Filter by country
            board: Filter by board
            grade: Filter by grade
            subject: Filter by subject
            status: Filter by status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of books with total count
        """
        books = self.repository.get_all(
            country=country,
            board=board,
            grade=grade,
            subject=subject,
            status=status,
            limit=limit,
            offset=offset
        )

        total = self.repository.count(
            country=country,
            board=board,
            grade=grade,
            subject=subject,
            status=status
        )

        return BookListResponse(
            books=[self._to_book_response(book) for book in books],
            total=total
        )

    def update_book_status(self, book_id: str, new_status: str) -> Optional[BookResponse]:
        """
        Update book status with validation.

        Args:
            book_id: Book identifier
            new_status: New status value

        Returns:
            Updated book response or None if not found

        Raises:
            ValueError: If status transition is invalid
        """
        book = self.repository.get_by_id(book_id)
        if not book:
            return None

        # Validate status transition
        current_status = book.status
        if new_status not in STATUS_TRANSITIONS.get(current_status, []):
            raise ValueError(
                f"Invalid status transition: {current_status} -> {new_status}. "
                f"Valid transitions: {STATUS_TRANSITIONS.get(current_status, [])}"
            )

        # Update status
        book = self.repository.update_status(book_id, new_status)
        logger.info(f"Updated book {book_id} status: {current_status} -> {new_status}")

        return self._to_book_response(book)

    def delete_book(self, book_id: str) -> bool:
        """
        Delete book and all associated S3 files.

        Args:
            book_id: Book identifier

        Returns:
            True if deleted, False if not found
        """
        book = self.repository.get_by_id(book_id)
        if not book:
            return False

        # Delete all S3 files
        prefix = f"books/{book_id}/"
        self.s3_client.delete_folder(prefix)
        logger.info(f"Deleted S3 folder: {prefix}")

        # Delete from database
        success = self.repository.delete(book_id)
        logger.info(f"Deleted book: {book_id}")

        return success

    def _generate_book_id(self, request: CreateBookRequest) -> str:
        """
        Generate a unique book ID from metadata.

        Args:
            request: Book creation request

        Returns:
            Book ID (e.g., "ncert_math_3_2024")
        """
        # Create base ID from metadata
        author_slug = request.author.lower().replace(" ", "_") if request.author else "unknown"
        subject_slug = request.subject.lower().replace(" ", "_")
        grade = request.grade
        edition_year = request.edition_year or datetime.now().year

        base_id = f"{author_slug}_{subject_slug}_{grade}_{edition_year}"

        # Check for uniqueness
        counter = 1
        book_id = base_id
        while self.repository.get_by_id(book_id):
            book_id = f"{base_id}_{counter}"
            counter += 1

        return book_id

    def _initialize_metadata(self, book_id: str):
        """
        Initialize metadata.json for a new book.

        Args:
            book_id: Book identifier
        """
        metadata = {
            "book_id": book_id,
            "pages": [],
            "total_pages": 0,
            "last_updated": datetime.utcnow().isoformat()
        }

        self.s3_client.update_metadata_json(book_id, metadata)
        logger.debug(f"Initialized metadata for book: {book_id}")

    def _load_pages(self, book_id: str) -> List[PageInfo]:
        """
        Load pages from metadata.json.

        Args:
            book_id: Book identifier

        Returns:
            List of page information
        """
        try:
            metadata = self.s3_client.download_json(f"books/{book_id}/metadata.json")
            pages_data = metadata.get("pages", [])

            return [
                PageInfo(
                    page_num=page["page_num"],
                    image_s3_key=page["image_s3_key"],
                    text_s3_key=page["text_s3_key"],
                    status=page["status"],
                    approved_at=page.get("approved_at")
                )
                for page in pages_data
            ]
        except Exception as e:
            logger.warning(f"Failed to load pages for book {book_id}: {e}")
            return []

    def _to_book_response(self, book: Book) -> BookResponse:
        """
        Convert Book ORM model to response schema.

        Args:
            book: Book ORM instance

        Returns:
            Book response schema
        """
        return BookResponse(
            id=book.id,
            title=book.title,
            author=book.author,
            edition=book.edition,
            edition_year=book.edition_year,
            country=book.country,
            board=book.board,
            grade=book.grade,
            subject=book.subject,
            cover_image_s3_key=book.cover_image_s3_key,
            s3_prefix=book.s3_prefix,
            status=book.status,
            created_at=book.created_at,
            updated_at=book.updated_at,
            created_by=book.created_by
        )
