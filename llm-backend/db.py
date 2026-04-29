"""
Database initialization and migration utilities.
"""
import sys
import argparse
from sqlalchemy import text, inspect
from shared.models.entities import Base
from database import get_db_manager


# Default LLM config rows seeded on first migrate.
# This is the ONLY place defaults exist — no fallbacks anywhere else.
_LLM_CONFIG_SEEDS = [
    {
        "component_key": "tutor",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Main tutoring pipeline (safety + master tutor + welcome)",
    },
    {
        "component_key": "study_plan_generator",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Study plan creation from teaching guidelines",
    },
    {
        "component_key": "study_plan_reviewer",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Study plan review and improvement",
    },
    {
        "component_key": "eval_evaluator",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Evaluation judge (scores tutor quality)",
    },
    {
        "component_key": "eval_simulator",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Student simulator for evaluations",
    },
    {
        "component_key": "book_ingestion_v2",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Book ingestion V2 pipeline (chunk extraction, consolidation, merge)",
    },
    {
        "component_key": "personality_derivation",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Kid personality derivation from enrichment profile",
    },
    {
        "component_key": "explanation_generator",
        "provider": "openai",
        "model_id": "gpt-5.2",
        "description": "Pre-computed explanation generation for topics",
    },
    {
        "component_key": "fast_model",
        "provider": "openai",
        "model_id": "gpt-4o-mini",
        "description": "Lightweight model for safety checks, translation, and other fast tasks",
    },
    {
        "component_key": "check_in_enrichment",
        "provider": "claude_code",
        "model_id": "claude-opus-4-7",
        "description": "Check-in card generation (match-the-pairs activities for explanation cards)",
    },
    {
        "component_key": "practice_bank_generator",
        "provider": "claude_code",
        "model_id": "claude-opus-4-7",
        "description": "Practice question bank generation + correctness review",
    },
    {
        "component_key": "practice_grader",
        "provider": "openai",
        "model_id": "gpt-4o-mini",
        "description": "Practice free-form grading + per-pick wrong-answer rationale",
    },
    {
        "component_key": "baatcheet_dialogue_generator",
        "provider": "claude_code",
        "model_id": "claude-opus-4-7",
        "description": "Stage 5b — conversational Baatcheet dialogue generation (Mr. Verma + Meera)",
    },
]


def migrate():
    """Create all database tables and apply schema migrations."""
    print("Creating database tables...")
    db_manager = get_db_manager()

    try:
        # Create all tables defined in models (creates new tables like 'users')
        Base.metadata.create_all(bind=db_manager.engine)
        print("✓ Tables created")

        # Apply column additions to existing tables
        # (create_all only creates NEW tables, it won't add columns to existing ones)
        _apply_session_columns(db_manager)
        _apply_learning_modes_columns(db_manager)
        _apply_user_language_columns(db_manager)
        _apply_user_preferred_name_column(db_manager)
        _apply_sequencing_columns(db_manager)
        _apply_v2_tables(db_manager)
        _rename_topic_subtopic_columns(db_manager)

        # Drop V1 tables and unused V1 columns
        _drop_v1_tables(db_manager)
        _drop_v1_guideline_columns(db_manager)

        # Remove V1 LLM config entry if it exists
        _remove_v1_llm_config(db_manager)

        # Kid enrichment & personality tables + LLM config seed
        _apply_kid_enrichment_tables(db_manager)

        # Drop unused enrichment columns (simplified from 9 to 4 sections)
        _drop_unused_enrichment_columns(db_manager)

        # Add user_id to study_plans for per-student personalized plans
        _apply_study_plan_user_column(db_manager)

        # Add focus_mode column to users
        _apply_focus_mode_column(db_manager)

        # Session feedback table (created by create_all, this is a no-op placeholder)
        _apply_session_feedback_table(db_manager)

        # Topic planning columns for quality improvement
        _apply_topic_planning_columns(db_manager)

        # Topic explanations table (created by create_all, verify + seed LLM config)
        _apply_topic_explanations_table(db_manager)

        # Baatcheet — topic_dialogues table + sessions.teach_me_mode column
        _apply_topic_dialogues_table(db_manager)
        _apply_sessions_teach_me_mode_column(db_manager)

        # Issues table (created by create_all, seed LLM config)
        _apply_issues_table(db_manager)

        # Rebuild paused-session unique index to include mode (teach_me + practice can both be paused)
        _apply_practice_mode_support(db_manager)

        # Topic Pipeline Dashboard — guideline_id + split active-job indexes
        _apply_chapter_jobs_guideline_id(db_manager)

        # Topic Pipeline DAG (Phase 2) — per-stage durable state
        _apply_topic_stage_runs_table(db_manager)

        # Topic Pipeline DAG (Phase 6) — durable hash store for cross-DAG warning
        _apply_topic_content_hashes_table(db_manager)

        # Practice v2 tables (create_all handles base tables; this adds the partial
        # unique index + seeds practice_bank_generator / practice_grader LLM configs)
        _apply_practice_tables(db_manager)

        # Destructive cleanup: drop legacy exam + chat-practice session data and columns
        _cleanup_exam_and_old_practice_data(db_manager)

        # Add reasoning_effort column to llm_config (idempotent)
        _apply_llm_config_reasoning_effort_column(db_manager)

        # Seed LLM config defaults (only if table is empty)
        _seed_llm_config(db_manager)

        # Seed feature flags
        _seed_feature_flags(db_manager)

        with db_manager.engine.connect() as conn:
            conn.commit()

    except Exception as e:
        print(f"Error during migration: {e}")
        raise


