"""Integration tests for health check endpoints."""
import pytest


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.critical
def test_root_health_check(client):
    """Test root endpoint returns service status."""
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data
    assert "version" in data
    assert data["version"] == "1.0.0"


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.critical
@pytest.mark.db
def test_database_health_check(client):
    """Test database health check endpoint."""
    response = client.get("/health/db")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


@pytest.mark.integration
@pytest.mark.smoke
def test_root_health_check_response_format(client):
    """Test that root health check returns correct format."""
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()

    # Verify all expected fields are present
    assert isinstance(data, dict)
    assert "status" in data
    assert "service" in data
    assert "version" in data

    # Verify field types
    assert isinstance(data["status"], str)
    assert isinstance(data["service"], str)
    assert isinstance(data["version"], str)
