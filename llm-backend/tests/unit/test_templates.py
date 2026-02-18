"""Unit tests for tutor/prompts/templates.py — PromptTemplate and helper functions."""
import os
import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-fake")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from tutor.prompts.templates import PromptTemplate, format_list_for_prompt, format_dict_for_prompt
from tutor.exceptions import PromptTemplateError


# ---------------------------------------------------------------------------
# PromptTemplate — construction & variable extraction
# ---------------------------------------------------------------------------

class TestPromptTemplateConstruction:
    """Tests for PromptTemplate instantiation and _extract_variables."""

    def test_basic_creation(self):
        """Template stores template string, name, and defaults."""
        pt = PromptTemplate("Hello {name}", name="greet", defaults={"name": "World"})
        assert pt.template == "Hello {name}"
        assert pt.name == "greet"
        assert pt.defaults == {"name": "World"}

    def test_template_is_stripped(self):
        """Leading/trailing whitespace is stripped from the template string."""
        pt = PromptTemplate("  Hello {name}  ", name="stripped")
        assert pt.template == "Hello {name}"

    def test_default_name_is_unnamed(self):
        """Omitting the name parameter defaults to 'unnamed'."""
        pt = PromptTemplate("Hello")
        assert pt.name == "unnamed"

    def test_default_defaults_is_empty_dict(self):
        """Omitting defaults gives an empty dict."""
        pt = PromptTemplate("Hello")
        assert pt.defaults == {}

    def test_extract_single_variable(self):
        """_extract_variables finds a single placeholder."""
        pt = PromptTemplate("Hi {user}")
        assert pt.required_vars == {"user"}

    def test_extract_multiple_variables(self):
        """_extract_variables finds all distinct placeholders."""
        pt = PromptTemplate("{greeting} {name}, welcome to {place}")
        assert pt.required_vars == {"greeting", "name", "place"}

    def test_extract_no_variables(self):
        """A template with no placeholders yields an empty set."""
        pt = PromptTemplate("No vars here")
        assert pt.required_vars == set()

    def test_extract_duplicate_variables(self):
        """Repeated placeholders still produce a single set entry."""
        pt = PromptTemplate("{x} and {x}")
        assert pt.required_vars == {"x"}

    def test_extract_ignores_escaped_braces(self):
        """Double braces ({{ }}) are literal and should not produce variables."""
        pt = PromptTemplate("JSON: {{\"key\": \"{value}\"}}")
        assert pt.required_vars == {"value"}

    def test_extract_with_dotted_access(self):
        """Dotted field names like {obj.attr} should extract the base name only."""
        pt = PromptTemplate("{student.name} scored {score}")
        assert pt.required_vars == {"student", "score"}

    def test_extract_with_bracket_access(self):
        """Bracket field names like {items[0]} should extract the base name."""
        pt = PromptTemplate("{items[0]} is first")
        assert pt.required_vars == {"items"}


# ---------------------------------------------------------------------------
# PromptTemplate — render
# ---------------------------------------------------------------------------

class TestPromptTemplateRender:
    """Tests for PromptTemplate.render()."""

    def test_render_with_all_vars(self):
        """Providing all variables renders the template correctly."""
        pt = PromptTemplate("{a} + {b} = {c}", name="math")
        result = pt.render(a="1", b="2", c="3")
        assert result == "1 + 2 = 3"

    def test_render_uses_defaults(self):
        """Defaults are used when keyword arguments are not provided."""
        pt = PromptTemplate("Hello {name}", defaults={"name": "World"})
        assert pt.render() == "Hello World"

    def test_render_kwargs_override_defaults(self):
        """Explicit kwargs override defaults."""
        pt = PromptTemplate("Hello {name}", defaults={"name": "World"})
        assert pt.render(name="Alice") == "Hello Alice"

    def test_render_missing_vars_raises_prompt_template_error(self):
        """Missing variables raise PromptTemplateError with template name and vars."""
        pt = PromptTemplate("{x} and {y}", name="pair")
        with pytest.raises(PromptTemplateError) as exc_info:
            pt.render(x="A")
        err = exc_info.value
        assert err.template_name == "pair"
        assert "y" in err.missing_vars

    def test_render_missing_multiple_vars(self):
        """Multiple missing variables are reported."""
        pt = PromptTemplate("{a} {b} {c}", name="triple")
        with pytest.raises(PromptTemplateError) as exc_info:
            pt.render()
        err = exc_info.value
        assert set(err.missing_vars) == {"a", "b", "c"}

    def test_render_extra_kwargs_ignored(self):
        """Extra keyword arguments that aren't in the template are silently ignored."""
        pt = PromptTemplate("Hello {name}")
        result = pt.render(name="Alice", unused="ignored")
        assert result == "Hello Alice"

    def test_render_with_no_variables(self):
        """A template with no placeholders renders as-is."""
        pt = PromptTemplate("Static content")
        assert pt.render() == "Static content"


