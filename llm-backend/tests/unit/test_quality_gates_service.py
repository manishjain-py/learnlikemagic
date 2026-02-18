"""
Tests for QualityGatesService — validation logic and scoring.

The V1 QualityGatesService references models (QualityFlags, etc.) that were
removed in V2. We mock the module imports so the service can still be loaded
and tested in isolation.
"""

import sys
import types
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Bootstrap: inject missing V1 model stubs so the module can import
# ---------------------------------------------------------------------------

@dataclass
class _QualityFlags:
    passed_validation: bool = False
    quality_score: float = 0.0
    validation_errors: list = None
    validation_warnings: list = None

    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []
        if self.validation_warnings is None:
            self.validation_warnings = []


# Patch the models module BEFORE importing the service
import book_ingestion.models.guideline_models as _gm

_gm.QualityFlags = _QualityFlags  # inject the missing symbol

from book_ingestion.services.quality_gates_service import (
    QualityGatesService,
    ValidationResult,
)
from book_ingestion.models.guideline_models import SubtopicShard, Assessment


# ---------------------------------------------------------------------------
# Helpers: build V1-style mock shards
# ---------------------------------------------------------------------------

def _make_assessment(level="basic", prompt="What is 1+1?", answer="2"):
    return MagicMock(level=level, prompt=prompt, answer=answer)


def _make_shard(
    objectives=None,
    examples=None,
    misconceptions=None,
    assessments=None,
    teaching_description=None,
    source_pages=None,
    source_page_start=1,
    source_page_end=3,
    subtopic_key="fractions-basics",
    subtopic_title="Fractions Basics",
    topic_title="Fractions",
    topic_key="fractions",
    status="stable",
    version=1,
):
    shard = MagicMock()
    shard.objectives = objectives if objectives is not None else ["Learn fractions", "Identify numerators"]
    shard.examples = examples if examples is not None else ["1/2 pizza"]
    shard.misconceptions = misconceptions if misconceptions is not None else ["Bigger denominator = bigger fraction"]
    shard.assessments = assessments if assessments is not None else [_make_assessment()]
    shard.teaching_description = teaching_description
    shard.source_pages = source_pages if source_pages is not None else [1, 2, 3]
    shard.source_page_start = source_page_start
    shard.source_page_end = source_page_end
    shard.subtopic_key = subtopic_key
    shard.subtopic_title = subtopic_title
    shard.topic_title = topic_title
    shard.topic_key = topic_key
    shard.status = status
    shard.version = version
    return shard


# ---------------------------------------------------------------------------
# Tests: initialization
# ---------------------------------------------------------------------------

class TestQualityGatesInit:
    def test_default_thresholds(self):
        svc = QualityGatesService()
        assert svc.min_objectives == 2
        assert svc.min_examples == 1
        assert svc.min_misconceptions == 1
        assert svc.min_assessments == 1

    def test_custom_thresholds(self):
        svc = QualityGatesService(
            min_objectives=5,
            min_examples=3,
            min_misconceptions=2,
            min_assessments=4,
        )
        assert svc.min_objectives == 5
        assert svc.min_examples == 3
        assert svc.min_misconceptions == 2
        assert svc.min_assessments == 4


# ---------------------------------------------------------------------------
# Tests: validate — fact completeness
# ---------------------------------------------------------------------------

