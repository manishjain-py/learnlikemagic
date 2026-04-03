"""
Topic sync service — syncs chapter_topics → teaching_guidelines table.

Maps V2 hierarchy (chapter→topic) directly:
  V2 chapter → teaching_guidelines "chapter"
  V2 topic   → teaching_guidelines "topic"
"""
import uuid
import logging
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from shared.repositories.book_repository import BookRepository
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

        if chapter.status not in [ChapterStatus.CHAPTER_COMPLETED.value, ChapterStatus.NEEDS_REVIEW.value]:
            raise ValueError(
                f"Chapter must be completed to sync (status: {chapter.status})"
            )

        topics = self.topic_repo.get_final_topics(chapter_id)
        if not topics:
            topics = self.topic_repo.get_by_chapter_id(chapter_id)

        errors = []
        synced = 0

        # Check if a refresher topic exists before deleting
        chapter_key = f"chapter-{chapter.chapter_number}"
        refresher_existed = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.chapter_key == chapter_key,
            TeachingGuideline.topic_key == "get-ready",
        ).count() > 0

        if refresher_existed:
            logger.warning(
                f"Re-sync will delete refresher topic for chapter {chapter_key}"
            )

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
            refresher_deleted=refresher_existed,
        )

    def sync_book(self, book_id: str) -> SyncResponse:
        """Sync all completed chapters for a book."""
        book = self.book_repo.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        chapters = self.chapter_repo.get_by_book_id(book_id)
        completed = [
            ch for ch in chapters
            if ch.status in [ChapterStatus.CHAPTER_COMPLETED.value, ChapterStatus.NEEDS_REVIEW.value]
        ]

        total_topics = 0
        total_errors = []
        synced_chapters = 0
        any_refresher_deleted = False

        for chapter in completed:
            result = self.sync_chapter(book_id, chapter.id)
            total_topics += result.synced_topics
            total_errors.extend(result.errors)
            synced_chapters += 1
            if result.refresher_deleted:
                any_refresher_deleted = True

        return SyncResponse(
            synced_chapters=synced_chapters,
            synced_topics=total_topics,
            errors=total_errors,
            refresher_deleted=any_refresher_deleted,
        )

    def _sync_topic(
        self, book, chapter: BookChapter, topic: ChapterTopic
    ):
        """Create a teaching_guidelines row from a V2 topic."""
        chapter_key = f"chapter-{chapter.chapter_number}"
        chapter_title = chapter.display_name or chapter.chapter_title

        # Build a short teaching description from guidelines (first ~500 chars)
        teaching_desc = topic.guidelines[:500] if topic.guidelines else topic.topic_title
        description = topic.summary or f"Teaching guide for {topic.topic_title}"

        guideline = TeachingGuideline(
            id=str(uuid.uuid4()),
            country=book.country,
            board=book.board,
            grade=book.grade,
            subject=book.subject,
            chapter=chapter_title,
            topic=topic.topic_title,
            guideline=topic.guidelines,
            teaching_description=teaching_desc,
            description=description,
            chapter_key=chapter_key,
            chapter_title=chapter_title,
            chapter_summary=chapter.summary,
            topic_key=topic.topic_key,
            topic_title=topic.topic_title,
            topic_summary=topic.summary,
            chapter_sequence=chapter.chapter_number,
            topic_sequence=topic.sequence_order,
            book_id=book.id,
            source_page_start=topic.source_page_start,
            source_page_end=topic.source_page_end,
            prior_topics_context=topic.prior_topics_context,
            status="approved",
            review_status="APPROVED",
            version=topic.version,
            generated_at=datetime.utcnow(),
        )

        self.db.add(guideline)
        self.db.commit()

    def _delete_chapter_guidelines(self, book_id: str, chapter: BookChapter):
        """Delete existing teaching_guidelines for this chapter."""
        chapter_key = f"chapter-{chapter.chapter_number}"
        self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.chapter_key == chapter_key,
        ).delete()
        self.db.commit()
