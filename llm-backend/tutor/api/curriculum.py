"""Curriculum discovery API endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from typing import Optional

from database import get_db
from shared.repositories import TeachingGuidelineRepository
from shared.models import CurriculumResponse

router = APIRouter(prefix="/curriculum", tags=["curriculum"])


@router.get("", response_model=CurriculumResponse)
def get_curriculum(
    country: str = Query(..., description="Country code (e.g., IN, US)"),
    board: str = Query(..., description="Board name (e.g., CBSE, ICSE)"),
    grade: int = Query(..., description="Grade level"),
    subject: Optional[str] = Query(None, description="Subject filter"),
    topic: Optional[str] = Query(None, description="Topic filter"),
    db: DBSession = Depends(get_db)
):
    """
    Discover available curriculum options.

    Query Parameters:
    - country: Country name (e.g., "India")
    - board: Education board (e.g., "CBSE")
    - grade: Grade level (e.g., 3)
    - subject (optional): Filter by subject (returns topics)
    - topic (optional): Filter by topic (returns subtopics, requires subject)

    Returns:
    - If only country/board/grade provided: list of subjects
    - If subject provided: list of topics
    - If subject + topic provided: list of subtopics with guideline IDs
    """
    try:
        repo = TeachingGuidelineRepository(db)

        # Case 1: Get subtopics (subject + topic provided)
        if subject and topic:
            subtopics = repo.get_subtopics(country, board, grade, subject, topic)
            return CurriculumResponse(subtopics=subtopics)

        # Case 2: Get topics (only subject provided)
        elif subject:
            topics = repo.get_topics(country, board, grade, subject)
            return CurriculumResponse(topics=topics)

        # Case 3: Get subjects (only country/board/grade provided)
        else:
            subjects = repo.get_subjects(country, board, grade)
            return CurriculumResponse(subjects=subjects)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching curriculum: {str(e)}")
