"""
DB Sync Service

Responsibility: Sync subtopic shards to teaching_guidelines database table.

Single Responsibility Principle:
- Only handles database synchronization
- Maps SubtopicShard model to teaching_guidelines schema
- Performs upserts (insert or update)

Database Schema (teaching_guidelines table):
- NEW Phase 6 columns: topic_key, subtopic_key, objectives_json, examples_json,
  misconceptions_json, assessments_json, teaching_description, source_page_start,
  source_page_end, evidence_summary, status, confidence, version
"""

import logging
import json
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..models.guideline_models import SubtopicShard, SubtopicShardV2, Assessment

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
        country: str = "India"
    ) -> int:
        """
        Sync a subtopic shard to the database.

        Args:
            shard: Subtopic shard to sync
            book_id: Book identifier
            grade: Grade level
            subject: Subject
            board: Board (CBSE, ICSE, etc.)
            country: Country (default: India)

        Returns:
            Database row ID (guideline_id)

        Side effects:
            - Inserts new row or updates existing row in teaching_guidelines table
            - Commits transaction
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
            self._update_guideline(existing_id, shard, grade, subject, board, country)
            return existing_id
        else:
            logger.info(
                f"Inserting new guideline: {shard.topic_key}/{shard.subtopic_key}"
            )
            new_id = self._insert_guideline(shard, book_id, grade, subject, board, country)
            return new_id

    def _find_existing_guideline(
        self,
        book_id: str,
        topic_key: str,
        subtopic_key: str
    ) -> Optional[int]:
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
        country: str
    ) -> int:
        """
        Insert new guideline into database.

        Args:
            shard: Subtopic shard
            book_id: Book identifier
            grade: Grade level
            subject: Subject
            board: Board

        Returns:
            New guideline_id
        """
        # Generate unique ID for the guideline
        import uuid
        guideline_id = str(uuid.uuid4())

        # Serialize JSON fields
        objectives_json = json.dumps(shard.objectives)
        examples_json = json.dumps(shard.examples)
        misconceptions_json = json.dumps(shard.misconceptions)
        assessments_json = json.dumps([
            {
                "level": a.level,
                "prompt": a.prompt,
                "answer": a.answer
            }
            for a in shard.assessments
        ])

        query = text("""
            INSERT INTO teaching_guidelines (
                id, country, book_id, grade, subject, board,
                topic, subtopic, guideline,
                topic_key, subtopic_key, topic_title, subtopic_title,
                objectives_json, examples_json, misconceptions_json, assessments_json,
                teaching_description, description,
                source_page_start, source_page_end, source_pages,
                evidence_summary, status, confidence, version,
                created_at
            )
            VALUES (
                :id, :country, :book_id, :grade, :subject, :board,
                :topic, :subtopic, :guideline,
                :topic_key, :subtopic_key, :topic_title, :subtopic_title,
                :objectives_json, :examples_json, :misconceptions_json, :assessments_json,
                :teaching_description, :description,
                :source_page_start, :source_page_end, :source_pages,
                :evidence_summary, :status, :confidence, :version,
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
                "topic": shard.topic_title,  # Old field - use title
                "subtopic": shard.subtopic_title,  # Old field - use title
                "guideline": shard.teaching_description or "",  # Old field - use teaching_description
                "topic_key": shard.topic_key,
                "subtopic_key": shard.subtopic_key,
                "topic_title": shard.topic_title,
                "subtopic_title": shard.subtopic_title,
                "objectives_json": objectives_json,
                "examples_json": examples_json,
                "misconceptions_json": misconceptions_json,
                "assessments_json": assessments_json,
                "teaching_description": shard.teaching_description or "",
                "description": shard.description or "",
                "source_page_start": shard.source_page_start,
                "source_page_end": shard.source_page_end,
                "source_pages": json.dumps(shard.source_pages),
                "evidence_summary": shard.evidence_summary,
                "status": shard.status,
                "confidence": shard.confidence,
                "version": shard.version
            }
        )

        self.db.commit()
        new_id = result.fetchone()[0]

        logger.info(
            f"Inserted guideline (id={new_id}): {shard.topic_key}/{shard.subtopic_key}"
        )

        return new_id

    def _update_guideline(
        self,
        guideline_id: int,
        shard: SubtopicShard,
        grade: int,
        subject: str,
        board: str,
        country: str
    ) -> None:
        """
        Update existing guideline.

        Args:
            guideline_id: Database row ID
            shard: Subtopic shard with new data
            grade: Grade level
            subject: Subject
            board: Board
        """
        # Serialize JSON fields
        objectives_json = json.dumps(shard.objectives)
        examples_json = json.dumps(shard.examples)
        misconceptions_json = json.dumps(shard.misconceptions)
        assessments_json = json.dumps([
            {
                "level": a.level,
                "prompt": a.prompt,
                "answer": a.answer
            }
            for a in shard.assessments
        ])

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
                objectives_json = :objectives_json,
                examples_json = :examples_json,
                misconceptions_json = :misconceptions_json,
                assessments_json = :assessments_json,
                teaching_description = :teaching_description,
                description = :description,
                source_page_start = :source_page_start,
                source_page_end = :source_page_end,
                source_pages = :source_pages,
                evidence_summary = :evidence_summary,
                status = :status,
                confidence = :confidence,
                version = :version
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
                "topic": shard.topic_title,  # Old field - use title
                "subtopic": shard.subtopic_title,  # Old field - use title
                "guideline": shard.teaching_description or "",  # Old field - use teaching_description
                "topic_title": shard.topic_title,
                "subtopic_title": shard.subtopic_title,
                "objectives_json": objectives_json,
                "examples_json": examples_json,
                "misconceptions_json": misconceptions_json,
                "assessments_json": assessments_json,
                "teaching_description": shard.teaching_description or "",
                "description": shard.description or "",
                "source_page_start": shard.source_page_start,
                "source_page_end": shard.source_page_end,
                "source_pages": json.dumps(shard.source_pages),
                "evidence_summary": shard.evidence_summary,
                "status": shard.status,
                "confidence": shard.confidence,
                "version": shard.version
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
    ) -> List[int]:
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

        Note:
            Uses a single transaction for all shards (atomic)
        """
        guideline_ids = []

        try:
            for shard in shards:
                guideline_id = self.sync_shard(shard, book_id, grade, subject, board)
                guideline_ids.append(guideline_id)

            logger.info(
                f"Synced {len(shards)} shards for book {book_id} "
                f"(grades={grade}, subject={subject})"
            )

            return guideline_ids

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to sync shards, rolling back: {str(e)}")
            raise

    def get_synced_guidelines_for_book(self, book_id: str) -> List[dict]:
        """
        Get all synced guidelines for a book.

        Args:
            book_id: Book identifier

        Returns:
            List of guideline dicts (for debugging/monitoring)
        """
        query = text("""
            SELECT
                id, topic_key, subtopic_key, topic_title, subtopic_title,
                status, confidence, version,
                source_page_start, source_page_end,
                created_at
            FROM teaching_guidelines
            WHERE book_id = :book_id
            ORDER BY source_page_start, topic_key, subtopic_key
        """)

        result = self.db.execute(query, {"book_id": book_id})
        rows = result.fetchall()

        guidelines = []
        for row in rows:
            guidelines.append({
                "id": row[0],
                "topic_key": row[1],
                "subtopic_key": row[2],
                "topic_title": row[3],
                "subtopic_title": row[4],
                "status": row[5],
                "confidence": row[6],
                "version": row[7],
                "source_page_start": row[8],
                "source_page_end": row[9],
                "created_at": row[10].isoformat() if row[10] else None
            })

        logger.debug(f"Retrieved {len(guidelines)} guidelines for book {book_id}")

        return guidelines

    def delete_guideline(self, guideline_id: int) -> None:
        """
        Delete a guideline (soft delete recommended, but hard delete for MVP).

        Args:
            guideline_id: Database row ID

        Note:
            Future versions should implement soft delete (is_deleted flag)
        """
        query = text("""
            DELETE FROM teaching_guidelines
            WHERE id = :guideline_id
        """)

        self.db.execute(query, {"guideline_id": guideline_id})
        self.db.commit()

        logger.warning(f"Deleted guideline (id={guideline_id})")

    # ========================================================================
    # V2 SYNC METHODS
    # ========================================================================

    def sync_shard_v2(
        self,
        shard: SubtopicShardV2,
        book_id: str,
        grade: int,
        subject: str,
        board: str,
        country: str = "India"
    ) -> str:
        """
        Sync a V2 subtopic shard to the database.

        V2 changes:
        - Uses single `guidelines` field instead of structured fields
        - No objectives_json, examples_json, misconceptions_json, assessments_json
        - No teaching_description, description, evidence_summary, confidence

        Args:
            shard: V2 subtopic shard to sync
            book_id: Book identifier
            grade: Grade level
            subject: Subject
            board: Board (CBSE, ICSE, etc.)
            country: Country (default: India)

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
                f"Updating existing V2 guideline (id={existing_id}): "
                f"{shard.topic_key}/{shard.subtopic_key}"
            )
            self._update_guideline_v2(existing_id, shard, grade, subject, board, country)
            return existing_id
        else:
            logger.info(
                f"Inserting new V2 guideline: {shard.topic_key}/{shard.subtopic_key}"
            )
            new_id = self._insert_guideline_v2(shard, book_id, grade, subject, board, country)
            return new_id

    def _insert_guideline_v2(
        self,
        shard: SubtopicShardV2,
        book_id: str,
        grade: int,
        subject: str,
        board: str,
        country: str
    ) -> str:
        """
        Insert new V2 guideline into database.

        V2 uses simplified schema with single guidelines field.
        """
        import uuid
        guideline_id = str(uuid.uuid4())

        # V2: Single guidelines field replaces all structured fields
        query = text("""
            INSERT INTO teaching_guidelines (
                id, country, book_id, grade, subject, board,
                topic, subtopic, guideline,
                topic_key, subtopic_key, topic_title, subtopic_title,
                source_page_start, source_page_end,
                status, version,
                created_at, updated_at
            )
            VALUES (
                :id, :country, :book_id, :grade, :subject, :board,
                :topic, :subtopic, :guideline,
                :topic_key, :subtopic_key, :topic_title, :subtopic_title,
                :source_page_start, :source_page_end,
                :status, :version,
                NOW(), NOW()
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
                "topic": shard.topic_title,  # Old field - use title for backward compat
                "subtopic": shard.subtopic_title,  # Old field - use title
                "guideline": shard.guidelines,  # V2: Single comprehensive guidelines field
                "topic_key": shard.topic_key,
                "subtopic_key": shard.subtopic_key,
                "topic_title": shard.topic_title,
                "subtopic_title": shard.subtopic_title,
                "source_page_start": shard.source_page_start,
                "source_page_end": shard.source_page_end,
                "status": shard.status,
                "version": shard.version
            }
        )

        self.db.commit()
        new_id = result.fetchone()[0]

        logger.info(
            f"Inserted V2 guideline (id={new_id}): {shard.topic_key}/{shard.subtopic_key}"
        )

        return new_id

    def _update_guideline_v2(
        self,
        guideline_id: str,
        shard: SubtopicShardV2,
        grade: int,
        subject: str,
        board: str,
        country: str
    ) -> None:
        """
        Update existing V2 guideline.

        V2 uses simplified schema with single guidelines field.
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
                source_page_start = :source_page_start,
                source_page_end = :source_page_end,
                status = :status,
                version = :version,
                updated_at = NOW()
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
                "topic": shard.topic_title,  # Old field - backward compat
                "subtopic": shard.subtopic_title,  # Old field - backward compat
                "guideline": shard.guidelines,  # V2: Single comprehensive guidelines field
                "topic_title": shard.topic_title,
                "subtopic_title": shard.subtopic_title,
                "source_page_start": shard.source_page_start,
                "source_page_end": shard.source_page_end,
                "status": shard.status,
                "version": shard.version
            }
        )

        self.db.commit()

        logger.info(
            f"Updated V2 guideline (id={guideline_id}): "
            f"{shard.topic_key}/{shard.subtopic_key}, version={shard.version}"
        )

    def sync_multiple_shards_v2(
        self,
        shards: List[SubtopicShardV2],
        book_id: str,
        grade: int,
        subject: str,
        board: str
    ) -> List[str]:
        """
        Sync multiple V2 shards in a batch.

        Args:
            shards: List of V2 subtopic shards
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
                guideline_id = self.sync_shard_v2(shard, book_id, grade, subject, board)
                guideline_ids.append(guideline_id)

            logger.info(
                f"Synced {len(shards)} V2 shards for book {book_id} "
                f"(grade={grade}, subject={subject})"
            )

            return guideline_ids

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to sync V2 shards, rolling back: {str(e)}")
            raise
