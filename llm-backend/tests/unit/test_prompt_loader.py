"""
Tests for shared/prompts/loader.py

Covers: PromptLoader.load (classmethod), load_template (instance),
        format, render, load_json, caching, and error cases.
"""

import json
import pytest
from pathlib import Path

from shared.prompts.loader import PromptLoader


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def clear_class_cache():
    """Clear class-level cache before each test to ensure isolation."""
    PromptLoader._cache.clear()
    yield
    PromptLoader._cache.clear()


@pytest.fixture
def templates_dir(tmp_path):
    """Create a temporary directory with sample template files."""
    # .txt template
    (tmp_path / "greeting.txt").write_text("Hello, {name}! Welcome to {place}.", encoding="utf-8")
    # .txt simple template
    (tmp_path / "simple.txt").write_text("Just a plain template.", encoding="utf-8")
    # .json template
    (tmp_path / "config.json").write_text(
        json.dumps({"model": "gpt-4", "temperature": 0.5}), encoding="utf-8"
    )
    return tmp_path


# ===========================================================================
# PromptLoader.load (classmethod) -- uses DEFAULT_PROMPTS_DIR
# ===========================================================================

class TestLoad:

    def test_load_existing_template(self, tmp_path, monkeypatch):
        """Load a template from the default directory."""
        (tmp_path / "test_tmpl.txt").write_text("Hello world", encoding="utf-8")
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)

        result = PromptLoader.load("test_tmpl")
        assert result == "Hello world"

    def test_load_caches_result(self, tmp_path, monkeypatch):
        """Second load should come from cache."""
        (tmp_path / "cached.txt").write_text("cached content", encoding="utf-8")
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)

        r1 = PromptLoader.load("cached")
        r2 = PromptLoader.load("cached")
        assert r1 == r2 == "cached content"
        assert "cached" in PromptLoader._cache

    def test_load_file_not_found(self, tmp_path, monkeypatch):
        """Loading a nonexistent template raises FileNotFoundError."""
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            PromptLoader.load("nonexistent")


# ===========================================================================
# PromptLoader.load_template (instance method) -- uses custom dir
# ===========================================================================

class TestLoadTemplate:

    def test_load_template_from_custom_dir(self, templates_dir):
        loader = PromptLoader(prompts_dir=templates_dir)
        result = loader.load_template("simple")
        assert result == "Just a plain template."

    def test_load_template_caches(self, templates_dir):
        loader = PromptLoader(prompts_dir=templates_dir)
        r1 = loader.load_template("simple")
        r2 = loader.load_template("simple")
        assert r1 == r2

    def test_load_template_file_not_found(self, tmp_path):
        loader = PromptLoader(prompts_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_template("missing")


# ===========================================================================
# PromptLoader.format (classmethod)
# ===========================================================================

class TestFormat:

    def test_format_with_variables(self, tmp_path, monkeypatch):
        (tmp_path / "greet.txt").write_text("Hello {name}, you are in grade {grade}.", encoding="utf-8")
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)

        result = PromptLoader.format("greet", name="Alice", grade=3)
        assert result == "Hello Alice, you are in grade 3."

    def test_format_missing_variable_raises(self, tmp_path, monkeypatch):
        (tmp_path / "needs_var.txt").write_text("Hello {name}!", encoding="utf-8")
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)

        with pytest.raises(KeyError):
            PromptLoader.format("needs_var")  # missing 'name'


# ===========================================================================
# PromptLoader.render (instance method)
# ===========================================================================

class TestRender:

    def test_render_with_variables(self, templates_dir):
        loader = PromptLoader(prompts_dir=templates_dir)
        result = loader.render("greeting", {"name": "Bob", "place": "School"})
        assert result == "Hello, Bob! Welcome to School."

    def test_render_missing_variable_raises(self, templates_dir):
        loader = PromptLoader(prompts_dir=templates_dir)
        with pytest.raises(KeyError):
            loader.render("greeting", {"name": "Bob"})  # missing 'place'


# ===========================================================================
# PromptLoader.load_json (classmethod)
# ===========================================================================

class TestLoadJson:

    def test_load_json_existing(self, tmp_path, monkeypatch):
        data = {"key": "value", "nested": {"a": 1}}
        (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)

        result = PromptLoader.load_json("data")
        assert result == data

    def test_load_json_file_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            PromptLoader.load_json("missing")

    def test_load_json_invalid_json(self, tmp_path, monkeypatch):
        (tmp_path / "bad.json").write_text("not json {{{", encoding="utf-8")
        monkeypatch.setattr("shared.prompts.loader.DEFAULT_PROMPTS_DIR", tmp_path)
        with pytest.raises(json.JSONDecodeError):
            PromptLoader.load_json("bad")


# ===========================================================================
# Constructor defaults
# ===========================================================================

class TestConstructor:

    def test_default_prompts_dir(self):
        loader = PromptLoader()
        from shared.prompts.loader import DEFAULT_PROMPTS_DIR
        assert loader._prompts_dir == DEFAULT_PROMPTS_DIR

    def test_custom_prompts_dir(self, tmp_path):
        loader = PromptLoader(prompts_dir=tmp_path)
        assert loader._prompts_dir == tmp_path
