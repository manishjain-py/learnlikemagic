"""Unit tests for shared/repositories/guideline_repository.py

Tests TeachingGuidelineRepository query and metadata-parsing operations
using an in-memory SQLite database.
All database interactions go through the db_session fixture from conftest.py.
"""

import json
import pytest

from shared.repositories.guideline_repository import TeachingGuidelineRepository
from shared.models.entities import TeachingGuideline
from shared.models.domain import GuidelineMetadata
from shared.models.schemas import GuidelineResponse, SubtopicInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_METADATA = {
    "learning_objectives": ["Compare fractions"],
    "depth_level": "intermediate",
    "prerequisites": ["counting"],
    "common_misconceptions": ["bigger is better"],
    "scaffolding_strategies": ["Use visuals"],
}

_SENTINEL = object()


def _make_guideline(
    id: str = "g1",
    country: str = "India",
    board: str = "CBSE",
    grade: int = 3,
    subject: str = "Mathematics",
    topic: str = "Fractions",
    subtopic: str = "Comparing",
    guideline_text: str = "Teach fractions comparison...",
    review_status: str = "APPROVED",
    metadata_json: str | None = _SENTINEL,
) -> TeachingGuideline:
    """Build a TeachingGuideline entity with sensible defaults."""
    if metadata_json is _SENTINEL:
        metadata_json = json.dumps(_VALID_METADATA)
    return TeachingGuideline(
        id=id,
        country=country,
        board=board,
        grade=grade,
        subject=subject,
        topic=topic,
        subtopic=subtopic,
        guideline=guideline_text,
        review_status=review_status,
        metadata_json=metadata_json,
    )


def _seed(db_session, *guidelines: TeachingGuideline) -> None:
    """Add guidelines to the database and commit."""
    for g in guidelines:
        db_session.add(g)
    db_session.commit()


# ===========================================================================
# _parse_metadata
# ===========================================================================

