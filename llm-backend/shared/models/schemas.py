"""Pydantic API request/response schemas."""
from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any, Optional

from .domain import Student, Goal, GradingResult


class CreateSessionRequest(BaseModel):
    """Request to create a new learning session."""
    student: Student
    goal: Goal
    mode: Literal["teach_me", "clarify_doubts", "exam"] = "teach_me"


class CreateSessionResponse(BaseModel):
    """Response with session ID and first teaching turn."""
    session_id: str
    first_turn: Dict[str, Any]
    mode: str = "teach_me"
    past_discussions: Optional[list[dict]] = None


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


class ExamHistoryEntry(BaseModel):
    """A single exam attempt for trend display."""
    date: str
    score: int
    total: int
    percentage: float


class ExamFeedbackResponse(BaseModel):
    """Exam feedback shown in report card."""
    strengths: list[str]
    weak_areas: list[str]
    patterns: list[str]
    next_steps: list[str]


class ReportCardSubtopic(BaseModel):
    """Subtopic-level data for report card."""
    subtopic: str
    subtopic_key: str
    guideline_id: Optional[str] = None
    coverage: float
    last_studied: Optional[str] = None
    revision_nudge: Optional[str] = None
    latest_exam_score: Optional[int] = None
    latest_exam_total: Optional[int] = None
    latest_exam_feedback: Optional[ExamFeedbackResponse] = None
    exam_count: int = 0
    exam_history: list[ExamHistoryEntry] = Field(default_factory=list)
    teach_me_sessions: int = 0
    clarify_sessions: int = 0
    # Legacy compat
    score: float = 0.0
    session_count: int = 0
    concepts: Dict[str, float] = Field(default_factory=dict)
    misconceptions: list[ScorecardMisconception] = Field(default_factory=list)


class ReportCardTopic(BaseModel):
    """Topic-level aggregated data for report card."""
    topic: str
    topic_key: str
    score: float
    subtopics: list[ReportCardSubtopic]


class ReportCardSubject(BaseModel):
    """Subject-level aggregated data for report card."""
    subject: str
    score: float
    session_count: int
    topics: list[ReportCardTopic]
    trend: list[ScorecardTrendPoint]


class ReportCardResponse(BaseModel):
    """Complete student report card response."""
    overall_score: float
    total_sessions: int
    total_topics_studied: int
    subjects: list[ReportCardSubject]
    strengths: list[ScorecardHighlight]
    needs_practice: list[ScorecardHighlight]


class ResumableSessionResponse(BaseModel):
    """Response for GET /sessions/resumable."""
    session_id: str
    coverage: float
    current_step: int
    total_steps: int
    concepts_covered: list[str]


class PauseSummary(BaseModel):
    """Response for POST /sessions/{id}/pause."""
    coverage: float
    concepts_covered: list[str]
    message: str


class EndExamResponse(BaseModel):
    """Response for POST /sessions/{id}/end-exam."""
    score: int
    total: int
    percentage: float
    feedback: Optional[dict] = None


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
