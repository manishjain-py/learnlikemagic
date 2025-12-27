"""
Database initialization, migration, and seeding utilities.
"""
import json
import sys
import argparse
from pathlib import Path
from models import Base, TeachingGuideline
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


def seed_guidelines(seed_file_path: str):
    """Load teaching guidelines from JSON file into teaching_guidelines table."""
    print(f"Loading teaching guidelines from {seed_file_path}...")

    path = Path(seed_file_path)
    if not path.exists():
        print(f"Error: Seed file not found: {seed_file_path}")
        return

    with open(path, 'r') as f:
        guidelines_data = json.load(f)

    db_manager = get_db_manager()
    db = db_manager.get_session()

    try:
        # Clear existing guidelines
        db.query(TeachingGuideline).delete()
        db.commit()

        # Insert new guidelines
        for item in guidelines_data:
            # Convert metadata dict to JSON string
            metadata_json = json.dumps(item.get("metadata", {})) if "metadata" in item else None

            guideline = TeachingGuideline(
                id=item["id"],
                country=item["country"],
                board=item["board"],
                grade=item["grade"],
                subject=item["subject"],
                topic=item["topic"],
                subtopic=item["subtopic"],
                guideline=item["guideline"],
                metadata_json=metadata_json
            )
            db.add(guideline)

        db.commit()
        print(f"✓ Loaded {len(guidelines_data)} teaching guidelines")

    except Exception as e:
        print(f"Error seeding guidelines: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Database management CLI")
    parser.add_argument("--migrate", action="store_true", help="Create database tables")
    parser.add_argument("--seed-guidelines", type=str, help="Seed teaching guidelines from JSON file")

    args = parser.parse_args()

    if args.migrate:
        migrate()
    elif args.seed_guidelines:
        seed_guidelines(args.seed_guidelines)
    else:
        print("Usage:")
        print("  python db.py --migrate                      # Create tables")
        print("  python db.py --seed-guidelines <json_file>  # Load teaching guidelines")
        sys.exit(1)
