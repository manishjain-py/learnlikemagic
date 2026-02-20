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


# ── Scorecard schemas ──

class ScorecardMisconception(BaseModel):
    """A misconception detected during a session."""
    description: str
    resolved: bool


class ScorecardSubtopic(BaseModel):
    """Subtopic-level performance data."""
    subtopic: str
    subtopic_key: str
    guideline_id: Optional[str] = None
    score: float
    session_count: int
    latest_session_date: Optional[str] = None
    concepts: Dict[str, float]
    misconceptions: List[ScorecardMisconception]


class ScorecardTopic(BaseModel):
    """Topic-level aggregated performance."""
    topic: str
    topic_key: str
    score: float
    subtopics: List[ScorecardSubtopic]


class ScorecardTrendPoint(BaseModel):
    """A single data point for mastery trend over time."""
    date: Optional[str] = None
    date_label: Optional[str] = None
    score: float


class ScorecardSubject(BaseModel):
    """Subject-level aggregated performance with trend data."""
    subject: str
    score: float
    session_count: int
    topics: List[ScorecardTopic]
    trend: List[ScorecardTrendPoint]


class ScorecardHighlight(BaseModel):
    """A highlighted subtopic (strength or needs-practice)."""
    subtopic: str
    subject: str
    score: float


class ScorecardResponse(BaseModel):
    """Complete student scorecard response."""
    overall_score: float
    total_sessions: int
    total_topics_studied: int
    subjects: List[ScorecardSubject]
    strengths: List[ScorecardHighlight]
    needs_practice: List[ScorecardHighlight]


class SubtopicProgressEntry(BaseModel):
    """Progress for a single subtopic (used in topic selection indicators)."""
    score: float
    session_count: int
    status: str  # "mastered" | "in_progress"


class SubtopicProgressResponse(BaseModel):
    """Lightweight subtopic progress lookup for curriculum picker."""
    user_progress: Dict[str, SubtopicProgressEntry]


# Import GuidelineMetadata for forward reference
from .domain import GuidelineMetadata
GuidelineResponse.model_rebuild()
