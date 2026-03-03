"""SQLAlchemy ORM database models."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """User table - stores student profiles linked to Cognito."""
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    cognito_sub = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=True)
    phone = Column(String, unique=True, nullable=True)
    auth_provider = Column(String, nullable=False)  # 'email', 'phone', 'google'
    name = Column(String, nullable=True)
    preferred_name = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    grade = Column(Integer, nullable=True)
    board = Column(String, nullable=True)
    school_name = Column(String, nullable=True)
    about_me = Column(Text, nullable=True)
    text_language_preference = Column(String, nullable=True)
    audio_language_preference = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    onboarding_complete = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    sessions = relationship("Session", back_populates="user")

    __table_args__ = (
        Index("idx_cognito_sub", "cognito_sub"),
        Index("idx_user_email", "email"),
    )


class Session(Base):
    """Session table - stores tutor state per learning session."""
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    student_json = Column(Text, nullable=False)  # JSON: {id, grade, prefs}
    goal_json = Column(Text, nullable=False)     # JSON: {topic, syllabus, learning_objectives}
    state_json = Column(Text, nullable=False)    # Full TutorState serialized
    mastery = Column(Float, default=0.0)  # Matches production database column name
    step_idx = Column(Integer, default=0)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    subject = Column(String, nullable=True)  # Denormalized for history filtering
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    mode = Column(String, default='teach_me')
    is_paused = Column(Boolean, default=False)
    exam_score = Column(Float, nullable=True)
    exam_total = Column(Integer, nullable=True)
    guideline_id = Column(String, nullable=True)
    state_version = Column(Integer, default=1, nullable=False)

    events = relationship("Event", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("idx_session_user_guideline", "user_id", "guideline_id", "mode"),
    )


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

    Hierarchy: Book → Chapter → Topic
    - chapter = chapter-level grouping (e.g., "Fractions")
    - topic = learning unit (e.g., "Comparing Like Denominators")
    """
    __tablename__ = "teaching_guidelines"

    id = Column(String, primary_key=True)
    country = Column(String, nullable=False)  # e.g., "India"
    board = Column(String, nullable=False)    # e.g., "CBSE", "ICSE"
    grade = Column(Integer, nullable=False)   # e.g., 3
    subject = Column(String, nullable=False)  # e.g., "Mathematics"
    chapter = Column(String, nullable=False)  # e.g., "Fractions"
    topic = Column(String, nullable=False)    # e.g., "Comparing Like Denominators"
    guideline = Column(Text, nullable=False)  # Detailed teaching instructions
    metadata_json = Column(Text, nullable=True)  # JSON: objectives, depth, misconceptions, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Hierarchy keys and titles
    chapter_key = Column(String, nullable=True)   # Slugified chapter
    topic_key = Column(String, nullable=True)      # Slugified topic
    chapter_title = Column(String, nullable=True)  # Human-readable chapter
    topic_title = Column(String, nullable=True)    # Human-readable topic
    chapter_summary = Column(Text, nullable=True)  # Chapter-level summary (20-40 words)
    topic_summary = Column(Text, nullable=True)    # Topic-level summary (15-30 words)

    # Pedagogical sequencing fields
    chapter_sequence = Column(Integer, nullable=True)     # Teaching order of chapter within book (1-based)
    topic_sequence = Column(Integer, nullable=True)       # Teaching order of topic within chapter (1-based)
    chapter_storyline = Column(Text, nullable=True)       # Narrative of chapter's teaching progression

    # V1 structured fields (legacy)
    objectives_json = Column(Text, nullable=True)
    examples_json = Column(Text, nullable=True)
    misconceptions_json = Column(Text, nullable=True)
    assessments_json = Column(Text, nullable=True)
    teaching_description = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    evidence_summary = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    # Metadata
    book_id = Column(String, nullable=True)  # Reference to books table
    source_page_start = Column(Integer, nullable=True)
    source_page_end = Column(Integer, nullable=True)
    source_pages = Column(String, nullable=True)
    status = Column(String, nullable=False, default='draft')
    review_status = Column(String, default='TO_BE_REVIEWED')
    generated_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    version = Column(Integer, default=1)

    __table_args__ = (
        Index("idx_curriculum", "country", "board", "grade", "subject", "chapter"),
    )



class StudyPlan(Base):
    """Pre-generated study plans for teaching guidelines (1:1 relationship)."""
    __tablename__ = "study_plans"

    id = Column(String, primary_key=True)
    guideline_id = Column(String, ForeignKey("teaching_guidelines.id", ondelete="CASCADE"),
                          nullable=False, unique=True)

    # The plan JSON (same structure as PLANNER output)
    plan_json = Column(Text, nullable=False)

    # Generation metadata
    generator_model = Column(String, nullable=True)
    reviewer_model = Column(String, nullable=True)
    generation_reasoning = Column(Text, nullable=True)
    reviewer_feedback = Column(Text, nullable=True)
    was_revised = Column(Integer, default=0)  # 0=no, 1=yes

    # Status
    status = Column(String, default='generated')  # generated, approved
    version = Column(Integer, default=1)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_plans_guideline", "guideline_id"),
    )



class Book(Base):
    """
    Book table - stores metadata for uploaded textbooks.
    """
    __tablename__ = "books"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=True)
    edition = Column(String, nullable=True)
    edition_year = Column(Integer, nullable=True)
    country = Column(String, nullable=False)
    board = Column(String, nullable=False)  # e.g., "CBSE"
    grade = Column(Integer, nullable=False)
    subject = Column(String, nullable=False)  # e.g., "Mathematics"
    pipeline_version = Column(Integer, default=1)  # 1=V1, 2=V2

    # S3 storage
    cover_image_s3_key = Column(String, nullable=True)
    s3_prefix = Column(String, nullable=False)  # books/{book_id}/
    metadata_s3_key = Column(String, nullable=True)  # books/{book_id}/metadata.json

    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String, default="admin")

    __table_args__ = (
        Index("idx_books_curriculum", "country", "board", "grade", "subject"),
    )


class LLMConfig(Base):
    """Centralized LLM model configuration per component.

    Single source of truth for which provider+model each component uses.
    Managed via /admin/llm-config UI. No fallbacks — missing config = error.
    """
    __tablename__ = "llm_config"

    component_key = Column(String, primary_key=True)  # e.g. "tutor", "book_ingestion"
    provider = Column(String, nullable=False)           # "openai", "anthropic", "google"
    model_id = Column(String, nullable=False)           # "gpt-5.2", "claude-opus-4-6", etc.
    description = Column(String, nullable=True)         # Human-readable description
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String, nullable=True)


# FTS5 virtual table is created via raw SQL in db.py, not as ORM model