def _apply_session_columns(db_manager):
    """Add user_id and subject columns to sessions table if they don't exist."""
    inspector = inspect(db_manager.engine)
    existing_columns = {col["name"] for col in inspector.get_columns("sessions")}

    with db_manager.engine.connect() as conn:
        if "user_id" not in existing_columns:
            print("  Adding user_id column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN user_id VARCHAR REFERENCES users(id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"))
            print("  ✓ user_id column added")

        if "subject" not in existing_columns:
            print("  Adding subject column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN subject VARCHAR"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_subject ON sessions(subject)"))
            print("  ✓ subject column added")

        conn.commit()


def _apply_learning_modes_columns(db_manager):
    """Add learning-modes columns to sessions table if they don't exist."""
    inspector = inspect(db_manager.engine)
    existing_columns = {col["name"] for col in inspector.get_columns("sessions")}

    with db_manager.engine.connect() as conn:
        if "mode" not in existing_columns:
            print("  Adding mode column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN mode VARCHAR DEFAULT 'teach_me'"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode)"))
            print("  ✓ mode column added")

        if "is_paused" not in existing_columns:
            print("  Adding is_paused column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN is_paused BOOLEAN DEFAULT FALSE"))
            print("  ✓ is_paused column added")

        if "guideline_id" not in existing_columns:
            print("  Adding guideline_id column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN guideline_id VARCHAR"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_guideline_id ON sessions(guideline_id)"))
            print("  ✓ guideline_id column added")

        if "state_version" not in existing_columns:
            print("  Adding state_version column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN state_version INTEGER DEFAULT 1 NOT NULL"))
            print("  ✓ state_version column added")

        # Partial unique index: only one paused session per user+guideline
        # NOTE: This is the legacy (user_id, guideline_id) variant. The mode-aware
        # rebuild happens in _apply_practice_mode_support() so that paused Teach Me
        # and paused Practice sessions for the same topic don't collide.
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_one_paused_per_user_guideline "
            "ON sessions(user_id, guideline_id) WHERE is_paused = TRUE"
        ))

        # Backfill mode for existing sessions
        conn.execute(text("UPDATE sessions SET mode = 'teach_me' WHERE mode IS NULL"))

        conn.commit()


def _apply_chapter_jobs_guideline_id(db_manager):
    """Add guideline_id column + split active-job unique indexes on chapter_processing_jobs.

    The column was previously overloaded: post-sync jobs stored `guideline_id`
    in the `chapter_id` column. This migration adds a native `guideline_id`
    column, backfills it for recoverable historical rows, and splits
    `idx_chapter_active_job` into two partial unique indexes:
      - chapter-level: `(chapter_id)` WHERE status IN (pending, running) AND guideline_id IS NULL
      - topic-level:   `(chapter_id, guideline_id)` WHERE ... AND guideline_id IS NOT NULL

    Idempotent. Historical rows' `chapter_id` is NOT rewritten — the
    recovery join is brittle and historical jobs are terminal.
    """
    inspector = inspect(db_manager.engine)

    if "chapter_processing_jobs" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("chapter_processing_jobs")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("chapter_processing_jobs")}

    with db_manager.engine.connect() as conn:
        # 1. Add guideline_id column
        if "guideline_id" not in existing_columns:
            print("  Adding guideline_id column to chapter_processing_jobs...")
            conn.execute(text(
                "ALTER TABLE chapter_processing_jobs ADD COLUMN guideline_id VARCHAR"
            ))
            print("  ✓ guideline_id column added")

        # 2. Backfill guideline_id for historical post-sync rows.
        #    For those rows, chapter_id overloaded stored a guideline UUID. We
        #    copy it to guideline_id iff that value resolves to a
        #    teaching_guidelines.id. The Baatcheet types were added to the
        #    set in Phase 2 — historical rows for those stages also stored
        #    guideline_id-in-chapter_id, so they need the same backfill.
        post_sync_types = (
            "'v2_explanation_generation', 'v2_visual_enrichment', "
            "'v2_check_in_enrichment', 'v2_practice_bank_generation', "
            "'v2_audio_text_review', 'v2_audio_generation', "
            "'v2_baatcheet_dialogue_generation', 'v2_baatcheet_visual_enrichment', "
            "'v2_baatcheet_audio_review'"
        )
        backfill_sql = (
            "UPDATE chapter_processing_jobs SET guideline_id = chapter_id "
            f"WHERE job_type IN ({post_sync_types}) "
            "AND guideline_id IS NULL "
            "AND EXISTS (SELECT 1 FROM teaching_guidelines tg "
            "            WHERE tg.id = chapter_processing_jobs.chapter_id)"
        )
        result = conn.execute(text(backfill_sql))
        if result.rowcount:
            print(f"  Backfilled guideline_id for {result.rowcount} historical post-sync rows")

        # 3. Replace single active-job index with two partial unique indexes.
        if "idx_chapter_active_job" in existing_indexes:
            print("  Dropping legacy idx_chapter_active_job...")
            conn.execute(text("DROP INDEX IF EXISTS idx_chapter_active_job"))

        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_active_chapter_job "
            "ON chapter_processing_jobs (chapter_id) "
            "WHERE status IN ('pending', 'running') AND guideline_id IS NULL"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_active_topic_job "
            "ON chapter_processing_jobs (chapter_id, guideline_id) "
            "WHERE status IN ('pending', 'running') AND guideline_id IS NOT NULL"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chapter_jobs_guideline "
            "ON chapter_processing_jobs (guideline_id)"
        ))
        conn.commit()
        print("  ✓ chapter_processing_jobs guideline_id migration applied")


