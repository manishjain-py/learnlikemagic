"""Integration tests for summary feature."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from ..services.guideline_extraction_orchestrator import GuidelineExtractionOrchestrator
from ..models.guideline_models import SubtopicShard, GuidelinesIndex, TopicIndexEntry, SubtopicIndexEntry

class TestSummaryIntegration:

    @pytest.fixture
    def mock_s3(self):
        s3 = MagicMock()
        # Mock index download
        s3.download_json.return_value = {
            "book_id": "test_book",
            "topics": [],
            "version": 1,
            "updated_at": "2023-01-01T00:00:00"
        }
        return s3

    @pytest.fixture
    def mock_openai(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock()
        # Mock response for summary generation
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Generated Summary"))]
        )
        return client

    @pytest.fixture
    def orchestrator(self, mock_s3, mock_openai):
        with patch('features.book_ingestion.services.guideline_extraction_orchestrator.DBSyncService'):
            return GuidelineExtractionOrchestrator(
                s3_client=mock_s3,
                openai_client=mock_openai
            )

    @pytest.mark.asyncio
    async def test_process_page_generates_summaries(self, orchestrator, mock_s3):
        """Test that process_page triggers summary generation and updates index."""
        # Mock shard creation
        orchestrator._create_shard_v2 = MagicMock(return_value=SubtopicShard(
            topic_key="math",
            topic_title="Math",
            subtopic_key="addition",
            subtopic_title="Addition",
            guidelines="Guidelines",
            source_page_start=1,
            source_page_end=1,
            version=1,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        ))

        # Mock collect summaries
        orchestrator._collect_subtopic_summaries = AsyncMock(return_value=["Summary 1"])

        # Mock update indices to verify it receives summaries
        orchestrator._update_indices = MagicMock()

        await orchestrator.process_page("test_book", 1, {})

        # Verify summary service was called
        # (Implicitly verified by checking if _update_indices received summaries)
        
        # Verify _update_indices called with summaries
        call_args = orchestrator._update_indices.call_args
        assert call_args.kwargs['subtopic_summary'] == "Generated Summary"
        assert call_args.kwargs['topic_summary'] == "Generated Summary"

    @pytest.mark.asyncio
    async def test_finalize_book_regenerates_topic_summaries(self, orchestrator, mock_s3):
        """Test that finalize_book regenerates topic summaries."""
        # Mock index with existing topics
        index = GuidelinesIndex(
            book_id="test_book",
            topics=[
                TopicIndexEntry(
                    topic_key="math",
                    topic_title="Math",
                    topic_summary="Old Summary",
                    subtopics=[
                        SubtopicIndexEntry(
                            subtopic_key="add",
                            subtopic_title="Add",
                            subtopic_summary="Sub Summary",
                            status="open",
                            page_range="1-1"
                        )
                    ]
                )
            ]
        )
        orchestrator._load_index = MagicMock(return_value=index)
        orchestrator.index_manager.save_index = MagicMock()
        
        # Mock merge duplicate shards
        orchestrator._merge_duplicate_shards = AsyncMock()

        await orchestrator.finalize_book("test_book")

        # Verify topic summary was regenerated
        assert index.topics[0].topic_summary == "Generated Summary"
        orchestrator.index_manager.save_index.assert_called_once()
