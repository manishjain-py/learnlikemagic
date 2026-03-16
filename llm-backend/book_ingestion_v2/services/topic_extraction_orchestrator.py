"""
Topic extraction orchestrator — full chapter extraction + auto-finalization.

Orchestrates chunk-by-chunk processing for a chapter:
1. Validate chapter readiness
2. Acquire job lock
3. Build chunk windows
4. Process each chunk, accumulating topic map
5. Persist draft topics
6. Auto-trigger finalization
7. Release job lock
"""
import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from config import get_settings
from database import get_db_manager
from shared.utils.s3_client import get_s3_client
from shared.services.llm_service import LLMService
from shared.services.llm_config_service import LLMConfigService

from book_ingestion_v2.constants import (
    ChapterStatus, V2JobType, V2JobStatus, LLM_CONFIG_KEY,
)
from book_ingestion_v2.models.database import BookChapter, ChapterChunk, ChapterTopic, ChapterProcessingJob
from book_ingestion_v2.models.processing_models import (
    ChunkInput, RunningState, TopicAccumulator,
    PlannedTopic, ChapterTopicPlan,
)
from book_ingestion_v2.services.chapter_topic_planner_service import ChapterTopicPlannerService
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.chapter_page_repository import ChapterPageRepository
from book_ingestion_v2.repositories.chunk_repository import ChunkRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from book_ingestion_v2.services.chapter_job_service import ChapterJobService
from book_ingestion_v2.services.chunk_processor_service import ChunkProcessorService
from book_ingestion_v2.services.chapter_finalization_service import ChapterFinalizationService
from book_ingestion_v2.utils.chunk_builder import build_chunk_windows

logger = logging.getLogger(__name__)


