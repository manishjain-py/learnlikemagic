# Principles: Let's Practice

The philosophy behind the batch-drill practice mode.

## 1. Practice ≠ Teaching

No hints, no scaffolding during the set. If a student is struggling, the learning loop sends them back to Teach Me — never into a hybrid teacher-during-drill mode. Practice is where the student honestly sees what they know; learning happens at review time (§4).

## 2. Built for Reps

No timer, repeats allowed, history kept forever. Built for letting students practice again and again and get better by practicing.

## 3. Offline-First Question Bank

Quality comes from pre-generating and reviewing questions at ingestion time, not from runtime generation. Each topic gets a question bank with a correctness review pass.

## 4. Evaluation as Learning

Every wrong answer earns a per-pick explanation at review time — not just "correct answer is X" but "here's why YOUR pick was wrong, given what the question asked." The post-submit review is where learning happens.

## 5. Deterministic Where Possible, LLM Where Necessary

Structured formats grade deterministically — no LLM call, no variance. Only free-form text grading and per-pick "why you were wrong" rationales use the LLM. Keeps grading fast, cheap, and reproducible.

## 6. Half-Point Granularity

Scores round to half-points at write-time (e.g., 7.5 / 10). Half-points balance signal and simplicity.

## 7. Snapshot Isolation Protects History

Each attempt snapshots the selected questions at creation. Rendering, grading, and review all read from the snapshot — never from the live bank. Regenerating a topic's bank doesn't orphan or mutate past attempts.

## 8. One-Tap Submit, Background Grading

Submit is a single tap from the review screen — no confirmation dialog. Grading runs asynchronously in the background; the student is free to start another activity immediately.

## 9. Format Variety per Set

Each set uses multiple question formats. Variety keeps the drill from feeling rote.

## 10. Static Questions, No Personalization

Questions are pre-generated once per topic and shared across all students. Runtime personalization would require per-student generation, which doesn't justify the cost.

## 11. Fresh Random Sample per Attempt

Each attempt draws a fresh random sample from the bank, so repeat attempts present different question combinations.

---

*Reviewed by Manish on date: 2026-05-27*
