"""Prompt template loading and management."""
from pathlib import Path
from typing import Dict, Any, Optional
import json

DEFAULT_PROMPTS_DIR = Path(__file__).parent / "templates"


class PromptLoader:
    """Load and format prompt templates.

    Supports both class methods (for shared templates) and instance methods
    (for custom template directories like agent prompts).
    """

    _cache: Dict[str, str] = {}

    def __init__(self, prompts_dir: Optional[Path] = None):
        """
        Initialize PromptLoader with optional custom directory.

        Args:
            prompts_dir: Custom directory for templates. If None, uses default.
        """
        self._prompts_dir = prompts_dir or DEFAULT_PROMPTS_DIR
        self._instance_cache: Dict[str, str] = {}

    @classmethod
    def load(cls, template_name: str) -> str:
        """
        Load a prompt template by name (class method, uses default dir).

        Args:
            template_name: Name of template file (without .txt extension)

        Returns:
            Template content as string
        """
        if template_name not in cls._cache:
            template_path = DEFAULT_PROMPTS_DIR / f"{template_name}.txt"
            with open(template_path, 'r', encoding='utf-8') as f:
                cls._cache[template_name] = f.read()
        return cls._cache[template_name]

    def load_template(self, template_name: str) -> str:
        """
        Load a prompt template by name (instance method, uses instance dir).

        Args:
            template_name: Name of template file (without .txt extension)

        Returns:
            Template content as string
        """
        cache_key = f"{self._prompts_dir}:{template_name}"
        if cache_key not in self._instance_cache:
            template_path = self._prompts_dir / f"{template_name}.txt"
            with open(template_path, 'r', encoding='utf-8') as f:
                self._instance_cache[cache_key] = f.read()
        return self._instance_cache[cache_key]

    @classmethod
    def format(cls, template_name: str, **kwargs: Any) -> str:
        """
        Load and format a prompt template with variables (class method).

        Args:
            template_name: Name of template file (without .txt extension)
            **kwargs: Variables to interpolate into template

        Returns:
            Formatted prompt string
        """
        template = cls.load(template_name)
        return template.format(**kwargs)

    def render(self, template_name: str, variables: Dict[str, Any]) -> str:
        """
        Load and render a prompt template with variables dict (instance method).

        Args:
            template_name: Name of template file (without .txt extension)
            variables: Dictionary of variables to interpolate into template

        Returns:
            Rendered prompt string
        """
        template = self.load_template(template_name)
        return template.format(**variables)

    @classmethod
    def load_json(cls, template_name: str) -> Dict[str, Any]:
        """
        Load a JSON template file.

        Args:
            template_name: Name of JSON file (without .json extension)

        Returns:
            Parsed JSON as dictionary
        """
        template_path = DEFAULT_PROMPTS_DIR / f"{template_name}.json"
        with open(template_path, 'r', encoding='utf-8') as f:
            return json.load(f)
