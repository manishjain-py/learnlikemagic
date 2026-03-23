"""
Session Experience Evaluator — Naturalness Judge

Reads the full conversation (welcome → cards → interactive → end) and flags
specific messages that feel unnatural, forced, overwhelming, or inappropriate
for an average/below-average student.

This is NOT a dimension-scoring evaluator. It's a message-level naturalness
reviewer that identifies WHICH messages break the flow and WHY.
"""

import json
from pathlib import Path

from autoresearch.session_experience.evaluation.config import SessionExperienceConfig

# Issue categories for flagged messages
ISSUE_CATEGORIES = [
    "forced_transition",      # "Great! Now let's..." instead of natural flow
    "overwhelming",           # Too much info in one message for this student
    "unnatural_language",     # Sounds like chatbot, not a person
    "complexity_mismatch",    # Vocabulary/concepts too advanced
    "emotional_disconnect",   # Praise too big, not acknowledging struggle
    "repetitive_pattern",     # Tutor always asks/responds the same way
    "abrupt_shift",           # Ignoring what student said, jumping ahead
    "card_disconnect",        # No reference to what cards just taught
    "robotic_structure",      # Every response has same format (praise → teach → question)
    "false_ok_missed",        # Student said "hmm ok" and tutor plowed forward
    "information_dump",       # Wall of text when student needs bite-sized pieces
    "premature_advance",      # Moving to next concept before student is ready
]

EXPERIENCE_EVALUATOR_PROMPT = (Path(__file__).parent / "prompts" / "experience_evaluator.txt").read_text()


class ExperienceEvaluator:
    """Evaluates conversation naturalness by flagging specific problematic messages."""

    def __init__(self, config: SessionExperienceConfig):
        self.config = config
        self.llm = config.create_llm_service("evaluator")

    def _format_transcript(self, conversation: list[dict]) -> str:
        lines = []
        for msg in conversation:
            role = msg.get("role", "unknown")
            turn = msg.get("turn", "?")
            phase = msg.get("phase", "")

            if role == "explanation_card":
                lines.append(f"[EXPLANATION CARD] {msg['content']}")
            elif role == "tutor":
                phase_label = f" ({phase})" if phase else ""
                lines.append(f"[Turn {turn}] TUTOR{phase_label}: {msg['content']}")
            elif role == "student":
                lines.append(f"[Turn {turn}] STUDENT: {msg['content']}")
            else:
                lines.append(f"[Turn {turn}] {role.upper()}: {msg['content']}")

        return "\n\n".join(lines)

    def _build_user_message(
        self,
        conversation: list[dict],
        persona: dict | None = None,
        card_phase_data: dict | None = None,
        topic_name: str | None = None,
    ) -> str:
        has_cards = any(m.get("role") == "explanation_card" for m in conversation)

        card_context = ""
        if has_cards and card_phase_data:
            cards = card_phase_data.get("cards", [])
            variant = card_phase_data.get("variant_key", "?")
            card_context = (
                f"\n\n## CARD PHASE CONTEXT\n"
                f"Before the interactive session, the student was shown "
                f"{len(cards)} pre-computed explanation cards (variant {variant}). "
                f"The student clicked 'Clear' (indicating they read them), then "
                f"transitioned to the interactive teaching.\n"
                f"Cards appear as [EXPLANATION CARD] entries in the transcript."
            )

        transcript = self._format_transcript(conversation)
        message = f"## FULL CONVERSATION TRANSCRIPT\n\n{transcript}"
        message += card_context

        if topic_name:
            message += f"\n\n## TOPIC\n{topic_name}"

        if persona:
            message += (
                f"\n\n## STUDENT PROFILE\n"
                f"Name: {persona['name']}, Age: {persona.get('age', '?')}, "
                f"Grade: {persona.get('grade', '?')}\n"
                f"Correct answer probability: {int(persona.get('correct_answer_probability', 0.6) * 100)}%\n"
                f"Key traits: {', '.join(persona.get('personality_traits', [])[:5])}"
            )

        message += "\n\nPlease review this conversation and flag any messages that don't feel natural. Return JSON."
        return message

    def evaluate(
        self,
        conversation: list[dict],
        persona: dict | None = None,
        card_phase_data: dict | None = None,
        topic_name: str | None = None,
    ) -> dict:
        """Evaluate a conversation for naturalness. Returns flagged messages."""
        system_prompt = EXPERIENCE_EVALUATOR_PROMPT.format(
            issue_categories=", ".join(ISSUE_CATEGORIES),
        )
        user_message = self._build_user_message(conversation, persona, card_phase_data, topic_name)
        prompt = f"{system_prompt}\n\n{user_message}"

        result = self.llm.call(prompt=prompt, reasoning_effort="high", json_mode=True)
        parsed = result.get("parsed") or self.llm.parse_json_response(result["output_text"])
        return parsed
