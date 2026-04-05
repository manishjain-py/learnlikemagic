"""
Exam Mode Prompts

Prompts for exam question generation and evaluation.
"""

from tutor.prompts.templates import PromptTemplate


EXAM_QUESTION_GENERATION_PROMPT = PromptTemplate(
    """You are designing a short, fun exam for a Grade {grade} student on: {topic_name}

Your goal: create an exam that feels fair and rewarding. The student should finish
thinking "I know this stuff!" — not "that was confusing." Even hard questions should
feel solvable with careful thinking.

## Context

Learning Objectives:
{learning_objectives}

Key Concepts:
{concepts}

Curriculum Scope:
{curriculum_scope}

Common Misconceptions (use these to craft smart distractors and error-spotting questions):
{common_misconceptions}

## Question Design Rules

1. **Start easy, build up.** The first 1-2 questions should be confidence builders
   that most students who studied can answer. End with 1-2 stretch questions.
2. **Every question must feel different.** Vary the format — don't just ask
   "What is X?" seven times. Mix these styles:
   - A real-world scenario ("You have 3 bags of marbles with 24 in each...")
   - An error-spotting question ("Priya says 0.5 > 0.45 because 5 > 45. Is she right?")
   - A comparison or ordering question ("Which is greater: A or B? Why?")
   - A reasoning question ("Why does this rule work?" or "Explain in your own words")
   - A procedural/calculation question (straightforward solve)
   - A reverse/puzzle question ("I'm thinking of a number. When I multiply by 3...")
3. **Use relatable contexts.** Mention things a Grade {grade} student cares about —
   games, food, sports, friends, festivals, school events, animals, shopping.
   Use Indian names (Aarav, Diya, Kabir, Meera, etc.) and contexts where appropriate.
4. **Be clear and unambiguous.** Each question should have one correct answer
   (or a clearly defined correct approach). No trick questions. The student is Indian —
   English is NOT their first language. Use only simple, everyday words in question text.
   No idioms, no phrasal verbs, no complex grammar. Sentences under 12 words.
5. **Test understanding, not memorization.** Prefer questions that show whether
   the student truly gets the concept, not just whether they memorized a formula.

## Output

Generate exactly {num_questions} questions, ordered from easiest to hardest.

Difficulty distribution:
- ~30% easy (confidence builders — recall, basic understanding)
- ~50% medium (application, comparison, real-world scenarios)
- ~20% hard (multi-step reasoning, error analysis, stretch problems)

For each question provide:
1. question_text — clear, age-appropriate language
2. expected_answer — the correct answer (concise but complete)
3. concept — which concept this tests
4. difficulty — easy, medium, or hard
5. question_type — one of: conceptual, procedural, application, real_world, error_spotting, reasoning

{personalization_section}""",
    name="exam_question_generation",
)


