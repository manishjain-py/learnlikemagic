"""
Database initialization, migration, and seeding utilities.
"""
import json
import sys
import argparse
from pathlib import Path
from sqlalchemy.orm import Session as DBSession
from models import Base, Session, Event, TeachingGuideline
from database import get_db_manager
import uuid


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


def create_session_record(db: DBSession, session_id: str, state_json: str, student_json: str, goal_json: str) -> Session:
    """Helper to create a session record."""
    session = Session(
        id=session_id,
        student_json=student_json,
        goal_json=goal_json,
        state_json=state_json,
        mastery=0.0,
        step_idx=0
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def update_session_state(db: DBSession, session_id: str, state_json: str, mastery: float, step_idx: int):
    """Update session state."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.state_json = state_json
        session.mastery = mastery
        session.step_idx = step_idx
        db.commit()


def log_event(db: DBSession, session_id: str, node: str, step_idx: int, payload: dict):
    """Log an event to the events table."""
    event = Event(
        id=str(uuid.uuid4()),
        session_id=session_id,
        node=node,
        step_idx=step_idx,
        payload_json=json.dumps(payload)
    )
    db.add(event)
    db.commit()


def get_session_by_id(db: DBSession, session_id: str) -> Session:
    """Retrieve a session by ID."""
    return db.query(Session).filter(Session.id == session_id).first()


def get_session_events(db: DBSession, session_id: str):
    """Get all events for a session."""
    return db.query(Event).filter(Event.session_id == session_id).order_by(Event.created_at).all()


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