def _apply_topic_stage_runs_table(db_manager):
    """Phase 2 — verify topic_stage_runs table + ensure partial index on is_stale.

    The table itself is created by `Base.metadata.create_all()` (the ORM
    model is in `book_ingestion_v2/models/database.py`). The partial index
    `WHERE is_stale = TRUE` is portable across Postgres and SQLite via the
    Index dialect kwargs, so create_all emits it on a fresh DB. This helper
    re-issues the CREATE for existing deployments where the index may be
    missing. Idempotent.
    """
    inspector = inspect(db_manager.engine)
    if "topic_stage_runs" not in inspector.get_table_names():
        print("  ⚠ topic_stage_runs table not found — will be created by create_all()")
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("topic_stage_runs")}

    with db_manager.engine.connect() as conn:
        if "idx_topic_stage_runs_state" not in existing_indexes:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_topic_stage_runs_state "
                "ON topic_stage_runs (state)"
            ))
        if "idx_topic_stage_runs_is_stale" not in existing_indexes:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_topic_stage_runs_is_stale "
                "ON topic_stage_runs (is_stale) WHERE is_stale = TRUE"
            ))
        conn.commit()
    print("  ✓ topic_stage_runs table + indexes verified")


def _apply_topic_content_hashes_table(db_manager):
    """Phase 6 — create `topic_content_hashes` + drop the earlier
    `teaching_guidelines.explanations_input_hash` column.

    The column was an earlier (broken) design that keyed the hash on
    `guideline_id` — but `topic_sync` deletes-and-recreates guidelines
    on every chapter resync, so the hash never survived a sync. The new
    table is keyed on the stable curriculum tuple
    `(book_id, chapter_key, topic_key)`.

    Idempotent — drops the column only if present, creates the table
    via `Base.metadata.create_all` (handled by the V2 import block).
    """
    inspector = inspect(db_manager.engine)
    if "teaching_guidelines" not in inspector.get_table_names():
        return

    existing_columns = {
        col["name"] for col in inspector.get_columns("teaching_guidelines")
    }
    with db_manager.engine.connect() as conn:
        if "explanations_input_hash" in existing_columns:
            print("  Dropping legacy explanations_input_hash column from teaching_guidelines...")
            conn.execute(text(
                "ALTER TABLE teaching_guidelines "
                "DROP COLUMN explanations_input_hash"
            ))
            conn.commit()
            print("  ✓ explanations_input_hash column dropped")

    if "topic_content_hashes" in inspector.get_table_names():
        print("  ✓ topic_content_hashes table verified")
    else:
        # `Base.metadata.create_all` in `migrate()` already creates new V2
        # tables; this branch reports the post-create state for clarity.
        print("  ⚠ topic_content_hashes table not found — will be created by create_all()")


def _apply_practice_mode_support(db_manager):
    """Rebuild the paused-session unique index to include mode (+ teach_me_mode).

    Index includes:
    - mode (teach_me, clarify_doubts, practice…) so paused Teach Me + paused
      Practice can coexist for the same (user, topic).
    - teach_me_mode (explain, baatcheet) when the column exists, so paused
      Baatcheet + paused Explain can coexist for the same (user, topic) —
      PRD §FR-4.

    Defensive against migration ordering: detects the column before including
    it. Falls back to the legacy 3-col shape when teach_me_mode hasn't been
    added yet. Idempotent.
    """
    inspector = inspect(db_manager.engine)
    if "sessions" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("sessions")}
    has_teach_me_mode = "teach_me_mode" in cols

    with db_manager.engine.connect() as conn:
        print("  Rebuilding paused-session unique index...")
        conn.execute(text(
            "DROP INDEX IF EXISTS idx_sessions_one_paused_per_user_guideline"
        ))
        if has_teach_me_mode:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_one_paused_per_user_guideline "
                "ON sessions(user_id, guideline_id, mode, teach_me_mode) WHERE is_paused = TRUE"
            ))
            print("  ✓ paused-session unique index includes mode + teach_me_mode")
        else:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_one_paused_per_user_guideline "
                "ON sessions(user_id, guideline_id, mode) WHERE is_paused = TRUE"
            ))
            print("  ✓ paused-session unique index includes mode (legacy 3-col)")
        conn.commit()


def _apply_user_language_columns(db_manager):
    """Add language preference columns to users table if they don't exist."""
    inspector = inspect(db_manager.engine)
    existing_columns = {col["name"] for col in inspector.get_columns("users")}

    with db_manager.engine.connect() as conn:
        if "text_language_preference" not in existing_columns:
            print("  Adding text_language_preference column to users...")
            conn.execute(text("ALTER TABLE users ADD COLUMN text_language_preference VARCHAR"))
            print("  ✓ text_language_preference column added")

        if "audio_language_preference" not in existing_columns:
            print("  Adding audio_language_preference column to users...")
            conn.execute(text("ALTER TABLE users ADD COLUMN audio_language_preference VARCHAR"))
            print("  ✓ audio_language_preference column added")

        conn.commit()


