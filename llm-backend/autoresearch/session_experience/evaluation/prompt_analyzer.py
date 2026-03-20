"""
Prompt Analyzer — Root Cause Tracing

Takes flagged messages from the experience evaluator + the master tutor prompt
that generated those messages → identifies which specific prompt instructions
or rules are causing the naturalness issues.

This is the key differentiator from the existing pipeline: it connects
symptoms (bad messages) to causes (prompt instructions).
"""

import json

from autoresearch.session_experience.evaluation.config import SessionExperienceConfig


PROMPT_ANALYZER_PROMPT = """You are an expert prompt engineer analyzing why an AI tutor produced unnatural messages during a teaching session.

You will receive:
1. A list of FLAGGED MESSAGES — specific tutor messages identified as unnatural
2. The MASTER TUTOR PROMPT — the exact system prompt + turn prompt that was used to generate those messages

Your job: trace each flagged message back to the specific prompt instruction(s) that caused it. The goal is to identify what to CHANGE in the prompt to fix these issues.

## HOW TO ANALYZE

For each flagged message:
1. Read the flagged message and its description
2. Read the master tutor prompt carefully
3. Find the specific rule, instruction, or section that CAUSED the issue:
   - Maybe a rule is too aggressive (e.g., "always ask a question" → forces questions even when natural response would be a statement)
   - Maybe rules conflict (e.g., "ACCELERATE" directive + "check understanding" → tutor rushes through checks)
   - Maybe a rule is missing (e.g., no instruction on how to handle vague "ok" responses)
   - Maybe the tone/language in the prompt bleeds into the response
   - Maybe the pacing directive is inappropriate for the student's current state
   - Maybe the card summary section doesn't give enough context to build on

## OUTPUT FORMAT (JSON)

Return a JSON object:
{{
  "analyses": [
    {{
      "turn": <turn number of flagged message>,
      "issue_category": "<from the flagged message>",
      "root_instructions": [
        {{
          "instruction": "<quote or paraphrase the specific prompt instruction causing this>",
          "location": "<where in the prompt: e.g. 'Rule 9: Calibrate praise', 'pacing directive: ACCELERATE', 'precomputed_explanation_summary_section'>",
          "mechanism": "<1 sentence: HOW this instruction caused the problem>"
        }}
      ],
      "suggested_fix": "<1-2 sentences: what to change in the prompt to fix this>",
      "target_file": "<which file to modify: master_tutor_prompts.py, master_tutor.py, or session_service.py>",
      "fix_type": "modify_rule|add_rule|remove_rule|reword|restructure"
    }}
  ],
  "cross_cutting_patterns": [
    {{
      "pattern": "<a pattern that appears across multiple flagged messages>",
      "root_cause": "<the underlying prompt issue driving this pattern>",
      "fix_priority": "high|medium|low"
    }}
  ],
  "top_recommendation": "<THE single most impactful change to make, in 2-3 sentences>"
}}

RULES:
- Be SPECIFIC about which instruction/rule causes the issue — don't just say "prompt quality"
- Quote or closely paraphrase the actual prompt text when citing root instructions
- Focus on actionable fixes, not vague suggestions
- If multiple instructions interact to cause a problem, list all of them
- The suggested_fix should be concrete enough that someone can implement it directly"""


class PromptAnalyzer:
    """Traces naturalness issues to specific prompt instructions."""

    def __init__(self, config: SessionExperienceConfig):
        self.config = config
        self.llm = config.create_llm_service("analyzer")

    def _build_user_message(
        self,
        flagged_messages: list[dict],
        conversation: list[dict],
        master_tutor_prompts: list[dict],
    ) -> str:
        parts = []

        # Section 1: Flagged messages
        parts.append("## FLAGGED MESSAGES\n")
        parts.append("These tutor messages were identified as unnatural:\n")
        for flag in flagged_messages:
            turn = flag.get("turn", "?")
            category = flag.get("issue_category", "unknown")
            desc = flag.get("description", "")
            snippet = flag.get("message_snippet", "")
            severity = flag.get("severity", "?")
            context = flag.get("surrounding_context", "")

            parts.append(f"### Turn {turn} [{severity.upper()}] — {category}")
            parts.append(f"Message: \"{snippet}\"")
            parts.append(f"Issue: {desc}")
            if context:
                parts.append(f"Context: {context}")
            parts.append("")

            # Find surrounding conversation context (2 messages before and after)
            turn_msgs = []
            for i, msg in enumerate(conversation):
                if msg.get("turn") == turn or (isinstance(turn, int) and msg.get("turn") in range(max(0, turn - 2), turn + 3)):
                    role = msg.get("role", "?").upper()
                    turn_msgs.append(f"  [{msg.get('turn', '?')}] {role}: {msg['content'][:200]}")
            if turn_msgs:
                parts.append("Conversation context:")
                parts.extend(turn_msgs)
                parts.append("")

        # Section 2: Master tutor prompts used during the session
        parts.append("\n## MASTER TUTOR PROMPTS\n")
        parts.append("These are the actual prompts sent to the LLM to generate the tutor's responses.\n")

        # Group prompts, showing the ones for flagged turns
        flagged_turns = {f.get("turn") for f in flagged_messages}
        shown_system = False

        for prompt_entry in master_tutor_prompts:
            turn = prompt_entry.get("turn")
            prompt_text = prompt_entry.get("prompt", "")

            if turn in flagged_turns:
                parts.append(f"### Prompt for Turn {turn} (FLAGGED)")
                parts.append(f"```\n{prompt_text}\n```")
                parts.append("")
            elif not shown_system and prompt_text:
                # Show the system prompt once (from the first available turn)
                parts.append(f"### System Prompt (from Turn {turn})")
                # Extract just the system portion (before the turn-specific part)
                if "CURRENT SESSION STATE" in prompt_text:
                    system_part = prompt_text[:prompt_text.index("CURRENT SESSION STATE")]
                    parts.append(f"```\n{system_part}\n```")
                else:
                    parts.append(f"```\n{prompt_text[:3000]}\n```")
                parts.append("")
                shown_system = True

        parts.append("\nAnalyze these flagged messages against the prompts. Return JSON.")
        return "\n".join(parts)

    def analyze(
        self,
        flagged_messages: list[dict],
        conversation: list[dict],
        master_tutor_prompts: list[dict],
    ) -> dict:
        """Trace flagged messages to prompt instructions.

        Args:
            flagged_messages: Output from ExperienceEvaluator.evaluate()["flagged_messages"]
            conversation: Full conversation transcript
            master_tutor_prompts: List of {turn, prompt} dicts captured during session
        """
        if not flagged_messages:
            return {
                "analyses": [],
                "cross_cutting_patterns": [],
                "top_recommendation": "No issues flagged — conversation appears natural.",
            }

        system_prompt = PROMPT_ANALYZER_PROMPT
        user_message = self._build_user_message(flagged_messages, conversation, master_tutor_prompts)
        prompt = f"{system_prompt}\n\n{user_message}"

        result = self.llm.call(prompt=prompt, reasoning_effort="high", json_mode=True)
        parsed = result.get("parsed") or self.llm.parse_json_response(result["output_text"])
        return parsed
