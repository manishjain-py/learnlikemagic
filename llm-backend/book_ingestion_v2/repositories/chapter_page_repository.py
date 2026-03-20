"""Repository for ChapterPage data access."""
from typing import List, Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import ChapterPage


class ChapterPageRepository:
    """Repository for ChapterPage database operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, page: ChapterPage) -> ChapterPage:
        """Create a new page."""
        self.db.add(page)
        self.db.commit()
        self.db.refresh(page)
        return page

    def get_by_id(self, page_id: str) -> Optional[ChapterPage]:
        """Get page by ID."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.id == page_id
        ).first()

    def get_by_chapter_id(self, chapter_id: str) -> List[ChapterPage]:
        """Get all pages for a chapter, ordered by page number."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id
        ).order_by(ChapterPage.page_number).all()

    def get_by_chapter_and_page_number(
        self, chapter_id: str, page_number: int
    ) -> Optional[ChapterPage]:
        """Get a specific page by chapter ID and page number."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id,
            ChapterPage.page_number == page_number
        ).first()

    def get_by_book_and_page_number(
        self, book_id: str, page_number: int
    ) -> Optional[ChapterPage]:
        """Get page by book ID and absolute page number."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.book_id == book_id,
            ChapterPage.page_number == page_number
        ).first()

    def count_by_chapter(self, chapter_id: str) -> int:
        """Count pages uploaded for a chapter."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id
        ).count()

    def count_ocr_completed(self, chapter_id: str) -> int:
        """Count pages with completed OCR for a chapter."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id,
            ChapterPage.ocr_status == "completed"
        ).count()

    def get_failed_ocr_pages(self, chapter_id: str) -> List[ChapterPage]:
        """Get pages with failed OCR for a chapter."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id,
            ChapterPage.ocr_status == "failed"
        ).order_by(ChapterPage.page_number).all()

    def get_pages_needing_ocr(self, chapter_id: str) -> List[ChapterPage]:
        """Get pages with pending or failed OCR, ordered by page number."""
        return self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id,
            ChapterPage.ocr_status.in_(["pending", "failed"]),
        ).order_by(ChapterPage.page_number).all()

    def reset_ocr_for_chapter(self, chapter_id: str) -> int:
        """Reset OCR for all pages in chapter. Returns count updated."""
        count = self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id
        ).update({
            ChapterPage.ocr_status: "pending",
            ChapterPage.text_s3_key: None,
            ChapterPage.ocr_error: None,
            ChapterPage.ocr_completed_at: None,
        })
        self.db.commit()
        return count

    def update(self, page: ChapterPage) -> ChapterPage:
        """Update page instance."""
        self.db.commit()
        self.db.refresh(page)
        return page

    def delete(self, page_id: str) -> bool:
        """Delete page by ID."""
        page = self.get_by_id(page_id)
        if page:
            self.db.delete(page)
            self.db.commit()
            return True
        return False

    def delete_by_chapter_id(self, chapter_id: str) -> int:
        """Delete all pages for a chapter. Returns count deleted."""
        count = self.db.query(ChapterPage).filter(
            ChapterPage.chapter_id == chapter_id
        ).delete()
        self.db.commit()
        return count
