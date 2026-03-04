"""
Orchestrator Prompts

Prompts used by the orchestrator for welcome messages and session summaries.
"""

from tutor.prompts.templates import PromptTemplate


WELCOME_MESSAGE_PROMPT = PromptTemplate(
    """You are a friendly tutor starting a session with a Grade {grade} student.

Topic: {topic_name}
Subject: {subject}
Learning Objectives:
{learning_objectives}

Student preferences:
- Language Level: {language_level}
- Preferred Examples: {preferred_examples}

Generate a short, warm welcome message that:
1. Greets the student
2. Tells them the topic for today

That's it. Do NOT explain any concepts, do NOT ask any questions, do NOT use analogies or hooks. Just a simple greeting and the topic name.
- GOOD: "Hi Manish! Today we'll be learning about fractions. Let's get started!"
- BAD: "Have you ever tried sharing a pizza?" (no questions)
- BAD: "Think of it like slicing a pizza..." (no explanations or analogies)
- BAD: "Are you ready?" (no questions)

Keep it to 1-2 sentences. Use {language_level} language.
Do not use emojis.

Return JSON with two fields:
- "response": The welcome message. {response_language_instruction}
- "audio_text": The spoken version for TTS. {audio_language_instruction}""",
    name="welcome_message",
)


SESSION_SUMMARY_PROMPT = PromptTemplate(
    """Summarize this tutoring session for context continuity.

Concepts Covered: {concepts_covered}
Examples Used: {examples_used}
Stuck Points: {stuck_points}
Correct Responses: {correct_count}
Incorrect Responses: {incorrect_count}
Misconceptions Detected: {misconceptions}

Provide a brief (2-3 sentence) summary of:
1. What was taught and understood
2. Any challenges encountered
3. Current progress status

Keep it factual and concise.""",
    name="session_summary",
)
