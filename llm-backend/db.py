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

        # Seed LLM config defaults (only if table is empty)
        _seed_llm_config(db_manager)

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

        if "exam_score" not in existing_columns:
            print("  Adding exam_score column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN exam_score FLOAT"))
            print("  ✓ exam_score column added")

        if "exam_total" not in existing_columns:
            print("  Adding exam_total column to sessions...")
            conn.execute(text("ALTER TABLE sessions ADD COLUMN exam_total INTEGER"))
            print("  ✓ exam_total column added")

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
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_one_paused_per_user_guideline "
            "ON sessions(user_id, guideline_id) WHERE is_paused = TRUE"
        ))

        # Backfill mode for existing sessions
        conn.execute(text("UPDATE sessions SET mode = 'teach_me' WHERE mode IS NULL"))

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
        "topic_sequence": "INTEGER",
        "subtopic_sequence": "INTEGER",
        "topic_storyline": "TEXT",
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

    # 3. Seed book_ingestion_v2 LLM config if missing
    with db_manager.engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM llm_config WHERE component_key = 'book_ingestion_v2'"
        )).fetchone()
        if not exists:
            conn.execute(text(
                "INSERT INTO llm_config (component_key, provider, model_id, description) "
                "VALUES ('book_ingestion_v2', 'openai', 'gpt-5.2', "
                "'Book ingestion V2 pipeline (chunk extraction, consolidation, merge)')"
            ))
            print("  ✓ Seeded book_ingestion_v2 llm_config")
        conn.commit()


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
                    "INSERT INTO llm_config (component_key, provider, model_id, description) "
                    "VALUES (:component_key, :provider, :model_id, :description)"
                ),
                seed,
            )
        conn.commit()
        print(f"  ✓ Seeded {len(_LLM_CONFIG_SEEDS)} llm_config rows")


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
