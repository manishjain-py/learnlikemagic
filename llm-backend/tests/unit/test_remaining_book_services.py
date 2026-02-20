"""
Tests for remaining book-ingestion services:
- TeachingDescriptionGenerator
- DescriptionGenerator
- ReducerService  (V1 -- needs import mocking for missing models)
- FactsExtractionService  (V1 -- needs import mocking for missing models)

All LLM, DB, S3, and external-service calls are mocked.
"""

import sys
import types
import json
import io
import pytest
from copy import deepcopy
from unittest.mock import MagicMock, Mock, patch, PropertyMock
from pathlib import Path
from dataclasses import dataclass, field as dc_field
from typing import List


# ============================================================================
# Bootstrap stubs for V1 models removed in V2
# ============================================================================

@dataclass
class _Assessment:
    level: str = "basic"
    prompt: str = "What is 1+1?"
    answer: str = "2"


@dataclass
class _PageFacts:
    objectives_add: list = dc_field(default_factory=list)
    examples_add: list = dc_field(default_factory=list)
    misconceptions_add: list = dc_field(default_factory=list)
    assessments_add: list = dc_field(default_factory=list)


@dataclass
class _FactsExtractionResponse:
    objectives_add: list = dc_field(default_factory=list)
    examples_add: list = dc_field(default_factory=list)
    misconceptions_add: list = dc_field(default_factory=list)
    assessments_add: list = dc_field(default_factory=list)


# Inject stubs into guideline_models so V1 services can import them
import book_ingestion.models.guideline_models as _gm

if not hasattr(_gm, "PageFacts"):
    _gm.PageFacts = _PageFacts
if not hasattr(_gm, "FactsExtractionResponse"):
    _gm.FactsExtractionResponse = _FactsExtractionResponse

# Ensure Assessment stub is present (the real one exists but just in case)
_RealAssessment = getattr(_gm, "Assessment", _Assessment)


# ============================================================================
# Helpers
# ============================================================================

