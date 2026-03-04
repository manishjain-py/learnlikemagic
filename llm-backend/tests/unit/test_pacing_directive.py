"""Tests for MasterTutorAgent._compute_pacing_directive and _compute_explain_first_directive"""

from unittest.mock import MagicMock
from tutor.agents.master_tutor import MasterTutorAgent


def _make_session(turn_count=5, mastery=None, trend="steady", is_complete=False):
    """Create a mock session with specified state."""
    session = MagicMock()
    session.turn_count = turn_count
    session.mastery_estimates = mastery or {"concept1": 0.5}
    session.session_summary.progress_trend = trend
    session.is_complete = is_complete
    session.last_question = None  # Avoid MagicMock comparison errors
    return session


def _make_session_with_step(turn_count=3, step_type="explain", concept="Addition",
                            mastery=None, has_pending_question=False, concepts_covered=None,
                            concepts_explained=None, content_hint=None):
    """Create a mock session with a current step for explain-first tests."""
    session = MagicMock()
    session.turn_count = turn_count
    session.mastery_estimates = mastery or {}
    session.last_question = MagicMock() if has_pending_question else None
    session.concepts_covered_set = concepts_covered or set()
    session.concepts_explained = concepts_explained or set()
    session.current_step_data = MagicMock()
    session.current_step_data.type = step_type
    session.current_step_data.concept = concept
    session.current_step_data.content_hint = content_hint
    return session


def _make_agent():
    agent = MasterTutorAgent(llm_service=MagicMock())
    return agent


class TestPacingDirective:
    def test_first_turn_directive(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        result = agent._compute_pacing_directive(session)
        assert "FIRST TURN" in result
        assert "Explain" in result

    def test_first_turn_not_zero(self):
        """turn_count=0 is pre-increment state, should NOT be first turn."""
        agent = _make_agent()
        session = _make_session(turn_count=0)
        result = agent._compute_pacing_directive(session)
        assert "FIRST TURN" not in result

    def test_accelerate_high_mastery(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.9, "c2": 0.85}, trend="improving")
        result = agent._compute_pacing_directive(session)
        assert "ACCELERATE" in result

    def test_extend_past_plan(self):
        agent = _make_agent()
        session = _make_session(
            mastery={"c1": 0.9, "c2": 0.85}, trend="improving", is_complete=True
        )
        result = agent._compute_pacing_directive(session)
        assert "EXTEND" in result

    def test_simplify_low_mastery(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.2, "c2": 0.3})
        result = agent._compute_pacing_directive(session)
        assert "SIMPLIFY" in result

    def test_simplify_struggling_trend(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.5}, trend="struggling")
        result = agent._compute_pacing_directive(session)
        assert "SIMPLIFY" in result

    def test_steady_default(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.6}, trend="steady")
        result = agent._compute_pacing_directive(session)
        assert "STEADY" in result

    def test_all_zero_mastery_is_steady_not_simplify(self):
        """All-zero mastery (no real data yet) should be STEADY, not SIMPLIFY."""
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.0, "c2": 0.0, "c3": 0.0}, trend="steady")
        result = agent._compute_pacing_directive(session)
        assert "STEADY" in result
        assert "SIMPLIFY" not in result


class TestExplainFirstDirective:
    """Tests for MasterTutorAgent._compute_explain_first_directive."""

    def test_explain_step_new_concept_returns_teaching_phase(self):
        """On an explain step with no mastery data, should inject TEACHING PHASE."""
        agent = _make_agent()
        session = _make_session_with_step(turn_count=2, step_type="explain", concept="Addition")
        result = agent._compute_explain_first_directive(session)
        assert "TEACHING PHASE" in result
        assert "Addition" in result

    def test_check_step_new_concept_returns_teaching_phase(self):
        """On a check step with no mastery, should inject brief explanation guidance."""
        agent = _make_agent()
        session = _make_session_with_step(turn_count=2, step_type="check", concept="Addition")
        result = agent._compute_explain_first_directive(session)
        assert "TEACHING PHASE" in result
        assert "CHECK" in result

    def test_practice_step_returns_empty(self):
        """Practice steps should not get explain-first directive."""
        agent = _make_agent()
        session = _make_session_with_step(turn_count=2, step_type="practice", concept="Addition")
        result = agent._compute_explain_first_directive(session)
        assert result == ""

    def test_concept_with_mastery_returns_empty(self):
        """If concept already has mastery > 0, no explain-first needed."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            mastery={"Addition": 0.5}
        )
        result = agent._compute_explain_first_directive(session)
        assert result == ""

    def test_pending_question_returns_empty(self):
        """If there's a pending question, don't override with explain-first."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            has_pending_question=True
        )
        result = agent._compute_explain_first_directive(session)
        assert result == ""

    def test_first_turn_returns_empty(self):
        """First turn has its own pacing directive, so explain-first should not fire."""
        agent = _make_agent()
        session = _make_session_with_step(turn_count=1, step_type="explain", concept="Addition")
        result = agent._compute_explain_first_directive(session)
        assert result == ""

    def test_concept_already_covered_returns_empty(self):
        """If concept is in concepts_covered_set, don't re-explain."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            concepts_covered={"Addition"}
        )
        result = agent._compute_explain_first_directive(session)
        assert result == ""

    def test_zero_mastery_still_triggers(self):
        """Mastery of 0.0 (initialized but no real signal) should still trigger."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            mastery={"Addition": 0.0}
        )
        result = agent._compute_explain_first_directive(session)
        assert "TEACHING PHASE" in result

    def test_concept_already_explained_returns_empty(self):
        """If concept is in concepts_explained, no explain-first needed."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            concepts_explained={"Addition"}
        )
        result = agent._compute_explain_first_directive(session)
        assert result == ""

    def test_content_hint_included_in_directive(self):
        """Content hint should be included in the explain-first directive."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            content_hint="Combining groups of objects"
        )
        result = agent._compute_explain_first_directive(session)
        assert "TEACHING PHASE" in result
        assert "Combining groups of objects" in result

    def test_no_content_hint_still_works(self):
        """Directive should work fine without a content hint."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            content_hint=None
        )
        result = agent._compute_explain_first_directive(session)
        assert "TEACHING PHASE" in result
        assert "content hint" not in result.lower()

    def test_concept_explained_takes_priority_over_zero_mastery(self):
        """concepts_explained should be checked before mastery — if explained, skip."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="explain", concept="Addition",
            mastery={"Addition": 0.0},
            concepts_explained={"Addition"}
        )
        result = agent._compute_explain_first_directive(session)
        assert result == ""

    def test_concept_name_in_directive(self):
        """The concept name should appear in the directive for context."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=3, step_type="explain", concept="Multiplication"
        )
        result = agent._compute_explain_first_directive(session)
        assert "Multiplication" in result

    def test_check_step_mentions_concept_explained_signal(self):
        """Check step directive should tell tutor to set concept_explained."""
        agent = _make_agent()
        session = _make_session_with_step(
            turn_count=2, step_type="check", concept="Fractions"
        )
        result = agent._compute_explain_first_directive(session)
        assert "concept_explained" in result
        assert "Fractions" in result
