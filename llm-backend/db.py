"""
Database initialization, migration, and seeding utilities.
"""
import json
import sys
import argparse
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session as DBSession
from models import Base, Session, Event, Content
import uuid


DATABASE_URL = "sqlite:///./tutor.db"
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> DBSession:
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_fts_table(conn):
    """Create FTS5 virtual table for full-text search."""
    # Drop existing triggers if they exist
    conn.execute(text("DROP TRIGGER IF EXISTS contents_ai"))
    conn.execute(text("DROP TRIGGER IF EXISTS contents_ad"))
    conn.execute(text("DROP TRIGGER IF EXISTS contents_au"))

    # Drop existing FTS table if exists
    conn.execute(text("DROP TABLE IF EXISTS contents_fts"))

    # Create FTS5 virtual table
    conn.execute(text("""
        CREATE VIRTUAL TABLE contents_fts USING fts5(
            id UNINDEXED,
            topic,
            grade UNINDEXED,
            skill,
            text,
            tags,
            content='contents',
            content_rowid='rowid'
        )
    """))

    # Create triggers to keep FTS in sync
    conn.execute(text("""
        CREATE TRIGGER contents_ai AFTER INSERT ON contents BEGIN
            INSERT INTO contents_fts(rowid, id, topic, grade, skill, text, tags)
            VALUES (new.rowid, new.id, new.topic, new.grade, new.skill, new.text, new.tags);
        END
    """))

    conn.execute(text("""
        CREATE TRIGGER contents_ad AFTER DELETE ON contents BEGIN
            DELETE FROM contents_fts WHERE rowid = old.rowid;
        END
    """))

    conn.execute(text("""
        CREATE TRIGGER contents_au AFTER UPDATE ON contents BEGIN
            DELETE FROM contents_fts WHERE rowid = old.rowid;
            INSERT INTO contents_fts(rowid, id, topic, grade, skill, text, tags)
            VALUES (new.rowid, new.id, new.topic, new.grade, new.skill, new.text, new.tags);
        END
    """))

    conn.commit()
    print("✓ FTS5 table and triggers created")


def migrate():
    """Create all tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created")

    # Create FTS table
    with engine.connect() as conn:
        create_fts_table(conn)


def seed_contents(seed_file_path: str):
    """Load seed data from JSON file into contents table."""
    print(f"Loading seed data from {seed_file_path}...")

    path = Path(seed_file_path)
    if not path.exists():
        print(f"Error: Seed file not found: {seed_file_path}")
        return

    with open(path, 'r') as f:
        contents = json.load(f)

    db = SessionLocal()
    try:
        # Clear existing contents
        db.query(Content).delete()
        db.commit()

        # Insert new contents
        for item in contents:
            content = Content(
                id=item["id"],
                topic=item["topic"],
                grade=item["grade"],
                skill=item["skill"],
                text=item["text"],
                tags=item["tags"]
            )
            db.add(content)

        db.commit()
        print(f"✓ Loaded {len(contents)} content items")

        # Verify FTS index
        result = db.execute(text("SELECT COUNT(*) FROM contents_fts")).scalar()
        print(f"✓ FTS index contains {result} items")

    except Exception as e:
        print(f"Error seeding data: {e}")
        db.rollback()
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


def seed_guidelines(seed_file_path: str):
    """Load teaching guidelines from JSON file into teaching_guidelines table."""
    from models import TeachingGuideline

    print(f"Loading teaching guidelines from {seed_file_path}...")

    path = Path(seed_file_path)
    if not path.exists():
        print(f"Error: Seed file not found: {seed_file_path}")
        return

    with open(path, 'r') as f:
        guidelines_data = json.load(f)

    db = SessionLocal()
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
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Database management CLI")
    parser.add_argument("--migrate", action="store_true", help="Create database tables")
    parser.add_argument("--seed", type=str, help="Seed contents from JSON file")
    parser.add_argument("--seed-guidelines", type=str, help="Seed teaching guidelines from JSON file")

    args = parser.parse_args()

    if args.migrate:
        migrate()
    elif args.seed:
        seed_contents(args.seed)
    elif args.seed_guidelines:
        seed_guidelines(args.seed_guidelines)
    else:
        print("Usage:")
        print("  python db.py --migrate                      # Create tables")
        print("  python db.py --seed <json_file>             # Load seed content data")
        print("  python db.py --seed-guidelines <json_file>  # Load teaching guidelines")
        sys.exit(1)
