"""Pydantic API request/response schemas."""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from .domain import Student, Goal, GradingResult


class CreateSessionRequest(BaseModel):
    """Request to create a new learning session."""
    student: Student
    goal: Goal


class CreateSessionResponse(BaseModel):
    """Response with session ID and first teaching turn."""
    session_id: str
    first_turn: Dict[str, Any]


class StepRequest(BaseModel):
    """Request to submit a student's answer."""
    student_reply: str


class StepResponse(BaseModel):
    """Response with next teaching turn and grading info."""
    next_turn: Dict[str, Any]
    routing: str  # "Advance" or "Remediate"
    last_grading: Optional[GradingResult] = None


class SummaryResponse(BaseModel):
    """Session summary with performance metrics."""
    steps_completed: int
    mastery_score: float
    misconceptions_seen: List[str]
    suggestions: List[str]


class GuidelineResponse(BaseModel):
    """Teaching guideline with metadata."""
    id: str
    country: str
    board: str
    grade: int
    subject: str
    topic: str
    subtopic: str
    guideline: str
    metadata: Optional["GuidelineMetadata"] = None  # Forward reference


class SubtopicInfo(BaseModel):
    """Subtopic information with guideline ID."""
    subtopic: str
    guideline_id: str


class CurriculumResponse(BaseModel):
    """Curriculum discovery response - one of subjects, topics, or subtopics."""
    subjects: Optional[List[str]] = None
    topics: Optional[List[str]] = None
    subtopics: Optional[List[SubtopicInfo]] = None


# Import GuidelineMetadata for forward reference
from .domain import GuidelineMetadata
GuidelineResponse.model_rebuild()
