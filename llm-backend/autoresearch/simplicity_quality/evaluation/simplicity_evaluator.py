"""
Simplicity Evaluator — ELI5 Judge

Reads the full conversation (cards + interactive) and scores on ONE primary
dimension: radical simplicity. Also produces message-level flags for any
card or tutor message that's too complex for a struggling student.

Separate sub-scores for card_phase_simplicity and interactive_tutor_simplicity
to pinpoint whether problems are in cards or tutor messages.
"""

import json

from autoresearch.simplicity_quality.evaluation.config import SimplicityConfig

SIMPLICITY_EVALUATOR_PROMPT = """You are an expert evaluator of educational content simplicity. Your ONE job: determine whether every explanation card and every tutor message is simple enough that even a below-average IQ student would understand it INSTANTLY.

The gold standard: "Explain Like I'm 5" (ELI5). A struggling Grade 5 student should read any card or tutor message and think: "Wow, that's so simple. I just get it."

## WHAT TO EVALUATE

Score the ENTIRE session — both explanation cards AND tutor messages.

### Primary Dimension: **Simplicity Score** (1-10)

Judge EVERY visible card and tutor message on these sub-criteria:

**Word Choice** — Are ALL words from a child's daily vocabulary? Would a 10-year-old use these words in conversation? Is every technical term introduced with a simple everyday explanation alongside?

**Sentence Structure** — Are sentences short (under 15 words ideal)? One idea per sentence? No complex or compound clauses ("although X, if Y, then Z")? No nested structures?

**Concept Density** — One idea per card/message? No information overload? Student never needs to hold multiple new concepts at once?

**Concreteness** — Are examples specific and tangible (pizza slices, pocket money, cricket scores)? Not abstract or academic? Even with simple words, abstract explanations fail struggling students.

**Accessibility** — Would even a below-average IQ student understand immediately without re-reading? No "wait, what does that mean?" moments?

**The "Wow" Factor** — Does the student feel "that's so simple, I just get it!"? Does the explanation make a hard concept feel easy?

**Language Consistency** — Does the tutor reuse the same simple words from the cards, or "upgrade" to harder vocabulary in the interactive session?

### Scoring Rubric:
- **9-10:** Every single message is crystal clear. A 5-year-old could follow. Words are everyday, sentences are short, ideas are bite-sized. Student feels "wow, this is so simple!"
- **7-8:** Most messages are simple and clear. Occasional words or sentences could be simpler. Student pauses at 1-2 spots but generally follows easily.
- **5-6:** Mix of simple and complex. Some messages use big words, long sentences, or pack too many ideas. Student understands most but struggles with some.
- **3-4:** Often too complex. Textbook-like language, long explanations, multiple concepts at once. Student would feel overwhelmed at several points.
- **1-2:** Far too complex for a child. Academic language, dense paragraphs, abstract concepts without grounding. Student would give up.

### Supporting Dimensions (score separately, 1-10 each):

**Relatability** — Are examples from the student's world? Do analogies click immediately for a child? Are comparisons to things they experience daily?

**Progressive Building** — Is each step a tiny, natural leap from the previous? Could a student guess what's coming next? No jumps that require holding multiple ideas at once?

## MESSAGE-LEVEL FLAGS

For each card or tutor message that falls short of radical simplicity, flag it:

CRITICAL RULES:
- Flag BOTH explanation cards AND tutor messages
- Be specific — quote the exact word, phrase, or sentence that's too complex
- For each flag, suggest a concrete simplification (rewrite the complex part)
- Fewer impactful flags > many trivial ones. Max 12 flags.
- Do NOT flag very short responses ("Yes!", "Exactly", "Great job!") — brevity IS simplicity
- Do NOT flag a message just because it uses a technical term — only flag if the term isn't introduced simply alongside

## OUTPUT FORMAT (JSON)

Return a JSON object:
{{
  "card_phase_simplicity": <1-10 or null if no cards>,
  "interactive_tutor_simplicity": <1-10>,
  "overall_simplicity_score": <1-10, weighted average>,
  "relatability": <1-10>,
  "progressive_building": <1-10>,
  "flagged_messages": [
    {{
      "turn": <turn number or "card_N" for explanation cards>,
      "message_type": "card|tutor",
      "message_snippet": "<first 80 chars of the message>",
      "complex_part": "<the specific word/phrase/sentence that's too complex>",
      "why_complex": "<1 sentence: why this is too hard for a struggling student>",
      "simplification": "<concrete rewrite that would be simpler>",
      "severity": "critical|major|minor"
    }}
  ],
  "issue_count_by_severity": {{
    "critical": <count>,
    "major": <count>,
    "minor": <count>
  }},
  "simplicity_assessment": "<2-3 sentences: overall, how simple is this session? Where does complexity creep in?>",
  "strongest_simplicity_moments": "<1-2 sentences: which parts are exemplary in their simplicity?>"
}}"""


class SimplicityEvaluator:
    """Evaluates conversation simplicity by scoring cards and tutor messages."""

    def __init__(self, config: SimplicityConfig):
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

        message += "\n\nPlease evaluate this session for SIMPLICITY. Score every card and tutor message. Return JSON."
        return message

    def evaluate(
        self,
        conversation: list[dict],
        persona: dict | None = None,
        card_phase_data: dict | None = None,
        topic_name: str | None = None,
    ) -> dict:
        """Evaluate a conversation for simplicity. Returns scores + flagged messages."""
        system_prompt = SIMPLICITY_EVALUATOR_PROMPT
        user_message = self._build_user_message(conversation, persona, card_phase_data, topic_name)
        prompt = f"{system_prompt}\n\n{user_message}"

        result = self.llm.call(prompt=prompt, reasoning_effort="high", json_mode=True)
        parsed = result.get("parsed") or self.llm.parse_json_response(result["output_text"])
        return parsed
