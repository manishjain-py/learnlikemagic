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


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Book ingestion migrations")
    parser.add_argument("--migrate", action="store_true", help="Run migrations")
    parser.add_argument("--rollback", action="store_true", help="Rollback migrations (DANGEROUS)")

    args = parser.parse_args()

    if args.migrate:
        migrate_book_ingestion()
    elif args.rollback:
        rollback_book_ingestion()
    else:
        print("Usage:")
        print("  python -m features.book_ingestion.migrations --migrate   # Run migrations")
        print("  python -m features.book_ingestion.migrations --rollback  # Rollback (DANGEROUS)")
        sys.exit(1)