def _apply_user_preferred_name_column(db_manager):
    """Add preferred_name column to users table if it doesn't exist."""
    inspector = inspect(db_manager.engine)
    existing_columns = {col["name"] for col in inspector.get_columns("users")}

    with db_manager.engine.connect() as conn:
        if "preferred_name" not in existing_columns:
            print("  Adding preferred_name column to users...")
            conn.execute(text("ALTER TABLE users ADD COLUMN preferred_name VARCHAR"))
            print("  ✓ preferred_name column added")

        conn.commit()


def _apply_sequencing_columns(db_manager):
    """Add pedagogical sequencing columns to teaching_guidelines if they don't exist."""
    inspector = inspect(db_manager.engine)

    if "teaching_guidelines" not in inspector.get_table_names():
        return  # Table doesn't exist yet, create_all will handle it

    existing_columns = {col["name"] for col in inspector.get_columns("teaching_guidelines")}

    new_columns = {
        "chapter_sequence": "INTEGER",
        "topic_sequence": "INTEGER",
        "chapter_storyline": "TEXT",
    }

    with db_manager.engine.connect() as conn:
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                print(f"  Adding {col_name} column to teaching_guidelines...")
                conn.execute(text(f"ALTER TABLE teaching_guidelines ADD COLUMN {col_name} {col_type}"))
                print(f"  ✓ {col_name} column added")

        conn.commit()
        print("  ✓ sequencing columns applied")


def _apply_v2_tables(db_manager):
    """Add pipeline_version column to books and create V2 tables."""
    inspector = inspect(db_manager.engine)

    # 1. Add pipeline_version column to books table
    existing_columns = {col["name"] for col in inspector.get_columns("books")}
    with db_manager.engine.connect() as conn:
        if "pipeline_version" not in existing_columns:
            print("  Adding pipeline_version column to books...")
            conn.execute(text(
                "ALTER TABLE books ADD COLUMN pipeline_version INTEGER DEFAULT 1"
            ))
            print("  ✓ pipeline_version column added")
        conn.commit()

    # 2. Create V2 tables (create_all handles IF NOT EXISTS)
    # Import V2 models so they register with Base.metadata
    import book_ingestion_v2.models.database  # noqa: F401
    Base.metadata.create_all(bind=db_manager.engine)
    print("  ✓ V2 tables created")

    # 3. Add unique constraints to V2 tables (idempotent for existing DBs)
    #    Deduplicates existing rows before adding each constraint to avoid
    #    migration failures on DBs that accumulated duplicates pre-constraint.
    _v2_unique_constraints = [
        ("book_chapters", "uq_book_chapters_book_number", "book_id, chapter_number"),
        ("chapter_pages", "uq_chapter_pages_chapter_page", "chapter_id, page_number"),
        ("chapter_topics", "uq_chapter_topics_chapter_key", "chapter_id, topic_key"),
    ]
    existing_tables = inspector.get_table_names()
    with db_manager.engine.connect() as conn:
        for table, constraint_name, columns in _v2_unique_constraints:
            if table not in existing_tables:
                continue
            existing_constraints = {
                c["name"] for c in inspector.get_unique_constraints(table)
            }
            if constraint_name not in existing_constraints:
                # Remove duplicates: keep the row with the latest created_at
                dedup_sql = (
                    f"DELETE FROM {table} WHERE id NOT IN ("
                    f"  SELECT DISTINCT ON ({columns}) id FROM {table}"
                    f"  ORDER BY {columns}, created_at DESC"
                    f")"
                )
                result = conn.execute(text(dedup_sql))
                if result.rowcount:
                    print(f"  Removed {result.rowcount} duplicate rows from {table}")
                print(f"  Adding unique constraint {constraint_name} on {table}...")
                conn.execute(text(
                    f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} UNIQUE ({columns})"
                ))
        conn.commit()
    print("  ✓ V2 unique constraints applied")

    # 4. Seed book_ingestion_v2 LLM config if missing
    with db_manager.engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM llm_config WHERE component_key = 'book_ingestion_v2'"
        )).fetchone()
        if not exists:
            conn.execute(text(
                "INSERT INTO llm_config "
                "(component_key, provider, model_id, description, reasoning_effort) "
                "VALUES ('book_ingestion_v2', 'openai', 'gpt-5.2', "
                "'Book ingestion V2 pipeline (chunk extraction, consolidation, merge)', "
                "'max')"
            ))
            print("  ✓ Seeded book_ingestion_v2 llm_config")
        conn.commit()


def _rename_topic_subtopic_columns(db_manager):
    """Rename topic/subtopic columns to chapter/topic in teaching_guidelines.

    Aligns V1 naming (topic→subtopic) with V2 hierarchy (chapter→topic).
    Each rename is idempotent: skipped if the old column no longer exists.
    Order matters — rename topic_* first to free the name, then subtopic_*.
    """
    inspector = inspect(db_manager.engine)

    if "teaching_guidelines" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("teaching_guidelines")}

    renames = [
        # Step 1-6: topic_* → chapter_*
        ("topic", "chapter"),
        ("topic_key", "chapter_key"),
        ("topic_title", "chapter_title"),
        ("topic_summary", "chapter_summary"),
        ("topic_sequence", "chapter_sequence"),
        ("topic_storyline", "chapter_storyline"),
        # Step 7-11: subtopic_* → topic_*
        ("subtopic", "topic"),
        ("subtopic_key", "topic_key"),
        ("subtopic_title", "topic_title"),
        ("subtopic_summary", "topic_summary"),
        ("subtopic_sequence", "topic_sequence"),
    ]

    with db_manager.engine.connect() as conn:
        applied = 0
        for old_col, new_col in renames:
            if old_col in existing and new_col not in existing:
                print(f"  Renaming teaching_guidelines.{old_col} → {new_col}...")
                conn.execute(text(
                    f"ALTER TABLE teaching_guidelines RENAME COLUMN {old_col} TO {new_col}"
                ))
                existing.discard(old_col)
                existing.add(new_col)
                applied += 1
        conn.commit()

    if applied:
        print(f"  ✓ Renamed {applied} columns in teaching_guidelines")
    else:
        print("  ✓ teaching_guidelines columns already renamed")


