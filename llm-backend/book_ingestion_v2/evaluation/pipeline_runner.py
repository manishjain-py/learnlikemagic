"""
Pipeline Runner

Runs the book ingestion extraction pipeline on a chapter and collects results,
or loads existing topics from DB when --skip-extraction is used.
"""

import uuid
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from config import get_settings
from shared.utils.s3_client import get_s3_client
from shared.services.llm_service import LLMService
from shared.services.llm_config_service import LLMConfigService
from shared.repositories.book_repository import BookRepository

from book_ingestion_v2.constants import LLM_CONFIG_KEY, V2JobType, V2JobStatus
from book_ingestion_v2.models.database import BookChapter, ChapterProcessingJob
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.chapter_page_repository import ChapterPageRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from book_ingestion_v2.services.chapter_job_service import ChapterJobService
from book_ingestion_v2.services.topic_extraction_orchestrator import TopicExtractionOrchestrator

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Runs extraction pipeline on a chapter and collects output."""

    def __init__(self, db: Session):
        self.db = db
        self.s3_client = get_s3_client()

    def _load_chapter(self, chapter_id: str) -> tuple[BookChapter, dict]:
        """Load chapter and book metadata."""
        chapter_repo = ChapterRepository(self.db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter:
            raise ValueError(f"Chapter not found: {chapter_id}")

        book_repo = BookRepository(self.db)
        book = book_repo.get_by_id(chapter.book_id)
        book_metadata = {
            "title": book.title,
            "subject": book.subject,
            "grade": book.grade,
            "board": book.board,
        }
        return chapter, book_metadata

    def _load_page_texts(self, chapter_id: str) -> list[dict]:
        """Load all OCR'd page texts for a chapter."""
        page_repo = ChapterPageRepository(self.db)
        pages = page_repo.get_by_chapter_id(chapter_id)
        result = []
        for page in sorted(pages, key=lambda p: p.page_number):
            if page.ocr_status == "completed" and page.text_s3_key:
                text = self.s3_client.download_bytes(page.text_s3_key).decode("utf-8")
                result.append({"page_number": page.page_number, "text": text})
        return result

    def _topics_to_dicts(self, topics) -> list[dict]:
        """Convert ChapterTopic ORM objects to dicts."""
        return [
            {
                "topic_key": t.topic_key,
                "topic_title": t.topic_title,
                "guidelines": t.guidelines,
                "summary": t.summary or "",
                "source_page_start": t.source_page_start,
                "source_page_end": t.source_page_end,
                "sequence_order": t.sequence_order,
                "status": t.status,
            }
            for t in topics
        ]

    def load_existing(self, chapter_id: str) -> dict:
        """Load existing topics from DB without re-running extraction."""
        chapter, book_metadata = self._load_chapter(chapter_id)
        page_texts = self._load_page_texts(chapter_id)

        topic_repo = TopicRepository(self.db)
        topics = topic_repo.get_by_chapter_id(chapter_id)

        return {
            "chapter": {
                "id": chapter.id,
                "chapter_number": chapter.chapter_number,
                "chapter_title": chapter.chapter_title,
                "start_page": chapter.start_page,
                "end_page": chapter.end_page,
                "status": chapter.status,
            },
            "book_metadata": book_metadata,
            "topics": self._topics_to_dicts(topics),
            "original_pages": page_texts,
            "extraction_mode": "existing",
        }

    def run_extraction(self, chapter_id: str) -> dict:
        """Run full extraction pipeline and return results."""
        chapter, book_metadata = self._load_chapter(chapter_id)
        page_texts = self._load_page_texts(chapter_id)

        # Create a job record
        job_service = ChapterJobService(self.db)
        job_id = str(uuid.uuid4())
        job = ChapterProcessingJob(
            id=job_id,
            book_id=chapter.book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.TOPIC_EXTRACTION.value,
            status=V2JobStatus.RUNNING.value,
            started_at=datetime.utcnow(),
        )
        self.db.add(job)
        self.db.commit()

        # Delete existing topics (clean slate)
        topic_repo = TopicRepository(self.db)
        topic_repo.delete_by_chapter_id(chapter_id)

        # Run the orchestrator
        orchestrator = TopicExtractionOrchestrator(self.db)
        orchestrator.extract(
            db=self.db,
            job_id=job_id,
            chapter_id=chapter_id,
            book_id=chapter.book_id,
        )

        # Reload final topics
        topics = topic_repo.get_by_chapter_id(chapter_id)

        return {
            "chapter": {
                "id": chapter.id,
                "chapter_number": chapter.chapter_number,
                "chapter_title": chapter.chapter_title,
                "start_page": chapter.start_page,
                "end_page": chapter.end_page,
                "status": chapter.status,
            },
            "book_metadata": book_metadata,
            "topics": self._topics_to_dicts(topics),
            "original_pages": page_texts,
            "extraction_mode": "fresh",
            "job_id": job_id,
        }
