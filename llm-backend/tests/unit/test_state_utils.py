"""Unit tests for tutor state management utilities."""
import pytest

from tutor.utils.state_utils import (
    update_mastery_estimate,
    calculate_overall_mastery,
    should_advance_step,
    get_mastery_level,
    merge_misconceptions,
)


class TestUpdateMasteryEstimate:
    """Tests for update_mastery_estimate (EMA update)."""

    def test_correct_answer_increases_mastery(self):
        """Correct answer should increase mastery toward 1.0."""
        result = update_mastery_estimate(current=0.5, is_correct=True)
        assert result > 0.5

    def test_incorrect_answer_decreases_mastery(self):
        """Incorrect answer should decrease mastery."""
        result = update_mastery_estimate(current=0.5, is_correct=False)
        assert result < 0.5

    def test_correct_answer_specific_value(self):
        """Verify exact EMA calculation for correct answer with defaults."""
        # effective_rate = 0.2 * 1.0 = 0.2
        # delta = (1.0 - 0.5) * 0.2 = 0.1
        # result = 0.5 + 0.1 = 0.6
        result = update_mastery_estimate(current=0.5, is_correct=True)
        assert result == pytest.approx(0.6)

    def test_incorrect_answer_specific_value(self):
        """Verify exact EMA calculation for incorrect answer with defaults."""
        # effective_rate = 0.2 * 1.0 = 0.2
        # delta = -0.5 * 0.2 * 0.5 = -0.05
        # result = 0.5 - 0.05 = 0.45
        result = update_mastery_estimate(current=0.5, is_correct=False)
        assert result == pytest.approx(0.45)

    def test_correct_from_zero(self):
        """Correct answer from zero mastery should increase."""
        # delta = (1.0 - 0.0) * 0.2 = 0.2
        result = update_mastery_estimate(current=0.0, is_correct=True)
        assert result == pytest.approx(0.2)

    def test_incorrect_from_zero_stays_zero(self):
        """Incorrect answer from zero mastery should stay at zero."""
        # delta = -0.0 * 0.2 * 0.5 = 0.0
        result = update_mastery_estimate(current=0.0, is_correct=False)
        assert result == pytest.approx(0.0)

    def test_correct_near_one_has_diminishing_returns(self):
        """Correct answers near 1.0 should have small deltas."""
        # delta = (1.0 - 0.95) * 0.2 = 0.01
        result = update_mastery_estimate(current=0.95, is_correct=True)
        assert result == pytest.approx(0.96)

    def test_result_clamped_to_one(self):
        """Result should never exceed 1.0."""
        result = update_mastery_estimate(current=1.0, is_correct=True)
        assert result <= 1.0

    def test_result_clamped_to_zero(self):
        """Result should never go below 0.0."""
        result = update_mastery_estimate(
            current=0.01, is_correct=False, confidence=1.0, learning_rate=1.0
        )
        assert result >= 0.0

    def test_high_confidence_amplifies_update(self):
        """Higher confidence should produce a larger change."""
        low_conf = update_mastery_estimate(current=0.5, is_correct=True, confidence=0.5)
        high_conf = update_mastery_estimate(current=0.5, is_correct=True, confidence=1.0)
        assert high_conf > low_conf

    def test_zero_confidence_no_change(self):
        """Zero confidence should produce no change."""
        result = update_mastery_estimate(current=0.5, is_correct=True, confidence=0.0)
        assert result == pytest.approx(0.5)

    def test_custom_learning_rate(self):
        """Custom learning rate should scale the update."""
        # effective_rate = 0.5 * 1.0 = 0.5
        # delta = (1.0 - 0.5) * 0.5 = 0.25
        result = update_mastery_estimate(
            current=0.5, is_correct=True, learning_rate=0.5
        )
        assert result == pytest.approx(0.75)

    def test_zero_learning_rate_no_change(self):
        """Zero learning rate should produce no change."""
        result = update_mastery_estimate(
            current=0.5, is_correct=True, learning_rate=0.0
        )
        assert result == pytest.approx(0.5)

    def test_confidence_and_learning_rate_combined(self):
        """Confidence and learning rate should multiply together."""
        # effective_rate = 0.4 * 0.5 = 0.2
        # delta = (1.0 - 0.5) * 0.2 = 0.1
        result = update_mastery_estimate(
            current=0.5, is_correct=True, confidence=0.5, learning_rate=0.4
        )
        assert result == pytest.approx(0.6)


