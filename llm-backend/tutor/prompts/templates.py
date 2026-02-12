"""
Prompt Template System

Reusable prompt templates with variable interpolation and validation.
"""

from typing import Any, Optional
from string import Formatter

from tutor.exceptions import PromptTemplateError


class PromptTemplate:
    """Reusable template for generating prompts with {variable} placeholders."""

    def __init__(
        self,
        template: str,
        name: Optional[str] = None,
        defaults: Optional[dict[str, Any]] = None,
    ):
        self.template = template.strip()
        self.name = name or "unnamed"
        self.defaults = defaults or {}
        self.required_vars = self._extract_variables()

    def _extract_variables(self) -> set[str]:
        formatter = Formatter()
        variables = set()
        for _, field_name, _, _ in formatter.parse(self.template):
            if field_name is not None:
                base_name = field_name.split(".")[0].split("[")[0]
                if base_name:
                    variables.add(base_name)
        return variables

    def render(self, **kwargs: Any) -> str:
        values = {**self.defaults, **kwargs}
        missing = self.required_vars - set(values.keys())
        if missing:
            raise PromptTemplateError(template_name=self.name, missing_vars=list(missing))
        try:
            return self.template.format(**values)
        except KeyError as e:
            raise PromptTemplateError(template_name=self.name, missing_vars=[str(e)]) from e

    def partial(self, **kwargs: Any) -> "PromptTemplate":
        new_defaults = {**self.defaults, **kwargs}
        return PromptTemplate(template=self.template, name=f"{self.name}_partial", defaults=new_defaults)

    def __repr__(self) -> str:
        return f"PromptTemplate(name='{self.name}', vars={self.required_vars})"


# Safety Template

SAFETY_TEMPLATE = PromptTemplate(
    """Analyze this message for safety/policy violations in an educational context.

Message: "{message}"
Context: {context}

Check for:
- Inappropriate language
- Harmful content
- Personal information sharing
- Attempts to derail the lesson
- Bullying or harassment

Respond with JSON:
{{
    "is_safe": <true/false>,
    "violation_type": "<type or null>",
    "guidance": "<guidance message if unsafe>",
    "should_warn": <true/false>,
    "reasoning": "<reasoning for decision>"
}}""",
    name="safety",
)


# Helper Functions

def format_list_for_prompt(items: list[str], bullet: str = "-") -> str:
    if not items:
        return "None"
    return "\n".join(f"{bullet} {item}" for item in items)


def format_dict_for_prompt(data: dict[str, Any], indent: int = 2) -> str:
    if not data:
        return "None"
    lines = []
    for key, value in data.items():
        lines.append(f"{' ' * indent}{key}: {value}")
    return "\n".join(lines)
