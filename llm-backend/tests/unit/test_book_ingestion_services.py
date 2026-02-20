"""
Tests for book ingestion pipeline services:
- BoundaryDetectionService
- TopicDeduplicationService
- TopicNameRefinementService
- TopicSubtopicSummaryService
- MinisummaryService
- GuidelineMergeService
- ContextPackService
- IndexManagementService
- DBSyncService
- OCRService
- GuidelineExtractionOrchestrator

All LLM, S3, and DB calls are mocked.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from book_ingestion.models.guideline_models import (
    SubtopicShard,
    ContextPack,
    BoundaryDecision,
    TopicNameRefinement,
    MinisummaryResponse,
    GuidelinesIndex,
    TopicIndexEntry,
    SubtopicIndexEntry,
    PageIndex,
    PageAssignment,
    OpenTopicInfo,
    OpenSubtopicInfo,
    RecentPageSummary,
    ToCHints,
)


# ============================================================================
# Helper to build a mock OpenAI response
# ============================================================================

def _mock_openai_response(content: str):
    """Create a mock OpenAI chat completion response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    return mock_response


def _make_shard(**overrides):
    """Create a SubtopicShard with sensible defaults."""
    defaults = dict(
        topic_key="fractions",
        topic_title="Fractions",
        subtopic_key="adding-fractions",
        subtopic_title="Adding Fractions",
        source_page_start=1,
        source_page_end=3,
        guidelines="Teach adding fractions using visual models and number lines.",
        version=1,
    )
    defaults.update(overrides)
    return SubtopicShard(**defaults)


# ============================================================================
# BoundaryDetectionService Tests
# ============================================================================

class TestBoundaryDetectionService:
    """Tests for BoundaryDetectionService."""

    def _make_service(self):
        mock_client = MagicMock()
        with patch(
            "book_ingestion.services.boundary_detection_service.BoundaryDetectionService._load_prompt_template",
            return_value="Grade: {grade}, Subject: {subject}, Board: {board}, Page: {current_page}\n{open_topics}\n{recent_summaries}\n{page_text}"
        ):
            from book_ingestion.services.boundary_detection_service import BoundaryDetectionService
            service = BoundaryDetectionService(openai_client=mock_client, model="gpt-4o-mini")
        return service, mock_client

    def test_detect_new_topic(self):
        service, mock_client = self._make_service()
        response_data = {
            "is_new_topic": True,
            "topic_name": "data-handling",
            "subtopic_name": "pictographs",
            "page_guidelines": "Guidelines for pictographs page.",
            "reasoning": "New chapter on data handling.",
        }
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps(response_data)
        )

        context_pack = ContextPack(
            book_id="test",
            current_page=5,
            book_metadata={"grade": 3, "subject": "Math", "board": "CBSE"},
        )

        is_new, topic_key, topic_title, subtopic_key, subtopic_title, guidelines = service.detect(
            context_pack, "Page text about data handling."
        )

        assert is_new is True
        assert topic_key == "data-handling"
        assert subtopic_key == "pictographs"
        assert "pictographs" in guidelines.lower()

    def test_detect_continue_topic(self):
        service, mock_client = self._make_service()
        response_data = {
            "is_new_topic": False,
            "topic_name": "fractions",
            "subtopic_name": "adding-fractions",
            "page_guidelines": "More guidelines on adding fractions.",
            "reasoning": "Continues existing topic.",
        }
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps(response_data)
        )

        context_pack = ContextPack(
            book_id="test",
            current_page=3,
            book_metadata={"grade": 3, "subject": "Math", "board": "CBSE"},
            open_topics=[
                OpenTopicInfo(
                    topic_key="fractions",
                    topic_title="Fractions",
                    open_subtopics=[
                        OpenSubtopicInfo(
                            subtopic_key="adding-fractions",
                            subtopic_title="Adding Fractions",
                            page_start=1,
                            page_end=2,
                            guidelines="Existing guidelines.",
                        )
                    ],
                )
            ],
        )

        is_new, topic_key, topic_title, subtopic_key, subtopic_title, guidelines = service.detect(
            context_pack, "Page text continuing fractions."
        )

        assert is_new is False
        assert topic_key == "fractions"

    def test_detect_invalid_json_raises_value_error(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "not valid json"
        )

        context_pack = ContextPack(
            book_id="test",
            current_page=1,
            book_metadata={"grade": 3, "subject": "Math", "board": "CBSE"},
        )

        with pytest.raises(ValueError, match="Invalid JSON"):
            service.detect(context_pack, "Some page text.")

    def test_build_prompt_no_open_topics(self):
        service, _ = self._make_service()
        context_pack = ContextPack(
            book_id="test",
            current_page=1,
            book_metadata={"grade": 3, "subject": "Math", "board": "CBSE"},
        )

        prompt = service._build_prompt(context_pack, "Page text here.")

        assert "Grade: 3" in prompt
        assert "No open topics yet" in prompt

    def test_build_prompt_with_open_topics(self):
        service, _ = self._make_service()
        context_pack = ContextPack(
            book_id="test",
            current_page=5,
            book_metadata={"grade": 3, "subject": "Math", "board": "CBSE"},
            open_topics=[
                OpenTopicInfo(
                    topic_key="fractions",
                    topic_title="Fractions",
                    open_subtopics=[
                        OpenSubtopicInfo(
                            subtopic_key="adding",
                            subtopic_title="Adding",
                            page_start=1,
                            page_end=3,
                            guidelines="Guidelines for adding fractions.",
                        )
                    ],
                )
            ],
            recent_page_summaries=[
                RecentPageSummary(page=4, summary="Summary of page 4")
            ],
        )

        prompt = service._build_prompt(context_pack, "Page 5 text.")

        assert "Fractions" in prompt
        assert "Page 5 text." in prompt


