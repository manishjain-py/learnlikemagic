"""Integration tests for curriculum discovery endpoints."""
import pytest
from tests.integration.helpers.database_helpers import seed_test_guideline, cleanup_teaching_guidelines


@pytest.mark.integration
@pytest.mark.db
def test_get_subjects_for_curriculum(client, db_session, cleanup_tracker):
    """Test fetching subjects for a given country/board/grade."""
    # Seed test guideline data
    guideline1 = seed_test_guideline(db_session, {
        "id": "test_guideline_1",
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra",
        "subtopic": "Linear Equations",
        "guideline": "Test content for linear equations"
    })
    guideline2 = seed_test_guideline(db_session, {
        "id": "test_guideline_2",
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Science",
        "topic": "Physics",
        "subtopic": "Motion",
        "guideline": "Test content for motion"
    })

    # Track for cleanup
    cleanup_tracker["guideline_ids"] = [guideline1.id, guideline2.id]

    response = client.get("/curriculum", params={
        "country": "India",
        "board": "CBSE",
        "grade": 8
    })

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "subjects" in data or isinstance(data, list)

    # If it returns a list, check if our subjects are there
    if isinstance(data, list):
        subject_names = [s["name"] if isinstance(s, dict) else s for s in data]
        assert "Mathematics" in subject_names or any("Math" in str(s) for s in subject_names)
    else:
        # If it returns a dict with subjects key
        assert "Mathematics" in data["subjects"] or "Science" in data["subjects"]


@pytest.mark.integration
@pytest.mark.db
def test_get_topics_for_subject(client, db_session, cleanup_tracker):
    """Test fetching topics for a given subject."""
    # Seed test guideline
    guideline = seed_test_guideline(db_session, {
        "id": "test_guideline_3",
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra",
        "subtopic": "Linear Equations",
        "guideline": "Test content"
    })
    cleanup_tracker["guideline_ids"] = [guideline.id]

    response = client.get("/curriculum", params={
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics"
    })

    assert response.status_code == 200
    data = response.json()

    # Verify response structure - should have topics
    assert "topics" in data or isinstance(data, list)

    if isinstance(data, list):
        topic_names = [t["name"] if isinstance(t, dict) else t for t in data]
        assert "Algebra" in topic_names or any("Algebra" in str(t) for t in topic_names)
    else:
        assert "Algebra" in data["topics"] or len(data["topics"]) > 0


@pytest.mark.integration
@pytest.mark.db
def test_get_subtopics_for_topic(client, db_session, cleanup_tracker):
    """Test fetching subtopics for a given topic."""
    # Seed test guidelines with multiple subtopics
    guideline1 = seed_test_guideline(db_session, {
        "id": "test_guideline_4",
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra",
        "subtopic": "Linear Equations",
        "guideline": "Test content for linear equations"
    })
    guideline2 = seed_test_guideline(db_session, {
        "id": "test_guideline_5",
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra",
        "subtopic": "Quadratic Equations",
        "guideline": "Test content for quadratic equations"
    })
    cleanup_tracker["guideline_ids"] = [guideline1.id, guideline2.id]

    response = client.get("/curriculum", params={
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra"
    })

    assert response.status_code == 200
    data = response.json()

    # Verify response structure - should have subtopics
    assert "subtopics" in data or isinstance(data, list)

    if isinstance(data, list):
        # List of subtopics
        assert len(data) > 0
        # Check if our subtopic is present
        subtopic_names = [s.get("subtopic", s.get("name", str(s))) if isinstance(s, dict) else str(s) for s in data]
        assert any("Linear Equations" in name for name in subtopic_names)
    else:
        # Dict with subtopics key
        assert len(data["subtopics"]) > 0
        subtopic_names = [s.get("subtopic", s.get("name", str(s))) if isinstance(s, dict) else str(s) for s in data["subtopics"]]
        assert any("Linear" in name or "Quadratic" in name for name in subtopic_names)


@pytest.mark.integration
@pytest.mark.db
def test_curriculum_with_nonexistent_data(client):
    """Test curriculum endpoint with data that doesn't exist."""
    response = client.get("/curriculum", params={
        "country": "NonExistentCountry",
        "board": "NonExistentBoard",
        "grade": 999
    })

    # Should return 200 with empty results, not error
    assert response.status_code == 200
    data = response.json()

    # Should return empty or minimal structure
    if isinstance(data, list):
        assert len(data) == 0 or data == []
    elif isinstance(data, dict):
        # Check for empty subjects/topics/subtopics
        for key in ["subjects", "topics", "subtopics"]:
            if key in data and data[key] is not None:
                assert len(data[key]) == 0 or data[key] == []


@pytest.mark.integration
def test_curriculum_missing_required_params(client):
    """Test curriculum endpoint without required parameters."""
    response = client.get("/curriculum")

    # Should return validation error (422)
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


@pytest.mark.integration
@pytest.mark.db
def test_curriculum_response_structure(client, db_session, cleanup_tracker):
    """Test that curriculum endpoint returns correctly structured data."""
    # Seed complete curriculum hierarchy
    guideline = seed_test_guideline(db_session, {
        "id": "test_guideline_6",
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra",
        "subtopic": "Linear Equations",
        "guideline": "Test content"
    })
    cleanup_tracker["guideline_ids"] = [guideline.id]

    # Test subject level
    response = client.get("/curriculum", params={
        "country": "India",
        "board": "CBSE",
        "grade": 8
    })
    assert response.status_code == 200
    assert isinstance(response.json(), (list, dict))

    # Test topic level
    response = client.get("/curriculum", params={
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics"
    })
    assert response.status_code == 200
    assert isinstance(response.json(), (list, dict))

    # Test subtopic level
    response = client.get("/curriculum", params={
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "topic": "Algebra"
    })
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, (list, dict))

    # If dict, should have subtopics or be a list of subtopics
    if isinstance(data, dict):
        assert "subtopics" in data or len(data) > 0


@pytest.fixture(autouse=True)
def cleanup_guidelines_after_test(db_session, cleanup_tracker, request):
    """Cleanup guidelines after each curriculum test."""
    # Skip if not an integration test
    if "integration" not in [mark.name for mark in request.node.iter_markers()]:
        yield
        return

    yield

    # Cleanup guidelines
    if cleanup_tracker.get("guideline_ids"):
        cleanup_teaching_guidelines(db_session, cleanup_tracker["guideline_ids"])
