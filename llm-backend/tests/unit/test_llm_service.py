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
# call_gpt_5_2 — happy path
# ---------------------------------------------------------------------------

class TestCallGpt52:
    @patch("shared.services.llm_service.OpenAI")
    def test_happy_path(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_result = _make_responses_result('{"answer": "42"}')
        mock_client.responses.create.return_value = mock_result

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        result = service.call_gpt_5_2(prompt="What is the meaning of life?")

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
        result = service.call_gpt_5_2(
            prompt="test",
            json_schema=schema,
            schema_name="TestSchema",
        )

        call_kwargs = mock_client.responses.create.call_args
        # Should use json_schema format when schema is provided
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
        result = service.call_gpt_5_2(prompt="test", reasoning_effort="high")

        assert result["reasoning"] == "I thought about it"
        call_kwargs = mock_client.responses.create.call_args
        # Should include reasoning parameter when not "none"
        assert "reasoning" in call_kwargs.kwargs or "reasoning" in (call_kwargs[1] if len(call_kwargs) > 1 else {})


# ---------------------------------------------------------------------------
# call_gpt_5_2 — anthropic provider delegation
# ---------------------------------------------------------------------------

class TestCallGpt52AnthropicDelegation:
    @patch("shared.services.llm_service.OpenAI")
    def test_delegates_to_anthropic_when_provider_set(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()

        service = LLMService(api_key="fake-key", provider="anthropic", model_id="claude-opus-4-6")
        # Manually set up the adapter mock
        mock_adapter = Mock()
        mock_adapter.call_sync.return_value = {"output_text": "claude says hi", "reasoning": None}
        service.anthropic_adapter = mock_adapter
        service.provider = "anthropic"

        result = service.call_gpt_5_2(prompt="Hello Claude")

        mock_adapter.call_sync.assert_called_once()
        assert result["output_text"] == "claude says hi"


# ---------------------------------------------------------------------------
# call_gpt_5_1
# ---------------------------------------------------------------------------

class TestCallGpt51:
    @patch("shared.services.llm_service.OpenAI")
    def test_happy_path(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_result = _make_responses_result('{"plan": "step1"}')
        mock_client.responses.create.return_value = mock_result

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        result = service.call_gpt_5_1(prompt="Plan a lesson")

        assert result["output_text"] == '{"plan": "step1"}'
        call_kwargs = mock_client.responses.create.call_args
        assert call_kwargs.kwargs.get("model") == "gpt-5.1" or call_kwargs[1].get("model") == "gpt-5.1"


# ---------------------------------------------------------------------------
# call_gpt_4o
# ---------------------------------------------------------------------------

class TestCallGpt4o:
    @patch("shared.services.llm_service.OpenAI")
    def test_happy_path(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = _make_chat_response('{"result": "ok"}')
        mock_client.chat.completions.create.return_value = mock_response

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        result = service.call_gpt_4o(prompt="Generate a response")

        assert result == '{"result": "ok"}'
        mock_client.chat.completions.create.assert_called_once()

    @patch("shared.services.llm_service.OpenAI")
    def test_passes_json_mode(self, mock_openai_cls):
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = _make_chat_response("plain text")
        mock_client.chat.completions.create.return_value = mock_response

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")
        service.call_gpt_4o(prompt="test", json_mode=False)

        call_kwargs = mock_client.chat.completions.create.call_args
        # json_mode=False should not include response_format
        assert "response_format" not in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# call_gemini
# ---------------------------------------------------------------------------

class TestCallGemini:
    @patch("shared.services.llm_service.genai")
    @patch("shared.services.llm_service.OpenAI")
    def test_happy_path(self, mock_openai_cls, mock_genai):
        mock_openai_cls.return_value = Mock()

        mock_gemini_client = Mock()
        mock_genai.Client.return_value = mock_gemini_client

        mock_response = Mock()
        mock_response.text = '{"plan": "gemini output"}'
        mock_gemini_client.models.generate_content.return_value = mock_response

        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2", gemini_api_key="gemini-key")
        result = service.call_gemini(prompt="Generate a plan")

        assert result == '{"plan": "gemini output"}'
        mock_gemini_client.models.generate_content.assert_called_once()

    @patch("shared.services.llm_service.OpenAI")
    def test_raises_when_not_configured(self, mock_openai_cls):
        mock_openai_cls.return_value = Mock()
        service = LLMService(api_key="fake-key", provider="openai", model_id="gpt-5.2")

        with pytest.raises(LLMServiceError, match="Gemini API key not configured"):
            service.call_gemini(prompt="test")


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