def _drop_v1_tables(db_manager):
    """Drop V1 pipeline tables (book_guidelines, book_jobs) if they exist."""
    inspector = inspect(db_manager.engine)
    existing_tables = inspector.get_table_names()

    v1_tables = ["book_guidelines", "book_jobs"]
    with db_manager.engine.connect() as conn:
        for table in v1_tables:
            if table in existing_tables:
                print(f"  Dropping V1 table {table}...")
                conn.execute(text(f"DROP TABLE {table} CASCADE"))
                print(f"  ✓ {table} dropped")
        conn.commit()


def _drop_v1_guideline_columns(db_manager):
    """Drop unused V1 structured-field columns from teaching_guidelines.

    Removes: objectives_json, examples_json, misconceptions_json,
             assessments_json, evidence_summary, confidence.
    Keeps columns still used by V2 pipeline: teaching_description, description,
    source_page_start, source_page_end, source_pages, book_id.
    """
    inspector = inspect(db_manager.engine)

    if "teaching_guidelines" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("teaching_guidelines")}

    v1_columns = [
        "objectives_json",
        "examples_json",
        "misconceptions_json",
        "assessments_json",
        "evidence_summary",
        "confidence",
    ]

    with db_manager.engine.connect() as conn:
        dropped = 0
        for col in v1_columns:
            if col in existing:
                print(f"  Dropping teaching_guidelines.{col}...")
                conn.execute(text(f"ALTER TABLE teaching_guidelines DROP COLUMN {col}"))
                dropped += 1
        conn.commit()

    if dropped:
        print(f"  ✓ Dropped {dropped} unused V1 columns from teaching_guidelines")
    else:
        print("  ✓ V1 columns already removed from teaching_guidelines")


def _remove_v1_llm_config(db_manager):
    """Remove the V1 'book_ingestion' LLM config entry if it exists.

    The V1 pipeline is gone; only 'book_ingestion_v2' should remain.
    This is safe because no code references the old key.
    """
    with db_manager.engine.connect() as conn:
        result = conn.execute(text(
            "DELETE FROM llm_config WHERE component_key = 'book_ingestion'"
        ))
        if result.rowcount:
            print("  ✓ Removed V1 'book_ingestion' LLM config entry")
        conn.commit()


def _apply_kid_enrichment_tables(db_manager):
    """Create kid_enrichment_profiles and kid_personalities tables + seed LLM config.

    Tables are created by Base.metadata.create_all() (the ORM models are in entities.py).
    This function handles the LLM config seed for existing deployments where
    _LLM_CONFIG_SEEDS won't run (it only seeds when the table is empty).
    """
    with db_manager.engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM llm_config WHERE component_key = 'personality_derivation'"
        )).fetchone()
        if not exists:
            # Copy provider/model from the tutor config
            tutor_row = conn.execute(text(
                "SELECT provider, model_id FROM llm_config WHERE component_key = 'tutor'"
            )).fetchone()
            if tutor_row:
                conn.execute(text(
                    "INSERT INTO llm_config "
                    "(component_key, provider, model_id, description, reasoning_effort) "
                    "VALUES ('personality_derivation', :provider, :model_id, "
                    "'Kid personality derivation from enrichment profile', 'max')"
                ), {"provider": tutor_row[0], "model_id": tutor_row[1]})
                print("  ✓ Seeded personality_derivation LLM config (copied from tutor)")
        conn.commit()


def _drop_unused_enrichment_columns(db_manager):
    """Drop columns removed when enrichment was simplified from 9 to 4 sections."""
    columns_to_drop = [
        "my_world", "strengths", "personality_traits",
        "favorite_media", "favorite_characters", "memorable_experience", "aspiration",
    ]
    inspector = inspect(db_manager.engine)
    if "kid_enrichment_profiles" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("kid_enrichment_profiles")}
    with db_manager.engine.connect() as conn:
        for col in columns_to_drop:
            if col in existing:
                conn.execute(text(f"ALTER TABLE kid_enrichment_profiles DROP COLUMN {col}"))
                print(f"  ✓ Dropped kid_enrichment_profiles.{col}")
        conn.commit()


