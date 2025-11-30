"""Repository for Book data access."""
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from features.book_ingestion.models.database import Book


class BookRepository:
    """
    Repository for Book database operations.

    Follows the repository pattern used in the existing codebase.
    """

    def __init__(self, db: Session):
        """
        Initialize repository with database session.

        Args:
            db: SQLAlchemy session
        """
        self.db = db

    def create(self, book: Book) -> Book:
        """
        Create a new book.

        Args:
            book: Book instance to create

        Returns:
            Created book instance with database state
        """
        self.db.add(book)
        self.db.commit()
        self.db.refresh(book)
        return book

    def get_by_id(self, book_id: str) -> Optional[Book]:
        """
        Get book by ID.

        Args:
            book_id: Book identifier

        Returns:
            Book instance or None if not found
        """
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
        """
        Get books with optional filters.

        Args:
            country: Filter by country
            board: Filter by board
            grade: Filter by grade
            subject: Filter by subject
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of Book instances
        """
        query = self.db.query(Book)

        # Apply filters
        if country:
            query = query.filter(Book.country == country)
        if board:
            query = query.filter(Book.board == board)
        if grade is not None:
            query = query.filter(Book.grade == grade)
        if subject:
            query = query.filter(Book.subject == subject)

        # Apply pagination and order
        return query.order_by(Book.created_at.desc()).limit(limit).offset(offset).all()

    def count(
        self,
        country: Optional[str] = None,
        board: Optional[str] = None,
        grade: Optional[int] = None,
        subject: Optional[str] = None
    ) -> int:
        """
        Count books with optional filters.

        Args:
            country: Filter by country
            board: Filter by board
            grade: Filter by grade
            subject: Filter by subject

        Returns:
            Number of matching books
        """
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
        """
        Update book instance.

        Args:
            book: Book instance with updated fields

        Returns:
            Updated book instance
        """
        self.db.commit()
        self.db.refresh(book)
        return book

    def delete(self, book_id: str) -> bool:
        """
        Delete book by ID.

        Args:
            book_id: Book identifier

        Returns:
            True if deleted, False if not found
        """
        book = self.get_by_id(book_id)
        if book:
            self.db.delete(book)
            self.db.commit()
            return True
        return False

    def get_by_curriculum(self, country: str, board: str, grade: int, subject: str) -> List[Book]:
        """
        Get books matching exact curriculum parameters.

        Args:
            country: Country name
            board: Board name
            grade: Grade number
            subject: Subject name

        Returns:
            List of matching books
        """
        return self.db.query(Book).filter(
            and_(
                Book.country == country,
                Book.board == board,
                Book.grade == grade,
                Book.subject == subject
            )
        ).all()
