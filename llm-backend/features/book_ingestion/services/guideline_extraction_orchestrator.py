"""
Guideline Extraction Orchestrator

Responsibility: Coordinate the entire guideline extraction pipeline.

Single Responsibility Principle:
- Only handles orchestration logic (calling other services in sequence)
- No LLM calls (delegates to component services)
- No business logic (delegates to component services)

Pipeline Flow (for each page):
1. Load page OCR text
2. Generate minisummary
3. Build context pack
4. Detect subtopic boundary
5. Extract page facts
6. Merge facts into shard (reducer)
7. Update indices (index management)
8. Check stability (stability detector)
9. If stable: generate teaching description, validate quality, sync to DB
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from openai import OpenAI
from sqlalchemy.orm import Session

from ..models.guideline_models import (
    SubtopicShard,
    PageGuideline,
    PageFacts,
    DecisionMetadata,
    slugify
)
from ..utils.s3_client import S3Client

# Import all component services
from .minisummary_service import MinisummaryService
from .context_pack_service import ContextPackService
from .boundary_detection_service import BoundaryDetectionService
from .facts_extraction_service import FactsExtractionService
from .reducer_service import ReducerService
from .stability_detector_service import StabilityDetectorService
from .index_management_service import IndexManagementService
from .teaching_description_generator import TeachingDescriptionGenerator
from .quality_gates_service import QualityGatesService
from .db_sync_service import DBSyncService

logger = logging.getLogger(__name__)


class GuidelineExtractionOrchestrator:
    """
    Orchestrate the entire guideline extraction pipeline.

    This is the main entry point for extracting teaching guidelines
    from textbook pages. It coordinates all 9+ component services.
    """

    def __init__(
        self,
        s3_client: S3Client,
        openai_client: Optional[OpenAI] = None,
        db_session: Optional[Session] = None
    ):
        """
        Initialize orchestrator with all component services.

        Args:
            s3_client: S3 client for reading/writing files
            openai_client: Optional OpenAI client (if None, creates new one)
            db_session: Optional database session (if None, DB sync disabled)
        """
        self.s3 = s3_client
        self.openai_client = openai_client or OpenAI()
        self.db_session = db_session

        # Initialize component services
        self.minisummary = MinisummaryService(self.openai_client)
        self.context_pack = ContextPackService(self.s3)
        self.boundary_detector = BoundaryDetectionService(self.openai_client)
        self.facts_extractor = FactsExtractionService(self.openai_client)
        self.reducer = ReducerService()
        self.stability_detector = StabilityDetectorService()
        self.index_manager = IndexManagementService(self.s3)
        self.teaching_desc_gen = TeachingDescriptionGenerator(self.openai_client)
        self.quality_gates = QualityGatesService()
        self.db_sync = DBSyncService(self.db_session) if self.db_session else None

        logger.info("Initialized GuidelineExtractionOrchestrator with all component services")

    def extract_guidelines_for_book(
        self,
        book_id: str,
        book_metadata: Dict[str, Any],
        start_page: int = 1,
        end_page: Optional[int] = None,
        auto_sync_to_db: bool = False
    ) -> Dict[str, Any]:
        """
        Extract guidelines for an entire book.

        Args:
            book_id: Book identifier
            book_metadata: Book metadata (grade, subject, board, total_pages)
            start_page: Starting page number (default: 1)
            end_page: Ending page number (default: total_pages)
            auto_sync_to_db: If True, automatically sync final shards to database

        Returns:
            Dict with extraction results and statistics

        Pipeline:
            For each page (start_page to end_page):
            1. Process page (extract, merge, update indices)
            2. Check for stable subtopics
            3. Finalize stable subtopics (teaching desc, quality, DB sync)
        """
        total_pages = book_metadata.get("total_pages", 100)
        end_page = end_page or total_pages

        logger.info(
            f"Starting guideline extraction for book {book_id}: "
            f"pages {start_page}-{end_page}, auto_sync={auto_sync_to_db}"
        )

        stats = {
            "pages_processed": 0,
            "subtopics_created": 0,
            "subtopics_finalized": 0,
            "errors": [],
            "warnings": []
        }

        try:
            # Process each page sequentially
            for page_num in range(start_page, end_page + 1):
                try:
                    logger.info(f"Processing page {page_num}/{end_page}...")

                    # Process single page
                    page_result = self.process_page(
                        book_id=book_id,
                        page_num=page_num,
                        book_metadata=book_metadata
                    )

                    stats["pages_processed"] += 1

                    if page_result.get("new_subtopic_created"):
                        stats["subtopics_created"] += 1

                    # Check for stable subtopics
                    stable_subtopics = self.check_and_finalize_stable_subtopics(
                        book_id=book_id,
                        current_page=page_num,
                        book_metadata=book_metadata,
                        auto_sync_to_db=auto_sync_to_db
                    )

                    stats["subtopics_finalized"] += len(stable_subtopics)

                    logger.info(
                        f"Page {page_num} complete: "
                        f"{stats['subtopics_created']} subtopics created, "
                        f"{stats['subtopics_finalized']} finalized"
                    )

                except Exception as e:
                    error_msg = f"Error processing page {page_num}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    stats["errors"].append(error_msg)
                    # Continue processing next page

            logger.info(
                f"Guideline extraction complete for book {book_id}: "
                f"{stats['pages_processed']} pages, "
                f"{stats['subtopics_created']} subtopics, "
                f"{stats['subtopics_finalized']} finalized, "
                f"{len(stats['errors'])} errors"
            )

            return stats

        except Exception as e:
            logger.error(f"Guideline extraction failed for book {book_id}: {str(e)}", exc_info=True)
            raise

    def process_page(
        self,
        book_id: str,
        page_num: int,
        book_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single page through the pipeline.

        Args:
            book_id: Book identifier
            page_num: Page number
            book_metadata: Book metadata

        Returns:
            Dict with page processing results

        Steps:
        1. Load page OCR text
        2. Generate minisummary
        3. Build context pack
        4. Detect subtopic boundary
        5. Extract page facts
        6. Merge facts into shard
        7. Save updated shard to S3
        8. Update indices
        9. Save page guideline
        """
        logger.debug(f"Processing page {page_num}...")

        # Step 1: Load page OCR text
        page_text = self._load_page_text(book_id, page_num)

        # Step 2: Generate minisummary
        minisummary = self.minisummary.generate(page_text)

        # Step 3: Build context pack
        context_pack = self.context_pack.build(
            book_id=book_id,
            current_page=page_num,
            book_metadata=book_metadata
        )

        # Step 4: Detect subtopic boundary
        decision, topic_key, topic_title, subtopic_key, subtopic_title, confidence = \
            self.boundary_detector.detect(
                context_pack=context_pack,
                minisummary=minisummary,
                default_topic_key=f"{book_metadata.get('subject', 'unknown').lower()}-grade-{book_metadata.get('grade', 0)}"
            )

        # Step 5: Extract page facts
        page_facts = self.facts_extractor.extract(
            page_text=page_text,
            subtopic_title=subtopic_title,
            grade=book_metadata.get("grade", 3),
            subject=book_metadata.get("subject", "Math")
        )

        # Step 6: Load or create shard, then merge facts
        shard = self._load_or_create_shard(
            book_id=book_id,
            topic_key=topic_key,
            topic_title=topic_title,
            subtopic_key=subtopic_key,
            subtopic_title=subtopic_title,
            page_facts=page_facts,
            page_num=page_num
        )

        new_subtopic_created = (shard.version == 1)

        if not new_subtopic_created:
            # Merge facts into existing shard
            shard = self.reducer.merge(shard, page_facts, page_num)

        # Step 7: Save updated shard to S3
        self._save_shard(shard)

        # Step 8: Update indices
        self._update_indices(
            book_id=book_id,
            topic_key=topic_key,
            topic_title=topic_title,
            subtopic_key=subtopic_key,
            subtopic_title=subtopic_title,
            page_num=page_num,
            confidence=confidence,
            status=shard.status
        )

        # Step 9: Save page guideline
        page_guideline = PageGuideline(
            book_id=book_id,
            page=page_num,
            assigned_topic_key=topic_key,
            assigned_subtopic_key=subtopic_key,
            assigned_topic_title=topic_title,
            assigned_subtopic_title=subtopic_title,
            confidence=confidence,
            summary=minisummary,
            facts=page_facts,
            provisional=False,
            decision_metadata=DecisionMetadata(
                decision=decision,
                continue_score=0.0,  # Not stored in MVP v1
                new_score=0.0
            )
        )
        self._save_page_guideline(page_guideline)

        logger.debug(
            f"Page {page_num} processed: {topic_key}/{subtopic_key}, "
            f"confidence={confidence:.2f}, new_subtopic={new_subtopic_created}"
        )

        return {
            "page_num": page_num,
            "topic_key": topic_key,
            "subtopic_key": subtopic_key,
            "confidence": confidence,
            "new_subtopic_created": new_subtopic_created,
            "facts_count": {
                "objectives": len(page_facts.objectives_add),
                "examples": len(page_facts.examples_add),
                "misconceptions": len(page_facts.misconceptions_add),
                "assessments": len(page_facts.assessments_add)
            }
        }

    def check_and_finalize_stable_subtopics(
        self,
        book_id: str,
        current_page: int,
        book_metadata: Dict[str, Any],
        auto_sync_to_db: bool = False
    ) -> List[Tuple[str, str]]:
        """
        Check for stable subtopics and finalize them.

        Args:
            book_id: Book identifier
            current_page: Current page number
            book_metadata: Book metadata
            auto_sync_to_db: If True, sync to database

        Returns:
            List of (topic_key, subtopic_key) that were finalized

        Steps (for each stable subtopic):
        1. Mark shard as stable
        2. Generate teaching description
        3. Run quality validation
        4. Update quality flags
        5. Save updated shard
        6. Optionally sync to database
        """
        # Load indices
        index = self.index_manager.get_or_create_index(book_id)
        page_index = self.index_manager.get_or_create_page_index(book_id)

        # Detect stable subtopics
        stable_subtopics = self.stability_detector.detect_stable_subtopics(
            index=index,
            page_index=page_index,
            current_page=current_page
        )

        finalized = []

        for topic_key, subtopic_key in stable_subtopics:
            try:
                logger.info(f"Finalizing stable subtopic: {topic_key}/{subtopic_key}")

                # Load shard
                shard = self._load_shard(book_id, topic_key, subtopic_key)

                # Step 1: Mark as stable
                shard = self.stability_detector.mark_as_stable(shard)

                # Step 2: Generate teaching description
                teaching_description, is_valid = self.teaching_desc_gen.generate_with_validation(
                    shard=shard,
                    grade=book_metadata.get("grade", 3),
                    subject=book_metadata.get("subject", "Math"),
                    max_retries=2
                )
                shard.teaching_description = teaching_description

                # Step 3: Run quality validation
                validation_result = self.quality_gates.validate(shard)

                # Step 4: Update quality flags and status
                shard = self.quality_gates.update_quality_flags(shard, validation_result)

                # Step 5: Save updated shard
                self._save_shard(shard)

                # Update index status
                index = self.index_manager.update_subtopic_status(
                    index=index,
                    topic_key=topic_key,
                    subtopic_key=subtopic_key,
                    new_status=shard.status  # "final" or "needs_review"
                )
                self.index_manager.save_index(index, create_snapshot=True)

                # Step 6: Optionally sync to database
                if auto_sync_to_db and self.db_sync and shard.status == "final":
                    self.db_sync.sync_shard(
                        shard=shard,
                        book_id=book_id,
                        grade=book_metadata.get("grade", 3),
                        subject=book_metadata.get("subject", "Math"),
                        board=book_metadata.get("board", "CBSE")
                    )
                    logger.info(f"Synced {topic_key}/{subtopic_key} to database")

                finalized.append((topic_key, subtopic_key))

                logger.info(
                    f"Finalized {topic_key}/{subtopic_key}: "
                    f"status={shard.status}, quality_score={shard.quality_flags.quality_score}"
                )

            except Exception as e:
                logger.error(
                    f"Failed to finalize {topic_key}/{subtopic_key}: {str(e)}",
                    exc_info=True
                )
                # Continue with next subtopic

        return finalized

    # ==================== Helper Methods ====================

    def _load_page_text(self, book_id: str, page_num: int) -> str:
        """Load page OCR text from S3"""
        page_key = f"books/{book_id}/pages/{page_num:03d}.ocr.txt"

        try:
            page_text = self.s3.get_text(page_key)
            logger.debug(f"Loaded page text from {page_key}: {len(page_text)} chars")
            return page_text
        except Exception as e:
            logger.error(f"Failed to load page text from {page_key}: {str(e)}")
            raise FileNotFoundError(f"Page text not found: {page_key}")

    def _load_or_create_shard(
        self,
        book_id: str,
        topic_key: str,
        topic_title: str,
        subtopic_key: str,
        subtopic_title: str,
        page_facts: PageFacts,
        page_num: int
    ) -> SubtopicShard:
        """Load existing shard or create new one"""
        try:
            # Try to load existing shard
            shard = self._load_shard(book_id, topic_key, subtopic_key)
            logger.debug(f"Loaded existing shard: {topic_key}/{subtopic_key}")
            return shard
        except FileNotFoundError:
            # Create new shard
            shard = self.reducer.create_new_shard(
                book_id=book_id,
                topic_key=topic_key,
                topic_title=topic_title,
                subtopic_key=subtopic_key,
                subtopic_title=subtopic_title,
                page_facts=page_facts,
                page_num=page_num
            )
            logger.info(f"Created new shard: {topic_key}/{subtopic_key}")
            return shard

    def _load_shard(self, book_id: str, topic_key: str, subtopic_key: str) -> SubtopicShard:
        """Load shard from S3"""
        shard_key = (
            f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
            f"{subtopic_key}.latest.json"
        )

        try:
            shard_data = self.s3.get_json(shard_key)
            return SubtopicShard(**shard_data)
        except Exception as e:
            raise FileNotFoundError(f"Shard not found: {shard_key}")

    def _save_shard(self, shard: SubtopicShard) -> None:
        """Save shard to S3"""
        shard_key = (
            f"books/{shard.book_id}/guidelines/topics/{shard.topic_key}/subtopics/"
            f"{shard.subtopic_key}.latest.json"
        )

        try:
            self.s3.put_json(shard_key, shard.model_dump())
            logger.debug(f"Saved shard to {shard_key}: version {shard.version}")
        except Exception as e:
            logger.error(f"Failed to save shard to {shard_key}: {str(e)}")
            raise

    def _save_page_guideline(self, page_guideline: PageGuideline) -> None:
        """Save page guideline to S3"""
        page_key = (
            f"books/{page_guideline.book_id}/pages/{page_guideline.page:03d}."
            f"page_guideline.json"
        )

        try:
            self.s3.put_json(page_key, page_guideline.model_dump())
            logger.debug(f"Saved page guideline to {page_key}")
        except Exception as e:
            logger.error(f"Failed to save page guideline to {page_key}: {str(e)}")
            raise

    def _update_indices(
        self,
        book_id: str,
        topic_key: str,
        topic_title: str,
        subtopic_key: str,
        subtopic_title: str,
        page_num: int,
        confidence: float,
        status: str
    ) -> None:
        """Update index.json and page_index.json"""
        # Update main index
        index = self.index_manager.get_or_create_index(book_id)
        index = self.index_manager.add_or_update_subtopic(
            index=index,
            topic_key=topic_key,
            topic_title=topic_title,
            subtopic_key=subtopic_key,
            subtopic_title=subtopic_title,
            status=status
        )
        self.index_manager.save_index(index, create_snapshot=False)

        # Update page index
        page_index = self.index_manager.get_or_create_page_index(book_id)
        page_index = self.index_manager.add_page_assignment(
            page_index=page_index,
            page_num=page_num,
            topic_key=topic_key,
            subtopic_key=subtopic_key,
            confidence=confidence,
            provisional=False
        )
        self.index_manager.save_page_index(page_index, create_snapshot=False)
