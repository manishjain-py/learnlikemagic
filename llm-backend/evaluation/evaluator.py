"""
Conversation Evaluator

Uses OpenAI Responses API (gpt-5.2) or Anthropic Messages API (claude-opus-4-6)
with high reasoning effort to evaluate a tutoring conversation across 10 dimensions.
"""

import json
from openai import OpenAI

from evaluation.config import EvalConfig

EVALUATION_DIMENSIONS = [
    "coherence",
    "non_repetition",
    "natural_flow",
    "engagement",
    "responsiveness",
    "pacing",
    "grade_appropriateness",
    "topic_coverage",
    "session_arc",
    "overall_naturalness",
]

ROOT_CAUSE_CATEGORIES = [
    "conversation_history_window",
    "session_summary_lossy",
    "multi_agent_composition",
    "turn_level_processing",
    "rigid_study_plan",
    "prompt_quality",
    "model_capability",
    "other",
]

EVALUATOR_PROMPT = """You are an expert evaluator of AI tutoring conversations. You will be given a full transcript of a tutoring session between an AI tutor and a grade school student.

Your job is to evaluate the quality of the TUTOR's performance (not the student) across 10 dimensions, and identify the top problems.

## EVALUATION DIMENSIONS (score each 1-10)

1. **Coherence** (1-10): Does the tutor maintain a logical thread across turns? Do responses connect to what was said before, or do they feel disconnected?

2. **Non-Repetition** (1-10): Does the tutor avoid repeating the same explanations, phrases, or questions? Or does it say the same thing multiple times?

3. **Natural Flow** (1-10): Does the conversation feel like a natural tutoring session? Or does it feel robotic, formulaic, or like a chatbot?

4. **Engagement** (1-10): Does the tutor keep the student interested? Does it use relatable examples, encouragement, and varied approaches?

5. **Responsiveness** (1-10): Does the tutor actually respond to what the student says? Or does it ignore the student's input and follow its own script?

6. **Pacing** (1-10): Is the tutor's pacing appropriate? Does it move too fast, too slow, or adapt to the student's level of understanding?

7. **Grade Appropriateness** (1-10): Is the language and content appropriate for the student's grade level? Not too simple, not too complex?

8. **Topic Coverage** (1-10): Does the session cover the intended learning objectives? Does it make progress through the curriculum?

9. **Session Arc** (1-10): Does the session have a natural beginning, middle, and end? Does it feel like a complete learning experience?

10. **Overall Naturalness** (1-10): Taking everything together, how natural and human-like does this tutoring session feel?

## PROBLEM IDENTIFICATION

Identify the **top 5 most significant problems** in this conversation. For each problem:
- Cite specific turn numbers where the problem occurs
- Describe what went wrong
- Rate severity: "critical", "major", or "minor"
- Assign a root cause category from: conversation_history_window, session_summary_lossy, multi_agent_composition, turn_level_processing, rigid_study_plan, prompt_quality, model_capability, other

## OUTPUT FORMAT (JSON)

Return a JSON object with this exact structure:
{
  "scores": {
    "coherence": <1-10>,
    "non_repetition": <1-10>,
    "natural_flow": <1-10>,
    "engagement": <1-10>,
    "responsiveness": <1-10>,
    "pacing": <1-10>,
    "grade_appropriateness": <1-10>,
    "topic_coverage": <1-10>,
    "session_arc": <1-10>,
    "overall_naturalness": <1-10>
  },
  "dimension_analysis": {
    "coherence": "<2-3 sentence analysis>",
    "non_repetition": "<2-3 sentence analysis>",
    "natural_flow": "<2-3 sentence analysis>",
    "engagement": "<2-3 sentence analysis>",
    "responsiveness": "<2-3 sentence analysis>",
    "pacing": "<2-3 sentence analysis>",
    "grade_appropriateness": "<2-3 sentence analysis>",
    "topic_coverage": "<2-3 sentence analysis>",
    "session_arc": "<2-3 sentence analysis>",
    "overall_naturalness": "<2-3 sentence analysis>"
  },
  "problems": [
    {
      "title": "<short problem title>",
      "turns": [<turn numbers>],
      "description": "<what went wrong>",
      "quote": "<exact quote from conversation showing the problem>",
      "severity": "critical|major|minor",
      "root_cause": "<category from list above>"
    }
  ],
  "summary": "<3-5 sentence overall assessment>"
}"""


class ConversationEvaluator:
    """Evaluates a tutoring conversation using an LLM judge."""

    def __init__(self, config: EvalConfig):
        self.config = config
        self.provider = config.eval_llm_provider

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

    def _build_user_message(self, conversation: list[dict], topic_info: dict | None = None) -> str:
        transcript = self._format_transcript(conversation)
        user_message = f"## CONVERSATION TRANSCRIPT\n\n{transcript}"

        if topic_info:
            objectives = topic_info.get("guidelines", {}).get("learning_objectives", [])
            misconceptions = topic_info.get("guidelines", {}).get("common_misconceptions", [])
            user_message += f"\n\n## TOPIC CONTEXT\n"
            user_message += f"Topic: {topic_info.get('topic_name', 'Unknown')}\n"
            user_message += f"Grade Level: {topic_info.get('grade_level', 'Unknown')}\n"
            user_message += f"Learning Objectives: {json.dumps(objectives)}\n"
            user_message += f"Common Misconceptions: {json.dumps(misconceptions)}\n"

        user_message += "\n\nPlease evaluate this tutoring conversation according to the rubric. Return your evaluation as JSON."
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

    def evaluate(self, conversation: list[dict], topic_info: dict | None = None) -> dict:
        """Evaluate a conversation transcript."""
        user_message = self._build_user_message(conversation, topic_info)

        if self.provider == "anthropic":
            return self._evaluate_anthropic(user_message)
        return self._evaluate_openai(user_message)
