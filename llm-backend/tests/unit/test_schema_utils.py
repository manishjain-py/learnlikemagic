"""Unit tests for JSON schema utilities."""
import json

import pytest
from pydantic import BaseModel, Field
from typing import Optional

from tutor.exceptions import AgentOutputError
from tutor.utils.schema_utils import (
    get_strict_schema,
    make_schema_strict,
    validate_agent_output,
    parse_json_safely,
    extract_json_from_text,
)


# --- Test Pydantic Models ---


class SimpleModel(BaseModel):
    """Simple model for testing."""

    name: str
    score: float


class NestedChild(BaseModel):
    """Child model for nested schema tests."""

    label: str
    value: int


class NestedParent(BaseModel):
    """Parent model containing a nested child."""

    title: str
    child: NestedChild


class OptionalFieldsModel(BaseModel):
    """Model with optional fields."""

    required_field: str
    optional_field: Optional[str] = None


class ListFieldModel(BaseModel):
    """Model with a list of nested objects."""

    items: list[NestedChild]
    count: int


# --- Tests ---


class TestGetStrictSchema:
    """Tests for get_strict_schema."""

    def test_simple_model_has_additional_properties_false(self):
        """Strict schema should set additionalProperties to false."""
        schema = get_strict_schema(SimpleModel)
        assert schema.get("additionalProperties") is False

    def test_simple_model_has_all_required_fields(self):
        """Strict schema should list all properties as required."""
        schema = get_strict_schema(SimpleModel)
        assert set(schema["required"]) == {"name", "score"}

    def test_simple_model_preserves_types(self):
        """Schema should preserve property types."""
        schema = get_strict_schema(SimpleModel)
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["score"]["type"] == "number"

    def test_nested_model_defs_are_strict(self):
        """Nested model definitions should also be made strict."""
        schema = get_strict_schema(NestedParent)
        # The $defs section should contain NestedChild with strict properties
        if "$defs" in schema:
            for def_name, def_schema in schema["$defs"].items():
                if def_schema.get("type") == "object":
                    assert def_schema.get("additionalProperties") is False
                    assert "required" in def_schema

    def test_nested_model_top_level_is_strict(self):
        """Top-level of nested model should be strict."""
        schema = get_strict_schema(NestedParent)
        assert schema.get("additionalProperties") is False
        assert "title" in schema.get("required", [])
        assert "child" in schema.get("required", [])

    def test_returns_dict(self):
        """get_strict_schema should return a dictionary."""
        schema = get_strict_schema(SimpleModel)
        assert isinstance(schema, dict)


