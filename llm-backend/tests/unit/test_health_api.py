"""
Tests for shared/api/health.py

Covers 3 endpoints: read_root, get_model_config, database_health.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.health import router
from database import get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_and_client():
    """Build a test app with health router and mocked DB dependency."""
    app = FastAPI()
    app.include_router(router)

    mock_db = MagicMock()

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return app, client, mock_db


# ===========================================================================
# read_root
# ===========================================================================

class TestReadRoot:

    def test_health_check(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "LearnLikeMagic LLM Backend"
        assert data["version"] == "1.0.0"


# ===========================================================================
# get_model_config
# ===========================================================================

class TestGetModelConfig:

    @patch("config.get_settings")
    def test_openai_tutor(self, mock_get_settings, app_and_client):
        _, client, _ = app_and_client

        mock_settings = MagicMock()
        mock_settings.resolved_tutor_provider = "openai"
        mock_settings.ingestion_llm_provider = "openai"
        mock_get_settings.return_value = mock_settings

        resp = client.get("/config/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tutor"]["provider"] == "openai"
        assert data["tutor"]["model_label"] == "GPT-5.2"
        assert data["ingestion"]["provider"] == "openai"
        assert data["ingestion"]["model_label"] == "GPT-4o Mini"

    @patch("config.get_settings")
    def test_anthropic_tutor(self, mock_get_settings, app_and_client):
        _, client, _ = app_and_client

        mock_settings = MagicMock()
        mock_settings.resolved_tutor_provider = "anthropic"
        mock_settings.ingestion_llm_provider = "openai"
        mock_get_settings.return_value = mock_settings

        resp = client.get("/config/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tutor"]["model_label"] == "Claude Opus 4.6"

    @patch("config.get_settings")
    def test_unknown_provider(self, mock_get_settings, app_and_client):
        _, client, _ = app_and_client

        mock_settings = MagicMock()
        mock_settings.resolved_tutor_provider = "custom-provider"
        mock_settings.ingestion_llm_provider = "openai"
        mock_get_settings.return_value = mock_settings

        resp = client.get("/config/models")
        assert resp.status_code == 200
        data = resp.json()
        # Unknown provider falls back to provider name as label
        assert data["tutor"]["model_label"] == "custom-provider"


# ===========================================================================
# database_health
# ===========================================================================

class TestDatabaseHealth:

    @patch("shared.api.health.get_db_manager")
    def test_db_healthy(self, mock_get_manager, app_and_client):
        _, client, _ = app_and_client

        mock_manager = MagicMock()
        mock_manager.health_check.return_value = True
        mock_get_manager.return_value = mock_manager

        resp = client.get("/health/db")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    @patch("shared.api.health.get_db_manager")
    def test_db_unhealthy(self, mock_get_manager, app_and_client):
        _, client, _ = app_and_client

        mock_manager = MagicMock()
        mock_manager.health_check.return_value = False
        mock_get_manager.return_value = mock_manager

        resp = client.get("/health/db")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert data["database"] == "connection_failed"

    @patch("shared.api.health.get_db_manager")
    def test_db_exception(self, mock_get_manager, app_and_client):
        _, client, _ = app_and_client

        mock_get_manager.side_effect = RuntimeError("cannot connect")

        resp = client.get("/health/db")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "cannot connect" in data["database"]
