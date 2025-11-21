"""
Prompt Loading and Rendering Utilities

This module provides utilities for loading and rendering prompt templates.
Prompts are stored as separate .txt files for easy iteration without code changes.
"""

from pathlib import Path
from typing import Dict, Any
import re


class PromptLoader:
    """
    Loads and renders prompt templates from .txt files.

    Features:
    - Simple variable substitution using {variable_name}
    - Template caching for performance
    - Clear error messages for missing templates or variables
    """

    def __init__(self, prompts_dir: Path = None):
        """
        Initialize prompt loader.

        Args:
            prompts_dir: Directory containing prompt template files.
                        Defaults to directory of this file.
        """
        if prompts_dir is None:
            prompts_dir = Path(__file__).parent

        self.prompts_dir = Path(prompts_dir)
        self._cache = {}

    def load(self, template_name: str) -> str:
        """
        Load a prompt template from file.

        Args:
            template_name: Name of template file (without .txt extension)

        Returns:
            Template string

        Raises:
            FileNotFoundError: If template file doesn't exist
        """
        # Check cache first
        if template_name in self._cache:
            return self._cache[template_name]

        # Load from file
        template_path = self.prompts_dir / f"{template_name}.txt"

        if not template_path.exists():
            raise FileNotFoundError(
                f"Prompt template not found: {template_path}\n"
                f"Available templates: {self.list_templates()}"
            )

        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        # Cache it
        self._cache[template_name] = template

        return template

    def render(self, template_name: str, variables: Dict[str, Any]) -> str:
        """
        Load and render a prompt template with variables.

        Args:
            template_name: Name of template file
            variables: Dictionary of variables to substitute

        Returns:
            Rendered prompt string

        Raises:
            FileNotFoundError: If template doesn't exist
            KeyError: If required variable is missing
        """
        template = self.load(template_name)

        # Find all variables in template
        required_vars = set(re.findall(r'\{(\w+)\}', template))

        # Check for missing variables
        missing_vars = required_vars - set(variables.keys())
        if missing_vars:
            raise KeyError(
                f"Missing required variables for template '{template_name}': {missing_vars}"
            )

        # Render template
        try:
            rendered = template.format(**variables)
            return rendered
        except KeyError as e:
            raise KeyError(
                f"Error rendering template '{template_name}': Missing variable {e}"
            )

    def list_templates(self) -> list[str]:
        """
        List all available prompt templates.

        Returns:
            List of template names (without .txt extension)
        """
        return [
            f.stem for f in self.prompts_dir.glob("*.txt") if f.is_file()
        ]


# Global instance for easy imports
default_loader = PromptLoader()


# Convenience functions
def load_prompt(template_name: str) -> str:
    """Load a prompt template"""
    return default_loader.load(template_name)


def render_prompt(template_name: str, variables: Dict[str, Any]) -> str:
    """Load and render a prompt template"""
    return default_loader.render(template_name, variables)


def list_prompts() -> list[str]:
    """List available prompt templates"""
    return default_loader.list_templates()
