"""Repository for ChapterTopic data access."""
from typing import List, Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import ChapterTopic


class TopicRepository:
    """Repository for ChapterTopic database operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, topic: ChapterTopic) -> ChapterTopic:
        """Create a new topic."""
        self.db.add(topic)
        self.db.commit()
        self.db.refresh(topic)
        return topic

    def create_all(self, topics: List[ChapterTopic]) -> List[ChapterTopic]:
        """Create multiple topics in a single transaction."""
        self.db.add_all(topics)
        self.db.commit()
        for t in topics:
            self.db.refresh(t)
        return topics

    def get_by_id(self, topic_id: str) -> Optional[ChapterTopic]:
        """Get topic by ID."""
        return self.db.query(ChapterTopic).filter(
            ChapterTopic.id == topic_id
        ).first()

    def get_by_chapter_id(self, chapter_id: str) -> List[ChapterTopic]:
        """Get all topics for a chapter, ordered by sequence."""
        return self.db.query(ChapterTopic).filter(
            ChapterTopic.chapter_id == chapter_id
        ).order_by(ChapterTopic.sequence_order).all()

    def get_by_chapter_and_key(
        self, chapter_id: str, topic_key: str
    ) -> Optional[ChapterTopic]:
        """Get a specific topic by chapter ID and topic key."""
        return self.db.query(ChapterTopic).filter(
            ChapterTopic.chapter_id == chapter_id,
            ChapterTopic.topic_key == topic_key
        ).first()

    def get_by_book_id(self, book_id: str) -> List[ChapterTopic]:
        """Get all topics for a book, ordered by chapter and sequence."""
        return self.db.query(ChapterTopic).filter(
            ChapterTopic.book_id == book_id
        ).order_by(ChapterTopic.chapter_id, ChapterTopic.sequence_order).all()

    def get_final_topics(self, chapter_id: str) -> List[ChapterTopic]:
        """Get topics with 'final' or 'approved' status for a chapter."""
        return self.db.query(ChapterTopic).filter(
            ChapterTopic.chapter_id == chapter_id,
            ChapterTopic.status.in_(["final", "approved"])
        ).order_by(ChapterTopic.sequence_order).all()

    def count_by_chapter(self, chapter_id: str) -> int:
        """Count topics for a chapter."""
        return self.db.query(ChapterTopic).filter(
            ChapterTopic.chapter_id == chapter_id
        ).count()

    def update(self, topic: ChapterTopic) -> ChapterTopic:
        """Update topic instance."""
        self.db.commit()
        self.db.refresh(topic)
        return topic

    def delete(self, topic_id: str) -> bool:
        """Delete topic by ID."""
        topic = self.get_by_id(topic_id)
        if topic:
            self.db.delete(topic)
            self.db.commit()
            return True
        return False

    def delete_by_chapter_id(self, chapter_id: str) -> int:
        """Delete all topics for a chapter. Returns count deleted."""
        count = self.db.query(ChapterTopic).filter(
            ChapterTopic.chapter_id == chapter_id
        ).delete()
        self.db.commit()
        return count
