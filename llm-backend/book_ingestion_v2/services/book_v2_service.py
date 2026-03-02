"""
Book V2 service — business logic for V2 book management.

Handles book CRUD with pipeline_version=2 and chapter-aware responses.
"""
import logging
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from book_ingestion.models.database import Book
from book_ingestion.repositories.book_repository import BookRepository
from book_ingestion.utils.s3_client import get_s3_client
from book_ingestion_v2.models.schemas import (
    CreateBookV2Request,
    BookV2Response,
    BookV2ListResponse,
    BookV2DetailResponse,
    ChapterResponse,
)
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.chapter_page_repository import ChapterPageRepository
from book_ingestion_v2.repositories.processing_job_repository import ProcessingJobRepository
from book_ingestion_v2.repositories.chunk_repository import ChunkRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository

logger = logging.getLogger(__name__)


class BookV2Service:
    """Service for V2 book management operations."""

    def __init__(self, db: Session):
        self.db = db
        self.repository = BookRepository(db)
        self.chapter_repository = ChapterRepository(db)
        self.s3_client = get_s3_client()

    def create_book(self, request: CreateBookV2Request, created_by: str = "admin") -> BookV2Response:
        """Create a new V2 book with pipeline_version=2."""
        book_id = self._generate_book_id(request)
        s3_prefix = f"books/{book_id}/"

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
            pipeline_version=2,
            s3_prefix=s3_prefix,
            metadata_s3_key=f"{s3_prefix}metadata.json",
            created_by=created_by,
        )

        book = self.repository.create(book)

        # Initialize S3 metadata
        self.s3_client.update_metadata_json(book_id, {
            "book_id": book_id,
            "pipeline_version": 2,
            "chapters": [],
            "last_updated": datetime.utcnow().isoformat(),
        })

        logger.info(f"Created V2 book: {book_id}")
        return self._to_response(book)

    def get_book(self, book_id: str) -> Optional[BookV2Response]:
        """Get V2 book by ID."""
        book = self.repository.get_by_id(book_id)
        if not book or getattr(book, "pipeline_version", 1) != 2:
            return None
        return self._to_response(book)

    def get_book_detail(self, book_id: str) -> Optional[BookV2DetailResponse]:
        """Get V2 book with full chapter information."""
        book = self.repository.get_by_id(book_id)
        if not book or getattr(book, "pipeline_version", 1) != 2:
            return None

        chapters = self.chapter_repository.get_by_book_id(book_id)
        chapter_responses = [self._to_chapter_response(ch) for ch in chapters]

        return BookV2DetailResponse(
            id=book.id,
            title=book.title,
            author=book.author,
            edition=book.edition,
            edition_year=book.edition_year,
            country=book.country,
            board=book.board,
            grade=book.grade,
            subject=book.subject,
            pipeline_version=2,
            chapters=chapter_responses,
            created_at=book.created_at,
            updated_at=book.updated_at,
        )

    def list_books(
        self,
        country: Optional[str] = None,
        board: Optional[str] = None,
        grade: Optional[int] = None,
        subject: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> BookV2ListResponse:
        """List V2 books with optional filters."""
        # Filter to pipeline_version=2 at DB level before pagination
        query = self.db.query(Book).filter(Book.pipeline_version == 2)

        if country:
            query = query.filter(Book.country == country)
        if board:
            query = query.filter(Book.board == board)
        if grade is not None:
            query = query.filter(Book.grade == grade)
        if subject:
            query = query.filter(Book.subject == subject)

        total = query.count()
        v2_books = query.order_by(Book.created_at.desc()).limit(limit).offset(offset).all()

        return BookV2ListResponse(
            books=[self._to_response(b) for b in v2_books],
            total=total,
        )

    def delete_book(self, book_id: str) -> bool:
        """Delete V2 book, all chapters, and all S3 data."""
        book = self.repository.get_by_id(book_id)
        if not book or getattr(book, "pipeline_version", 1) != 2:
            return False

        # Delete S3 folder
        prefix = f"books/{book_id}/"
        self.s3_client.delete_folder(prefix)
        logger.info(f"Deleted S3 folder: {prefix}")

        # Explicit cascade delete (no FK constraints on V2 tables)
        chapters = self.chapter_repository.get_by_book_id(book_id)
        topic_repo = TopicRepository(self.db)
        page_repo = ChapterPageRepository(self.db)
        chunk_repo = ChunkRepository(self.db)
        job_repo = ProcessingJobRepository(self.db)

        for ch in chapters:
            topic_repo.delete_by_chapter_id(ch.id)
            chunk_repo.delete_by_chapter_id(ch.id)
            page_repo.delete_by_chapter_id(ch.id)
            job_repo.delete_by_chapter_id(ch.id)

        self.chapter_repository.delete_by_book_id(book_id)

        success = self.repository.delete(book_id)
        logger.info(f"Deleted V2 book and all child records: {book_id}")
        return success

    def _generate_book_id(self, request: CreateBookV2Request) -> str:
        """Generate a unique book ID from metadata."""
        author_slug = request.author.lower().replace(" ", "_") if request.author else "unknown"
        subject_slug = request.subject.lower().replace(" ", "_")
        grade = request.grade
        edition_year = request.edition_year or datetime.now().year

        base_id = f"{author_slug}_{subject_slug}_{grade}_{edition_year}"

        counter = 1
        book_id = base_id
        while self.repository.get_by_id(book_id):
            book_id = f"{base_id}_{counter}"
            counter += 1

        return book_id

    def _to_response(self, book: Book) -> BookV2Response:
        """Convert Book ORM model to V2 response schema."""
        chapter_count = self.chapter_repository.count_by_book_id(book.id)

        return BookV2Response(
            id=book.id,
            title=book.title,
            author=book.author,
            edition=book.edition,
            edition_year=book.edition_year,
            country=book.country,
            board=book.board,
            grade=book.grade,
            subject=book.subject,
            pipeline_version=2,
            chapter_count=chapter_count,
            created_at=book.created_at,
            updated_at=book.updated_at,
            created_by=book.created_by,
        )

    def _to_chapter_response(self, chapter) -> ChapterResponse:
        """Convert BookChapter ORM model to response schema."""
        return ChapterResponse(
            id=chapter.id,
            chapter_number=chapter.chapter_number,
            chapter_title=chapter.chapter_title,
            start_page=chapter.start_page,
            end_page=chapter.end_page,
            display_name=chapter.display_name,
            summary=chapter.summary,
            status=chapter.status,
            total_pages=chapter.total_pages,
            uploaded_page_count=chapter.uploaded_page_count,
            error_message=chapter.error_message,
            error_type=chapter.error_type,
            created_at=chapter.created_at,
            updated_at=chapter.updated_at,
        )
