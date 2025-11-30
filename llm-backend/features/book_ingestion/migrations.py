"""
Database migrations for book ingestion feature.

This script safely creates new tables and extends existing ones.
"""
from sqlalchemy import text, inspect
from database import get_db_manager
from features.book_ingestion.models.database import Book, BookGuideline
from models.database import Base
import logging

logger = logging.getLogger(__name__)


def migrate_book_ingestion():
    """
    Run migrations for book ingestion feature.

    Creates:
    - books table
    - book_guidelines table
    - Adds book_id and source_pages columns to teaching_guidelines (if not exist)
    """
    print("🔄 Running book ingestion migrations...")
    db_manager = get_db_manager()
    engine = db_manager.engine
    inspector = inspect(engine)

    try:
        # Step 1: Create new tables (books, book_guidelines)
        print("  Creating new tables (books, book_guidelines)...")
        # This will only create tables that don't exist
        Base.metadata.create_all(bind=engine, tables=[
            Book.__table__,
            BookGuideline.__table__
        ])
        print("  ✓ New tables created")

        # Step 2: Add columns to teaching_guidelines table
        print("  Extending teaching_guidelines table...")
        with engine.connect() as conn:
            # Check if book_id column exists
            columns = [col['name'] for col in inspector.get_columns('teaching_guidelines')]

            if 'book_id' not in columns:
                print("    Adding book_id column...")
                conn.execute(text("""
                    ALTER TABLE teaching_guidelines
                    ADD COLUMN book_id VARCHAR REFERENCES books(id) ON DELETE SET NULL
                """))
                conn.execute(text("""
                    CREATE INDEX idx_teaching_guidelines_book
                    ON teaching_guidelines(book_id)
                """))
                print("    ✓ book_id column added")
            else:
                print("    ✓ book_id column already exists")

            if 'source_pages' not in columns:
                print("    Adding source_pages column...")
                conn.execute(text("""
                    ALTER TABLE teaching_guidelines
                    ADD COLUMN source_pages VARCHAR
                """))
                print("    ✓ source_pages column added")
            else:
                print("    ✓ source_pages column already exists")

            conn.commit()

        print("✅ Book ingestion migrations completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"Migration error: {e}", exc_info=True)
        raise


def rollback_book_ingestion():
    """
    Rollback book ingestion migrations (for development/testing).

    WARNING: This will delete all book ingestion data!
    """
    print("⚠️  Rolling back book ingestion migrations...")
    print("   This will delete all book ingestion data!")

    response = input("   Are you sure? (yes/no): ")
    if response.lower() != "yes":
        print("   Rollback cancelled")
        return

    db_manager = get_db_manager()
    engine = db_manager.engine

    try:
        with engine.connect() as conn:
            # Drop columns from teaching_guidelines
            print("  Removing columns from teaching_guidelines...")
            conn.execute(text("DROP INDEX IF EXISTS idx_teaching_guidelines_book"))
            conn.execute(text("ALTER TABLE teaching_guidelines DROP COLUMN IF EXISTS source_pages"))
            conn.execute(text("ALTER TABLE teaching_guidelines DROP COLUMN IF EXISTS book_id"))
            print("  ✓ Columns removed")

            # Drop new tables
            print("  Dropping book_guidelines table...")
            conn.execute(text("DROP TABLE IF EXISTS book_guidelines CASCADE"))
            print("  ✓ book_guidelines dropped")

            print("  Dropping books table...")
            conn.execute(text("DROP TABLE IF EXISTS books CASCADE"))
            print("  ✓ books dropped")

            conn.commit()

        print("✅ Rollback completed successfully!")

    except Exception as e:
        print(f"❌ Rollback failed: {e}")
        logger.error(f"Rollback error: {e}", exc_info=True)
        raise


def migrate_phase6_schema():
    """
    Run Phase 6 schema migration for teaching_guidelines table.

    Adds new columns for sharded guideline extraction:
    - topic_key, subtopic_key (slugified identifiers)
    - objectives_json, examples_json, misconceptions_json, assessments_json
    - teaching_description (3-6 line teaching instructions)
    - source_page_start, source_page_end (page range)
    - evidence_summary (rule-based summary)
    - status (open, stable, final, needs_review)
    - confidence (boundary detection confidence)
    - version (shard version for tracking updates)
    """
    print("🔄 Running Phase 6 schema migration...")
    db_manager = get_db_manager()
    engine = db_manager.engine
    inspector = inspect(engine)

    try:
        with engine.connect() as conn:
            # Check existing columns
            columns = [col['name'] for col in inspector.get_columns('teaching_guidelines')]

            # Phase 6 columns to add
            phase6_columns = {
                'topic_key': "VARCHAR NOT NULL DEFAULT 'unknown-topic'",
                'subtopic_key': "VARCHAR NOT NULL DEFAULT 'unknown-subtopic'",
                'topic_title': "VARCHAR",
                'subtopic_title': "VARCHAR",
                'objectives_json': "TEXT",
                'examples_json': "TEXT",
                'misconceptions_json': "TEXT",
                'assessments_json': "TEXT",
                'teaching_description': "TEXT NOT NULL DEFAULT ''",
                'source_page_start': "INTEGER",
                'source_page_end': "INTEGER",
                'evidence_summary': "TEXT",
                'status': "VARCHAR DEFAULT 'final'",
                'confidence': "FLOAT DEFAULT 1.0",
                'version': "INTEGER DEFAULT 1"
            }

            for col_name, col_type in phase6_columns.items():
                if col_name not in columns:
                    print(f"  Adding {col_name} column...")
                    conn.execute(text(f"""
                        ALTER TABLE teaching_guidelines
                        ADD COLUMN {col_name} {col_type}
                    """))
                    print(f"  ✓ {col_name} column added")
                else:
                    print(f"  ✓ {col_name} column already exists")

            # Create indices for faster lookups
            print("  Creating indices...")

            # Index on topic_key + subtopic_key (for lookups)
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_teaching_guidelines_topic_subtopic
                    ON teaching_guidelines(topic_key, subtopic_key)
                """))
                print("  ✓ idx_teaching_guidelines_topic_subtopic created")
            except:
                print("  ✓ idx_teaching_guidelines_topic_subtopic already exists")

            # Index on book_id + topic_key (for book queries)
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_teaching_guidelines_book_topic
                    ON teaching_guidelines(book_id, topic_key)
                """))
                print("  ✓ idx_teaching_guidelines_book_topic created")
            except:
                print("  ✓ idx_teaching_guidelines_book_topic already exists")

            # Index on status (for filtering)
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_teaching_guidelines_status
                    ON teaching_guidelines(status)
                """))
                print("  ✓ idx_teaching_guidelines_status created")
            except:
                print("  ✓ idx_teaching_guidelines_status already exists")

            conn.commit()

        print("✅ Phase 6 schema migration completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"Phase 6 migration error: {e}", exc_info=True)
        raise


def rollback_phase6_schema():
    """
    Rollback Phase 6 schema migration (for development/testing).

    WARNING: This will delete Phase 6 columns from teaching_guidelines!
    """
    print("⚠️  Rolling back Phase 6 schema migration...")
    print("   This will delete Phase 6 columns from teaching_guidelines!")

    response = input("   Are you sure? (yes/no): ")
    if response.lower() != "yes":
        print("   Rollback cancelled")
        return

    db_manager = get_db_manager()
    engine = db_manager.engine

    try:
        with engine.connect() as conn:
            # Drop indices
            print("  Dropping indices...")
            conn.execute(text("DROP INDEX IF EXISTS idx_teaching_guidelines_topic_subtopic"))
            conn.execute(text("DROP INDEX IF EXISTS idx_teaching_guidelines_book_topic"))
            conn.execute(text("DROP INDEX IF EXISTS idx_teaching_guidelines_status"))
            print("  ✓ Indices dropped")

            # Drop Phase 6 columns
            print("  Removing Phase 6 columns from teaching_guidelines...")
            phase6_columns = [
                'topic_key', 'subtopic_key', 'topic_title', 'subtopic_title',
                'objectives_json', 'examples_json', 'misconceptions_json', 'assessments_json',
                'teaching_description', 'source_page_start', 'source_page_end',
                'evidence_summary', 'status', 'confidence', 'version'
            ]

            for col_name in phase6_columns:
                conn.execute(text(f"ALTER TABLE teaching_guidelines DROP COLUMN IF EXISTS {col_name}"))
                print(f"  ✓ {col_name} dropped")

            conn.commit()

        print("✅ Phase 6 rollback completed successfully!")

    except Exception as e:
        print(f"❌ Rollback failed: {e}")
        logger.error(f"Phase 6 rollback error: {e}", exc_info=True)
        raise


def add_description_field():
    """
    Add description field to teaching_guidelines table.

    This migration adds the comprehensive description field (200-300 words)
    that consolidates teaching guidance into a single paragraph.
    """
    print("🔄 Adding description field to teaching_guidelines...")
    db_manager = get_db_manager()
    engine = db_manager.engine
    inspector = inspect(engine)

    try:
        with engine.connect() as conn:
            # Check if description column already exists
            columns = [col['name'] for col in inspector.get_columns('teaching_guidelines')]

            if 'description' not in columns:
                print("  Adding description column...")
                conn.execute(text("""
                    ALTER TABLE teaching_guidelines
                    ADD COLUMN description TEXT DEFAULT NULL
                """))
                print("  ✓ description column added")

                # Add comment for documentation
                conn.execute(text("""
                    COMMENT ON COLUMN teaching_guidelines.description IS
                    'Comprehensive 200-300 word description covering what the topic is, how it is taught, and how it is assessed'
                """))
                print("  ✓ Column comment added")
            else:
                print("  ✓ description column already exists")

            conn.commit()

        print("✅ Description field migration completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"Description field migration error: {e}", exc_info=True)
        raise


def add_updated_at_field():
    """
    Add updated_at field to teaching_guidelines table.

    This migration adds the missing updated_at timestamp column that is
    expected by the SQLAlchemy model but missing from the database.
    """
    print("🔄 Adding updated_at field to teaching_guidelines...")
    db_manager = get_db_manager()
    engine = db_manager.engine
    inspector = inspect(engine)

    try:
        with engine.connect() as conn:
            # Check if updated_at column already exists
            columns = [col['name'] for col in inspector.get_columns('teaching_guidelines')]

            if 'updated_at' not in columns:
                print("  Adding updated_at column...")
                conn.execute(text("""
                    ALTER TABLE teaching_guidelines
                    ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                """))
                print("  ✓ updated_at column added")

                # Set updated_at = created_at for existing records
                print("  Setting updated_at = created_at for existing records...")
                conn.execute(text("""
                    UPDATE teaching_guidelines 
                    SET updated_at = created_at 
                    WHERE updated_at IS NULL
                """))
                print("  ✓ Existing records updated")

                # Add comment for documentation
                conn.execute(text("""
                    COMMENT ON COLUMN teaching_guidelines.updated_at IS
                    'Timestamp when the record was last updated. Auto-updated on changes.'
                """))
                print("  ✓ Column comment added")
            else:
                print("  ✓ updated_at column already exists")

            conn.commit()

        print("✅ Updated_at field migration completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"Updated_at field migration error: {e}", exc_info=True)
        raise


def add_book_guidelines_review_status():
    """
    Add review_status column to book_guidelines table.

    This column tracks the approval status of guidelines:
    - TO_BE_REVIEWED: Default, awaiting admin review
    - APPROVED: Admin has approved the guideline
    """
    print("🔄 Adding review_status column to book_guidelines table...")
    db_manager = get_db_manager()
    engine = db_manager.engine
    inspector = inspect(engine)

    try:
        with engine.connect() as conn:
            # Check if column already exists
            columns = [col['name'] for col in inspector.get_columns('book_guidelines')]

            if 'review_status' not in columns:
                print("  Adding review_status column...")
                conn.execute(text("""
                    ALTER TABLE book_guidelines
                    ADD COLUMN review_status VARCHAR(20) DEFAULT 'TO_BE_REVIEWED' NOT NULL
                """))
                print("  ✓ review_status column added")

                # Create index for efficient filtering
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_book_guidelines_review_status
                    ON book_guidelines(book_id, review_status)
                """))
                print("  ✓ review_status index created")
            else:
                print("  ✓ review_status column already exists")

            conn.commit()

        print("✅ book_guidelines review_status migration completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"book_guidelines review_status migration error: {e}", exc_info=True)
        raise


def remove_book_status_column():
    """
    Remove the status column from the books table.

    This migration removes the book-level status column as part of the
    "Remove Book Status State Machine" proposal. Book status is now
    derived from actual data (page_count, guideline_count, etc.) rather
    than stored as a column.

    See: docs/features/REMOVE_BOOK_STATUS_PROPOSAL.md
    """
    print("🔄 Removing status column from books table...")
    db_manager = get_db_manager()
    engine = db_manager.engine
    inspector = inspect(engine)

    try:
        with engine.connect() as conn:
            # Check if status column exists
            columns = [col['name'] for col in inspector.get_columns('books')]

            if 'status' in columns:
                print("  Dropping status column from books...")
                conn.execute(text("""
                    ALTER TABLE books DROP COLUMN status
                """))
                print("  ✓ status column removed")
            else:
                print("  ✓ status column already removed (or never existed)")

            conn.commit()

        print("✅ Book status column removal completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"Remove book status migration error: {e}", exc_info=True)
        raise


def migrate_guidelines_workflow():
    """
    Run Guidelines Workflow migration.

    Adds new columns and tables required for the guidelines extraction workflow:
    - review_status column in teaching_guidelines (TO_BE_REVIEWED, APPROVED)
    - book_jobs table for job locking
    """
    print("🔄 Running Guidelines Workflow migration...")
    db_manager = get_db_manager()
    engine = db_manager.engine
    inspector = inspect(engine)

    try:
        with engine.connect() as conn:
            # Step 1: Add review_status column to teaching_guidelines
            columns = [col['name'] for col in inspector.get_columns('teaching_guidelines')]

            if 'review_status' not in columns:
                print("  Adding review_status column to teaching_guidelines...")
                conn.execute(text("""
                    ALTER TABLE teaching_guidelines
                    ADD COLUMN review_status VARCHAR(20) DEFAULT 'TO_BE_REVIEWED' NOT NULL
                """))
                print("  ✓ review_status column added")

                # Create index for efficient filtering
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_teaching_guidelines_review_status
                    ON teaching_guidelines(book_id, review_status)
                """))
                print("  ✓ review_status index created")
            else:
                print("  ✓ review_status column already exists")

            conn.commit()

        # Step 2: Create book_jobs table
        print("  Creating book_jobs table...")
        tables = inspector.get_table_names()

        if 'book_jobs' not in tables:
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE book_jobs (
                        id VARCHAR(36) PRIMARY KEY,
                        book_id VARCHAR(255) NOT NULL,
                        job_type VARCHAR(50) NOT NULL,
                        status VARCHAR(20) DEFAULT 'running',
                        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        error_message TEXT,
                        FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
                    )
                """))
                conn.execute(text("""
                    CREATE INDEX idx_book_jobs_book_id ON book_jobs(book_id)
                """))
                conn.execute(text("""
                    CREATE INDEX idx_book_jobs_status ON book_jobs(status)
                """))
                conn.commit()
            print("  ✓ book_jobs table created")
        else:
            print("  ✓ book_jobs table already exists")

        print("✅ Guidelines Workflow migration completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        logger.error(f"Guidelines Workflow migration error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Book ingestion migrations")
    parser.add_argument("--migrate", action="store_true", help="Run migrations")
    parser.add_argument("--rollback", action="store_true", help="Rollback migrations (DANGEROUS)")
    parser.add_argument("--phase6", action="store_true", help="Run Phase 6 schema migration")
    parser.add_argument("--rollback-phase6", action="store_true", help="Rollback Phase 6 schema (DANGEROUS)")
    parser.add_argument("--add-description", action="store_true", help="Add description field to teaching_guidelines")
    parser.add_argument("--add-updated-at", action="store_true", help="Add updated_at field to teaching_guidelines")
    parser.add_argument("--guidelines-workflow", action="store_true", help="Run Guidelines Workflow migration (review_status + book_jobs)")
    parser.add_argument("--remove-book-status", action="store_true", help="Remove status column from books table")
    parser.add_argument("--add-book-guidelines-review-status", action="store_true", help="Add review_status column to book_guidelines table")

    args = parser.parse_args()

    if args.migrate:
        migrate_book_ingestion()
    elif args.rollback:
        rollback_book_ingestion()
    elif args.phase6:
        migrate_phase6_schema()
    elif args.rollback_phase6:
        rollback_phase6_schema()
    elif args.add_description:
        add_description_field()
    elif args.add_updated_at:
        add_updated_at_field()
    elif args.guidelines_workflow:
        migrate_guidelines_workflow()
    elif args.remove_book_status:
        remove_book_status_column()
    elif args.add_book_guidelines_review_status:
        add_book_guidelines_review_status()
    else:
        print("Usage:")
        print("  python -m features.book_ingestion.migrations --migrate           # Run base migrations")
        print("  python -m features.book_ingestion.migrations --rollback          # Rollback base (DANGEROUS)")
        print("  python -m features.book_ingestion.migrations --phase6            # Run Phase 6 schema")
        print("  python -m features.book_ingestion.migrations --rollback-phase6   # Rollback Phase 6 (DANGEROUS)")
        print("  python -m features.book_ingestion.migrations --add-description   # Add description field")
        print("  python -m features.book_ingestion.migrations --add-updated-at    # Add updated_at field")
        print("  python -m features.book_ingestion.migrations --guidelines-workflow # Add review_status + book_jobs")
        print("  python -m features.book_ingestion.migrations --remove-book-status  # Remove status column from books")
        print("  python -m features.book_ingestion.migrations --add-book-guidelines-review-status  # Add review_status to book_guidelines")
        sys.exit(1)