class TestCalculateOverallMastery:
    """Tests for calculate_overall_mastery."""

    def test_empty_dict_returns_zero(self):
        """Empty mastery estimates should return 0.0."""
        result = calculate_overall_mastery({})
        assert result == 0.0

    def test_single_concept(self):
        """Single concept should return its own score."""
        result = calculate_overall_mastery({"fractions": 0.8})
        assert result == pytest.approx(0.8)

    def test_uniform_scores(self):
        """Uniform scores should return that score as average."""
        result = calculate_overall_mastery({"a": 0.5, "b": 0.5, "c": 0.5})
        assert result == pytest.approx(0.5)

    def test_average_of_different_scores(self):
        """Different scores should return their mean."""
        result = calculate_overall_mastery({"a": 0.2, "b": 0.8})
        assert result == pytest.approx(0.5)

    def test_all_zeros(self):
        """All zero scores should return 0.0."""
        result = calculate_overall_mastery({"a": 0.0, "b": 0.0})
        assert result == pytest.approx(0.0)

    def test_all_ones(self):
        """All perfect scores should return 1.0."""
        result = calculate_overall_mastery({"a": 1.0, "b": 1.0})
        assert result == pytest.approx(1.0)

    def test_with_weights(self):
        """Weighted mastery should respect weights."""
        # weighted_sum = 0.8 * 2.0 + 0.4 * 1.0 = 2.0
        # total_weight = 3.0
        # result = 2.0 / 3.0 = 0.6667
        result = calculate_overall_mastery(
            {"a": 0.8, "b": 0.4},
            weights={"a": 2.0, "b": 1.0},
        )
        assert result == pytest.approx(2.0 / 3.0)

    def test_with_partial_weights(self):
        """Concepts missing from weights dict should default to weight 1.0."""
        # a: 0.8 * 3.0 = 2.4, b: 0.6 * 1.0 (default) = 0.6
        # total_weight = 4.0, result = 3.0 / 4.0 = 0.75
        result = calculate_overall_mastery(
            {"a": 0.8, "b": 0.6},
            weights={"a": 3.0},
        )
        assert result == pytest.approx(0.75)

    def test_with_zero_total_weight(self):
        """Zero total weight should return 0.0 to avoid division by zero."""
        result = calculate_overall_mastery(
            {"a": 0.8},
            weights={"a": 0.0},
        )
        assert result == 0.0

    def test_weights_none_uses_simple_average(self):
        """Passing weights=None should use simple average."""
        result = calculate_overall_mastery({"a": 0.3, "b": 0.9}, weights=None)
        assert result == pytest.approx(0.6)


class TestShouldAdvanceStep:
    """Tests for should_advance_step."""

    def test_above_threshold_advances(self):
        """Mastery above threshold should return True."""
        result = should_advance_step({"fractions": 0.8}, "fractions", threshold=0.7)
        assert result is True

    def test_at_threshold_advances(self):
        """Mastery exactly at threshold should return True."""
        result = should_advance_step({"fractions": 0.7}, "fractions", threshold=0.7)
        assert result is True

    def test_below_threshold_does_not_advance(self):
        """Mastery below threshold should return False."""
        result = should_advance_step({"fractions": 0.6}, "fractions", threshold=0.7)
        assert result is False

    def test_missing_concept_returns_false(self):
        """Missing concept should default to 0.0, returning False."""
        result = should_advance_step({"fractions": 0.9}, "algebra", threshold=0.7)
        assert result is False

    def test_empty_estimates_returns_false(self):
        """Empty estimates dict should return False."""
        result = should_advance_step({}, "fractions", threshold=0.7)
        assert result is False

    def test_default_threshold(self):
        """Default threshold should be 0.7."""
        assert should_advance_step({"a": 0.7}, "a") is True
        assert should_advance_step({"a": 0.69}, "a") is False

    def test_custom_threshold(self):
        """Custom threshold should override default."""
        result = should_advance_step({"a": 0.5}, "a", threshold=0.4)
        assert result is True

    def test_zero_threshold(self):
        """Zero threshold should always advance (even zero mastery)."""
        result = should_advance_step({"a": 0.0}, "a", threshold=0.0)
        assert result is True


