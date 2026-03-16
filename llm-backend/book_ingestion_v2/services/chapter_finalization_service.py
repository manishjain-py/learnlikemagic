"""
Chapter finalization service — consolidation, dedup, naming, sequencing.

Runs after all chunks are extracted. Produces final topic set for a chapter.
"""
import json
import logging
from pathlib import Path
from typing import List

from book_ingestion_v2.models.database import ChapterTopic, BookChapter
from book_ingestion_v2.models.processing_models import ConsolidationOutput
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.constants import TopicStatus
from shared.services.llm_service import LLMService
from shared.utils.s3_client import get_s3_client

logger = logging.getLogger(__name__)

_CONSOLIDATION_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "chapter_consolidation.txt"
_CONSOLIDATION_TEMPLATE = _CONSOLIDATION_PROMPT_PATH.read_text()

_MERGE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "topic_guidelines_merge.txt"
_MERGE_TEMPLATE = _MERGE_PROMPT_PATH.read_text()


class ChapterFinalizationService:
    """Handles chapter-level consolidation after extraction."""

    def __init__(self, db, llm_service: LLMService, book_metadata: dict, job_service=None, job_id: str = None):
        self.db = db
        self.llm_service = llm_service
        self.book_metadata = book_metadata
        self.topic_repo = TopicRepository(db)
        self.chapter_repo = ChapterRepository(db)
        self.s3_client = get_s3_client()
        self.job_service = job_service
        self.job_id = job_id

    def _refresh_db_session(self):
        """Get a fresh DB session after long-running LLM calls."""
        from database import get_db_manager
        try:
            self.db.close()
        except Exception:
            pass
        self.db = get_db_manager().get_session()
        self.topic_repo = TopicRepository(self.db)
        self.chapter_repo = ChapterRepository(self.db)
        if self.job_service:
            from book_ingestion_v2.services.chapter_job_service import ChapterJobService
            self.job_service = ChapterJobService(self.db)

    def finalize(self, chapter: BookChapter, job_id: str) -> ConsolidationOutput:
        """
        Run full finalization pipeline for a chapter.

        1. Load draft topics
        2. LLM-merge each topic's appended guidelines into unified text
        3. Call consolidation LLM for dedup, naming, sequencing
        4. Execute merge actions
        5. Apply topic updates
        6. Save final output to S3 and DB
        """
        chapter_id = chapter.id
        book_id = chapter.book_id
        ch_num = str(chapter.chapter_number).zfill(2)
        s3_run_base = f"books/{book_id}/chapters/{ch_num}/processing/runs/{job_id}"

        # Save chapter metadata as plain values — ORM objects become detached
        # after DB session refreshes between long LLM calls
        chapter_title = chapter.chapter_title
        chapter_number = chapter.chapter_number

        # 1. Load draft topics
        draft_topics = self.topic_repo.get_by_chapter_id(chapter_id)
        if not draft_topics:
            raise ValueError(f"No draft topics found for chapter {chapter_id}")

        logger.info(f"Finalizing chapter {chapter_id}: {len(draft_topics)} draft topics")

        # 2. Save pre-consolidation snapshot
        pre_snapshot = [
            {"topic_key": t.topic_key, "topic_title": t.topic_title,
             "guidelines_length": len(t.guidelines), "status": t.status}
            for t in draft_topics
        ]
        self.s3_client.upload_bytes(
            json.dumps(pre_snapshot, indent=2).encode("utf-8"),
            f"{s3_run_base}/pre_consolidation.json",
        )

        # 3. LLM-merge each topic's appended guidelines
        # Pre-extract into plain dicts — ORM objects will become detached
        # after the first session refresh
        topics_to_merge = [
            {
                "topic_key": t.topic_key,
                "topic_title": t.topic_title,
                "guidelines": t.guidelines,
            }
            for t in draft_topics
            if "## Pages" in t.guidelines
        ]
        merge_count = len(topics_to_merge)
        merged_so_far = 0

        for topic_data in topics_to_merge:
            merged_so_far += 1
            self._heartbeat(f"Merging guidelines: {merged_so_far}/{merge_count} topics")

            # Build prompt from pre-extracted data (no ORM dependency)
            prompt = _MERGE_TEMPLATE.format(
                book_title=self.book_metadata.get("title", ""),
                subject=self.book_metadata.get("subject", ""),
                grade=self.book_metadata.get("grade", ""),
                chapter_title=chapter_title,
                topic_title=topic_data["topic_title"],
                existing_guidelines=topic_data["guidelines"],
            )
            result = self.llm_service.call(prompt=prompt, json_mode=False)
            merged = result.get("output_text", "").strip()

            # Refresh DB session after LLM call, reload topic from DB
            self._refresh_db_session()
            topic = self.topic_repo.get_by_chapter_and_key(
                chapter_id, topic_data["topic_key"]
            )
            if topic:
                topic.guidelines = merged
                topic.status = TopicStatus.CONSOLIDATED.value
                self.topic_repo.update(topic)

        # 4. Call consolidation LLM — reload everything from DB
        self._heartbeat("Running consolidation...")
        draft_topics = self.topic_repo.get_by_chapter_id(chapter_id)
        chapter = self.chapter_repo.get_by_id(chapter_id)
        consolidation_output = self._run_consolidation(chapter, draft_topics)

        # Refresh DB session after LLM call
        self._refresh_db_session()

        # Save consolidation output
        self.s3_client.upload_bytes(
            json.dumps(consolidation_output.model_dump(), indent=2).encode("utf-8"),
            f"{s3_run_base}/consolidation_output.json",
        )

        # 5. Execute merge actions
        for merge in consolidation_output.merge_actions:
            self._execute_merge_by_id(chapter_id, merge.merge_from, merge.merge_into)

        # 6. Apply topic updates
        for update in consolidation_output.topic_updates:
            topic = self.topic_repo.get_by_chapter_and_key(chapter_id, update.original_key)
            if not topic:
                continue

            topic.topic_key = update.new_key
            topic.topic_title = update.new_title
            topic.summary = update.summary
            topic.sequence_order = update.sequence_order
            topic.status = TopicStatus.FINAL.value
            self.topic_repo.update(topic)

        # 7. Update chapter
        chapter = self.chapter_repo.get_by_id(chapter_id)
        chapter.display_name = consolidation_output.chapter_display_name
        chapter.summary = consolidation_output.final_chapter_summary
        self.chapter_repo.update(chapter)

        # 8. Save final output to S3
        final_topics = self.topic_repo.get_by_chapter_id(chapter_id)
        self._save_final_output(chapter, final_topics, job_id)

        logger.info(
            f"Finalization complete for chapter {chapter_id}: "
            f"{len(final_topics)} final topics, "
            f"{len(consolidation_output.merge_actions)} merges"
        )

        return consolidation_output

    def _heartbeat(self, detail: str = None):
        """Update job heartbeat to prevent stale detection."""
        if self.job_service and self.job_id:
            try:
                self.job_service.update_progress(self.job_id, current_item=detail)
            except Exception:
                pass

    def _merge_topic_guidelines(self, chapter: BookChapter, topic: ChapterTopic) -> str:
        """LLM-merge appended per-chunk guidelines into unified text."""
        prompt = _MERGE_TEMPLATE.format(
            book_title=self.book_metadata.get("title", ""),
            subject=self.book_metadata.get("subject", ""),
            grade=self.book_metadata.get("grade", ""),
            chapter_title=chapter.chapter_title,
            topic_title=topic.topic_title,
            existing_guidelines=topic.guidelines,
        )

        result = self.llm_service.call(prompt=prompt, json_mode=False)
        return result.get("output_text", "").strip()

    def _run_consolidation(
        self, chapter: BookChapter, topics: List[ChapterTopic]
    ) -> ConsolidationOutput:
        """Call the consolidation LLM."""
        topics_data = [
            {
                "topic_key": t.topic_key,
                "topic_title": t.topic_title,
                "guidelines_preview": t.guidelines[:500],
                "guidelines_length": len(t.guidelines),
                "source_pages": f"{t.source_page_start}-{t.source_page_end}",
            }
            for t in topics
        ]

        prompt = _CONSOLIDATION_TEMPLATE.format(
            book_title=self.book_metadata.get("title", ""),
            subject=self.book_metadata.get("subject", ""),
            grade=self.book_metadata.get("grade", ""),
            board=self.book_metadata.get("board", ""),
            chapter_number=chapter.chapter_number,
            chapter_title=chapter.chapter_title,
            topic_count=len(topics),
            topics_json=json.dumps(topics_data, indent=2),
        )

        result = self.llm_service.call(prompt=prompt, json_mode=True)
        output_text = result.get("output_text", "")

        # Parse response
        text = output_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]

        data = json.loads(text.strip())
        return ConsolidationOutput(**data)

    def _execute_merge_by_id(self, chapter_id: str, merge_from_key: str, merge_into_key: str):
        """Merge one topic into another."""
        from_topic = self.topic_repo.get_by_chapter_and_key(chapter_id, merge_from_key)
        into_topic = self.topic_repo.get_by_chapter_and_key(chapter_id, merge_into_key)

        if not from_topic or not into_topic:
            logger.warning(
                f"Merge skipped: {merge_from_key} → {merge_into_key} "
                f"(topic not found)"
            )
            return

        # Append guidelines from merged topic
        into_topic.guidelines += f"\n\n{from_topic.guidelines}"

        # Expand source page range
        if from_topic.source_page_start and into_topic.source_page_start:
            into_topic.source_page_start = min(
                into_topic.source_page_start, from_topic.source_page_start
            )
        if from_topic.source_page_end and into_topic.source_page_end:
            into_topic.source_page_end = max(
                into_topic.source_page_end, from_topic.source_page_end
            )

        self.topic_repo.update(into_topic)
        self.topic_repo.delete(from_topic.id)

        logger.info(f"Merged topic '{merge_from_key}' into '{merge_into_key}'")

    def _save_final_output(
        self, chapter: BookChapter, topics: List[ChapterTopic], job_id: str
    ):
        """Save final chapter result and individual topics to S3."""
        book_id = chapter.book_id
        ch_num = str(chapter.chapter_number).zfill(2)
        output_base = f"books/{book_id}/chapters/{ch_num}/output"

        # Chapter result
        chapter_result = {
            "chapter_number": chapter.chapter_number,
            "chapter_title": chapter.chapter_title,
            "display_name": chapter.display_name,
            "summary": chapter.summary,
            "topic_count": len(topics),
            "job_id": job_id,
        }
        self.s3_client.upload_bytes(
            json.dumps(chapter_result, indent=2).encode("utf-8"),
            f"{output_base}/chapter_result.json",
        )

        # Individual topics
        for topic in topics:
            topic_data = {
                "topic_key": topic.topic_key,
                "topic_title": topic.topic_title,
                "guidelines": topic.guidelines,
                "summary": topic.summary,
                "source_page_start": topic.source_page_start,
                "source_page_end": topic.source_page_end,
                "sequence_order": topic.sequence_order,
            }
            self.s3_client.upload_bytes(
                json.dumps(topic_data, indent=2).encode("utf-8"),
                f"{output_base}/topics/{topic.topic_key}.json",
            )
