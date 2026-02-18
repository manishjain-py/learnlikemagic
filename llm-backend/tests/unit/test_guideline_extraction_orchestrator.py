"""
Comprehensive tests for GuidelineExtractionOrchestrator.

Tests all methods with mocked S3, OpenAI, and component services.
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime

from book_ingestion.services.guideline_extraction_orchestrator import (
    GuidelineExtractionOrchestrator,
)
from book_ingestion.models.guideline_models import (
    SubtopicShard,
    GuidelinesIndex,
    TopicIndexEntry,
    SubtopicIndexEntry,
    PageIndex,
    PageAssignment,
    ContextPack,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_s3():
    """Create a mocked S3Client."""
    s3 = MagicMock()
    s3.download_bytes = MagicMock()
    s3.download_json = MagicMock()
    s3.upload_json = MagicMock()
    s3.delete_file = MagicMock()
    return s3


@pytest.fixture
def mock_openai():
    """Create a mocked OpenAI client."""
    return MagicMock()


@pytest.fixture
def mock_db_session():
    """Create a mocked DB session."""
    return MagicMock()


@pytest.fixture
def book_metadata():
    """Standard book metadata for tests."""
    return {
        "grade": 3,
        "subject": "Math",
        "board": "CBSE",
        "total_pages": 10,
    }


def _make_shard(
    topic_key="fractions",
    topic_title="Fractions",
    subtopic_key="adding-fractions",
    subtopic_title="Adding Fractions",
    page_start=1,
    page_end=3,
    guidelines="Teach adding fractions step by step.",
    subtopic_summary="Adding fractions basics.",
    version=1,
):
    """Helper to create a SubtopicShard for tests."""
    return SubtopicShard(
        topic_key=topic_key,
        topic_title=topic_title,
        subtopic_key=subtopic_key,
        subtopic_title=subtopic_title,
        subtopic_summary=subtopic_summary,
        source_page_start=page_start,
        source_page_end=page_end,
        guidelines=guidelines,
        version=version,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )


def _make_index(book_id="book-1", topics=None):
    """Helper to create a GuidelinesIndex for tests."""
    return GuidelinesIndex(
        book_id=book_id,
        topics=topics or [],
        version=1,
        last_updated=datetime.utcnow(),
    )


def _make_topic_entry(
    topic_key="fractions",
    topic_title="Fractions",
    subtopics=None,
):
    """Helper to create a TopicIndexEntry."""
    return TopicIndexEntry(
        topic_key=topic_key,
        topic_title=topic_title,
        topic_summary="Fractions topic summary.",
        subtopics=subtopics or [],
    )


def _make_subtopic_entry(
    subtopic_key="adding-fractions",
    subtopic_title="Adding Fractions",
    status="open",
    page_range="1-3",
    subtopic_summary="Adding fractions basics.",
):
    """Helper to create a SubtopicIndexEntry."""
    return SubtopicIndexEntry(
        subtopic_key=subtopic_key,
        subtopic_title=subtopic_title,
        subtopic_summary=subtopic_summary,
        status=status,
        page_range=page_range,
    )


@pytest.fixture
def orchestrator(mock_s3, mock_openai, mock_db_session):
    """
    Create a GuidelineExtractionOrchestrator with all component services mocked.
    """
    with patch(
        "book_ingestion.services.guideline_extraction_orchestrator.MinisummaryService"
    ) as MockMini, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.ContextPackService"
    ) as MockCtx, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.BoundaryDetectionService"
    ) as MockBD, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.GuidelineMergeService"
    ) as MockMerge, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.TopicDeduplicationService"
    ) as MockDedup, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.TopicNameRefinementService"
    ) as MockRefine, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.IndexManagementService"
    ) as MockIdx, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.DBSyncService"
    ) as MockDB, patch(
        "book_ingestion.services.guideline_extraction_orchestrator.TopicSubtopicSummaryService"
    ) as MockSummary:
        orch = GuidelineExtractionOrchestrator(
            s3_client=mock_s3,
            openai_client=mock_openai,
            db_session=mock_db_session,
        )
        yield orch


# ============================================================================
# __init__ TESTS
# ============================================================================

class TestInit:
    def test_init_sets_s3_client(self, orchestrator, mock_s3):
        assert orchestrator.s3 is mock_s3

    def test_init_sets_openai_client(self, orchestrator, mock_openai):
        assert orchestrator.openai_client is mock_openai

    def test_init_creates_all_services(self, orchestrator):
        assert orchestrator.minisummary is not None
        assert orchestrator.context_pack is not None
        assert orchestrator.boundary_detector is not None
        assert orchestrator.merge_service is not None
        assert orchestrator.dedup_service is not None
        assert orchestrator.name_refinement is not None
        assert orchestrator.index_manager is not None
        assert orchestrator.db_sync is not None
        assert orchestrator.summary_service is not None

    def test_init_without_db_session(self, mock_s3, mock_openai):
        """When db_session is None, db_sync should be None."""
        with patch(
            "book_ingestion.services.guideline_extraction_orchestrator.MinisummaryService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.ContextPackService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.BoundaryDetectionService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.GuidelineMergeService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.TopicDeduplicationService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.TopicNameRefinementService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.IndexManagementService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.DBSyncService"
        ), patch(
            "book_ingestion.services.guideline_extraction_orchestrator.TopicSubtopicSummaryService"
        ):
            orch = GuidelineExtractionOrchestrator(
                s3_client=mock_s3,
                openai_client=mock_openai,
                db_session=None,
            )
            assert orch.db_sync is None

    def test_stability_threshold_is_five(self, orchestrator):
        assert orchestrator.STABILITY_THRESHOLD == 5


# ============================================================================
# _load_page_text TESTS
# ============================================================================

class TestLoadPageText:
    def test_load_page_text_primary_path(self, orchestrator, mock_s3):
        """Should load from pages/001.ocr.txt first."""
        mock_s3.download_bytes.return_value = b"Page one text content"
        result = orchestrator._load_page_text("book-1", 1)
        assert result == "Page one text content"
        mock_s3.download_bytes.assert_called_once_with(
            "books/book-1/pages/001.ocr.txt"
        )

    def test_load_page_text_fallback_path(self, orchestrator, mock_s3):
        """Should fall back to {page_num}.txt if primary path fails."""
        mock_s3.download_bytes.side_effect = [
            Exception("Not found"),
            b"Fallback text content",
        ]
        result = orchestrator._load_page_text("book-1", 5)
        assert result == "Fallback text content"
        assert mock_s3.download_bytes.call_count == 2
        mock_s3.download_bytes.assert_any_call("books/book-1/pages/005.ocr.txt")
        mock_s3.download_bytes.assert_any_call("books/book-1/5.txt")

    def test_load_page_text_both_fail_raises(self, orchestrator, mock_s3):
        """Should raise when both paths fail."""
        mock_s3.download_bytes.side_effect = Exception("Not found")
        with pytest.raises(Exception, match="Not found"):
            orchestrator._load_page_text("book-1", 1)

    def test_load_page_text_page_number_formatting(self, orchestrator, mock_s3):
        """Page numbers should be zero-padded to 3 digits."""
        mock_s3.download_bytes.return_value = b"content"
        orchestrator._load_page_text("book-1", 42)
        mock_s3.download_bytes.assert_called_once_with(
            "books/book-1/pages/042.ocr.txt"
        )


# ============================================================================
# _load_shard_v2 TESTS
# ============================================================================

class TestLoadShardV2:
    def test_load_shard_success(self, orchestrator, mock_s3):
        shard = _make_shard()
        mock_s3.download_json.return_value = shard.model_dump()
        result = orchestrator._load_shard_v2("book-1", "fractions", "adding-fractions")
        assert isinstance(result, SubtopicShard)
        assert result.topic_key == "fractions"
        assert result.subtopic_key == "adding-fractions"
        mock_s3.download_json.assert_called_once_with(
            "books/book-1/guidelines/topics/fractions/subtopics/adding-fractions.latest.json"
        )

    def test_load_shard_not_found_raises(self, orchestrator, mock_s3):
        mock_s3.download_json.side_effect = Exception("NoSuchKey")
        with pytest.raises(Exception, match="NoSuchKey"):
            orchestrator._load_shard_v2("book-1", "fractions", "missing")


# ============================================================================
# _save_shard_v2 TESTS
# ============================================================================

class TestSaveShardV2:
    def test_save_shard_calls_upload_json(self, orchestrator, mock_s3):
        shard = _make_shard()
        orchestrator._save_shard_v2("book-1", shard)
        expected_key = (
            "books/book-1/guidelines/topics/fractions/subtopics/"
            "adding-fractions.latest.json"
        )
        mock_s3.upload_json.assert_called_once_with(
            shard.model_dump(), expected_key
        )

    def test_save_shard_upload_failure_raises(self, orchestrator, mock_s3):
        mock_s3.upload_json.side_effect = Exception("Upload failed")
        shard = _make_shard()
        with pytest.raises(Exception, match="Upload failed"):
            orchestrator._save_shard_v2("book-1", shard)


# ============================================================================
# _delete_shard_v2 TESTS
# ============================================================================

class TestDeleteShardV2:
    def test_delete_shard_calls_delete_file(self, orchestrator, mock_s3):
        orchestrator._delete_shard_v2("book-1", "fractions", "adding-fractions")
        expected_key = (
            "books/book-1/guidelines/topics/fractions/subtopics/"
            "adding-fractions.latest.json"
        )
        mock_s3.delete_file.assert_called_once_with(expected_key)

    def test_delete_shard_failure_does_not_raise(self, orchestrator, mock_s3):
        """Delete failure is a warning, not an error."""
        mock_s3.delete_file.side_effect = Exception("Delete failed")
        # Should NOT raise
        orchestrator._delete_shard_v2("book-1", "fractions", "adding-fractions")


# ============================================================================
# _load_all_shards_v2 TESTS
# ============================================================================

class TestLoadAllShardsV2:
    def test_load_all_shards_from_index(self, orchestrator, mock_s3):
        shard1 = _make_shard(subtopic_key="sub-a", subtopic_title="Sub A")
        shard2 = _make_shard(subtopic_key="sub-b", subtopic_title="Sub B")

        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[
                        _make_subtopic_entry(subtopic_key="sub-a"),
                        _make_subtopic_entry(subtopic_key="sub-b"),
                    ]
                )
            ]
        )

        # _load_index -> download_json for index
        # _load_shard_v2 -> download_json for each shard
        mock_s3.download_json.side_effect = [
            index.model_dump(mode="json"),  # index load
            shard1.model_dump(),            # shard 1
            shard2.model_dump(),            # shard 2
        ]

        result = orchestrator._load_all_shards_v2("book-1")
        assert len(result) == 2
        assert result[0].subtopic_key == "sub-a"
        assert result[1].subtopic_key == "sub-b"

    def test_load_all_shards_skips_missing(self, orchestrator, mock_s3):
        """If a shard cannot be loaded, it is skipped."""
        shard1 = _make_shard(subtopic_key="sub-a", subtopic_title="Sub A")

        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[
                        _make_subtopic_entry(subtopic_key="sub-a"),
                        _make_subtopic_entry(subtopic_key="sub-missing"),
                    ]
                )
            ]
        )

        mock_s3.download_json.side_effect = [
            index.model_dump(mode="json"),
            shard1.model_dump(),
            Exception("NoSuchKey"),
        ]

        result = orchestrator._load_all_shards_v2("book-1")
        assert len(result) == 1

    def test_load_all_shards_empty_index(self, orchestrator, mock_s3):
        """If index has no topics, return empty list."""
        index = _make_index(topics=[])
        mock_s3.download_json.return_value = index.model_dump(mode="json")
        result = orchestrator._load_all_shards_v2("book-1")
        assert result == []


# ============================================================================
# _save_page_guideline_v2 TESTS
# ============================================================================

class TestSavePageGuidelineV2:
    def test_save_page_guideline(self, orchestrator, mock_s3):
        orchestrator._save_page_guideline_v2("book-1", 5, "This page is about fractions.")
        expected_key = "books/book-1/pages/005.page_guideline.json"
        call_args = mock_s3.upload_json.call_args
        data = call_args[0][0]
        key = call_args[0][1]
        assert key == expected_key
        assert data["page"] == 5
        assert data["summary"] == "This page is about fractions."
        assert data["version"] == "v2"

    def test_save_page_guideline_failure_raises(self, orchestrator, mock_s3):
        mock_s3.upload_json.side_effect = Exception("Upload failed")
        with pytest.raises(Exception, match="Upload failed"):
            orchestrator._save_page_guideline_v2("book-1", 1, "summary")


# ============================================================================
# _load_index TESTS
# ============================================================================

class TestLoadIndex:
    def test_load_index_success(self, orchestrator, mock_s3):
        index = _make_index()
        mock_s3.download_json.return_value = index.model_dump(mode="json")
        result = orchestrator._load_index("book-1")
        assert isinstance(result, GuidelinesIndex)
        assert result.book_id == "book-1"
        mock_s3.download_json.assert_called_once_with(
            "books/book-1/guidelines/index.json"
        )

    def test_load_index_not_found_creates_empty(self, orchestrator, mock_s3):
        """When no index exists, create an empty one."""
        mock_s3.download_json.side_effect = Exception("NoSuchKey")
        result = orchestrator._load_index("book-1")
        assert isinstance(result, GuidelinesIndex)
        assert result.book_id == "book-1"
        assert result.topics == []


# ============================================================================
# _check_and_mark_stable_subtopics TESTS
# ============================================================================

class TestCheckAndMarkStableSubtopics:
    def test_marks_stable_when_threshold_met(self, orchestrator, mock_s3):
        """Subtopic should be marked stable after 5-page gap."""
        shard = _make_shard(page_end=2)  # last page 2
        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[
                        _make_subtopic_entry(status="open", page_range="1-2"),
                    ]
                )
            ]
        )

        # First call: _load_index; Second call: _load_shard_v2
        mock_s3.download_json.side_effect = [
            index.model_dump(mode="json"),
            shard.model_dump(),
        ]

        # current_page=7, shard.source_page_end=2, gap=5 >= STABILITY_THRESHOLD=5
        result = orchestrator._check_and_mark_stable_subtopics("book-1", 7)
        assert result == 1
        # Shard should have been saved
        assert mock_s3.upload_json.called

    def test_no_stable_when_below_threshold(self, orchestrator, mock_s3):
        """Subtopic should NOT be marked stable if gap < 5."""
        shard = _make_shard(page_end=4)
        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[
                        _make_subtopic_entry(status="open", page_range="1-4"),
                    ]
                )
            ]
        )

        mock_s3.download_json.side_effect = [
            index.model_dump(mode="json"),
            shard.model_dump(),
        ]

        # current_page=8, shard.source_page_end=4, gap=4 < 5
        result = orchestrator._check_and_mark_stable_subtopics("book-1", 8)
        assert result == 0

    def test_skips_non_open_subtopics(self, orchestrator, mock_s3):
        """Only 'open' subtopics should be checked for stability."""
        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[
                        _make_subtopic_entry(status="stable", page_range="1-2"),
                    ]
                )
            ]
        )

        mock_s3.download_json.return_value = index.model_dump(mode="json")

        result = orchestrator._check_and_mark_stable_subtopics("book-1", 100)
        assert result == 0
        # Should NOT have tried to load any shard
        mock_s3.download_json.assert_called_once()


# ============================================================================
# _collect_subtopic_summaries TESTS
# ============================================================================

class TestCollectSubtopicSummaries:
    def test_collect_with_existing_summaries(self, orchestrator, mock_s3):
        index = _make_index(
            topics=[
                _make_topic_entry(
                    topic_key="fractions",
                    subtopics=[
                        _make_subtopic_entry(
                            subtopic_key="sub-a",
                            subtopic_summary="Sub A summary",
                        ),
                        _make_subtopic_entry(
                            subtopic_key="sub-b",
                            subtopic_summary="Sub B summary",
                        ),
                    ],
                )
            ]
        )
        mock_s3.download_json.return_value = index.model_dump(mode="json")

        result = orchestrator._collect_subtopic_summaries(
            "book-1", "fractions", current_subtopic_summary="Current summary"
        )
        assert "Sub A summary" in result
        assert "Sub B summary" in result
        assert "Current summary" in result

    def test_collect_no_matching_topic(self, orchestrator, mock_s3):
        index = _make_index(topics=[])
        mock_s3.download_json.return_value = index.model_dump(mode="json")

        result = orchestrator._collect_subtopic_summaries(
            "book-1", "nonexistent", current_subtopic_summary="Current"
        )
        assert result == ["Current"]

    def test_collect_handles_index_error(self, orchestrator, mock_s3):
        mock_s3.download_json.side_effect = Exception("S3 error")
        result = orchestrator._collect_subtopic_summaries(
            "book-1", "fractions", current_subtopic_summary=""
        )
        assert result == []

    def test_collect_without_current_summary(self, orchestrator, mock_s3):
        index = _make_index(
            topics=[
                _make_topic_entry(
                    topic_key="fractions",
                    subtopics=[
                        _make_subtopic_entry(subtopic_summary="Existing"),
                    ],
                )
            ]
        )
        mock_s3.download_json.return_value = index.model_dump(mode="json")

        result = orchestrator._collect_subtopic_summaries(
            "book-1", "fractions", current_subtopic_summary=""
        )
        assert result == ["Existing"]


# ============================================================================
# _remove_from_index TESTS
# ============================================================================

class TestRemoveFromIndex:
    def test_remove_subtopic_from_index(self, orchestrator, mock_s3):
        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[
                        _make_subtopic_entry(subtopic_key="sub-a"),
                        _make_subtopic_entry(subtopic_key="sub-b"),
                    ]
                )
            ]
        )
        mock_s3.download_json.return_value = index.model_dump(mode="json")

        orchestrator._remove_from_index("book-1", "fractions", "sub-a")

        # Should have uploaded updated index
        assert mock_s3.upload_json.called
        saved_data = mock_s3.upload_json.call_args[0][0]
        remaining_subtopics = saved_data["topics"][0]["subtopics"]
        assert len(remaining_subtopics) == 1
        assert remaining_subtopics[0]["subtopic_key"] == "sub-b"

    def test_remove_last_subtopic_removes_topic(self, orchestrator, mock_s3):
        """If removing the last subtopic, the topic should also be removed."""
        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[_make_subtopic_entry(subtopic_key="only-one")]
                )
            ]
        )
        mock_s3.download_json.return_value = index.model_dump(mode="json")

        orchestrator._remove_from_index("book-1", "fractions", "only-one")

        saved_data = mock_s3.upload_json.call_args[0][0]
        assert len(saved_data["topics"]) == 0

    def test_remove_nonexistent_subtopic_no_error(self, orchestrator, mock_s3):
        """Removing a non-existent subtopic should not raise."""
        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[_make_subtopic_entry(subtopic_key="sub-a")]
                )
            ]
        )
        mock_s3.download_json.return_value = index.model_dump(mode="json")
        # Should not raise
        orchestrator._remove_from_index("book-1", "fractions", "nonexistent")


# ============================================================================
# _update_index_names TESTS
# ============================================================================

class TestUpdateIndexNames:
    def test_update_topic_and_subtopic_names(self, orchestrator, mock_s3):
        index = _make_index(
            topics=[
                _make_topic_entry(
                    topic_key="old-topic",
                    topic_title="Old Topic",
                    subtopics=[
                        _make_subtopic_entry(
                            subtopic_key="old-sub",
                            subtopic_title="Old Sub",
                        )
                    ],
                )
            ]
        )
        mock_s3.download_json.return_value = index.model_dump(mode="json")

        orchestrator._update_index_names(
            "book-1",
            "old-topic", "old-sub",
            "new-topic", "new-sub",
            "New Topic", "New Sub",
        )

        saved_data = mock_s3.upload_json.call_args[0][0]
        topic = saved_data["topics"][0]
        assert topic["topic_key"] == "new-topic"
        assert topic["topic_title"] == "New Topic"
        assert topic["subtopics"][0]["subtopic_key"] == "new-sub"
        assert topic["subtopics"][0]["subtopic_title"] == "New Sub"

    def test_update_only_subtopic_name(self, orchestrator, mock_s3):
        """If topic key stays the same, only subtopic should be updated."""
        index = _make_index(
            topics=[
                _make_topic_entry(
                    topic_key="fractions",
                    subtopics=[
                        _make_subtopic_entry(
                            subtopic_key="old-sub",
                            subtopic_title="Old Sub",
                        )
                    ],
                )
            ]
        )
        mock_s3.download_json.return_value = index.model_dump(mode="json")

        orchestrator._update_index_names(
            "book-1",
            "fractions", "old-sub",
            "fractions", "new-sub",
            "Fractions", "New Sub",
        )

        saved_data = mock_s3.upload_json.call_args[0][0]
        topic = saved_data["topics"][0]
        assert topic["topic_key"] == "fractions"
        assert topic["subtopics"][0]["subtopic_key"] == "new-sub"

    def test_update_index_names_handles_error(self, orchestrator, mock_s3):
        """Should not raise on S3 error."""
        mock_s3.download_json.side_effect = Exception("S3 error")
        # Should not raise
        orchestrator._update_index_names(
            "book-1", "old", "old-sub", "new", "new-sub", "New", "New Sub"
        )


# ============================================================================
# process_page TESTS
# ============================================================================

class TestProcessPage:
    @pytest.mark.asyncio
    async def test_process_page_new_topic(self, orchestrator, mock_s3, book_metadata):
        """Test processing a page that starts a new topic."""
        # Step 1: _load_page_text
        mock_s3.download_bytes.return_value = b"Page text about new topic."

        # Step 2: minisummary
        orchestrator.minisummary.generate.return_value = "Minisummary of page."

        # Step 3: context_pack
        context_pack = ContextPack(
            book_id="book-1",
            current_page=1,
            book_metadata=book_metadata,
        )
        orchestrator.context_pack.build.return_value = context_pack

        # Step 4: boundary_detector => new topic
        orchestrator.boundary_detector.detect.return_value = (
            True,                    # is_new
            "fractions",             # topic_key
            "Fractions",             # topic_title
            "adding-fractions",      # subtopic_key
            "Adding Fractions",      # subtopic_title
            "Guidelines for adding fractions.",  # page_guidelines
        )

        # Step 6: summary_service
        orchestrator.summary_service.generate_subtopic_summary.return_value = "Subtopic summary."
        orchestrator.summary_service.generate_topic_summary.return_value = "Topic summary."

        # _collect_subtopic_summaries needs index
        mock_s3.download_json.return_value = _make_index().model_dump(mode="json")

        # index_manager stubs
        orchestrator.index_manager.get_or_create_index.return_value = _make_index()
        orchestrator.index_manager.add_or_update_subtopic.return_value = _make_index()
        orchestrator.index_manager.get_or_create_page_index.return_value = PageIndex(
            book_id="book-1"
        )
        orchestrator.index_manager.add_page_assignment.return_value = PageIndex(
            book_id="book-1"
        )

        result = await orchestrator.process_page("book-1", 1, book_metadata)

        assert result["is_new_topic"] is True
        assert result["topic_key"] == "fractions"
        assert result["subtopic_key"] == "adding-fractions"
        assert result["page_num"] == 1
        # Shard should be saved
        assert mock_s3.upload_json.called
        # Minisummary should be generated
        orchestrator.minisummary.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_page_continue_topic(self, orchestrator, mock_s3, book_metadata):
        """Test processing a page that continues an existing topic."""
        # Step 1: _load_page_text
        mock_s3.download_bytes.return_value = b"More fraction content."

        # Step 2: minisummary
        orchestrator.minisummary.generate.return_value = "Continued fractions."

        # Step 3: context_pack
        context_pack = ContextPack(
            book_id="book-1",
            current_page=2,
            book_metadata=book_metadata,
        )
        orchestrator.context_pack.build.return_value = context_pack

        # Step 4: boundary_detector => continue existing topic
        orchestrator.boundary_detector.detect.return_value = (
            False,                   # is_new = False
            "fractions",
            "Fractions",
            "adding-fractions",
            "Adding Fractions",
            "New guidelines from page 2.",
        )

        # Step 5: load existing shard for merge
        existing_shard = _make_shard(page_end=1)
        # download_json calls: first for _load_shard_v2, then for _collect_subtopic_summaries (_load_index)
        mock_s3.download_json.side_effect = [
            existing_shard.model_dump(),                     # _load_shard_v2
            _make_index().model_dump(mode="json"),           # _collect_subtopic_summaries -> _load_index
        ]

        # merge_service
        orchestrator.merge_service.merge.return_value = "Merged guidelines."

        # summary
        orchestrator.summary_service.generate_subtopic_summary.return_value = "Updated summary."
        orchestrator.summary_service.generate_topic_summary.return_value = "Topic summary."

        # index_manager stubs
        orchestrator.index_manager.get_or_create_index.return_value = _make_index()
        orchestrator.index_manager.add_or_update_subtopic.return_value = _make_index()
        orchestrator.index_manager.get_or_create_page_index.return_value = PageIndex(
            book_id="book-1"
        )
        orchestrator.index_manager.add_page_assignment.return_value = PageIndex(
            book_id="book-1"
        )

        result = await orchestrator.process_page("book-1", 2, book_metadata)

        assert result["is_new_topic"] is False
        assert result["topic_key"] == "fractions"
        orchestrator.merge_service.merge.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_page_continue_shard_not_found_creates_new(
        self, orchestrator, mock_s3, book_metadata
    ):
        """When boundary says CONTINUE but shard not found, create new shard."""
        mock_s3.download_bytes.return_value = b"Content."
        orchestrator.minisummary.generate.return_value = "Summary."
        orchestrator.context_pack.build.return_value = ContextPack(
            book_id="book-1", current_page=3, book_metadata=book_metadata
        )
        orchestrator.boundary_detector.detect.return_value = (
            False, "fractions", "Fractions", "new-sub", "New Sub", "Guidelines."
        )

        # Shard not found (download_json raises); then _collect_subtopic_summaries -> _load_index
        mock_s3.download_json.side_effect = [
            Exception("NoSuchKey"),                      # _load_shard_v2 fails
            _make_index().model_dump(mode="json"),       # _collect_subtopic_summaries -> _load_index
        ]

        orchestrator.summary_service.generate_subtopic_summary.return_value = "Summary."
        orchestrator.summary_service.generate_topic_summary.return_value = "Topic summary."

        orchestrator.index_manager.get_or_create_index.return_value = _make_index()
        orchestrator.index_manager.add_or_update_subtopic.return_value = _make_index()
        orchestrator.index_manager.get_or_create_page_index.return_value = PageIndex(
            book_id="book-1"
        )
        orchestrator.index_manager.add_page_assignment.return_value = PageIndex(
            book_id="book-1"
        )

        result = await orchestrator.process_page("book-1", 3, book_metadata)
        # Should still succeed, treating as new
        assert result["topic_key"] == "fractions"
        assert result["subtopic_key"] == "new-sub"


# ============================================================================
# extract_guidelines_for_book TESTS
# ============================================================================

class TestExtractGuidelinesForBook:
    @pytest.mark.asyncio
    async def test_extract_processes_all_pages(self, orchestrator, mock_s3, book_metadata):
        """Should process pages start_page through end_page."""
        book_metadata["total_pages"] = 3

        # Stub process_page
        async def mock_process_page(book_id, page_num, book_metadata):
            return {
                "page_num": page_num,
                "topic_key": "fractions",
                "subtopic_key": "sub",
                "is_new_topic": page_num == 1,
                "guidelines_length": 50,
            }

        orchestrator.process_page = AsyncMock(side_effect=mock_process_page)

        # Stub _check_and_mark_stable_subtopics
        orchestrator._check_and_mark_stable_subtopics = MagicMock(return_value=0)

        result = await orchestrator.extract_guidelines_for_book(
            "book-1", book_metadata, start_page=1, end_page=3
        )

        assert result["pages_processed"] == 3
        assert result["subtopics_created"] == 1
        assert result["subtopics_merged"] == 2
        assert orchestrator.process_page.call_count == 3

    @pytest.mark.asyncio
    async def test_extract_handles_page_error(self, orchestrator, mock_s3, book_metadata):
        """If a page fails, it should be recorded in errors and processing continues."""
        book_metadata["total_pages"] = 2
        call_count = 0

        async def mock_process_page(book_id, page_num, book_metadata):
            nonlocal call_count
            call_count += 1
            if page_num == 1:
                raise ValueError("Bad page")
            return {
                "page_num": page_num,
                "topic_key": "t",
                "subtopic_key": "s",
                "is_new_topic": True,
                "guidelines_length": 10,
            }

        orchestrator.process_page = AsyncMock(side_effect=mock_process_page)
        orchestrator._check_and_mark_stable_subtopics = MagicMock(return_value=0)

        result = await orchestrator.extract_guidelines_for_book(
            "book-1", book_metadata, start_page=1, end_page=2
        )

        assert result["pages_processed"] == 1
        assert len(result["errors"]) == 1
        assert "page 1" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_extract_uses_total_pages_as_default_end(
        self, orchestrator, mock_s3, book_metadata
    ):
        """end_page defaults to total_pages from metadata."""
        book_metadata["total_pages"] = 2

        async def mock_process_page(book_id, page_num, book_metadata):
            return {
                "page_num": page_num,
                "topic_key": "t",
                "subtopic_key": "s",
                "is_new_topic": True,
                "guidelines_length": 10,
            }

        orchestrator.process_page = AsyncMock(side_effect=mock_process_page)
        orchestrator._check_and_mark_stable_subtopics = MagicMock(return_value=0)

        result = await orchestrator.extract_guidelines_for_book(
            "book-1", book_metadata, start_page=1
        )

        assert result["pages_processed"] == 2
        assert orchestrator.process_page.call_count == 2

    @pytest.mark.asyncio
    async def test_extract_custom_page_range(self, orchestrator, mock_s3, book_metadata):
        """Should respect custom start_page and end_page."""
        book_metadata["total_pages"] = 10

        async def mock_process_page(book_id, page_num, book_metadata):
            return {
                "page_num": page_num,
                "topic_key": "t",
                "subtopic_key": "s",
                "is_new_topic": True,
                "guidelines_length": 10,
            }

        orchestrator.process_page = AsyncMock(side_effect=mock_process_page)
        orchestrator._check_and_mark_stable_subtopics = MagicMock(return_value=0)

        result = await orchestrator.extract_guidelines_for_book(
            "book-1", book_metadata, start_page=5, end_page=7
        )

        assert result["pages_processed"] == 3


# ============================================================================
# finalize_book TESTS
# ============================================================================

class TestFinalizeBook:
    @pytest.mark.asyncio
    async def test_finalize_book_full_flow(self, orchestrator, mock_s3, book_metadata):
        """Test full finalize flow: finalize open, refine names, dedup, summary regen."""
        shard = _make_shard()
        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[_make_subtopic_entry(status="open")]
                )
            ]
        )

        # _load_index calls (multiple)
        # For finalize: _load_index then _load_shard_v2 for each open shard
        # For name refinement: _load_shard_v2
        # For load_all_shards: _load_index + _load_shard_v2
        # For _remove_from_index: _load_index
        # For final summary regeneration: _load_index (already covered)

        shard_dump = shard.model_dump()
        index_dump = index.model_dump(mode="json")

        mock_s3.download_json.side_effect = [
            index_dump,      # _load_index (finalize step 1)
            shard_dump,      # _load_shard_v2 (finalize open shard)
            shard_dump,      # _load_shard_v2 (name refinement)
            index_dump,      # _load_index (load_all_shards step 3)
            shard_dump,      # _load_shard_v2 (load_all_shards)
            index_dump,      # _load_index (final summary regeneration)
        ]

        # Name refinement: no change
        refinement = MagicMock()
        refinement.topic_title = shard.topic_title
        refinement.topic_key = shard.topic_key
        refinement.subtopic_title = shard.subtopic_title
        refinement.subtopic_key = shard.subtopic_key
        orchestrator.name_refinement.refine_names.return_value = refinement

        # Dedup: no duplicates
        orchestrator.dedup_service.deduplicate.return_value = []

        # Summary service
        orchestrator.summary_service.generate_topic_summary.return_value = "Updated topic summary."

        # Index manager for save_index
        orchestrator.index_manager.save_index = MagicMock()

        result = await orchestrator.finalize_book("book-1", book_metadata)

        assert result["status"] == "finalized"
        assert result["subtopics_finalized"] == 1
        assert result["duplicates_merged"] == 0

    @pytest.mark.asyncio
    async def test_finalize_with_duplicates(self, orchestrator, mock_s3, book_metadata):
        """Test that duplicates are merged during finalization."""
        shard1 = _make_shard(subtopic_key="sub-a", subtopic_title="Sub A")
        shard2 = _make_shard(subtopic_key="sub-b", subtopic_title="Sub B", page_start=4, page_end=6)

        index = _make_index(
            topics=[
                _make_topic_entry(
                    subtopics=[
                        _make_subtopic_entry(subtopic_key="sub-a", status="open"),
                        _make_subtopic_entry(subtopic_key="sub-b", status="open"),
                    ]
                )
            ]
        )

        shard1_dump = shard1.model_dump()
        shard2_dump = shard2.model_dump()
        index_dump = index.model_dump(mode="json")

        mock_s3.download_json.side_effect = [
            index_dump,   # _load_index (finalize step 1)
            shard1_dump,  # _load_shard_v2 (finalize sub-a)
            shard2_dump,  # _load_shard_v2 (finalize sub-b)
            shard1_dump,  # _load_shard_v2 (refine names sub-a)
            shard2_dump,  # _load_shard_v2 (refine names sub-b)
            index_dump,   # _load_index (load_all_shards)
            shard1_dump,  # _load_shard_v2 (load_all_shards sub-a)
            shard2_dump,  # _load_shard_v2 (load_all_shards sub-b)
            # _merge_duplicate_shards: load shard1 and shard2
            shard1_dump,  # _load_shard_v2 (merge: shard1)
            shard2_dump,  # _load_shard_v2 (merge: shard2)
            # _remove_from_index: _load_index
            index_dump,
            # Final summary: _load_index
            index_dump,
        ]

        # Name refinement: no changes for both
        refinement1 = MagicMock()
        refinement1.topic_title = shard1.topic_title
        refinement1.topic_key = shard1.topic_key
        refinement1.subtopic_title = shard1.subtopic_title
        refinement1.subtopic_key = shard1.subtopic_key

        refinement2 = MagicMock()
        refinement2.topic_title = shard2.topic_title
        refinement2.topic_key = shard2.topic_key
        refinement2.subtopic_title = shard2.subtopic_title
        refinement2.subtopic_key = shard2.subtopic_key

        orchestrator.name_refinement.refine_names.side_effect = [refinement1, refinement2]

        # Dedup: one pair of duplicates
        orchestrator.dedup_service.deduplicate.return_value = [
            ("fractions", "sub-a", "fractions", "sub-b")
        ]

        # Merge service
        orchestrator.merge_service.merge.return_value = "Merged guidelines text."
        orchestrator.summary_service.generate_subtopic_summary.return_value = "Merged summary."
        orchestrator.summary_service.generate_topic_summary.return_value = "Topic summary."
        orchestrator.index_manager.save_index = MagicMock()

        result = await orchestrator.finalize_book("book-1", book_metadata)

        assert result["duplicates_merged"] == 1
        orchestrator.merge_service.merge.assert_called()

    @pytest.mark.asyncio
    async def test_finalize_with_db_sync(self, orchestrator, mock_s3, book_metadata):
        """Test that DB sync is called when auto_sync_to_db=True."""
        index = _make_index(topics=[])
        index_dump = index.model_dump(mode="json")

        mock_s3.download_json.side_effect = [
            index_dump,   # _load_index (finalize)
            index_dump,   # _load_index (load_all_shards)
            index_dump,   # _load_index (final summary)
        ]

        orchestrator.dedup_service.deduplicate.return_value = []
        orchestrator.summary_service.generate_topic_summary.return_value = "Summary."
        orchestrator.index_manager.save_index = MagicMock()
        orchestrator.db_sync.sync_book_guidelines.return_value = {
            "synced_count": 0,
            "created_count": 0,
            "updated_count": 0,
        }

        result = await orchestrator.finalize_book(
            "book-1", book_metadata, auto_sync_to_db=True
        )

        orchestrator.db_sync.sync_book_guidelines.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_skips_db_sync_when_disabled(
        self, orchestrator, mock_s3, book_metadata
    ):
        """DB sync should NOT be called when auto_sync_to_db=False."""
        index = _make_index(topics=[])
        index_dump = index.model_dump(mode="json")

        mock_s3.download_json.side_effect = [
            index_dump,
            index_dump,
            index_dump,
        ]

        orchestrator.dedup_service.deduplicate.return_value = []
        orchestrator.index_manager.save_index = MagicMock()

        await orchestrator.finalize_book(
            "book-1", book_metadata, auto_sync_to_db=False
        )

        if orchestrator.db_sync:
            orchestrator.db_sync.sync_book_guidelines.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_with_name_refinement(self, orchestrator, mock_s3, book_metadata):
        """Test that name refinement renames shards and updates index."""
        shard = _make_shard(topic_key="old-topic", subtopic_key="old-sub")
        index = _make_index(
            topics=[
                _make_topic_entry(
                    topic_key="old-topic",
                    subtopics=[
                        _make_subtopic_entry(subtopic_key="old-sub", status="open")
                    ],
                )
            ]
        )

        shard_dump = shard.model_dump()
        index_dump = index.model_dump(mode="json")

        mock_s3.download_json.side_effect = [
            index_dump,     # _load_index (finalize)
            shard_dump,     # _load_shard_v2 (finalize open)
            shard_dump,     # _load_shard_v2 (name refinement)
            index_dump,     # _update_index_names -> _load_index
            index_dump,     # _load_index (load_all_shards)
            shard_dump,     # _load_shard_v2 (load_all_shards) - note: uses old key
            index_dump,     # _load_index (final summary)
        ]

        # Name refinement returns new names
        refinement = MagicMock()
        refinement.topic_title = "New Topic"
        refinement.topic_key = "new-topic"
        refinement.subtopic_title = "New Sub"
        refinement.subtopic_key = "new-sub"
        orchestrator.name_refinement.refine_names.return_value = refinement

        orchestrator.dedup_service.deduplicate.return_value = []
        orchestrator.summary_service.generate_topic_summary.return_value = "Summary."
        orchestrator.index_manager.save_index = MagicMock()

        result = await orchestrator.finalize_book("book-1", book_metadata)

        assert result["subtopics_renamed"] == 1
        # Old shard should be deleted
        mock_s3.delete_file.assert_called()


# ============================================================================
# _merge_duplicate_shards TESTS
# ============================================================================

class TestMergeDuplicateShards:
    @pytest.mark.asyncio
    async def test_merge_duplicate_shards(self, orchestrator, mock_s3):
        shard1 = _make_shard(
            subtopic_key="sub-a", subtopic_title="Sub A",
            page_start=1, page_end=3
        )
        shard2 = _make_shard(
            subtopic_key="sub-b", subtopic_title="Sub B",
            page_start=5, page_end=7
        )

        mock_s3.download_json.side_effect = [
            shard1.model_dump(),                         # _load_shard_v2(shard1)
            shard2.model_dump(),                         # _load_shard_v2(shard2)
            _make_index().model_dump(mode="json"),       # _remove_from_index -> _load_index
        ]

        orchestrator.merge_service.merge.return_value = "Merged guidelines."
        orchestrator.summary_service.generate_subtopic_summary.return_value = "Merged summary."

        await orchestrator._merge_duplicate_shards(
            book_id="book-1",
            topic1="fractions", subtopic1="sub-a",
            topic2="fractions", subtopic2="sub-b",
            grade=3, subject="Math",
        )

        # merge_service.merge called with both shard guidelines
        orchestrator.merge_service.merge.assert_called_once_with(
            existing_guidelines=shard1.guidelines,
            new_page_guidelines=shard2.guidelines,
            topic_title=shard1.topic_title,
            subtopic_title=shard1.subtopic_title,
            grade=3,
            subject="Math",
        )

        # shard1 saved with merged page range
        save_call = mock_s3.upload_json.call_args_list[0]
        saved_data = save_call[0][0]
        assert saved_data["source_page_start"] == 1
        assert saved_data["source_page_end"] == 7
        assert saved_data["guidelines"] == "Merged guidelines."
        assert saved_data["version"] == 2

        # shard2 deleted
        mock_s3.delete_file.assert_called()

    @pytest.mark.asyncio
    async def test_merge_duplicate_shards_page_range(self, orchestrator, mock_s3):
        """Merged shard should have min start and max end page."""
        shard1 = _make_shard(page_start=10, page_end=15)
        shard2 = _make_shard(page_start=3, page_end=20)

        mock_s3.download_json.side_effect = [
            shard1.model_dump(),
            shard2.model_dump(),
            _make_index().model_dump(mode="json"),
        ]

        orchestrator.merge_service.merge.return_value = "Merged."
        orchestrator.summary_service.generate_subtopic_summary.return_value = "Summary."

        await orchestrator._merge_duplicate_shards(
            "book-1", "fractions", "sub-a", "fractions", "sub-b", 3, "Math"
        )

        saved_data = mock_s3.upload_json.call_args_list[0][0][0]
        assert saved_data["source_page_start"] == 3
        assert saved_data["source_page_end"] == 20


# ============================================================================
# _update_indices TESTS
# ============================================================================

class TestUpdateIndices:
    def test_update_indices_calls_index_manager(self, orchestrator):
        """Should call index_manager methods for both index and page_index."""
        orchestrator.index_manager.get_or_create_index.return_value = _make_index()
        orchestrator.index_manager.add_or_update_subtopic.return_value = _make_index()
        orchestrator.index_manager.get_or_create_page_index.return_value = PageIndex(
            book_id="book-1"
        )
        orchestrator.index_manager.add_page_assignment.return_value = PageIndex(
            book_id="book-1"
        )

        orchestrator._update_indices(
            book_id="book-1",
            topic_key="fractions",
            topic_title="Fractions",
            subtopic_key="adding",
            subtopic_title="Adding",
            page_num=5,
            status="open",
            source_page_start=3,
            source_page_end=5,
            subtopic_summary="Summary.",
            topic_summary="Topic summary.",
        )

        orchestrator.index_manager.get_or_create_index.assert_called_once_with("book-1")
        orchestrator.index_manager.add_or_update_subtopic.assert_called_once()
        orchestrator.index_manager.save_index.assert_called_once()
        orchestrator.index_manager.get_or_create_page_index.assert_called_once_with("book-1")
        orchestrator.index_manager.add_page_assignment.assert_called_once()
        orchestrator.index_manager.save_page_index.assert_called_once()

    def test_update_indices_page_range_format(self, orchestrator):
        """Page range should be formatted as 'start-end'."""
        orchestrator.index_manager.get_or_create_index.return_value = _make_index()
        orchestrator.index_manager.add_or_update_subtopic.return_value = _make_index()
        orchestrator.index_manager.get_or_create_page_index.return_value = PageIndex(
            book_id="book-1"
        )
        orchestrator.index_manager.add_page_assignment.return_value = PageIndex(
            book_id="book-1"
        )

        orchestrator._update_indices(
            book_id="book-1",
            topic_key="t",
            topic_title="T",
            subtopic_key="s",
            subtopic_title="S",
            page_num=7,
            status="open",
            source_page_start=3,
            source_page_end=7,
        )

        call_kwargs = orchestrator.index_manager.add_or_update_subtopic.call_args
        assert call_kwargs[1]["page_range"] == "3-7" or call_kwargs.kwargs.get("page_range") == "3-7"
