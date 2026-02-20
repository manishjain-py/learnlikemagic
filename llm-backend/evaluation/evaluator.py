"""
Conversation Evaluator

Uses OpenAI Responses API (gpt-5.2) or Anthropic Messages API (claude-opus-4-6)
with high reasoning effort to evaluate a tutoring conversation across 10 dimensions.
"""

import json
from openai import OpenAI

from evaluation.config import EvalConfig

EVALUATION_DIMENSIONS = [
    "responsiveness",
    "explanation_quality", 
    "emotional_attunement",
    "pacing",
    "authenticity",
]

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
    "other",
]

EVALUATOR_PROMPT = """You are an expert evaluator of AI tutoring conversations, focused on teaching craft and persona-aware evaluation.

You will be given a full transcript of a tutoring session between an AI tutor and a grade school student. The student was roleplaying as a specific persona with distinct characteristics and learning tendencies.

Your job is to evaluate how well the TUTOR adapted to and taught THIS specific type of student across 5 teaching-craft dimensions.

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
- Assign a root cause category from: missed_student_signal, wrong_pacing, repetitive_approach, emotional_mismatch, missed_misconception, over_scaffolding, conversation_history_window, prompt_quality, model_capability, other

## OUTPUT FORMAT (JSON)

Return a JSON object with this exact structure:
{
  "scores": {
    "responsiveness": <1-10>,
    "explanation_quality": <1-10>,
    "emotional_attunement": <1-10>,
    "pacing": <1-10>,
    "authenticity": <1-10>
  },
  "dimension_analysis": {
    "responsiveness": "<2-3 sentence analysis considering the student persona>",
    "explanation_quality": "<2-3 sentence analysis considering the student persona>",
    "emotional_attunement": "<2-3 sentence analysis considering the student persona>",
    "pacing": "<2-3 sentence analysis considering the student persona>",
    "authenticity": "<2-3 sentence analysis considering the student persona>"
  },
  "problems": [
    {
      "title": "<short problem title>",
      "turns": [<turn numbers>],
      "description": "<what went wrong in context of this persona>",
      "quote": "<exact quote from conversation showing the problem>",
      "severity": "critical|major|minor",
      "root_cause": "<category from list above>"
    }
  ],
  "summary": "<3-5 sentence overall assessment of how well the tutor handled THIS specific student persona>"
}"""


class ConversationEvaluator:
    """Evaluates a tutoring conversation using an LLM judge."""

    def __init__(self, config: EvalConfig):
        self.config = config
        self.provider = config.evaluator_provider

        if self.provider == "anthropic":
            import anthropic
            self.anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        else:
            self.client = OpenAI(api_key=config.openai_api_key)

    def _format_transcript(self, conversation: list[dict]) -> str:
        lines = []
        for msg in conversation:
            role = "TUTOR" if msg["role"] == "tutor" else "STUDENT"
            turn = msg.get("turn", "?")
            lines.append(f"[Turn {turn}] {role}: {msg['content']}")
        return "\n\n".join(lines)

    def _build_user_message(self, conversation: list[dict], topic_info: dict | None = None, persona: dict | None = None) -> str:
        transcript = self._format_transcript(conversation)
        user_message = f"## CONVERSATION TRANSCRIPT\n\n{transcript}"

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

    def _evaluate_openai(self, user_message: str) -> dict:
        response = self.client.responses.create(
            model=self.config.evaluator_model,
            instructions=EVALUATOR_PROMPT,
            input=user_message,
            reasoning={"effort": self.config.evaluator_reasoning_effort},
            text={"format": {"type": "json_object"}},
        )
        return json.loads(response.output_text)

    def _evaluate_anthropic(self, user_message: str) -> dict:
        thinking_budget = self.config.anthropic_evaluator_thinking_budget
        max_tokens = max(thinking_budget + 8192, 25000)

        text_content = ""
        with self.anthropic_client.messages.stream(
            model=self.config.anthropic_evaluator_model,
            max_tokens=max_tokens,
            system=EVALUATOR_PROMPT,
            thinking={
                "type": "enabled",
                "budget_tokens": thinking_budget,
            },
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for event in stream:
                pass
            response = stream.get_final_message()

        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()
                return json.loads(text)

        raise ValueError("No text block found in Anthropic response")

    def evaluate(self, conversation: list[dict], topic_info: dict | None = None, persona: dict | None = None) -> dict:
        """Evaluate a conversation transcript."""
        user_message = self._build_user_message(conversation, topic_info, persona)

        if self.provider == "anthropic":
            return self._evaluate_anthropic(user_message)
        return self._evaluate_openai(user_message)
