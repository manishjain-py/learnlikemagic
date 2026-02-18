"""
Tests for shared/api/health.py and shared/prompts/loader.py.

All DB, config, and filesystem calls are mocked.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.health import router as health_router
from shared.prompts.loader import PromptLoader, DEFAULT_PROMPTS_DIR


# ============================================================================
# Health Router Fixtures
# ============================================================================

@pytest.fixture
def health_client():
    """TestClient with the health router mounted."""
    app = FastAPI()
    app.include_router(health_router)
    return TestClient(app)


# ============================================================================
# Tests: GET / (health check)
# ============================================================================

class TestRootHealthCheck:
    def test_returns_ok(self, health_client):
        resp = health_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "LearnLikeMagic LLM Backend"
        assert data["version"] == "1.0.0"

    def test_response_keys(self, health_client):
        resp = health_client.get("/")
        data = resp.json()
        assert set(data.keys()) == {"status", "service", "version"}


# ============================================================================
# Tests: GET /config/models
# ============================================================================

class TestModelConfig:
    @patch("config.get_settings")
    def test_returns_model_config_openai(self, mock_settings, health_client):
        settings = MagicMock()
        settings.resolved_tutor_provider = "openai"
        settings.ingestion_llm_provider = "openai"
        mock_settings.return_value = settings

        resp = health_client.get("/config/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tutor"]["provider"] == "openai"
        assert data["tutor"]["model_label"] == "GPT-5.2"
        assert data["ingestion"]["provider"] == "openai"
        assert data["ingestion"]["model_label"] == "GPT-4o Mini"

    @patch("config.get_settings")
    def test_returns_model_config_anthropic(self, mock_settings, health_client):
        settings = MagicMock()
        settings.resolved_tutor_provider = "anthropic"
        settings.ingestion_llm_provider = "openai"
        mock_settings.return_value = settings

        resp = health_client.get("/config/models")
        data = resp.json()
        assert data["tutor"]["provider"] == "anthropic"
        assert data["tutor"]["model_label"] == "Claude Opus 4.6"

    @patch("config.get_settings")
    def test_returns_model_config_anthropic_haiku(self, mock_settings, health_client):
        settings = MagicMock()
        settings.resolved_tutor_provider = "anthropic-haiku"
        settings.ingestion_llm_provider = "openai"
        mock_settings.return_value = settings

        resp = health_client.get("/config/models")
        data = resp.json()
        assert data["tutor"]["model_label"] == "Claude Haiku 4.5"

    @patch("config.get_settings")
    def test_unknown_provider_label(self, mock_settings, health_client):
        settings = MagicMock()
        settings.resolved_tutor_provider = "some-new-provider"
        settings.ingestion_llm_provider = "openai"
        mock_settings.return_value = settings

        resp = health_client.get("/config/models")
        data = resp.json()
        assert data["tutor"]["model_label"] == "some-new-provider"


# ============================================================================
# Tests: GET /health/db
# ============================================================================

class TestDatabaseHealth:
    @patch("shared.api.health.get_db_manager")
    @patch("shared.api.health.get_db")
    def test_db_healthy(self, mock_get_db, mock_get_db_manager, health_client):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_manager = MagicMock()
        mock_manager.health_check.return_value = True
        mock_get_db_manager.return_value = mock_manager

        # Override dependency
        from shared.api.health import router
        from database import get_db

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        with patch("shared.api.health.get_db_manager", return_value=mock_manager):
            resp = client.get("/health/db")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    def test_db_unhealthy(self):
        from shared.api.health import router
        from database import get_db

        mock_db = MagicMock()
        mock_manager = MagicMock()
        mock_manager.health_check.return_value = False

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        with patch("shared.api.health.get_db_manager", return_value=mock_manager):
            resp = client.get("/health/db")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert data["database"] == "connection_failed"

    def test_db_exception(self):
        from shared.api.health import router
        from database import get_db

        mock_db = MagicMock()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        with patch("shared.api.health.get_db_manager", side_effect=RuntimeError("DB down")):
            resp = client.get("/health/db")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "DB down" in data["database"]


# ############################################################################
# PromptLoader Tests
# ############################################################################

class TestPromptLoaderClassMethods:
    """Tests for PromptLoader class methods (load, format, load_json)."""

    def setup_method(self):
        """Clear class-level cache before each test."""
        PromptLoader._cache.clear()

    def test_load_reads_file(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "greeting.txt").write_text("Hello {name}!")

        with patch.object(PromptLoader, "_cache", {}):
            with patch(
                "shared.prompts.loader.DEFAULT_PROMPTS_DIR", template_dir
            ):
                result = PromptLoader.load("greeting")
                assert result == "Hello {name}!"

    def test_load_caches_result(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "cached.txt").write_text("Cached content")

        with patch.object(PromptLoader, "_cache", {}):
            with patch(
                "shared.prompts.loader.DEFAULT_PROMPTS_DIR", template_dir
            ):
                result1 = PromptLoader.load("cached")
                result2 = PromptLoader.load("cached")
                assert result1 == result2 == "Cached content"

    def test_load_file_not_found_raises(self):
        with patch.object(PromptLoader, "_cache", {}):
            with patch(
                "shared.prompts.loader.DEFAULT_PROMPTS_DIR",
                Path("/nonexistent/path"),
            ):
                with pytest.raises(FileNotFoundError):
                    PromptLoader.load("missing_template")

    def test_format_interpolates_variables(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "hello.txt").write_text("Hello {name}, you are {age}!")

        with patch.object(PromptLoader, "_cache", {}):
            with patch(
                "shared.prompts.loader.DEFAULT_PROMPTS_DIR", template_dir
            ):
                result = PromptLoader.format("hello", name="Alice", age=30)
                assert result == "Hello Alice, you are 30!"

    def test_format_missing_variable_raises(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "needs_vars.txt").write_text("{required_var}")

        with patch.object(PromptLoader, "_cache", {}):
            with patch(
                "shared.prompts.loader.DEFAULT_PROMPTS_DIR", template_dir
            ):
                with pytest.raises(KeyError):
                    PromptLoader.format("needs_vars")

    def test_load_json_reads_json(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        data = {"key": "value", "nested": {"a": 1}}
        (template_dir / "config.json").write_text(json.dumps(data))

        with patch(
            "shared.prompts.loader.DEFAULT_PROMPTS_DIR", template_dir
        ):
            result = PromptLoader.load_json("config")
            assert result == data

    def test_load_json_invalid_json_raises(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "bad.json").write_text("NOT JSON")

        with patch(
            "shared.prompts.loader.DEFAULT_PROMPTS_DIR", template_dir
        ):
            with pytest.raises(json.JSONDecodeError):
                PromptLoader.load_json("bad")

    def test_load_json_missing_file_raises(self):
        with patch(
            "shared.prompts.loader.DEFAULT_PROMPTS_DIR",
            Path("/nonexistent"),
        ):
            with pytest.raises(FileNotFoundError):
                PromptLoader.load_json("missing")


class TestPromptLoaderInstanceMethods:
    """Tests for PromptLoader instance methods (load_template, render)."""

    def test_init_default_dir(self):
        loader = PromptLoader()
        assert loader._prompts_dir == DEFAULT_PROMPTS_DIR

    def test_init_custom_dir(self, tmp_path):
        loader = PromptLoader(prompts_dir=tmp_path)
        assert loader._prompts_dir == tmp_path

    def test_load_template(self, tmp_path):
        (tmp_path / "test.txt").write_text("Template content")
        loader = PromptLoader(prompts_dir=tmp_path)
        result = loader.load_template("test")
        assert result == "Template content"

    def test_load_template_caches(self, tmp_path):
        (tmp_path / "cached.txt").write_text("Cached")
        loader = PromptLoader(prompts_dir=tmp_path)
        r1 = loader.load_template("cached")
        r2 = loader.load_template("cached")
        assert r1 == r2 == "Cached"

    def test_load_template_missing_raises(self, tmp_path):
        loader = PromptLoader(prompts_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_template("nonexistent")

    def test_render(self, tmp_path):
        (tmp_path / "greeting.txt").write_text("Hello {name}, grade {grade}!")
        loader = PromptLoader(prompts_dir=tmp_path)
        result = loader.render("greeting", {"name": "Bob", "grade": 5})
        assert result == "Hello Bob, grade 5!"

    def test_render_missing_variable_raises(self, tmp_path):
        (tmp_path / "needs.txt").write_text("{required}")
        loader = PromptLoader(prompts_dir=tmp_path)
        with pytest.raises(KeyError):
            loader.render("needs", {})

    def test_different_instances_different_caches(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        (dir1 / "tmpl.txt").write_text("From dir1")

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        (dir2 / "tmpl.txt").write_text("From dir2")

        loader1 = PromptLoader(prompts_dir=dir1)
        loader2 = PromptLoader(prompts_dir=dir2)

        assert loader1.load_template("tmpl") == "From dir1"
        assert loader2.load_template("tmpl") == "From dir2"

    def test_render_multiline_template(self, tmp_path):
        template = "Line 1: {topic}\nLine 2: {subtopic}\nLine 3: done"
        (tmp_path / "multi.txt").write_text(template)
        loader = PromptLoader(prompts_dir=tmp_path)
        result = loader.render("multi", {"topic": "Math", "subtopic": "Fractions"})
        assert "Math" in result
        assert "Fractions" in result
        assert result.count("\n") == 2
