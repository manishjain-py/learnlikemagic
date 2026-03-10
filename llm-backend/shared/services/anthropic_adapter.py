"""
Anthropic (Claude) Adapter

Encapsulates all Claude API interaction, mapping the same interface
used by LLMService for OpenAI to the Anthropic Messages API.

Handles:
- Reasoning effort -> thinking budget mapping
- JSON schema -> tool_use structured output
- JSON mode -> prompt-based JSON instruction
- Response parsing into the standard {output_text, reasoning, parsed} dict
"""

import json
import logging
from typing import Dict, Any, Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_CLAUDE_MODEL = "claude-opus-4-6"
CLAUDE_HAIKU_MODEL = "claude-haiku-4-5-20251001"

THINKING_BUDGET_MAP = {
    "none": 0,
    "low": 5_000,
    "medium": 10_000,
    "high": 20_000,
    "xhigh": 40_000,
}


class AnthropicAdapter:
    """Adapter that translates OpenAI-style calls to Anthropic's Messages API."""

    def __init__(self, api_key: str, timeout: int = 60, model: str = DEFAULT_CLAUDE_MODEL):
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self.async_client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)

    def _build_kwargs(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """Build kwargs for anthropic messages.create().

        Supports prompt caching: if the prompt contains a '---' separator
        (system_prompt --- turn_prompt), the system portion is extracted and
        marked with cache_control for Anthropic's prompt caching, saving
        significant latency on repeated calls within a session.
        """
        system_blocks = []
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16384,
        }

        budget = THINKING_BUDGET_MAP.get(reasoning_effort, 0)
        if budget > 0:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}

        if json_schema:
            kwargs["tools"] = [
                {
                    "name": schema_name,
                    "description": f"Return the {schema_name} output.",
                    "input_schema": json_schema,
                }
            ]
            if budget > 0:
                kwargs["tool_choice"] = {"type": "auto"}
            else:
                kwargs["tool_choice"] = {"type": "tool", "name": schema_name}
        elif json_mode:
            system_blocks.append({
                "type": "text",
                "text": "You MUST respond with valid JSON only. No markdown, no explanation outside the JSON.",
            })

        # Split prompt on '---' to extract cacheable system prompt
        separator = "\n\n---\n\n"
        if separator in prompt:
            system_text, user_text = prompt.split(separator, 1)
            # System prompt with cache_control for prompt caching
            system_blocks.append({
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            })
            user_content = user_text
        else:
            user_content = prompt

        if system_blocks:
            kwargs["system"] = system_blocks

        kwargs["messages"] = [{"role": "user", "content": user_content}]
        return kwargs

    def _parse_response(
        self,
        response: Any,
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Parse Anthropic response into standard {output_text, reasoning, parsed} dict."""
        output_text = ""
        reasoning_str = None
        parsed = None

        for block in response.content:
            if block.type == "thinking":
                reasoning_str = block.thinking
            elif block.type == "text":
                output_text = block.text
            elif block.type == "tool_use":
                parsed = block.input
                output_text = json.dumps(parsed)

        if json_schema and not parsed and output_text:
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                parsed = None

        if json_mode and not json_schema and not parsed:
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                parsed = None

        return {
            "output_text": output_text,
            "reasoning": reasoning_str,
            "parsed": parsed if (json_mode or json_schema) else None,
        }

    async def call_async(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """Async call to Claude, returning the standard output dict."""
        kwargs = self._build_kwargs(prompt, reasoning_effort, json_mode, json_schema, schema_name)
        response = await self.async_client.messages.create(**kwargs)
        return self._parse_response(response, json_mode, json_schema)

    def call_sync(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """Sync call to Claude, returning the standard output dict."""
        kwargs = self._build_kwargs(prompt, reasoning_effort, json_mode, json_schema, schema_name)
        try:
            response = self.client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            logger.error(
                f"Anthropic API error ({type(e).__name__}): status={e.status_code} {e.message}"
            )
            raise
        return self._parse_response(response, json_mode, json_schema)

    def stream_sync(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ):
        """Streaming sync call to Claude. Yields text chunks as they arrive.

        For tool_use (json_schema) responses, yields the JSON input delta chunks.
        For text responses, yields text delta chunks.
        """
        import time
        kwargs = self._build_kwargs(prompt, reasoning_effort, json_mode, json_schema, schema_name)

        logger.info(json.dumps({
            "step": "LLM_CALL_STREAM",
            "status": "starting",
            "model": self.model,
        }))
        start_time = time.time()
        total_chars = 0

        try:
            with self.client.messages.stream(**kwargs) as stream:
                for event in stream:
                    # Text delta events
                    if hasattr(event, 'type'):
                        if event.type == 'content_block_delta':
                            delta = getattr(event, 'delta', None)
                            if delta:
                                if hasattr(delta, 'text'):
                                    total_chars += len(delta.text)
                                    yield delta.text
                                elif hasattr(delta, 'partial_json'):
                                    total_chars += len(delta.partial_json)
                                    yield delta.partial_json
        except anthropic.APIStatusError as e:
            logger.error(
                f"Anthropic streaming error ({type(e).__name__}): status={e.status_code} {e.message}"
            )
            raise

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(json.dumps({
            "step": "LLM_CALL_STREAM",
            "status": "complete",
            "model": self.model,
            "output": {"response_length": total_chars},
            "duration_ms": duration_ms,
        }))
