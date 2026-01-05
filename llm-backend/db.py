"""
Database initialization and migration utilities.
"""
import sys
import argparse
from shared.models.entities import Base
from database import get_db_manager


def migrate():
    """Create all database tables."""
    print("Creating database tables...")
    db_manager = get_db_manager()

    try:
        # Create all tables defined in models
        Base.metadata.create_all(bind=db_manager.engine)
        print("✓ Tables created")

        # Create indexes for teaching_guidelines if needed
        with db_manager.engine.connect() as conn:
            conn.commit()

    except Exception as e:
        print(f"Error during migration: {e}")
        raise


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
