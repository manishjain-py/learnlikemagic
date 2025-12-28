"""
LLM Service for Tutor Workflow

This service provides a clean interface to OpenAI's API with:
- Support for GPT-5.2, GPT-5.1 (with reasoning) and GPT-4o
- Automatic retry logic with exponential backoff
- Error handling for rate limits and timeouts
- Response parsing and validation
- Type safety

Design Principles:
- Single Responsibility: Only handles LLM API calls
- Dependency Injection: Receives config via constructor
- Testability: Easy to mock for testing

GPT-5.2 Notes:
- Uses Responses API (same as GPT-5.1)
- Default reasoning is "none" (unlike GPT-5.1's "low")
- New "xhigh" reasoning level for maximum reasoning
- Supports structured output with json_schema (stricter than json_object)
- Better token efficiency and cleaner formatting
"""

import json
import time
from typing import Dict, Any, Optional, Literal
from openai import OpenAI, OpenAIError, RateLimitError, APITimeoutError
from google import genai
from google.genai import types
import logging

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for making LLM API calls with retry logic and error handling.

    Features:
    - GPT-5.2 support with reasoning parameter and strict json_schema output
    - GPT-5.1 support with reasoning parameter
    - GPT-4o support for faster execution
    - Gemini support for alternative planning
    - Automatic retries with exponential backoff
    - Structured error handling
    - JSON mode support
    """

    def __init__(
        self,
        api_key: str,
        gemini_api_key: Optional[str] = None,
        max_retries: int = 3,
        initial_retry_delay: float = 1.0,
        timeout: int = 60,
    ):
        """
        Initialize LLM service.

        Args:
            api_key: OpenAI API key
            gemini_api_key: Google Gemini API key
            max_retries: Maximum number of retry attempts
            initial_retry_delay: Initial delay between retries (seconds)
            timeout: Request timeout (seconds)
        """
        self.client = OpenAI(api_key=api_key)
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay
        self.timeout = timeout
        
        if gemini_api_key:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
            self.has_gemini = True
        else:
            self.has_gemini = False

    def call_gpt_5_1(
        self,
        prompt: str,
        reasoning_effort: Literal["low", "medium", "high"] = "low",
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> Dict[str, Any]:
        """
        Call GPT-5.1 with extended reasoning.

        Used for:
        - Initial planning (strategic thinking)
        - Replanning (analyzing what went wrong)
        - Study plan generation

        Args:
            prompt: The prompt to send
            reasoning_effort: How much thinking effort to use
            max_tokens: Maximum tokens in response
            json_mode: Whether to request JSON output (default True)

        Returns:
            Dict containing:
                - output_text: The main output (valid JSON if json_mode=True)
                - reasoning: The reasoning process (if available)

        Raises:
            LLMServiceError: If API call fails after retries
        """
        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": "gpt-5.1",
            "params": {"reasoning_effort": reasoning_effort, "json_mode": json_mode}
        }))

        def _api_call():
            try:
                kwargs = {
                    "model": "gpt-5.1",
                    "input": prompt,
                    "reasoning": {"effort": reasoning_effort},
                    "timeout": self.timeout,
                }

                if json_mode:
                    kwargs["text"] = {"format": {"type": "json_object"}}

                result = self.client.responses.create(**kwargs)

                # Convert reasoning object to string if present
                # OpenAI SDK returns a Reasoning object, not a string
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
            except (OpenAIError, Exception) as e:
                logger.warning(json.dumps({
                    "step": "LLM_CALL",
                    "status": "warning",
                    "model": "gpt-5.1",
                    "error": str(e),
                    "message": "Falling back to GPT-4o"
                }))
                # Fallback to GPT-4o with same json_mode setting
                fallback_response = self.call_gpt_4o(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    json_mode=json_mode
                )
                return {
                    "output_text": fallback_response,
                    "reasoning": "Fallback to GPT-4o due to GPT-5.1 failure",
                }

        return self._execute_with_retry(_api_call, "GPT-5.1")

    def call_gpt_5_2(
        self,
        prompt: str,
        reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """
        Call GPT-5.2 with extended reasoning and optional strict structured output.

        GPT-5.2 is the newest flagship model with improvements over GPT-5.1:
        - Better token efficiency on medium-to-complex tasks
        - Cleaner formatting with less unnecessary verbosity
        - New "xhigh" reasoning effort level
        - Default reasoning is "none" for lower latency (unlike GPT-5.1's "low")
        - Supports strict json_schema for guaranteed schema adherence

        Used for:
        - Initial planning (strategic thinking) with "medium" or "high" reasoning
        - Fast execution with "none" reasoning
        - Strict structured output with json_schema parameter

        Args:
            prompt: The prompt to send
            reasoning_effort: How much thinking effort to use
                - "none": Fastest, no chain-of-thought (default)
                - "low": Light reasoning
                - "medium": Moderate reasoning
                - "high": Heavy reasoning
                - "xhigh": Maximum reasoning (new in 5.2)
            json_mode: Whether to request JSON output (default True)
            json_schema: Optional JSON schema for strict structured output.
                         When provided, uses json_schema format instead of json_object.
                         Schema must be strict-compliant (use make_schema_strict helper).
            schema_name: Name for the schema (for logging/debugging)

        Returns:
            Dict containing:
                - output_text: The main output (valid JSON if json_mode=True)
                - reasoning: The reasoning process (if available)

        Raises:
            LLMServiceError: If API call fails after retries
        """
        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": "gpt-5.2",
            "params": {
                "reasoning_effort": reasoning_effort,
                "json_mode": json_mode,
                "has_schema": json_schema is not None,
                "schema_name": schema_name if json_schema else None,
            }
        }))

        def _api_call():
            try:
                kwargs = {
                    "model": "gpt-5.2",
                    "input": prompt,
                    "timeout": self.timeout,
                }

                # Add reasoning if not "none" (none is default for 5.2)
                if reasoning_effort != "none":
                    kwargs["reasoning"] = {"effort": reasoning_effort}

                # Add structured output format
                if json_schema:
                    # Use strict json_schema format for guaranteed schema adherence
                    kwargs["text"] = {
                        "format": {
                            "type": "json_schema",
                            "name": schema_name,
                            "schema": json_schema,
                            "strict": True,
                        }
                    }
                elif json_mode:
                    # Fall back to simple json_object format
                    kwargs["text"] = {"format": {"type": "json_object"}}

                result = self.client.responses.create(**kwargs)

                # Convert reasoning object to string if present
                # OpenAI SDK returns a Reasoning object, not a string
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
            except (OpenAIError, Exception) as e:
                logger.warning(json.dumps({
                    "step": "LLM_CALL",
                    "status": "warning",
                    "model": "gpt-5.2",
                    "error": str(e),
                    "message": "Falling back to GPT-5.1"
                }))
                # Fallback to GPT-5.1 with equivalent settings
                # Map xhigh to high for GPT-5.1 compatibility
                fallback_effort = "high" if reasoning_effort == "xhigh" else reasoning_effort
                if fallback_effort == "none":
                    fallback_effort = "low"  # GPT-5.1 doesn't support "none"
                return self.call_gpt_5_1(
                    prompt=prompt,
                    reasoning_effort=fallback_effort,
                    json_mode=json_mode,
                )

        return self._execute_with_retry(_api_call, "GPT-5.2")

    @staticmethod
    def make_schema_strict(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform a JSON schema to meet OpenAI's strict mode requirements.

        OpenAI's structured output with strict=true requires:
        1. All objects must have additionalProperties: false
        2. All properties must be in the required array
        3. $defs references must also be transformed
        4. $ref cannot have sibling keywords (like description)

        Use this when passing a Pydantic-generated schema to call_gpt_5_2().

        Example:
            from pydantic import BaseModel

            class MyOutput(BaseModel):
                field1: str
                field2: int

            schema = MyOutput.model_json_schema()
            strict_schema = LLMService.make_schema_strict(schema)

            response = llm_service.call_gpt_5_2(
                prompt="...",
                json_schema=strict_schema,
                schema_name="MyOutput"
            )

        Args:
            schema: Original JSON schema (e.g., from Pydantic's model_json_schema())

        Returns:
            Transformed schema meeting OpenAI's strict requirements
        """
        def transform(obj: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(obj, dict):
                return obj

            # If this object has a $ref, remove sibling keywords
            # OpenAI requires $ref to be alone (no description, title, etc.)
            if "$ref" in obj:
                return {"$ref": obj["$ref"]}

            result = {}
            for key, value in obj.items():
                if key == "$defs":
                    # Transform all definitions
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

            # If this is an object type, add strict requirements
            if result.get("type") == "object" and "properties" in result:
                result["additionalProperties"] = False
                # All properties must be required in strict mode
                result["required"] = list(result["properties"].keys())

            return result

        return transform(schema)

    def call_gpt_4o(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        json_mode: bool = True,
    ) -> str:
        """
        Call GPT-4o for faster execution.

        Used for:
        - Message generation (EXECUTOR)
        - Response evaluation (EVALUATOR)

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            json_mode: Whether to request JSON output

        Returns:
            Response text (JSON string if json_mode=True)

        Raises:
            LLMServiceError: If API call fails after retries
        """
        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": "gpt-4o",
            "params": {"json_mode": json_mode}
        }))

        def _api_call():
            kwargs = {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": self.timeout,
            }

            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        return self._execute_with_retry(_api_call, "GPT-4o")

    def call_gemini(
        self,
        prompt: str,
        model_name: str = "gemini-3-pro-preview",
        temperature: float = 0.7,
        json_mode: bool = True,
    ) -> str:
        """
        Call Google Gemini model.

        Args:
            prompt: The prompt to send
            model_name: Model to use (e.g., gemini-3-pro-preview)
            temperature: Sampling temperature
            json_mode: Whether to request JSON output

        Returns:
            Response text

        Raises:
            LLMServiceError: If API call fails or Gemini not configured
        """
        if not self.has_gemini:
            raise LLMServiceError("Gemini API key not configured")

        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": model_name,
            "params": {"temperature": temperature}
        }))

        def _api_call():
            config = {
                "temperature": temperature,
            }
            
            if json_mode:
                config["response_mime_type"] = "application/json"

            response = self.gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            
            return response.text

        # Use generic retry logic
        return self._execute_with_retry(_api_call, f"Gemini-{model_name}")

    def _execute_with_retry(self, api_call_fn, model_name: str) -> Any:
        """
        Execute API call with exponential backoff retry logic.

        Args:
            api_call_fn: Function that makes the API call
            model_name: Name of model for logging

        Returns:
            Result from API call

        Raises:
            LLMServiceError: If all retries fail
        """
        last_error = None
        delay = self.initial_retry_delay
        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                result = api_call_fn()
                duration_ms = int((time.time() - start_time) * 1000)

                # Log successful completion
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
                delay *= 2  # Exponential backoff

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
                # Don't retry on other API errors
                raise LLMServiceError(f"{model_name} API error: {str(e)}") from e

            except Exception as e:
                last_error = e
                logger.error(f"{model_name} unexpected error: {str(e)}")
                # For Gemini, we might want to retry on some errors, but for now we'll treat them as unexpected
                # unless we specifically import google.api_core.exceptions
                raise LLMServiceError(f"{model_name} unexpected error: {str(e)}") from e

        # All retries failed
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
        """
        Parse JSON response from LLM.

        Args:
            response: JSON string from LLM

        Returns:
            Parsed dictionary

        Raises:
            LLMServiceError: If JSON parsing fails
        """
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {response[:200]}...")
            raise LLMServiceError(f"Invalid JSON response: {str(e)}") from e


class LLMServiceError(Exception):
    """Custom exception for LLM service errors"""

    pass
