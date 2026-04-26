"""
LLM Service — Centralized interface for all LLM API calls.

Routes calls to the correct provider (OpenAI, Anthropic, Google) based on
provider + model_id set from the DB-backed LLM config.

The primary entry point is `call()`. `call_fast()` uses a separate lightweight
model (also DB-configurable via the 'fast_model' llm_config entry).
"""

import json
import time
from typing import Dict, Any, Optional, Literal, Generator
from openai import OpenAI, OpenAIError, RateLimitError, APITimeoutError
from google import genai
from google.genai import types
import logging

logger = logging.getLogger(__name__)

# Models that use the OpenAI Responses API (vs Chat Completions)
_RESPONSES_API_MODELS = {"gpt-5.4", "gpt-5.4-nano", "gpt-5.3-codex", "gpt-5.2", "gpt-5.1"}
# Note: gpt-realtime-1.5 is excluded — it's a realtime-only model incompatible
# with both Chat Completions and Responses API endpoints.


class LLMService:
    """
    Service for making LLM API calls with retry logic and error handling.

    Both `provider` and `model_id` are REQUIRED — no defaults.
    They come from the llm_config DB table via LLMConfigService.
    """

    def __init__(
        self,
        api_key: str,
        *,
        provider: str,
        model_id: str,
        reasoning_effort: str = "none",
        fast_model_id: str = "gpt-4o-mini",
        gemini_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        max_retries: int = 3,
        initial_retry_delay: float = 1.0,
        timeout: int = 60,
    ):
        self.client = OpenAI(api_key=api_key)
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay
        self.timeout = timeout
        self.provider = provider
        self.model_id = model_id
        # Default reasoning_effort sourced from llm_config (admin-tunable per
        # component). Each call() can still override with an explicit value.
        self.reasoning_effort = reasoning_effort
        if reasoning_effort == "none":
            # Construction with the sentinel default means the caller forgot
            # to pass `reasoning_effort=config["reasoning_effort"]`. The call
            # paths fall back to provider-default behavior (OpenAI uses its
            # built-in default; Claude Code adapter falls back to "max").
            # Surfacing this is cheap and helps catch missed callsite plumbing.
            logger.warning(
                "LLMService constructed with reasoning_effort='none' "
                "(provider=%s model=%s). Per-component admin tuning will not "
                "apply — pass reasoning_effort from llm_config explicitly.",
                provider, model_id,
            )
        self.fast_model_id = fast_model_id

        if gemini_api_key:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
            self.has_gemini = True
        else:
            self.has_gemini = False

        self.anthropic_adapter = None
        if anthropic_api_key:
            from shared.services.anthropic_adapter import AnthropicAdapter
            self.anthropic_adapter = AnthropicAdapter(
                api_key=anthropic_api_key, timeout=timeout, model=model_id
            )

        self.claude_code_adapter = None
        if self.provider == "claude_code":
            from shared.services.claude_code_adapter import ClaudeCodeAdapter
            self.claude_code_adapter = ClaudeCodeAdapter(timeout=1800)

    # ─── Primary entry point ───────────────────────────────────────────

    def call(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
        system_prompt_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generic LLM call — routes to the correct API based on self.provider + self.model_id.

        When the caller passes reasoning_effort="none" (the default), the value
        configured at construction time (from llm_config) is used. Pass an
        explicit value to override the per-component default.

        Args:
            system_prompt_file: Optional path to static instructions file.
                For claude_code provider, loaded via --append-system-prompt-file
                (reduces stdin size). For other providers, prepended to prompt.

        Always returns: {output_text: str, reasoning: str|None, parsed: dict|None}
        """
        effort = reasoning_effort if reasoning_effort and reasoning_effort != "none" \
            else self.reasoning_effort

        if self.provider == "claude_code":
            return self._call_claude_code(
                prompt, effort, json_mode, json_schema, schema_name,
                system_prompt_file=system_prompt_file,
            )
        elif self.provider in ("anthropic", "anthropic-haiku"):
            return self._call_anthropic(
                prompt, effort, json_mode, json_schema, schema_name
            )
        elif self.provider == "google":
            text = self._call_gemini(prompt, model_name=self.model_id, json_mode=json_mode)
            return {"output_text": text, "reasoning": None}
        else:
            # OpenAI — pick Responses API or Chat Completions based on model
            if self.model_id in _RESPONSES_API_MODELS:
                return self._call_responses_api(
                    prompt, self.model_id, effort, json_mode, json_schema, schema_name
                )
            else:
                text = self._call_chat_completions(
                    prompt, self.model_id, json_mode=json_mode
                )
                return {"output_text": text, "reasoning": None}

    # ─── Fast model entry point (lightweight tasks) ─────────────────

    def call_fast(
        self,
        prompt: str,
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """
        Fast LLM call for lightweight tasks (translation, safety checks, etc.).

        Uses self.fast_model_id (from DB 'fast_model' config, defaults to gpt-4o-mini).
        Always uses OpenAI Chat Completions regardless of the main provider setting.
        """
        model = self.fast_model_id
        logger.info(json.dumps({
            "step": "LLM_CALL_FAST",
            "status": "starting",
            "model": model,
        }))
        text = self._call_chat_completions(
            prompt, model, max_tokens=512, temperature=0.3, json_mode=json_mode
        )
        return {"output_text": text, "reasoning": None}

    # ─── Streaming entry point ───────────────────────────────────────

    def call_stream(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Generator[str, None, None]:
        """
        Streaming LLM call — yields text chunks as they arrive.

        Mirrors `.call()`'s effort-fallback behavior: when caller passes
        "none" (the default), the construction-time `self.reasoning_effort`
        is used so the per-component admin setting flows through to live
        streaming responses (e.g. the live tutor).

        Supports OpenAI Responses API and Chat Completions streaming.
        Anthropic/Gemini fall back to non-streaming (yield full response as one chunk).
        """
        effort = reasoning_effort if reasoning_effort and reasoning_effort != "none" \
            else self.reasoning_effort

        if self.provider == "claude_code":
            # Claude Code CLI doesn't support streaming; yield full response
            result = self.call(prompt, effort, json_mode, json_schema, schema_name)
            yield result.get("output_text", "")
            return

        if self.provider in ("anthropic", "anthropic-haiku"):
            if self.anthropic_adapter:
                yield from self.anthropic_adapter.stream_sync(
                    prompt, effort, json_mode, json_schema, schema_name
                )
                return
            # Fallback if adapter not configured
            result = self.call(prompt, effort, json_mode, json_schema, schema_name)
            yield result.get("output_text", "")
            return

        if self.provider == "google":
            text = self._call_gemini(prompt, model_name=self.model_id, json_mode=json_mode)
            yield text
            return

        # OpenAI streaming
        if self.model_id in _RESPONSES_API_MODELS:
            yield from self._stream_responses_api(
                prompt, self.model_id, effort, json_mode, json_schema, schema_name
            )
        else:
            yield from self._stream_chat_completions(
                prompt, self.model_id, json_mode=json_mode
            )

    def _stream_responses_api(
        self,
        prompt: str,
        model: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Generator[str, None, None]:
        """Stream from OpenAI Responses API. Yields text chunks."""
        logger.info(json.dumps({
            "step": "LLM_CALL_STREAM",
            "status": "starting",
            "model": model,
        }))
        start_time = time.time()

        kwargs = {
            "model": model,
            "input": prompt,
            "stream": True,
            "timeout": self.timeout,
        }

        if reasoning_effort != "none":
            kwargs["reasoning"] = {"effort": reasoning_effort}

        if json_schema:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                }
            }
        elif json_mode:
            kwargs["text"] = {"format": {"type": "json_object"}}

        stream = self.client.responses.create(**kwargs)
        total_chars = 0
        for event in stream:
            if getattr(event, "type", None) == "response.output_text.delta":
                total_chars += len(event.delta)
                yield event.delta

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(json.dumps({
            "step": "LLM_CALL_STREAM",
            "status": "complete",
            "model": model,
            "output": {"response_length": total_chars},
            "duration_ms": duration_ms,
        }))

    def _stream_chat_completions(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        json_mode: bool = True,
    ) -> Generator[str, None, None]:
        """Stream from OpenAI Chat Completions API. Yields text chunks."""
        logger.info(json.dumps({
            "step": "LLM_CALL_STREAM",
            "status": "starting",
            "model": model,
        }))
        start_time = time.time()

        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "timeout": self.timeout,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        stream = self.client.chat.completions.create(**kwargs)
        total_chars = 0
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                total_chars += len(content)
                yield content

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(json.dumps({
            "step": "LLM_CALL_STREAM",
            "status": "complete",
            "model": model,
            "output": {"response_length": total_chars},
            "duration_ms": duration_ms,
        }))

    # ─── OpenAI Responses API (gpt-5.2, gpt-5.1) ─────────────────────

    def _call_responses_api(
        self,
        prompt: str,
        model: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """Call OpenAI Responses API (gpt-5.2, gpt-5.1)."""
        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": model,
            "params": {
                "reasoning_effort": reasoning_effort,
                "json_mode": json_mode,
                "has_schema": json_schema is not None,
                "schema_name": schema_name if json_schema else None,
            }
        }))

        def _api_call():
            kwargs = {
                "model": model,
                "input": prompt,
                "timeout": self.timeout,
            }

            if reasoning_effort != "none":
                kwargs["reasoning"] = {"effort": reasoning_effort}

            if json_schema:
                kwargs["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": json_schema,
                        "strict": True,
                    }
                }
            elif json_mode:
                kwargs["text"] = {"format": {"type": "json_object"}}

            result = self.client.responses.create(**kwargs)

            reasoning_obj = getattr(result, "reasoning", None)
            reasoning_str = None
            if reasoning_obj is not None:
                if hasattr(reasoning_obj, "summary") and reasoning_obj.summary:
                    reasoning_str = str(reasoning_obj.summary)
                elif hasattr(reasoning_obj, "text") and reasoning_obj.text:
                    reasoning_str = str(reasoning_obj.text)
                else:
                    reasoning_str = str(reasoning_obj)

            return {
                "output_text": result.output_text,
                "reasoning": reasoning_str,
            }

        return self._execute_with_retry(_api_call, model)

    # ─── OpenAI Chat Completions API (gpt-4o, gpt-4o-mini) ───────────

    def _call_chat_completions(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        json_mode: bool = True,
    ) -> str:
        """Call OpenAI Chat Completions API (gpt-4o, gpt-4o-mini). Returns raw text."""
        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": model,
            "params": {"json_mode": json_mode}
        }))

        def _api_call():
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                "timeout": self.timeout,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        return self._execute_with_retry(_api_call, model)

    # ─── Anthropic ────────────────────────────────────────────────────

    def _call_anthropic(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """Call Anthropic Claude via the adapter."""
        if not self.anthropic_adapter:
            raise LLMServiceError("Anthropic adapter not configured (missing API key)")
        return self.anthropic_adapter.call_sync(
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            json_mode=json_mode,
            json_schema=json_schema,
            schema_name=schema_name,
        )

    # ─── Claude Code CLI ──────────────────────────────────────────────

    def _call_claude_code(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
        system_prompt_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call Claude Code CLI via subprocess."""
        if not self.claude_code_adapter:
            raise LLMServiceError("Claude Code adapter not configured")
        return self.claude_code_adapter.call_sync(
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            json_mode=json_mode,
            json_schema=json_schema,
            schema_name=schema_name,
            system_prompt_file=system_prompt_file,
        )

    # ─── Gemini ───────────────────────────────────────────────────────

    def _call_gemini(
        self,
        prompt: str,
        model_name: str = "gemini-3-pro-preview",
        temperature: float = 0.7,
        json_mode: bool = True,
    ) -> str:
        """Call Google Gemini. Returns raw text."""
        if not self.has_gemini:
            raise LLMServiceError("Gemini API key not configured")

        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": model_name,
            "params": {"temperature": temperature}
        }))

        def _api_call():
            config = {"temperature": temperature}
            if json_mode:
                config["response_mime_type"] = "application/json"
            response = self.gemini_client.models.generate_content(
                model=model_name, contents=prompt, config=config
            )
            return response.text

        return self._execute_with_retry(_api_call, f"Gemini-{model_name}")

    # ─── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def make_schema_strict(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform a JSON schema to meet OpenAI's strict mode requirements.

        OpenAI's structured output with strict=true requires:
        1. All objects must have additionalProperties: false
        2. All properties must be in the required array
        3. $defs references must also be transformed
        4. $ref cannot have sibling keywords (like description)
        """
        def transform(obj: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(obj, dict):
                return obj

            if "$ref" in obj:
                return {"$ref": obj["$ref"]}

            result = {}
            for key, value in obj.items():
                if key == "$defs":
                    result[key] = {k: transform(v) for k, v in value.items()}
                elif isinstance(value, dict):
                    result[key] = transform(value)
                elif isinstance(value, list):
                    result[key] = [
                        transform(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    result[key] = value

            if result.get("type") == "object" and "properties" in result:
                result["additionalProperties"] = False
                result["required"] = list(result["properties"].keys())

            return result

        return transform(schema)

    def _execute_with_retry(self, api_call_fn, model_name: str) -> Any:
        """Execute API call with exponential backoff retry logic."""
        last_error = None
        delay = self.initial_retry_delay
        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                result = api_call_fn()
                duration_ms = int((time.time() - start_time) * 1000)

                logger.info(json.dumps({
                    "step": "LLM_CALL",
                    "status": "complete",
                    "model": model_name,
                    "output": {"response_length": len(str(result)) if result else 0},
                    "duration_ms": duration_ms,
                    "attempts": attempt + 1
                }))

                if attempt > 0:
                    logger.info(f"{model_name} call succeeded on attempt {attempt + 1}")
                return result

            except RateLimitError as e:
                last_error = e
                logger.warning(
                    f"{model_name} rate limit hit (attempt {attempt + 1}/{self.max_retries}). "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2

            except APITimeoutError as e:
                last_error = e
                logger.warning(
                    f"{model_name} timeout (attempt {attempt + 1}/{self.max_retries}). "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2

            except OpenAIError as e:
                last_error = e
                logger.error(f"{model_name} API error: {str(e)}")
                raise LLMServiceError(f"{model_name} API error: {str(e)}") from e

            except Exception as e:
                last_error = e
                logger.error(f"{model_name} unexpected error: {str(e)}")
                raise LLMServiceError(f"{model_name} unexpected error: {str(e)}") from e

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "failed",
            "model": model_name,
            "error": str(last_error),
            "duration_ms": duration_ms,
            "attempts": self.max_retries
        }))
        raise LLMServiceError(
            f"{model_name} failed after {self.max_retries} attempts. Last error: {str(last_error)}"
        ) from last_error

    def parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON response from LLM."""
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {response[:200]}...")
            raise LLMServiceError(f"Invalid JSON response: {str(e)}") from e


class LLMServiceError(Exception):
    """Custom exception for LLM service errors"""
    pass
