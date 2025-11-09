"""
Guideline Extraction Orchestrator V2

V2 Simplifications:
- No FactsExtractionService (done in boundary detection)
- No ReducerService (replaced with GuidelineMergeService)
- No TeachingDescriptionGenerator (single guidelines field)
- No QualityGatesService (parked for V2)
- Adds TopicDeduplicationService for end-of-book cleanup
- 5-page stability threshold (vs 3 in V1)
- Book-end finalization

Single Responsibility Principle:
- Only handles orchestration logic (calling V2 services in sequence)
- No LLM calls (delegates to component services)
- No business logic (delegates to component services)

V2 Pipeline Flow (for each page):
1. Load page OCR text
2. Generate minisummary (5-6 lines)
3. Build context pack (5 recent pages + guidelines)
4. Detect boundary + extract guidelines (combined)
5. Create new shard OR merge guidelines (LLM-based)
6. Check stability (5-page threshold)
7. Update indices
8. Save shard and page guideline

Book End Flow:
1. Finalize all open topics
2. Run deduplication pass
3. Merge duplicate shards
4. Sync to database (if enabled)
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

from openai import OpenAI
from sqlalchemy.orm import Session

from ..models.guideline_models import (
    SubtopicShard,
    slugify,
    deslugify,
    GuidelinesIndex
)
from ..utils.s3_client import S3Client

# Import V2 component services
from .minisummary_service import MinisummaryService
from .context_pack_service import ContextPackService
from .boundary_detection_service import BoundaryDetectionService
from .guideline_merge_service import GuidelineMergeService
from .topic_deduplication_service import TopicDeduplicationService
from .topic_name_refinement_service import TopicNameRefinementService
from .index_management_service import IndexManagementService
from .db_sync_service import DBSyncService

logger = logging.getLogger(__name__)


class GuidelineExtractionOrchestrator:
    """
    V2 Orchestrator - Simplified pipeline with LLM-based merging.

    Key changes from V1:
    - Use BoundaryDetectionService (extracts guidelines in same call)
    - Use GuidelineMergeService for CONTINUE (LLM-based)
    - No FactsExtractionService (done in boundary detection)
    - Add TopicDeduplicationService for end-of-book cleanup
    - 5-page stability threshold
    - Book-end finalization
    """

    # V2 Configuration
    STABILITY_THRESHOLD = 5  # V2: 5 pages without update (vs 3 in V1)

    def __init__(
        self,
        s3_client: S3Client,
        openai_client: Optional[OpenAI] = None,
        db_session: Optional[Session] = None
    ):
        """
        Initialize V2 orchestrator with component services.

        Args:
            s3_client: S3 client for reading/writing files
            openai_client: Optional OpenAI client (if None, creates new one)
            db_session: Optional database session (if None, DB sync disabled)
        """
        self.s3 = s3_client
        self.openai_client = openai_client or OpenAI()
        self.db_session = db_session

        # Initialize V2 component services
        self.minisummary = MinisummaryService(self.openai_client)
        self.context_pack = ContextPackService(self.s3)
        self.boundary_detector = BoundaryDetectionService(self.openai_client)
        self.merge_service = GuidelineMergeService(self.openai_client)
        self.dedup_service = TopicDeduplicationService(self.openai_client)
        self.name_refinement = TopicNameRefinementService(self.openai_client)
        self.index_manager = IndexManagementService(self.s3)
        self.db_sync = DBSyncService(self.db_session) if self.db_session else None

        logger.info("Initialized GuidelineExtractionOrchestrator with all V2 services")

    def extract_guidelines_for_book(
        self,
        book_id: str,
        book_metadata: Dict[str, Any],
        start_page: int = 1,
        end_page: Optional[int] = None,
        auto_sync_to_db: bool = False
    ) -> Dict[str, Any]:
        """
        Extract guidelines for an entire book (V2 pipeline).

        Args:
            book_id: Book identifier
            book_metadata: Book metadata (grade, subject, board, total_pages)
            start_page: Starting page number (default: 1)
            end_page: Ending page number (default: total_pages)
            auto_sync_to_db: If True, automatically sync final shards to database

        Returns:
            Dict with extraction results and statistics

        V2 Pipeline:
            For each page (start_page to end_page):
            1. Process page (extract guidelines, merge, update indices)
            2. Check for stable subtopics (5-page threshold)

            After all pages:
            1. Finalize all open topics
            2. Run deduplication
            3. Merge duplicates
            4. Sync to database (if enabled)
        """
        total_pages = book_metadata.get("total_pages", 100)
        end_page = end_page or total_pages

        logger.info(
            f"Starting V2 guideline extraction for book {book_id}: "
            f"pages {start_page}-{end_page}, auto_sync={auto_sync_to_db}"
        )

        stats = {
            "pages_processed": 0,
            "subtopics_created": 0,
            "subtopics_merged": 0,
            "subtopics_finalized": 0,
            "duplicates_merged": 0,
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

                    if page_result.get("is_new_topic"):
                        stats["subtopics_created"] += 1
                    else:
                        stats["subtopics_merged"] += 1

                    # Check for stable subtopics (5-page threshold)
                    stable_count = self._check_and_mark_stable_subtopics(
                        book_id=book_id,
                        current_page=page_num
                    )

                    logger.info(
                        f"Page {page_num} complete: "
                        f"{'NEW' if page_result.get('is_new_topic') else 'CONTINUE'} "
                        f"→ {page_result.get('topic_key')}/{page_result.get('subtopic_key')}, "
                        f"{stable_count} marked stable"
                    )

                except Exception as e:
                    error_msg = f"Error processing page {page_num}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    stats["errors"].append(error_msg)
                    # Continue processing next page

            # Book-end processing
            logger.info(f"Book processing complete. Starting finalization...")

            finalization_result = self.finalize_book(
                book_id=book_id,
                book_metadata=book_metadata,
                auto_sync_to_db=auto_sync_to_db
            )

            stats["subtopics_finalized"] = finalization_result.get("subtopics_finalized", 0)
            stats["duplicates_merged"] = finalization_result.get("duplicates_merged", 0)

            logger.info(
                f"V2 guideline extraction complete for book {book_id}: "
                f"{stats['pages_processed']} pages, "
                f"{stats['subtopics_created']} created, "
                f"{stats['subtopics_merged']} merged, "
                f"{stats['duplicates_merged']} duplicates merged, "
                f"{len(stats['errors'])} errors"
            )

            return stats

        except Exception as e:
            logger.error(f"V2 guideline extraction failed for book {book_id}: {str(e)}", exc_info=True)
            raise

    def process_page(
        self,
        book_id: str,
        page_num: int,
        book_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single page through the V2 pipeline.

        Args:
            book_id: Book identifier
            page_num: Page number
            book_metadata: Book metadata

        Returns:
            Dict with page processing results

        V2 Steps:
        1. Load page OCR text
        2. Generate minisummary (5-6 lines)
        3. Build context pack (5 recent pages + guidelines)
        4. Boundary detection + guideline extraction (combined)
        5. Create new shard OR merge guidelines (LLM)
        6. Save updated shard to S3
        7. Update indices
        8. Save page guideline
        """
        logger.debug(f"Processing page {page_num} (V2 pipeline)...")

        # Step 1: Load page OCR text
        page_text = self._load_page_text(book_id, page_num)

        # Step 2: Generate minisummary (5-6 lines)
        minisummary = self.minisummary.generate(page_text)

        # Step 3: Build context pack (5 recent + guidelines)
        context_pack = self.context_pack.build(
            book_id=book_id,
            current_page=page_num,
            book_metadata=book_metadata
        )

        # Step 4: Boundary detection + guideline extraction (V2)
        is_new, topic_key, topic_title, subtopic_key, subtopic_title, page_guidelines = \
            self.boundary_detector.detect(
                context_pack=context_pack,
                page_text=page_text  # V2: Full text, not summary
            )

        # Step 5: Create or merge shard
        if is_new:
            # Create new shard
            shard = SubtopicShard(
                topic_key=topic_key,
                topic_title=topic_title,
                subtopic_key=subtopic_key,
                subtopic_title=subtopic_title,
                source_page_start=page_num,
                source_page_end=page_num,
                status="open",
                guidelines=page_guidelines,  # V2: Single field
                version=1
            )
            logger.info(f"Created NEW shard: {topic_key}/{subtopic_key}")
        else:
            # Load existing shard and merge (or create if doesn't exist yet)
            try:
                shard = self._load_shard_v2(book_id, topic_key, subtopic_key)

                # V2: LLM-based merge
                merged_guidelines = self.merge_service.merge(
                    existing_guidelines=shard.guidelines,
                    new_page_guidelines=page_guidelines,
                    topic_title=topic_title,
                    subtopic_title=subtopic_title,
                    grade=book_metadata.get("grade", 3),
                    subject=book_metadata.get("subject", "Math")
                )

                shard.guidelines = merged_guidelines
                shard.source_page_end = page_num
                shard.version += 1
                shard.updated_at = datetime.utcnow().isoformat()

                logger.info(f"Merged into existing shard: {topic_key}/{subtopic_key}")
            except Exception as e:
                # Shard doesn't exist yet - treat as new
                logger.warning(f"Shard not found, creating new: {topic_key}/{subtopic_key}")
                shard = SubtopicShard(
                    topic_key=topic_key,
                    topic_title=topic_title,
                    subtopic_key=subtopic_key,
                    subtopic_title=subtopic_title,
                    source_page_start=page_num,
                    source_page_end=page_num,
                    status="open",
                    guidelines=page_guidelines,
                    version=1
                )

        # Step 6: Save shard to S3
        self._save_shard_v2(book_id, shard)

        # Step 7: Update indices
        self._update_indices(
            book_id=book_id,
            topic_key=topic_key,
            topic_title=topic_title,
            subtopic_key=subtopic_key,
            subtopic_title=subtopic_title,
            page_num=page_num,
            status=shard.status,
            source_page_start=shard.source_page_start,
            source_page_end=shard.source_page_end
        )

        # Step 8: Save page guideline (minisummary)
        self._save_page_guideline_v2(
            book_id=book_id,
            page_num=page_num,
            minisummary=minisummary
        )

        logger.debug(
            f"Page {page_num} processed (V2): {topic_key}/{subtopic_key}, "
            f"is_new={is_new}"
        )

        return {
            "page_num": page_num,
            "topic_key": topic_key,
            "subtopic_key": subtopic_key,
            "is_new_topic": is_new,
            "guidelines_length": len(page_guidelines)
        }

    def finalize_book(
        self,
        book_id: str,
        book_metadata: Dict[str, Any],
        auto_sync_to_db: bool = False
    ) -> Dict[str, Any]:
        """
        End-of-book processing (V2).

        Steps:
        1. Finalize all open topics/subtopics
        2. Run deduplication pass
        3. Merge duplicate shards
        4. Sync to database (if enabled)

        Args:
            book_id: Book identifier
            book_metadata: Book metadata
            auto_sync_to_db: If True, sync to database

        Returns:
            Dict with finalization results
        """
        logger.info(f"Finalizing book {book_id} (V2 pipeline)")

        # Step 1: Finalize all open shards
        index = self._load_index(book_id)
        finalized_count = 0

        for topic in index.topics:
            for subtopic in topic.subtopics:
                if subtopic.status in ["open", "stable"]:
                    try:
                        shard = self._load_shard_v2(book_id, topic.topic_key, subtopic.subtopic_key)
                        shard.status = "final"
                        shard.updated_at = datetime.utcnow().isoformat()
                        self._save_shard_v2(book_id, shard)
                        finalized_count += 1
                    except Exception as e:
                        logger.warning(f"Shard not found during finalization, skipping: {topic.topic_key}/{subtopic.subtopic_key} - {str(e)}")
                        continue

        logger.info(f"Finalized {finalized_count} open/stable shards")

        # Step 2: Refine topic/subtopic names based on complete guidelines
        logger.info(f"Refining topic/subtopic names for {book_id}")
        refined_count = 0
        for topic in index.topics:
            for subtopic in topic.subtopics:
                try:
                    shard = self._load_shard_v2(book_id, topic.topic_key, subtopic.subtopic_key)

                    # Get refined names from LLM
                    refinement = self.name_refinement.refine_names(shard, book_metadata)

                    # Track if names changed
                    names_changed = (
                        refinement.topic_title != shard.topic_title or
                        refinement.topic_key != shard.topic_key or
                        refinement.subtopic_title != shard.subtopic_title or
                        refinement.subtopic_key != shard.subtopic_key
                    )

                    if names_changed:
                        logger.info(
                            f"Refining: {shard.topic_key}/{shard.subtopic_key} → "
                            f"{refinement.topic_key}/{refinement.subtopic_key}"
                        )

                        # Update shard with new names
                        old_topic_key = shard.topic_key
                        old_subtopic_key = shard.subtopic_key

                        shard.topic_title = refinement.topic_title
                        shard.topic_key = refinement.topic_key
                        shard.subtopic_title = refinement.subtopic_title
                        shard.subtopic_key = refinement.subtopic_key
                        shard.updated_at = datetime.utcnow().isoformat()

                        # Save shard with NEW key (and delete old if key changed)
                        self._save_shard_v2(book_id, shard)
                        if old_topic_key != shard.topic_key or old_subtopic_key != shard.subtopic_key:
                            self._delete_shard_v2(book_id, old_topic_key, old_subtopic_key)

                        # Update index with new names
                        self._update_index_names(
                            book_id, old_topic_key, old_subtopic_key,
                            refinement.topic_key, refinement.subtopic_key,
                            refinement.topic_title, refinement.subtopic_title
                        )

                        refined_count += 1

                except Exception as e:
                    logger.warning(f"Failed to refine names for {topic.topic_key}/{subtopic.subtopic_key}: {str(e)}")
                    continue

        logger.info(f"Refined {refined_count} topic/subtopic names")

        # Step 3: Load all shards for deduplication
        all_shards = self._load_all_shards_v2(book_id)

        # Step 3: Identify duplicates
        duplicates = self.dedup_service.deduplicate(
            all_shards=all_shards,
            grade=book_metadata.get("grade", 3),
            subject=book_metadata.get("subject", "Math")
        )

        # Step 4: Merge duplicate shards
        merged_count = 0
        for topic1, subtopic1, topic2, subtopic2 in duplicates:
            try:
                self._merge_duplicate_shards(
                    book_id=book_id,
                    topic1=topic1,
                    subtopic1=subtopic1,
                    topic2=topic2,
                    subtopic2=subtopic2,
                    grade=book_metadata.get("grade", 3),
                    subject=book_metadata.get("subject", "Math")
                )
                merged_count += 1
            except Exception as e:
                logger.error(f"Failed to merge duplicates {topic1}/{subtopic1} + {topic2}/{subtopic2}: {e}")

        logger.info(f"Book finalized: {merged_count} duplicate pairs merged")

        # Step 5: Sync to database (if enabled)
        logger.info(f"DEBUG: auto_sync_to_db={auto_sync_to_db}, self.db_sync={self.db_sync}")
        if auto_sync_to_db and self.db_sync:
            logger.info("Auto-syncing to database...")
            try:
                sync_stats = self.db_sync.sync_book_guidelines(
                    book_id=book_id,
                    s3_client=self.s3,
                    book_metadata=book_metadata
                )
                logger.info(
                    f"Database sync complete: {sync_stats['synced_count']} guidelines synced "
                    f"({sync_stats['created_count']} created, {sync_stats['updated_count']} updated)"
                )
            except Exception as e:
                logger.error(f"Database sync failed: {str(e)}")

        return {
            "status": "finalized",
            "subtopics_finalized": finalized_count,
            "subtopics_renamed": refined_count,
            "duplicates_merged": merged_count,
            "total_topics": len(index.topics)
        }

    def _check_and_mark_stable_subtopics(
        self,
        book_id: str,
        current_page: int
    ) -> int:
        """
        Check for stable subtopics (V2: 5-page threshold).

        Args:
            book_id: Book identifier
            current_page: Current page number

        Returns:
            Number of subtopics marked as stable
        """
        index = self._load_index(book_id)
        stable_count = 0

        for topic in index.topics:
            for subtopic in topic.subtopics:
                if subtopic.status == "open":
                    shard = self._load_shard_v2(book_id, topic.topic_key, subtopic.subtopic_key)

                    # V2: 5-page gap threshold
                    if current_page - shard.source_page_end >= self.STABILITY_THRESHOLD:
                        shard.status = "stable"
                        shard.updated_at = datetime.utcnow().isoformat()
                        self._save_shard_v2(book_id, shard)
                        stable_count += 1
                        logger.info(
                            f"Marked stable: {topic.topic_key}/{subtopic.subtopic_key} "
                            f"(last page: {shard.source_page_end}, current: {current_page})"
                        )

        return stable_count

    def _merge_duplicate_shards(
        self,
        book_id: str,
        topic1: str,
        subtopic1: str,
        topic2: str,
        subtopic2: str,
        grade: int,
        subject: str
    ):
        """Merge two duplicate shards"""
        shard1 = self._load_shard_v2(book_id, topic1, subtopic1)
        shard2 = self._load_shard_v2(book_id, topic2, subtopic2)

        # Merge guidelines using LLM
        merged_guidelines = self.merge_service.merge(
            existing_guidelines=shard1.guidelines,
            new_page_guidelines=shard2.guidelines,
            topic_title=shard1.topic_title,
            subtopic_title=shard1.subtopic_title,
            grade=grade,
            subject=subject
        )

        # Keep shard1, update it
        shard1.guidelines = merged_guidelines
        shard1.source_page_start = min(shard1.source_page_start, shard2.source_page_start)
        shard1.source_page_end = max(shard1.source_page_end, shard2.source_page_end)
        shard1.version += 1
        shard1.updated_at = datetime.utcnow().isoformat()

        # Save merged shard
        self._save_shard_v2(book_id, shard1)

        # Delete shard2
        self._delete_shard_v2(book_id, topic2, subtopic2)

        # Update index to remove shard2
        self._remove_from_index(book_id, topic2, subtopic2)

        logger.info(f"Merged {topic1}/{subtopic1} ← {topic2}/{subtopic2}")

    # ========================================================================
    # HELPER METHODS - S3 I/O
    # ========================================================================

    def _load_page_text(self, book_id: str, page_num: int) -> str:
        """Load OCR text for a page"""
        # Try OCR text file first
        page_key = f"books/{book_id}/pages/{page_num:03d}.ocr.txt"
        try:
            text_bytes = self.s3.download_bytes(page_key)
            return text_bytes.decode('utf-8')
        except Exception:
            # Fallback: try .txt extension
            page_key = f"books/{book_id}/{page_num}.txt"
            try:
                text_bytes = self.s3.download_bytes(page_key)
                return text_bytes.decode('utf-8')
            except Exception as e:
                logger.error(f"Failed to load page text from {page_key}: {str(e)}")
                raise

    def _load_shard_v2(self, book_id: str, topic_key: str, subtopic_key: str) -> SubtopicShard:
        """Load a V2 subtopic shard from S3"""
        shard_key = (
            f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
            f"{subtopic_key}.latest.json"
        )
        try:
            shard_data = self.s3.download_json(shard_key)
            return SubtopicShard(**shard_data)
        except Exception as e:
            logger.error(f"Failed to load V2 shard from {shard_key}: {str(e)}")
            raise

    def _save_shard_v2(self, book_id: str, shard: SubtopicShard):
        """Save a V2 subtopic shard to S3"""
        shard_key = (
            f"books/{book_id}/guidelines/topics/{shard.topic_key}/subtopics/"
            f"{shard.subtopic_key}.latest.json"
        )
        try:
            self.s3.upload_json(shard.model_dump(), shard_key)
            logger.debug(f"Saved V2 shard: {shard_key}")
        except Exception as e:
            logger.error(f"Failed to save V2 shard to {shard_key}: {str(e)}")
            raise

    def _delete_shard_v2(self, book_id: str, topic_key: str, subtopic_key: str):
        """Delete a V2 subtopic shard from S3"""
        shard_key = (
            f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
            f"{subtopic_key}.latest.json"
        )
        try:
            self.s3.delete_file(shard_key)
            logger.debug(f"Deleted V2 shard: {shard_key}")
        except Exception as e:
            logger.warning(f"Failed to delete V2 shard {shard_key}: {str(e)}")

    def _load_all_shards_v2(self, book_id: str) -> List[SubtopicShard]:
        """Load all V2 shards for a book"""
        index = self._load_index(book_id)
        all_shards = []

        for topic in index.topics:
            for subtopic in topic.subtopics:
                try:
                    shard = self._load_shard_v2(book_id, topic.topic_key, subtopic.subtopic_key)
                    all_shards.append(shard)
                except Exception as e:
                    logger.warning(f"Failed to load shard {topic.topic_key}/{subtopic.subtopic_key}: {e}")

        return all_shards

    def _save_page_guideline_v2(self, book_id: str, page_num: int, minisummary: str):
        """Save page guideline (minisummary) for context building"""
        page_key = f"books/{book_id}/pages/{page_num:03d}.page_guideline.json"
        page_data = {
            "page": page_num,
            "summary": minisummary,
            "version": "v2"
        }
        try:
            self.s3.upload_json(page_data, page_key)
        except Exception as e:
            logger.error(f"Failed to save page guideline to {page_key}: {str(e)}")
            raise

    def _load_index(self, book_id: str) -> GuidelinesIndex:
        """Load guidelines index from S3"""
        index_key = f"books/{book_id}/guidelines/index.json"
        try:
            index_data = self.s3.download_json(index_key)
            return GuidelinesIndex(**index_data)
        except Exception as e:
            logger.warning(f"No index found at {index_key}, creating new one")
            return GuidelinesIndex(book_id=book_id, topics=[])

    def _update_indices(
        self,
        book_id: str,
        topic_key: str,
        topic_title: str,
        subtopic_key: str,
        subtopic_title: str,
        page_num: int,
        status: str,
        source_page_start: int,
        source_page_end: int
    ):
        """Update guidelines index and page index"""
        # Calculate page range
        page_range = f"{source_page_start}-{source_page_end}"

        # Update main index
        index = self.index_manager.get_or_create_index(book_id)
        index = self.index_manager.add_or_update_subtopic(
            index=index,
            topic_key=topic_key,
            topic_title=topic_title,
            subtopic_key=subtopic_key,
            subtopic_title=subtopic_title,
            page_range=page_range,
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
            confidence=0.9,  # V2: using fixed high confidence
            provisional=False
        )
        self.index_manager.save_page_index(page_index, create_snapshot=False)

    def _remove_from_index(self, book_id: str, topic_key: str, subtopic_key: str):
        """Remove subtopic from index (after merging duplicates)"""
        try:
            index = self._load_index(book_id)

            for topic in index.topics:
                if topic.topic_key == topic_key:
                    topic.subtopics = [s for s in topic.subtopics if s.subtopic_key != subtopic_key]
                    # Remove topic if no subtopics left
                    if not topic.subtopics:
                        index.topics = [t for t in index.topics if t.topic_key != topic_key]
                    break

            # Save updated index (use mode='json' to serialize datetime)
            index_key = f"books/{book_id}/guidelines/index.json"
            self.s3.upload_json(index.model_dump(mode='json'), index_key)

        except Exception as e:
            logger.error(f"Failed to remove {topic_key}/{subtopic_key} from index: {e}")

    def _update_index_names(
        self,
        book_id: str,
        old_topic_key: str,
        old_subtopic_key: str,
        new_topic_key: str,
        new_subtopic_key: str,
        new_topic_title: str,
        new_subtopic_title: str
    ):
        """Update topic/subtopic names in the index after refinement"""
        try:
            index = self._load_index(book_id)

            # Find and update the subtopic entry
            for topic in index.topics:
                if topic.topic_key == old_topic_key:
                    # Update topic name if it changed
                    if old_topic_key != new_topic_key:
                        topic.topic_key = new_topic_key
                        topic.topic_title = new_topic_title

                    # Update subtopic entry
                    for subtopic in topic.subtopics:
                        if subtopic.subtopic_key == old_subtopic_key:
                            subtopic.subtopic_key = new_subtopic_key
                            subtopic.subtopic_title = new_subtopic_title
                            break
                    break

            # Save updated index (use mode='json' to serialize datetime)
            index_key = f"books/{book_id}/guidelines/index.json"
            self.s3.upload_json(index.model_dump(mode='json'), index_key)
            logger.debug(f"Updated index: {old_topic_key}/{old_subtopic_key} → {new_topic_key}/{new_subtopic_key}")

        except Exception as e:
            logger.error(f"Failed to update index names: {e}")