def _apply_study_plan_user_column(db_manager):
    """Add user_id column to study_plans for per-student personalized plans."""
    inspector = inspect(db_manager.engine)

    if "study_plans" not in inspector.get_table_names():
        return  # Table doesn't exist yet, create_all will handle it

    existing_columns = {col["name"] for col in inspector.get_columns("study_plans")}

    with db_manager.engine.connect() as conn:
        if "user_id" not in existing_columns:
            print("  Adding user_id column to study_plans...")
            conn.execute(text(
                "ALTER TABLE study_plans ADD COLUMN user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE"
            ))
            print("  ✓ user_id column added")

        # Drop old unique constraint on guideline_id (if exists)
        existing_unique = {c["name"] for c in inspector.get_unique_constraints("study_plans")}
        # Also check indexes that enforce uniqueness
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("study_plans")}
        for name in list(existing_unique | existing_indexes):
            # The old ORM-generated unique constraint name varies by DB
            if name and "guideline_id" in name and "user" not in name:
                try:
                    conn.execute(text(f"ALTER TABLE study_plans DROP CONSTRAINT IF EXISTS {name}"))
                except Exception:
                    try:
                        conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
                    except Exception:
                        pass

        # Create composite unique index (idempotent)
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_study_plans_user_guideline "
            "ON study_plans(user_id, guideline_id)"
        ))
        print("  ✓ study_plans user_id migration complete")

        conn.commit()


def _apply_focus_mode_column(db_manager):
    """Add focus_mode column to users table if it doesn't exist."""
    inspector = inspect(db_manager.engine)
    existing_columns = {col["name"] for col in inspector.get_columns("users")}

    with db_manager.engine.connect() as conn:
        if "focus_mode" not in existing_columns:
            print("  Adding focus_mode column to users...")
            conn.execute(text("ALTER TABLE users ADD COLUMN focus_mode BOOLEAN DEFAULT TRUE NOT NULL"))
            print("  ✓ focus_mode column added")
        else:
            # Flip existing users who never changed it to the new default (true)
            conn.execute(text("UPDATE users SET focus_mode = TRUE WHERE focus_mode = FALSE"))

        conn.commit()


def _apply_session_feedback_table(db_manager):
    """Ensure session_feedback table exists (created by Base.metadata.create_all)."""
    inspector = inspect(db_manager.engine)
    if "session_feedback" in inspector.get_table_names():
        print("  ✓ session_feedback table already exists")
    else:
        print("  ✓ session_feedback table created")


def _apply_topic_planning_columns(db_manager):
    """Add topic planning columns for chapter-to-topic quality improvement."""
    inspector = inspect(db_manager.engine)
    existing_tables = inspector.get_table_names()

    with db_manager.engine.connect() as conn:
        # chapter_processing_jobs.planned_topics_json
        if "chapter_processing_jobs" in existing_tables:
            existing = {col["name"] for col in inspector.get_columns("chapter_processing_jobs")}
            if "planned_topics_json" not in existing:
                print("  Adding planned_topics_json column to chapter_processing_jobs...")
                conn.execute(text("ALTER TABLE chapter_processing_jobs ADD COLUMN planned_topics_json TEXT"))
                print("  ✓ planned_topics_json column added")

        # chapter_topics.prior_topics_context, chapter_topics.topic_assignment
        if "chapter_topics" in existing_tables:
            existing = {col["name"] for col in inspector.get_columns("chapter_topics")}
            if "prior_topics_context" not in existing:
                print("  Adding prior_topics_context column to chapter_topics...")
                conn.execute(text("ALTER TABLE chapter_topics ADD COLUMN prior_topics_context TEXT"))
                print("  ✓ prior_topics_context column added")
            if "topic_assignment" not in existing:
                print("  Adding topic_assignment column to chapter_topics...")
                conn.execute(text("ALTER TABLE chapter_topics ADD COLUMN topic_assignment VARCHAR"))
                print("  ✓ topic_assignment column added")

        # teaching_guidelines.prior_topics_context
        if "teaching_guidelines" in existing_tables:
            existing = {col["name"] for col in inspector.get_columns("teaching_guidelines")}
            if "prior_topics_context" not in existing:
                print("  Adding prior_topics_context column to teaching_guidelines...")
                conn.execute(text("ALTER TABLE teaching_guidelines ADD COLUMN prior_topics_context TEXT"))
                print("  ✓ prior_topics_context column added")

        conn.commit()
    print("  ✓ topic planning columns applied")


def _apply_topic_explanations_table(db_manager):
    """Verify topic_explanations table exists (created by Base.metadata.create_all()).

    The UniqueConstraint on (guideline_id, variant_key) is defined in the entity
    and created by create_all(). This function only logs verification — no separate
    index creation to avoid duplicate constraint/index issues.

    Also ensures the explanation_generator LLM config exists for existing deployments
    where _seed_llm_config() won't run (it only seeds when the table is empty).
    """
    inspector = inspect(db_manager.engine)
    if "topic_explanations" in inspector.get_table_names():
        print("  ✓ topic_explanations table exists")
    else:
        print("  ⚠ topic_explanations table not found — will be created by create_all()")

    _ensure_llm_config(
        db_manager,
        component_key="explanation_generator",
        provider="openai",
        model_id="gpt-5.2",
        description="Pre-computed explanation generation for topics",
    )
    _ensure_llm_config(
        db_manager,
        component_key="check_in_enrichment",
        provider="claude_code",
        model_id="claude-opus-4-7",
        description="Check-in card generation (match-the-pairs activities for explanation cards)",
    )


