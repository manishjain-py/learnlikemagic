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

Generate a warm, engaging welcome message that:
1. Greets the student warmly
2. Introduces the topic in an exciting way
3. Gives a brief preview of what they'll learn
4. Asks if they're ready to begin

Keep it concise (2-3 sentences). Use {language_level} language.
Do not use emojis.""",
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
