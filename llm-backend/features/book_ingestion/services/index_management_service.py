"""
Index Management Service

Responsibility: Maintain guidelines index and page index files.

Single Responsibility Principle:
- Only handles index CRUD operations
- Maintains index.json (topics/subtopics registry)
- Maintains page_index.json (page → subtopic mapping)
- Handles snapshot versioning

Indices Managed:
1. index.json: Registry of all topics/subtopics with metadata
2. page_index.json: Mapping from page numbers to assigned subtopics
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..models.guideline_models import (
    GuidelinesIndex,
    TopicIndexEntry,
    SubtopicIndexEntry,
    PageIndex,
    PageAssignment
)
from ..utils.s3_client import S3Client

logger = logging.getLogger(__name__)


class IndexManagementService:
    """
    Manage guideline indices (index.json, page_index.json).

    These indices provide:
    - Fast lookup of all topics/subtopics
    - Status tracking (open, stable, final)
    - Page-to-subtopic mapping
    - Snapshot versioning for rollback
    """

    def __init__(self, s3_client: S3Client):
        """
        Initialize index management service.

        Args:
            s3_client: S3 client for reading/writing indices
        """
        self.s3 = s3_client

    # ==================== Index.json Operations ====================

    def get_or_create_index(self, book_id: str) -> GuidelinesIndex:
        """
        Get existing index or create new one.

        Args:
            book_id: Book identifier

        Returns:
            GuidelinesIndex (existing or newly created)
        """
        try:
            return self.load_index(book_id)
        except FileNotFoundError:
            logger.info(f"No index found for book {book_id}, creating new one")
            return GuidelinesIndex(
                book_id=book_id,
                version=1,
                last_updated=datetime.utcnow(),
                topics=[]
            )

    def load_index(self, book_id: str) -> GuidelinesIndex:
        """
        Load index.json from S3.

        Args:
            book_id: Book identifier

        Returns:
            GuidelinesIndex

        Raises:
            FileNotFoundError: If index doesn't exist
        """
        index_key = f"books/{book_id}/guidelines/index.json"

        try:
            index_data = self.s3.download_json(index_key)
            index = GuidelinesIndex(**index_data)
            logger.debug(f"Loaded index for book {book_id}: version {index.version}")
            return index
        except Exception as e:
            logger.error(f"Failed to load index from {index_key}: {str(e)}")
            raise FileNotFoundError(f"Index not found: {index_key}")

    def save_index(
        self,
        index: GuidelinesIndex,
        create_snapshot: bool = True
    ) -> None:
        """
        Save index.json to S3 (with optional snapshot).

        Args:
            index: Index to save
            create_snapshot: If True, create versioned snapshot before overwriting

        Side effects:
            - Writes to books/{book_id}/guidelines/index.json
            - Optionally writes to books/{book_id}/guidelines/snapshots/index.v{N}.json
        """
        book_id = index.book_id
        index_key = f"books/{book_id}/guidelines/index.json"

        # Create snapshot of old version (if exists and requested)
        if create_snapshot:
            try:
                old_index = self.load_index(book_id)
                snapshot_key = (
                    f"books/{book_id}/guidelines/snapshots/"
                    f"index.v{old_index.version}.json"
                )
                self.s3.upload_json(data=old_index.model_dump(mode='json'), s3_key=snapshot_key)
                logger.info(f"Created index snapshot: {snapshot_key}")
            except FileNotFoundError:
                # First save - no snapshot needed
                pass
            except Exception as e:
                logger.warning(f"Failed to create index snapshot: {str(e)}")

        # Update timestamp and save
        index.last_updated = datetime.utcnow()

        try:
            import time
            import json
            start_time = time.time()

            # Use mode='json' to properly serialize datetime objects
            self.s3.upload_json(data=index.model_dump(mode='json'), s3_key=index_key)
            
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "INDEX_SAVE",
                "status": "complete",
                "book_id": book_id,
                "output": {
                    "version": index.version,
                    "topics_count": len(index.topics)
                },
                "duration_ms": duration_ms
            }))
        except Exception as e:
            logger.error(f"Failed to save index to {index_key}: {str(e)}")
            raise

    def add_or_update_subtopic(
        self,
        index: GuidelinesIndex,
        topic_key: str,
        topic_title: str,
        subtopic_key: str,
        subtopic_title: str,
        page_range: str,
        status: str = "open"
    ) -> GuidelinesIndex:
        """
        Add or update a subtopic in the index (immutable).

        Args:
            index: Current index
            topic_key: Topic identifier (slugified)
            topic_title: Human-readable topic name
            subtopic_key: Subtopic identifier (slugified)
            subtopic_title: Human-readable subtopic name
            page_range: Page range for the subtopic (e.g., "2-6" or "7-?")
            status: Subtopic status (open, stable, final, needs_review)

        Returns:
            New GuidelinesIndex with updated subtopic

        Note:
            This function does NOT mutate the input index.
            It returns a new index with updated values.
        """
        from copy import deepcopy
        updated_index = deepcopy(index)

        # Find or create topic
        topic_entry = None
        for t in updated_index.topics:
            if t.topic_key == topic_key:
                topic_entry = t
                break

        if not topic_entry:
            # Create new topic
            topic_entry = TopicIndexEntry(
                topic_key=topic_key,
                topic_title=topic_title,
                subtopics=[]
            )
            updated_index.topics.append(topic_entry)
            logger.info(f"Created new topic: {topic_key} ({topic_title})")

        # Find or create subtopic
        subtopic_entry = None
        for s in topic_entry.subtopics:
            if s.subtopic_key == subtopic_key:
                subtopic_entry = s
                break

        if subtopic_entry:
            # Update existing subtopic
            old_status = subtopic_entry.status
            subtopic_entry.status = status
            subtopic_entry.page_range = page_range  # Update page range
            logger.info(
                f"Updated subtopic {topic_key}/{subtopic_key}: "
                f"{old_status} → {status}, page_range={page_range}"
            )
        else:
            # Create new subtopic
            subtopic_entry = SubtopicIndexEntry(
                subtopic_key=subtopic_key,
                subtopic_title=subtopic_title,
                page_range=page_range,
                status=status
            )
            topic_entry.subtopics.append(subtopic_entry)
            logger.info(
                f"Created new subtopic: {topic_key}/{subtopic_key} "
                f"({subtopic_title}), status={status}"
            )

        # Increment version
        updated_index.version += 1

        return updated_index

    def update_subtopic_status(
        self,
        index: GuidelinesIndex,
        topic_key: str,
        subtopic_key: str,
        new_status: str
    ) -> GuidelinesIndex:
        """
        Update a subtopic's status (immutable).

        Args:
            index: Current index
            topic_key: Topic identifier
            subtopic_key: Subtopic identifier
            new_status: New status (open, stable, final, needs_review)

        Returns:
            New GuidelinesIndex with updated status

        Raises:
            ValueError: If subtopic not found
        """
        from copy import deepcopy
        updated_index = deepcopy(index)

        # Find topic
        for topic_entry in updated_index.topics:
            if topic_entry.topic_key == topic_key:
                # Find subtopic
                for subtopic_entry in topic_entry.subtopics:
                    if subtopic_entry.subtopic_key == subtopic_key:
                        old_status = subtopic_entry.status
                        subtopic_entry.status = new_status
                        updated_index.version += 1

                        logger.info(
                            f"Updated status for {topic_key}/{subtopic_key}: "
                            f"{old_status} → {new_status}, version={updated_index.version}"
                        )
                        return updated_index

        raise ValueError(f"Subtopic {topic_key}/{subtopic_key} not found in index")

    # ==================== Page Index Operations ====================

    def get_or_create_page_index(self, book_id: str) -> PageIndex:
        """
        Get existing page index or create new one.

        Args:
            book_id: Book identifier

        Returns:
            PageIndex (existing or newly created)
        """
        try:
            return self.load_page_index(book_id)
        except FileNotFoundError:
            logger.info(f"No page index found for book {book_id}, creating new one")
            return PageIndex(
                book_id=book_id,
                version=1,
                last_updated=datetime.utcnow(),
                pages={}
            )

    def load_page_index(self, book_id: str) -> PageIndex:
        """
        Load page_index.json from S3.

        Args:
            book_id: Book identifier

        Returns:
            PageIndex

        Raises:
            FileNotFoundError: If page index doesn't exist
        """
        page_index_key = f"books/{book_id}/guidelines/page_index.json"

        try:
            page_index_data = self.s3.download_json(page_index_key)

            # Convert string keys to integers (JSON stores dict keys as strings)
            if "pages" in page_index_data:
                page_index_data["pages"] = {
                    int(k): v for k, v in page_index_data["pages"].items()
                }

            page_index = PageIndex(**page_index_data)
            logger.debug(
                f"Loaded page index for book {book_id}: "
                f"version {page_index.version}, {len(page_index.pages)} pages"
            )
            return page_index
        except Exception as e:
            logger.error(f"Failed to load page index from {page_index_key}: {str(e)}")
            raise FileNotFoundError(f"Page index not found: {page_index_key}")

    def save_page_index(
        self,
        page_index: PageIndex,
        create_snapshot: bool = True
    ) -> None:
        """
        Save page_index.json to S3 (with optional snapshot).

        Args:
            page_index: Page index to save
            create_snapshot: If True, create versioned snapshot before overwriting

        Side effects:
            - Writes to books/{book_id}/guidelines/page_index.json
            - Optionally writes to books/{book_id}/guidelines/snapshots/page_index.v{N}.json
        """
        book_id = page_index.book_id
        page_index_key = f"books/{book_id}/guidelines/page_index.json"

        # Create snapshot of old version (if exists and requested)
        if create_snapshot:
            try:
                old_page_index = self.load_page_index(book_id)
                snapshot_key = (
                    f"books/{book_id}/guidelines/snapshots/"
                    f"page_index.v{old_page_index.version}.json"
                )
                # Convert integer keys to strings for JSON serialization
                # Use mode='json' to properly serialize datetime objects
                snapshot_data = old_page_index.model_dump(mode='json')
                snapshot_data["pages"] = {
                    str(k): v for k, v in snapshot_data["pages"].items()
                }
                self.s3.upload_json(data=snapshot_data, s3_key=snapshot_key)
                logger.info(f"Created page index snapshot: {snapshot_key}")
            except FileNotFoundError:
                # First save - no snapshot needed
                pass
            except Exception as e:
                logger.warning(f"Failed to create page index snapshot: {str(e)}")

        # Update timestamp and save
        page_index.last_updated = datetime.utcnow()

        try:
            # Convert integer keys to strings for JSON serialization
            # Use mode='json' to properly serialize datetime objects
            save_data = page_index.model_dump(mode='json')
            save_data["pages"] = {
                str(k): v for k, v in save_data["pages"].items()
            }

            self.s3.upload_json(data=save_data, s3_key=page_index_key)
            logger.info(
                f"Saved page index for book {book_id}: version {page_index.version}, "
                f"{len(page_index.pages)} pages"
            )
        except Exception as e:
            logger.error(f"Failed to save page index to {page_index_key}: {str(e)}")
            raise

    def add_page_assignment(
        self,
        page_index: PageIndex,
        page_num: int,
        topic_key: str,
        subtopic_key: str,
        confidence: float,
        provisional: bool = False
    ) -> PageIndex:
        """
        Add or update page assignment (immutable).

        Args:
            page_index: Current page index
            page_num: Page number
            topic_key: Assigned topic
            subtopic_key: Assigned subtopic
            confidence: Boundary detection confidence
            provisional: If True, assignment may change (reconciliation)

        Returns:
            New PageIndex with updated assignment

        Note:
            This function does NOT mutate the input page index.
            It returns a new page index with updated values.
        """
        from copy import deepcopy
        updated_page_index = deepcopy(page_index)

        # Create page entry
        page_entry = PageAssignment(
            topic_key=topic_key,
            subtopic_key=subtopic_key,
            confidence=confidence,
            provisional=provisional
        )

        # Add or update
        if page_num in updated_page_index.pages:
            old_entry = updated_page_index.pages[page_num]
            logger.debug(
                f"Updating page {page_num} assignment: "
                f"{old_entry.topic_key}/{old_entry.subtopic_key} → "
                f"{topic_key}/{subtopic_key} (confidence={confidence:.2f})"
            )
        else:
            logger.debug(
                f"Adding page {page_num} assignment: "
                f"{topic_key}/{subtopic_key} (confidence={confidence:.2f})"
            )

        updated_page_index.pages[page_num] = page_entry
        updated_page_index.version += 1

        return updated_page_index

    def get_page_assignment(
        self,
        page_index: PageIndex,
        page_num: int
    ) -> Optional[PageAssignment]:
        """
        Get page assignment.

        Args:
            page_index: Current page index
            page_num: Page number

        Returns:
            PageAssignment if found, None otherwise
        """
        return page_index.pages.get(page_num)

    def get_pages_for_subtopic(
        self,
        page_index: PageIndex,
        topic_key: str,
        subtopic_key: str
    ) -> List[int]:
        """
        Get all pages assigned to a subtopic.

        Args:
            page_index: Current page index
            topic_key: Topic identifier
            subtopic_key: Subtopic identifier

        Returns:
            List of page numbers (sorted)
        """
        pages = []
        for page_num, entry in page_index.pages.items():
            if entry.topic_key == topic_key and entry.subtopic_key == subtopic_key:
                pages.append(page_num)

        pages.sort()
        return pages
