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

    @patch("shared.services.llm_config_service.LLMConfigService")
    def test_returns_all_configs(self, mock_cls, app_and_client):
        _, client, _ = app_and_client

        mock_service = MagicMock()
        mock_service.get_all_configs.return_value = [
            {"component_key": "tutor", "provider": "openai", "model_id": "gpt-5.2", "description": "Tutor"},
            {"component_key": "book_ingestion", "provider": "openai", "model_id": "gpt-4o-mini", "description": "Ingestion"},
        ]
        mock_cls.return_value = mock_service

        resp = client.get("/config/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tutor"]["provider"] == "openai"
        assert data["tutor"]["model_id"] == "gpt-5.2"
        assert data["book_ingestion"]["provider"] == "openai"
        assert data["book_ingestion"]["model_id"] == "gpt-4o-mini"


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