class TestParseMetadata:
    def test_valid_json_returns_guideline_metadata(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        result = repo._parse_metadata(json.dumps(_VALID_METADATA))

        assert isinstance(result, GuidelineMetadata)
        assert result.learning_objectives == ["Compare fractions"]
        assert result.depth_level == "intermediate"
        assert result.prerequisites == ["counting"]
        assert result.common_misconceptions == ["bigger is better"]
        assert result.scaffolding_strategies == ["Use visuals"]

    def test_invalid_json_returns_none(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        result = repo._parse_metadata("{not valid json")
        assert result is None

    def test_none_input_returns_none(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        result = repo._parse_metadata(None)
        assert result is None

    def test_empty_string_returns_none(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        result = repo._parse_metadata("")
        assert result is None

    def test_partial_metadata_uses_defaults(self, db_session):
        """Missing optional fields should get default values from the model."""
        repo = TeachingGuidelineRepository(db_session)
        partial = json.dumps({"learning_objectives": ["LO1"]})
        result = repo._parse_metadata(partial)

        assert result is not None
        assert result.learning_objectives == ["LO1"]
        assert result.depth_level == "intermediate"  # default
        assert result.prerequisites == []  # default
        assert result.common_misconceptions == []  # default
        assert result.scaffolding_strategies == []  # default


# ===========================================================================
# get_guideline
# ===========================================================================

class TestGetGuideline:
    def test_returns_matching_approved_guideline(self, db_session):
        _seed(db_session, _make_guideline(id="g1"))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline("India", "CBSE", 3, "Mathematics", "Fractions", "Comparing")

        assert result is not None
        assert isinstance(result, GuidelineResponse)
        assert result.id == "g1"
        assert result.country == "India"
        assert result.board == "CBSE"
        assert result.grade == 3
        assert result.subject == "Mathematics"
        assert result.topic == "Fractions"
        assert result.subtopic == "Comparing"
        assert result.guideline == "Teach fractions comparison..."

    def test_returns_none_for_nonexistent(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        result = repo.get_guideline("India", "CBSE", 3, "Mathematics", "Fractions", "Comparing")
        assert result is None

    def test_non_approved_not_returned(self, db_session):
        _seed(db_session, _make_guideline(id="g-pending", review_status="TO_BE_REVIEWED"))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline("India", "CBSE", 3, "Mathematics", "Fractions", "Comparing")
        assert result is None

    def test_includes_parsed_metadata(self, db_session):
        _seed(db_session, _make_guideline(id="g1"))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline("India", "CBSE", 3, "Mathematics", "Fractions", "Comparing")

        assert result.metadata is not None
        assert isinstance(result.metadata, GuidelineMetadata)
        assert result.metadata.learning_objectives == ["Compare fractions"]

    def test_no_match_on_wrong_subject(self, db_session):
        _seed(db_session, _make_guideline(id="g1", subject="Mathematics"))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline("India", "CBSE", 3, "Science", "Fractions", "Comparing")
        assert result is None

    def test_no_match_on_wrong_grade(self, db_session):
        _seed(db_session, _make_guideline(id="g1", grade=3))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline("India", "CBSE", 5, "Mathematics", "Fractions", "Comparing")
        assert result is None


# ===========================================================================
# get_guideline_by_id
# ===========================================================================

class TestGetGuidelineById:
    def test_returns_approved_guideline_by_id(self, db_session):
        _seed(db_session, _make_guideline(id="g42"))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline_by_id("g42")

        assert result is not None
        assert result.id == "g42"
        assert isinstance(result, GuidelineResponse)

    def test_returns_none_for_unknown_id(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        result = repo.get_guideline_by_id("nonexistent")
        assert result is None

    def test_non_approved_not_returned_by_id(self, db_session):
        _seed(db_session, _make_guideline(id="g-draft", review_status="TO_BE_REVIEWED"))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline_by_id("g-draft")
        assert result is None

    def test_metadata_included_in_response(self, db_session):
        _seed(db_session, _make_guideline(id="g1"))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline_by_id("g1")
        assert result.metadata is not None
        assert result.metadata.depth_level == "intermediate"

    def test_null_metadata_returns_none_metadata(self, db_session):
        _seed(db_session, _make_guideline(id="g-no-meta", metadata_json=None))
        repo = TeachingGuidelineRepository(db_session)

        result = repo.get_guideline_by_id("g-no-meta")
        assert result is not None
        assert result.metadata is None


# ===========================================================================
# get_subjects
# ===========================================================================

class TestGetSubjects:
    def test_returns_distinct_subjects(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", subject="Mathematics", topic="Fractions", subtopic="Comparing"),
            _make_guideline(id="g2", subject="Mathematics", topic="Fractions", subtopic="Adding"),
            _make_guideline(id="g3", subject="Science", topic="Plants", subtopic="Parts"),
        )
        repo = TeachingGuidelineRepository(db_session)

        subjects = repo.get_subjects("India", "CBSE", 3)
        assert sorted(subjects) == ["Mathematics", "Science"]

    def test_returns_empty_when_no_match(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        subjects = repo.get_subjects("India", "CBSE", 99)
        assert subjects == []

    def test_excludes_non_approved(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", subject="Mathematics", review_status="APPROVED"),
            _make_guideline(id="g2", subject="Science", review_status="TO_BE_REVIEWED"),
        )
        repo = TeachingGuidelineRepository(db_session)

        subjects = repo.get_subjects("India", "CBSE", 3)
        assert subjects == ["Mathematics"]

    def test_filters_by_country_and_board(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", country="India", board="CBSE", subject="Mathematics"),
            _make_guideline(id="g2", country="India", board="ICSE", subject="Science"),
        )
        repo = TeachingGuidelineRepository(db_session)

        subjects = repo.get_subjects("India", "CBSE", 3)
        assert subjects == ["Mathematics"]


# ===========================================================================
# get_topics
# ===========================================================================

class TestGetTopics:
    def test_returns_distinct_topics(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", topic="Fractions", subtopic="Comparing"),
            _make_guideline(id="g2", topic="Fractions", subtopic="Adding"),
            _make_guideline(id="g3", topic="Geometry", subtopic="Shapes"),
        )
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics")
        assert sorted(topics) == ["Fractions", "Geometry"]

    def test_returns_empty_when_no_match(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        topics = repo.get_topics("India", "CBSE", 3, "History")
        assert topics == []

    def test_excludes_non_approved(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", topic="Fractions", review_status="APPROVED"),
            _make_guideline(id="g2", topic="Geometry", review_status="TO_BE_REVIEWED"),
        )
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics")
        assert topics == ["Fractions"]


# ===========================================================================
# get_subtopics
# ===========================================================================

class TestGetSubtopics:
    def test_returns_subtopic_info_list(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", subtopic="Comparing"),
            _make_guideline(id="g2", subtopic="Adding"),
        )
        repo = TeachingGuidelineRepository(db_session)

        subtopics = repo.get_subtopics("India", "CBSE", 3, "Mathematics", "Fractions")

        assert len(subtopics) == 2
        assert all(isinstance(s, SubtopicInfo) for s in subtopics)

        subtopic_names = [s.subtopic for s in subtopics]
        assert "Comparing" in subtopic_names
        assert "Adding" in subtopic_names

    def test_subtopics_have_guideline_ids(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g10", subtopic="Comparing"),
        )
        repo = TeachingGuidelineRepository(db_session)

        subtopics = repo.get_subtopics("India", "CBSE", 3, "Mathematics", "Fractions")
        assert subtopics[0].guideline_id == "g10"

    def test_returns_empty_when_no_match(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        subtopics = repo.get_subtopics("India", "CBSE", 3, "Mathematics", "NoSuchTopic")
        assert subtopics == []

    def test_excludes_non_approved(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", subtopic="Comparing", review_status="APPROVED"),
            _make_guideline(id="g2", subtopic="Adding", review_status="TO_BE_REVIEWED"),
        )
        repo = TeachingGuidelineRepository(db_session)

        subtopics = repo.get_subtopics("India", "CBSE", 3, "Mathematics", "Fractions")
        assert len(subtopics) == 1
        assert subtopics[0].subtopic == "Comparing"

    def test_subtopics_ordered_alphabetically(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", subtopic="Zebra"),
            _make_guideline(id="g2", subtopic="Apple"),
            _make_guideline(id="g3", subtopic="Mango"),
        )
        repo = TeachingGuidelineRepository(db_session)

        subtopics = repo.get_subtopics("India", "CBSE", 3, "Mathematics", "Fractions")
        names = [s.subtopic for s in subtopics]
        assert names == ["Apple", "Mango", "Zebra"]
