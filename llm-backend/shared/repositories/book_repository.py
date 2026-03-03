"""Repository for Book data access."""
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from shared.models.entities import Book


class BookRepository:
    """
    Repository for Book database operations.

    Follows the repository pattern used in the existing codebase.
    """

    def __init__(self, db: Session):
        self.db = db

    def create(self, book: Book) -> Book:
        """Create a new book."""
        self.db.add(book)
        self.db.commit()
        self.db.refresh(book)
        return book

    def get_by_id(self, book_id: str) -> Optional[Book]:
        """Get book by ID."""
        return self.db.query(Book).filter(Book.id == book_id).first()

    def get_all(
        self,
        country: Optional[str] = None,
        board: Optional[str] = None,
        grade: Optional[int] = None,
        subject: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Book]:
        """Get books with optional filters."""
        query = self.db.query(Book)

        if country:
            query = query.filter(Book.country == country)
        if board:
            query = query.filter(Book.board == board)
        if grade is not None:
            query = query.filter(Book.grade == grade)
        if subject:
            query = query.filter(Book.subject == subject)

        return query.order_by(Book.created_at.desc()).limit(limit).offset(offset).all()

    def count(
        self,
        country: Optional[str] = None,
        board: Optional[str] = None,
        grade: Optional[int] = None,
        subject: Optional[str] = None
    ) -> int:
        """Count books with optional filters."""
        query = self.db.query(Book)

        if country:
            query = query.filter(Book.country == country)
        if board:
            query = query.filter(Book.board == board)
        if grade is not None:
            query = query.filter(Book.grade == grade)
        if subject:
            query = query.filter(Book.subject == subject)

        return query.count()

    def update(self, book: Book) -> Book:
        """Update book instance."""
        self.db.commit()
        self.db.refresh(book)
        return book

    def delete(self, book_id: str) -> bool:
        """Delete book by ID."""
        book = self.get_by_id(book_id)
        if book:
            self.db.delete(book)
            self.db.commit()
            return True
        return False

    def get_by_curriculum(self, country: str, board: str, grade: int, subject: str) -> List[Book]:
        """Get books matching exact curriculum parameters."""
        return self.db.query(Book).filter(
            and_(
                Book.country == country,
                Book.board == board,
                Book.grade == grade,
                Book.subject == subject
            )
        ).all()
