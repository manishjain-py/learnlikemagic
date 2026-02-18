"""Unit tests for tutor/exceptions.py

Tests the full exception hierarchy: instantiation, message formatting,
attribute storage, and isinstance inheritance chains.
"""

import pytest

from tutor.exceptions import (
    TutorAgentError,
    # LLM hierarchy
    LLMError,
    LLMServiceError,
    LLMTimeoutError,
    LLMRateLimitError,
    # Agent hierarchy
    AgentError,
    AgentExecutionError,
    AgentTimeoutError,
    AgentOutputError,
    # Session hierarchy
    SessionError,
    SessionNotFoundError,
    SessionExpiredError,
    SessionValidationError,
    # State hierarchy
    StateError,
    StateValidationError,
    StateTransitionError,
    # Prompt hierarchy
    PromptError,
    PromptTemplateError,
    # Configuration
    ConfigurationError,
)


# ===========================================================================
# TutorAgentError (base)
# ===========================================================================

class TestTutorAgentError:
    def test_message_and_details(self):
        err = TutorAgentError("something broke", details={"code": 42})
        assert err.message == "something broke"
        assert err.details == {"code": 42}
        assert str(err) == "something broke"

    def test_details_default_empty_dict(self):
        err = TutorAgentError("oops")
        assert err.details == {}

    def test_is_exception(self):
        assert issubclass(TutorAgentError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(TutorAgentError, match="boom"):
            raise TutorAgentError("boom")


# ===========================================================================
# LLM errors
# ===========================================================================

class TestLLMError:
    def test_inherits_from_tutor_agent_error(self):
        err = LLMError("llm fail")
        assert isinstance(err, TutorAgentError)
        assert isinstance(err, LLMError)

    def test_message(self):
        err = LLMError("llm fail")
        assert err.message == "llm fail"


class TestLLMServiceError:
    def test_attributes(self):
        err = LLMServiceError("API down", model_name="gpt-4", attempts=3)
        assert err.message == "API down"
        assert err.model_name == "gpt-4"
        assert err.attempts == 3

    def test_optional_defaults(self):
        err = LLMServiceError("fail")
        assert err.model_name is None
        assert err.attempts is None

    def test_inheritance_chain(self):
        err = LLMServiceError("x")
        assert isinstance(err, LLMError)
        assert isinstance(err, TutorAgentError)
        assert isinstance(err, Exception)


class TestLLMTimeoutError:
    def test_message_without_model(self):
        err = LLMTimeoutError(timeout_seconds=30)
        assert "30s" in str(err)
        assert err.timeout_seconds == 30
        assert err.model_name is None

    def test_message_with_model(self):
        err = LLMTimeoutError(timeout_seconds=60, model_name="gpt-4")
        assert "60s" in str(err)
        assert "gpt-4" in str(err)
        assert err.model_name == "gpt-4"

    def test_inheritance_chain(self):
        err = LLMTimeoutError(timeout_seconds=10)
        assert isinstance(err, LLMError)
        assert isinstance(err, TutorAgentError)


class TestLLMRateLimitError:
    def test_message_without_retry(self):
        err = LLMRateLimitError()
        assert "rate limit" in str(err).lower()
        assert err.retry_after is None

    def test_message_with_retry(self):
        err = LLMRateLimitError(retry_after=30)
        assert "30s" in str(err)
        assert err.retry_after == 30

    def test_inheritance_chain(self):
        err = LLMRateLimitError()
        assert isinstance(err, LLMError)
        assert isinstance(err, TutorAgentError)


# ===========================================================================
# Agent errors
# ===========================================================================

class TestAgentError:
    def test_formatted_message(self):
        err = AgentError("planner", "failed to plan")
        assert str(err) == "[planner] failed to plan"
        assert err.agent_name == "planner"

    def test_details_passed_through(self):
        err = AgentError("a", "m", details={"key": "val"})
        assert err.details == {"key": "val"}

    def test_inheritance_chain(self):
        err = AgentError("a", "m")
        assert isinstance(err, TutorAgentError)
        assert isinstance(err, Exception)


class TestAgentExecutionError:
    def test_inherits_from_agent_error(self):
        err = AgentExecutionError("eval", "crashed")
        assert isinstance(err, AgentError)
        assert isinstance(err, TutorAgentError)
        assert err.agent_name == "eval"
        assert "[eval] crashed" in str(err)


class TestAgentTimeoutError:
    def test_attributes_and_message(self):
        err = AgentTimeoutError("planner", timeout_seconds=45)
        assert err.agent_name == "planner"
        assert err.timeout_seconds == 45
        assert "45s" in str(err)
        assert "[planner]" in str(err)

    def test_inheritance_chain(self):
        err = AgentTimeoutError("a", 10)
        assert isinstance(err, AgentError)
        assert isinstance(err, TutorAgentError)


class TestAgentOutputError:
    def test_without_schema(self):
        err = AgentOutputError("planner")
        assert err.agent_name == "planner"
        assert err.expected_schema is None
        assert "Invalid" in str(err) or "invalid" in str(err).lower()

    def test_with_schema(self):
        err = AgentOutputError("planner", expected_schema="TutorResponse")
        assert err.expected_schema == "TutorResponse"
        assert "TutorResponse" in str(err)

    def test_inheritance_chain(self):
        err = AgentOutputError("a")
        assert isinstance(err, AgentError)
        assert isinstance(err, TutorAgentError)


# ===========================================================================
# Session errors
# ===========================================================================

class TestSessionError:
    def test_inherits_from_tutor_agent_error(self):
        err = SessionError("session issue")
        assert isinstance(err, TutorAgentError)
        assert err.message == "session issue"


class TestSessionNotFoundError:
    def test_attributes_and_message(self):
        err = SessionNotFoundError("sess_abc123")
        assert err.session_id == "sess_abc123"
        assert "sess_abc123" in str(err)
        assert "not found" in str(err).lower()

    def test_inheritance_chain(self):
        err = SessionNotFoundError("x")
        assert isinstance(err, SessionError)
        assert isinstance(err, TutorAgentError)


class TestSessionExpiredError:
    def test_without_expired_at(self):
        err = SessionExpiredError("sess_1")
        assert err.session_id == "sess_1"
        assert err.expired_at is None
        assert "expired" in str(err).lower()

    def test_with_expired_at(self):
        err = SessionExpiredError("sess_1", expired_at="2025-01-01T00:00:00Z")
        assert err.expired_at == "2025-01-01T00:00:00Z"
        assert "2025-01-01T00:00:00Z" in str(err)

    def test_inheritance_chain(self):
        err = SessionExpiredError("x")
        assert isinstance(err, SessionError)
        assert isinstance(err, TutorAgentError)


class TestSessionValidationError:
    def test_attributes(self):
        errors = ["field1 missing", "field2 invalid"]
        err = SessionValidationError("sess_1", validation_errors=errors)
        assert err.session_id == "sess_1"
        assert err.validation_errors == errors
        assert "validation" in str(err).lower()

    def test_inheritance_chain(self):
        err = SessionValidationError("x", [])
        assert isinstance(err, SessionError)
        assert isinstance(err, TutorAgentError)


# ===========================================================================
# State errors
# ===========================================================================

class TestStateError:
    def test_inherits_from_tutor_agent_error(self):
        err = StateError("state issue")
        assert isinstance(err, TutorAgentError)


class TestStateValidationError:
    def test_attributes_and_message(self):
        err = StateValidationError(field="mastery", reason="must be 0-1")
        assert err.field == "mastery"
        assert err.reason == "must be 0-1"
        assert "mastery" in str(err)
        assert "must be 0-1" in str(err)

    def test_inheritance_chain(self):
        err = StateValidationError("f", "r")
        assert isinstance(err, StateError)
        assert isinstance(err, TutorAgentError)


class TestStateTransitionError:
    def test_attributes_and_message(self):
        err = StateTransitionError(
            from_state="teaching",
            to_state="complete",
            reason="steps remaining",
        )
        assert err.from_state == "teaching"
        assert err.to_state == "complete"
        assert err.reason == "steps remaining"
        assert "teaching" in str(err)
        assert "complete" in str(err)
        assert "steps remaining" in str(err)

    def test_inheritance_chain(self):
        err = StateTransitionError("a", "b", "r")
        assert isinstance(err, StateError)
        assert isinstance(err, TutorAgentError)


# ===========================================================================
# Prompt errors
# ===========================================================================

class TestPromptError:
    def test_inherits_from_tutor_agent_error(self):
        err = PromptError("prompt issue")
        assert isinstance(err, TutorAgentError)


class TestPromptTemplateError:
    def test_attributes_and_message(self):
        err = PromptTemplateError(
            template_name="tutor_response",
            missing_vars=["student_name", "grade"],
        )
        assert err.template_name == "tutor_response"
        assert err.missing_vars == ["student_name", "grade"]
        assert "tutor_response" in str(err)
        assert "student_name" in str(err)
        assert "grade" in str(err)

    def test_inheritance_chain(self):
        err = PromptTemplateError("t", ["v"])
        assert isinstance(err, PromptError)
        assert isinstance(err, TutorAgentError)


# ===========================================================================
# Configuration errors
# ===========================================================================

class TestConfigurationError:
    def test_attributes_and_message(self):
        err = ConfigurationError(config_key="OPENAI_API_KEY", reason="not set")
        assert err.config_key == "OPENAI_API_KEY"
        assert err.reason == "not set"
        assert "OPENAI_API_KEY" in str(err)
        assert "not set" in str(err)

    def test_inheritance_chain(self):
        err = ConfigurationError("k", "r")
        assert isinstance(err, TutorAgentError)
        assert isinstance(err, Exception)


# ===========================================================================
# Cross-cutting: all exceptions are raiseable and catchable
# ===========================================================================

class TestAllExceptionsRaiseable:
    """Verify every exception class can be raised and caught by its base."""

    @pytest.mark.parametrize(
        "exc_factory,catch_type",
        [
            (lambda: TutorAgentError("e"), Exception),
            (lambda: LLMError("e"), TutorAgentError),
            (lambda: LLMServiceError("e"), LLMError),
            (lambda: LLMTimeoutError(10), LLMError),
            (lambda: LLMRateLimitError(), LLMError),
            (lambda: AgentError("a", "m"), TutorAgentError),
            (lambda: AgentExecutionError("a", "m"), AgentError),
            (lambda: AgentTimeoutError("a", 10), AgentError),
            (lambda: AgentOutputError("a"), AgentError),
            (lambda: SessionError("e"), TutorAgentError),
            (lambda: SessionNotFoundError("s"), SessionError),
            (lambda: SessionExpiredError("s"), SessionError),
            (lambda: SessionValidationError("s", []), SessionError),
            (lambda: StateError("e"), TutorAgentError),
            (lambda: StateValidationError("f", "r"), StateError),
            (lambda: StateTransitionError("a", "b", "r"), StateError),
            (lambda: PromptError("e"), TutorAgentError),
            (lambda: PromptTemplateError("t", ["v"]), PromptError),
            (lambda: ConfigurationError("k", "r"), TutorAgentError),
        ],
    )
    def test_catch_by_base(self, exc_factory, catch_type):
        with pytest.raises(catch_type):
            raise exc_factory()
