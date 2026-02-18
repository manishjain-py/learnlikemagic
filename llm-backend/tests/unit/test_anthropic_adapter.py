"""Unit tests for shared/services/anthropic_adapter.py — AnthropicAdapter."""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from shared.services.anthropic_adapter import (
    AnthropicAdapter,
    DEFAULT_CLAUDE_MODEL,
    CLAUDE_HAIKU_MODEL,
    THINKING_BUDGET_MAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter():
    with patch("shared.services.anthropic_adapter.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = MagicMock()
        mock_anthropic.AsyncAnthropic.return_value = MagicMock()
        ad = AnthropicAdapter(api_key="test-key-fake")
    return ad


# ---------------------------------------------------------------------------
# Tests — Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_default_model(self):
        assert DEFAULT_CLAUDE_MODEL == "claude-opus-4-6"

    def test_haiku_model(self):
        assert CLAUDE_HAIKU_MODEL == "claude-haiku-4-5-20251001"

    def test_thinking_budget_map(self):
        assert THINKING_BUDGET_MAP["none"] == 0
        assert THINKING_BUDGET_MAP["low"] == 5_000
        assert THINKING_BUDGET_MAP["medium"] == 10_000
        assert THINKING_BUDGET_MAP["high"] == 20_000
        assert THINKING_BUDGET_MAP["xhigh"] == 40_000


# ---------------------------------------------------------------------------
# Tests — _build_kwargs
# ---------------------------------------------------------------------------

class TestBuildKwargs:
    def test_basic_json_mode(self, adapter):
        kwargs = adapter._build_kwargs("Hello", reasoning_effort="none", json_mode=True)

        assert kwargs["model"] == DEFAULT_CLAUDE_MODEL
        assert kwargs["max_tokens"] == 16384
        assert kwargs["messages"] == [{"role": "user", "content": "Hello"}]
        assert "system" in kwargs
        assert "JSON" in kwargs["system"]
        assert "thinking" not in kwargs

    def test_no_json_mode(self, adapter):
        kwargs = adapter._build_kwargs("Hello", reasoning_effort="none", json_mode=False)
        assert "system" not in kwargs

    def test_with_thinking(self, adapter):
        kwargs = adapter._build_kwargs("Hello", reasoning_effort="high", json_mode=False)

        assert "thinking" in kwargs
        assert kwargs["thinking"]["type"] == "enabled"
        assert kwargs["thinking"]["budget_tokens"] == 20_000

    def test_with_json_schema(self, adapter):
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        kwargs = adapter._build_kwargs(
            "Hello",
            reasoning_effort="none",
            json_mode=True,
            json_schema=schema,
            schema_name="my_output",
        )

        assert "tools" in kwargs
        assert len(kwargs["tools"]) == 1
        assert kwargs["tools"][0]["name"] == "my_output"
        assert kwargs["tools"][0]["input_schema"] == schema
        assert kwargs["tool_choice"]["type"] == "tool"
        assert kwargs["tool_choice"]["name"] == "my_output"
        # When schema is provided, no system message for JSON instruction
        assert "system" not in kwargs

    def test_schema_with_thinking_uses_auto_tool_choice(self, adapter):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        kwargs = adapter._build_kwargs(
            "Hello",
            reasoning_effort="high",
            json_schema=schema,
        )

        assert kwargs["tool_choice"]["type"] == "auto"

    def test_unknown_reasoning_effort(self, adapter):
        kwargs = adapter._build_kwargs("Hello", reasoning_effort="unknown_level")
        # Should not add thinking block for unknown budget (defaults to 0)
        assert "thinking" not in kwargs


# ---------------------------------------------------------------------------
# Tests — _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_parse_text_response(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '{"result": "ok"}'

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        result = adapter._parse_response(mock_response, json_mode=True)

        assert result["output_text"] == '{"result": "ok"}'
        assert result["parsed"] == {"result": "ok"}
        assert result["reasoning"] is None

    def test_parse_tool_use_response(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {"answer": "42"}

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        result = adapter._parse_response(
            mock_response,
            json_mode=True,
            json_schema={"type": "object"},
        )

        assert result["parsed"] == {"answer": "42"}
        assert result["output_text"] == json.dumps({"answer": "42"})

    def test_parse_thinking_response(self, adapter):
        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = "Let me think about this..."

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = '{"answer": "yes"}'

        mock_response = MagicMock()
        mock_response.content = [thinking_block, text_block]

        result = adapter._parse_response(mock_response, json_mode=True)

        assert result["reasoning"] == "Let me think about this..."
        assert result["parsed"] == {"answer": "yes"}

    def test_parse_non_json_response(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "This is just plain text"

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        result = adapter._parse_response(mock_response, json_mode=False)

        assert result["output_text"] == "This is just plain text"
        assert result["parsed"] is None

    def test_parse_invalid_json(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "not valid json {"

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        result = adapter._parse_response(mock_response, json_mode=True)

        assert result["output_text"] == "not valid json {"
        assert result["parsed"] is None

    def test_parse_text_fallback_for_schema(self, adapter):
        """When schema is provided but no tool_use block, fallback to JSON text."""
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '{"answer": "fallback"}'

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        result = adapter._parse_response(
            mock_response,
            json_mode=True,
            json_schema={"type": "object"},
        )

        assert result["parsed"] == {"answer": "fallback"}


# ---------------------------------------------------------------------------
# Tests — call_sync
# ---------------------------------------------------------------------------

class TestCallSync:
    def test_call_sync(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '{"answer": "sync"}'

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        adapter.client.messages.create.return_value = mock_response

        result = adapter.call_sync("Test prompt", json_mode=True)

        assert result["parsed"] == {"answer": "sync"}
        adapter.client.messages.create.assert_called_once()

    def test_call_sync_with_schema(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.input = {"data": "structured"}

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        adapter.client.messages.create.return_value = mock_response

        schema = {"type": "object", "properties": {"data": {"type": "string"}}}
        result = adapter.call_sync("Test prompt", json_schema=schema, schema_name="test")

        assert result["parsed"] == {"data": "structured"}


# ---------------------------------------------------------------------------
# Tests — call_async
# ---------------------------------------------------------------------------

class TestCallAsync:
    @pytest.mark.asyncio
    async def test_call_async(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '{"answer": "async"}'

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        adapter.async_client.messages.create = AsyncMock(return_value=mock_response)

        result = await adapter.call_async("Test prompt", json_mode=True)

        assert result["parsed"] == {"answer": "async"}
