"""
Context Pack Builder Service

Responsibility: Build compact context summaries for LLM calls.

Single Responsibility Principle:
- Only handles context pack construction
- Reads from S3 (via injected client)
- Builds ContextPack model from current state

This service solves the token explosion problem:
- Without Context Pack: 24,500 tokens (all previous pages)
- With Context Pack: ~300 tokens (98% reduction)
"""

import logging
import json
from typing import Dict, Any, List, Union

from ..models.guideline_models import (
    ContextPack,
    OpenTopicInfo,
    OpenSubtopicInfo,
    RecentPageSummary,
    ToCHints,
    GuidelinesIndex,
    SubtopicShard,
    # V2 models
    OpenTopicInfo,
    OpenSubtopicInfo,
    SubtopicShard
)
from ..utils.s3_client import S3Client

logger = logging.getLogger(__name__)


class ContextPackService:
    """
    Build compact context packs from current guideline state.

    V1 Context Pack contains:
    - Open subtopics with evidence summaries
    - Recent page summaries (last 2 pages)
    - ToC hints (simplified)

    V2 Context Pack contains:
    - Open subtopics with FULL guidelines text
    - Recent page summaries (last 5 pages)
    - ToC hints (simplified)
    """

    def __init__(self, s3_client: S3Client):
        """
        Initialize context pack service.

        Args:
            s3_client: S3 client for reading guideline state
        """
        self.s3 = s3_client
        # Use 5 recent pages for context
        self.num_recent_pages = 5

    def build(
        self,
        book_id: str,
        current_page: int,
        book_metadata: Dict[str, Any]
    ) -> ContextPack:
        """
        Build context pack for the current page.

        Args:
            book_id: Book identifier
            current_page: Current page number being processed
            book_metadata: Book metadata (grade, subject, board, etc.)

        Returns:
            ContextPack model ready for LLM

        Raises:
            FileNotFoundError: If index.json not found (first page case)
        """
        try:
            # Load current index
            index = self._load_index(book_id)

            # Find open subtopics
            open_topics = self._extract_open_topics(book_id, index)

            # Get recent page summaries (2 for V1, 5 for V2)
            recent_summaries = self._get_recent_summaries(
                book_id, current_page, num_recent=self.num_recent_pages
            )

            # Build ToC hints (simplified for MVP v1)
            toc_hints = self._build_toc_hints(index)

            context_pack = ContextPack(
                book_id=book_id,
                current_page=current_page,
                book_metadata=book_metadata,
                open_topics=open_topics,
                recent_page_summaries=recent_summaries,
                toc_hints=toc_hints
            )

            logger.debug(
                f"Built context pack for page {current_page}: "
                f"{len(open_topics)} open topics, "
                f"{len(recent_summaries)} recent summaries"
            )

            return context_pack

        except FileNotFoundError:
            # First page case - no index yet
            logger.info(f"No index found for book {book_id}, returning empty context pack")
            return ContextPack(
                book_id=book_id,
                current_page=current_page,
                book_metadata=book_metadata,
                open_topics=[],
                recent_page_summaries=[],
                toc_hints=ToCHints()
            )

    def _load_index(self, book_id: str) -> GuidelinesIndex:
        """Load guidelines index from S3"""
        index_key = f"books/{book_id}/guidelines/index.json"

        try:
            index_data = self.s3.download_json(index_key)
            return GuidelinesIndex(**index_data)
        except Exception as e:
            logger.error(f"Failed to load index from {index_key}: {str(e)}")
            raise FileNotFoundError(f"Index not found: {index_key}")

    def _extract_open_topics(
        self,
        book_id: str,
        index: GuidelinesIndex
    ) -> List[Union[OpenTopicInfo, OpenTopicInfo]]:
        """
        Extract information about open topics and their subtopics.

        V1: Returns OpenTopicInfo with evidence summaries
        V2: Returns OpenTopicInfo with full guidelines text

        Args:
            book_id: Book identifier
            index: Current guidelines index

        Returns:
            List of open topic information (V1 or V2 format)
        """
        open_topics = []

        for topic_entry in index.topics:
            open_subtopics = []

            # Find all open or stable subtopics for this topic
            for subtopic_entry in topic_entry.subtopics:
                if subtopic_entry.status in ["open", "stable"]:
                    # Load shard to get details
                    try:
                        shard = self._load_shard(
                            book_id,
                            topic_entry.topic_key,
                            subtopic_entry.subtopic_key
                        )

                        if True:  # simplified
                            # V2: Include full guidelines text
                            # Try to load as V2 shard first, fallback to V1
                            guidelines_text = getattr(shard, 'guidelines', '')
                            if not guidelines_text:
                                # Fallback: construct from V1 fields
                                guidelines_text = self._construct_guidelines_from_v1(shard)

                            open_subtopics.append(
                                OpenSubtopicInfo(
                                    subtopic_key=shard.subtopic_key,
                                    subtopic_title=shard.subtopic_title,
                                    page_start=shard.source_page_start,
                                    page_end=shard.source_page_end,
                                    guidelines=guidelines_text
                                )
                            )
                        else:
                            # V1: Use evidence summary
                            open_subtopics.append(
                                OpenSubtopicInfo(
                                    subtopic_key=shard.subtopic_key,
                                    subtopic_title=shard.subtopic_title,
                                    evidence_summary=self._generate_evidence_summary(shard),
                                    objectives_count=len(getattr(shard, 'objectives', [])),
                                    examples_count=len(getattr(shard, 'examples', []))
                                )
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to load shard for {subtopic_entry.subtopic_key}: {str(e)}"
                        )
                        continue

            # Only include topics with open subtopics
            if open_subtopics:
                if True:  # simplified
                    open_topics.append(
                        OpenTopicInfo(
                            topic_key=topic_entry.topic_key,
                            topic_title=topic_entry.topic_title,
                            open_subtopics=open_subtopics
                        )
                    )
                else:
                    open_topics.append(
                        OpenTopicInfo(
                            topic_key=topic_entry.topic_key,
                            topic_title=topic_entry.topic_title,
                            open_subtopics=open_subtopics
                        )
                    )

        return open_topics

    def _load_shard(
        self,
        book_id: str,
        topic_key: str,
        subtopic_key: str
    ) -> Union[SubtopicShard, SubtopicShard]:
        """Load a subtopic shard from S3"""
        # Use V2 path if version is v2
        if True:  # simplified
            shard_key = (
                f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
                f"{subtopic_key}.latest.json"
            )
        else:
            shard_key = (
                f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
                f"{subtopic_key}.latest.json"
            )

        try:
            shard_data = self.s3.download_json(shard_key)

            # Load as appropriate model based on version
            if True:  # simplified
                return SubtopicShard(**shard_data)
            else:
                return SubtopicShard(**shard_data)
        except Exception as e:
            logger.error(f"Failed to load shard from {shard_key}: {str(e)}")
            raise

    def _generate_evidence_summary(self, shard: SubtopicShard) -> str:
        """
        Generate a rule-based evidence summary (MVP v1 approach).

        Args:
            shard: Subtopic shard

        Returns:
            Brief evidence summary string

        Example:
            "Pages 2-6: 3 objectives, 5 examples, 2 misconceptions"
        """
        objectives = getattr(shard, 'objectives', [])
        examples = getattr(shard, 'examples', [])
        return (
            f"Pages {shard.source_page_start}-{shard.source_page_end}: "
            f"{len(objectives)} objectives, "
            f"{len(examples)} examples"
        )

    def _construct_guidelines_from_v1(self, shard: SubtopicShard) -> str:
        """
        Construct guidelines text from V1 structured fields (fallback).

        Used when loading V1 shards in V2 mode.

        Args:
            shard: V1 subtopic shard

        Returns:
            Guidelines text constructed from V1 fields
        """
        lines = []

        # Objectives
        objectives = getattr(shard, 'objectives', [])
        if objectives:
            lines.append("Learning Objectives:")
            for obj in objectives:
                lines.append(f"- {obj}")
            lines.append("")

        # Examples
        examples = getattr(shard, 'examples', [])
        if examples:
            lines.append("Examples:")
            for ex in examples:
                lines.append(f"- {ex}")
            lines.append("")

        # Misconceptions
        misconceptions = getattr(shard, 'misconceptions', [])
        if misconceptions:
            lines.append("Common Misconceptions:")
            for misc in misconceptions:
                lines.append(f"- {misc}")
            lines.append("")

        # Teaching description
        teaching_desc = getattr(shard, 'teaching_description', None)
        if teaching_desc:
            lines.append("Teaching Approach:")
            lines.append(teaching_desc)
            lines.append("")

        # Assessments
        assessments = getattr(shard, 'assessments', [])
        if assessments:
            lines.append("Assessment Questions:")
            for assessment in assessments:
                lines.append(f"- [{assessment.level}] {assessment.prompt}")
            lines.append("")

        return "\n".join(lines).strip() or "No guidelines available"

    def _get_recent_summaries(
        self,
        book_id: str,
        current_page: int,
        num_recent: int = 2
    ) -> List[RecentPageSummary]:
        """
        Get summaries of recent pages.

        Args:
            book_id: Book identifier
            current_page: Current page number
            num_recent: Number of recent pages to include (default: 2)

        Returns:
            List of recent page summaries
        """
        recent_summaries = []

        # Get last num_recent pages (but not before page 1)
        start_page = max(1, current_page - num_recent)

        for page_num in range(start_page, current_page):
            try:
                # Load page guideline
                page_key = f"books/{book_id}/pages/{page_num:03d}.page_guideline.json"
                page_data = self.s3.download_json(page_key)

                recent_summaries.append(
                    RecentPageSummary(
                        page=page_num,
                        summary=page_data.get("summary", "")
                    )
                )
            except Exception as e:
                logger.warning(
                    f"Failed to load page guideline for page {page_num}: {str(e)}"
                )
                continue

        return recent_summaries

    def _build_toc_hints(self, index: GuidelinesIndex) -> ToCHints:
        """
        Build table of contents hints (simplified for MVP v1).

        Args:
            index: Current guidelines index

        Returns:
            ToC hints

        Note:
            MVP v1 uses simple heuristics. Future versions can use
            LLM-based ToC extraction.
        """
        # Simplified: Use last topic as current chapter
        current_chapter = None
        if index.topics:
            current_chapter = index.topics[-1].topic_title

        # No next section prediction in MVP v1
        return ToCHints(
            current_chapter=current_chapter,
            next_section_candidate=None
        )
