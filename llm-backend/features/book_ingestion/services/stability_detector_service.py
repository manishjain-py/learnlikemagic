"""
Stability Detector Service

Responsibility: Detect when subtopics have stabilized (ready for teaching description).

Single Responsibility Principle:
- Only handles stability detection logic
- Monitors page updates to determine when subtopic is "stable"
- No LLM calls (pure business logic)

Stability Criteria:
- K=3 pages processed without updates to this subtopic
- "Stable" means no new facts added, boundary detector moved to other subtopic
"""

import logging
from typing import Dict, List, Optional

from ..models.guideline_models import GuidelinesIndex, PageIndex, SubtopicShard

logger = logging.getLogger(__name__)


class StabilityDetectorService:
    """
    Detect when subtopics have stabilized and are ready for final processing.

    A subtopic is "stable" when:
    1. It's currently "open"
    2. K consecutive pages have been processed without updating this subtopic
    3. K=3 (configurable)

    Stable subtopics trigger:
    - Teaching description generation
    - Quality gate validation
    - Potential DB sync (if quality passes)
    """

    # Number of pages without updates before marking stable
    STABILITY_THRESHOLD = 3

    def __init__(self, stability_threshold: int = STABILITY_THRESHOLD):
        """
        Initialize stability detector.

        Args:
            stability_threshold: Number of pages without updates before stable (default: 3)
        """
        self.stability_threshold = stability_threshold
        logger.info(f"Initialized StabilityDetector with threshold K={stability_threshold}")

    def detect_stable_subtopics(
        self,
        index: GuidelinesIndex,
        page_index: PageIndex,
        current_page: int
    ) -> List[tuple[str, str]]:
        """
        Detect which subtopics have become stable.

        Args:
            index: Current guidelines index (topic/subtopic registry)
            page_index: Page-to-subtopic mapping
            current_page: Current page being processed

        Returns:
            List of (topic_key, subtopic_key) tuples that are now stable

        Algorithm:
            For each open subtopic:
            1. Find last page that updated this subtopic
            2. If (current_page - last_update_page) >= K: mark stable
        """
        stable_subtopics = []

        # Build reverse mapping: subtopic -> last_updated_page
        subtopic_last_update: Dict[tuple[str, str], int] = {}

        for page_num, page_entry in page_index.pages.items():
            topic_key = page_entry.topic_key
            subtopic_key = page_entry.subtopic_key
            key = (topic_key, subtopic_key)

            # Track the highest page number for each subtopic
            if key not in subtopic_last_update:
                subtopic_last_update[key] = page_num
            else:
                subtopic_last_update[key] = max(subtopic_last_update[key], page_num)

        # Check each open subtopic for stability
        for topic_entry in index.topics:
            for subtopic_entry in topic_entry.subtopics:
                # Only check open subtopics
                if subtopic_entry.status != "open":
                    continue

                topic_key = topic_entry.topic_key
                subtopic_key = subtopic_entry.subtopic_key
                key = (topic_key, subtopic_key)

                # Find last update page
                last_update_page = subtopic_last_update.get(key, 0)

                if last_update_page == 0:
                    # Subtopic exists but never received pages (shouldn't happen)
                    logger.warning(
                        f"Subtopic {topic_key}/{subtopic_key} exists but has no pages"
                    )
                    continue

                # Calculate pages since last update
                pages_since_update = current_page - last_update_page

                if pages_since_update >= self.stability_threshold:
                    logger.info(
                        f"Subtopic {topic_key}/{subtopic_key} is STABLE: "
                        f"last update on page {last_update_page}, "
                        f"{pages_since_update} pages ago (threshold={self.stability_threshold})"
                    )
                    stable_subtopics.append((topic_key, subtopic_key))
                else:
                    logger.debug(
                        f"Subtopic {topic_key}/{subtopic_key} still OPEN: "
                        f"last update on page {last_update_page}, "
                        f"only {pages_since_update} pages ago (need {self.stability_threshold})"
                    )

        return stable_subtopics

    def should_mark_stable(
        self,
        subtopic_key: str,
        topic_key: str,
        current_page: int,
        page_index: PageIndex
    ) -> bool:
        """
        Check if a specific subtopic should be marked stable.

        Args:
            subtopic_key: Subtopic to check
            topic_key: Topic containing the subtopic
            current_page: Current page number
            page_index: Page-to-subtopic mapping

        Returns:
            True if subtopic should be marked stable
        """
        # Find last page that updated this subtopic
        last_update_page = 0

        for page_num, page_entry in page_index.pages.items():
            if (page_entry.topic_key == topic_key and
                page_entry.subtopic_key == subtopic_key):
                last_update_page = max(last_update_page, page_num)

        if last_update_page == 0:
            logger.warning(
                f"Subtopic {topic_key}/{subtopic_key} has no pages in index"
            )
            return False

        pages_since_update = current_page - last_update_page
        should_stabilize = pages_since_update >= self.stability_threshold

        logger.debug(
            f"Stability check for {topic_key}/{subtopic_key}: "
            f"last_update={last_update_page}, current={current_page}, "
            f"gap={pages_since_update}, threshold={self.stability_threshold}, "
            f"should_stabilize={should_stabilize}"
        )

        return should_stabilize

    def mark_as_stable(
        self,
        shard: SubtopicShard,
        reason: str = "stability_threshold_reached"
    ) -> SubtopicShard:
        """
        Mark a shard as stable (immutable - returns new shard).

        Args:
            shard: Current subtopic shard
            reason: Reason for marking stable (for logging/debugging)

        Returns:
            New shard with status="stable"

        Note:
            This function does NOT mutate the input shard.
            It returns a new shard with updated status.
        """
        if shard.status == "stable":
            logger.debug(f"Shard {shard.subtopic_key} already stable, skipping")
            return shard

        # Create new shard with updated status
        from copy import deepcopy
        updated_shard = deepcopy(shard)
        updated_shard.status = "stable"
        updated_shard.version += 1

        logger.info(
            f"Marked {updated_shard.topic_key}/{updated_shard.subtopic_key} as STABLE: "
            f"reason={reason}, version={updated_shard.version}, "
            f"pages={updated_shard.source_page_start}-{updated_shard.source_page_end}"
        )

        return updated_shard

    def get_unstable_subtopics(
        self,
        index: GuidelinesIndex,
        page_index: PageIndex,
        current_page: int
    ) -> List[tuple[str, str, int]]:
        """
        Get all unstable (open) subtopics with their staleness.

        Args:
            index: Current guidelines index
            page_index: Page-to-subtopic mapping
            current_page: Current page number

        Returns:
            List of (topic_key, subtopic_key, pages_since_update) tuples

        Use case:
            Debugging, monitoring, UI display of "active" subtopics
        """
        unstable = []

        # Build reverse mapping
        subtopic_last_update: Dict[tuple[str, str], int] = {}
        for page_num, page_entry in page_index.pages.items():
            key = (page_entry.topic_key, page_entry.subtopic_key)
            subtopic_last_update[key] = max(
                subtopic_last_update.get(key, 0),
                page_num
            )

        # Find all open subtopics
        for topic_entry in index.topics:
            for subtopic_entry in topic_entry.subtopics:
                if subtopic_entry.status == "open":
                    topic_key = topic_entry.topic_key
                    subtopic_key = subtopic_entry.subtopic_key
                    key = (topic_key, subtopic_key)

                    last_update = subtopic_last_update.get(key, current_page)
                    pages_since = current_page - last_update

                    unstable.append((topic_key, subtopic_key, pages_since))

        return unstable
