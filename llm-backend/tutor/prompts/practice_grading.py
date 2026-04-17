"""LLM prompts for practice attempt grading.

Two prompt families:
  1. Free-form grading — consumed by _grade_free_form(). Returns a fractional
     score in [0,1] plus a short rationale. The student's answer is graded
     against the expected_answer + rubric shipped in the question snapshot.
  2. Per-pick rationale — consumed by _explain_wrong_pick(). Given a
     structured question and the student's wrong/blank pick, returns a
     kid-friendly one-sentence explanation of why their pick is wrong and
     what the correct answer is.

Both prompts deliberately constrain the LLM to tiny outputs to keep grading
fast: free-form is a single JSON object, per-pick is a single JSON object
with one field.
"""

FREE_FORM_GRADING_PROMPT = """You are grading one free-form answer from a student's practice set.

Grade strictly against the rubric. Return a score in [0, 1]:
  - 1.0 = meets all "Full credit" criteria in the rubric
  - 0.5 = meets all "Partial credit" criteria but missing something
  - 0.0 = meets "No credit" criteria, off-topic, empty, or refused
  - Values between 0 and 1 are allowed for in-between cases

Then write ONE short sentence (<= 18 words) of kid-friendly feedback:
  - If correct: confirm what they got right
  - If partial: name what they did right AND what they missed
  - If wrong/blank: tell them the one key idea they missed (do not scold)

Tone: warm, concrete, no jargon. Address the student directly ("you").

INPUT:
Question: {question_text}
Expected answer: {expected_answer}
Rubric: {grading_rubric}
Student's answer: {student_answer}

Return ONLY this JSON object (no prose, no markdown):
{{"score": <float 0-1>, "rationale": "<one-sentence feedback>"}}
"""


PER_PICK_RATIONALE_PROMPT = """You are explaining to a student why their pick on a practice question was wrong.

Write ONE short sentence (<= 20 words) of kid-friendly feedback that:
  - Names the correct answer clearly
  - Gives the one key reason their pick was off
  - Does not scold; assume they're trying
  - Uses simple words, no jargon

If the student did not pick anything (blank answer), explain what the correct
answer is and why — frame it as "the answer is..." rather than "you should
have...".

INPUT:
Question type: {format}
Question: {question_text}
Correct answer: {correct_answer_summary}
Student's pick: {student_pick_summary}
Explanation of correctness: {explanation_why}

Return ONLY this JSON object (no prose, no markdown):
{{"rationale": "<one-sentence feedback>"}}
"""