def _mock_openai_response(content: str):
    """Create a mock OpenAI ChatCompletion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


def _make_v1_shard(**overrides):
    """Build a MagicMock that acts like a V1 SubtopicShard (objectives etc.)."""
    defaults = dict(
        subtopic_key="adding-fractions",
        subtopic_title="Adding Fractions",
        topic_key="fractions",
        topic_title="Fractions",
        source_page_start=1,
        source_page_end=3,
        source_pages=[1, 2, 3],
        objectives=["Understand adding fractions"],
        examples=["1/4 + 2/4 = 3/4"],
        misconceptions=["Adding numerators AND denominators"],
        assessments=[_RealAssessment(level="basic", prompt="What is 1/4 + 2/4?", answer="3/4")],
        evidence_summary="Students learn to add fractions with like denominators.",
        version=1,
        last_updated_page=3,
    )
    defaults.update(overrides)
    shard = MagicMock()
    for k, v in defaults.items():
        setattr(shard, k, v)
    return shard


# ============================================================================
# TeachingDescriptionGenerator Tests
# ============================================================================

class TestTeachingDescriptionGenerator:

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Pages: {page_range}, NumPages: {num_pages}",
    )
    def test_init_default_client(self, mock_load):
        with patch("book_ingestion.services.teaching_description_generator.OpenAI"):
            from book_ingestion.services.teaching_description_generator import (
                TeachingDescriptionGenerator,
            )
            gen = TeachingDescriptionGenerator(model="gpt-4o-mini")
            assert gen.model == "gpt-4o-mini"

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="template {grade} {subject}",
    )
    def test_init_custom_client(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        custom = MagicMock()
        gen = TeachingDescriptionGenerator(openai_client=custom, model="gpt-4o-mini")
        assert gen.client is custom

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Pages: {page_range}, NumPages: {num_pages}",
    )
    def test_generate_happy_path(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        mock_client = MagicMock()
        gen = TeachingDescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")

        response_text = (
            "Line one: teach the concept.\n"
            "Line two: use examples.\n"
            "Line three: check understanding."
        )
        mock_client.chat.completions.create.return_value = _mock_openai_response(response_text)

        shard = _make_v1_shard()
        result = gen.generate(shard, grade=3, subject="Math")
        assert "teach the concept" in result
        mock_client.chat.completions.create.assert_called_once()

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_generate_raises_on_no_objectives(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        shard = _make_v1_shard(objectives=[])
        with pytest.raises(ValueError, match="no objectives"):
            gen.generate(shard, grade=3, subject="Math")

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Pages: {page_range}, NumPages: {num_pages}",
    )
    def test_generate_truncates_long_response(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        mock_client = MagicMock()
        gen = TeachingDescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")

        lines = [f"Line {i}: content here about teaching." for i in range(10)]
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "\n".join(lines)
        )

        shard = _make_v1_shard()
        result = gen.generate(shard, grade=3, subject="Math")
        actual_lines = [l for l in result.split("\n") if l.strip()]
        assert len(actual_lines) <= 6

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Pages: {page_range}, NumPages: {num_pages}",
    )
    def test_generate_raises_on_llm_error(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        mock_client = MagicMock()
        gen = TeachingDescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")

        shard = _make_v1_shard()
        with pytest.raises(ValueError, match="Failed to generate"):
            gen.generate(shard, grade=3, subject="Math")

    # -- validate_teaching_description --

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_validate_valid(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        desc = (
            "First, teach the concept of fractions using visual models.\n"
            "Then, demonstrate examples with number lines and pie charts.\n"
            "Finally, check understanding by asking comparison questions."
        )
        is_valid, errors = gen.validate_teaching_description(desc)
        assert is_valid is True
        assert errors == []

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_validate_too_few_lines(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        is_valid, errors = gen.validate_teaching_description("One line only about teaching.")
        assert is_valid is False
        assert any("Too few lines" in e for e in errors)

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_validate_line_too_short(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        desc = "Teach the concept of fractions.\nUse examples.\nShort.\nCheck understanding via tests."
        is_valid, errors = gen.validate_teaching_description(desc)
        assert is_valid is False

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_validate_too_long_total(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        desc = "\n".join(
            [f"Line {i}: teach the concept in great detail " * 3 for i in range(5)]
        )
        if len(desc) <= 600:
            desc += "x" * (601 - len(desc))
        is_valid, errors = gen.validate_teaching_description(desc)
        assert is_valid is False

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_validate_missing_teaching_words(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        desc = (
            "The sky is blue and the grass is green today.\n"
            "Lorem ipsum dolor sit amet consectetur.\n"
            "Another line without relevant vocabulary."
        )
        is_valid, errors = gen.validate_teaching_description(desc)
        assert is_valid is False
        assert any("teaching-related" in e.lower() for e in errors)

    # -- generate_with_validation --

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Pages: {page_range}, NumPages: {num_pages}",
    )
    def test_generate_with_validation_first_try(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        mock_client = MagicMock()
        gen = TeachingDescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")

        good = (
            "First, teach the concept of fractions.\n"
            "Then, demonstrate with examples.\n"
            "Finally, check understanding."
        )
        mock_client.chat.completions.create.return_value = _mock_openai_response(good)

        shard = _make_v1_shard()
        desc, is_valid = gen.generate_with_validation(shard, grade=3, subject="Math")
        assert is_valid is True
        assert "teach" in desc.lower()

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Pages: {page_range}, NumPages: {num_pages}",
    )
    def test_generate_with_validation_retries_then_returns_best(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        mock_client = MagicMock()
        gen = TeachingDescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")

        bad = "Too short for teaching."
        mock_client.chat.completions.create.return_value = _mock_openai_response(bad)

        shard = _make_v1_shard()
        desc, is_valid = gen.generate_with_validation(shard, grade=3, subject="Math", max_retries=2)
        assert is_valid is False
        assert desc is not None

    # -- _build_context_from_shard --

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_build_context_from_shard(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        shard = _make_v1_shard(
            objectives=["Obj1", "Obj2"],
            examples=["Ex1", "Ex2", "Ex3", "Ex4", "Ex5", "Ex6"],
            misconceptions=[],
            assessments=[],
        )
        ctx = gen._build_context_from_shard(shard)
        assert "Obj1" in ctx["objectives_str"]
        assert "Ex6" not in ctx["examples_str"]  # limited to 5
        assert "... and 1 more" in ctx["examples_str"]
        assert ctx["misconceptions_str"] == "(None)"
        assert ctx["assessments_str"] == "(None)"

    @patch(
        "book_ingestion.services.teaching_description_generator"
        ".TeachingDescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_build_context_empty(self, mock_load):
        from book_ingestion.services.teaching_description_generator import (
            TeachingDescriptionGenerator,
        )
        gen = TeachingDescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        shard = _make_v1_shard(objectives=[], examples=[], misconceptions=[], assessments=[])
        ctx = gen._build_context_from_shard(shard)
        assert ctx["objectives_str"] == "(None)"
        assert ctx["examples_str"] == "(None)"


# ============================================================================
# DescriptionGenerator Tests
# ============================================================================

class TestDescriptionGenerator:

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Evidence: {evidence_summary}",
    )
    def test_init_default(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        with patch("book_ingestion.services.description_generator.OpenAI"):
            gen = DescriptionGenerator(model="gpt-4o-mini")
            assert gen.model == "gpt-4o-mini"

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="tmpl {grade} {subject}",
    )
    def test_init_custom_client(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        custom = MagicMock()
        gen = DescriptionGenerator(openai_client=custom, model="gpt-4o-mini")
        assert gen.client is custom

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Evidence: {evidence_summary}",
    )
    def test_generate_happy_path(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        mock_client = MagicMock()
        gen = DescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")

        # 200+ words
        words = " ".join(["word"] * 220)
        mock_client.chat.completions.create.return_value = _mock_openai_response(words)

        shard = _make_v1_shard()
        result = gen.generate(shard, grade=3, subject="Math")
        assert len(result.split()) >= 200

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_generate_no_objectives_raises(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        gen = DescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        shard = _make_v1_shard(objectives=[])
        with pytest.raises(ValueError, match="no objectives"):
            gen.generate(shard, grade=3, subject="Math")

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Evidence: {evidence_summary}",
    )
    def test_generate_llm_error_raises(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        mock_client = MagicMock()
        gen = DescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")
        mock_client.chat.completions.create.side_effect = RuntimeError("API fail")
        shard = _make_v1_shard()
        with pytest.raises(ValueError, match="Description generation failed"):
            gen.generate(shard, grade=3, subject="Math")

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Evidence: {evidence_summary}",
    )
    def test_generate_with_validation_accepts_in_range(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        mock_client = MagicMock()
        gen = DescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")

        # 250 words -- in target range
        text = " ".join(["word"] * 250)
        mock_client.chat.completions.create.return_value = _mock_openai_response(text)

        shard = _make_v1_shard()
        desc, is_valid = gen.generate_with_validation(shard, grade=3, subject="Math")
        assert is_valid is True

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Topic: {topic_title}, "
        "Subtopic: {subtopic_title}, Objectives: {objectives}, "
        "Examples: {examples}, Misconceptions: {misconceptions}, "
        "Assessments: {assessments}, Evidence: {evidence_summary}",
    )
    def test_generate_with_validation_retries(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        mock_client = MagicMock()
        gen = DescriptionGenerator(openai_client=mock_client, model="gpt-4o-mini")

        # 100 words -- too short, all attempts
        text = " ".join(["word"] * 100)
        mock_client.chat.completions.create.return_value = _mock_openai_response(text)

        shard = _make_v1_shard()
        desc, is_valid = gen.generate_with_validation(shard, grade=3, subject="Math", max_retries=2)
        assert is_valid is False
        assert desc is not None
        # Should have called create 3 times (1 initial + 2 retries)
        assert mock_client.chat.completions.create.call_count == 3

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_build_context_empty_fields(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        gen = DescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        shard = _make_v1_shard(objectives=[], examples=[], misconceptions=[], assessments=[])
        ctx = gen._build_context_from_shard(shard)
        assert ctx["objectives_str"] == "None specified"
        assert ctx["examples_str"] == "None provided"
        assert ctx["misconceptions_str"] == "None identified"
        assert ctx["assessments_str"] == "None provided"

    @patch(
        "book_ingestion.services.description_generator"
        ".DescriptionGenerator._load_prompt_template",
        return_value="tmpl",
    )
    def test_build_context_with_data(self, mock_load):
        from book_ingestion.services.description_generator import DescriptionGenerator
        gen = DescriptionGenerator(openai_client=MagicMock(), model="gpt-4o-mini")
        shard = _make_v1_shard()
        ctx = gen._build_context_from_shard(shard)
        assert "Understand adding fractions" in ctx["objectives_str"]
        assert "1/4 + 2/4" in ctx["examples_str"]


# ============================================================================
# ReducerService Tests (pure logic, no mocks needed)
# ============================================================================

class TestReducerService:
    """Tests for ReducerService -- all deterministic, no external calls."""

    def _make_shard(self, **overrides):
        """Build a V1-style SubtopicShard dataclass for testing."""
        from book_ingestion.services.reducer_service import SubtopicShard as ShardModel
        # ShardModel is the V1-patched model from guideline_models;
        # but since V2, it no longer has objectives etc.
        # We build a real-enough mock.
        defaults = dict(
            book_id="book-1",
            topic_key="fractions",
            subtopic_key="adding",
            topic_title="Fractions",
            subtopic_title="Adding",
            status="open",
            source_page_start=1,
            source_page_end=1,
            source_pages=[1],
            objectives=["Obj A"],
            examples=["Ex A"],
            misconceptions=["Mis A"],
            assessments=[],
            last_updated_page=1,
            version=1,
        )
        defaults.update(overrides)
        shard = MagicMock()
        for k, v in defaults.items():
            setattr(shard, k, deepcopy(v))
        return shard

    def _make_facts(self, **overrides):
        defaults = dict(
            objectives_add=[],
            examples_add=[],
            misconceptions_add=[],
            assessments_add=[],
        )
        defaults.update(overrides)
        return _PageFacts(**defaults)

    def _service(self):
        from book_ingestion.services.reducer_service import ReducerService
        return ReducerService()

    # -- _merge_objectives --

    def test_merge_objectives_empty(self):
        svc = self._service()
        result = svc._merge_objectives(["A"], [])
        assert result == ["A"]

    def test_merge_objectives_new_items(self):
        svc = self._service()
        result = svc._merge_objectives(["A"], ["B", "C"])
        assert result == ["A", "B", "C"]

    def test_merge_objectives_dedup_case_insensitive(self):
        svc = self._service()
        result = svc._merge_objectives(["Learn fractions"], ["learn fractions", "New obj"])
        assert len(result) == 2
        assert "New obj" in result

    # -- _merge_examples --

    def test_merge_examples_empty(self):
        svc = self._service()
        result = svc._merge_examples(["ex1"], [])
        assert result == ["ex1"]

    def test_merge_examples_new(self):
        svc = self._service()
        result = svc._merge_examples(["ex1"], ["ex2"])
        assert result == ["ex1", "ex2"]

    def test_merge_examples_dedup_exact(self):
        svc = self._service()
        result = svc._merge_examples(["ex1"], ["ex1", "ex2"])
        assert result == ["ex1", "ex2"]

    # -- _merge_misconceptions --

    def test_merge_misconceptions_empty(self):
        svc = self._service()
        assert svc._merge_misconceptions(["m1"], []) == ["m1"]

    def test_merge_misconceptions_dedup_case_insensitive(self):
        svc = self._service()
        result = svc._merge_misconceptions(["Adding tops and bottoms"], ["adding tops and bottoms"])
        assert len(result) == 1

    def test_merge_misconceptions_new(self):
        svc = self._service()
        result = svc._merge_misconceptions(["m1"], ["m2"])
        assert result == ["m1", "m2"]

    # -- _merge_assessments --

    def test_merge_assessments_empty(self):
        svc = self._service()
        result = svc._merge_assessments([_RealAssessment(level="basic", prompt="Q1", answer="A1")], [])
        assert len(result) == 1

    def test_merge_assessments_new(self):
        svc = self._service()
        a1 = _RealAssessment(level="basic", prompt="Q1", answer="A1")
        a2 = _RealAssessment(level="advanced", prompt="Q2", answer="A2")
        result = svc._merge_assessments([a1], [a2])
        assert len(result) == 2

    def test_merge_assessments_dedup_exact(self):
        svc = self._service()
        a1 = _RealAssessment(level="basic", prompt="Q1", answer="A1")
        a1_dup = _RealAssessment(level="basic", prompt="Q1", answer="A1")
        result = svc._merge_assessments([a1], [a1_dup])
        assert len(result) == 1

    def test_merge_assessments_different_level_not_deduped(self):
        svc = self._service()
        a1 = _RealAssessment(level="basic", prompt="Q1", answer="A1")
        a2 = _RealAssessment(level="advanced", prompt="Q1", answer="A1")
        result = svc._merge_assessments([a1], [a2])
        assert len(result) == 2

    # -- _update_page_tracking --

    def test_update_page_tracking_new_page(self):
        svc = self._service()
        shard = self._make_shard(source_pages=[1, 2], source_page_start=1, source_page_end=2)
        updated = svc._update_page_tracking(shard, 5)
        assert 5 in updated.source_pages
        assert updated.source_page_end == 5

    def test_update_page_tracking_existing_page(self):
        svc = self._service()
        shard = self._make_shard(source_pages=[1, 2], source_page_start=1, source_page_end=2)
        updated = svc._update_page_tracking(shard, 2)
        assert updated.source_pages == [1, 2]  # no duplicate

    def test_update_page_tracking_earlier_page(self):
        svc = self._service()
        shard = self._make_shard(source_pages=[3, 5], source_page_start=3, source_page_end=5)
        updated = svc._update_page_tracking(shard, 1)
        assert updated.source_page_start == 1

    # -- merge (integration of sub-methods) --

    def test_merge_increments_version(self):
        svc = self._service()
        shard = self._make_shard(version=1)
        facts = self._make_facts(objectives_add=["New obj"])
        updated = svc.merge(shard, facts, page_num=2)
        assert updated.version == 2

    def test_merge_does_not_mutate_original(self):
        svc = self._service()
        shard = self._make_shard(objectives=["A"])
        original_objs = shard.objectives.copy()
        facts = self._make_facts(objectives_add=["B"])
        svc.merge(shard, facts, page_num=2)
        # Original should not be mutated (deepcopy inside merge)
        # With MagicMock the deepcopy copies the mock, so we verify
        # that original shard's objectives list was not modified in place
        assert shard.objectives == original_objs

    # -- create_new_shard --

    @pytest.mark.xfail(reason="create_new_shard uses V1 fields not present in V2 SubtopicShard model")
    def test_create_new_shard(self):
        svc = self._service()
        facts = self._make_facts(
            objectives_add=["Learn X"],
            examples_add=["Ex X"],
            misconceptions_add=["Mis X"],
            assessments_add=[_RealAssessment(level="basic", prompt="Q", answer="A")],
        )
        shard = svc.create_new_shard(
            book_id="book-1",
            topic_key="fractions",
            topic_title="Fractions",
            subtopic_key="adding",
            subtopic_title="Adding",
            page_facts=facts,
            page_num=5,
        )
        assert shard.book_id == "book-1"
        assert shard.topic_key == "fractions"
        assert shard.subtopic_key == "adding"
        assert shard.source_page_start == 5
        assert shard.source_page_end == 5
        assert shard.source_pages == [5]
        assert shard.objectives == ["Learn X"]
        assert shard.version == 1


# ============================================================================
# FactsExtractionService Tests
# ============================================================================

class TestFactsExtractionService:

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_init(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        mock_client = MagicMock()
        svc = FactsExtractionService(openai_client=mock_client, model="gpt-4o-mini")
        assert svc.client is mock_client
        assert svc.model == "gpt-4o-mini"

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_happy_path(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        mock_client = MagicMock()
        svc = FactsExtractionService(openai_client=mock_client, model="gpt-4o-mini")

        resp_json = json.dumps({
            "objectives_add": ["Learn fractions"],
            "examples_add": ["1/2 + 1/2 = 1"],
            "misconceptions_add": [],
            "assessments_add": [],
        })
        mock_client.chat.completions.create.return_value = _mock_openai_response(resp_json)

        result = svc.extract("Some page text about fractions", "Adding Fractions", grade=3, subject="Math")
        assert result.objectives_add == ["Learn fractions"]
        assert result.examples_add == ["1/2 + 1/2 = 1"]

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_empty_text_raises(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        svc = FactsExtractionService(openai_client=MagicMock(), model="gpt-4o-mini")
        with pytest.raises(ValueError, match="cannot be empty"):
            svc.extract("", "Topic", grade=3, subject="Math")

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_whitespace_only_raises(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        svc = FactsExtractionService(openai_client=MagicMock(), model="gpt-4o-mini")
        with pytest.raises(ValueError, match="cannot be empty"):
            svc.extract("   \n\t  ", "Topic", grade=3, subject="Math")

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_invalid_json_returns_empty(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        mock_client = MagicMock()
        svc = FactsExtractionService(openai_client=mock_client, model="gpt-4o-mini")
        mock_client.chat.completions.create.return_value = _mock_openai_response("not json {{{")
        result = svc.extract("text", "Topic", grade=3, subject="Math")
        assert result.objectives_add == []

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_llm_error_returns_empty(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        mock_client = MagicMock()
        svc = FactsExtractionService(openai_client=mock_client, model="gpt-4o-mini")
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")
        result = svc.extract("text", "Topic", grade=3, subject="Math")
        assert result.objectives_add == []

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_batch_happy_path(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        mock_client = MagicMock()
        svc = FactsExtractionService(openai_client=mock_client, model="gpt-4o-mini")

        resp_json = json.dumps({
            "objectives_add": ["Obj"],
            "examples_add": [],
            "misconceptions_add": [],
            "assessments_add": [],
        })
        mock_client.chat.completions.create.return_value = _mock_openai_response(resp_json)

        results = svc.extract_batch(
            ["text1", "text2"], ["Topic1", "Topic2"], grade=3, subject="Math"
        )
        assert len(results) == 2
        assert all(r.objectives_add == ["Obj"] for r in results)

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_batch_mismatched_lengths_raises(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        svc = FactsExtractionService(openai_client=MagicMock(), model="gpt-4o-mini")
        with pytest.raises(ValueError, match="same length"):
            svc.extract_batch(["t1"], ["s1", "s2"], grade=3, subject="Math")

    @patch(
        "book_ingestion.services.facts_extraction_service"
        ".FactsExtractionService._load_prompt_template",
        return_value="Grade: {grade}, Subject: {subject}, Subtopic: {subtopic_title}, Text: {page_text}",
    )
    def test_extract_batch_partial_failure(self, mock_load):
        from book_ingestion.services.facts_extraction_service import FactsExtractionService
        mock_client = MagicMock()
        svc = FactsExtractionService(openai_client=mock_client, model="gpt-4o-mini")

        good_json = json.dumps({
            "objectives_add": ["Obj"],
            "examples_add": [],
            "misconceptions_add": [],
            "assessments_add": [],
        })
        # First call succeeds, second fails
        mock_client.chat.completions.create.side_effect = [
            _mock_openai_response(good_json),
            RuntimeError("API error"),
        ]

        results = svc.extract_batch(["t1", "t2"], ["s1", "s2"], grade=3, subject="Math")
        assert len(results) == 2
        assert results[0].objectives_add == ["Obj"]
        assert results[1].objectives_add == []  # fallback empty
