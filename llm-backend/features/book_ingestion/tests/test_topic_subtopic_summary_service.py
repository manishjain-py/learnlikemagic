"""Unit tests for TopicSubtopicSummaryService."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ..services.topic_subtopic_summary_service import TopicSubtopicSummaryService


class TestTopicSubtopicSummaryService:

    @pytest.fixture
    def mock_openai(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_openai):
        def mock_load_prompt(filename):
            if "subtopic" in filename:
                return "{subtopic_title} {guidelines}"
            return "{topic_title}\n{subtopic_summaries}"

        with patch.object(TopicSubtopicSummaryService, '_load_prompt', side_effect=mock_load_prompt):
            return TopicSubtopicSummaryService(mock_openai)

    @pytest.mark.asyncio
    async def test_generate_subtopic_summary_basic(self, service, mock_openai):
        """Test basic subtopic summary generation."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Teaches adding fractions with same denominators by summing numerators"))]
        mock_openai.chat.completions.create.return_value = mock_response

        summary = await service.generate_subtopic_summary(
            "Same Denominator Addition",
            "Guidelines about adding fractions..."
        )

        assert len(summary.split()) <= 35
        assert len(summary.split()) >= 5
        mock_openai.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_topic_summary_multiple_subtopics(self, service, mock_openai):
        """Test topic summary synthesizes multiple subtopics."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Covers fraction addition from basic same-denominator cases through unlike denominators"))]
        mock_openai.chat.completions.create.return_value = mock_response

        summary = await service.generate_topic_summary(
            "Adding Fractions",
            [
                "Teaches adding with same denominators",
                "Covers finding common denominators",
                "Explains mixed number addition"
            ]
        )

        assert len(summary.split()) <= 50
        mock_openai.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, service, mock_openai):
        """Test graceful fallback when LLM fails."""
        mock_openai.chat.completions.create.side_effect = Exception("API Error")

        summary = await service.generate_subtopic_summary(
            "Same Denominator Addition",
            "Guidelines..."
        )

        assert summary == "Same Denominator Addition - teaching guidelines"

    @pytest.mark.asyncio
    async def test_empty_subtopic_summaries(self, service, mock_openai):
        """Test topic summary with empty subtopic list."""
        summary = await service.generate_topic_summary("Empty Topic", [])
        assert summary == "Empty Topic - teaching guidelines"

    @pytest.mark.asyncio
    async def test_truncates_long_guidelines(self, service, mock_openai):
        """Test that very long guidelines are truncated."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Short summary"))]
        mock_openai.chat.completions.create.return_value = mock_response

        long_guidelines = "x" * 5000
        await service.generate_subtopic_summary("Test", long_guidelines)

        # Verify the prompt was truncated
        call_args = mock_openai.chat.completions.create.call_args
        # Check user message (index 1), not system message (index 0)
        content = call_args.kwargs['messages'][1]['content']
        assert len(content) < 5000  # Should be truncated
