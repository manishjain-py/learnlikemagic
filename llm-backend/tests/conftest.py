"""Pytest configuration and shared fixtures."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from shared.models.entities import Base
# Import all models to ensure they are registered with Base.metadata
from shared.models.entities import *
from book_ingestion.models.database import *
from main import app


@pytest.fixture(scope="function")
def db_session():
    """
    Create a test database session with in-memory SQLite.

    This fixture creates a fresh database for each test function,
    ensuring test isolation.
    """
    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Create all tables
    Base.metadata.create_all(engine)

    # Create session
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    # Cleanup
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def sample_student():
    """Sample student data for testing."""
    from shared.models.domain import Student, StudentPrefs

    return Student(
        id="test-student-1",
        grade=3,
        prefs=StudentPrefs(
            style="standard",
            lang="en"
        )
    )


@pytest.fixture
def sample_goal():
    """Sample learning goal for testing."""
    from shared.models.domain import Goal

    return Goal(
        topic="Fractions",
        syllabus="CBSE Grade 3 Mathematics",
        learning_objectives=[
            "Compare fractions with like denominators",
            "Identify larger/smaller fractions"
        ],
        guideline_id="g1"
    )


@pytest.fixture
def sample_tutor_state(sample_student, sample_goal):
    """Sample tutor state for testing."""
    from shared.models.domain import TutorState

    return TutorState(
        session_id="test-session-123",
        student=sample_student,
        goal=sample_goal,
        step_idx=0,
        history=[],
        evidence=[],
        mastery_score=0.5,
        last_grading=None,
        next_action="present"
    )


@pytest.fixture
def sample_grading_result():
    """Sample grading result for testing."""
    from shared.models.domain import GradingResult

    return GradingResult(
        score=0.85,
        rationale="Student correctly identified the larger fraction",
        labels=["correct_comparison"],
        confidence=0.9
    )


@pytest.fixture
def mock_llm_provider(mocker):
    """Mock LLM provider for testing without API calls."""
    mock_provider = mocker.Mock()
    mock_provider.generate.return_value = {
        "message": "Great! Let's work on fractions.",
        "hints": ["Think about the numerator", "Compare the top numbers"],
        "expected_answer_form": "short_text"
    }
    return mock_provider
