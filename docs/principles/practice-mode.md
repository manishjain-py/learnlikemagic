# Principles: Let's Practice

The philosophy behind the batch-drill practice mode. Replaces the old Exam and tutor-in-the-loop Practice designs.

## 1. Practice ≠ Teaching

No hints, no scaffolding, no tutor-in-the-loop during the set. If a student is struggling on a concept, the learning loop sends them back to Teach Me via the Reteach button — never into a hybrid teacher-during-drill mode. Practice is where the student honestly sees what they know.

## 2. Low Stakes by Default

Warm name ("Let's Practice"), no timer, repeats allowed, history kept forever. Built for reps, not for grading. No "test" framing.

## 3. Offline-First Question Bank

Quality comes from pre-generating and reviewing questions at ingestion time, not from runtime generation. Each topic gets 30–40 questions with a correctness review pass. If a topic has no bank, the tile is greyed out — no on-demand generation.

## 4. Evaluation as Learning

Every wrong answer earns a per-pick explanation at review time — not just "correct answer is X" but "here's why YOUR pick was wrong, given what the question asked." The post-submit review is where learning happens.

## 5. Deterministic Where Possible, LLM Where Necessary

Structured formats (pick_one, true_false, match_pairs, etc.) grade deterministically — no LLM call, no variance. Only free-form text grading and per-pick "why you were wrong" rationales use the LLM. Keeps grading fast, cheap, and reproducible.

## 6. Half-Point Granularity

Scores round to half-points at write-time (e.g., 7.5 / 10). Whole-number partial credit is too coarse for free-form; full fractional is too noisy. Half-points balance signal and readability.

## 7. Snapshot Isolation Protects History

Each attempt snapshots the 10 selected questions into its own row at creation. Rendering, grading, and review all read from the snapshot — never from the live bank. Regenerating a topic's bank doesn't orphan or mutate past attempts.

## 8. One-Tap Submit, Background Grading

Submit is a single tap from the review screen — no confirmation dialog. Grading runs in the background in a daemon thread; the student is free to start another activity immediately. A banner surfaces the results when ready.

## 9. Format Variety per Set

Each 10-question set MUST use at least 4 different formats and no more than 2 consecutive questions of the same format. Free-form questions count toward variety. Variety keeps the drill from feeling rote.

## 10. Static Questions, No Personalization

Questions are the same for every student. No name/interest substitution at runtime. Personalization adds variance that breaks the "did you actually learn this" signal and complicates bank review.