def _apply_topic_dialogues_table(db_manager):
    """Verify topic_dialogues table exists (created by Base.metadata.create_all).

    Ensures the unique-on-guideline_id index exists for the unique=True
    column on the ORM model — Postgres normally creates the index for a
    column-level UNIQUE constraint, but on existing deployments where the
    table predated the constraint we make the index idempotent here.
    Also seeds the baatcheet_dialogue_generator LLM config.
    """
    inspector = inspect(db_manager.engine)
    if "topic_dialogues" not in inspector.get_table_names():
        print("  ⚠ topic_dialogues table not found — will be created by create_all()")
    else:
        print("  ✓ topic_dialogues table exists")
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("topic_dialogues")}
        existing_columns = {col["name"] for col in inspector.get_columns("topic_dialogues")}
        with db_manager.engine.connect() as conn:
            if "idx_topic_dialogues_guideline" not in existing_indexes:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_dialogues_guideline "
                    "ON topic_dialogues(guideline_id)"
                ))
            # V2 designed-lesson plan column. Idempotent ALTER for deployments
            # that pre-date the V2 plan stage.
            if "plan_json" not in existing_columns:
                print("  Adding plan_json column to topic_dialogues...")
                conn.execute(text(
                    "ALTER TABLE topic_dialogues ADD COLUMN plan_json JSONB"
                ))
                print("  ✓ plan_json column added")
            conn.commit()

    _ensure_llm_config(
        db_manager,
        component_key="baatcheet_dialogue_generator",
        provider="claude_code",
        model_id="claude-opus-4-7",
        description="Stage 5b — conversational Baatcheet dialogue generation (Mr. Verma + Meera)",
    )


def _apply_sessions_teach_me_mode_column(db_manager):
    """Add `teach_me_mode` column + rebuild paused-session unique index.

    Distinguishes the two Teach Me submodes ("explain" / "baatcheet") within
    `mode == "teach_me"`. Existing rows backfill to "explain". Idempotent.
    The paused-session unique index is rebuilt to include teach_me_mode so
    that a paused Baatcheet and a paused Explain session can coexist for the
    same (user, guideline). A non-unique lookup index supports the resume CTA.
    """
    inspector = inspect(db_manager.engine)
    if "sessions" not in inspector.get_table_names():
        return
    existing_columns = {c["name"] for c in inspector.get_columns("sessions")}

    with db_manager.engine.connect() as conn:
        if "teach_me_mode" not in existing_columns:
            print("  Adding teach_me_mode column to sessions...")
            conn.execute(text(
                "ALTER TABLE sessions ADD COLUMN teach_me_mode VARCHAR DEFAULT 'explain'"
            ))
            conn.execute(text(
                "UPDATE sessions SET teach_me_mode = 'explain' "
                "WHERE mode = 'teach_me' AND teach_me_mode IS NULL"
            ))
            print("  ✓ teach_me_mode column added (existing teach_me rows backfilled)")

        # Always-on backfill from state_json. The column-add step above sets
        # every teach_me row to 'explain' indiscriminately, so any Baatcheet
        # session created before the ORM column was wired (PR #121 first cut)
        # is mis-tagged. This re-derives the value from the embedded session
        # state. Idempotent — only touches rows where the recorded column
        # value disagrees with state_json.
        result = conn.execute(text(
            "UPDATE sessions "
            "SET teach_me_mode = state_json::jsonb->>'teach_me_mode' "
            "WHERE mode = 'teach_me' "
            "  AND state_json::jsonb->>'teach_me_mode' IS NOT NULL "
            "  AND state_json::jsonb->>'teach_me_mode' <> COALESCE(teach_me_mode, '')"
        ))
        if result.rowcount:
            print(f"  ✓ teach_me_mode backfilled from state_json on {result.rowcount} row(s)")

        print("  Rebuilding paused-session unique index to include teach_me_mode...")
        conn.execute(text("DROP INDEX IF EXISTS idx_sessions_one_paused_per_user_guideline"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_one_paused_per_user_guideline "
            "ON sessions(user_id, guideline_id, mode, teach_me_mode) WHERE is_paused = TRUE"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_guideline_teach_mode "
            "ON sessions(user_id, guideline_id, mode, teach_me_mode, updated_at DESC)"
        ))
        conn.commit()
        print("  ✓ paused-session unique index rebuilt with teach_me_mode")


def _ensure_llm_config(db_manager, component_key, provider, model_id, description,
                       reasoning_effort: str = "max"):
    """Insert an LLM config entry if the component_key is missing.

    Unlike _seed_llm_config() which only runs on empty tables, this is idempotent
    and works on existing deployments.
    """
    with db_manager.engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM llm_config WHERE component_key = :key"
        ), {"key": component_key}).fetchone()
        if not exists:
            conn.execute(text(
                "INSERT INTO llm_config "
                "(component_key, provider, model_id, description, reasoning_effort) "
                "VALUES (:key, :provider, :model, :desc, :effort)"
            ), {"key": component_key, "provider": provider, "model": model_id,
                "desc": description, "effort": reasoning_effort})
            conn.commit()
            print(f"  ✓ Seeded {component_key} LLM config")


def _apply_issues_table(db_manager):
    """Verify issues table exists."""
    inspector = inspect(db_manager.engine)
    if "issues" in inspector.get_table_names():
        print("  ✓ issues table exists")
    else:
        print("  ✓ issues table created")


