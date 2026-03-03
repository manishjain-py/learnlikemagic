"""
Topic sync service — syncs chapter_topics → teaching_guidelines table.

Maps V2 hierarchy (chapter→topic) to V1 table structure (topic→subtopic):
  V2 chapter → teaching_guidelines "topic" (top-level navigation)
  V2 topic   → teaching_guidelines "subtopic" (actual learning unit)
"""
import uuid
import logging
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from book_ingestion.repositories.book_repository import BookRepository
from book_ingestion_v2.constants import ChapterStatus
from book_ingestion_v2.models.database import BookChapter, ChapterTopic
from book_ingestion_v2.models.schemas import SyncResponse
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from shared.models.entities import TeachingGuideline

logger = logging.getLogger(__name__)


class TopicSyncService:
    """Syncs V2 chapter_topics to teaching_guidelines table."""

    def __init__(self, db: Session):
        self.db = db
        self.book_repo = BookRepository(db)
        self.chapter_repo = ChapterRepository(db)
        self.topic_repo = TopicRepository(db)

    def sync_chapter(self, book_id: str, chapter_id: str) -> SyncResponse:
        """Sync a single completed chapter to teaching_guidelines."""
        book = self.book_repo.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        chapter = self.chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise ValueError(f"Chapter not found: {chapter_id}")

        if chapter.status != ChapterStatus.CHAPTER_COMPLETED.value:
            raise ValueError(
                f"Chapter must be completed to sync (status: {chapter.status})"
            )

        topics = self.topic_repo.get_final_topics(chapter_id)
        if not topics:
            topics = self.topic_repo.get_by_chapter_id(chapter_id)

        errors = []
        synced = 0

        # Delete existing guidelines for this chapter
        self._delete_chapter_guidelines(book_id, chapter)

        for topic in topics:
            try:
                self._sync_topic(book, chapter, topic)
                synced += 1
            except Exception as e:
                errors.append(f"Topic '{topic.topic_key}': {e}")
                logger.warning(f"Failed to sync topic {topic.topic_key}: {e}")

        logger.info(
            f"Synced chapter {chapter_id}: {synced} topics, {len(errors)} errors"
        )

        return SyncResponse(
            synced_chapters=1,
            synced_topics=synced,
            errors=errors,
        )

    def sync_book(self, book_id: str) -> SyncResponse:
        """Sync all completed chapters for a book."""
        book = self.book_repo.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        chapters = self.chapter_repo.get_by_book_id(book_id)
        completed = [
            ch for ch in chapters
            if ch.status == ChapterStatus.CHAPTER_COMPLETED.value
        ]

        total_topics = 0
        total_errors = []
        synced_chapters = 0

        for chapter in completed:
            result = self.sync_chapter(book_id, chapter.id)
            total_topics += result.synced_topics
            total_errors.extend(result.errors)
            synced_chapters += 1

        return SyncResponse(
            synced_chapters=synced_chapters,
            synced_topics=total_topics,
            errors=total_errors,
        )

    def _sync_topic(
        self, book, chapter: BookChapter, topic: ChapterTopic
    ):
        """Create a teaching_guidelines row from a V2 topic."""
        # V2 mapping: chapter = "topic" level, topic = "subtopic" level
        topic_key = f"chapter-{chapter.chapter_number}"
        topic_title = chapter.display_name or chapter.chapter_title

        # Build a short teaching description from guidelines (first ~500 chars)
        teaching_desc = topic.guidelines[:500] if topic.guidelines else topic.topic_title
        description = topic.summary or f"Teaching guide for {topic.topic_title}"

        guideline = TeachingGuideline(
            id=str(uuid.uuid4()),
            country=book.country,
            board=book.board,
            grade=book.grade,
            subject=book.subject,
            topic=topic_title,
            subtopic=topic.topic_title,
            guideline=topic.guidelines,
            teaching_description=teaching_desc,
            description=description,
            topic_key=topic_key,
            topic_title=topic_title,
            topic_summary=chapter.summary,
            subtopic_key=topic.topic_key,
            subtopic_title=topic.topic_title,
            subtopic_summary=topic.summary,
            topic_sequence=chapter.chapter_number,
            subtopic_sequence=topic.sequence_order,
            book_id=book.id,
            source_page_start=topic.source_page_start,
            source_page_end=topic.source_page_end,
            status="approved",
            review_status="APPROVED",
            version=topic.version,
            generated_at=datetime.utcnow(),
        )

        self.db.add(guideline)
        self.db.commit()

    def _delete_chapter_guidelines(self, book_id: str, chapter: BookChapter):
        """Delete existing teaching_guidelines for this chapter."""
        topic_key = f"chapter-{chapter.chapter_number}"
        self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.topic_key == topic_key,
        ).delete()
        self.db.commit()
