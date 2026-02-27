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


# ── Report Card schemas ──

class ReportCardSubtopic(BaseModel):
    """Subtopic-level data for report card."""
    subtopic: str
    subtopic_key: str
    guideline_id: Optional[str] = None
    coverage: float                          # 0-100%, teach_me sessions only
    latest_exam_score: Optional[int] = None  # X in X/Y
    latest_exam_total: Optional[int] = None  # Y in X/Y
    last_studied: Optional[str] = None


class ReportCardTopic(BaseModel):
    """Topic-level data for report card."""
    topic: str
    topic_key: str
    subtopics: list[ReportCardSubtopic]


class ReportCardSubject(BaseModel):
    """Subject-level data for report card."""
    subject: str
    topics: list[ReportCardTopic]


class ReportCardResponse(BaseModel):
    """Complete student report card response."""
    total_sessions: int
    total_topics_studied: int
    subjects: list[ReportCardSubject]


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
    score: float
    total: int
    percentage: float
    feedback: Optional[dict] = None


class SubtopicProgressEntry(BaseModel):
    """Progress for a single subtopic (used in topic selection indicators)."""
    coverage: float
    session_count: int
    status: str  # "studied" | "not_started"


class SubtopicProgressResponse(BaseModel):
    """Lightweight subtopic progress lookup for curriculum picker."""
    user_progress: Dict[str, SubtopicProgressEntry]


class GuidelineSessionEntry(BaseModel):
    """A session summary for a specific guideline."""
    session_id: str
    mode: str
    created_at: Optional[str] = None
    is_complete: bool
    exam_finished: bool = False
    exam_score: Optional[float] = None
    exam_total: Optional[int] = None
    exam_answered: Optional[int] = None
    coverage: Optional[float] = None


class GuidelineSessionsResponse(BaseModel):
    """Response for GET /sessions/guideline/{guideline_id}."""
    sessions: list[GuidelineSessionEntry]


class ExamReviewQuestion(BaseModel):
    """A single exam question with full review details."""
    question_idx: int
    question_text: str
    student_answer: Optional[str] = None
    expected_answer: str
    result: Optional[str] = None
    score: float = 0.0
    marks_rationale: str = ""
    feedback: str = ""
    concept: str = ""
    difficulty: str = ""


class ExamReviewResponse(BaseModel):
    """Response for GET /sessions/{id}/exam-review."""
    session_id: str
    created_at: Optional[str] = None
    exam_feedback: Optional[dict] = None
    questions: list[ExamReviewQuestion]


# Import GuidelineMetadata for forward reference
from .domain import GuidelineMetadata
GuidelineResponse.model_rebuild()
