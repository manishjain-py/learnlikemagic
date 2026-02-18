"""
Tests for book_ingestion models: schemas.py and guideline_models.py.

Tests Pydantic model validation, serialization, and helper functions.
"""
import pytest
from datetime import datetime
from pydantic import ValidationError


# ===== Schema Tests =====

from book_ingestion.models.schemas import (
    CreateBookRequest,
    BookResponse,
    BookListResponse,
    PageInfo,
    PageUploadResponse,
    PageApproveResponse,
    GuidelineMetadata,
    SubtopicGuideline,
    TopicGuideline,
    GuidelineJSON,
    GuidelineResponse,
    GuidelineApproveResponse,
    GuidelineRejectRequest,
    BookDetailResponse,
)


class TestCreateBookRequest:
    """Tests for CreateBookRequest schema."""

    def test_valid_request(self):
        req = CreateBookRequest(
            title="Math Book",
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
        )
        assert req.title == "Math Book"
        assert req.country == "India"
        assert req.grade == 3
        assert req.author is None
        assert req.edition is None
        assert req.edition_year is None

    def test_valid_request_all_fields(self):
        req = CreateBookRequest(
            title="Math Book",
            author="NCERT",
            edition="2nd",
            edition_year=2024,
            country="India",
            board="CBSE",
            grade=5,
            subject="Science",
        )
        assert req.author == "NCERT"
        assert req.edition == "2nd"
        assert req.edition_year == 2024

    def test_empty_title_rejected(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(
                title="",
                country="India",
                board="CBSE",
                grade=3,
                subject="Math",
            )

    def test_title_too_long_rejected(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(
                title="A" * 256,
                country="India",
                board="CBSE",
                grade=3,
                subject="Math",
            )

    def test_grade_below_range_rejected(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(
                title="Book",
                country="India",
                board="CBSE",
                grade=0,
                subject="Math",
            )

    def test_grade_above_range_rejected(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(
                title="Book",
                country="India",
                board="CBSE",
                grade=13,
                subject="Math",
            )

    def test_edition_year_below_range_rejected(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(
                title="Book",
                country="India",
                board="CBSE",
                grade=3,
                subject="Math",
                edition_year=1899,
            )

    def test_edition_year_above_range_rejected(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(
                title="Book",
                country="India",
                board="CBSE",
                grade=3,
                subject="Math",
                edition_year=2101,
            )

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(title="Book")

    def test_empty_country_rejected(self):
        with pytest.raises(ValidationError):
            CreateBookRequest(
                title="Book",
                country="",
                board="CBSE",
                grade=3,
                subject="Math",
            )


class TestBookResponse:
    """Tests for BookResponse schema."""

    def test_valid_response(self):
        now = datetime.utcnow()
        resp = BookResponse(
            id="ncert_math_3_2024",
            title="Math Book",
            author="NCERT",
            edition=None,
            edition_year=2024,
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
            cover_image_s3_key=None,
            s3_prefix="books/ncert_math_3_2024/",
            page_count=10,
            guideline_count=5,
            approved_guideline_count=3,
            has_active_job=False,
            created_at=now,
            updated_at=now,
            created_by="admin",
        )
        assert resp.id == "ncert_math_3_2024"
        assert resp.page_count == 10

    def test_default_counts(self):
        now = datetime.utcnow()
        resp = BookResponse(
            id="test",
            title="Test",
            author=None,
            edition=None,
            edition_year=None,
            country="India",
            board="CBSE",
            grade=3,
            subject="Math",
            cover_image_s3_key=None,
            s3_prefix="books/test/",
            created_at=now,
            updated_at=now,
            created_by="admin",
        )
        assert resp.page_count == 0
        assert resp.guideline_count == 0
        assert resp.approved_guideline_count == 0
        assert resp.has_active_job is False


class TestBookListResponse:
    """Tests for BookListResponse schema."""

    def test_empty_list(self):
        resp = BookListResponse(books=[], total=0)
        assert resp.books == []
        assert resp.total == 0


class TestPageInfo:
    """Tests for PageInfo schema."""

    def test_valid_page_info(self):
        page = PageInfo(
            page_num=1,
            image_s3_key="books/test/pages/001.png",
            text_s3_key="books/test/pages/001.ocr.txt",
            status="pending_review",
        )
        assert page.page_num == 1
        assert page.approved_at is None

    def test_approved_page(self):
        now = datetime.utcnow()
        page = PageInfo(
            page_num=2,
            image_s3_key="books/test/pages/002.png",
            text_s3_key="books/test/pages/002.ocr.txt",
            status="approved",
            approved_at=now,
        )
        assert page.status == "approved"
        assert page.approved_at == now


class TestGuidelineMetadata:
    """Tests for GuidelineMetadata schema."""

    def test_defaults(self):
        meta = GuidelineMetadata()
        assert meta.learning_objectives == []
        assert meta.depth_level == "intermediate"
        assert meta.prerequisites == []
        assert meta.common_misconceptions == []
        assert meta.scaffolding_strategies == []
        assert meta.assessment_criteria == {}

    def test_populated(self):
        meta = GuidelineMetadata(
            learning_objectives=["Understand fractions"],
            depth_level="basic",
            common_misconceptions=["Bigger denominator means bigger fraction"],
        )
        assert len(meta.learning_objectives) == 1
        assert meta.depth_level == "basic"


class TestGuidelineJSON:
    """Tests for GuidelineJSON schema."""

    def test_empty_topics(self):
        gj = GuidelineJSON(
            book_id="test",
            book_metadata={"grade": 3},
            topics=[],
        )
        assert gj.topics == []

    def test_with_topics(self):
        gj = GuidelineJSON(
            book_id="test",
            book_metadata={"grade": 3},
            topics=[
                TopicGuideline(
                    topic="Fractions",
                    subtopics=[
                        SubtopicGuideline(
                            subtopic="Adding fractions",
                            guideline="Teach adding fractions step by step.",
                            metadata=GuidelineMetadata(),
                            source_pages=[1, 2],
                        )
                    ],
                )
            ],
        )
        assert len(gj.topics) == 1
        assert gj.topics[0].topic == "Fractions"
        assert len(gj.topics[0].subtopics) == 1


class TestGuidelineApproveResponse:
    """Tests for GuidelineApproveResponse schema."""

    def test_valid(self):
        resp = GuidelineApproveResponse(
            message="Approved", teaching_guidelines_created=5
        )
        assert resp.teaching_guidelines_created == 5


class TestGuidelineRejectRequest:
    """Tests for GuidelineRejectRequest schema."""

    def test_valid(self):
        req = GuidelineRejectRequest(reason="Not accurate enough")
        assert req.reason == "Not accurate enough"


class TestBookDetailResponse:
    """Tests for BookDetailResponse schema."""

    def test_with_pages(self):
        now = datetime.utcnow()
        resp = BookDetailResponse(
            id="test",
            title="Test",
            author=None,
            edition=None,
            edition_year=None,
            country="India",
            board="CBSE",
            grade=3,
            subject="Math",
            pages=[
                PageInfo(
                    page_num=1,
                    image_s3_key="k1",
                    text_s3_key="k2",
                    status="approved",
                )
            ],
            created_at=now,
            updated_at=now,
        )
        assert len(resp.pages) == 1

    def test_empty_pages(self):
        now = datetime.utcnow()
        resp = BookDetailResponse(
            id="test",
            title="Test",
            author=None,
            edition=None,
            edition_year=None,
            country="India",
            board="CBSE",
            grade=3,
            subject="Math",
            pages=[],
            created_at=now,
            updated_at=now,
        )
        assert resp.pages == []


# ===== Guideline Model Tests =====

from book_ingestion.models.guideline_models import (
    Assessment,
    SubtopicShard,
    SubtopicIndexEntry,
    TopicIndexEntry,
    GuidelinesIndex,
    PageAssignment,
    PageIndex,
    RecentPageSummary,
    OpenSubtopicInfo,
    OpenTopicInfo,
    ToCHints,
    ContextPack,
    BoundaryDecision,
    TopicNameRefinement,
    MinisummaryResponse,
    slugify,
    deslugify,
)


class TestAssessment:
    """Tests for Assessment model."""

    def test_valid_assessment(self):
        a = Assessment(level="basic", prompt="What is 2+2?", answer="4")
        assert a.level == "basic"
        assert a.prompt == "What is 2+2?"

    def test_invalid_level_rejected(self):
        with pytest.raises(ValidationError):
            Assessment(level="beginner", prompt="Q", answer="A")

    def test_valid_levels(self):
        for level in ["basic", "proficient", "advanced"]:
            a = Assessment(level=level, prompt="Q", answer="A")
            assert a.level == level


class TestSubtopicShard:
    """Tests for SubtopicShard model."""

    def test_minimal_shard(self):
        shard = SubtopicShard(
            topic_key="fractions",
            topic_title="Fractions",
            subtopic_key="adding-fractions",
            subtopic_title="Adding Fractions",
            source_page_start=1,
            source_page_end=3,
            guidelines="Teach adding fractions step by step.",
        )
        assert shard.topic_key == "fractions"
        assert shard.version == 1
        assert shard.subtopic_summary == ""

    def test_shard_with_summary(self):
        shard = SubtopicShard(
            topic_key="fractions",
            topic_title="Fractions",
            subtopic_key="adding-fractions",
            subtopic_title="Adding Fractions",
            source_page_start=1,
            source_page_end=3,
            guidelines="Guidelines text here.",
            subtopic_summary="Covers addition of like fractions",
        )
        assert shard.subtopic_summary == "Covers addition of like fractions"

    def test_shard_version_increments(self):
        shard = SubtopicShard(
            topic_key="t",
            topic_title="T",
            subtopic_key="s",
            subtopic_title="S",
            source_page_start=1,
            source_page_end=1,
            guidelines="G",
            version=5,
        )
        assert shard.version == 5


class TestSubtopicIndexEntry:
    """Tests for SubtopicIndexEntry model."""

    def test_valid_entry(self):
        entry = SubtopicIndexEntry(
            subtopic_key="adding-fractions",
            subtopic_title="Adding Fractions",
            status="open",
            page_range="1-3",
        )
        assert entry.subtopic_key == "adding-fractions"
        assert entry.subtopic_summary == ""

    def test_all_statuses(self):
        for status in ["open", "stable", "final", "needs_review"]:
            entry = SubtopicIndexEntry(
                subtopic_key="s",
                subtopic_title="S",
                status=status,
                page_range="1-1",
            )
            assert entry.status == status

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            SubtopicIndexEntry(
                subtopic_key="s",
                subtopic_title="S",
                status="invalid",
                page_range="1-1",
            )


class TestTopicIndexEntry:
    """Tests for TopicIndexEntry model."""

    def test_empty_subtopics(self):
        entry = TopicIndexEntry(
            topic_key="fractions",
            topic_title="Fractions",
        )
        assert entry.subtopics == []
        assert entry.topic_summary == ""

    def test_with_subtopics(self):
        entry = TopicIndexEntry(
            topic_key="fractions",
            topic_title="Fractions",
            subtopics=[
                SubtopicIndexEntry(
                    subtopic_key="adding",
                    subtopic_title="Adding",
                    status="open",
                    page_range="1-3",
                )
            ],
        )
        assert len(entry.subtopics) == 1


class TestGuidelinesIndex:
    """Tests for GuidelinesIndex model."""

    def test_empty_index(self):
        idx = GuidelinesIndex(book_id="test-book")
        assert idx.book_id == "test-book"
        assert idx.topics == []
        assert idx.version == 1

    def test_with_topics(self):
        idx = GuidelinesIndex(
            book_id="test-book",
            topics=[
                TopicIndexEntry(
                    topic_key="fractions",
                    topic_title="Fractions",
                )
            ],
            version=3,
        )
        assert len(idx.topics) == 1
        assert idx.version == 3


class TestPageAssignment:
    """Tests for PageAssignment model."""

    def test_valid_assignment(self):
        pa = PageAssignment(
            topic_key="fractions",
            subtopic_key="adding",
            confidence=0.85,
        )
        assert pa.confidence == 0.85
        assert pa.provisional is False

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            PageAssignment(
                topic_key="t", subtopic_key="s", confidence=1.5
            )
        with pytest.raises(ValidationError):
            PageAssignment(
                topic_key="t", subtopic_key="s", confidence=-0.1
            )

    def test_edge_confidence_values(self):
        pa0 = PageAssignment(topic_key="t", subtopic_key="s", confidence=0.0)
        assert pa0.confidence == 0.0
        pa1 = PageAssignment(topic_key="t", subtopic_key="s", confidence=1.0)
        assert pa1.confidence == 1.0


class TestPageIndex:
    """Tests for PageIndex model."""

    def test_empty_page_index(self):
        pi = PageIndex(book_id="test")
        assert pi.pages == {}
        assert pi.version == 1

    def test_with_pages(self):
        pi = PageIndex(
            book_id="test",
            pages={
                1: PageAssignment(
                    topic_key="t", subtopic_key="s", confidence=0.9
                )
            },
        )
        assert 1 in pi.pages
        assert pi.pages[1].topic_key == "t"


class TestContextPack:
    """Tests for ContextPack model."""

    def test_minimal_context_pack(self):
        cp = ContextPack(
            book_id="test",
            current_page=5,
            book_metadata={"grade": 3, "subject": "Math"},
        )
        assert cp.current_page == 5
        assert cp.open_topics == []
        assert cp.recent_page_summaries == []

    def test_full_context_pack(self):
        cp = ContextPack(
            book_id="test",
            current_page=10,
            book_metadata={"grade": 3, "subject": "Math"},
            open_topics=[
                OpenTopicInfo(
                    topic_key="fractions",
                    topic_title="Fractions",
                    open_subtopics=[
                        OpenSubtopicInfo(
                            subtopic_key="adding",
                            subtopic_title="Adding",
                            page_start=1,
                            page_end=5,
                            guidelines="Guidelines text",
                        )
                    ],
                )
            ],
            recent_page_summaries=[
                RecentPageSummary(page=9, summary="Page about adding fractions")
            ],
            toc_hints=ToCHints(current_chapter="Fractions"),
        )
        assert len(cp.open_topics) == 1
        assert len(cp.recent_page_summaries) == 1
        assert cp.toc_hints.current_chapter == "Fractions"


class TestBoundaryDecision:
    """Tests for BoundaryDecision model."""

    def test_new_topic(self):
        bd = BoundaryDecision(
            is_new_topic=True,
            topic_name="fractions",
            subtopic_name="adding-fractions",
            page_guidelines="Guidelines for this page.",
            reasoning="New chapter starts here.",
        )
        assert bd.is_new_topic is True
        assert bd.topic_name == "fractions"

    def test_continue_topic(self):
        bd = BoundaryDecision(
            is_new_topic=False,
            topic_name="fractions",
            subtopic_name="adding-fractions",
            page_guidelines="More on adding fractions.",
            reasoning="Continuation of existing topic.",
        )
        assert bd.is_new_topic is False


class TestTopicNameRefinement:
    """Tests for TopicNameRefinement model."""

    def test_valid_refinement(self):
        tnr = TopicNameRefinement(
            topic_title="Fractions",
            topic_key="fractions",
            subtopic_title="Adding Like Fractions",
            subtopic_key="adding-like-fractions",
            reasoning="Refined for clarity.",
        )
        assert tnr.topic_title == "Fractions"
        assert tnr.subtopic_key == "adding-like-fractions"


class TestMinisummaryResponse:
    """Tests for MinisummaryResponse model."""

    def test_valid_summary(self):
        ms = MinisummaryResponse(summary="This page covers adding fractions.")
        assert "adding fractions" in ms.summary

    def test_max_length_enforced(self):
        with pytest.raises(ValidationError):
            MinisummaryResponse(summary="x" * 501)

    def test_short_summary(self):
        ms = MinisummaryResponse(summary="Short.")
        assert ms.summary == "Short."


class TestSlugify:
    """Tests for slugify helper function."""

    def test_basic_slugify(self):
        assert slugify("Adding Like Fractions") == "adding-like-fractions"

    def test_single_word(self):
        assert slugify("Fractions") == "fractions"

    def test_with_underscores(self):
        assert slugify("data_handling_basics") == "data-handling-basics"

    def test_with_special_chars(self):
        assert slugify("What's the answer?") == "whats-the-answer"

    def test_multiple_spaces(self):
        assert slugify("Adding   Like   Fractions") == "adding-like-fractions"

    def test_leading_trailing_hyphens_stripped(self):
        assert slugify("-hello-") == "hello"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_all_special_chars(self):
        result = slugify("!@#$%")
        assert result == ""


class TestDeslugify:
    """Tests for deslugify helper function."""

    def test_basic_deslugify(self):
        assert deslugify("adding-like-fractions") == "Adding Like Fractions"

    def test_single_word(self):
        assert deslugify("fractions") == "Fractions"

    def test_already_capitalized(self):
        # deslugify always capitalizes each word
        assert deslugify("fractions") == "Fractions"

    def test_empty_string(self):
        assert deslugify("") == ""
