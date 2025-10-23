"""SQLAlchemy ORM database models."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Session(Base):
    """Session table - stores tutor state per learning session."""
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    student_json = Column(Text, nullable=False)  # JSON: {id, grade, prefs}
    goal_json = Column(Text, nullable=False)     # JSON: {topic, syllabus, learning_objectives}
    state_json = Column(Text, nullable=False)    # Full TutorState serialized
    mastery = Column(Float, default=0.0)  # Matches production database column name
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
    metadata_json = Column(Text, nullable=True)  # JSON: objectives, depth, misconceptions, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_curriculum", "country", "board", "grade", "subject", "topic"),
    )


# FTS5 virtual table is created via raw SQL in db.py, not as ORM model
