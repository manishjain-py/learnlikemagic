"""
LLM abstraction layer with OpenAI provider.
"""
import os
import json
from typing import Dict, Any, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class LLMProvider:
    """Abstract base class for LLM providers."""

    def generate(self, system_prompt: str, user_prompt: str, response_format: str = "json") -> Dict[str, Any]:
        """Generate a response from the LLM."""
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.client = OpenAI(api_key=self.api_key)

    def generate(self, system_prompt: str, user_prompt: str, response_format: str = "json") -> Dict[str, Any]:
        """
        Generate JSON response using OpenAI API.

        Args:
            system_prompt: System instructions
            user_prompt: User query/context (can be JSON string)
            response_format: Expected format (default "json")

        Returns:
            Parsed JSON response as dictionary
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"} if response_format == "json" else None,
                temperature=0.7,
                max_tokens=500
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            print(f"OpenAI API error: {e}")
            # Fallback to deterministic response
            return self._fallback_response()

    def _fallback_response(self) -> Dict[str, Any]:
        """Fallback response when API fails."""
        return {
            "message": "Let's work on comparing fractions!",
            "hints": ["Think about which numerator is bigger"],
            "expected_answer_form": "short_text"
        }




# Factory function
def get_llm_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """
    Factory function to get the OpenAI LLM provider.

    Args:
        provider_name: Reserved for future use (currently only supports "openai")

    Returns:
        OpenAIProvider instance
    """
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    return OpenAIProvider(model=model)


# Convenience function for node implementations
def generate_response(system_prompt: str, user_prompt: str, provider: Optional[LLMProvider] = None) -> Dict[str, Any]:
    """
    Generate a response using the configured LLM provider.

    Args:
        system_prompt: System instructions
        user_prompt: User context
        provider: Optional provider instance (creates default if None)

    Returns:
        Parsed JSON response
    """
    if provider is None:
        provider = get_llm_provider()

    return provider.generate(system_prompt, user_prompt)
