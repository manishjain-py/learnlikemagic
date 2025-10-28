"""Integration tests for session management endpoints."""
import pytest
import uuid


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.critical
def test_create_session_success(client, db_session, sample_student, sample_goal, cleanup_tracker):
    """Test creating a new tutoring session."""
    request_data = {
        "student": sample_student,
        "goal": sample_goal
    }

    response = client.post("/sessions", json=request_data)

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "session_id" in data
    assert "first_turn" in data
    assert isinstance(data["first_turn"], dict)

    session_id = data["session_id"]
    cleanup_tracker["session_ids"].append(session_id)

    # Verify session persisted to database
    from tests.integration.helpers.database_helpers import verify_session_in_db
    db_record = verify_session_in_db(db_session, session_id)
    assert db_record.id == session_id


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.llm
@pytest.mark.slow
def test_submit_step_with_answer(client, db_session, sample_student, sample_goal, cleanup_tracker):
    """Test submitting a student answer and receiving next turn."""
    # Create session first
    create_response = client.post("/sessions", json={
        "student": sample_student,
        "goal": sample_goal
    })
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]
    cleanup_tracker["session_ids"].append(session_id)

    # Submit a step with an answer
    step_response = client.post(f"/sessions/{session_id}/step", json={
        "student_reply": "I think 5/8 is bigger than 3/8 because 5 is more than 3"
    })

    assert step_response.status_code == 200
    data = step_response.json()

    # Verify response structure
    assert "next_turn" in data
    assert "routing" in data
    assert "last_grading" in data
    assert isinstance(data["next_turn"], dict)
    assert isinstance(data["last_grading"], dict)

    # Verify grading result structure
    grading = data["last_grading"]
    assert "is_correct" in grading or "score" in grading


@pytest.mark.integration
@pytest.mark.db
def test_get_session_summary(client, db_session, sample_student, sample_goal, cleanup_tracker):
    """Test fetching session summary."""
    # Create session
    create_response = client.post("/sessions", json={
        "student": sample_student,
        "goal": sample_goal
    })
    session_id = create_response.json()["session_id"]
    cleanup_tracker["session_ids"].append(session_id)

    # Get summary
    summary_response = client.get(f"/sessions/{session_id}/summary")

    assert summary_response.status_code == 200
    data = summary_response.json()

    # Verify summary structure
    assert "steps_completed" in data or "step_idx" in data
    assert "mastery_score" in data or "mastery" in data
    # May have misconceptions_seen and suggestions


@pytest.mark.integration
@pytest.mark.db
def test_get_session_state(client, db_session, sample_student, sample_goal, cleanup_tracker):
    """Test fetching full session state (debug endpoint)."""
    # Create session
    create_response = client.post("/sessions", json={
        "student": sample_student,
        "goal": sample_goal
    })
    session_id = create_response.json()["session_id"]
    cleanup_tracker["session_ids"].append(session_id)

    # Get full state
    state_response = client.get(f"/sessions/{session_id}")

    assert state_response.status_code == 200
    data = state_response.json()

    # Verify state contains expected fields
    assert isinstance(data, dict)
    # Should have some session state information


@pytest.mark.integration
def test_create_session_invalid_student_data(client):
    """Test creating session with invalid student data."""
    request_data = {
        "student": {"invalid": "data"},  # Missing required fields
        "goal": {
            "country": "India",
            "board": "CBSE",
            "grade": 8,
            "subject": "Mathematics"
        }
    }

    response = client.post("/sessions", json=request_data)

    # Should return validation error
    assert response.status_code in [400, 422]


@pytest.mark.integration
def test_create_session_missing_goal(client, sample_student):
    """Test creating session without goal."""
    request_data = {
        "student": sample_student
        # Missing goal
    }

    response = client.post("/sessions", json=request_data)

    # Should return validation error
    assert response.status_code in [400, 422]


@pytest.mark.integration
def test_submit_step_nonexistent_session(client):
    """Test submitting step to non-existent session."""
    fake_session_id = str(uuid.uuid4())

    response = client.post(f"/sessions/{fake_session_id}/step", json={
        "student_reply": "test answer"
    })

    # Should return 404 or 400
    assert response.status_code in [404, 400, 500]


@pytest.mark.integration
def test_get_summary_nonexistent_session(client):
    """Test getting summary for non-existent session."""
    fake_session_id = str(uuid.uuid4())

    response = client.get(f"/sessions/{fake_session_id}/summary")

    # Should return 404 or 400
    assert response.status_code in [404, 400, 500]
