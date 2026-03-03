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
from shared.models.schemas import GuidelineResponse, TopicInfo, ChapterInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_METADATA = {
    "learning_objectives": ["Compare fractions"],
    "depth_level": "intermediate",
    "prerequisites": ["counting"],
    "common_misconceptions": ["bigger is better"],
    "scope_boundary": "Fractions with single-digit denominators",
}

_SENTINEL = object()


def _make_guideline(
    id: str = "g1",
    country: str = "India",
    board: str = "CBSE",
    grade: int = 3,
    subject: str = "Mathematics",
    chapter: str = "Fractions",
    topic: str = "Comparing",
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
        chapter=chapter,
        topic=topic,
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
        assert result.scope_boundary == "Fractions with single-digit denominators"

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
        assert result.scope_boundary == ""  # default


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
        assert result.chapter == "Fractions"
        assert result.topic == "Comparing"
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
            _make_guideline(id="g1", subject="Mathematics", chapter="Fractions", topic="Comparing"),
            _make_guideline(id="g2", subject="Mathematics", chapter="Fractions", topic="Adding"),
            _make_guideline(id="g3", subject="Science", chapter="Plants", topic="Parts"),
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
# get_chapters
# ===========================================================================

class TestGetChapters:
    def test_returns_chapter_info_objects(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", chapter="Fractions", topic="Comparing"),
            _make_guideline(id="g2", chapter="Fractions", topic="Adding"),
            _make_guideline(id="g3", chapter="Geometry", topic="Shapes"),
        )
        repo = TeachingGuidelineRepository(db_session)

        chapters = repo.get_chapters("India", "CBSE", 3, "Mathematics")
        assert len(chapters) == 2
        assert all(isinstance(c, ChapterInfo) for c in chapters)

        chapter_names = sorted(c.chapter for c in chapters)
        assert chapter_names == ["Fractions", "Geometry"]

    def test_includes_topic_count_and_guideline_ids(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", chapter="Fractions", topic="Comparing"),
            _make_guideline(id="g2", chapter="Fractions", topic="Adding"),
            _make_guideline(id="g3", chapter="Geometry", topic="Shapes"),
        )
        repo = TeachingGuidelineRepository(db_session)

        chapters = repo.get_chapters("India", "CBSE", 3, "Mathematics")
        fractions = next(c for c in chapters if c.chapter == "Fractions")
        geometry = next(c for c in chapters if c.chapter == "Geometry")

        assert fractions.topic_count == 2
        assert sorted(fractions.guideline_ids) == ["g1", "g2"]
        assert geometry.topic_count == 1
        assert geometry.guideline_ids == ["g3"]

    def test_returns_empty_when_no_match(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        chapters = repo.get_chapters("India", "CBSE", 3, "History")
        assert chapters == []

    def test_excludes_non_approved(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", chapter="Fractions", review_status="APPROVED"),
            _make_guideline(id="g2", chapter="Geometry", review_status="TO_BE_REVIEWED"),
        )
        repo = TeachingGuidelineRepository(db_session)

        chapters = repo.get_chapters("India", "CBSE", 3, "Mathematics")
        assert len(chapters) == 1
        assert chapters[0].chapter == "Fractions"


# ===========================================================================
# get_topics
# ===========================================================================

class TestGetTopics:
    def test_returns_topic_info_list(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", topic="Comparing"),
            _make_guideline(id="g2", topic="Adding"),
        )
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics", "Fractions")

        assert len(topics) == 2
        assert all(isinstance(s, TopicInfo) for s in topics)

        topic_names = [s.topic for s in topics]
        assert "Comparing" in topic_names
        assert "Adding" in topic_names

    def test_topics_have_guideline_ids(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g10", topic="Comparing"),
        )
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics", "Fractions")
        assert topics[0].guideline_id == "g10"

    def test_returns_empty_when_no_match(self, db_session):
        repo = TeachingGuidelineRepository(db_session)
        topics = repo.get_topics("India", "CBSE", 3, "Mathematics", "NoSuchChapter")
        assert topics == []

    def test_excludes_non_approved(self, db_session):
        _seed(
            db_session,
            _make_guideline(id="g1", topic="Comparing", review_status="APPROVED"),
            _make_guideline(id="g2", topic="Adding", review_status="TO_BE_REVIEWED"),
        )
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics", "Fractions")
        assert len(topics) == 1
        assert topics[0].topic == "Comparing"

    def test_topics_ordered_by_sequence_then_alphabetically(self, db_session):
        g1 = _make_guideline(id="g1", topic="Zebra")
        g1.topic_sequence = 1
        g2 = _make_guideline(id="g2", topic="Apple")
        g2.topic_sequence = 3
        g3 = _make_guideline(id="g3", topic="Mango")
        g3.topic_sequence = 2
        _seed(db_session, g1, g2, g3)
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics", "Fractions")
        names = [t.topic for t in topics]
        assert names == ["Zebra", "Mango", "Apple"]

    def test_null_sequence_sorted_last(self, db_session):
        g1 = _make_guideline(id="g1", topic="Sequenced")
        g1.topic_sequence = 1
        g2 = _make_guideline(id="g2", topic="NoSequence")
        # topic_sequence defaults to None
        _seed(db_session, g1, g2)
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics", "Fractions")
        names = [t.topic for t in topics]
        assert names == ["Sequenced", "NoSequence"]

    def test_topics_include_summary_and_sequence(self, db_session):
        g = _make_guideline(id="g1", topic="Comparing")
        g.topic_summary = "Learn to compare fractions"
        g.topic_sequence = 2
        _seed(db_session, g)
        repo = TeachingGuidelineRepository(db_session)

        topics = repo.get_topics("India", "CBSE", 3, "Mathematics", "Fractions")
        assert topics[0].topic_summary == "Learn to compare fractions"
        assert topics[0].topic_sequence == 2
