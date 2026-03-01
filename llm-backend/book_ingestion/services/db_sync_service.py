"""
DB Sync Service

Responsibility: Sync subtopic shards to teaching_guidelines database table.

Single Responsibility Principle:
- Only handles database synchronization
- Maps SubtopicShard model to teaching_guidelines schema
- Performs upserts (insert or update)

Database Schema (teaching_guidelines table):
- Key columns: topic_key, subtopic_key, topic_title, subtopic_title
- Content: guidelines (text field with complete teaching guidelines)
- Metadata: source_page_start, source_page_end, status, version
"""

import logging
import json
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..models.guideline_models import SubtopicShard, Assessment

logger = logging.getLogger(__name__)


class DBSyncService:
    """
    Sync subtopic shards to PostgreSQL teaching_guidelines table.

    Responsibilities:
    1. Map SubtopicShard to database schema
    2. Perform upsert operations (INSERT or UPDATE)
    3. Handle JSON serialization for array fields
    4. Maintain data integrity
    """

    def __init__(self, db_session: Session):
        """
        Initialize DB sync service.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session
        logger.info("Initialized DBSyncService")

    def sync_shard(
        self,
        shard: SubtopicShard,
        book_id: str,
        grade: int,
        subject: str,
        board: str,
        country: str = "India",
        topic_summary: str = "",
        topic_sequence: Optional[int] = None,
        subtopic_sequence: Optional[int] = None,
        topic_storyline: Optional[str] = None
    ) -> str:
        """
        Sync a subtopic shard to the database.

        Uses simplified schema with single `guidelines` text field containing
        complete teaching guidelines in natural language.

        Args:
            shard: Subtopic shard to sync
            book_id: Book identifier
            grade: Grade level
            subject: Subject
            board: Board (CBSE, ICSE, etc.)
            country: Country (default: India)
            topic_summary: Topic summary
            topic_sequence: Teaching order of topic within book
            subtopic_sequence: Teaching order of subtopic within topic
            topic_storyline: Narrative of topic's teaching progression

        Returns:
            Database row ID (guideline_id)
        """
        # Check if guideline already exists
        existing_id = self._find_existing_guideline(
            book_id,
            shard.topic_key,
            shard.subtopic_key
        )

        if existing_id:
            logger.info(
                f"Updating existing guideline (id={existing_id}): "
                f"{shard.topic_key}/{shard.subtopic_key}"
            )
            self._update_guideline(
                existing_id, shard, grade, subject, board, country, topic_summary,
                topic_sequence=topic_sequence, subtopic_sequence=subtopic_sequence,
                topic_storyline=topic_storyline
            )
            return existing_id
        else:
            logger.info(
                f"Inserting new guideline: {shard.topic_key}/{shard.subtopic_key}"
            )
            new_id = self._insert_guideline(
                shard, book_id, grade, subject, board, country, topic_summary=topic_summary,
                topic_sequence=topic_sequence, subtopic_sequence=subtopic_sequence,
                topic_storyline=topic_storyline
            )
            return new_id

    def _find_existing_guideline(
        self,
        book_id: str,
        topic_key: str,
        subtopic_key: str
    ) -> Optional[str]:
        """
        Find existing guideline by book_id + topic_key + subtopic_key.

        Args:
            book_id: Book identifier
            topic_key: Topic key
            subtopic_key: Subtopic key

        Returns:
            guideline_id if found, None otherwise
        """
        query = text("""
            SELECT id FROM teaching_guidelines
            WHERE book_id = :book_id
              AND topic_key = :topic_key
              AND subtopic_key = :subtopic_key
            LIMIT 1
        """)

        result = self.db.execute(
            query,
            {
                "book_id": book_id,
                "topic_key": topic_key,
                "subtopic_key": subtopic_key
            }
        )
        row = result.fetchone()

        if row:
            return row[0]
        return None

    def _insert_guideline(
        self,
        shard: SubtopicShard,
        book_id: str,
        grade: int,
        subject: str,
        board: str,
        country: str,
        review_status: str = "TO_BE_REVIEWED",
        topic_summary: str = "",
        topic_sequence: Optional[int] = None,
        subtopic_sequence: Optional[int] = None,
        topic_storyline: Optional[str] = None,
        _commit: bool = True
    ) -> str:
        """
        Insert new guideline into database.

        Uses simplified schema with single guidelines text field.
        Set _commit=False when caller manages the transaction (e.g. batch sync).
        """
        import uuid
        guideline_id = str(uuid.uuid4())

        query = text("""
            INSERT INTO teaching_guidelines (
                id, country, book_id, grade, subject, board,
                topic, subtopic, guideline,
                topic_key, subtopic_key, topic_title, subtopic_title,
                topic_summary, subtopic_summary,
                topic_sequence, subtopic_sequence, topic_storyline,
                source_page_start, source_page_end,
                status, version, review_status,
                created_at
            )
            VALUES (
                :id, :country, :book_id, :grade, :subject, :board,
                :topic, :subtopic, :guideline,
                :topic_key, :subtopic_key, :topic_title, :subtopic_title,
                :topic_summary, :subtopic_summary,
                :topic_sequence, :subtopic_sequence, :topic_storyline,
                :source_page_start, :source_page_end,
                :status, :version, :review_status,
                NOW()
            )
            RETURNING id
        """)

        result = self.db.execute(
            query,
            {
                "id": guideline_id,
                "country": country,
                "book_id": book_id,
                "grade": grade,
                "subject": subject,
                "board": board,
                "topic": shard.topic_title,  # Legacy column for backward compatibility
                "subtopic": shard.subtopic_title,  # Legacy column
                "guideline": shard.guidelines,  # Complete guidelines in natural language
                "topic_key": shard.topic_key,
                "subtopic_key": shard.subtopic_key,
                "topic_title": shard.topic_title,
                "subtopic_title": shard.subtopic_title,
                "topic_summary": topic_summary,
                "subtopic_summary": shard.subtopic_summary,
                "topic_sequence": topic_sequence,
                "subtopic_sequence": shard.subtopic_sequence if shard.subtopic_sequence else subtopic_sequence,
                "topic_storyline": topic_storyline,
                "source_page_start": shard.source_page_start,
                "source_page_end": shard.source_page_end,
                "status": "synced", # Default status as shard.status is removed
                "version": shard.version,
                "review_status": review_status
            }
        )

        if _commit:
            self.db.commit()
        new_id = result.fetchone()[0]

        logger.info(
            f"Inserted guideline (id={new_id}): {shard.topic_key}/{shard.subtopic_key}"
        )

        return new_id

    def _update_guideline(
        self,
        guideline_id: str,
        shard: SubtopicShard,
        grade: int,
        subject: str,
        board: str,
        country: str,
        topic_summary: str = "",
        topic_sequence: Optional[int] = None,
        subtopic_sequence: Optional[int] = None,
        topic_storyline: Optional[str] = None
    ) -> None:
        """
        Update existing guideline.

        Uses simplified schema with single guidelines text field.
        """
        query = text("""
            UPDATE teaching_guidelines
            SET
                country = :country,
                grade = :grade,
                subject = :subject,
                board = :board,
                topic = :topic,
                subtopic = :subtopic,
                guideline = :guideline,
                topic_title = :topic_title,
                subtopic_title = :subtopic_title,
                topic_summary = :topic_summary,
                subtopic_summary = :subtopic_summary,
                topic_sequence = :topic_sequence,
                subtopic_sequence = :subtopic_sequence,
                topic_storyline = :topic_storyline,
                source_page_start = :source_page_start,
                source_page_end = :source_page_end,
                status = :status,
                version = :version,
                updated_at = :updated_at
            WHERE id = :guideline_id
        """)

        self.db.execute(
            query,
            {
                "guideline_id": guideline_id,
                "country": country,
                "grade": grade,
                "subject": subject,
                "board": board,
                "topic": shard.topic_title,  # Legacy column for backward compatibility
                "subtopic": shard.subtopic_title,  # Legacy column
                "guideline": shard.guidelines,  # Complete guidelines in natural language
                "topic_title": shard.topic_title,
                "subtopic_title": shard.subtopic_title,
                "topic_summary": topic_summary,
                "subtopic_summary": shard.subtopic_summary,
                "topic_sequence": topic_sequence,
                "subtopic_sequence": shard.subtopic_sequence if shard.subtopic_sequence else subtopic_sequence,
                "topic_storyline": topic_storyline,
                "source_page_start": shard.source_page_start,
                "source_page_end": shard.source_page_end,
                "status": "synced", # Default status
                "version": shard.version,
                "updated_at": datetime.utcnow()
            }
        )

        self.db.commit()

        logger.info(
            f"Updated guideline (id={guideline_id}): "
            f"{shard.topic_key}/{shard.subtopic_key}, version={shard.version}"
        )

    def sync_multiple_shards(
        self,
        shards: List[SubtopicShard],
        book_id: str,
        grade: int,
        subject: str,
        board: str
    ) -> List[str]:
        """
        Sync multiple shards in a batch.

        Args:
            shards: List of subtopic shards
            book_id: Book identifier
            grade: Grade level
            subject: Subject
            board: Board

        Returns:
            List of guideline_ids (in same order as input shards)
        """
        guideline_ids = []

        try:
            for shard in shards:
                guideline_id = self.sync_shard(shard, book_id, grade, subject, board)
                guideline_ids.append(guideline_id)

            logger.info(
                f"Synced {len(shards)} shards for book {book_id} "
                f"(grade={grade}, subject={subject})"
            )

            return guideline_ids

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to sync shards, rolling back: {str(e)}")
            raise

    def sync_book_guidelines(
        self,
        book_id: str,
        s3_client,
        book_metadata: dict
    ) -> dict:
        """
        Sync all guidelines for a book from S3 to database.

        This method loads all shards from S3 and syncs them to the database.

        Args:
            book_id: Book identifier
            s3_client: S3 client for loading shards
            book_metadata: Book metadata containing grade, subject, board

        Returns:
            Dict with sync statistics: {
                "synced_count": int,
                "updated_count": int,
                "created_count": int
            }
        """
        from ..models.guideline_models import GuidelinesIndex, SubtopicShard

        logger.info(f"Starting database sync for book {book_id}")

        # Load index to get all topics/subtopics
        try:
            index_key = f"books/{book_id}/guidelines/index.json"
            index_data = s3_client.download_json(index_key)
            index = GuidelinesIndex(**index_data)
        except Exception as e:
            logger.error(f"Failed to load index for book {book_id}: {e}")
            return {"synced_count": 0, "updated_count": 0, "created_count": 0}

        # Extract metadata
        grade = book_metadata.get("grade", 0)
        subject = book_metadata.get("subject", "Unknown")
        board = book_metadata.get("board", "Unknown")
        country = book_metadata.get("country", "India")

        # Collect all shards to sync
        shards_to_sync = []
        for topic_entry in index.topics:
            for subtopic_entry in topic_entry.subtopics:
                # Load shard from S3
                shard_key = (
                    f"books/{book_id}/guidelines/topics/{topic_entry.topic_key}/"
                    f"subtopics/{subtopic_entry.subtopic_key}.latest.json"
                )
                try:
                    shard_data = s3_client.download_json(shard_key)
                    shard = SubtopicShard(**shard_data)
                    shards_to_sync.append(shard)
                except Exception as e:
                    logger.warning(
                        f"Failed to load shard {shard_key}: {e}. Skipping."
                    )
                    continue

        if not shards_to_sync:
            logger.warning(f"No shards found to sync for book {book_id}")
            return {"synced_count": 0, "updated_count": 0, "created_count": 0}

        # Sync all shards (Requirement 6: Full book snapshot & reset statuses)
        try:
            import time
            import json
            start_time = time.time()

            logger.info(json.dumps({
                "step": "DB_SYNC",
                "status": "starting",
                "book_id": book_id,
                "input": {"shards_count": len(shards_to_sync)}
            }))

            # 1. Cascade-delete study plans for guidelines being replaced
            study_plans_delete = text(
                "DELETE FROM study_plans WHERE guideline_id IN "
                "(SELECT id FROM teaching_guidelines WHERE book_id = :book_id)"
            )
            self.db.execute(study_plans_delete, {"book_id": book_id})

            # 2. Delete all existing guidelines for this book
            delete_query = text("DELETE FROM teaching_guidelines WHERE book_id = :book_id")
            self.db.execute(delete_query, {"book_id": book_id})
            
            # 3. Insert all shards as new rows with TO_BE_REVIEWED status
            created_count = 0
            
            for shard in shards_to_sync:
                # Get topic-level fields from index
                topic_summary = ""
                topic_sequence = None
                topic_storyline = None
                for topic in index.topics:
                    if topic.topic_key == shard.topic_key:
                        topic_summary = topic.topic_summary
                        topic_sequence = topic.topic_sequence if topic.topic_sequence else None
                        topic_storyline = topic.topic_storyline if topic.topic_storyline else None
                        break

                # Insert new row (no per-row commit — single transaction)
                self._insert_guideline(
                    shard, book_id, grade, subject, board, country,
                    review_status="TO_BE_REVIEWED",
                    topic_summary=topic_summary,
                    topic_sequence=topic_sequence,
                    subtopic_sequence=shard.subtopic_sequence if shard.subtopic_sequence else None,
                    topic_storyline=topic_storyline,
                    _commit=False
                )
                created_count += 1

            # Single commit for the entire delete+insert transaction
            self.db.commit()
            
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "DB_SYNC",
                "status": "complete",
                "book_id": book_id,
                "output": {
                    "synced_count": created_count,
                    "created_count": created_count,
                    "updated_count": 0
                },
                "duration_ms": duration_ms
            }))

            return {
                "synced_count": created_count,
                "created_count": created_count,
                "updated_count": 0
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to sync book guidelines: {str(e)}")
            raise
