"""
LLM Service for Tutor Workflow

This service provides a clean interface to OpenAI's API with:
- Support for GPT-5.1 (with reasoning) and GPT-4o
- Automatic retry logic with exponential backoff
- Error handling for rate limits and timeouts
- Response parsing and validation
- Type safety

Design Principles:
- Single Responsibility: Only handles LLM API calls
- Dependency Injection: Receives config via constructor
- Testability: Easy to mock for testing
"""

import json
import time
from typing import Dict, Any, Optional, Literal
from openai import OpenAI, OpenAIError, RateLimitError, APITimeoutError
import logging

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for making LLM API calls with retry logic and error handling.

    Features:
    - GPT-5.1 support with reasoning parameter
    - GPT-4o support for faster execution
    - Automatic retries with exponential backoff
    - Structured error handling
    - JSON mode support
    """

    def __init__(
        self,
        api_key: str,
        max_retries: int = 3,
        initial_retry_delay: float = 1.0,
        timeout: int = 60,
    ):
        """
        Initialize LLM service.

        Args:
            api_key: OpenAI API key
            max_retries: Maximum number of retry attempts
            initial_retry_delay: Initial delay between retries (seconds)
            timeout: Request timeout (seconds)
        """
        self.client = OpenAI(api_key=api_key)
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay
        self.timeout = timeout

    def call_gpt_5_1(
        self,
        prompt: str,
        reasoning_effort: Literal["low", "medium", "high"] = "high",
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Call GPT-5.1 with extended reasoning.

        Used for:
        - Initial planning (strategic thinking)
        - Replanning (analyzing what went wrong)

        Args:
            prompt: The prompt to send
            reasoning_effort: How much thinking effort to use
            max_tokens: Maximum tokens in response

        Returns:
            Dict containing:
                - output_text: The main output
                - reasoning: The reasoning process (if available)

        Raises:
            LLMServiceError: If API call fails after retries
        """
        logger.info(f"Calling GPT-5.1 with reasoning effort: {reasoning_effort}")

        def _api_call():
            try:
                result = self.client.responses.create(
                    model="gpt-5.1",
                    input=prompt,
                    reasoning={"effort": reasoning_effort},
                    timeout=self.timeout,
                )
                return {
                    "output_text": result.output_text,
                    "reasoning": getattr(result, "reasoning", None),
                }
            except (OpenAIError, Exception) as e:
                logger.warning(f"GPT-5.1 call failed: {str(e)}. Falling back to GPT-4o.")
                # Fallback to GPT-4o
                # We need to adapt the prompt or just use it as is. 
                # Since GPT-4o is chat model, we use chat completions.
                # We'll try to mimic the structure.
                fallback_response = self.call_gpt_4o(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    json_mode=True # Planner usually expects JSON
                )
                return {
                    "output_text": fallback_response,
                    "reasoning": "Fallback to GPT-4o due to GPT-5.1 failure",
                }

        return self._execute_with_retry(_api_call, "GPT-5.1")

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
        logger.info(f"Calling GPT-4o (json_mode={json_mode})")

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

        for attempt in range(self.max_retries):
            try:
                result = api_call_fn()
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
                raise LLMServiceError(f"{model_name} unexpected error: {str(e)}") from e

        # All retries failed
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
