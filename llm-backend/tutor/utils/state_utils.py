"""
State management utilities.

Provides helper functions for mastery calculations and progress tracking.
"""

from typing import Optional


def update_mastery_estimate(
    current: float,
    is_correct: bool,
    confidence: float = 1.0,
    learning_rate: float = 0.2,
) -> float:
    """
    Update mastery estimate using exponential moving average.

    Correct answers move mastery toward 1.0 with diminishing returns.
    Incorrect answers decrease mastery but preserve some progress.
    """
    effective_rate = learning_rate * confidence

    if is_correct:
        delta = (1.0 - current) * effective_rate
    else:
        delta = -current * effective_rate * 0.5

    return max(0.0, min(1.0, current + delta))


def calculate_overall_mastery(
    mastery_estimates: dict[str, float],
    weights: Optional[dict[str, float]] = None,
) -> float:
    """Calculate overall mastery score from individual concept scores."""
    if not mastery_estimates:
        return 0.0

    if weights is None:
        return sum(mastery_estimates.values()) / len(mastery_estimates)

    total_weight = 0.0
    weighted_sum = 0.0

    for concept, score in mastery_estimates.items():
        weight = weights.get(concept, 1.0)
        weighted_sum += score * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    return weighted_sum / total_weight


def should_advance_step(
    mastery_estimates: dict[str, float],
    current_concept: str,
    threshold: float = 0.7,
) -> bool:
    """Determine if the student should advance to the next step."""
    current_mastery = mastery_estimates.get(current_concept, 0.0)
    return current_mastery >= threshold


def get_mastery_level(score: float) -> str:
    """Convert mastery score to categorical level."""
    if score >= 0.9:
        return "mastered"
    elif score >= 0.7:
        return "strong"
    elif score >= 0.5:
        return "adequate"
    elif score >= 0.3:
        return "developing"
    else:
        return "needs_work"


def merge_misconceptions(
    existing: list[str],
    new_misconceptions: list[str],
    max_count: int = 10,
) -> list[str]:
    """Merge new misconceptions with existing ones, avoiding duplicates."""
    seen = {}
    for m in existing + new_misconceptions:
        if m not in seen:
            seen[m] = True
    return list(seen.keys())[-max_count:]
