"""SQLAlchemy ORM models for Book Ingestion V2."""
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from shared.models.entities import Base


class BookChapter(Base):
    """
    TOC entries and chapter-level state.

    Each chapter corresponds to one admin-defined TOC entry with a page range.
    Status tracks the chapter through the ingestion pipeline.
    """
    __tablename__ = "book_chapters"

    id = Column(String, primary_key=True)
    book_id = Column(String, nullable=False)  # References books.id
    chapter_number = Column(Integer, nullable=False)
    chapter_title = Column(String, nullable=False)
    start_page = Column(Integer, nullable=False)
    end_page = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)  # Supplementary info from TOC (themes, subtopics, etc.)

    # AI-generated (set during finalization)
    display_name = Column(String, nullable=True)
    summary = Column(Text, nullable=True)

    # Status tracking
    status = Column(String, nullable=False, default="toc_defined")

    # Denormalized counts for fast UI display
    total_pages = Column(Integer, nullable=False)
    uploaded_page_count = Column(Integer, nullable=False, default=0)

    # Error state
    error_message = Column(Text, nullable=True)
    error_type = Column(String, nullable=True)  # retryable | terminal | validation

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String, default="admin")

    __table_args__ = (
        UniqueConstraint("book_id", "chapter_number", name="uq_book_chapters_book_number"),
        Index("idx_book_chapters_book", "book_id"),
        Index("idx_book_chapters_status", "book_id", "status"),
    )


class ChapterPage(Base):
    """
    Individual pages within chapters.

    Each page is scoped to a chapter via TOC range. OCR runs inline on upload.
    """
    __tablename__ = "chapter_pages"

    id = Column(String, primary_key=True)
    book_id = Column(String, nullable=False)
    chapter_id = Column(String, nullable=False)  # References book_chapters.id
    page_number = Column(Integer, nullable=False)

    # S3 references
    raw_image_s3_key = Column(String, nullable=True)
    image_s3_key = Column(String, nullable=True)
    text_s3_key = Column(String, nullable=True)

    # OCR tracking
    ocr_status = Column(String, default="pending")
    ocr_error = Column(Text, nullable=True)
    ocr_model = Column(String, nullable=True)

    # Timestamps
    uploaded_at = Column(DateTime, nullable=True)
    ocr_completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chapter_id", "page_number", name="uq_chapter_pages_chapter_page"),
        Index("idx_chapter_pages_chapter", "chapter_id"),
        Index("idx_chapter_pages_ocr", "chapter_id", "ocr_status"),
    )


class ChapterProcessingJob(Base):
    """
    Background job tracking per chapter (chapter-level) or per topic (post-sync).

    Tracks all pipeline jobs with progress, heartbeat for stale detection,
    and LLM audit fields. `guideline_id` is populated for post-sync topic-level
    jobs and NULL for chapter-level jobs (OCR, extraction, finalization,
    refresher). See ChapterJobService.acquire_lock for reader-writer semantics.
    """
    __tablename__ = "chapter_processing_jobs"

    id = Column(String, primary_key=True)
    book_id = Column(String, nullable=False)
    chapter_id = Column(String, nullable=False)  # References book_chapters.id
    guideline_id = Column(String, nullable=True)  # NULL for chapter-level jobs

    # Job definition
    job_type = Column(String, nullable=False)       # v2_topic_extraction | v2_refinalization
    status = Column(String, default="pending")      # pending | running | completed | completed_with_errors | failed

    # Progress
    total_items = Column(Integer, nullable=True)
    completed_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
    current_item = Column(String, nullable=True)
    last_completed_item = Column(String, nullable=True)
    progress_detail = Column(Text, nullable=True)   # JSON

    # Heartbeat (stale detection)
    heartbeat_at = Column(DateTime, nullable=True)

    # LLM audit
    model_provider = Column(String, nullable=True)
    model_id = Column(String, nullable=True)

    # Pipeline stage snapshots (JSON list — intermediate card sets per topic)
    stage_snapshots_json = Column(Text, nullable=True)

    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    planned_topics_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # Chapter-level active job invariant — one active job per chapter where
        # guideline_id is NULL (OCR, extraction, finalization, refresher).
        Index(
            "idx_chapter_active_chapter_job",
            "chapter_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'running') AND guideline_id IS NULL"
            ),
            sqlite_where=text(
                "status IN ('pending', 'running') AND guideline_id IS NULL"
            ),
        ),
        # Topic-level active job invariant — one active job per (chapter, guideline)
        # for post-sync stages (explanations, visuals, check-ins, practice,
        # audio-review, audio-synthesis).
        Index(
            "idx_chapter_active_topic_job",
            "chapter_id",
            "guideline_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'running') AND guideline_id IS NOT NULL"
            ),
            sqlite_where=text(
                "status IN ('pending', 'running') AND guideline_id IS NOT NULL"
            ),
        ),
        Index("idx_chapter_jobs_book", "book_id"),
        Index("idx_chapter_jobs_chapter", "chapter_id"),
        Index("idx_chapter_jobs_guideline", "guideline_id"),
    )


