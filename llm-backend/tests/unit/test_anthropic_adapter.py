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
        # System prompt is rendered as a list of content blocks (extended-thinking
        # cache compatible). Each block has {"type": "text", "text": "..."}.
        system_text = " ".join(b["text"] for b in kwargs["system"])
        assert "JSON" in system_text
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


# ---------------------------------------------------------------------------
# Cacheable system-prompt split (---) and APIStatusError handling
# ---------------------------------------------------------------------------

class TestPromptCachingSplit:
    """The adapter splits prompts on '\\n\\n---\\n\\n' so the system half can
    be cache-tagged for prompt caching."""

    def test_split_creates_two_system_blocks(self, adapter):
        prompt = "system rules here\n\n---\n\nuser question"
        kwargs = adapter._build_kwargs(prompt, reasoning_effort="none", json_mode=True)
        # JSON enforcement block + the cached system block.
        assert len(kwargs["system"]) == 2
        cached = kwargs["system"][1]
        assert cached["text"] == "system rules here"
        assert cached["cache_control"] == {"type": "ephemeral"}
        # User prompt only carries the post-separator text.
        assert kwargs["messages"][0]["content"] == "user question"

    def test_no_separator_uses_full_prompt_as_user(self, adapter):
        kwargs = adapter._build_kwargs("just a flat prompt", reasoning_effort="none", json_mode=True)
        assert kwargs["messages"][0]["content"] == "just a flat prompt"


class TestParseResponseExtras:
    def test_json_decode_error_when_schema_present_returns_none_parsed(self, adapter):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "not valid {json"
        mock_response = MagicMock(content=[mock_block])

        result = adapter._parse_response(
            mock_response, json_mode=True, json_schema={"type": "object"},
        )
        # The schema branch tries to parse output_text and falls back to None.
        assert result["parsed"] is None
        assert result["output_text"] == "not valid {json"


class TestCallSyncErrorHandling:
    def test_api_status_error_re_raises(self, adapter):
        import anthropic
        # Build a minimal APIStatusError-like exception. anthropic exports the
        # class but instantiating it requires a response — easiest is to mock
        # one and patch __mro__ to satisfy the isinstance check.
        err_cls = anthropic.APIStatusError
        err = err_cls.__new__(err_cls)
        err.status_code = 503
        err.message = "service unavailable"

        adapter.client.messages.create.side_effect = err

        with pytest.raises(err_cls):
            adapter.call_sync("hello")


class TestStreamSync:
    """stream_sync yields text or tool-input deltas, skipping thinking blocks."""

    def _make_event(self, type_, **attrs):
        ev = MagicMock()
        ev.type = type_
        for k, v in attrs.items():
            setattr(ev, k, v)
        return ev

    def _make_delta(self, *, text=None, partial_json=None):
        delta = MagicMock(spec=["text"] if text is not None else ["partial_json"])
        if text is not None:
            delta.text = text
        if partial_json is not None:
            delta.partial_json = partial_json
        return delta

    def test_yields_text_deltas(self, adapter):
        # Build a synthetic event sequence: open text block → 2 deltas → close.
        text_block = MagicMock()
        text_block.type = "text"
        events = [
            self._make_event("content_block_start", content_block=text_block),
            self._make_event("content_block_delta", delta=self._make_delta(text="Hel")),
            self._make_event("content_block_delta", delta=self._make_delta(text="lo")),
            self._make_event("content_block_stop"),
        ]

        ctx = MagicMock()
        ctx.__enter__.return_value = iter(events)
        ctx.__exit__.return_value = False
        adapter.client.messages.stream.return_value = ctx

        chunks = list(adapter.stream_sync("hi", json_mode=True))
        assert chunks == ["Hel", "lo"]

    def test_skips_thinking_block_deltas(self, adapter):
        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        text_block = MagicMock()
        text_block.type = "text"
        events = [
            self._make_event("content_block_start", content_block=thinking_block),
            self._make_event("content_block_delta", delta=self._make_delta(text="internal")),
            self._make_event("content_block_stop"),
            self._make_event("content_block_start", content_block=text_block),
            self._make_event("content_block_delta", delta=self._make_delta(text="visible")),
            self._make_event("content_block_stop"),
        ]
        ctx = MagicMock()
        ctx.__enter__.return_value = iter(events)
        ctx.__exit__.return_value = False
        adapter.client.messages.stream.return_value = ctx

        chunks = list(adapter.stream_sync("hi"))
        assert chunks == ["visible"]

    def test_yields_partial_json_for_tool_use(self, adapter):
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        events = [
            self._make_event("content_block_start", content_block=tool_block),
            self._make_event(
                "content_block_delta", delta=self._make_delta(partial_json='{"a":'),
            ),
            self._make_event(
                "content_block_delta", delta=self._make_delta(partial_json="1}"),
            ),
            self._make_event("content_block_stop"),
        ]
        ctx = MagicMock()
        ctx.__enter__.return_value = iter(events)
        ctx.__exit__.return_value = False
        adapter.client.messages.stream.return_value = ctx

        chunks = list(adapter.stream_sync("hi", json_schema={"type": "object"}))
        assert chunks == ['{"a":', "1}"]

    def test_streaming_api_status_error_re_raises(self, adapter):
        import anthropic
        err_cls = anthropic.APIStatusError
        err = err_cls.__new__(err_cls)
        err.status_code = 500
        err.message = "boom"

        adapter.client.messages.stream.side_effect = err

        with pytest.raises(err_cls):
            list(adapter.stream_sync("hi"))
