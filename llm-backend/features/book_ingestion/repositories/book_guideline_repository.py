"""Repository for BookGuideline data access."""
from typing import List, Optional
from sqlalchemy.orm import Session

from features.book_ingestion.models.database import BookGuideline


class BookGuidelineRepository:
    """
    Repository for BookGuideline database operations.

    Handles storage and retrieval of book guideline metadata.
    """

    def __init__(self, db: Session):
        """
        Initialize repository with database session.

        Args:
            db: SQLAlchemy session
        """
        self.db = db

    def create(self, guideline: BookGuideline) -> BookGuideline:
        """
        Create a new book guideline.

        Args:
            guideline: BookGuideline instance to create

        Returns:
            Created guideline instance
        """
        self.db.add(guideline)
        self.db.commit()
        self.db.refresh(guideline)
        return guideline

    def get_by_id(self, guideline_id: str) -> Optional[BookGuideline]:
        """
        Get guideline by ID.

        Args:
            guideline_id: Guideline identifier

        Returns:
            BookGuideline instance or None if not found
        """
        return self.db.query(BookGuideline).filter(BookGuideline.id == guideline_id).first()

    def get_by_book_id(self, book_id: str) -> List[BookGuideline]:
        """
        Get all guidelines for a book (all versions).

        Args:
            book_id: Book identifier

        Returns:
            List of BookGuideline instances
        """
        return self.db.query(BookGuideline).filter(
            BookGuideline.book_id == book_id
        ).order_by(BookGuideline.version.desc()).all()

    def get_latest_by_book_id(self, book_id: str) -> Optional[BookGuideline]:
        """
        Get the latest guideline for a book.

        Args:
            book_id: Book identifier

        Returns:
            Latest BookGuideline instance or None if not found
        """
        return self.db.query(BookGuideline).filter(
            BookGuideline.book_id == book_id
        ).order_by(BookGuideline.version.desc()).first()

    def update_status(
        self,
        guideline_id: str,
        status: str,
        reviewed_by: Optional[str] = None
    ) -> Optional[BookGuideline]:
        """
        Update guideline status and review information.

        Args:
            guideline_id: Guideline identifier
            status: New status (pending_review, approved, rejected)
            reviewed_by: Username of reviewer

        Returns:
            Updated guideline instance or None if not found
        """
        from datetime import datetime

        guideline = self.get_by_id(guideline_id)
        if guideline:
            guideline.status = status
            if reviewed_by:
                guideline.reviewed_by = reviewed_by
                guideline.reviewed_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(guideline)
        return guideline

    def delete(self, guideline_id: str) -> bool:
        """
        Delete guideline by ID.

        Args:
            guideline_id: Guideline identifier

        Returns:
            True if deleted, False if not found
        """
        guideline = self.get_by_id(guideline_id)
        if guideline:
            self.db.delete(guideline)
            self.db.commit()
            return True
        return False