class ChapterChunk(Base):
    """
    Per-chunk processing audit trail.

    Each chunk represents a 3-page window processed by the LLM.
    Captures full input/output for reproducibility and debugging.
    """
    __tablename__ = "chapter_chunks"

    id = Column(String, primary_key=True)
    chapter_id = Column(String, nullable=False)
    processing_job_id = Column(String, nullable=False)

    # Chunk definition
    chunk_index = Column(Integer, nullable=False)
    page_start = Column(Integer, nullable=False)
    page_end = Column(Integer, nullable=False)

    # Input context (captured for reproducibility)
    previous_page_text = Column(Text, nullable=True)
    chapter_summary_before = Column(Text, nullable=True)
    topic_map_before_s3_key = Column(String, nullable=True)

    # LLM output
    raw_llm_response = Column(Text, nullable=True)
    topics_detected_json = Column(Text, nullable=True)
    chapter_summary_after = Column(Text, nullable=True)
    topic_map_after_s3_key = Column(String, nullable=True)

    # Status
    status = Column(String, default="pending")
    error_message = Column(Text, nullable=True)

    # LLM metrics (audit)
    model_provider = Column(String, nullable=True)
    model_id = Column(String, nullable=True)
    prompt_hash = Column(String, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_chunks_chapter", "chapter_id"),
        Index("idx_chunks_job", "processing_job_id"),
    )


class ChapterTopic(Base):
    """
    Extracted topics (final output per chapter).

    Topics progress from draft (during extraction) through consolidated
    and final (after finalization) to approved (after admin review).
    """
    __tablename__ = "chapter_topics"

    id = Column(String, primary_key=True)
    book_id = Column(String, nullable=False)
    chapter_id = Column(String, nullable=False)

    # Topic identification
    topic_key = Column(String, nullable=False)
    topic_title = Column(String, nullable=False)

    # Content
    guidelines = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)

    # Source tracking
    source_page_start = Column(Integer, nullable=True)
    source_page_end = Column(Integer, nullable=True)

    # Sequencing
    sequence_order = Column(Integer, nullable=True)

    # Status
    status = Column(String, default="draft")

    # Version
    version = Column(Integer, default=1)
    prior_topics_context = Column(Text, nullable=True)
    topic_assignment = Column(String, nullable=True)  # "planned" or "unplanned"

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chapter_id", "topic_key", name="uq_chapter_topics_chapter_key"),
        Index("idx_chapter_topics_book", "book_id"),
        Index("idx_chapter_topics_chapter", "chapter_id"),
    )


class TopicStageRun(Base):
    """Latest-only per-stage state for the topic-pipeline DAG (Phase 2).

    One row per `(guideline_id, stage_id)`. Written by the
    `run_in_background_v2` hook on stage entry (`state='running'`) and on
    terminal (`state in ('done','failed')`). Historical runs live in
    `chapter_processing_jobs`; this table is the durable, queryable view
    used by the dashboard + cascade orchestrator.

    `is_stale` is reserved for Phase 3 cascade staleness; defaults to FALSE.
    `content_anchor` snapshots the staleness signal (e.g. parent stage's
    `content_anchor`) at the moment a stage reaches `done`.
    """
    __tablename__ = "topic_stage_runs"

    guideline_id = Column(
        String,
        ForeignKey("teaching_guidelines.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    stage_id = Column(String, primary_key=True, nullable=False)
    state = Column(String, nullable=False, default="pending")
    is_stale = Column(Boolean, nullable=False, default=False)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    last_job_id = Column(
        String,
        ForeignKey("chapter_processing_jobs.id"),
        nullable=True,
    )
    content_anchor = Column(String, nullable=True)
    summary_json = Column(JSONB, nullable=True)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("idx_topic_stage_runs_state", "state"),
        Index(
            "idx_topic_stage_runs_is_stale",
            "is_stale",
            postgresql_where=text("is_stale = TRUE"),
            sqlite_where=text("is_stale = TRUE"),
        ),
    )


class TopicContentHash(Base):
    """Phase 6 — durable content-hash anchor for cross-DAG warnings.

    `teaching_guidelines` rows are deleted-and-recreated by `topic_sync`
    on every chapter resync, so anything keyed on `guideline_id` dies
    with them. This table is keyed on the stable curriculum tuple
    `(book_id, chapter_key, topic_key)` so the hash captured at a
    successful `explanations` run survives that delete-recreate. The
    cross-DAG warning endpoint compares this stored hash to a live one
    computed from the current guideline row to surface a "chapter
    re-extracted" banner.

    No FK to `teaching_guidelines` — the whole point is to outlive that
    row.
    """
    __tablename__ = "topic_content_hashes"

    book_id = Column(String, primary_key=True, nullable=False)
    chapter_key = Column(String, primary_key=True, nullable=False)
    topic_key = Column(String, primary_key=True, nullable=False)

    explanations_input_hash = Column(String(64), nullable=False)
    last_explanations_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
