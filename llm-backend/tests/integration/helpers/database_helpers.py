"""Database helper utilities for integration tests."""


def cleanup_sessions(db_session, session_ids):
    """
    Clean up test sessions and related events.

    Args:
        db_session: SQLAlchemy session
        session_ids: List of session IDs to delete
    """
    from shared.models.entities import Session, Event

    if not session_ids:
        return

    # Delete events first (foreign key dependency)
    db_session.query(Event).filter(
        Event.session_id.in_(session_ids)
    ).delete(synchronize_session=False)

    # Delete sessions
    db_session.query(Session).filter(
        Session.id.in_(session_ids)
    ).delete(synchronize_session=False)

    db_session.commit()


def cleanup_books(db_session, book_ids):
    """
    Clean up test books and related guidelines.

    Args:
        db_session: SQLAlchemy session
        book_ids: List of book IDs to delete
    """
    from book_ingestion.models.database import Book, BookGuideline

    if not book_ids:
        return

    # Delete book guidelines first
    db_session.query(BookGuideline).filter(
        BookGuideline.book_id.in_(book_ids)
    ).delete(synchronize_session=False)

    # Delete books
    db_session.query(Book).filter(
        Book.id.in_(book_ids)
    ).delete(synchronize_session=False)

    db_session.commit()


def cleanup_teaching_guidelines(db_session, guideline_ids):
    """
    Clean up teaching guidelines.

    Args:
        db_session: SQLAlchemy session
        guideline_ids: List of guideline IDs to delete
    """
    from shared.models.entities import TeachingGuideline

    if not guideline_ids:
        return

    db_session.query(TeachingGuideline).filter(
        TeachingGuideline.id.in_(guideline_ids)
    ).delete(synchronize_session=False)

    db_session.commit()


def verify_session_in_db(db_session, session_id):
    """
    Verify a session exists in the database.

    Args:
        db_session: SQLAlchemy session
        session_id: Session ID to verify

    Returns:
        Session object if found

    Raises:
        AssertionError: If session not found
    """
    from shared.models.entities import Session

    session = db_session.query(Session).filter_by(id=session_id).first()
    assert session is not None, f"Session {session_id} not found in database"
    return session


def verify_book_in_db(db_session, book_id):
    """
    Verify a book exists in the database.

    Args:
        db_session: SQLAlchemy session
        book_id: Book ID to verify

    Returns:
        Book object if found

    Raises:
        AssertionError: If book not found
    """
    from book_ingestion.models.database import Book

    book = db_session.query(Book).filter_by(id=book_id).first()
    assert book is not None, f"Book {book_id} not found in database"
    return book


def count_events_for_session(db_session, session_id):
    """
    Count events for a given session.

    Args:
        db_session: SQLAlchemy session
        session_id: Session ID

    Returns:
        Number of events for the session
    """
    from shared.models.entities import Event

    return db_session.query(Event).filter_by(session_id=session_id).count()


def seed_test_guideline(db_session, guideline_data):
    """
    Seed a test guideline for curriculum testing.

    Args:
        db_session: SQLAlchemy session
        guideline_data: Dictionary with guideline fields

    Returns:
        Created TeachingGuideline object
    """
    from shared.models.entities import TeachingGuideline
    import re

    # Generate topic_key and subtopic_key if not provided
    if "topic_key" not in guideline_data and "topic" in guideline_data:
        guideline_data["topic_key"] = re.sub(r'[^a-z0-9]+', '_', guideline_data["topic"].lower()).strip('_')

    if "subtopic_key" not in guideline_data and "subtopic" in guideline_data:
        guideline_data["subtopic_key"] = re.sub(r'[^a-z0-9]+', '_', guideline_data["subtopic"].lower()).strip('_')

    # Add teaching_description if not provided (required in production DB)
    if "teaching_description" not in guideline_data:
        guideline_data["teaching_description"] = guideline_data.get("guideline", "Test teaching description")

    guideline = TeachingGuideline(**guideline_data)
    db_session.add(guideline)
    db_session.commit()
    db_session.refresh(guideline)
    return guideline
