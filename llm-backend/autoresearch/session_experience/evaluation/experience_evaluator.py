"""
Session Experience Evaluator — Naturalness Judge

Reads the full conversation (welcome → cards → interactive → end) and flags
specific messages that feel unnatural, forced, overwhelming, or inappropriate
for an average/below-average student.

This is NOT a dimension-scoring evaluator. It's a message-level naturalness
reviewer that identifies WHICH messages break the flow and WHY.
"""

import json

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

EXPERIENCE_EVALUATOR_PROMPT = """You are reviewing a complete tutoring session between an AI tutor and a grade school student. Your job is to read the ENTIRE conversation — from the very first welcome message, through any explanation cards, through every interactive exchange, to the session end — and identify specific messages that DON'T FEEL RIGHT.

Think of yourself as a parent sitting next to their child during this session. You're watching every message. When something makes you think "that was weird" or "that was too much" or "the tutor missed something obvious" — flag it.

## THE STUDENT

The student is an average or below-average learner. They:
- Need simple language and everyday examples
- Get overwhelmed by too much information at once
- Won't tell you they're confused — they'll just say "ok" or go quiet
- Need frequent check-ins, not long monologues
- Respond best to warm, patient, conversational teaching
- Are between ages 8-12

## WHAT TO FLAG

Flag any tutor message where:

**Flow breaks:**
- The transition from one topic/phase to another feels forced or abrupt
- The conversation suddenly changes direction without acknowledging what just happened
- A message feels like it belongs in a different conversation

**Overwhelming content:**
- Too many ideas crammed into one message
- Vocabulary that's too advanced for the student
- Long explanations when a few sentences would do
- Multiple questions in one message

**Unnatural tone:**
- Sounds like a chatbot (formulaic praise, template responses, overly structured)
- Every response follows the same pattern (praise → explain → question)
- Generic encouragement that doesn't match the moment
- Overly enthusiastic about trivial things

**Missed signals:**
- Student gave a vague "ok" / "hmm ok" and tutor didn't probe
- Student seems confused but tutor moved forward
- Student's energy dropped but tutor didn't adjust
- Student gave a wrong answer and tutor's response didn't match the type of error

**Card phase issues (if cards were shown):**
- Tutor re-explains things the cards already covered
- Tutor ignores the cards entirely and starts fresh
- The transition from reading cards to interactive teaching is jarring
- No reference to the specific analogies/examples from cards

## WHAT FEELS NATURAL

For contrast — don't flag messages that:
- Build naturally on what the student just said
- Use simple language matched to the student
- Have a warm, conversational tone (not formulaic)
- Check understanding with simple, single questions
- Reference earlier parts of the conversation
- Respond proportionally (small praise for small wins, genuine excitement for breakthroughs)

## OUTPUT FORMAT (JSON)

Return a JSON object:
{{
  "flagged_messages": [
    {{
      "turn": <turn number>,
      "message_snippet": "<first 80 chars of the tutor message>",
      "issue_category": "<one of: {issue_categories}>",
      "description": "<1-2 sentences: what feels off and why it matters for this student>",
      "severity": "critical|major|minor",
      "surrounding_context": "<what happened before/after that makes this feel wrong>"
    }}
  ],
  "flow_assessment": "<2-3 sentences: overall, does this session flow naturally? Where does it break?>",
  "strongest_moments": "<1-2 sentences: what worked well — which parts felt most natural?>",
  "issue_count_by_severity": {{
    "critical": <count>,
    "major": <count>,
    "minor": <count>
  }},
  "overall_naturalness_score": <1-10, where 10 = perfectly natural conversation>
}}

CRITICAL RULES:
- Flag TUTOR messages only (the student is simulated, don't judge them)
- Be specific — cite the actual turn number and quote the message
- Focus on what an average student would experience, not what an expert would notice
- Fewer, more impactful flags > many trivial ones. Only flag things that genuinely break the experience.
- Maximum 10 flagged messages. If more than 10 issues exist, pick the 10 most significant."""


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