def _apply_practice_tables(db_manager):
    """Practice v2 — additive migration only (Step 1 of lets-practice-v2 impl plan).

    Base.metadata.create_all() already created practice_questions and
    practice_attempts via the ORM models. This function adds the partial
    unique index that SQLAlchemy declarative can't express portably in this
    codebase's pattern, and ensures the practice LLM config rows exist on
    deployments where _seed_llm_config won't re-run (table non-empty).

    Does NOT touch sessions.exam_score / sessions.exam_total — the destructive
    cleanup (DELETE rows + DROP columns) is bundled into Step 12 of the impl
    plan alongside the code removal so runtime never sees a half-state.
    """
    inspector = inspect(db_manager.engine)
    if "practice_attempts" not in inspector.get_table_names():
        return

    with db_manager.engine.connect() as conn:
        print("  Applying practice_attempts partial unique index...")
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_practice_attempts_one_inprogress_per_topic "
            "ON practice_attempts(user_id, guideline_id) WHERE status = 'in_progress'"
        ))
        conn.commit()
        print("  ✓ practice_attempts partial unique index applied")

    _ensure_llm_config(
        db_manager,
        component_key="practice_bank_generator",
        provider="claude_code",
        model_id="claude-opus-4-7",
        description="Practice question bank generation + correctness review",
    )
    _ensure_llm_config(
        db_manager,
        component_key="practice_grader",
        provider="openai",
        model_id="gpt-4o-mini",
        description="Practice free-form grading + per-pick wrong-answer rationale",
    )


def _cleanup_exam_and_old_practice_data(db_manager):
    """Step 12 destructive cleanup — rip out legacy exam + chat-practice data.

    Runs the DELETE + DROP in a single transaction so the runtime never sees a
    half-state where code has shipped without exam/practice handling but rows +
    columns still reference it.

    Idempotent: DROP uses IF EXISTS, DELETE is safe on empty state.
    """
    inspector = inspect(db_manager.engine)
    if "sessions" not in inspector.get_table_names():
        return

    existing_cols = {c["name"] for c in inspector.get_columns("sessions")}
    has_exam_cols = "exam_score" in existing_cols or "exam_total" in existing_cols

    with db_manager.engine.begin() as conn:
        # Events FK-reference sessions with ON DELETE RESTRICT. Clear child rows first.
        events_deleted = conn.execute(text(
            "DELETE FROM events WHERE session_id IN ("
            "SELECT id FROM sessions WHERE mode IN ('exam', 'practice')"
            ")"
        )).rowcount
        if events_deleted:
            print(f"  ✓ Deleted {events_deleted} event row(s) for legacy sessions")

        # session_feedback also FK-references sessions; SET NULL on delete per model.
        # No action needed — PG handles the null-out automatically.

        deleted = conn.execute(
            text("DELETE FROM sessions WHERE mode IN ('exam', 'practice')")
        ).rowcount
        if deleted:
            print(f"  ✓ Deleted {deleted} legacy exam/chat-practice session row(s)")

        if has_exam_cols:
            conn.execute(text("ALTER TABLE sessions DROP COLUMN IF EXISTS exam_score"))
            conn.execute(text("ALTER TABLE sessions DROP COLUMN IF EXISTS exam_total"))
            print("  ✓ Dropped sessions.exam_score + sessions.exam_total columns")


def _apply_llm_config_reasoning_effort_column(db_manager):
    """Add reasoning_effort column to llm_config if missing; backfill to 'max'."""
    inspector = inspect(db_manager.engine)
    if "llm_config" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("llm_config")}
    if "reasoning_effort" in existing:
        return
    with db_manager.engine.connect() as conn:
        print("  Adding reasoning_effort column to llm_config...")
        conn.execute(text(
            "ALTER TABLE llm_config ADD COLUMN reasoning_effort VARCHAR NOT NULL DEFAULT 'max'"
        ))
        conn.commit()
        print("  ✓ reasoning_effort column added (default 'max', existing rows backfilled)")


def _seed_llm_config(db_manager):
    """Seed llm_config table with defaults if empty."""
    with db_manager.engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM llm_config")).scalar()
        if row_count > 0:
            print(f"  llm_config already has {row_count} rows, skipping seed")
            return

        print("  Seeding llm_config defaults...")
        for seed in _LLM_CONFIG_SEEDS:
            conn.execute(
                text(
                    "INSERT INTO llm_config "
                    "(component_key, provider, model_id, description, reasoning_effort) "
                    "VALUES (:component_key, :provider, :model_id, :description, "
                    ":reasoning_effort)"
                ),
                {**seed, "reasoning_effort": seed.get("reasoning_effort", "max")},
            )
        conn.commit()
        print(f"  ✓ Seeded {len(_LLM_CONFIG_SEEDS)} llm_config rows")


_FEATURE_FLAG_SEEDS = [
    {
        "flag_name": "show_visuals_in_tutor_flow",
        "enabled": True,
        "description": "Show Pixi.js visual explanations during tutoring sessions",
    },
]


def _seed_feature_flags(db_manager):
    """Seed feature_flags table with defaults (insert-if-missing per flag)."""
    with db_manager.engine.connect() as conn:
        for seed in _FEATURE_FLAG_SEEDS:
            exists = conn.execute(
                text("SELECT 1 FROM feature_flags WHERE flag_name = :name"),
                {"name": seed["flag_name"]},
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "INSERT INTO feature_flags (flag_name, enabled, description) "
                        "VALUES (:flag_name, :enabled, :description)"
                    ),
                    seed,
                )
                print(f"  ✓ Seeded feature flag: {seed['flag_name']}")
        conn.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Database management CLI")
    parser.add_argument("--migrate", action="store_true", help="Create database tables")

    args = parser.parse_args()

    if args.migrate:
        migrate()
    else:
        print("Usage:")
        print("  python db.py --migrate  # Create tables")
        sys.exit(1)
