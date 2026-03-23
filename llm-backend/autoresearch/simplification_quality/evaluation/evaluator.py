"""
Simplification Quality Evaluator — LLM-as-Judge

Evaluates how well a simplified explanation card addresses the student's
"I didn't understand" feedback. Scores on 5 dimensions: reason adherence,
content differentiation, simplicity, concept accuracy, presentation quality.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("autoresearch.simplification_quality")

REASON_LABELS = {
    "example": "I need an example",
    "simpler_words": "The language is tough",
    "elaborate": "I need more detail",
    "different_approach": "Explain it differently",
}

EVALUATOR_PROMPT = (Path(__file__).parent / "prompts" / "evaluator.txt").read_text()


class SimplificationEvaluator:
    """Evaluates how well a simplified card addresses student feedback."""

    def __init__(self, config):
        self.llm = config.create_llm_service("evaluator")

    def _build_user_message(
        self,
        original_card: dict,
        simplified_card: dict,
        reason: str,
        previous_attempts: list[dict],
        grade: int,
        topic_name: str,
    ) -> str:
        reason_label = REASON_LABELS.get(reason, reason)

        parts = [
            f"## TOPIC\n{topic_name}",
            f"## STUDENT GRADE\n{grade}",
            f"## REASON FOR SIMPLIFICATION\nCode: {reason}\nStudent said: \"{reason_label}\"",
        ]

        # Original card
        orig_title = original_card.get("title", "")
        orig_body = original_card.get("body", original_card.get("content", ""))
        parts.append(
            f"## ORIGINAL CARD\n"
            f"Title: {orig_title}\n"
            f"Body:\n{orig_body}"
        )

        # Previous attempts (for depth-2+ simplifications)
        if previous_attempts:
            for i, attempt in enumerate(previous_attempts, 1):
                att_title = attempt.get("title", "")
                att_body = attempt.get("body", attempt.get("content", ""))
                parts.append(
                    f"## PREVIOUS ATTEMPT {i}\n"
                    f"Title: {att_title}\n"
                    f"Body:\n{att_body}"
                )

        # Simplified card being evaluated
        simp_title = simplified_card.get("title", "")
        simp_body = simplified_card.get("body", simplified_card.get("content", ""))
        parts.append(
            f"## SIMPLIFIED CARD (being evaluated)\n"
            f"Title: {simp_title}\n"
            f"Body:\n{simp_body}"
        )

        parts.append("Please evaluate this simplification and return JSON.")
        return "\n\n".join(parts)

    def evaluate(
        self,
        original_card: dict,
        simplified_card: dict,
        reason: str,
        previous_attempts: list[dict],
        grade: int,
        topic_name: str,
    ) -> dict:
        """Evaluate a simplified card. Returns scores dict."""
        system_prompt = EVALUATOR_PROMPT.format(grade=grade)
        user_message = self._build_user_message(
            original_card, simplified_card, reason, previous_attempts, grade, topic_name
        )
        prompt = f"{system_prompt}\n\n{user_message}"

        try:
            result = self.llm.call(prompt=prompt, reasoning_effort="high", json_mode=True)
            parsed = result.get("parsed") or self.llm.parse_json_response(result["output_text"])
            return parsed
        except Exception:
            logger.exception("Failed to evaluate simplification")
            default_dim = {"score": 1, "rationale": "Evaluation failed"}
            return {
                "reason_adherence": default_dim,
                "content_differentiation": default_dim,
                "simplicity": default_dim,
                "concept_accuracy": default_dim,
                "presentation_quality": default_dim,
                "overall_assessment": "Evaluation failed — could not parse LLM response",
                "specific_issues": [],
                "suggestions": [],
            }
