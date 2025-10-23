"""Prompt template loading and management."""
from pathlib import Path
from typing import Dict, Any
import json

PROMPTS_DIR = Path(__file__).parent / "templates"


class PromptLoader:
    """Load and format prompt templates."""

    _cache: Dict[str, str] = {}

    @classmethod
    def load(cls, template_name: str) -> str:
        """
        Load a prompt template by name.

        Args:
            template_name: Name of template file (without .txt extension)

        Returns:
            Template content as string
        """
        if template_name not in cls._cache:
            template_path = PROMPTS_DIR / f"{template_name}.txt"
            with open(template_path, 'r', encoding='utf-8') as f:
                cls._cache[template_name] = f.read()
        return cls._cache[template_name]

    @classmethod
    def format(cls, template_name: str, **kwargs: Any) -> str:
        """
        Load and format a prompt template with variables.

        Args:
            template_name: Name of template file (without .txt extension)
            **kwargs: Variables to interpolate into template

        Returns:
            Formatted prompt string
        """
        template = cls.load(template_name)
        return template.format(**kwargs)

    @classmethod
    def load_json(cls, template_name: str) -> Dict[str, Any]:
        """
        Load a JSON template file.

        Args:
            template_name: Name of JSON file (without .json extension)

        Returns:
            Parsed JSON as dictionary
        """
        template_path = PROMPTS_DIR / f"{template_name}.json"
        with open(template_path, 'r', encoding='utf-8') as f:
            return json.load(f)


# Convenience functions for specific prompts
def get_teaching_prompt(**kwargs) -> str:
    """
    Get the teaching/present node prompt.

    Expected kwargs: grade, topic, prefs, step_idx
    """
    return PromptLoader.format("teaching_prompt", **kwargs)


def get_grading_prompt(**kwargs) -> str:
    """
    Get the grading/check node prompt.

    Expected kwargs: grade, topic, reply
    """
    return PromptLoader.format("grading_prompt", **kwargs)


def get_remediation_prompt(**kwargs) -> str:
    """
    Get the remediation/help node prompt.

    Expected kwargs: grade, labels
    """
    return PromptLoader.format("remediation_prompt", **kwargs)


def get_fallback_responses() -> Dict[str, Any]:
    """Get fallback responses for error scenarios."""
    return PromptLoader.load_json("fallback_responses")
