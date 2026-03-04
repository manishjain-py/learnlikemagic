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
                "INSERT INTO llm_config (component_key, provider, model_id, description) "
                "VALUES ('book_ingestion_v2', 'openai', 'gpt-5.2', "
                "'Book ingestion V2 pipeline (chunk extraction, consolidation, merge)')"
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
                    "INSERT INTO llm_config (component_key, provider, model_id, description) "
                    "VALUES ('personality_derivation', :provider, :model_id, "
                    "'Kid personality derivation from enrichment profile')"
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
