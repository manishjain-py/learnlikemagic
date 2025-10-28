"""Integration test configuration and fixtures."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import DatabaseManager
from models.database import Base


@pytest.fixture(scope="session")
def test_config():
    """Load test-specific configuration."""
    return {
        "database_url": os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/learnlikemagic"),
        "s3_bucket": os.getenv("AWS_S3_BUCKET", "learnlikemagic-books"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "test_prefix": f"test_{uuid.uuid4().hex[:8]}_",
        "aws_region": os.getenv("AWS_REGION", "us-east-1")
    }


@pytest.fixture(scope="session")
def fastapi_app():
    """FastAPI application instance."""
    return app


@pytest.fixture
def client(fastapi_app):
    """HTTP test client for API calls."""
    return TestClient(fastapi_app)


@pytest.fixture
def db_session(test_config):
    """
    Database session with automatic cleanup.

    Uses production PostgreSQL database with proper cleanup.
    Creates a session and tracks created records for cleanup.
    """
    # Override database URL environment variable if needed
    if test_config.get("database_url"):
        import os
        os.environ["DATABASE_URL"] = test_config["database_url"]

    db_manager = DatabaseManager()
    session = db_manager.get_session()

    yield session

    # Cleanup happens in individual test fixtures
    session.close()


@pytest.fixture
def cleanup_tracker():
    """
    Track resources created during tests for cleanup.

    This fixture should be used by tests to register resources
    that need to be cleaned up after the test completes.
    """
    tracker = {
        "session_ids": [],
        "book_ids": [],
        "guideline_ids": [],
        "s3_keys": []
    }
    yield tracker


@pytest.fixture(autouse=True)
def cleanup_sessions_after_test(db_session, cleanup_tracker, request):
    """Cleanup sessions after each integration test."""
    # Skip if not an integration test
    if "integration" not in [mark.name for mark in request.node.iter_markers()]:
        yield
        return

    yield

    # Cleanup sessions
    if cleanup_tracker["session_ids"]:
        from models.database import Session, Event

        # Delete events first (foreign key dependency)
        db_session.query(Event).filter(
            Event.session_id.in_(cleanup_tracker["session_ids"])
        ).delete(synchronize_session=False)

        # Delete sessions
        db_session.query(Session).filter(
            Session.id.in_(cleanup_tracker["session_ids"])
        ).delete(synchronize_session=False)

        db_session.commit()


@pytest.fixture(autouse=True)
def cleanup_books_after_test(db_session, cleanup_tracker, request):
    """Cleanup books after each integration test."""
    # Skip if not an integration test
    if "integration" not in [mark.name for mark in request.node.iter_markers()]:
        yield
        return

    yield

    # Cleanup books
    if cleanup_tracker["book_ids"]:
        from features.book_ingestion.models.database import Book, BookGuideline

        # Delete book guidelines first
        db_session.query(BookGuideline).filter(
            BookGuideline.book_id.in_(cleanup_tracker["book_ids"])
        ).delete(synchronize_session=False)

        # Delete books
        db_session.query(Book).filter(
            Book.id.in_(cleanup_tracker["book_ids"])
        ).delete(synchronize_session=False)

        db_session.commit()


@pytest.fixture
def s3_client(test_config):
    """
    S3 client with automatic cleanup.

    Returns a tuple of (s3_client, uploaded_keys_list).
    Tests should append S3 keys to the uploaded_keys list
    for automatic cleanup.
    """
    from features.book_ingestion.utils.s3_client import S3Client

    s3 = S3Client(
        bucket_name=test_config["s3_bucket"],
        region_name=test_config["aws_region"]
    )

    uploaded_keys = []

    yield s3, uploaded_keys

    # Cleanup S3 objects
    for key in uploaded_keys:
        try:
            s3.client.delete_object(Bucket=s3.bucket_name, Key=key)
        except Exception as e:
            print(f"Warning: Failed to cleanup S3 key {key}: {e}")


@pytest.fixture
def sample_student(test_config):
    """Generate sample student data with unique ID."""
    return {
        "student_id": f"{test_config['test_prefix']}student_{uuid.uuid4().hex[:8]}",
        "name": "Test Student",
        "grade": 8,
        "country": "India",
        "board": "CBSE"
    }


@pytest.fixture
def sample_goal():
    """Generate sample learning goal."""
    return {
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra",
        "subtopic": "Linear Equations"
    }


@pytest.fixture
def sample_book_data(test_config):
    """Generate sample book metadata with unique title."""
    return {
        "title": f"{test_config['test_prefix']}Test_Book_{uuid.uuid4().hex[:8]}",
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "publisher": "Test Publisher",
        "year": 2024,
        "isbn": f"test-isbn-{uuid.uuid4().hex[:12]}"
    }


@pytest.fixture
def sample_page_image():
    """
    Generate a sample page image for OCR testing.

    Creates a simple PNG image with text content suitable
    for testing OCR functionality.
    """
    from PIL import Image, ImageDraw, ImageFont
    import io

    # Create a test image with text
    img = Image.new('RGB', (800, 1000), color='white')
    draw = ImageDraw.Draw(img)

    # Add some text (use default font)
    text_lines = [
        "Linear Equations",
        "",
        "A linear equation is an equation of the form ax + b = c",
        "where a, b, and c are constants and x is a variable.",
        "",
        "Examples:",
        "1. 2x + 3 = 7",
        "2. 5x - 4 = 11",
        "3. x + 8 = 15"
    ]

    y_position = 50
    for line in text_lines:
        draw.text((50, y_position), line, fill='black')
        y_position += 40

    # Convert to bytes
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


@pytest.fixture
def sample_create_session_request(sample_student, sample_goal):
    """Generate a complete session creation request payload."""
    return {
        "student": sample_student,
        "goal": sample_goal
    }