# ============================================================================
# TopicDeduplicationService Tests
# ============================================================================

class TestTopicDeduplicationService:
    """Tests for TopicDeduplicationService."""

    def _make_service(self):
        mock_client = MagicMock()
        with patch(
            "book_ingestion.services.topic_deduplication_service.TopicDeduplicationService._load_prompt_template",
            return_value="Grade: {grade}, Subject: {subject}\n{topics_summary}"
        ):
            from book_ingestion.services.topic_deduplication_service import TopicDeduplicationService
            service = TopicDeduplicationService(openai_client=mock_client, model="gpt-4o-mini")
        return service, mock_client

    def test_empty_shards(self):
        service, _ = self._make_service()

        result = service.deduplicate([], grade=3, subject="Math")

        assert result == []

    def test_single_shard(self):
        service, _ = self._make_service()

        result = service.deduplicate([_make_shard()], grade=3, subject="Math")

        assert result == []

    def test_no_duplicates_found(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"duplicates": []})
        )

        shards = [
            _make_shard(topic_key="fractions", subtopic_key="adding"),
            _make_shard(topic_key="geometry", subtopic_key="shapes"),
        ]

        result = service.deduplicate(shards, grade=3, subject="Math")

        assert result == []

    def test_duplicates_found(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({
                "duplicates": [
                    {
                        "topic_key1": "data-handling",
                        "subtopic_key1": "pictographs",
                        "topic_key2": "data-handling-basics",
                        "subtopic_key2": "pictograph-reading",
                    }
                ]
            })
        )

        shards = [
            _make_shard(topic_key="data-handling", subtopic_key="pictographs"),
            _make_shard(topic_key="data-handling-basics", subtopic_key="pictograph-reading"),
        ]

        result = service.deduplicate(shards, grade=3, subject="Math")

        assert len(result) == 1
        assert result[0] == (
            "data-handling", "pictographs",
            "data-handling-basics", "pictograph-reading",
        )

    def test_invalid_json_returns_empty(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "not valid json"
        )

        shards = [
            _make_shard(topic_key="a", subtopic_key="b"),
            _make_shard(topic_key="c", subtopic_key="d"),
        ]

        result = service.deduplicate(shards, grade=3, subject="Math")

        assert result == []  # Safe fallback

    def test_llm_error_returns_empty(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.side_effect = Exception("LLM error")

        shards = [
            _make_shard(topic_key="a", subtopic_key="b"),
            _make_shard(topic_key="c", subtopic_key="d"),
        ]

        result = service.deduplicate(shards, grade=3, subject="Math")

        assert result == []

    def test_build_topics_summary(self):
        service, _ = self._make_service()
        shards = [
            _make_shard(
                topic_key="fractions", topic_title="Fractions",
                subtopic_key="adding", subtopic_title="Adding",
                guidelines="Short guidelines.",
            ),
        ]

        summary = service._build_topics_summary(shards)

        assert "Fractions" in summary
        assert "adding" in summary


# ============================================================================
# TopicNameRefinementService Tests
# ============================================================================

class TestTopicNameRefinementService:
    """Tests for TopicNameRefinementService."""

    def _make_service(self):
        mock_client = MagicMock()
        with patch(
            "book_ingestion.services.topic_name_refinement_service.TopicNameRefinementService._load_prompt_template",
            return_value=(
                "Grade: {grade}, Subject: {subject}, Board: {board}, Country: {country}\n"
                "Topic: {current_topic_title} ({current_topic_key})\n"
                "Subtopic: {current_subtopic_title} ({current_subtopic_key})\n"
                "Guidelines: {guidelines}\nPages: {page_start}-{page_end}"
            )
        ):
            from book_ingestion.services.topic_name_refinement_service import TopicNameRefinementService
            service = TopicNameRefinementService(openai_client=mock_client, model="gpt-4o-mini")
        return service, mock_client

    def test_refine_names_success(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({
                "topic_title": "Fractions",
                "topic_key": "fractions",
                "subtopic_title": "Adding Like Fractions",
                "subtopic_key": "adding-like-fractions",
                "reasoning": "More specific name.",
            })
        )

        shard = _make_shard()
        book_metadata = {"grade": 3, "subject": "Math", "board": "CBSE", "country": "India"}

        result = service.refine_names(shard, book_metadata)

        assert isinstance(result, TopicNameRefinement)
        assert result.subtopic_title == "Adding Like Fractions"

    def test_refine_names_error_returns_original(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.side_effect = Exception("LLM error")

        shard = _make_shard()
        book_metadata = {"grade": 3, "subject": "Math", "board": "CBSE"}

        result = service.refine_names(shard, book_metadata)

        # Should return original names on error
        assert result.topic_key == shard.topic_key
        assert result.subtopic_key == shard.subtopic_key
        assert "Error" in result.reasoning


# ============================================================================
# TopicSubtopicSummaryService Tests
# ============================================================================

class TestTopicSubtopicSummaryService:
    """Tests for TopicSubtopicSummaryService."""

    def _make_service(self):
        mock_client = MagicMock()
        with patch(
            "book_ingestion.services.topic_subtopic_summary_service.TopicSubtopicSummaryService._load_prompt",
            return_value="Summarize: {subtopic_title}\n{guidelines}"
        ):
            from book_ingestion.services.topic_subtopic_summary_service import TopicSubtopicSummaryService
            service = TopicSubtopicSummaryService(openai_client=mock_client, model="gpt-4o-mini")
        return service, mock_client

    def test_generate_subtopic_summary(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Covers adding fractions with like denominators."
        )

        result = service.generate_subtopic_summary(
            "Adding Fractions",
            "Full guidelines text about adding fractions."
        )

        assert "adding fractions" in result.lower()

    def test_generate_subtopic_summary_error_fallback(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.side_effect = Exception("LLM error")

        result = service.generate_subtopic_summary("Adding Fractions", "Guidelines")

        assert "Adding Fractions" in result

    def test_generate_topic_summary(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Comprehensive topic covering fractions operations."
        )

        result = service.generate_topic_summary(
            "Fractions",
            ["Summary of adding fractions", "Summary of subtracting fractions"]
        )

        assert len(result) > 0

    def test_generate_topic_summary_empty_subtopics(self):
        service, _ = self._make_service()

        result = service.generate_topic_summary("Fractions", [])

        assert "Fractions" in result  # Fallback

    def test_fallback_summary(self):
        service, _ = self._make_service()

        result = service._fallback_summary("Fractions")

        assert "Fractions" in result
        assert "guidelines" in result.lower()


# ============================================================================
# MinisummaryService Tests
# ============================================================================

class TestMinisummaryService:
    """Tests for MinisummaryService."""

    def _make_service(self):
        mock_client = MagicMock()
        with patch(
            "book_ingestion.services.minisummary_service.MinisummaryService._load_prompt_template",
            return_value="Summarize: {page_text}"
        ):
            from book_ingestion.services.minisummary_service import MinisummaryService
            service = MinisummaryService(openai_client=mock_client, model="gpt-4o-mini")
        return service, mock_client

    def test_generate_summary(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "This page introduces fractions."
        )

        result = service.generate("Page text about fractions and examples.")

        assert result == "This page introduces fractions."

    def test_empty_text_raises_value_error(self):
        service, _ = self._make_service()

        with pytest.raises(ValueError, match="empty"):
            service.generate("")

    def test_whitespace_only_text_raises_value_error(self):
        service, _ = self._make_service()

        with pytest.raises(ValueError, match="empty"):
            service.generate("   ")

    def test_llm_returns_empty_summary_raises(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response("")

        with pytest.raises(ValueError, match="empty summary"):
            service.generate("Some page text.")

    def test_text_truncation(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Summary"
        )

        long_text = "A" * 5000
        service.generate(long_text)

        # Check that the prompt used truncated text
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        user_content = None
        for msg in call_args[1].get("messages", call_args.kwargs.get("messages", [])):
            if msg["role"] == "user":
                user_content = msg["content"]
        # The truncated text should be max 3000 chars
        if user_content:
            assert len(user_content) <= 3100  # template + truncated text

    def test_generate_batch(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Summary."
        )

        results = service.generate_batch(["Page 1 text", "Page 2 text"])

        assert len(results) == 2
        assert all(r == "Summary." for r in results)

    def test_generate_batch_with_error_uses_fallback(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.side_effect = [
            _mock_openai_response("Good summary."),
            Exception("LLM error"),
        ]

        results = service.generate_batch(["Page 1 text", "Page 2 text with more words"])

        assert len(results) == 2
        assert results[0] == "Good summary."
        # Second should be a fallback (first 60 words)
        assert "Page 2" in results[1]


# ============================================================================
# GuidelineMergeService Tests
# ============================================================================

class TestGuidelineMergeService:
    """Tests for GuidelineMergeService."""

    def _make_service(self):
        mock_client = MagicMock()
        with patch(
            "book_ingestion.services.guideline_merge_service.GuidelineMergeService._load_prompt_template",
            return_value=(
                "Topic: {topic}, Subtopic: {subtopic}\n"
                "Grade: {grade}, Subject: {subject}\n"
                "Existing: {existing_guidelines}\nNew: {new_page_guidelines}"
            )
        ):
            from book_ingestion.services.guideline_merge_service import GuidelineMergeService
            service = GuidelineMergeService(openai_client=mock_client, model="gpt-4o-mini")
        return service, mock_client

    def test_merge_success(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Merged guidelines text covering adding and subtracting fractions."
        )

        result = service.merge(
            existing_guidelines="Guidelines about adding fractions.",
            new_page_guidelines="Guidelines about subtracting fractions.",
            topic_title="Fractions",
            subtopic_title="Operations",
            grade=3,
            subject="Math",
        )

        assert "Merged guidelines" in result

    def test_merge_empty_response_uses_fallback(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.return_value = _mock_openai_response("")

        result = service.merge(
            existing_guidelines="Existing.",
            new_page_guidelines="New.",
            topic_title="T",
            subtopic_title="S",
            grade=3,
            subject="Math",
        )

        # Fallback is simple concatenation
        assert "Existing." in result
        assert "New." in result

    def test_merge_llm_error_uses_fallback(self):
        service, mock_client = self._make_service()
        mock_client.chat.completions.create.side_effect = Exception("LLM error")

        result = service.merge(
            existing_guidelines="Existing guidelines.",
            new_page_guidelines="New guidelines.",
            topic_title="T",
            subtopic_title="S",
            grade=3,
            subject="Math",
        )

        assert "Existing guidelines." in result
        assert "New guidelines." in result


# ============================================================================
# ContextPackService Tests
# ============================================================================

class TestContextPackService:
    """Tests for ContextPackService."""

    def _make_service(self):
        mock_s3 = MagicMock()
        from book_ingestion.services.context_pack_service import ContextPackService
        service = ContextPackService(s3_client=mock_s3)
        return service, mock_s3

    def test_build_first_page_no_index(self):
        service, mock_s3 = self._make_service()
        mock_s3.download_json.side_effect = Exception("Not found")

        result = service.build(
            book_id="test",
            current_page=1,
            book_metadata={"grade": 3, "subject": "Math"},
        )

        assert isinstance(result, ContextPack)
        assert result.current_page == 1
        assert result.open_topics == []
        assert result.recent_page_summaries == []

    def test_build_with_existing_index(self):
        service, mock_s3 = self._make_service()

        index_data = {
            "book_id": "test",
            "topics": [
                {
                    "topic_key": "fractions",
                    "topic_title": "Fractions",
                    "subtopics": [
                        {
                            "subtopic_key": "adding",
                            "subtopic_title": "Adding",
                            "status": "open",
                            "page_range": "1-3",
                        }
                    ],
                }
            ],
            "version": 1,
            "last_updated": datetime.utcnow().isoformat(),
        }

        shard_data = {
            "topic_key": "fractions",
            "topic_title": "Fractions",
            "subtopic_key": "adding",
            "subtopic_title": "Adding",
            "source_page_start": 1,
            "source_page_end": 3,
            "guidelines": "Guidelines text.",
            "version": 1,
        }

        page_guideline_data = {"page": 4, "summary": "Summary of page 4"}

        def download_json_side_effect(key):
            if "index.json" in key:
                return index_data
            if "latest.json" in key:
                return shard_data
            if "page_guideline" in key:
                return page_guideline_data
            raise Exception(f"Unexpected key: {key}")

        mock_s3.download_json.side_effect = download_json_side_effect

        result = service.build(
            book_id="test",
            current_page=5,
            book_metadata={"grade": 3, "subject": "Math"},
        )

        assert len(result.open_topics) == 1
        assert result.open_topics[0].topic_key == "fractions"

    def test_build_toc_hints_empty(self):
        service, _ = self._make_service()
        index = GuidelinesIndex(book_id="test", topics=[])

        hints = service._build_toc_hints(index)

        assert hints.current_chapter is None
        assert hints.next_section_candidate is None

    def test_build_toc_hints_with_topics(self):
        service, _ = self._make_service()
        index = GuidelinesIndex(
            book_id="test",
            topics=[
                TopicIndexEntry(topic_key="fractions", topic_title="Fractions"),
                TopicIndexEntry(topic_key="geometry", topic_title="Geometry"),
            ],
        )

        hints = service._build_toc_hints(index)

        assert hints.current_chapter == "Geometry"

    def test_get_recent_summaries_first_page(self):
        service, mock_s3 = self._make_service()

        result = service._get_recent_summaries("test", current_page=1, num_recent=5)

        assert result == []

    def test_get_recent_summaries_with_missing_pages(self):
        service, mock_s3 = self._make_service()
        mock_s3.download_json.side_effect = Exception("Not found")

        result = service._get_recent_summaries("test", current_page=5, num_recent=3)

        assert result == []


# ============================================================================
# IndexManagementService Tests
# ============================================================================

class TestIndexManagementService:
    """Tests for IndexManagementService."""

    def _make_service(self):
        mock_s3 = MagicMock()
        from book_ingestion.services.index_management_service import IndexManagementService
        service = IndexManagementService(s3_client=mock_s3)
        return service, mock_s3

    def test_get_or_create_index_no_existing(self):
        service, mock_s3 = self._make_service()
        mock_s3.download_json.side_effect = Exception("Not found")

        result = service.get_or_create_index("test-book")

        assert isinstance(result, GuidelinesIndex)
        assert result.book_id == "test-book"
        assert result.topics == []

    def test_get_or_create_index_existing(self):
        service, mock_s3 = self._make_service()
        mock_s3.download_json.return_value = {
            "book_id": "test-book",
            "topics": [],
            "version": 5,
            "last_updated": datetime.utcnow().isoformat(),
        }

        result = service.get_or_create_index("test-book")

        assert result.version == 5

    def test_add_or_update_subtopic_new_topic(self):
        service, _ = self._make_service()
        index = GuidelinesIndex(book_id="test")

        result = service.add_or_update_subtopic(
            index=index,
            topic_key="fractions",
            topic_title="Fractions",
            subtopic_key="adding",
            subtopic_title="Adding",
            page_range="1-3",
            status="open",
        )

        assert len(result.topics) == 1
        assert result.topics[0].topic_key == "fractions"
        assert len(result.topics[0].subtopics) == 1
        assert result.version == 2  # Incremented

    def test_add_or_update_subtopic_existing_topic_new_subtopic(self):
        service, _ = self._make_service()
        index = GuidelinesIndex(
            book_id="test",
            topics=[
                TopicIndexEntry(
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
            ],
        )

        result = service.add_or_update_subtopic(
            index=index,
            topic_key="fractions",
            topic_title="Fractions",
            subtopic_key="subtracting",
            subtopic_title="Subtracting",
            page_range="4-6",
            status="open",
        )

        assert len(result.topics) == 1
        assert len(result.topics[0].subtopics) == 2

    def test_add_or_update_subtopic_updates_existing(self):
        service, _ = self._make_service()
        index = GuidelinesIndex(
            book_id="test",
            topics=[
                TopicIndexEntry(
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
            ],
        )

        result = service.add_or_update_subtopic(
            index=index,
            topic_key="fractions",
            topic_title="Fractions",
            subtopic_key="adding",
            subtopic_title="Adding",
            page_range="1-5",
            status="stable",
        )

        assert result.topics[0].subtopics[0].status == "stable"
        assert result.topics[0].subtopics[0].page_range == "1-5"

    def test_update_subtopic_status(self):
        service, _ = self._make_service()
        index = GuidelinesIndex(
            book_id="test",
            topics=[
                TopicIndexEntry(
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
            ],
        )

        result = service.update_subtopic_status(
            index=index,
            topic_key="fractions",
            subtopic_key="adding",
            new_status="stable",
        )

        assert result.topics[0].subtopics[0].status == "stable"

    def test_update_subtopic_status_not_found(self):
        service, _ = self._make_service()
        index = GuidelinesIndex(book_id="test", topics=[])

        with pytest.raises(ValueError, match="not found"):
            service.update_subtopic_status(
                index=index,
                topic_key="fractions",
                subtopic_key="adding",
                new_status="stable",
            )

    def test_save_index(self):
        service, mock_s3 = self._make_service()
        # No existing index for snapshot
        mock_s3.download_json.side_effect = Exception("Not found")

        index = GuidelinesIndex(book_id="test")

        service.save_index(index, create_snapshot=False)

        mock_s3.upload_json.assert_called_once()

    def test_save_index_with_snapshot(self):
        service, mock_s3 = self._make_service()
        # Return existing index for snapshot
        mock_s3.download_json.return_value = {
            "book_id": "test",
            "topics": [],
            "version": 1,
            "last_updated": datetime.utcnow().isoformat(),
        }

        index = GuidelinesIndex(book_id="test", version=2)

        service.save_index(index, create_snapshot=True)

        # Should have called upload_json twice: snapshot + actual
        assert mock_s3.upload_json.call_count == 2

    def test_get_or_create_page_index_no_existing(self):
        service, mock_s3 = self._make_service()
        mock_s3.download_json.side_effect = Exception("Not found")

        result = service.get_or_create_page_index("test-book")

        assert isinstance(result, PageIndex)
        assert result.pages == {}

    def test_add_page_assignment(self):
        service, _ = self._make_service()
        page_index = PageIndex(book_id="test")

        result = service.add_page_assignment(
            page_index=page_index,
            page_num=1,
            topic_key="fractions",
            subtopic_key="adding",
            confidence=0.9,
        )

        assert 1 in result.pages
        assert result.pages[1].topic_key == "fractions"
        assert result.pages[1].confidence == 0.9
        assert result.version == 2

    def test_get_page_assignment_found(self):
        service, _ = self._make_service()
        page_index = PageIndex(
            book_id="test",
            pages={
                1: PageAssignment(
                    topic_key="fractions",
                    subtopic_key="adding",
                    confidence=0.9,
                )
            },
        )

        result = service.get_page_assignment(page_index, 1)

        assert result is not None
        assert result.topic_key == "fractions"

    def test_get_page_assignment_not_found(self):
        service, _ = self._make_service()
        page_index = PageIndex(book_id="test")

        result = service.get_page_assignment(page_index, 999)

        assert result is None

    def test_get_pages_for_subtopic(self):
        service, _ = self._make_service()
        page_index = PageIndex(
            book_id="test",
            pages={
                1: PageAssignment(topic_key="fractions", subtopic_key="adding", confidence=0.9),
                2: PageAssignment(topic_key="fractions", subtopic_key="adding", confidence=0.85),
                3: PageAssignment(topic_key="geometry", subtopic_key="shapes", confidence=0.9),
            },
        )

        result = service.get_pages_for_subtopic(page_index, "fractions", "adding")

        assert result == [1, 2]

    def test_get_pages_for_subtopic_not_found(self):
        service, _ = self._make_service()
        page_index = PageIndex(book_id="test")

        result = service.get_pages_for_subtopic(page_index, "fractions", "adding")

        assert result == []


# ============================================================================
# DBSyncService Tests
# ============================================================================

class TestDBSyncService:
    """Tests for DBSyncService."""

    def _make_service(self):
        mock_db = MagicMock()
        from book_ingestion.services.db_sync_service import DBSyncService
        service = DBSyncService(db_session=mock_db)
        return service, mock_db

    def test_sync_shard_new(self):
        service, mock_db = self._make_service()
        # No existing guideline
        mock_db.execute.return_value.fetchone.side_effect = [None, ("new-id",)]

        shard = _make_shard()

        result = service.sync_shard(
            shard=shard,
            book_id="test-book",
            grade=3,
            subject="Math",
            board="CBSE",
        )

        assert result == "new-id"
        assert mock_db.commit.called

    def test_sync_shard_existing(self):
        service, mock_db = self._make_service()
        # Existing guideline found
        mock_db.execute.return_value.fetchone.return_value = ("existing-id",)

        shard = _make_shard()

        result = service.sync_shard(
            shard=shard,
            book_id="test-book",
            grade=3,
            subject="Math",
            board="CBSE",
        )

        assert result == "existing-id"

    def test_sync_multiple_shards(self):
        service, mock_db = self._make_service()
        # Alternating: no existing, then insert
        mock_db.execute.return_value.fetchone.side_effect = [
            None, ("id1",),  # First shard: not found, then insert
            None, ("id2",),  # Second shard: not found, then insert
        ]

        shards = [
            _make_shard(subtopic_key="adding"),
            _make_shard(subtopic_key="subtracting"),
        ]

        result = service.sync_multiple_shards(
            shards=shards,
            book_id="test-book",
            grade=3,
            subject="Math",
            board="CBSE",
        )

        assert len(result) == 2

    def test_sync_book_guidelines_no_index(self):
        service, mock_db = self._make_service()
        mock_s3 = MagicMock()
        mock_s3.download_json.side_effect = Exception("Not found")

        result = service.sync_book_guidelines(
            book_id="test",
            s3_client=mock_s3,
            book_metadata={"grade": 3, "subject": "Math", "board": "CBSE"},
        )

        assert result["synced_count"] == 0

    def test_sync_book_guidelines_with_shards(self):
        service, mock_db = self._make_service()
        mock_s3 = MagicMock()

        index_data = {
            "book_id": "test",
            "topics": [
                {
                    "topic_key": "fractions",
                    "topic_title": "Fractions",
                    "topic_summary": "About fractions",
                    "subtopics": [
                        {
                            "subtopic_key": "adding",
                            "subtopic_title": "Adding",
                            "status": "final",
                            "page_range": "1-3",
                        }
                    ],
                }
            ],
            "version": 1,
            "last_updated": datetime.utcnow().isoformat(),
        }

        shard_data = {
            "topic_key": "fractions",
            "topic_title": "Fractions",
            "subtopic_key": "adding",
            "subtopic_title": "Adding",
            "source_page_start": 1,
            "source_page_end": 3,
            "guidelines": "Guidelines text.",
            "version": 1,
        }

        def download_json_side_effect(key):
            if "index.json" in key:
                return index_data
            return shard_data

        mock_s3.download_json.side_effect = download_json_side_effect
        mock_db.execute.return_value.fetchone.return_value = ("new-id",)

        result = service.sync_book_guidelines(
            book_id="test",
            s3_client=mock_s3,
            book_metadata={"grade": 3, "subject": "Math", "board": "CBSE"},
        )

        assert result["synced_count"] == 1
        assert result["created_count"] == 1


# ============================================================================
# OCRService Tests
# ============================================================================

class TestOCRService:
    """Tests for OCRService."""

    @patch("book_ingestion.services.ocr_service.get_settings")
    @patch("book_ingestion.services.ocr_service.OpenAI")
    def test_extract_text_from_image_bytes(self, MockOpenAI, mock_settings):
        mock_settings.return_value.openai_api_key = "test-key"
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Extracted text from page."
        )

        from book_ingestion.services.ocr_service import OCRService
        service = OCRService(model="gpt-4o-mini")

        result = service.extract_text_from_image(image_bytes=b"fake image bytes")

        assert result == "Extracted text from page."

    @patch("book_ingestion.services.ocr_service.get_settings")
    @patch("book_ingestion.services.ocr_service.OpenAI")
    def test_extract_text_no_input_raises(self, MockOpenAI, mock_settings):
        mock_settings.return_value.openai_api_key = "test-key"
        MockOpenAI.return_value = MagicMock()

        from book_ingestion.services.ocr_service import OCRService
        service = OCRService(model="gpt-4o-mini")

        with pytest.raises(ValueError, match="Either image_path or image_bytes"):
            service.extract_text_from_image()

    @patch("book_ingestion.services.ocr_service.get_settings")
    @patch("book_ingestion.services.ocr_service.OpenAI")
    def test_encode_bytes_to_base64(self, MockOpenAI, mock_settings):
        mock_settings.return_value.openai_api_key = "test-key"
        MockOpenAI.return_value = MagicMock()

        from book_ingestion.services.ocr_service import OCRService
        service = OCRService(model="gpt-4o-mini")

        result = service.encode_bytes_to_base64(b"hello")

        import base64
        assert result == base64.b64encode(b"hello").decode("utf-8")

    @patch("book_ingestion.services.ocr_service.get_settings")
    @patch("book_ingestion.services.ocr_service.OpenAI")
    def test_extract_text_with_retry_success(self, MockOpenAI, mock_settings):
        mock_settings.return_value.openai_api_key = "test-key"
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Extracted."
        )

        from book_ingestion.services.ocr_service import OCRService
        service = OCRService(model="gpt-4o-mini")

        result = service.extract_text_with_retry(image_bytes=b"img", max_retries=2)

        assert result == "Extracted."

    @patch("book_ingestion.services.ocr_service.get_settings")
    @patch("book_ingestion.services.ocr_service.OpenAI")
    def test_extract_text_with_retry_eventual_success(self, MockOpenAI, mock_settings):
        mock_settings.return_value.openai_api_key = "test-key"
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            Exception("Temporary failure"),
            _mock_openai_response("Success on retry."),
        ]

        from book_ingestion.services.ocr_service import OCRService
        service = OCRService(model="gpt-4o-mini")

        result = service.extract_text_with_retry(image_bytes=b"img", max_retries=2)

        assert result == "Success on retry."

    @patch("book_ingestion.services.ocr_service.get_settings")
    @patch("book_ingestion.services.ocr_service.OpenAI")
    def test_extract_text_with_retry_all_fail(self, MockOpenAI, mock_settings):
        mock_settings.return_value.openai_api_key = "test-key"
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("Permanent failure")

        from book_ingestion.services.ocr_service import OCRService
        service = OCRService(model="gpt-4o-mini")

        with pytest.raises(Exception, match="failed after"):
            service.extract_text_with_retry(image_bytes=b"img", max_retries=1)
