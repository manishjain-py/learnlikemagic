"""
TOC service — business logic for Table of Contents management.

Handles TOC validation, chapter creation, range overlap checks, and lock enforcement.
"""
import uuid
import logging
from typing import List, Optional
from sqlalchemy.orm import Session

from shared.repositories.book_repository import BookRepository
from book_ingestion_v2.constants import ChapterStatus
from book_ingestion_v2.models.database import BookChapter
from book_ingestion_v2.models.schemas import (
    TOCEntry,
    SaveTOCRequest,
    TOCResponse,
    ChapterResponse,
)
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository

logger = logging.getLogger(__name__)


class TOCService:
    """Service for TOC authoring and validation."""

    def __init__(self, db: Session):
        self.db = db
        self.book_repository = BookRepository(db)
        self.chapter_repository = ChapterRepository(db)

    def save_toc(self, book_id: str, request: SaveTOCRequest) -> TOCResponse:
        """
        Create or replace the full TOC for a book.

        Validates all entries, checks for range overlaps, and creates chapter rows.
        Raises ValueError if validation fails or if any existing chapter has uploaded pages.
        """
        # Validate book exists and is V2
        book = self.book_repository.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")
        if getattr(book, "pipeline_version", 1) != 2:
            raise ValueError(f"Book {book_id} is not a V2 book")

        # Check if any existing chapter has uploaded pages (locked)
        existing_chapters = self.chapter_repository.get_by_book_id(book_id)
        for ch in existing_chapters:
            if ch.uploaded_page_count > 0:
                raise ValueError(
                    f"Cannot replace TOC: Chapter {ch.chapter_number} "
                    f"('{ch.chapter_title}') has {ch.uploaded_page_count} uploaded pages. "
                    f"Delete uploaded pages first to unlock."
                )

        # Validate the TOC entries
        self._validate_toc_entries(request.chapters)

        # Delete existing chapters (safe since none have pages)
        self.chapter_repository.delete_by_book_id(book_id)

        # Create new chapters
        new_chapters = []
        for entry in request.chapters:
            chapter = BookChapter(
                id=str(uuid.uuid4()),
                book_id=book_id,
                chapter_number=entry.chapter_number,
                chapter_title=entry.chapter_title,
                start_page=entry.start_page,
                end_page=entry.end_page,
                notes=entry.notes,
                status=ChapterStatus.TOC_DEFINED.value,
                total_pages=entry.end_page - entry.start_page + 1,
                uploaded_page_count=0,
            )
            new_chapters.append(chapter)

        created = self.chapter_repository.create_all(new_chapters)
        logger.info(f"Saved TOC for book {book_id}: {len(created)} chapters")

        return TOCResponse(
            book_id=book_id,
            chapters=[self._to_chapter_response(ch) for ch in created],
        )

    def get_toc(self, book_id: str) -> TOCResponse:
        """Get all TOC entries for a book."""
        chapters = self.chapter_repository.get_by_book_id(book_id)
        return TOCResponse(
            book_id=book_id,
            chapters=[self._to_chapter_response(ch) for ch in chapters],
        )

    def update_chapter(
        self, book_id: str, chapter_id: str, entry: TOCEntry
    ) -> ChapterResponse:
        """
        Update a single chapter entry.

        Blocked if chapter has uploaded pages.
        """
        chapter = self.chapter_repository.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise ValueError(f"Chapter not found: {chapter_id}")

        if chapter.uploaded_page_count > 0:
            raise ValueError(
                f"Cannot update chapter {chapter.chapter_number}: "
                f"has {chapter.uploaded_page_count} uploaded pages. Delete pages first."
            )

        # Validate updated entry doesn't overlap with other chapters
        all_chapters = self.chapter_repository.get_by_book_id(book_id)
        other_entries = [
            TOCEntry(
                chapter_number=ch.chapter_number,
                chapter_title=ch.chapter_title,
                start_page=ch.start_page,
                end_page=ch.end_page,
            )
            for ch in all_chapters
            if ch.id != chapter_id
        ]
        other_entries.append(entry)
        self._validate_toc_entries(other_entries)

        # Apply updates
        chapter.chapter_number = entry.chapter_number
        chapter.chapter_title = entry.chapter_title
        chapter.start_page = entry.start_page
        chapter.end_page = entry.end_page
        chapter.notes = entry.notes
        chapter.total_pages = entry.end_page - entry.start_page + 1

        updated = self.chapter_repository.update(chapter)
        logger.info(f"Updated chapter {chapter_id} for book {book_id}")
        return self._to_chapter_response(updated)

    def delete_chapter(self, book_id: str, chapter_id: str) -> bool:
        """
        Delete a single chapter entry.

        Blocked if chapter has uploaded pages.
        """
        chapter = self.chapter_repository.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise ValueError(f"Chapter not found: {chapter_id}")

        if chapter.uploaded_page_count > 0:
            raise ValueError(
                f"Cannot delete chapter {chapter.chapter_number}: "
                f"has {chapter.uploaded_page_count} uploaded pages. Delete pages first."
            )

        return self.chapter_repository.delete(chapter_id)

    def _validate_toc_entries(self, entries: List[TOCEntry]):
        """
        Validate TOC entries for correctness.

        Checks:
        - Ranges are positive and bounded (end >= start, start > 0)
        - Chapter numbers are sequential (1, 2, 3, ...)
        - Ranges do not overlap
        """
        if not entries:
            raise ValueError("TOC must have at least one chapter")

        # Check sequential chapter numbers
        sorted_entries = sorted(entries, key=lambda e: e.chapter_number)
        for i, entry in enumerate(sorted_entries):
            expected = i + 1
            if entry.chapter_number != expected:
                raise ValueError(
                    f"Chapter numbers must be sequential starting from 1. "
                    f"Expected {expected}, got {entry.chapter_number}"
                )

        # Check individual range validity
        for entry in sorted_entries:
            if entry.start_page <= 0:
                raise ValueError(
                    f"Chapter {entry.chapter_number}: start_page must be positive, "
                    f"got {entry.start_page}"
                )
            if entry.end_page < entry.start_page:
                raise ValueError(
                    f"Chapter {entry.chapter_number}: end_page ({entry.end_page}) "
                    f"must be >= start_page ({entry.start_page})"
                )

        # Check for range overlaps
        for i in range(len(sorted_entries)):
            for j in range(i + 1, len(sorted_entries)):
                a = sorted_entries[i]
                b = sorted_entries[j]
                if a.start_page <= b.end_page and b.start_page <= a.end_page:
                    raise ValueError(
                        f"Page range overlap between chapter {a.chapter_number} "
                        f"({a.start_page}-{a.end_page}) and chapter {b.chapter_number} "
                        f"({b.start_page}-{b.end_page})"
                    )

    def _to_chapter_response(self, chapter: BookChapter) -> ChapterResponse:
        """Convert BookChapter ORM model to response schema."""
        return ChapterResponse(
            id=chapter.id,
            chapter_number=chapter.chapter_number,
            chapter_title=chapter.chapter_title,
            start_page=chapter.start_page,
            end_page=chapter.end_page,
            notes=chapter.notes,
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