class TestValidateFacts:
    def test_valid_shard_passes(self):
        svc = QualityGatesService()
        desc = (
            "Teach fractions step by step.\n"
            "Explain numerator and denominator.\n"
            "Check understanding with examples.\n"
        )
        shard = _make_shard(teaching_description=desc * 2)
        result = svc.validate(shard)
        assert result.is_valid is True
        assert result.quality_score > 0

    def test_insufficient_objectives_produces_error(self):
        svc = QualityGatesService()
        shard = _make_shard(
            objectives=["Only one"],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert not result.is_valid
        assert any("objectives" in e.lower() for e in result.errors)

    def test_insufficient_examples_produces_error(self):
        svc = QualityGatesService(min_examples=2)
        shard = _make_shard(
            examples=["only one"],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("examples" in e.lower() for e in result.errors)

    def test_insufficient_misconceptions_produces_error(self):
        svc = QualityGatesService(min_misconceptions=2)
        shard = _make_shard(
            misconceptions=["only one"],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("misconceptions" in e.lower() for e in result.errors)

    def test_insufficient_assessments_produces_error(self):
        svc = QualityGatesService(min_assessments=2)
        shard = _make_shard(
            assessments=[_make_assessment()],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("assessments" in e.lower() for e in result.errors)

    def test_few_objectives_generates_warning(self):
        """2 objectives pass the min=2 threshold but generate a 'few objectives' warning."""
        svc = QualityGatesService()
        shard = _make_shard(
            objectives=["a", "b"],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("few objectives" in w.lower() for w in result.warnings)

    def test_few_examples_generates_warning(self):
        """1 example passes the min=1 threshold but generates a 'few examples' warning."""
        svc = QualityGatesService()
        shard = _make_shard(
            examples=["one example"],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("few examples" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Tests: validate — teaching description
# ---------------------------------------------------------------------------

class TestValidateTeachingDescription:
    def test_missing_description_is_error(self):
        svc = QualityGatesService()
        shard = _make_shard(teaching_description=None)
        result = svc.validate(shard)
        assert not result.is_valid
        assert any("missing teaching description" in e.lower() for e in result.errors)

    def test_empty_description_is_error(self):
        svc = QualityGatesService()
        shard = _make_shard(teaching_description="")
        result = svc.validate(shard)
        assert not result.is_valid
        assert any("missing teaching description" in e.lower() for e in result.errors)

    def test_description_too_short(self):
        svc = QualityGatesService()
        shard = _make_shard(teaching_description="Too short.\nReally.\nYes.\n")
        result = svc.validate(shard)
        assert any("too short" in e.lower() for e in result.errors)

    def test_description_too_long(self):
        svc = QualityGatesService()
        long_desc = "Teach this concept about fractions.\n" * 20  # well over 600 chars
        shard = _make_shard(teaching_description=long_desc)
        result = svc.validate(shard)
        assert any("too long" in w.lower() for w in result.warnings)

    def test_description_too_few_lines(self):
        svc = QualityGatesService()
        # 2 non-empty lines, each long enough to pass length check (>100 chars total)
        desc = "Teach the concept of fraction addition step by step with examples.\n" \
               "Show how numerators are added when denominators are the same.\n"
        shard = _make_shard(teaching_description=desc)
        result = svc.validate(shard)
        assert any("too few lines" in e.lower() for e in result.errors)

    def test_description_too_many_lines_warning(self):
        svc = QualityGatesService()
        desc = "\n".join([f"Line {i} about teaching fractions concept" for i in range(8)])
        shard = _make_shard(teaching_description=desc)
        result = svc.validate(shard)
        assert any("too many lines" in w.lower() for w in result.warnings)

    def test_missing_teaching_vocabulary_warning(self):
        svc = QualityGatesService()
        # No teaching-related words at all
        desc = "Alpha beta gamma delta.\nEpsilon zeta eta theta.\nIota kappa lambda mu.\n"
        # Make it long enough
        desc = desc * 4
        shard = _make_shard(teaching_description=desc)
        result = svc.validate(shard)
        assert any("vocabulary" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Tests: validate — content volume
# ---------------------------------------------------------------------------

class TestValidateContentVolume:
    def test_no_pages_error(self):
        svc = QualityGatesService()
        shard = _make_shard(
            source_pages=[],
            source_page_start=0,
            source_page_end=0,
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("too few pages" in e.lower() for e in result.errors)

    def test_many_pages_warning(self):
        svc = QualityGatesService()
        pages = list(range(1, 20))
        shard = _make_shard(
            source_pages=pages,
            source_page_start=1,
            source_page_end=19,
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("many pages" in w.lower() for w in result.warnings)

    def test_invalid_page_range_error(self):
        svc = QualityGatesService()
        shard = _make_shard(
            source_page_start=10,
            source_page_end=5,
            source_pages=[10, 9, 8, 7, 6, 5],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("invalid page range" in e.lower() for e in result.errors)

    def test_non_contiguous_pages_warning(self):
        svc = QualityGatesService()
        shard = _make_shard(
            source_pages=[1, 3, 5],
            source_page_start=1,
            source_page_end=5,
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("non-contiguous" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Tests: validate — assessment diversity
# ---------------------------------------------------------------------------

class TestValidateAssessmentDiversity:
    def test_no_basic_level_warning(self):
        svc = QualityGatesService()
        shard = _make_shard(
            assessments=[_make_assessment("proficient"), _make_assessment("advanced")],
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("no basic" in w.lower() for w in result.warnings)

    def test_skewed_assessments_warning(self):
        svc = QualityGatesService()
        shard = _make_shard(
            assessments=[_make_assessment("basic")] * 4,
            teaching_description="Teach fractions step by step.\nExplain numerator.\nCheck understanding.\n" * 2,
        )
        result = svc.validate(shard)
        assert any("skewed" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Tests: quality score
# ---------------------------------------------------------------------------

class TestQualityScore:
    def test_perfect_shard_high_score(self):
        svc = QualityGatesService()
        desc = (
            "Teach fractions by explaining the concept of parts of a whole.\n"
            "Demonstrate using visual examples such as pizza slices.\n"
            "Check understanding through practice problems.\n"
            "Address the misconception that bigger denominators mean bigger fractions.\n"
        )
        shard = _make_shard(
            objectives=["A", "B", "C", "D"],
            examples=["1", "2", "3", "4", "5"],
            misconceptions=["m1"],
            assessments=[
                _make_assessment("basic"),
                _make_assessment("proficient"),
                _make_assessment("advanced"),
                _make_assessment("basic"),
                _make_assessment("proficient"),
            ],
            teaching_description=desc,
        )
        result = svc.validate(shard)
        assert result.is_valid
        assert result.quality_score >= 0.9

    def test_errors_reduce_score(self):
        svc = QualityGatesService()
        shard = _make_shard(
            objectives=[],
            examples=[],
            misconceptions=[],
            assessments=[],
            teaching_description=None,
            source_pages=[],
            source_page_start=0,
            source_page_end=0,
        )
        result = svc.validate(shard)
        # Many errors: objectives, examples, misconceptions, assessments, teaching desc, pages
        assert not result.is_valid
        assert result.quality_score <= 0.5

    def test_score_clamped_to_0_1(self):
        svc = QualityGatesService()
        # Many errors to drive score negative before clamping
        shard = _make_shard(
            objectives=[],
            examples=[],
            misconceptions=[],
            assessments=[],
            source_pages=[],
            source_page_start=10,
            source_page_end=2,
            teaching_description=None,
        )
        result = svc.validate(shard)
        assert 0.0 <= result.quality_score <= 1.0


# ---------------------------------------------------------------------------
# Tests: update_quality_flags
# ---------------------------------------------------------------------------

class TestUpdateQualityFlags:
    def test_valid_result_changes_status_to_final(self):
        svc = QualityGatesService()
        shard = _make_shard(status="stable", version=1)
        result = ValidationResult(is_valid=True, errors=[], warnings=[], quality_score=0.9)
        updated = svc.update_quality_flags(shard, result)
        assert updated.status == "final"
        assert updated.version == 2

    def test_invalid_result_changes_status_to_needs_review(self):
        svc = QualityGatesService()
        shard = _make_shard(status="stable", version=1)
        result = ValidationResult(
            is_valid=False,
            errors=["Missing objectives"],
            warnings=[],
            quality_score=0.3,
        )
        updated = svc.update_quality_flags(shard, result)
        assert updated.status == "needs_review"
        assert updated.version == 2

    def test_does_not_mutate_original(self):
        svc = QualityGatesService()
        shard = _make_shard(status="stable", version=1)
        result = ValidationResult(is_valid=True, errors=[], warnings=[], quality_score=0.9)
        updated = svc.update_quality_flags(shard, result)
        assert shard.version == 1  # original unchanged


# ---------------------------------------------------------------------------
# Tests: get_validation_summary
# ---------------------------------------------------------------------------

class TestGetValidationSummary:
    def test_returns_expected_keys(self):
        svc = QualityGatesService()
        desc = (
            "Teach fractions step by step.\n"
            "Explain numerator and denominator.\n"
            "Check understanding with examples.\n"
        )
        shard = _make_shard(teaching_description=desc * 2)
        summary = svc.get_validation_summary(shard)
        assert "subtopic_key" in summary
        assert "is_valid" in summary
        assert "quality_score" in summary
        assert "stats" in summary
        assert "objectives" in summary["stats"]
        assert "page_range" in summary["stats"]
