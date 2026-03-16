"""
Repository abstraction for teaching guidelines.
This provides a clean interface to fetch guidelines and curriculum data,
isolating the rest of the codebase from database schema changes.
"""
import json
from typing import List, Optional, Dict
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import distinct
from shared.models import TeachingGuideline, GuidelineMetadata, GuidelineResponse, TopicInfo, ChapterInfo


class TeachingGuidelineRepository:
    """
    Repository for accessing teaching guidelines.
    Provides abstraction over database operations.
    """

    def __init__(self, db: DBSession):
        self.db = db

    def _parse_metadata(self, metadata_json: Optional[str]) -> Optional[GuidelineMetadata]:
        """
        Parse and validate metadata JSON.

        Args:
            metadata_json: JSON string containing metadata

        Returns:
            GuidelineMetadata object or None if parsing fails
        """
        if not metadata_json:
            return None

        try:
            metadata_dict = json.loads(metadata_json)
            return GuidelineMetadata(**metadata_dict)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_guideline(
        self,
        country: str,
        board: str,
        grade: int,
        subject: str,
        chapter: str,
        topic: str
    ) -> Optional[GuidelineResponse]:
        """
        Fetch a specific teaching guideline.

        Args:
            country: Country name (e.g., "India")
            board: Education board (e.g., "CBSE")
            grade: Grade level (e.g., 3)
            subject: Subject name (e.g., "Mathematics")
            chapter: Chapter name (e.g., "Fractions")
            topic: Topic name (e.g., "Comparing Like Denominators")

        Returns:
            GuidelineResponse or None if not found
        """
        guideline = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.country == country,
            TeachingGuideline.board == board,
            TeachingGuideline.grade == grade,
            TeachingGuideline.subject == subject,
            TeachingGuideline.chapter == chapter,
            TeachingGuideline.topic == topic,
            TeachingGuideline.review_status == "APPROVED"
        ).first()

        if not guideline:
            return None

        metadata = self._parse_metadata(guideline.metadata_json)

        return GuidelineResponse(
            id=guideline.id,
            country=guideline.country,
            board=guideline.board,
            grade=guideline.grade,
            subject=guideline.subject,
            chapter=guideline.chapter,
            topic=guideline.topic,
            guideline=guideline.guideline,
            metadata=metadata,
            prior_topics_context=guideline.prior_topics_context,
        )

    def get_guideline_by_id(self, guideline_id: str) -> Optional[GuidelineResponse]:
        """
        Fetch a guideline by its ID.

        Args:
            guideline_id: The guideline ID

        Returns:
            GuidelineResponse or None if not found
        """
        guideline = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline_id,
            TeachingGuideline.review_status == "APPROVED"  # Requirement: Tutor only sees approved
        ).first()

        if not guideline:
            return None

        # Parse metadata using helper
        metadata = self._parse_metadata(guideline.metadata_json)

        return GuidelineResponse(
            id=guideline.id,
            country=guideline.country,
            board=guideline.board,
            grade=guideline.grade,
            subject=guideline.subject,
            chapter=guideline.chapter,
            topic=guideline.topic,
            guideline=guideline.guideline,
            metadata=metadata,
            prior_topics_context=guideline.prior_topics_context,
        )

    def get_subjects(self, country: str, board: str, grade: int) -> List[str]:
        """
        Get all available subjects for a given country, board, and grade.

        Args:
            country: Country name
            board: Education board
            grade: Grade level

        Returns:
            List of subject names
        """
        subjects = self.db.query(distinct(TeachingGuideline.subject)).filter(
            TeachingGuideline.country == country,
            TeachingGuideline.board == board,
            TeachingGuideline.grade == grade,
            TeachingGuideline.review_status == "APPROVED"
        ).order_by(TeachingGuideline.subject).all()

        return [s[0] for s in subjects]

    def get_chapters(
        self,
        country: str,
        board: str,
        grade: int,
        subject: str
    ) -> List[ChapterInfo]:
        """
        Get all available chapters for a given subject, with summaries and sequencing.

        Args:
            country: Country name
            board: Education board
            grade: Grade level
            subject: Subject name

        Returns:
            List of ChapterInfo objects sorted by chapter_sequence
        """
        guidelines = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.country == country,
            TeachingGuideline.board == board,
            TeachingGuideline.grade == grade,
            TeachingGuideline.subject == subject,
            TeachingGuideline.review_status == "APPROVED"
        ).all()

        # Group by chapter
        chapter_map: Dict[str, dict] = {}
        for g in guidelines:
            ch = g.chapter
            if ch not in chapter_map:
                chapter_map[ch] = {
                    "chapter": ch,
                    "chapter_summary": g.chapter_summary,
                    "chapter_sequence": g.chapter_sequence,
                    "guideline_ids": [],
                }
            chapter_map[ch]["guideline_ids"].append(g.id)

        chapters = [
            ChapterInfo(
                chapter=data["chapter"],
                chapter_summary=data["chapter_summary"],
                chapter_sequence=data["chapter_sequence"],
                topic_count=len(data["guideline_ids"]),
                guideline_ids=data["guideline_ids"],
            )
            for data in chapter_map.values()
        ]

        # Sort by sequence (nulls last), then alphabetically
        chapters.sort(key=lambda c: (
            c.chapter_sequence if c.chapter_sequence is not None else 999999,
            c.chapter,
        ))

        return chapters

    def get_topics(
        self,
        country: str,
        board: str,
        grade: int,
        subject: str,
        chapter: str
    ) -> List[TopicInfo]:
        """
        Get all available topics for a given chapter, with summaries and sequencing.

        Args:
            country: Country name
            board: Education board
            grade: Grade level
            subject: Subject name
            chapter: Chapter name

        Returns:
            List of TopicInfo objects sorted by topic_sequence
        """
        guidelines = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.country == country,
            TeachingGuideline.board == board,
            TeachingGuideline.grade == grade,
            TeachingGuideline.subject == subject,
            TeachingGuideline.chapter == chapter,
            TeachingGuideline.review_status == "APPROVED"
        ).all()

        topics = [
            TopicInfo(
                topic=g.topic,
                guideline_id=g.id,
                topic_summary=g.topic_summary,
                topic_sequence=g.topic_sequence,
            )
            for g in guidelines
        ]

        # Sort by sequence (nulls last), then alphabetically
        topics.sort(key=lambda t: (
            t.topic_sequence if t.topic_sequence is not None else 999999,
            t.topic,
        ))

        return topics


# Factory function for dependency injection
def get_guideline_repository(db: DBSession) -> TeachingGuidelineRepository:
    """Factory function to create guideline repository."""
    return TeachingGuidelineRepository(db)
