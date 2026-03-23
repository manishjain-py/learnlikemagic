"""
Explanation Quality Evaluator

Uses LLMService with high reasoning effort to evaluate pre-computed
explanation cards across 5 dimensions focused on whether the explanation
actually helps a struggling student understand the concept.
"""

import json
from pathlib import Path

from autoresearch.explanation_quality.evaluation.config import ExplanationEvalConfig

EVALUATION_DIMENSIONS = [
    "simplicity",
    "concept_clarity",
    "examples_and_analogies",
    "structure_and_flow",
    "overall_effectiveness",
]

ROOT_CAUSE_CATEGORIES = [
    "complex_language",
    "abstract_explanation",
    "missing_visual",
    "too_dense",
    "wrong_sequence",
    "weak_analogy",
    "missing_anchor",
    "textbook_tone",
    "misconception_gap",
    "other",
]

EVALUATOR_PROMPT = (Path(__file__).parent / "prompts" / "evaluator.txt").read_text()


class ExplanationEvaluator:
    """Evaluates explanation cards using an LLM judge."""

    def __init__(self, config: ExplanationEvalConfig):
        self.config = config
        self.llm = config.create_llm_service("evaluator")

    def _format_cards(self, cards: list[dict]) -> str:
        """Format cards for the evaluator prompt."""
        lines = []
        for card in cards:
            idx = card.get("card_idx", "?")
            card_type = card.get("card_type", "?")
            title = card.get("title", "Untitled")
            content = card.get("content", "")
            visual = card.get("visual", "")

            lines.append(f"### Card {idx} [{card_type}]: {title}")
            lines.append(content)
            if visual:
                lines.append(f"\n**Visual:**\n```\n{visual}\n```")
            lines.append("")
        return "\n".join(lines)

    def evaluate(self, cards: list[dict], topic_title: str, grade: int, subject: str, guideline_text: str = "") -> dict:
        """Evaluate a set of explanation cards. Returns scores + analysis."""
        formatted_cards = self._format_cards(cards)

        system_prompt = EVALUATOR_PROMPT.format(grade=grade, subject=subject)

        user_message = f"## TOPIC: {topic_title}\n\n"
        if guideline_text:
            user_message += f"## TEACHING GUIDELINE\n{guideline_text}\n\n"
        user_message += f"## EXPLANATION CARDS ({len(cards)} cards)\n\n{formatted_cards}"
        user_message += "\n\nPlease evaluate these explanation cards according to the rubric. Return your evaluation as JSON."

        prompt = f"{system_prompt}\n\n{user_message}"

        result = self.llm.call(prompt=prompt, reasoning_effort="high", json_mode=True)
        parsed = result.get("parsed") or self.llm.parse_json_response(result["output_text"])
        return parsed
