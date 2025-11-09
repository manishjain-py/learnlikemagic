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
    """
    Teaching guidelines table - stores pedagogical instructions for teaching topics.

    V2 SCHEMA CHANGES (Breaking):
    - KEEP: id, country, board, grade, subject, book_id, created_at, updated_at
    - KEEP: topic_key, topic_title, subtopic_key, subtopic_title
    - KEEP: source_page_start, source_page_end, status, version
    - REMOVE: objectives_json, examples_json, misconceptions_json, assessments_json
    - REMOVE: teaching_description, description, evidence_summary, confidence
    - REMOVE: topic (redundant with topic_title), subtopic (redundant with subtopic_title)
    - REMOVE: metadata_json, source_pages
    - CHANGE: guideline → guidelines (single comprehensive text field)

    Migration: DROP all existing rows, recreate table with V2 schema
    """
    __tablename__ = "teaching_guidelines"

    id = Column(String, primary_key=True)
    country = Column(String, nullable=False)  # e.g., "India"
    board = Column(String, nullable=False)    # e.g., "CBSE", "ICSE"
    grade = Column(Integer, nullable=False)   # e.g., 3
    subject = Column(String, nullable=False)  # e.g., "Mathematics"
    topic = Column(String, nullable=False)    # e.g., "Fractions" [DEPRECATED in V2, use topic_title]
    subtopic = Column(String, nullable=False) # e.g., "Comparing Like Denominators" [DEPRECATED in V2, use subtopic_title]
    guideline = Column(Text, nullable=False)  # Detailed teaching instructions [RENAME to guidelines in V2]
    metadata_json = Column(Text, nullable=True)  # JSON: objectives, depth, misconceptions, etc. [REMOVE in V2]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # Added for V2

    # Phase 6 columns (kept in V2)
    topic_key = Column(String, nullable=True)  # Slugified topic
    subtopic_key = Column(String, nullable=True)  # Slugified subtopic
    topic_title = Column(String, nullable=True)  # Human-readable topic
    subtopic_title = Column(String, nullable=True)  # Human-readable subtopic

    # V1 structured fields (REMOVE in V2 migration)
    objectives_json = Column(Text, nullable=True)  # JSON array [V1 only]
    examples_json = Column(Text, nullable=True)  # JSON array [V1 only]
    misconceptions_json = Column(Text, nullable=True)  # JSON array [V1 only]
    assessments_json = Column(Text, nullable=True)  # JSON array [V1 only]
    teaching_description = Column(Text, nullable=True)  # 3-6 line teaching instructions [V1 only]
    description = Column(Text, nullable=True)  # Comprehensive 200-300 word description [V1 only]
    evidence_summary = Column(Text, nullable=True)  # [V1 only]
    confidence = Column(Float, nullable=True)  # [V1 only]

    # Metadata (kept in V2)
    book_id = Column(String, nullable=True)  # Reference to books table
    source_page_start = Column(Integer, nullable=True)
    source_page_end = Column(Integer, nullable=True)
    source_pages = Column(String, nullable=True)  # JSON array as string [REMOVE in V2]
    status = Column(String, default='draft')
    version = Column(Integer, default=1)

    __table_args__ = (
        Index("idx_curriculum", "country", "board", "grade", "subject", "topic"),
    )


# FTS5 virtual table is created via raw SQL in db.py, not as ORM model
