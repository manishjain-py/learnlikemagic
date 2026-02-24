"""
Student Simulator

Uses OpenAI Chat Completions API (gpt-4o) or Anthropic Messages API
to simulate a student responding to a tutor during a tutoring session.

Key design: correct_answer_probability is ENFORCED programmatically via
a random roll each turn, not left as a soft instruction to the LLM.
The LLM receives explicit per-turn instructions: "THIS TURN you MUST
answer incorrectly" or "THIS TURN you should answer correctly."
"""

import logging
import random
import time
from openai import OpenAI, RateLimitError

from evaluation.config import EvalConfig

logger = logging.getLogger(__name__)


class StudentSimulator:
    """Simulates a student using an LLM to generate realistic responses."""

    def __init__(self, config: EvalConfig, persona: dict):
        self.config = config
        self.persona = persona
        self.provider = config.simulator_provider
        self.correct_prob = persona.get("correct_answer_probability", 0.6)
        self.system_prompt = self._build_system_prompt()
        self.turn_count = 0
        # Track dice decisions for logging/debugging
        self.turn_decisions: list[dict] = []

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

        # Add persona-specific behaviors if present
        persona_behaviors = ""
        if "persona_specific_behaviors" in p:
            behaviors = []
            for behavior, probability in p["persona_specific_behaviors"].items():
                behavior_desc = behavior.replace("_", " ").replace("probability", "").strip()
                behaviors.append(f"- {behavior_desc}: about {int(probability * 100)}% of the time")
            if behaviors:
                persona_behaviors = f"\n\nPERSONA-SPECIFIC BEHAVIORAL TENDENCIES:\n" + "\n".join(behaviors)

        return f"""You are roleplaying as {p['name']}, a {p['age']}-year-old grade {p['grade']} student in a tutoring session.

PERSONALITY:
{traits}

COMMON MISTAKES you make (use these when you answer incorrectly):
{mistakes}

YOUR RESPONSE STYLE:
- Keep responses under {p['response_style']['max_words']} words
- Use {p['response_style']['language']}
- You are a real student, not a chatbot. Sound natural.

EXAMPLE RESPONSES (for tone reference — adapt to whatever topic is being taught):
{examples}

BEHAVIORAL GUIDELINES:
{behavioral}{persona_behaviors}

NATURAL VARIATION INSTRUCTION:
Remember: you are a TENDENCY, not a script. Even though you have these personality traits and behaviors, you don't express them every single turn. Some turns you're more like your described personality, some turns less. Be naturally variable like a real person.

CRITICAL RULES:
1. Each turn, you will receive a [TURN DIRECTIVE] telling you whether to answer correctly or incorrectly this turn. YOU MUST FOLLOW IT EXACTLY.
2. When the directive says ANSWER INCORRECTLY: pick a mistake from your common mistakes list and give a WRONG answer. Make a SPECIFIC, CONCRETE wrong answer. Do NOT hedge, do NOT self-correct, do NOT say "wait actually..." — commit fully to your wrong answer.
3. When the directive says ANSWER CORRECTLY: give the right answer in your persona's style.
4. If the tutor isn't asking a question (just explaining), respond naturally in character — the directive only applies to questions with answers.
5. Never break character. You are {p['name']}, a {p['age']}-year-old.
6. Keep responses SHORT — a real kid doesn't write paragraphs.
7. React naturally: show confusion, excitement, boredom, curiosity.
8. Don't repeat what the tutor said back to them word for word."""

    def _should_answer_correctly(self) -> bool:
        """Programmatically decide if this turn should be correct.
        
        Pure random roll against the persona's correct_answer_probability.
        The law of large numbers handles convergence over multiple turns.
        """
        return random.random() < self.correct_prob

    def _get_turn_directive(self, should_be_correct: bool) -> str:
        """Generate the per-turn directive injected into the conversation."""
        p = self.persona
        mistakes = p.get("common_mistakes", [])
        
        if should_be_correct:
            return "[TURN DIRECTIVE: This turn, if the tutor asks you a question, ANSWER CORRECTLY. Give the right answer in your natural style.]"
        else:
            mistake_hint = ""
            if mistakes:
                chosen_mistake = random.choice(mistakes)
                mistake_hint = f" Apply this type of mistake: '{chosen_mistake}'."
            
            return (
                f"[TURN DIRECTIVE: This turn, if the tutor asks you a question, you MUST ANSWER INCORRECTLY. "
                f"Give a WRONG answer — make a specific concrete error, not a vague one.{mistake_hint} "
                f"Say your wrong answer naturally as your character would. "
                f"Do NOT self-correct in the same response. Do NOT say 'wait actually' or reveal the correct answer. "
                f"Commit fully to the wrong answer.]"
            )

    def generate_response(self, conversation: list[dict], topic_info: dict | None = None) -> str:
        """Generate a student response given the conversation so far."""
        self.turn_count += 1
        
        # Determine if this turn should be correct or incorrect
        should_be_correct = self._should_answer_correctly()
        directive = self._get_turn_directive(should_be_correct)
        
        # Log the decision
        decision = {
            "turn": self.turn_count,
            "directive": "CORRECT" if should_be_correct else "INCORRECT",
            "probability": self.correct_prob,
        }
        self.turn_decisions.append(decision)
        logger.info(
            f"[Turn {self.turn_count}] Dice roll: {decision['directive']} "
            f"(target_prob={self.correct_prob})"
        )
        
        if self.provider == "anthropic":
            response = self._generate_anthropic(conversation, topic_info, directive)
        else:
            response = self._generate_openai(conversation, topic_info, directive)
            
        return response

    def _generate_openai(self, conversation: list[dict], topic_info: dict | None = None, directive: str = "") -> str:
        messages = [{"role": "system", "content": self.system_prompt}]

        if topic_info:
            context = f"[Context: The tutoring session is about '{topic_info.get('topic_name', 'a topic')}' for grade {topic_info.get('grade_level', 5)}]"
            messages.append({"role": "system", "content": context})

        for msg in conversation:
            if msg["role"] == "tutor":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "student":
                messages.append({"role": "assistant", "content": msg["content"]})

        # Inject the turn directive as the last system message (close to generation)
        if directive:
            messages.append({"role": "system", "content": directive})

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.simulator_model,
                    messages=messages,
                    temperature=self.config.simulator_temperature,
                    max_completion_tokens=self.config.simulator_max_tokens,
                )
                return response.choices[0].message.content.strip()
            except RateLimitError:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    raise

    def _generate_anthropic(self, conversation: list[dict], topic_info: dict | None = None, directive: str = "") -> str:
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

        # Inject directive as the last user message so it's close to generation
        # This is more effective than burying it in the system prompt for Claude
        if directive:
            # If the last message is from the tutor (user role), append directive to it
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += f"\n\n{directive}"
            else:
                messages.append({"role": "user", "content": directive})

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
