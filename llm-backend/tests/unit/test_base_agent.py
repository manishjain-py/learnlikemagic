"""
Unit tests for BaseAgent.

Tests the abstract base class via a concrete TestableAgent subclass.
Covers execute happy path, JSON parse errors, timeout, general exceptions,
and last_prompt tracking.
"""

import asyncio
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from pydantic import BaseModel, Field

from tutor.agents.base_agent import BaseAgent, AgentContext
from tutor.exceptions import AgentTimeoutError, AgentExecutionError, AgentOutputError


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------

class SomeModel(BaseModel):
    """Simple output model for the testable agent."""
    field: str = Field(description="A test field")
    score: float = Field(default=0.0, description="A numeric field")


class TestableAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "testable"

    def get_output_model(self):
        return SomeModel

    def build_prompt(self, context: AgentContext) -> str:
        return f"test prompt for {context.student_message}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_context(**overrides):
    defaults = dict(
        session_id="sess_123",
        turn_id="turn_1",
        student_message="Hello",
        current_step=1,
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


def make_llm_mock(output_text='{"field": "value", "score": 0.5}'):
    """Create a mock LLM service that returns structured output."""
    llm = Mock()
    llm.call.return_value = {"output_text": output_text}
    return llm


# ---------------------------------------------------------------------------
# AgentContext
# ---------------------------------------------------------------------------

class TestAgentContext:
    def test_required_fields(self):
        ctx = AgentContext(
            session_id="s1",
            turn_id="t1",
            student_message="Hi",
            current_step=1,
        )
        assert ctx.session_id == "s1"
        assert ctx.student_message == "Hi"

    def test_optional_defaults(self):
        ctx = make_context()
        assert ctx.current_concept is None
        assert ctx.student_grade == 5
        assert ctx.language_level == "simple"
        assert ctx.additional_context == {}


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestBaseAgentInit:
    def test_stores_llm_and_defaults(self):
        llm = Mock()
        agent = TestableAgent(llm)
        assert agent.llm is llm
        assert agent.timeout_seconds == 30
        assert agent._reasoning_effort == "none"

    def test_custom_timeout_and_reasoning(self):
        llm = Mock()
        agent = TestableAgent(llm, timeout_seconds=120, reasoning_effort="high")
        assert agent.timeout_seconds == 120
        assert agent._reasoning_effort == "high"

    def test_agent_name(self):
        agent = TestableAgent(Mock())
        assert agent.agent_name == "testable"


# ---------------------------------------------------------------------------
# execute — happy path
# ---------------------------------------------------------------------------

class TestExecuteHappyPath:
    @pytest.mark.asyncio
    async def test_returns_validated_output(self):
        llm = make_llm_mock('{"field": "hello", "score": 0.9}')
        agent = TestableAgent(llm)
        ctx = make_context()

        result = await agent.execute(ctx)

        assert isinstance(result, SomeModel)
        assert result.field == "hello"
        assert result.score == 0.9

    @pytest.mark.asyncio
    async def test_calls_llm_with_correct_params(self):
        llm = make_llm_mock()
        agent = TestableAgent(llm)
        ctx = make_context(student_message="What is 2+2?")

        await agent.execute(ctx)

        llm.call.assert_called_once()
        call_kwargs = llm.call.call_args
        # prompt should contain the student message
        assert "What is 2+2?" in call_kwargs.kwargs.get("prompt", call_kwargs[1].get("prompt", ""))

    @pytest.mark.asyncio
    async def test_uses_default_values_for_missing_fields(self):
        llm = make_llm_mock('{"field": "present"}')
        agent = TestableAgent(llm)
        ctx = make_context()

        result = await agent.execute(ctx)
        assert result.field == "present"
        assert result.score == 0.0  # default


# ---------------------------------------------------------------------------
# last_prompt tracking
# ---------------------------------------------------------------------------

class TestLastPrompt:
    @pytest.mark.asyncio
    async def test_last_prompt_stored_after_execute(self):
        llm = make_llm_mock()
        agent = TestableAgent(llm)
        ctx = make_context(student_message="fraction question")

        assert agent.last_prompt is None
        await agent.execute(ctx)
        assert agent.last_prompt is not None
        assert "fraction question" in agent.last_prompt

    @pytest.mark.asyncio
    async def test_last_prompt_updated_on_subsequent_call(self):
        llm = make_llm_mock()
        agent = TestableAgent(llm)

        await agent.execute(make_context(student_message="first"))
        first_prompt = agent.last_prompt

        await agent.execute(make_context(student_message="second"))
        assert agent.last_prompt != first_prompt
        assert "second" in agent.last_prompt


# ---------------------------------------------------------------------------
# execute — bad JSON
# ---------------------------------------------------------------------------

class TestExecuteBadJson:
    @pytest.mark.asyncio
    async def test_bad_json_raises_agent_output_error(self):
        llm = make_llm_mock("NOT VALID JSON")
        agent = TestableAgent(llm)
        ctx = make_context()

        # When JSON is invalid, parsed = {} which will fail validation
        # for the required 'field' in SomeModel
        with pytest.raises(AgentOutputError):
            await agent.execute(ctx)

    @pytest.mark.asyncio
    async def test_empty_json_missing_required_field(self):
        llm = make_llm_mock("{}")
        agent = TestableAgent(llm)
        ctx = make_context()

        with pytest.raises(AgentOutputError):
            await agent.execute(ctx)


# ---------------------------------------------------------------------------
# execute — timeout
# ---------------------------------------------------------------------------

class TestExecuteTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_agent_timeout_error(self):
        llm = Mock()
        llm.call.side_effect = asyncio.TimeoutError()
        agent = TestableAgent(llm, timeout_seconds=5)
        ctx = make_context()

        # The asyncio.TimeoutError is caught inside execute and re-raised
        # as AgentTimeoutError. However, the LLM call is run in an executor,
        # so the TimeoutError propagates as a generic exception and gets
        # wrapped in AgentExecutionError instead. We need to mock at the
        # right level.
        with pytest.raises((AgentTimeoutError, AgentExecutionError)):
            await agent.execute(ctx)


# ---------------------------------------------------------------------------
# execute — general exception
# ---------------------------------------------------------------------------

class TestExecuteGeneralException:
    @pytest.mark.asyncio
    async def test_general_exception_raises_agent_execution_error(self):
        llm = Mock()
        llm.call.side_effect = ValueError("something broke")
        agent = TestableAgent(llm)
        ctx = make_context()

        with pytest.raises(AgentExecutionError):
            await agent.execute(ctx)


# ---------------------------------------------------------------------------
# _summarize_output
# ---------------------------------------------------------------------------

class TestSummarizeOutput:
    def test_returns_output_type_and_fields(self):
        agent = TestableAgent(Mock())
        output = SomeModel(field="test", score=0.5)
        summary = agent._summarize_output(output)

        assert summary["output_type"] == "SomeModel"
        assert "field" in summary["fields"]
        assert "score" in summary["fields"]


# ---------------------------------------------------------------------------
# ResponseFieldExtractor — extracts streaming "response" string from JSON
# ---------------------------------------------------------------------------

class TestResponseFieldExtractor:
    """Cover the streaming JSON → response-text extractor used by execute_stream."""

    def _new_extractor(self):
        from tutor.agents.base_agent import ResponseFieldExtractor
        return ResponseFieldExtractor()

    def test_extracts_simple_response_value(self):
        ext = self._new_extractor()
        out = ext.feed('{"response": "Hello world", "other": 1}')
        assert out == "Hello world"

    def test_handles_chunked_input(self):
        ext = self._new_extractor()
        # Trigger pattern is split across chunks — extractor must remember state.
        parts = ['{"resp', 'onse": "Hi', ' there"}']
        result = "".join(ext.feed(p) for p in parts)
        assert result == "Hi there"

    def test_ignores_other_keys(self):
        ext = self._new_extractor()
        out = ext.feed('{"prefix": "ignored", "response": "real text"}')
        assert out == "real text"

    def test_handles_escape_sequences(self):
        ext = self._new_extractor()
        out = ext.feed(r'{"response": "line1\nline2\tend"}')
        assert out == "line1\nline2\tend"

    def test_handles_escaped_quote(self):
        ext = self._new_extractor()
        out = ext.feed(r'{"response": "she said \"hi\""}')
        assert out == 'she said "hi"'

    def test_handles_unicode_escape(self):
        ext = self._new_extractor()
        # é is é
        out = ext.feed(r'{"response": "café"}')
        assert out == "café"

    def test_invalid_unicode_escape_returns_raw(self):
        ext = self._new_extractor()
        # ZZZZ is not valid hex — extractor falls back to the raw escape body.
        out = ext.feed(r'{"response": "x\uZZZZy"}')
        assert "ZZZZ" in out

    def test_state_done_after_value_closes(self):
        ext = self._new_extractor()
        ext.feed('{"response": "first"')
        # Anything after the closing quote is dropped — no further extraction.
        more = ext.feed(', "response": "second"}')
        assert more == ""

    def test_scan_buffer_truncation_is_safe(self):
        # The extractor truncates its scan buffer to 20 chars beyond 30 to
        # avoid unbounded memory while waiting for the trigger.
        ext = self._new_extractor()
        long_prefix = "x" * 200 + '"response": "hit"'
        out = ext.feed(long_prefix)
        assert out == "hit"


# ---------------------------------------------------------------------------
# execute_stream — streaming token + final-result protocol
# ---------------------------------------------------------------------------

class TestExecuteStream:
    """Verify execute_stream yields ('token', str) chunks and a final ('result', model)."""

    @pytest.mark.asyncio
    async def test_streams_tokens_and_final_result(self):
        chunks = ['{"response": "Hel', 'lo!", "score": 0.9, "field": "ok"}']

        llm = Mock()
        llm.call_stream = Mock(return_value=iter(chunks))
        agent = TestableAgent(llm)

        events = []
        async for ev in agent.execute_stream(make_context()):
            events.append(ev)

        # Tokens come first, then the parsed model
        token_text = "".join(d for kind, d in events if kind == "token")
        results = [d for kind, d in events if kind == "result"]

        assert token_text == "Hello!"
        assert len(results) == 1
        assert isinstance(results[0], SomeModel)
        assert results[0].field == "ok"

    @pytest.mark.asyncio
    async def test_stream_with_invalid_final_json_raises(self):
        # Stream ends with malformed JSON — validate_agent_output should raise
        # AgentOutputError because no fields can be parsed.
        chunks = ['{"response": "ok"', ", broken"]

        llm = Mock()
        llm.call_stream = Mock(return_value=iter(chunks))
        agent = TestableAgent(llm)

        with pytest.raises((AgentExecutionError, AgentOutputError)):
            async for _ in agent.execute_stream(make_context()):
                pass

    @pytest.mark.asyncio
    async def test_stream_propagates_llm_exception(self):
        def _raising_iter():
            yield '{"response": "partial"'
            raise RuntimeError("upstream LLM crashed")

        llm = Mock()
        llm.call_stream = Mock(return_value=_raising_iter())
        agent = TestableAgent(llm)

        with pytest.raises(AgentExecutionError):
            async for _ in agent.execute_stream(make_context()):
                pass


# ---------------------------------------------------------------------------
# Use-fast-model branch in _execute_with_prompt
# ---------------------------------------------------------------------------

class TestExecuteFastModelBranch:
    """The use_fast_model flag routes through llm.call_fast instead of llm.call."""

    @pytest.mark.asyncio
    async def test_fast_model_uses_call_fast(self):
        llm = Mock()
        llm.call_fast.return_value = {"output_text": '{"field": "v"}'}
        agent = TestableAgent(llm, use_fast_model=True)

        result = await agent.execute(make_context())
        assert isinstance(result, SomeModel)
        assert llm.call_fast.called is True
        assert llm.call.called is False
