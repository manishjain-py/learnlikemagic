"""
JSON Schema Utilities for structured LLM output.

Provides helpers for transforming Pydantic schemas to meet
OpenAI's strict mode requirements.
"""

import json
import re
from typing import Any, Type, TypeVar
from pydantic import BaseModel, ValidationError

from tutor.exceptions import AgentOutputError


T = TypeVar("T", bound=BaseModel)


def get_strict_schema(model: Type[BaseModel]) -> dict[str, Any]:
    """
    Get a strict JSON schema from a Pydantic model.

    Transforms the schema to meet OpenAI's strict mode requirements:
    - All objects have additionalProperties: false
    - All properties are in the required array
    - $ref references have no sibling keywords
    """
    base_schema = model.model_json_schema()
    return make_schema_strict(base_schema)


def make_schema_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Transform a JSON schema to meet OpenAI's strict mode requirements."""
    def transform(obj: dict[str, Any]) -> dict[str, Any]:
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


def validate_agent_output(
    output: dict[str, Any],
    model: Type[T],
    agent_name: str = "unknown",
) -> T:
    """Validate and parse agent output against a Pydantic model."""
    try:
        return model.model_validate(output)
    except ValidationError as e:
        raise AgentOutputError(
            agent_name=agent_name,
            expected_schema=model.__name__,
        ) from e


def parse_json_safely(
    json_str: str,
    agent_name: str = "unknown",
) -> dict[str, Any]:
    """Safely parse JSON string with error handling."""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise AgentOutputError(
            agent_name=agent_name,
            expected_schema="valid JSON",
        ) from e


def extract_json_from_text(text: str) -> str:
    """Extract JSON object from text that may contain other content."""
    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block_match:
        return code_block_match.group(1)

    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json_match.group()

    raise ValueError("No JSON object found in text")
