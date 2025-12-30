"""Integration test configuration and fixtures."""
import os
import uuid
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import DatabaseManager
from shared.models.entities import Base
from book_ingestion.models.database import *
from book_ingestion.models.guideline_models import *


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
    
    # Ensure tables exist for tests
    # Note: verify we have engine access
    if hasattr(db_manager, "engine"):
         Base.metadata.create_all(db_manager.engine)
    elif hasattr(db_manager, "_engine"):
         Base.metadata.create_all(db_manager._engine)

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
def cleanup_sessions_after_test(db_session, cleanup_tracker, request, mock_s3):
    """Cleanup sessions after each integration test."""
    # Skip if not an integration test
    if "integration" not in [mark.name for mark in request.node.iter_markers()]:
        yield
        return

    yield

    # Cleanup sessions
    if cleanup_tracker["session_ids"]:
        from shared.models.entities import Session, Event

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
        from book_ingestion.models.database import Book, BookGuideline

        # Delete book guidelines first
        db_session.query(BookGuideline).filter(
            BookGuideline.book_id.in_(cleanup_tracker["book_ids"])
        ).delete(synchronize_session=False)

        # Delete books
        db_session.query(Book).filter(
            Book.id.in_(cleanup_tracker["book_ids"])
        ).delete(synchronize_session=False)

        db_session.commit()



class MockS3Client:
    """Mock S3 client for integration tests."""
    def __init__(self, *args, **kwargs):
        self.bucket_name = "test-bucket"
        self.storage = {}  # key -> bytes or str

    def upload_json(self, key, data):
        self.storage[key] = json.dumps(data)
        print(f"Mock S3: Uploaded JSON to {key}")

    def update_metadata_json(self, book_id, metadata):
        key = f"books/{book_id}/metadata.json"
        self.upload_json(key, metadata)

    def download_json(self, key):
        if key not in self.storage:
            raise Exception(f"NoSuchKey: {key}")
        data = self.storage[key]
        if isinstance(data, bytes):
            return json.loads(data.decode('utf-8'))
        return json.loads(data)

    def upload_file(self, file_obj, key, content_type=None):
        if hasattr(file_obj, 'read'):
            content = file_obj.read()
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
        else:
            content = file_obj
        self.storage[key] = content
        print(f"Mock S3: Uploaded file to {key}")
        return f"https://s3.amazonaws.com/{self.bucket_name}/{key}"

    def delete_folder(self, prefix):
        keys_to_delete = [k for k in self.storage if k.startswith(prefix)]
        for k in keys_to_delete:
            del self.storage[k]
        print(f"Mock S3: Deleted folder {prefix}")

    def generate_presigned_url(self, operation, key, expiration=3600):
        return f"https://mock-s3-presigned-url/{key}"

@pytest.fixture
def mock_s3(monkeypatch):
    """
    Mock S3Client for all integration tests.
    """
    import book_ingestion.utils.s3_client as s3_module
    import book_ingestion.services.book_service as book_service_module
    import book_ingestion.services.page_service as page_service_module
    
    mock_client = MockS3Client()
    
    def get_mock_client(*args, **kwargs):
        return mock_client

    # Patch S3Client class
    monkeypatch.setattr(s3_module, "S3Client", get_mock_client)
    
    # Patch get_s3_client if used
    if hasattr(s3_module, "get_s3_client"):
         monkeypatch.setattr(s3_module, "get_s3_client", lambda: mock_client)
    
    return mock_client

@pytest.fixture
def s3_client(test_config, mock_s3):
    """
    Returns the mock S3 client.
    """
    uploaded_keys = []
    yield mock_s3, uploaded_keys



@pytest.fixture
def sample_student(test_config):
    """Generate sample student data with unique ID."""
    return {
        "id": f"{test_config['test_prefix']}student_{uuid.uuid4().hex[:8]}",
        "grade": 3,
        "prefs": {
            "style": "standard",
            "lang": "en"
        }
    }


@pytest.fixture
def sample_goal():
    """Generate sample learning goal."""
    return {
        "topic": "Fractions",
        "syllabus": "CBSE Grade 3 Mathematics",
        "learning_objectives": [
            "Compare fractions with like denominators",
            "Identify larger/smaller fractions"
        ],
        "guideline_id": "g1"  # Reference to existing guideline
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
