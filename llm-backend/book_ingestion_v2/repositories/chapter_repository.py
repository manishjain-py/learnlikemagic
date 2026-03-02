"""Repository for BookChapter data access."""
from typing import List, Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import BookChapter


class ChapterRepository:
    """Repository for BookChapter database operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, chapter: BookChapter) -> BookChapter:
        """Create a new chapter."""
        self.db.add(chapter)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def create_all(self, chapters: List[BookChapter]) -> List[BookChapter]:
        """Create multiple chapters in a single transaction."""
        self.db.add_all(chapters)
        self.db.commit()
        for ch in chapters:
            self.db.refresh(ch)
        return chapters

    def get_by_id(self, chapter_id: str) -> Optional[BookChapter]:
        """Get chapter by ID."""
        return self.db.query(BookChapter).filter(
            BookChapter.id == chapter_id
        ).first()

    def get_by_book_id(self, book_id: str) -> List[BookChapter]:
        """Get all chapters for a book, ordered by chapter number."""
        return self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()

    def get_by_book_and_number(self, book_id: str, chapter_number: int) -> Optional[BookChapter]:
        """Get a specific chapter by book ID and chapter number."""
        return self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id,
            BookChapter.chapter_number == chapter_number
        ).first()

    def update(self, chapter: BookChapter) -> BookChapter:
        """Update chapter instance."""
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def delete(self, chapter_id: str) -> bool:
        """Delete chapter by ID."""
        chapter = self.get_by_id(chapter_id)
        if chapter:
            self.db.delete(chapter)
            self.db.commit()
            return True
        return False

    def delete_by_book_id(self, book_id: str) -> int:
        """Delete all chapters for a book. Returns count deleted."""
        count = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).delete()
        self.db.commit()
        return count

    def count_by_book_id(self, book_id: str) -> int:
        """Count chapters for a book."""
        return self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).count()

    def has_uploaded_pages(self, chapter_id: str) -> bool:
        """Check if chapter has any uploaded pages."""
        chapter = self.get_by_id(chapter_id)
        if not chapter:
            return False
        return chapter.uploaded_page_count > 0
