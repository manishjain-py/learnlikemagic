"""Unit tests for formatting utilities."""
import pytest
from utils.formatting import (
    format_conversation_history,
    extract_last_turn,
    build_turn_response
)
from models.domain import HistoryEntry


class TestFormatConversationHistory:
    """Tests for format_conversation_history function."""

    def test_format_empty_history(self):
        """Test formatting empty history returns placeholder."""
        result = format_conversation_history([])
        assert result == "(First turn - no history yet)"

    def test_format_single_entry(self):
        """Test formatting history with one entry."""
        history = [{"role": "teacher", "msg": "What is 1+1?"}]
        result = format_conversation_history(history)
        assert "Teacher: What is 1+1?" in result

    def test_format_multiple_entries(self):
        """Test formatting history with multiple entries."""
        history = [
            {"role": "teacher", "msg": "What is 1+1?"},
            {"role": "student", "msg": "2"},
            {"role": "teacher", "msg": "Correct!"}
        ]
        result = format_conversation_history(history)

        assert "Teacher: What is 1+1?" in result
        assert "Student: 2" in result
        assert "Teacher: Correct!" in result

    def test_format_preserves_order(self):
        """Test that formatting preserves entry order."""
        history = [
            {"role": "teacher", "msg": "First"},
            {"role": "student", "msg": "Second"},
        ]
        result = format_conversation_history(history)

        # "First" should appear before "Second"
        assert result.index("First") < result.index("Second")


class TestExtractLastTurn:
    """Tests for extract_last_turn function."""

    def test_extract_from_empty_history(self):
        """Test extracting from empty history returns default."""
        message, hints = extract_last_turn([])
        assert message == "Hello!"
        assert hints == []

    def test_extract_from_empty_history_custom_default(self):
        """Test extracting with custom default message."""
        message, hints = extract_last_turn([], default_message="Welcome!")
        assert message == "Welcome!"
        assert hints == []

    def test_extract_with_history_entry_object(self):
        """Test extracting from HistoryEntry objects."""
        history = [
            HistoryEntry(role="teacher", msg="Test message", meta={"hints": ["hint1", "hint2"]})
        ]
        message, hints = extract_last_turn(history)

        assert message == "Test message"
        assert hints == ["hint1", "hint2"]

    def test_extract_with_dict(self):
        """Test extracting from dictionary entries."""
        history = [
            {"role": "teacher", "msg": "Test message", "meta": {"hints": ["hint1"]}}
        ]
        message, hints = extract_last_turn(history)

        assert message == "Test message"
        assert hints == ["hint1"]

    def test_extract_without_meta(self):
        """Test extracting when entry has no meta field."""
        history = [
            HistoryEntry(role="teacher", msg="Test message", meta=None)
        ]
        message, hints = extract_last_turn(history)

        assert message == "Test message"
        assert hints == []

    def test_extract_takes_last_entry(self):
        """Test that only the last entry is extracted."""
        history = [
            HistoryEntry(role="teacher", msg="First", meta=None),
            HistoryEntry(role="student", msg="Second", meta=None),
            HistoryEntry(role="teacher", msg="Third", meta={"hints": ["final_hint"]})
        ]
        message, hints = extract_last_turn(history)

        assert message == "Third"
        assert hints == ["final_hint"]


class TestBuildTurnResponse:
    """Tests for build_turn_response function."""

    def test_build_turn_with_basic_data(self):
        """Test building turn response with basic data."""
        history = [
            HistoryEntry(role="teacher", msg="Question?", meta={"hints": ["hint1"]})
        ]

        result = build_turn_response(history, step_idx=2, mastery_score=0.7)

        assert result["message"] == "Question?"
        assert result["hints"] == ["hint1"]
        assert result["step_idx"] == 2
        assert result["mastery_score"] == 0.7
        assert result["is_complete"] is False

    def test_build_turn_marks_complete_at_max_steps(self):
        """Test that is_complete=True when step_idx >= MAX_STEPS."""
        from utils.constants import MAX_STEPS

        history = [HistoryEntry(role="teacher", msg="Done", meta=None)]
        result = build_turn_response(history, step_idx=MAX_STEPS, mastery_score=0.5)

        assert result["is_complete"] is True

    def test_build_turn_marks_complete_at_mastery_threshold(self):
        """Test that is_complete=True when mastery >= threshold."""
        from utils.constants import MASTERY_COMPLETION_THRESHOLD

        history = [HistoryEntry(role="teacher", msg="Great job!", meta=None)]
        result = build_turn_response(history, step_idx=5, mastery_score=MASTERY_COMPLETION_THRESHOLD)

        assert result["is_complete"] is True

    def test_build_turn_not_complete_below_thresholds(self):
        """Test that is_complete=False when below both thresholds."""
        history = [HistoryEntry(role="teacher", msg="Continue", meta=None)]
        result = build_turn_response(history, step_idx=3, mastery_score=0.6)

        assert result["is_complete"] is False