# ---------------------------------------------------------------------------
# PromptTemplate — partial
# ---------------------------------------------------------------------------

class TestPromptTemplatePartial:
    """Tests for PromptTemplate.partial()."""

    def test_partial_returns_new_template(self):
        """partial() returns a new PromptTemplate instance."""
        original = PromptTemplate("{a} {b}", name="orig")
        partial = original.partial(a="X")
        assert partial is not original

    def test_partial_name_has_suffix(self):
        """The partial template name has a '_partial' suffix."""
        original = PromptTemplate("{a} {b}", name="orig")
        partial = original.partial(a="X")
        assert partial.name == "orig_partial"

    def test_partial_merges_defaults(self):
        """partial() merges new kwargs with existing defaults."""
        original = PromptTemplate("{a} {b}", defaults={"a": "1"})
        partial = original.partial(b="2")
        assert partial.defaults == {"a": "1", "b": "2"}

    def test_partial_overrides_existing_defaults(self):
        """partial() overrides existing defaults for the same key."""
        original = PromptTemplate("{a}", defaults={"a": "old"})
        partial = original.partial(a="new")
        assert partial.defaults == {"a": "new"}

    def test_partial_can_render(self):
        """A partial template can be rendered when all vars are satisfied."""
        pt = PromptTemplate("{greeting} {name}", name="hello")
        partial = pt.partial(greeting="Hi")
        result = partial.render(name="Bob")
        assert result == "Hi Bob"

    def test_partial_preserves_template_text(self):
        """The underlying template text is preserved in the partial."""
        pt = PromptTemplate("{a} {b}")
        partial = pt.partial(a="X")
        assert partial.template == "{a} {b}"


# ---------------------------------------------------------------------------
# PromptTemplate — __repr__
# ---------------------------------------------------------------------------

class TestPromptTemplateRepr:
    """Tests for PromptTemplate.__repr__()."""

    def test_repr_contains_name(self):
        """repr includes the template name."""
        pt = PromptTemplate("{x}", name="test_tmpl")
        r = repr(pt)
        assert "test_tmpl" in r

    def test_repr_contains_vars(self):
        """repr includes the required variables."""
        pt = PromptTemplate("{x} {y}", name="duo")
        r = repr(pt)
        assert "PromptTemplate(" in r
        assert "duo" in r

    def test_repr_format(self):
        """repr follows the PromptTemplate(name='...', vars=...) format."""
        pt = PromptTemplate("{a}", name="single")
        r = repr(pt)
        assert r == f"PromptTemplate(name='single', vars={pt.required_vars})"


# ---------------------------------------------------------------------------
# format_list_for_prompt
# ---------------------------------------------------------------------------

class TestFormatListForPrompt:
    """Tests for format_list_for_prompt helper."""

    def test_empty_list_returns_none(self):
        """An empty list returns the string 'None'."""
        assert format_list_for_prompt([]) == "None"

    def test_single_item(self):
        """A single-item list produces one bullet line."""
        result = format_list_for_prompt(["item1"])
        assert result == "- item1"

    def test_multiple_items(self):
        """Multiple items produce newline-separated bullet lines."""
        result = format_list_for_prompt(["a", "b", "c"])
        assert result == "- a\n- b\n- c"

    def test_custom_bullet(self):
        """A custom bullet character is used in formatting."""
        result = format_list_for_prompt(["x", "y"], bullet="*")
        assert result == "* x\n* y"

    def test_default_bullet_is_dash(self):
        """The default bullet character is a dash."""
        result = format_list_for_prompt(["only"])
        assert result.startswith("- ")


# ---------------------------------------------------------------------------
# format_dict_for_prompt
# ---------------------------------------------------------------------------

class TestFormatDictForPrompt:
    """Tests for format_dict_for_prompt helper."""

    def test_empty_dict_returns_none(self):
        """An empty dict returns the string 'None'."""
        assert format_dict_for_prompt({}) == "None"

    def test_single_key(self):
        """A dict with one key produces a properly indented line."""
        result = format_dict_for_prompt({"key": "val"})
        assert result == "  key: val"

    def test_multiple_keys(self):
        """Multiple keys produce newline-separated lines."""
        result = format_dict_for_prompt({"a": 1, "b": 2})
        lines = result.split("\n")
        assert len(lines) == 2
        assert "  a: 1" in lines
        assert "  b: 2" in lines

    def test_custom_indent(self):
        """A custom indent value changes the leading spaces."""
        result = format_dict_for_prompt({"k": "v"}, indent=4)
        assert result == "    k: v"

    def test_default_indent_is_two(self):
        """The default indent is 2 spaces."""
        result = format_dict_for_prompt({"k": "v"})
        assert result.startswith("  ")

    def test_none_dict_returns_none(self):
        """None passed as data returns 'None' (falsy check)."""
        assert format_dict_for_prompt({}) == "None"