class TopicExtractionOrchestrator:
    """Orchestrates the full extraction + finalization pipeline for a chapter."""

    def __init__(self, db: Session):
        self.db = db
        self.chapter_repo = ChapterRepository(db)
        self.page_repo = ChapterPageRepository(db)
        self.chunk_repo = ChunkRepository(db)
        self.topic_repo = TopicRepository(db)
        self.job_service = ChapterJobService(db)
        self.s3_client = get_s3_client()

    def _refresh_db_session(self):
        """Get a fresh DB session after long-running LLM calls.

        The DB connection may have been killed by the server during a long
        idle period (e.g. a 90-855s Claude Code call). This closes the old
        session and gets a new connection from the pool.
        """
        try:
            self.db.close()
        except Exception:
            pass
        self.db = get_db_manager().get_session()
        self.chapter_repo = ChapterRepository(self.db)
        self.page_repo = ChapterPageRepository(self.db)
        self.chunk_repo = ChunkRepository(self.db)
        self.topic_repo = TopicRepository(self.db)
        self.job_service = ChapterJobService(self.db)

    def extract(
        self, db: Session, job_id: str, chapter_id: str, book_id: str, resume: bool = False
    ):
        """
        Main extraction entry point. Called by background task runner.

        This function runs in a background thread with its own DB session.
        The job_id has already been created; the runner calls start_job() before this.
        """
        # Rebind all repos to the background thread's DB session
        self.db = db
        self.chapter_repo = ChapterRepository(db)
        self.page_repo = ChapterPageRepository(db)
        self.chunk_repo = ChunkRepository(db)
        self.topic_repo = TopicRepository(db)
        self.job_service = ChapterJobService(db)

        # Reload chapter in this session
        chapter = self.chapter_repo.get_by_id(chapter_id)
        if not chapter:
            raise ValueError(f"Chapter not found: {chapter_id}")

        # Build LLM service
        settings = get_settings()
        config = LLMConfigService(db).get_config(LLM_CONFIG_KEY)
        llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        chunk_processor = ChunkProcessorService(llm_service)

        # Get book metadata
        from shared.repositories.book_repository import BookRepository
        book_repo = BookRepository(db)
        book = book_repo.get_by_id(book_id)
        book_metadata = {
            "title": book.title,
            "subject": book.subject,
            "grade": book.grade,
            "board": book.board,
        }

        # Build page list early — needed by both planner and chunk builder
        pages = self.page_repo.get_by_chapter_id(chapter_id)
        page_numbers = [p.page_number for p in pages if p.ocr_status == "completed"]

        # ── Chapter-level topic planning (skip on resume — plan is restored later) ──
        planned_topics = None

        if not resume:
            planner_service = ChapterTopicPlannerService(llm_service)
            try:
                self.job_service.update_progress(
                    job_id, current_item="Planning chapter topics...", completed=0, failed=0
                )

                # Load all OCR'd page texts for the planner
                all_page_texts = []
                for pn in page_numbers:
                    page = self.page_repo.get_by_chapter_and_page_number(chapter_id, pn)
                    if page and page.text_s3_key:
                        text = self.s3_client.download_bytes(page.text_s3_key).decode("utf-8")
                        all_page_texts.append({"page_number": pn, "text": text})

                chapter_metadata = {
                    "number": chapter.chapter_number,
                    "title": chapter.chapter_title,
                    "page_range": f"{chapter.start_page}-{chapter.end_page}",
                }

                plan = planner_service.plan_chapter(book_metadata, chapter_metadata, all_page_texts)
                planned_topics = plan.topics

                # Refresh DB session after LLM call
                self._refresh_db_session()

                # Save plan to job record
                job_record = self.db.query(ChapterProcessingJob).filter(
                    ChapterProcessingJob.id == job_id
                ).first()
                if job_record:
                    job_record.planned_topics_json = json.dumps(plan.model_dump())
                    self.db.commit()

                logger.info(f"Chapter planned: {len(planned_topics)} topics")

            except Exception as e:
                logger.warning(f"Chapter planner failed, falling back to unguided extraction: {e}")
                planned_topics = None
                self._refresh_db_session()

        # Update chapter status
        chapter = self.chapter_repo.get_by_id(chapter_id)
        chapter.status = ChapterStatus.TOPIC_EXTRACTION.value
        chapter.error_message = None
        chapter.error_type = None
        self.chapter_repo.update(chapter)

        self.job_service.update_progress(
            job_id, current_item="Building chunk windows", completed=0, failed=0
        )

        # Build chunk windows from OCR'd pages
        chunk_windows = build_chunk_windows(page_numbers)

        total_chunks = len(chunk_windows)

        # Initialize accumulator
        state = RunningState()

        # Pre-populate state from plan
        if planned_topics:
            for pt in planned_topics:
                state.topic_guidelines_map[pt.topic_key] = TopicAccumulator(
                    topic_key=pt.topic_key,
                    topic_title=pt.title,
                    guidelines="",
                    source_page_start=pt.page_start,
                    source_page_end=pt.page_end,
                )

        # Determine resume point
        start_chunk = 0
        if resume:
            # Find the previous job's chunks — query all jobs for this chapter,
            # pick the most recent one that isn't the current job.
            prev_job = db.query(ChapterProcessingJob).filter(
                ChapterProcessingJob.chapter_id == chapter_id,
                ChapterProcessingJob.job_type == V2JobType.TOPIC_EXTRACTION.value,
                ChapterProcessingJob.id != job_id,
            ).order_by(ChapterProcessingJob.created_at.desc()).first()

            last_chunk = self.chunk_repo.get_last_completed_chunk(prev_job.id) if prev_job else None
            if last_chunk:
                start_chunk = last_chunk.chunk_index + 1
                # Restore state from last completed chunk
                if last_chunk.chapter_summary_after:
                    state.chapter_summary_so_far = last_chunk.chapter_summary_after
                # Restore topic map from DB draft topics
                existing_topics = self.topic_repo.get_by_chapter_id(chapter_id)
                for t in existing_topics:
                    state.topic_guidelines_map[t.topic_key] = TopicAccumulator(
                        topic_key=t.topic_key,
                        topic_title=t.topic_title,
                        guidelines=t.guidelines,
                        source_page_start=t.source_page_start or chapter.start_page,
                        source_page_end=t.source_page_end or chapter.end_page,
                    )
                logger.info(f"Resuming from chunk {start_chunk}")

            # Restore planned topics from previous job
            if prev_job and prev_job.planned_topics_json:
                try:
                    prev_plan = ChapterTopicPlan(**json.loads(prev_job.planned_topics_json))
                    planned_topics = prev_plan.topics
                    # Copy plan to current job for self-containment
                    job_record = self.db.query(ChapterProcessingJob).filter(
                        ChapterProcessingJob.id == job_id
                    ).first()
                    if job_record:
                        job_record.planned_topics_json = prev_job.planned_topics_json
                        self.db.commit()
                except Exception:
                    logger.warning("Failed to restore planned topics from previous job")

        # S3 run directory
        ch_num = str(chapter.chapter_number).zfill(2)
        s3_run_base = f"books/{book_id}/chapters/{ch_num}/processing/runs/{job_id}"

        # Save run config
        run_config = {
            "job_id": job_id,
            "chapter_id": chapter_id,
            "book_id": book_id,
            "model_provider": config["provider"],
            "model_id": config["model_id"],
            "total_chunks": total_chunks,
            "resume_from": start_chunk,
            "started_at": datetime.utcnow().isoformat(),
        }
        self.s3_client.upload_bytes(
            json.dumps(run_config, indent=2).encode("utf-8"),
            f"{s3_run_base}/config.json",
        )

        # Save planned topics to S3 for audit
        if planned_topics:
            self.s3_client.upload_bytes(
                json.dumps([pt.model_dump() for pt in planned_topics], indent=2).encode("utf-8"),
                f"{s3_run_base}/planned_topics.json",
            )

        # Process each chunk
        completed = start_chunk
        failed = 0

        for window in chunk_windows[start_chunk:]:
            chunk_idx = window.chunk_index
            chunk_idx_str = str(chunk_idx).zfill(3)

            self.job_service.update_progress(
                job_id,
                current_item=f"Processing chunk {chunk_idx + 1}/{total_chunks} "
                             f"(pages {window.pages[0]}-{window.pages[-1]})",
                completed=completed,
                failed=failed,
            )

            # Load page texts
            current_pages = []
            for pn in window.pages:
                page = self.page_repo.get_by_chapter_and_page_number(chapter_id, pn)
                if page and page.text_s3_key:
                    text = self.s3_client.download_bytes(page.text_s3_key).decode("utf-8")
                    current_pages.append({"page_number": pn, "text": text})

            # Load previous page context
            prev_context = None
            if window.previous_page:
                prev_page = self.page_repo.get_by_chapter_and_page_number(
                    chapter_id, window.previous_page
                )
                if prev_page and prev_page.text_s3_key:
                    prev_context = self.s3_client.download_bytes(
                        prev_page.text_s3_key
                    ).decode("utf-8")

            # Build chunk input
            chunk_input = ChunkInput(
                book_metadata=book_metadata,
                chapter_metadata={
                    "number": chapter.chapter_number,
                    "title": chapter.chapter_title,
                    "page_range": f"{chapter.start_page}-{chapter.end_page}",
                },
                current_pages=current_pages,
                previous_page_context=prev_context,
                chapter_summary_so_far=state.chapter_summary_so_far,
                topics_so_far=list(state.topic_guidelines_map.values()),
            )

            # Save chunk input to S3
            self.s3_client.upload_bytes(
                json.dumps(chunk_input.model_dump(), indent=2).encode("utf-8"),
                f"{s3_run_base}/chunks/{chunk_idx_str}/input.json",
            )

            # Process chunk
            try:
                output = chunk_processor.process_chunk(chunk_input, planned_topics=planned_topics)

                # Refresh DB session — connection may have gone stale
                # during the long LLM call
                self._refresh_db_session()

                # Update accumulator
                state.chapter_summary_so_far = output.updated_chapter_summary
                for topic_update in output.topics:
                    # Determine if this is a new topic
                    is_new_topic = topic_update.is_new  # unguided mode
                    if planned_topics and topic_update.topic_assignment == "unplanned":
                        is_new_topic = True
                    elif planned_topics and topic_update.topic_assignment == "planned":
                        is_new_topic = False

                    if is_new_topic and topic_update.topic_key not in state.topic_guidelines_map:
                        state.topic_guidelines_map[topic_update.topic_key] = TopicAccumulator(
                            topic_key=topic_update.topic_key,
                            topic_title=topic_update.topic_title,
                            guidelines=f"## Pages {window.pages[0]}-{window.pages[-1]}\n"
                                       f"{topic_update.guidelines_for_this_chunk}",
                            source_page_start=window.pages[0],
                            source_page_end=window.pages[-1],
                        )
                    else:
                        existing = state.topic_guidelines_map.get(topic_update.topic_key)
                        if existing:
                            existing.guidelines += (
                                f"\n\n## Pages {window.pages[0]}-{window.pages[-1]}\n"
                                f"{topic_update.guidelines_for_this_chunk}"
                            )
                            existing.source_page_end = window.pages[-1]

                # Save chunk output to S3
                self.s3_client.upload_bytes(
                    json.dumps(output.model_dump(), indent=2).encode("utf-8"),
                    f"{s3_run_base}/chunks/{chunk_idx_str}/output.json",
                )

                # Save state snapshot
                self.s3_client.upload_bytes(
                    json.dumps(state.model_dump(), indent=2).encode("utf-8"),
                    f"{s3_run_base}/chunks/{chunk_idx_str}/state_after.json",
                )

                # Save chunk DB record
                chunk_record = ChapterChunk(
                    id=str(uuid.uuid4()),
                    chapter_id=chapter_id,
                    processing_job_id=job_id,
                    chunk_index=chunk_idx,
                    page_start=window.pages[0],
                    page_end=window.pages[-1],
                    previous_page_text=prev_context,
                    chapter_summary_before=chunk_input.chapter_summary_so_far,
                    raw_llm_response=json.dumps(output.model_dump()),
                    topics_detected_json=json.dumps([t.model_dump() for t in output.topics]),
                    chapter_summary_after=output.updated_chapter_summary,
                    status="completed",
                    model_provider=config["provider"],
                    model_id=config["model_id"],
                    prompt_hash=chunk_processor.get_prompt_hash(),
                    completed_at=datetime.utcnow(),
                )
                self.chunk_repo.create(chunk_record)
                completed += 1

            except Exception as e:
                # Refresh session in case the error was connection-related
                self._refresh_db_session()
                # Record failed chunk
                chunk_record = ChapterChunk(
                    id=str(uuid.uuid4()),
                    chapter_id=chapter_id,
                    processing_job_id=job_id,
                    chunk_index=chunk_idx,
                    page_start=window.pages[0],
                    page_end=window.pages[-1],
                    status="failed",
                    error_message=str(e),
                    model_provider=config["provider"],
                    model_id=config["model_id"],
                )
                self.chunk_repo.create(chunk_record)
                failed += 1
                logger.error(f"Chunk {chunk_idx} failed: {e}")

        # Refresh session before batch DB writes
        self._refresh_db_session()

        # Persist draft topics to DB
        self.topic_repo.delete_by_chapter_id(chapter_id)
        for topic_key, acc in state.topic_guidelines_map.items():
            # Determine topic_assignment
            topic_assignment = None
            if planned_topics:
                planned_keys = {pt.topic_key for pt in planned_topics}
                topic_assignment = "planned" if acc.topic_key in planned_keys else "unplanned"

            topic = ChapterTopic(
                id=str(uuid.uuid4()),
                book_id=book_id,
                chapter_id=chapter_id,
                topic_key=acc.topic_key,
                topic_title=acc.topic_title,
                guidelines=acc.guidelines,
                source_page_start=acc.source_page_start,
                source_page_end=acc.source_page_end,
                status="draft",
                topic_assignment=topic_assignment,
            )
            self.topic_repo.create(topic)

        # Reload chapter (original object is detached after session refreshes)
        chapter = self.chapter_repo.get_by_id(chapter_id)

        # Check for failures
        if failed > 0:
            self.job_service.update_progress(
                job_id, current_item="Extraction complete with errors",
                completed=completed, failed=failed,
            )
            chapter.status = ChapterStatus.FAILED.value
            chapter.error_message = f"{failed} chunks failed out of {total_chunks}"
            chapter.error_type = "retryable"
            self.chapter_repo.update(chapter)
            self.job_service.release_lock(
                job_id, status=V2JobStatus.COMPLETED_WITH_ERRORS.value,
                error=f"{failed} chunks failed",
            )
            return

        # Auto-trigger finalization
        self.job_service.update_progress(
            job_id, current_item="Running finalization...",
            completed=completed, failed=0,
        )
        chapter.status = ChapterStatus.CHAPTER_FINALIZING.value
        self.chapter_repo.update(chapter)

        try:
            finalization_service = ChapterFinalizationService(
                self.db, llm_service, book_metadata,
                job_service=self.job_service, job_id=job_id,
            )
            result = finalization_service.finalize(chapter, job_id, planned_topics=planned_topics)

            # Refresh and reload after finalization (which does its own LLM calls)
            self._refresh_db_session()
            chapter = self.chapter_repo.get_by_id(chapter_id)
            chapter.status = result.final_status  # NOT unconditionally CHAPTER_COMPLETED
            self.chapter_repo.update(chapter)

            self.job_service.release_lock(
                job_id, status=V2JobStatus.COMPLETED.value
            )
            logger.info(f"Chapter {chapter_id} extraction + finalization complete (status={result.final_status})")

        except Exception as e:
            self._refresh_db_session()
            chapter = self.chapter_repo.get_by_id(chapter_id)
            chapter.status = ChapterStatus.FAILED.value
            chapter.error_message = f"Finalization failed: {e}"
            chapter.error_type = "retryable"
            self.chapter_repo.update(chapter)
            self.job_service.release_lock(
                job_id, status=V2JobStatus.FAILED.value, error=str(e)
            )
            raise
