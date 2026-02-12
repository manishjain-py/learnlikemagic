"""
Student Simulator

Uses OpenAI Chat Completions API (gpt-4o) or Anthropic Messages API
to simulate a student responding to a tutor during a tutoring session.
"""

import time
from openai import OpenAI, RateLimitError

from evaluation.config import EvalConfig


class StudentSimulator:
    """Simulates a student using an LLM to generate realistic responses."""

    def __init__(self, config: EvalConfig, persona: dict):
        self.config = config
        self.persona = persona
        self.provider = config.eval_llm_provider
        self.system_prompt = self._build_system_prompt()

        if self.provider == "anthropic":
            import anthropic
            self.anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        else:
            self.client = OpenAI(api_key=config.openai_api_key)

    def _build_system_prompt(self) -> str:
        p = self.persona
        traits = "\n".join(f"- {t}" for t in p["personality_traits"])
        mistakes = "\n".join(f"- {m}" for m in p["common_mistakes"])
        examples = "\n".join(f'- "{e}"' for e in p["response_style"]["examples"])
        behavioral = "\n".join(f"- {b}" for b in p["behavioral_notes"])

        return f"""You are roleplaying as {p['name']}, a {p['age']}-year-old grade {p['grade']} student in a tutoring session.

PERSONALITY:
{traits}

COMMON MISTAKES you make (use these when you answer incorrectly):
{mistakes}

YOUR RESPONSE STYLE:
- Keep responses under {p['response_style']['max_words']} words
- Use {p['response_style']['language']}
- You are a real student, not a chatbot. Sound natural.

EXAMPLE RESPONSES (for tone reference):
{examples}

BEHAVIORAL GUIDELINES:
{behavioral}

IMPORTANT RULES:
1. You answer correctly about {int(p['correct_answer_probability'] * 100)}% of the time.
2. When you get something wrong, pick from your common mistakes list.
3. Never break character. You are {p['name']}, a {p['age']}-year-old.
4. Keep responses SHORT — a real kid doesn't write paragraphs.
5. React naturally: show confusion, excitement, boredom, curiosity.
6. If the tutor asks a question, ANSWER it (correctly or incorrectly based on your probability).
7. Don't repeat what the tutor said back to them word for word."""

    def generate_response(self, conversation: list[dict], topic_info: dict | None = None) -> str:
        """Generate a student response given the conversation so far."""
        if self.provider == "anthropic":
            return self._generate_anthropic(conversation, topic_info)
        return self._generate_openai(conversation, topic_info)

    def _generate_openai(self, conversation: list[dict], topic_info: dict | None = None) -> str:
        messages = [{"role": "system", "content": self.system_prompt}]

        if topic_info:
            context = f"[Context: The tutoring session is about '{topic_info.get('topic_name', 'a topic')}' for grade {topic_info.get('grade_level', 5)}]"
            messages.append({"role": "system", "content": context})

        for msg in conversation:
            if msg["role"] == "tutor":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "student":
                messages.append({"role": "assistant", "content": msg["content"]})

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.simulator_model,
                    messages=messages,
                    temperature=self.config.simulator_temperature,
                    max_tokens=self.config.simulator_max_tokens,
                )
                return response.choices[0].message.content.strip()
            except RateLimitError:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    raise

    def _generate_anthropic(self, conversation: list[dict], topic_info: dict | None = None) -> str:
        import anthropic as _anthropic

        system = self.system_prompt
        if topic_info:
            system += f"\n\n[Context: The tutoring session is about '{topic_info.get('topic_name', 'a topic')}' for grade {topic_info.get('grade_level', 5)}]"

        messages = []
        for msg in conversation:
            if msg["role"] == "tutor":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "student":
                messages.append({"role": "assistant", "content": msg["content"]})

        for attempt in range(3):
            try:
                response = self.anthropic_client.messages.create(
                    model=self.config.anthropic_simulator_model,
                    max_tokens=self.config.simulator_max_tokens,
                    system=system,
                    messages=messages,
                )
                for block in response.content:
                    if block.type == "text":
                        return block.text.strip()
                return ""
            except _anthropic.RateLimitError:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    raise
