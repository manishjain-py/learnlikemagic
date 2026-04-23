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

Then write 2-3 short sentences of kid-friendly feedback, in this order:
  1. Confirm what they got right warmly — or if fully wrong, state the correct idea clearly.
  2. Name the specific gap THIS student's answer shows — diagnose what they actually missed, not a generic reason.
  3. Give ONE concrete anchor — a small example, a re-framing, or a memorable tip that helps them see it next time.

Rules:
  - Do not scold; assume they're trying.
  - Focus on ONE key gap. Do not pile on multiple fixes.
  - Hard limit: 60 words total, 3 sentences maximum.
  - Tone: warm, concrete, no jargon. Address the student directly ("you").
  - Student is Indian, English is their second language. Each sentence under 12 words. No idioms, no phrasal verbs, no complex grammar. Use everyday Indian life (rupees, cricket, chapati, Indian names) as the default — never label it as "the Indian way" or compare to "Western."

INPUT:
Question: {question_text}
Expected answer: {expected_answer}
Rubric: {grading_rubric}
Student's answer: {student_answer}

Return ONLY this JSON object (no prose, no markdown):
{{"score": <float 0-1>, "rationale": "<2-3 short sentences>"}}
"""


PER_PICK_RATIONALE_PROMPT = """You are explaining to a student why their pick on a practice question was wrong.

Write 2-3 short sentences of kid-friendly feedback, in this order:
  1. Name the correct answer clearly, warmly.
  2. Name the specific error THIS student's pick reveals — look at what they actually picked and diagnose the misconception behind it. Do not give a generic reason.
  3. Give ONE concrete anchor — a small example, a re-framing, or a memorable tip that helps them see it next time.

Rules:
  - Do not scold; assume they're trying.
  - Focus on ONE key misconception. Do not pile on multiple fixes.
  - Hard limit: 60 words total, 3 sentences maximum.
  - Student is Indian, English is their second language. Each sentence under 12 words. No idioms, no phrasal verbs, no complex grammar. Use everyday Indian life (rupees, cricket, chapati, Indian names) as the default — never label it as "the Indian way" or compare to "Western."

If the student did not pick anything (blank answer), still use the 3 sentences:
state the correct answer, explain why it is the answer, give one anchor. Frame
it as "the answer is..." rather than "you should have...".

INPUT:
Question type: {format}
Question: {question_text}
Correct answer: {correct_answer_summary}
Student's pick: {student_pick_summary}
Explanation of correctness: {explanation_why}

Return ONLY this JSON object (no prose, no markdown):
{{"rationale": "<2-3 short sentences>"}}
"""
