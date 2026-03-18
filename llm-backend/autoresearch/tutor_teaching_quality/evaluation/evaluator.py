"""
Conversation Evaluator

Uses LLMService (supports openai, anthropic, claude_code providers) with high
reasoning effort to evaluate a tutoring conversation across 7 dimensions.

Dimensions 1-5 evaluate interactive teaching quality (original).
Dimensions 6-7 evaluate E2E coherence when pre-computed explanation cards were
shown before the interactive session.
"""

import json

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

EVALUATOR_PROMPT = """You are an expert evaluator of AI tutoring conversations, focused on teaching craft and persona-aware evaluation.

You will be given a full transcript of a tutoring session between an AI tutor and a grade school student. The student was roleplaying as a specific persona with distinct characteristics and learning tendencies.

Your job is to evaluate how well the TUTOR adapted to and taught THIS specific type of student across the evaluation dimensions below.

## EVALUATION DIMENSIONS (score each 1-10)

### 1. **Responsiveness** (1-10)
*Does the tutor adapt to student signals?*

- **9-10:** Tutor picks up on subtle cues (boredom, confusion, confidence), adjusts approach immediately. Asks follow-up questions that show it understood the student's state.
- **7-8:** Tutor generally responds to what the student says. Adjusts pace/difficulty when student is clearly struggling or breezing through.
- **5-6:** Tutor acknowledges student input but follows its own script. Some adaptation but mostly pre-planned.
- **3-4:** Tutor largely ignores student signals. Same pace/approach regardless of student responses.
- **1-2:** Tutor is a monologue. Student could be replaced by a "next" button.

### 2. **Explanation Quality** (1-10)
*Does the tutor explain well, and try different approaches when needed?*

- **9-10:** Explanations are clear, varied, use concrete examples. When one approach fails, tries another (visual → story → analogy). Checks if the new approach worked.
- **7-8:** Good explanations that mostly land. Occasionally tries a different approach. Uses age-appropriate language.
- **5-6:** Explanations are correct but formulaic. One approach per concept. If student doesn't get it, repeats similar explanation.
- **3-4:** Explanations are unclear, too abstract, or too wordy for the grade level.
- **1-2:** Explanations are wrong, confusing, or absent.

### 3. **Emotional Attunement** (1-10)
*Does the tutor read the room?*

- **9-10:** Tutor matches the student's emotional state perfectly. Celebrates breakthroughs, shows patience with struggle, doesn't over-praise easy wins. Feels like talking to a human who cares.
- **7-8:** Generally warm and encouraging. Appropriate emotional responses most of the time.
- **5-6:** Polite but flat. Stock phrases ("Great job!", "Not quite"). Doesn't differentiate between big and small moments.
- **3-4:** Emotionally mismatched. Over-praises trivial things, dismisses confusion, or is monotone.
- **1-2:** Cold, robotic, or condescending.

### 4. **Pacing** (1-10)
*Is the tutor moving at the right speed for this student?*

- **9-10:** Perfect calibration. Speeds up with quick learners, slows down with strugglers. Skips what's mastered, lingers on what's hard. Natural transitions.
- **7-8:** Generally good pacing with occasional mismatches (one too-easy question for an advanced student, or moving on before a struggling student is ready).
- **5-6:** Fixed pace regardless of student. Follows the plan without much adaptation.
- **3-4:** Consistently too fast or too slow. Doesn't read student's readiness.
- **1-2:** Wildly mismatched. Teaching calculus to a confused student, or drilling basics with one who's bored.

### 5. **Authenticity** (1-10)
*Does this feel like a real teacher, or a chatbot?*

- **9-10:** Completely natural. Varied language, appropriate informality, natural transitions. You'd believe this was a human tutor.
- **7-8:** Mostly natural with occasional chatbot-isms (formulaic praise, over-structured responses).
- **5-6:** Competent but clearly an AI. Structured responses, predictable patterns, stock phrases.
- **3-4:** Obviously a chatbot. Repetitive structure, unnatural transitions, template-like responses.
- **1-2:** Uncanny valley. Wrong register, bizarre phrasing, or clearly copy-pasted content.

{card_phase_dimensions}

## PERSONA-AWARE EVALUATION

Judge the tutor's responses based on the specific student persona. The same tutor behavior might score differently with different personas:

- **Ace students:** Did the tutor avoid patronizing? Speed up appropriately? Offer challenges?
- **Struggling students:** Did the tutor try different approaches? Show patience? Address specific misconceptions?
- **Quiet students:** Did the tutor draw them out with open questions? Check understanding despite minimal responses?
- **Distracted students:** Did the tutor handle tangents gracefully? Redirect without shutting down interests?
- **Confused-but-confident students:** Did the tutor probe confident wrong answers? Correct without crushing?

## PROBLEM IDENTIFICATION

Identify the **top 5 most significant problems** in this conversation. For each problem:
- Cite specific turn numbers where the problem occurs
- Describe what went wrong in the context of this persona
- Rate severity: "critical", "major", or "minor"
- Assign a root cause category from: {root_cause_list}

## OUTPUT FORMAT (JSON)

Return a JSON object with this exact structure:
{{
  "scores": {{
{scores_schema}
  }},
  "dimension_analysis": {{
{analysis_schema}
  }},
  "problems": [
    {{
      "title": "<short problem title>",
      "turns": [<turn numbers>],
      "description": "<what went wrong in context of this persona>",
      "quote": "<exact quote from conversation showing the problem>",
      "severity": "critical|major|minor",
      "root_cause": "<category from list above>"
    }}
  ],
  "summary": "<3-5 sentence overall assessment of how well the tutor handled THIS specific student persona>"
}}"""

# Additional dimensions shown only when card phase was present
CARD_PHASE_DIMENSIONS_TEXT = """
### 6. **Card-to-Session Coherence** (1-10)
*Does the interactive session feel connected to the explanation cards the student just read?*

- **9-10:** Tutor naturally references and builds on the specific analogies, examples, and concepts from the cards. Feels like one continuous learning experience. Uses cards as a springboard — "Remember when we talked about X? Now let's see what happens when..."
- **7-8:** Tutor is aware of the cards and avoids repetition. Occasionally builds on card content. Mostly coherent but doesn't actively leverage what the student already read.
- **5-6:** Tutor doesn't repeat card content (good) but also doesn't reference it. Cards and interactive session feel like two separate lessons that happen to be about the same topic.
- **3-4:** Tutor re-explains things the cards already covered, or contradicts the card approach. Student would feel confused about which explanation to trust.
- **1-2:** No connection at all. Tutor acts as if the student is hearing about this topic for the first time.

### 7. **Transition Quality** (1-10)
*How smooth is the bridge from reading explanation cards to interactive teaching?*

- **9-10:** Transition feels natural and purposeful. Tutor checks what the student remembers from the cards, identifies gaps, and launches into interactive teaching from exactly the right point. Student feels their card-reading time was valued.
- **7-8:** Decent transition. Tutor acknowledges the cards and moves into interaction. Might miss probing what the student actually absorbed.
- **5-6:** Abrupt but functional. Student goes from reading cards to being asked questions without much bridging. Feels like a gear shift.
- **3-4:** Jarring transition. Generic "now let's check your understanding" with no connection to what was just read. Student feels like they walked into a different class.
- **1-2:** No transition at all, or the transition confuses the student about what they should know.
"""


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
            analysis_lines.append(f'    "{d}": "<2-3 sentence analysis considering the student persona>"')

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
