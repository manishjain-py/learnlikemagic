"""
Simplification Quality Evaluator — LLM-as-Judge

Evaluates how well a simplified explanation card addresses the student's
"I didn't understand" feedback. Scores on 5 dimensions: reason adherence,
content differentiation, simplicity, concept accuracy, presentation quality.
"""

import json
import logging

logger = logging.getLogger("autoresearch.simplification_quality")

REASON_LABELS = {
    "example": "I need an example",
    "simpler_words": "The language is tough",
    "elaborate": "I need more detail",
    "different_approach": "Explain it differently",
}

EVALUATOR_PROMPT = """You are an expert evaluator for an AI tutoring app's "I didn't understand" simplification feature. A student read an explanation card and said they didn't understand. The system generated a simplified version. Your job is to judge how well the simplified card addresses the student's feedback.

## SCORING DIMENSIONS (each 1-10)

### 1. reason_adherence
Does the simplified card actually address what the student asked for?

Reason-specific expectations:
- **"example"** (student said "I need an example"):
  Score 1 = No example at all, just rephrased the theory
  Score 5 = Has an example but it's abstract or not relatable for this grade
  Score 10 = Has a concrete, relatable, age-appropriate example that directly illustrates the concept

- **"simpler_words"** (student said "The language is tough"):
  Score 1 = Same vocabulary level or even harder
  Score 5 = Some words simplified but key terms still complex
  Score 10 = Everyday language throughout, technical terms explained in simple words

- **"elaborate"** (student said "I need more detail"):
  Score 1 = Same level of detail or less
  Score 5 = Adds some detail but misses the parts that needed elaboration
  Score 10 = Breaks down the concept into finer steps, fills in the gaps the original left

- **"different_approach"** (student said "Explain it differently"):
  Score 1 = Same structure and approach, just reworded
  Score 5 = Somewhat different angle but still recognizably the same explanation
  Score 10 = Completely fresh approach — different analogy, different structure, different entry point

### 2. content_differentiation
Is the content genuinely different from the original card (and from previous attempts if any)?
Not just rephrased — a different angle, analogy, or structure.
Score 1 = Copy-paste with minor word swaps
Score 5 = Same structure but different wording and some new elements
Score 10 = Entirely fresh explanation that covers the same concept from a new angle

### 3. simplicity
Is the language simple enough for the target grade?
Score 1 = University-level language, long complex sentences
Score 5 = Mix of simple and complex, some sentences too long
Score 10 = Short sentences, everyday words, one idea at a time, perfect for the grade

### 4. concept_accuracy
Does it still explain the same concept correctly?
Score 1 = Wrong information or drifted to a different topic entirely
Score 5 = Mostly correct but has a subtle inaccuracy or misleading simplification
Score 10 = Perfectly accurate, simplifies without distorting

### 5. presentation_quality
Clean formatting, no meta-commentary, good structure.
Score 1 = Starts with "Let me explain this differently...", has "Let's simplify:" in the title, is a wall of text
Score 5 = Mostly clean but has minor issues (slightly verbose, one meta-comment)
Score 10 = Clean title (no prefixes), no preamble, well-structured, appropriate length

## OUTPUT FORMAT (JSON)

Return a JSON object:
{{
  "reason_adherence": {{"score": <1-10>, "rationale": "<1-2 sentences>"}},
  "content_differentiation": {{"score": <1-10>, "rationale": "<1-2 sentences>"}},
  "simplicity": {{"score": <1-10>, "rationale": "<1-2 sentences>"}},
  "concept_accuracy": {{"score": <1-10>, "rationale": "<1-2 sentences>"}},
  "presentation_quality": {{"score": <1-10>, "rationale": "<1-2 sentences>"}},
  "overall_assessment": "<2-3 sentences: overall quality of this simplification>",
  "specific_issues": ["<issue 1>", "<issue 2>"],
  "suggestions": ["<suggestion 1>"]
}}

CRITICAL RULES:
- Be strict. A score of 7+ means genuinely good, not just "okay".
- Judge from the perspective of a grade {grade} student.
- If the student asked for an example and there's no example, reason_adherence MUST be ≤ 3.
- If the simplified card is essentially the same text reworded, content_differentiation MUST be ≤ 3.
- If there are previous attempts shown, differentiation must also be from those attempts, not just the original."""


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
