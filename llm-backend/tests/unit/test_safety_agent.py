"""Unit tests for tutor/agents/safety.py — SafetyAgent."""

import pytest
from unittest.mock import MagicMock

from tutor.agents.safety import SafetyAgent, SafetyOutput
from tutor.agents.base_agent import AgentContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_agent() -> SafetyAgent:
    llm = MagicMock()
    return SafetyAgent(llm_service=llm)


def _make_context(**overrides) -> AgentContext:
    defaults = dict(
        session_id="sess-1",
        turn_id="turn_1",
        student_message="hello teacher",
        current_step=1,
        current_concept="fractions",
        student_grade=3,
        language_level="simple",
        additional_context={"lesson_context": "math tutoring session"},
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


# ---------------------------------------------------------------------------
# Tests — SafetyAgent properties
# ---------------------------------------------------------------------------

class TestSafetyAgentProperties:
    def test_agent_name(self):
        agent = _make_agent()
        assert agent.agent_name == "safety"

    def test_get_output_model(self):
        agent = _make_agent()
        assert agent.get_output_model() is SafetyOutput


# ---------------------------------------------------------------------------
# Tests — SafetyOutput model
# ---------------------------------------------------------------------------

class TestSafetyOutputModel:
    def test_safe_message(self):
        output = SafetyOutput(
            is_safe=True,
            reasoning="Normal student message.",
        )
        assert output.is_safe is True
        assert output.violation_type is None
        assert output.guidance is None
        assert output.should_warn is False

    def test_unsafe_message(self):
        output = SafetyOutput(
            is_safe=False,
            violation_type="inappropriate_language",
            guidance="Please use appropriate language.",
            should_warn=True,
            reasoning="Message contained inappropriate words.",
        )
        assert output.is_safe is False
        assert output.violation_type == "inappropriate_language"
        assert output.should_warn is True

    def test_default_values(self):
        output = SafetyOutput(is_safe=True, reasoning="ok")
        assert output.violation_type is None
        assert output.guidance is None
        assert output.should_warn is False
        assert output.reasoning == "ok"


# ---------------------------------------------------------------------------
# Tests — build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_prompt_contains_student_message(self):
        agent = _make_agent()
        ctx = _make_context(student_message="What is 2 + 2?")

        prompt = agent.build_prompt(ctx)
        assert "What is 2 + 2?" in prompt

    def test_prompt_contains_lesson_context(self):
        agent = _make_agent()
        ctx = _make_context(
            additional_context={"lesson_context": "fractions tutoring"},
        )

        prompt = agent.build_prompt(ctx)
        assert "fractions tutoring" in prompt

    def test_prompt_default_context_when_missing(self):
        agent = _make_agent()
        ctx = _make_context(additional_context={})

        prompt = agent.build_prompt(ctx)
        assert "tutoring session" in prompt

    def test_prompt_mentions_safety_checks(self):
        agent = _make_agent()
        ctx = _make_context()

        prompt = agent.build_prompt(ctx)
        assert "Inappropriate language" in prompt
        assert "Harmful content" in prompt
        assert "Personal information" in prompt
        assert "Bullying" in prompt


# ---------------------------------------------------------------------------
# Tests — _summarize_output
# ---------------------------------------------------------------------------

class TestSummarizeOutput:
    def test_summarize_safe(self):
        agent = _make_agent()
        output = SafetyOutput(is_safe=True, reasoning="fine")

        summary = agent._summarize_output(output)
        assert summary["is_safe"] is True
        assert summary["violation_type"] is None
        assert summary["should_warn"] is False

    def test_summarize_unsafe(self):
        agent = _make_agent()
        output = SafetyOutput(
            is_safe=False,
            violation_type="off_topic",
            should_warn=True,
            reasoning="Student tried to change topic",
        )

        summary = agent._summarize_output(output)
        assert summary["is_safe"] is False
        assert summary["violation_type"] == "off_topic"
        assert summary["should_warn"] is True
