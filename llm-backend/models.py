"""
Database models for the Adaptive Tutor Agent.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from pydantic import BaseModel, Field
from typing import List, Dict, Any

Base = declarative_base()


# SQLAlchemy ORM Models

class Session(Base):
    """Session table - stores tutor state per learning session."""
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    student_json = Column(Text, nullable=False)  # JSON: {id, grade, prefs}
    goal_json = Column(Text, nullable=False)     # JSON: {topic, syllabus, learning_objectives}
    state_json = Column(Text, nullable=False)    # Full TutorState serialized
    mastery = Column(Float, default=0.0)
    step_idx = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship("Event", back_populates="session", cascade="all, delete-orphan")


class Event(Base):
    """Event log - tracks each node execution."""
    __tablename__ = "events"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    node = Column(String, nullable=False)  # Present, Check, Diagnose, Remediate, Advance
    step_idx = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)  # JSON: arbitrary metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="events")

    __table_args__ = (
        Index("idx_session_step", "session_id", "step_idx"),
    )


class Content(Base):
    """Content table - stores curriculum snippets for RAG."""
    __tablename__ = "contents"

    id = Column(String, primary_key=True)
    topic = Column(String, nullable=False)
    grade = Column(Integer, nullable=False)
    skill = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    tags = Column(String, nullable=False)  # comma-separated

    __table_args__ = (
        Index("idx_topic_grade", "topic", "grade"),
    )


class TeachingGuideline(Base):
    """Teaching guidelines table - stores pedagogical instructions for teaching topics."""
    __tablename__ = "teaching_guidelines"

    id = Column(String, primary_key=True)
    country = Column(String, nullable=False)  # e.g., "India"
    board = Column(String, nullable=False)    # e.g., "CBSE", "ICSE"
    grade = Column(Integer, nullable=False)   # e.g., 3
    subject = Column(String, nullable=False)  # e.g., "Mathematics"
    topic = Column(String, nullable=False)    # e.g., "Fractions"
    subtopic = Column(String, nullable=False) # e.g., "Comparing Like Denominators"
    guideline = Column(Text, nullable=False)  # Detailed teaching instructions
    review_status = Column(String, default="TO_BE_REVIEWED")  # TO_BE_REVIEWED, APPROVED
    metadata_json = Column(Text, nullable=True)  # JSON: objectives, depth, misconceptions, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_curriculum", "country", "board", "grade", "subject", "topic"),
    )


# FTS5 virtual table is created via raw SQL in db.py, not as ORM model


# Pydantic Models for API

class StudentPrefs(BaseModel):
    style: Optional[str] = "standard"  # simple, standard, challenge
    lang: Optional[str] = "en"


class Student(BaseModel):
    id: str
    grade: int
    prefs: Optional[StudentPrefs] = None


class Goal(BaseModel):
    topic: str
    syllabus: str
    learning_objectives: List[str]
    guideline_id: Optional[str] = None  # ID of the teaching guideline to use


class HistoryEntry(BaseModel):
    role: str  # "teacher" or "student"
    msg: str
    meta: Optional[Dict[str, Any]] = None


class GradingResult(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    labels: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class TutorState(BaseModel):
    """Core state object for LangGraph agent."""
    session_id: str
    student: Student
    goal: Goal
    step_idx: int = 0
    history: List[HistoryEntry] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    mastery_score: float = 0.0
    last_grading: Optional[GradingResult] = None
    next_action: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


class CreateSessionRequest(BaseModel):
    student: Student
    goal: Goal


class CreateSessionResponse(BaseModel):
    session_id: str
    first_turn: Dict[str, Any]


class StepRequest(BaseModel):
    student_reply: str


class StepResponse(BaseModel):
    next_turn: Dict[str, Any]
    routing: str  # "Advance" or "Remediate"
    last_grading: Optional[GradingResult] = None


class SummaryResponse(BaseModel):
    steps_completed: int
    mastery_score: float
    misconceptions_seen: List[str]
    suggestions: List[str]


class RAGSnippet(BaseModel):
    """Represents a retrieved content snippet."""
    id: str
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class GuidelineMetadata(BaseModel):
    """Metadata for teaching guidelines."""
    learning_objectives: List[str] = Field(default_factory=list)
    depth_level: str = "intermediate"  # basic, intermediate, advanced
    prerequisites: List[str] = Field(default_factory=list)
    common_misconceptions: List[str] = Field(default_factory=list)
    scaffolding_strategies: List[str] = Field(default_factory=list)
    assessment_criteria: Dict[str, str] = Field(default_factory=dict)


class GuidelineResponse(BaseModel):
    """Response model for teaching guideline."""
    id: str
    country: str
    board: str
    grade: int
    subject: str
    topic: str
    subtopic: str
    guideline: str
    metadata: Optional[GuidelineMetadata] = None


class SubtopicInfo(BaseModel):
    """Information about a subtopic."""
    subtopic: str
    guideline_id: str


class CurriculumResponse(BaseModel):
    """Response model for curriculum discovery."""
    subjects: Optional[List[str]] = None
    topics: Optional[List[str]] = None
    subtopics: Optional[List[SubtopicInfo]] = None