class TestMakeSchemaStrict:
    """Tests for make_schema_strict."""

    def test_adds_additional_properties_false(self):
        """Should add additionalProperties: false to object schemas."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        result = make_schema_strict(schema)
        assert result["additionalProperties"] is False

    def test_adds_required_from_properties(self):
        """Should set required to all property names."""
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"},
            },
        }
        result = make_schema_strict(schema)
        assert set(result["required"]) == {"a", "b"}

    def test_ref_cleanup_strips_siblings(self):
        """$ref objects should only contain the $ref key."""
        schema = {
            "type": "object",
            "properties": {
                "child": {
                    "$ref": "#/$defs/ChildModel",
                    "description": "should be stripped",
                    "title": "also stripped",
                },
            },
        }
        result = make_schema_strict(schema)
        child = result["properties"]["child"]
        assert child == {"$ref": "#/$defs/ChildModel"}

    def test_nested_objects_in_defs_made_strict(self):
        """Objects inside $defs should also be made strict."""
        schema = {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/Child"}},
            "$defs": {
                "Child": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                }
            },
        }
        result = make_schema_strict(schema)
        child_def = result["$defs"]["Child"]
        assert child_def["additionalProperties"] is False
        assert child_def["required"] == ["value"]

    def test_non_object_types_unchanged(self):
        """Non-object types (string, integer) should pass through unchanged."""
        schema = {"type": "string"}
        result = make_schema_strict(schema)
        assert result == {"type": "string"}

    def test_list_items_processed(self):
        """Items inside arrays (lists) should also be processed."""
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            },
        }
        result = make_schema_strict(schema)
        items_schema = result["properties"]["items"]["items"]
        assert items_schema["additionalProperties"] is False
        assert items_schema["required"] == ["name"]

    def test_empty_schema(self):
        """Empty schema should return empty dict."""
        result = make_schema_strict({})
        assert result == {}

    def test_allof_anyof_processed(self):
        """Schemas inside allOf/anyOf arrays should be processed."""
        schema = {
            "type": "object",
            "properties": {
                "field": {
                    "anyOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {"x": {"type": "integer"}},
                        },
                    ]
                }
            },
        }
        result = make_schema_strict(schema)
        any_of = result["properties"]["field"]["anyOf"]
        # The string variant should be unchanged
        assert any_of[0] == {"type": "string"}
        # The object variant should be made strict
        assert any_of[1]["additionalProperties"] is False
        assert any_of[1]["required"] == ["x"]


class TestValidateAgentOutput:
    """Tests for validate_agent_output."""

    def test_valid_output_returns_model_instance(self):
        """Valid data should return a parsed Pydantic model instance."""
        result = validate_agent_output(
            {"name": "test", "score": 0.9},
            SimpleModel,
            agent_name="test_agent",
        )
        assert isinstance(result, SimpleModel)
        assert result.name == "test"
        assert result.score == 0.9

    def test_valid_nested_output(self):
        """Valid nested data should parse correctly."""
        result = validate_agent_output(
            {"title": "parent", "child": {"label": "child1", "value": 42}},
            NestedParent,
            agent_name="test_agent",
        )
        assert result.title == "parent"
        assert result.child.label == "child1"
        assert result.child.value == 42

    def test_missing_required_field_raises_error(self):
        """Missing required field should raise AgentOutputError."""
        with pytest.raises(AgentOutputError) as exc_info:
            validate_agent_output(
                {"name": "test"},  # missing 'score'
                SimpleModel,
                agent_name="scorer",
            )
        assert exc_info.value.agent_name == "scorer"
        assert exc_info.value.expected_schema == "SimpleModel"

    def test_wrong_type_raises_error(self):
        """Wrong field type should raise AgentOutputError."""
        with pytest.raises(AgentOutputError):
            validate_agent_output(
                {"name": "test", "score": "not_a_number"},
                SimpleModel,
                agent_name="test_agent",
            )

    def test_empty_dict_raises_error(self):
        """Empty dict should raise AgentOutputError for models with required fields."""
        with pytest.raises(AgentOutputError):
            validate_agent_output({}, SimpleModel, agent_name="test_agent")

    def test_default_agent_name(self):
        """Default agent_name should be 'unknown'."""
        with pytest.raises(AgentOutputError) as exc_info:
            validate_agent_output({}, SimpleModel)
        assert exc_info.value.agent_name == "unknown"

    def test_optional_fields_accepted(self):
        """Optional fields can be omitted."""
        result = validate_agent_output(
            {"required_field": "hello"},
            OptionalFieldsModel,
            agent_name="test_agent",
        )
        assert result.required_field == "hello"
        assert result.optional_field is None

    def test_extra_fields_accepted_by_default(self):
        """Pydantic models ignore extra fields by default; no error raised."""
        result = validate_agent_output(
            {"name": "test", "score": 0.5, "extra": "ignored"},
            SimpleModel,
            agent_name="test_agent",
        )
        assert result.name == "test"


class TestParseJsonSafely:
    """Tests for parse_json_safely."""

    def test_valid_json_object(self):
        """Valid JSON object should parse correctly."""
        result = parse_json_safely('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    def test_valid_json_nested(self):
        """Nested JSON should parse correctly."""
        result = parse_json_safely('{"a": {"b": [1, 2, 3]}}')
        assert result == {"a": {"b": [1, 2, 3]}}

    def test_invalid_json_raises_error(self):
        """Invalid JSON should raise AgentOutputError."""
        with pytest.raises(AgentOutputError) as exc_info:
            parse_json_safely("{bad json}", agent_name="parser")
        assert exc_info.value.agent_name == "parser"
        assert exc_info.value.expected_schema == "valid JSON"

    def test_empty_string_raises_error(self):
        """Empty string should raise AgentOutputError."""
        with pytest.raises(AgentOutputError):
            parse_json_safely("")

    def test_non_json_text_raises_error(self):
        """Plain text should raise AgentOutputError."""
        with pytest.raises(AgentOutputError):
            parse_json_safely("this is not json")

    def test_default_agent_name(self):
        """Default agent_name should be 'unknown'."""
        with pytest.raises(AgentOutputError) as exc_info:
            parse_json_safely("{invalid}")
        assert exc_info.value.agent_name == "unknown"

    def test_json_with_whitespace(self):
        """JSON with leading/trailing whitespace should parse fine."""
        result = parse_json_safely('  { "key": "value" }  ')
        assert result == {"key": "value"}

    def test_json_array_parses(self):
        """JSON arrays should parse without error (returns list, not dict)."""
        result = parse_json_safely('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_truncated_json_raises_error(self):
        """Truncated JSON should raise AgentOutputError."""
        with pytest.raises(AgentOutputError):
            parse_json_safely('{"key": "val')


class TestExtractJsonFromText:
    """Tests for extract_json_from_text."""

    def test_extract_from_json_code_block(self):
        """Should extract JSON from ```json code block."""
        text = 'Here is the result:\n```json\n{"answer": 42}\n```\nDone.'
        result = extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed == {"answer": 42}

    def test_extract_from_generic_code_block(self):
        """Should extract JSON from ``` code block (no language tag)."""
        text = 'Output:\n```\n{"key": "value"}\n```'
        result = extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed == {"key": "value"}

    def test_extract_raw_json_no_code_block(self):
        """Should extract JSON object from text without code blocks."""
        text = 'The response is {"status": "ok", "count": 5} end.'
        result = extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed == {"status": "ok", "count": 5}

    def test_no_json_raises_value_error(self):
        """Text without any JSON should raise ValueError."""
        with pytest.raises(ValueError, match="No JSON object found"):
            extract_json_from_text("This is just plain text")

    def test_empty_string_raises_value_error(self):
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError, match="No JSON object found"):
            extract_json_from_text("")

    def test_multiline_json_in_code_block(self):
        """Should extract multi-line JSON from code block."""
        text = '```json\n{\n  "name": "test",\n  "items": [1, 2]\n}\n```'
        result = extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed == {"name": "test", "items": [1, 2]}

    def test_prefers_code_block_over_raw_json(self):
        """Code block JSON should be preferred over raw JSON in text."""
        text = 'Not this: {"wrong": true}\n```json\n{"right": true}\n```'
        result = extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed == {"right": True}

    def test_json_with_surrounding_text(self):
        """Should extract JSON even with surrounding prose."""
        text = 'Prefix text {"data": "found"} suffix text'
        result = extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed == {"data": "found"}
