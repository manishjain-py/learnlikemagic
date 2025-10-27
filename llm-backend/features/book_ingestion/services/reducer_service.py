"""
Reducer Service

Responsibility: Merge page facts into authoritative subtopic shards.

Single Responsibility Principle:
- Only handles shard merging logic
- Implements deterministic, idempotent merge operations
- No LLM calls (pure data transformation)

Key Properties:
- DETERMINISTIC: Same input always produces same output
- IDEMPOTENT: Applying same delta twice has no additional effect
- CONFLICT-FREE: Uses deduplication to prevent duplicates
"""

import logging
from typing import List, Dict, Any
from copy import deepcopy

from ..models.guideline_models import SubtopicShard, PageFacts, Assessment

logger = logging.getLogger(__name__)


class ReducerService:
    """
    Merge page facts into subtopic shards deterministically.

    This service ensures that:
    1. Multiple pages can update the same shard safely
    2. Duplicate facts are automatically deduplicated
    3. Page ranges are tracked correctly
    4. Version numbers increment consistently
    """

    def merge(
        self,
        shard: SubtopicShard,
        page_facts: PageFacts,
        page_num: int
    ) -> SubtopicShard:
        """
        Merge page facts into a subtopic shard.

        Args:
            shard: Current subtopic shard (will not be mutated)
            page_facts: Facts extracted from current page
            page_num: Current page number

        Returns:
            New SubtopicShard with merged facts

        Note:
            This function does NOT mutate the input shard.
            It returns a new shard with updated values.
        """
        # Deep copy to avoid mutation
        updated_shard = deepcopy(shard)

        # Merge objectives (deduplicate case-insensitive)
        updated_shard.objectives = self._merge_objectives(
            updated_shard.objectives,
            page_facts.objectives_add
        )

        # Merge examples (deduplicate by hash)
        updated_shard.examples = self._merge_examples(
            updated_shard.examples,
            page_facts.examples_add
        )

        # Merge misconceptions (deduplicate case-insensitive)
        updated_shard.misconceptions = self._merge_misconceptions(
            updated_shard.misconceptions,
            page_facts.misconceptions_add
        )

        # Merge assessments (allow duplicates at different levels)
        updated_shard.assessments = self._merge_assessments(
            updated_shard.assessments,
            page_facts.assessments_add
        )

        # Update page tracking
        updated_shard = self._update_page_tracking(updated_shard, page_num)

        # Increment version
        updated_shard.version += 1
        updated_shard.last_updated_page = page_num

        logger.debug(
            f"Merged page {page_num} into {updated_shard.subtopic_key}: "
            f"version {updated_shard.version}, "
            f"{len(updated_shard.objectives)} objectives, "
            f"{len(updated_shard.examples)} examples"
        )

        return updated_shard

    def _merge_objectives(
        self,
        existing: List[str],
        new: List[str]
    ) -> List[str]:
        """
        Merge objectives with case-insensitive deduplication.

        Args:
            existing: Current objectives
            new: New objectives to add

        Returns:
            Merged list (preserves order, no duplicates)
        """
        # Build lowercase set for comparison
        existing_lower = {obj.lower() for obj in existing}
        result = existing.copy()

        for obj in new:
            if obj.lower() not in existing_lower:
                result.append(obj)
                existing_lower.add(obj.lower())

        return result

    def _merge_examples(
        self,
        existing: List[str],
        new: List[str]
    ) -> List[str]:
        """
        Merge examples with hash-based deduplication.

        Args:
            existing: Current examples
            new: New examples to add

        Returns:
            Merged list (preserves order, no duplicates)
        """
        # Build hash set for comparison
        existing_hashes = {hash(ex) for ex in existing}
        result = existing.copy()

        for ex in new:
            ex_hash = hash(ex)
            if ex_hash not in existing_hashes:
                result.append(ex)
                existing_hashes.add(ex_hash)

        return result

    def _merge_misconceptions(
        self,
        existing: List[str],
        new: List[str]
    ) -> List[str]:
        """
        Merge misconceptions with case-insensitive deduplication.

        Args:
            existing: Current misconceptions
            new: New misconceptions to add

        Returns:
            Merged list (preserves order, no duplicates)
        """
        # Build lowercase set for comparison
        existing_lower = {m.lower() for m in existing}
        result = existing.copy()

        for m in new:
            if m.lower() not in existing_lower:
                result.append(m)
                existing_lower.add(m.lower())

        return result

    def _merge_assessments(
        self,
        existing: List[Assessment],
        new: List[Assessment]
    ) -> List[Assessment]:
        """
        Merge assessments with hash-based deduplication.

        Note: Unlike other fields, assessments can have duplicates
        at different difficulty levels. We deduplicate exact matches only.

        Args:
            existing: Current assessments
            new: New assessments to add

        Returns:
            Merged list (preserves order, minimal duplicates)
        """
        # Build hash set for comparison (hash based on prompt+answer+level)
        existing_hashes = {
            hash((a.prompt, a.answer, a.level)) for a in existing
        }
        result = existing.copy()

        for assessment in new:
            assessment_hash = hash((
                assessment.prompt,
                assessment.answer,
                assessment.level
            ))
            if assessment_hash not in existing_hashes:
                result.append(assessment)
                existing_hashes.add(assessment_hash)

        return result

    def _update_page_tracking(
        self,
        shard: SubtopicShard,
        page_num: int
    ) -> SubtopicShard:
        """
        Update page range and page list.

        Args:
            shard: Subtopic shard
            page_num: Current page number

        Returns:
            Updated shard with new page tracking
        """
        # Add to pages list if not already present
        if page_num not in shard.source_pages:
            shard.source_pages.append(page_num)
            shard.source_pages.sort()  # Maintain sorted order

        # Update page range
        if page_num < shard.source_page_start:
            shard.source_page_start = page_num
        if page_num > shard.source_page_end:
            shard.source_page_end = page_num

        return shard

    def create_new_shard(
        self,
        book_id: str,
        topic_key: str,
        topic_title: str,
        subtopic_key: str,
        subtopic_title: str,
        page_facts: PageFacts,
        page_num: int
    ) -> SubtopicShard:
        """
        Create a new subtopic shard from initial page facts.

        Args:
            book_id: Book identifier
            topic_key: Slugified topic identifier
            topic_title: Human-readable topic name
            subtopic_key: Slugified subtopic identifier
            subtopic_title: Human-readable subtopic name
            page_facts: Initial facts from first page
            page_num: First page number

        Returns:
            New SubtopicShard
        """
        shard = SubtopicShard(
            book_id=book_id,
            topic_key=topic_key,
            subtopic_key=subtopic_key,
            topic_title=topic_title,
            subtopic_title=subtopic_title,
            status="open",
            source_page_start=page_num,
            source_page_end=page_num,
            source_pages=[page_num],
            objectives=page_facts.objectives_add,
            examples=page_facts.examples_add,
            misconceptions=page_facts.misconceptions_add,
            assessments=page_facts.assessments_add,
            last_updated_page=page_num,
            version=1
        )

        logger.info(
            f"Created new shard: {topic_key}/{subtopic_key} "
            f"starting at page {page_num}"
        )

        return shard