class TestGetMasteryLevel:
    """Tests for get_mastery_level categorical mapping."""

    def test_mastered_at_0_9(self):
        assert get_mastery_level(0.9) == "mastered"

    def test_mastered_at_1_0(self):
        assert get_mastery_level(1.0) == "mastered"

    def test_mastered_above_0_9(self):
        assert get_mastery_level(0.95) == "mastered"

    def test_strong_at_0_7(self):
        assert get_mastery_level(0.7) == "strong"

    def test_strong_at_0_89(self):
        assert get_mastery_level(0.89) == "strong"

    def test_adequate_at_0_5(self):
        assert get_mastery_level(0.5) == "adequate"

    def test_adequate_at_0_69(self):
        assert get_mastery_level(0.69) == "adequate"

    def test_developing_at_0_3(self):
        assert get_mastery_level(0.3) == "developing"

    def test_developing_at_0_49(self):
        assert get_mastery_level(0.49) == "developing"

    def test_needs_work_at_0_29(self):
        assert get_mastery_level(0.29) == "needs_work"

    def test_needs_work_at_zero(self):
        assert get_mastery_level(0.0) == "needs_work"

    def test_boundary_just_below_0_9(self):
        """Score just below 0.9 should be 'strong', not 'mastered'."""
        assert get_mastery_level(0.8999) == "strong"

    def test_boundary_just_below_0_7(self):
        """Score just below 0.7 should be 'adequate', not 'strong'."""
        assert get_mastery_level(0.6999) == "adequate"

    def test_boundary_just_below_0_5(self):
        """Score just below 0.5 should be 'developing', not 'adequate'."""
        assert get_mastery_level(0.4999) == "developing"

    def test_boundary_just_below_0_3(self):
        """Score just below 0.3 should be 'needs_work', not 'developing'."""
        assert get_mastery_level(0.2999) == "needs_work"


class TestMergeMisconceptions:
    """Tests for merge_misconceptions."""

    def test_merge_no_duplicates(self):
        """Merging distinct lists should combine them."""
        result = merge_misconceptions(["a", "b"], ["c", "d"])
        assert result == ["a", "b", "c", "d"]

    def test_merge_with_duplicates(self):
        """Duplicate entries should be removed."""
        result = merge_misconceptions(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_empty_existing(self):
        """Empty existing list should return only new misconceptions."""
        result = merge_misconceptions([], ["x", "y"])
        assert result == ["x", "y"]

    def test_empty_new(self):
        """Empty new list should return existing misconceptions."""
        result = merge_misconceptions(["x", "y"], [])
        assert result == ["x", "y"]

    def test_both_empty(self):
        """Both empty lists should return empty list."""
        result = merge_misconceptions([], [])
        assert result == []

    def test_max_count_trims_from_front(self):
        """When exceeding max_count, keep the most recent (last) items."""
        result = merge_misconceptions(
            ["a", "b", "c"],
            ["d", "e"],
            max_count=3,
        )
        # Total unique: [a, b, c, d, e], keep last 3
        assert result == ["c", "d", "e"]

    def test_max_count_not_exceeded(self):
        """When under max_count, return all items."""
        result = merge_misconceptions(["a", "b"], ["c"], max_count=10)
        assert result == ["a", "b", "c"]

    def test_max_count_exact(self):
        """When exactly at max_count, return all items."""
        result = merge_misconceptions(["a", "b"], ["c"], max_count=3)
        assert result == ["a", "b", "c"]

    def test_default_max_count_is_ten(self):
        """Default max_count should be 10."""
        items = [f"item_{i}" for i in range(15)]
        result = merge_misconceptions(items, [])
        assert len(result) == 10
        # Should keep the last 10
        assert result == [f"item_{i}" for i in range(5, 15)]

    def test_all_duplicates(self):
        """All duplicate entries should collapse to unique set."""
        result = merge_misconceptions(["a", "b"], ["a", "b"])
        assert result == ["a", "b"]

    def test_preserves_order(self):
        """Order should be preserved: existing first, then new."""
        result = merge_misconceptions(["first", "second"], ["third"])
        assert result == ["first", "second", "third"]

    def test_max_count_one(self):
        """Max count of 1 should keep only the last item."""
        result = merge_misconceptions(["a", "b"], ["c"], max_count=1)
        assert result == ["c"]
