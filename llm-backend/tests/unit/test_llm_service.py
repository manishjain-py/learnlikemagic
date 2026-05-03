"""
Unit tests for LLMService.

Tests all LLM call methods, retry logic, provider delegation, schema
transformation, and JSON parsing. All OpenAI and Gemini clients are mocked.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock, PropertyMock

from shared.services.llm_service import LLMService, LLMServiceError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_responses_result(output_text='{"key": "value"}', reasoning=None):
    """Create a mock result for client.responses.create."""
    result = Mock()
    result.output_text = output_text
    result.reasoning = reasoning
    return result


def _make_chat_response(content='{"result": "ok"}'):
    """Create a mock response for client.chat.completions.create."""
    response = Mock()
    response.choices = [Mock(message=Mock(content=content))]
    return response


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestLLMServiceInit:
    @patch("shared.services.llm_service.OpenAI")
    def test_init_with_only_api_key(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")

        mock_openai_cls.assert_called_once_with(api_key="fake-key")
        assert service.has_gemini is False
        assert service.anthropic_adapter is None

    @patch("shared.services.llm_service.genai")
    @patch("shared.services.llm_service.OpenAI")
    def test_init_with_gemini_key(self, mock_openai_cls, mock_genai):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2", gemini_api_key="gemini-key")

        assert service.has_gemini is True
        mock_genai.Client.assert_called_once_with(api_key="gemini-key")

    @patch("shared.services.llm_service.OpenAI")
    def test_init_without_optional_keys(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")

        assert service.has_gemini is False
        assert service.anthropic_adapter is None
        assert service.max_retries == 3
        assert service.initial_retry_delay == 1.0
        assert service.timeout == 60


# ---------------------------------------------------------------------------
# call() — Responses API (gpt-5.x models)
# ---------------------------------------------------------------------------

class TestCallResponsesApi:
    @patch("shared.services.llm_service.OpenAI")
    def test_happy_path(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_result = _make_responses_result('{"answer": "42"}')
        mock_client.responses.create.return_value = mock_result

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        result = service.call(prompt="What is the meaning of life?")

        assert result["output_text"] == '{"answer": "42"}'
        mock_client.responses.create.assert_called_once()

    @patch("shared.services.llm_service.OpenAI")
    def test_with_json_schema(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_result = _make_responses_result('{"field": "val"}')
        mock_client.responses.create.return_value = mock_result

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        schema = {"type": "object", "properties": {"field": {"type": "string"}}}
        result = service.call(
            prompt="test",
            json_schema=schema,
            schema_name="TestSchema",
        )

        call_kwargs = mock_client.responses.create.call_args
        assert "text" in call_kwargs.kwargs or "text" in (call_kwargs[1] if len(call_kwargs) > 1 else {})
        assert result["output_text"] == '{"field": "val"}'

    @patch("shared.services.llm_service.OpenAI")
    def test_with_reasoning_effort(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_result = _make_responses_result()
        mock_result.reasoning = Mock()
        mock_result.reasoning.summary = "I thought about it"
        mock_client.responses.create.return_value = mock_result

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        result = service.call(prompt="test", reasoning_effort="high")

        assert result["reasoning"] == "I thought about it"


# ---------------------------------------------------------------------------
# call() — Anthropic provider delegation
# ---------------------------------------------------------------------------

class TestCallAnthropicDelegation:
    @patch("shared.services.llm_service.OpenAI")
    def test_delegates_to_anthropic_when_provider_set(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()

        service = LLMService(api_key="fake-key", provider="anthropic", model_id="claude-opus-4-6")
        mock_adapter = Mock()
        mock_adapter.call_sync.return_value = {"output_text": "claude says hi", "reasoning": None}
        service.anthropic_adapter = mock_adapter

        result = service.call(prompt="Hello Claude")

        mock_adapter.call_sync.assert_called_once()
        assert result["output_text"] == "claude says hi"


# ---------------------------------------------------------------------------
# call() — Chat Completions (non-Responses-API models)
# ---------------------------------------------------------------------------

class TestCallChatCompletions:
    @patch("shared.services.llm_service.OpenAI")
    def test_happy_path(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = _make_chat_response('{"result": "ok"}')
        mock_client.chat.completions.create.return_value = mock_response

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-4o")
        result = service.call(prompt="Generate a response")

        assert result["output_text"] == '{"result": "ok"}'
        mock_client.chat.completions.create.assert_called_once()

    @patch("shared.services.llm_service.OpenAI")
    def test_json_mode_false(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = _make_chat_response("plain text")
        mock_client.chat.completions.create.return_value = mock_response

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-4o")
        service.call(prompt="test", json_mode=False)

        call_kwargs = mock_client.chat.completions.create.call_args
        assert "response_format" not in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# call_fast() — uses configurable fast_model_id
# ---------------------------------------------------------------------------

class TestCallFast:
    @patch("shared.services.llm_service.OpenAI")
    def test_uses_configured_fast_model(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = _make_chat_response('{"safe": true}')
        mock_client.chat.completions.create.return_value = mock_response

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2", fast_model_id="gpt-4o-mini")
        result = service.call_fast(prompt="Is this safe? Respond with JSON.")

        assert result["output_text"] == '{"safe": true}'
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("model") == "gpt-4o-mini"

    @patch("shared.services.llm_service.OpenAI")
    def test_default_fast_model(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = _make_chat_response('{"ok": true}')
        mock_client.chat.completions.create.return_value = mock_response

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        assert service.fast_model_id == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# make_schema_strict
# ---------------------------------------------------------------------------

class TestMakeSchemaStrict:
    def test_adds_additional_properties_false(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        strict = LLMService.make_schema_strict(schema)
        assert strict["additionalProperties"] is False

    def test_all_properties_required(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        strict = LLMService.make_schema_strict(schema)
        assert set(strict["required"]) == {"name", "age"}

    def test_ref_stripped_of_siblings(self):
        schema = {
            "$ref": "#/$defs/MyType",
            "description": "Should be removed",
            "title": "Also removed",
        }
        strict = LLMService.make_schema_strict(schema)
        assert strict == {"$ref": "#/$defs/MyType"}

    def test_nested_defs_transformed(self):
        schema = {
            "type": "object",
            "properties": {
                "inner": {"$ref": "#/$defs/Inner"},
            },
            "$defs": {
                "Inner": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                    },
                },
            },
        }
        strict = LLMService.make_schema_strict(schema)
        inner_def = strict["$defs"]["Inner"]
        assert inner_def["additionalProperties"] is False
        assert inner_def["required"] == ["value"]

    def test_non_object_unchanged(self):
        schema = {"type": "string"}
        strict = LLMService.make_schema_strict(schema)
        assert strict == {"type": "string"}
        assert "additionalProperties" not in strict


# ---------------------------------------------------------------------------
# _execute_with_retry
# ---------------------------------------------------------------------------

class TestExecuteWithRetry:
    @patch("shared.services.llm_service.OpenAI")
    def test_succeeds_on_first_try(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")

        fn = Mock(return_value="success")
        result = service._execute_with_retry(fn, "TestModel")
        assert result == "success"
        assert fn.call_count == 1

    @patch("shared.services.llm_service.time")
    @patch("shared.services.llm_service.OpenAI")
    def test_retries_on_rate_limit(self, mock_openai_cls, mock_time):
        mock_openai_cls.return_value = Mock()
        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        from openai import RateLimitError

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2", max_retries=3, initial_retry_delay=0.01)

        fn = Mock(side_effect=[
            RateLimitError("rate limit", response=Mock(status_code=429), body=None),
            "success",
        ])
        result = service._execute_with_retry(fn, "TestModel")
        assert result == "success"
        assert fn.call_count == 2
        mock_time.sleep.assert_called_once()

    @patch("shared.services.llm_service.time")
    @patch("shared.services.llm_service.OpenAI")
    def test_raises_after_max_retries(self, mock_openai_cls, mock_time):
        mock_openai_cls.return_value = Mock()
        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        from openai import RateLimitError

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2", max_retries=2, initial_retry_delay=0.01)

        fn = Mock(side_effect=RateLimitError(
            "rate limit", response=Mock(status_code=429), body=None,
        ))
        with pytest.raises(LLMServiceError, match="failed after 2 attempts"):
            service._execute_with_retry(fn, "TestModel")
        assert fn.call_count == 2

    @patch("shared.services.llm_service.OpenAI")
    def test_non_retryable_openai_error_raises_immediately(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()

        from openai import AuthenticationError

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2", max_retries=3)

        fn = Mock(side_effect=AuthenticationError(
            "bad key", response=Mock(status_code=401), body=None,
        ))
        with pytest.raises(LLMServiceError):
            service._execute_with_retry(fn, "TestModel")
        assert fn.call_count == 1  # No retries


# ---------------------------------------------------------------------------
# parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    @patch("shared.services.llm_service.OpenAI")
    def test_valid_json(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")

        result = service.parse_json_response('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    @patch("shared.services.llm_service.OpenAI")
    def test_invalid_json_raises(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")

        with pytest.raises(LLMServiceError, match="Invalid JSON"):
            service.parse_json_response("not json at all")

    @patch("shared.services.llm_service.OpenAI")
    def test_empty_object(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")

        result = service.parse_json_response("{}")
        assert result == {}


# ---------------------------------------------------------------------------
# call() routing — provider dispatch
# ---------------------------------------------------------------------------

class TestCallRouting:
    @patch("shared.services.llm_service.OpenAI")
    def test_routes_to_anthropic_when_provider_anthropic(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(
            api_key="fake-key", provider="anthropic", model_id="claude-opus-4-6",
            anthropic_api_key="anthropic-key",
        )
        service._call_anthropic = Mock(return_value={"output_text": "ok"})

        out = service.call("hi", reasoning_effort="high", json_mode=True)
        service._call_anthropic.assert_called_once()
        assert out == {"output_text": "ok"}

    @patch("shared.services.llm_service.OpenAI")
    def test_routes_to_claude_code_when_provider_claude_code(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        with patch("shared.services.llm_service.ClaudeCodeAdapter", create=True):
            service = LLMService(
                api_key="fake-key", provider="claude_code", model_id="claude-opus-4-6",
            )
        service._call_claude_code = Mock(return_value={"output_text": "claude"})

        out = service.call("hi")
        service._call_claude_code.assert_called_once()
        assert out == {"output_text": "claude"}

    @patch("shared.services.llm_service.genai")
    @patch("shared.services.llm_service.OpenAI")
    def test_routes_to_gemini_when_provider_google(self, mock_openai_cls, mock_genai):
        mock_openai_cls.return_value = Mock()
        service = LLMService(
            api_key="fake-key", provider="google",
            model_id="gemini-3-pro-preview", gemini_api_key="g-key",
        )
        service._call_gemini = Mock(return_value="gemini text")

        out = service.call("hi", json_mode=True)
        service._call_gemini.assert_called_once()
        assert out == {"output_text": "gemini text", "reasoning": None}

    @patch("shared.services.llm_service.OpenAI")
    def test_uses_construction_time_effort_when_caller_passes_none(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(
            api_key="fake-key", provider="openai", model_id="gpt-5.2",
            reasoning_effort="medium",
        )
        service._call_responses_api = Mock(return_value={"output_text": ""})

        service.call("hi", reasoning_effort="none")
        # Caller passed "none" → service should fall back to its own "medium".
        kwargs = service._call_responses_api.call_args
        assert kwargs[0][2] == "medium"


# ---------------------------------------------------------------------------
# _call_anthropic and _call_claude_code error paths
# ---------------------------------------------------------------------------

class TestProviderErrorPaths:
    @patch("shared.services.llm_service.OpenAI")
    def test_call_anthropic_raises_when_adapter_missing(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        service.anthropic_adapter = None
        with pytest.raises(LLMServiceError, match="Anthropic adapter not configured"):
            service._call_anthropic("hi")

    @patch("shared.services.llm_service.OpenAI")
    def test_call_claude_code_raises_when_adapter_missing(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        service.claude_code_adapter = None
        with pytest.raises(LLMServiceError, match="Claude Code adapter not configured"):
            service._call_claude_code("hi")

    @patch("shared.services.llm_service.OpenAI")
    def test_call_gemini_raises_when_not_configured(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        service.has_gemini = False
        with pytest.raises(LLMServiceError, match="Gemini API key not configured"):
            service._call_gemini("hi")

    @patch("shared.services.llm_service.OpenAI")
    def test_call_anthropic_delegates_with_kwargs(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(
            api_key="fake-key", provider="anthropic", model_id="claude-opus-4-6",
            anthropic_api_key="a-key",
        )
        adapter = Mock()
        adapter.call_sync.return_value = {"output_text": "x"}
        service.anthropic_adapter = adapter

        out = service._call_anthropic(
            "hi", reasoning_effort="high", json_mode=False,
            json_schema={"type": "object"}, schema_name="MyOut",
        )
        adapter.call_sync.assert_called_once_with(
            prompt="hi", reasoning_effort="high",
            json_mode=False, json_schema={"type": "object"},
            schema_name="MyOut",
        )
        assert out == {"output_text": "x"}


# ---------------------------------------------------------------------------
# call_stream — provider dispatch + chunk plumbing
# ---------------------------------------------------------------------------

class TestCallStream:
    @patch("shared.services.llm_service.OpenAI")
    def test_anthropic_stream_yields_via_adapter(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(
            api_key="fake-key", provider="anthropic", model_id="claude-opus-4-6",
            anthropic_api_key="a-key",
        )
        adapter = Mock()
        adapter.stream_sync.return_value = iter(["A", "B", "C"])
        service.anthropic_adapter = adapter

        chunks = list(service.call_stream("hi", json_mode=True))
        assert chunks == ["A", "B", "C"]

    @patch("shared.services.llm_service.OpenAI")
    def test_claude_code_stream_falls_back_to_call(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        with patch("shared.services.llm_service.ClaudeCodeAdapter", create=True):
            service = LLMService(
                api_key="fake-key", provider="claude_code",
                model_id="claude-opus-4-6",
            )
        service.call = Mock(return_value={"output_text": "full text"})

        chunks = list(service.call_stream("hi"))
        assert chunks == ["full text"]


# ---------------------------------------------------------------------------
# call_fast — fast model path
# ---------------------------------------------------------------------------

class TestCallFastEdgeCases:
    @patch("shared.services.llm_service.OpenAI")
    def test_call_fast_passes_json_mode_through(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        service._call_chat_completions = Mock(return_value="fast")

        out = service.call_fast("hi", json_mode=False)
        # Verify json_mode flag flows through
        kwargs = service._call_chat_completions.call_args
        assert kwargs.kwargs.get("json_mode") is False
        assert out == {"output_text": "fast", "reasoning": None}
