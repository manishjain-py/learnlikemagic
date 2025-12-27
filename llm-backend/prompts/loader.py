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
