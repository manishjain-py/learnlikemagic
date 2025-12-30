"""
Repository abstraction for teaching guidelines.
This provides a clean interface to fetch guidelines and curriculum data,
isolating the rest of the codebase from database schema changes.
"""
import json
from typing import List, Optional, Dict
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import distinct
from shared.models import TeachingGuideline, GuidelineMetadata, GuidelineResponse, SubtopicInfo


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
        topic: str,
        subtopic: str
    ) -> Optional[GuidelineResponse]:
        """
        Fetch a specific teaching guideline.

        Args:
            country: Country name (e.g., "India")
            board: Education board (e.g., "CBSE")
            grade: Grade level (e.g., 3)
            subject: Subject name (e.g., "Mathematics")
            topic: Topic name (e.g., "Fractions")
            subtopic: Subtopic name (e.g., "Comparing Like Denominators")

        Returns:
            GuidelineResponse or None if not found
        """
        guideline = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.country == country,
            TeachingGuideline.board == board,
            TeachingGuideline.grade == grade,
            TeachingGuideline.subject == subject,
            TeachingGuideline.topic == topic,
            TeachingGuideline.subtopic == subtopic,
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
            topic=guideline.topic,
            subtopic=guideline.subtopic,
            guideline=guideline.guideline,
            metadata=metadata
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
            topic=guideline.topic,
            subtopic=guideline.subtopic,
            guideline=guideline.guideline,
            metadata=metadata
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

    def get_topics(
        self,
        country: str,
        board: str,
        grade: int,
        subject: str
    ) -> List[str]:
        """
        Get all available topics for a given subject.

        Args:
            country: Country name
            board: Education board
            grade: Grade level
            subject: Subject name

        Returns:
            List of topic names
        """
        topics = self.db.query(distinct(TeachingGuideline.topic)).filter(
            TeachingGuideline.country == country,
            TeachingGuideline.board == board,
            TeachingGuideline.grade == grade,
            TeachingGuideline.subject == subject,
            TeachingGuideline.review_status == "APPROVED"
        ).order_by(TeachingGuideline.topic).all()

        return [t[0] for t in topics]

    def get_subtopics(
        self,
        country: str,
        board: str,
        grade: int,
        subject: str,
        topic: str
    ) -> List[SubtopicInfo]:
        """
        Get all available subtopics for a given topic.

        Args:
            country: Country name
            board: Education board
            grade: Grade level
            subject: Subject name
            topic: Topic name

        Returns:
            List of SubtopicInfo objects
        """
        guidelines = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.country == country,
            TeachingGuideline.board == board,
            TeachingGuideline.grade == grade,
            TeachingGuideline.subject == subject,
            TeachingGuideline.topic == topic,
            TeachingGuideline.review_status == "APPROVED"
        ).order_by(TeachingGuideline.subtopic).all()

        return [
            SubtopicInfo(
                subtopic=g.subtopic,
                guideline_id=g.id
            )
            for g in guidelines
        ]


# Factory function for dependency injection
def get_guideline_repository(db: DBSession) -> TeachingGuidelineRepository:
    """Factory function to create guideline repository."""
    return TeachingGuidelineRepository(db)
