# Principles: Baatcheet Dialogue Craft

How we author conversational teaching dialogues for Baatcheet — the pre-scripted exchange between Mr. Verma (tutor) and Meera (peer learner) generated at ingestion time.

Pairs with `interactive-teaching.md` (live tutoring), `how-to-explain.md` (variant A explanations), `easy-english.md` (language).

**Visual chrome** (chalkboard surface, top nav, bottom rail, button styling, motion) is inherited from Explain — see `typography.md` §4 and `ux-design.md`. This doc covers content authoring only.

## 1. Pedagogy First

The dialogue's primary job is teaching — discovery rhythm, scaffolded misconception correction, examples-before-rules. Naturalness is a quality bar (the conversation must not read stilted) but never the destination. When pedagogy and natural feel conflict, pedagogy wins.

## 2. Same Concepts as Variant A, Free Choreography

Every key concept variant A teaches must appear in the dialogue. Order, examples, opening hook, and pacing are the dialogue's own. Inheriting variant A's card structure produces dialogue-shaped monologue — the very failure mode this principle exists to prevent.

## 3. Meera Has an Arc

Within each topic, Meera moves: uncertain → wrong attempt(s) → tutor scaffolds → click → confident by summary. Her early questions are basic; her later questions are sharper. The student watches her grow as the teaching lands. "Got it" moments are fine — Meera does not artificially trail the student.

## 4. Curiosity Gaps Are Sacred

A question and its answer never appear in the same card. Tutor poses → next card pauses or hands to Meera → Meera tries (often wrong, sometimes right) → tutor reveals or scaffolds. The gap is what makes the answer stick.

## 5. Examples Before Rules

State a rule → the very next card applies it concretely. Never two abstract rule cards in a row. The student should see the pattern in action before it gets named.

## 6. Earn the Aha-Moments

At least 2 moments per dialogue where tension builds and a reveal lands one or two cards later. Meera's "wow!" must be earned by setup. Unearned wows feel scripted (because they are).

## 7. Meera Speaks From Reaction, Not Service

Meera doesn't volunteer rehearsal numbers, drop facts to set up the next card, or echo what the tutor just said. She speaks because: she heard a word she doesn't know, she just had a thought, the tutor turned to her, or something just clicked or broke. Real beginners don't supply pivots.

## 8. Misconceptions Get Explored, Not Just Corrected

When Meera voices a misconception, the tutor probes ("what made you read it that way?") before correcting, then explains the underlying *why*. Mechanical correction ("say this instead") teaches procedure; explored correction teaches understanding.

## 9. No Boilerplate Pivots to the Real Student

Banned: ending cards with `{student_name}, your turn now!` — that's a stage direction, not a pivot. Pivots to the real student must be embedded in the conversation: *"Meera almost had it. {student_name}, can you help her? What's ten times one thousand?"*

## 10. Soft Real-World Examples

When a culturally-grounded Indian context (cricket scores, festival numbers, school populations, mall prices) makes a concept land naturally, use it. Don't force one when the topic flows better without. Never label India as "the variant" — the student's world IS the world (per `easy-english.md` §8).

## 11. Tone Calibration

- **Mr. Verma:** warm, patient, simple words. Treats Meera and the real student kindly. Never patronizing, never babyish.
- **Meera:** curious, friendly, not-quite-there-yet. Confident enough to guess aloud — sometimes right, sometimes wrong. Vocabulary slightly simpler than the tutor's.

## 12. Length Discipline

- 25–35 cards total per topic (PRD §FR-11).
- 1–3 short lines per card.
- Tutor sentences ≤12 words; Meera ≤10.
- Talk-ratio is a heuristic, not a goal. Role variety matters more than balance.

## 13. Test: Read As a Student

Before finalizing, read the dialogue as a struggling Indian Grade-N ESL student. Where does the rhythm break? Where do you not feel a question land? Where does Meera's voice flatten into recitation? Those are the rewrite targets — for the generation prompt, the refine prompt, and the manual reviewer.
