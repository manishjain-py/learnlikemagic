"""
Conversation Evaluator

Uses LLMService (supports openai, anthropic, claude_code providers) with high
reasoning effort to evaluate a tutoring conversation across 7 dimensions.

Dimensions 1-5 evaluate interactive teaching quality (original).
Dimensions 6-7 evaluate E2E coherence when pre-computed explanation cards were
shown before the interactive session.
"""

import json
from pathlib import Path

from autoresearch.tutor_teaching_quality.evaluation.config import EvalConfig

EVALUATION_DIMENSIONS = [
    "responsiveness",
    "explanation_quality",
    "emotional_attunement",
    "pacing",
    "authenticity",
    "card_to_session_coherence",
    "transition_quality",
]

# Which dimensions only apply when cards were shown
CARD_PHASE_DIMENSIONS = {"card_to_session_coherence", "transition_quality"}

ROOT_CAUSE_CATEGORIES = [
    "missed_student_signal",
    "wrong_pacing",
    "repetitive_approach",
    "emotional_mismatch",
    "missed_misconception",
    "over_scaffolding",
    "conversation_history_window",
    "prompt_quality",
    "model_capability",
    "card_content_ignored",
    "abrupt_transition",
    "card_repetition",
    "other",
]

_PROMPTS_DIR = Path(__file__).parent / "prompts"
EVALUATOR_PROMPT = (_PROMPTS_DIR / "evaluator.txt").read_text()

# Additional dimensions shown only when card phase was present
CARD_PHASE_DIMENSIONS_TEXT = (_PROMPTS_DIR / "card_phase_dimensions.txt").read_text()


class ConversationEvaluator:
    """Evaluates a tutoring conversation using an LLM judge."""

    def __init__(self, config: EvalConfig):
        self.config = config
        self.llm = config.create_llm_service("evaluator")

    def _has_card_phase(self, conversation: list[dict]) -> bool:
        """Check if the conversation includes explanation cards."""
        return any(msg.get("role") == "explanation_card" for msg in conversation)

    def _build_prompt(self, has_cards: bool) -> str:
        """Build the evaluator prompt, including card dimensions only when relevant."""
        if has_cards:
            dims = [d for d in EVALUATION_DIMENSIONS]
            card_dims_text = CARD_PHASE_DIMENSIONS_TEXT
        else:
            dims = [d for d in EVALUATION_DIMENSIONS if d not in CARD_PHASE_DIMENSIONS]
            card_dims_text = ""

        scores_lines = []
        analysis_lines = []
        for d in dims:
            scores_lines.append(f'    "{d}": <1-10>')
            analysis_lines.append(f'    "{d}": "<1-2 sentence analysis — cite specific turns, be concise>"')

        return EVALUATOR_PROMPT.format(
            card_phase_dimensions=card_dims_text,
            root_cause_list=", ".join(ROOT_CAUSE_CATEGORIES),
            scores_schema=",\n".join(scores_lines),
            analysis_schema=",\n".join(analysis_lines),
        )

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
        topic_info: dict | None = None,
        persona: dict | None = None,
        card_phase_data: dict | None = None,
    ) -> str:
        has_cards = self._has_card_phase(conversation)

        # If card phase data provided, add context header
        card_context = ""
        if has_cards and card_phase_data:
            cards = card_phase_data.get("cards", [])
            variant = card_phase_data.get("variant_key", "?")
            total_variants = card_phase_data.get("total_variants", 1)
            card_context = (
                f"\n\n## CARD PHASE CONTEXT\n"
                f"Before the interactive session, the student was shown "
                f"{len(cards)} pre-computed explanation cards (variant {variant} "
                f"of {total_variants} available). The student clicked 'Clear' "
                f"(indicating they read and understood the cards), then transitioned "
                f"to the interactive teaching session below.\n"
                f"The card content is included in the transcript as [EXPLANATION CARD] entries."
            )

        transcript = self._format_transcript(conversation)
        user_message = f"## CONVERSATION TRANSCRIPT\n\n{transcript}"
        user_message += card_context

        if persona:
            user_message += f"\n\n## STUDENT PERSONA\n"
            user_message += f"The student was roleplaying as: **{persona['name']}** ({persona['persona_id']})\n\n"
            user_message += f"**Description:** {persona.get('description', 'No description')}\n\n"
            user_message += f"**Key traits:**\n"
            for trait in persona.get('personality_traits', []):
                user_message += f"- {trait}\n"
            user_message += f"\n**Correct answer probability:** {int(persona.get('correct_answer_probability', 0.6) * 100)}%\n"

            if 'persona_specific_behaviors' in persona:
                user_message += f"\n**Behavioral tendencies:**\n"
                for behavior, prob in persona['persona_specific_behaviors'].items():
                    behavior_name = behavior.replace('_', ' ').replace('probability', '').strip()
                    user_message += f"- {behavior_name}: {int(prob * 100)}% of the time\n"

        if topic_info:
            objectives = topic_info.get("guidelines", {}).get("learning_objectives", [])
            misconceptions = topic_info.get("guidelines", {}).get("common_misconceptions", [])
            user_message += f"\n\n## TOPIC CONTEXT\n"
            user_message += f"Topic: {topic_info.get('topic_name', 'Unknown')}\n"
            user_message += f"Grade Level: {topic_info.get('grade_level', 'Unknown')}\n"
            user_message += f"Learning Objectives: {json.dumps(objectives)}\n"
            user_message += f"Common Misconceptions: {json.dumps(misconceptions)}\n"

        user_message += "\n\nPlease evaluate this tutoring conversation according to the rubric, taking into account how well the tutor adapted to THIS specific student persona. Return your evaluation as JSON."
        return user_message

    def evaluate(
        self,
        conversation: list[dict],
        topic_info: dict | None = None,
        persona: dict | None = None,
        card_phase_data: dict | None = None,
    ) -> dict:
        """Evaluate a conversation transcript.

        Args:
            conversation: Full conversation including card entries if present.
            topic_info: Topic metadata (name, objectives, misconceptions).
            persona: Student persona definition.
            card_phase_data: Card phase metadata from session runner (cards, variant, etc.).
        """
        has_cards = self._has_card_phase(conversation)
        system_prompt = self._build_prompt(has_cards)
        user_message = self._build_user_message(conversation, topic_info, persona, card_phase_data)
        prompt = f"{system_prompt}\n\n{user_message}"

        result = self.llm.call(prompt=prompt, reasoning_effort="high", json_mode=True)
        parsed = result.get("parsed") or self.llm.parse_json_response(result["output_text"])
        return parsed
