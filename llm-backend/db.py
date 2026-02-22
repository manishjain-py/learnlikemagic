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
        "component_key": "book_ingestion",
        "provider": "openai",
        "model_id": "gpt-4o-mini",
        "description": "All book ingestion services (OCR, boundaries, merge, etc.)",
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
        "model_id": "gpt-4o",
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
        "model_id": "gpt-4o",
        "description": "Student simulator for evaluations",
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
