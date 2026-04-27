# Principles: Baatcheet Dialogue Craft

How we author conversational teaching dialogues for Baatcheet — the pre-scripted exchange between Mr. Verma (tutor) and Meera (peer learner) generated at ingestion time.

Pairs with `interactive-teaching.md` (live tutoring), `how-to-explain.md` (variant A explanations), `easy-english.md` (language). Visual chrome inherited from Explain — see `typography.md` §4 and `ux-design.md`. This doc covers content authoring only.

**V2 framing (2026-04-27):** the dialogue is a *designed lesson with disguised structure*, not a free-form conversation about concepts. Surface rules (curiosity gap, examples-before-rules) are necessary but insufficient. Architecture comes first — Part I — then surface rules — Part II — then voice — Part III. See `feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md` for the V2 working doc and `gold-example-fractions-class4.md` for the benchmark.

---

## Part I — Architecture

### 1. Pedagogy and Naturalness

The dialogue's primary job is teaching — discovery rhythm, scaffolded misconception correction, examples-before-rules. Naturalness is a *quality bar*, not a goal: when pedagogy and natural feel conflict, pedagogy wins. But "natural" is what separates Baatcheet from Explain — without it, the dialogue is just Explain-with-question-marks, and the student gains nothing new from the format. Both axes are non-negotiable.

### 2. The Dialogue is a Designed Lesson

The lesson is *engineered*, not transcribed. Before card-writing begins, four things are decided:
- 2-3 documented misconceptions for the topic
- One narrative spine (lived Indian-household situation)
- Concrete materials the student can have in hand
- A macro-structure: hook → activate → introduce-notation → trap-resolve × N → guided-practice → independent-check → close-with-takeaways

The card-by-card prose is a *realization* of this plan. The plan is the load-bearing structure; the surface charm is what makes it land.

### 3. Narrative Spine

One real-life Indian-household situation threads through the entire dialogue. Not a "soft example" — the *spine*. The opening hook plants it, mid-dialogue cards call back to it, the closing card resolves it.

Examples of spines: a fight with a younger sibling over chocolate; counting money from grandma at Diwali; reading the population number on a milestone sign on a road trip; sharing roti at dinner. One spine per dialogue.

Why: a 30-40 card exchange that doesn't reference itself is N disconnected mini-explanations. The spine gives the conversation memory and the student a thread they can hang every concept on.

### 4. Misconceptions Drive the Macro-Structure

Each documented misconception gets *one trap-resolve cycle* of ~6-8 cards:
1. **Trap-set** — tutor poses a hypothetical that invites the wrong belief.
2. **Fall** — Meera voices the misconception (it comes from her mouth, not the tutor's).
3. **Concrete disproof** OR **funnel question** — student does something physical and reports, OR tutor asks one focusing question. Either way, the student feels the contradiction.
4. **Articulate** — *only after the student has done the work*, the tutor names the rule.

The tutor never says "a common mistake is..." Misconceptions are surfaced *through* the conversation, not narrated about it. This is the AutoTutor "expectation- and misconception-tailored" pattern — the highest-leverage move in the gold-standard dialogue, and the move our V1 dialogues most consistently failed.

3 misconceptions × ~7 cards = ~21 cards of trap-resolve. Plus intro (~6 cards), worked example (~3 cards), independent check (~2 cards), close (~2 cards). That's why the card budget is 30-40 (revised from 25-35) — three cycles need the room.

### 5. Move Grammar

Each card does *one specific pedagogical move*. The lesson plan assigns a move to every card before card-writing. The vocabulary:

| Move | What it does |
|---|---|
| `hook` | Open with a lived situation; pose an open question |
| `activate` | Elicit the student's prior knowledge ("have you heard X?", "how would you Y?") |
| `concretize` | Bridge from lived situation to a manipulable artifact (chapati, rupees, paper) |
| `notate` | Introduce the formal symbol/notation after the concept has landed |
| `trap-set` | Hypothetical that invites a misconception |
| `fall` | Peer voices the misconception aloud |
| `student-act` | Tutor instructs student to do something physical; student reports observation |
| `funnel` | One focusing question that lets the student arrive at the rule |
| `articulate` | Tutor names the rule after the student has felt it |
| `escalate` | Extend the rule with an extreme case or analogy |
| `callback` | Reference an earlier moment in the dialogue (spine reuse, prior misconception) |
| `practice-guided` | Worked example, tutor scaffolds while student attempts |
| `practice-independent` | Student applies the rule with no scaffolding |
| `reframe` | Acknowledge the student's emotion (confusion, fatigue) and normalize it |
| `close` | Summarize three takeaways tied to the three misconceptions; callback to opening |

Card types (`tutor_turn` / `peer_turn` / `visual` / `check_in` / `summary`) remain the schema layer; moves are the *pedagogical* layer expressed in the lesson plan and realized through prose. No two consecutive cards do the same move except `trap-set → fall` and `articulate → callback`.

### 6. Student-Does-the-Concrete

At least *two moments* in every dialogue, the tutor instructs the real student (or Meera, who watches) to do something physical: fold a paper, count fingers, draw a line, point to something, hold up two hands. The student reports what they observe. The tutor articulates the rule from the student's observation.

This is the highest-bandwidth disproof move available. A told concept lasts a turn; an observed concept lasts a year. The pure-listening dialogue is the failure mode this rule exists to prevent.

### 7. Threading & Closing Takeaways

**Threading.** The opening hook (the spine) is referenced ≥2 times mid-dialogue and resolved at the close. Character particulars established early (younger sister, friend Aarav, the specific feeling) are reused later. Without threading, the dialogue is N disconnected explanations.

**Closing takeaways.** The final card names *exactly three rules* the student now owns, each mapping to one of the three trap-resolve cycles. Plus a callback to the opening situation ("now you can…"). Generic summaries ("today you learned about fractions") are banned — the close makes the lesson's architecture visible to the student.

---

## Part II — Surface Rules

The architecture above is what makes the dialogue teach. The rules below are how the prose stays clean.

### 8. Same Concepts as Variant A, Free Choreography

Every key concept variant A teaches must appear in the dialogue. Order, examples, opening hook, and pacing are the dialogue's own. Inheriting variant A's card structure produces dialogue-shaped monologue — the very failure mode this principle exists to prevent. Variant A is reference for *what to teach*, not *how to sequence it*.

### 9. Curiosity Gaps Are Sacred

A question and its answer never appear in the same card. Tutor poses → next card pauses or hands to Meera → Meera tries (often wrong, sometimes right) → tutor reveals or scaffolds. The gap is what makes the answer stick.

### 10. Examples Before Rules

State a rule → the very next card applies it concretely is wrong. Apply concretely → the next card names the rule is right. Never two abstract rule cards in a row. The student should see the pattern in action before it gets named. (This is automatic if you follow §4 — the trap-resolve cycle is example-before-rule by construction.)

### 11. Earn the Aha-Moments

Each trap-resolve cycle (§4) IS an earned aha-moment. ≥3 per dialogue (one per misconception). Meera's "wow!" comes after she has worked through it — never as an unearned exclamation.

### 12. Meera Speaks From Reaction, Not Service

Meera doesn't volunteer rehearsal numbers, drop facts to set up the next card, or echo what the tutor just said. She speaks because: she heard a word she doesn't know, she just had a thought, the tutor turned to her, or something just clicked or broke. Real beginners don't supply pivots.

### 13. No Boilerplate Pivots to the Real Student

Banned: ending cards with `{student_name}, your turn now!` — that's a stage direction, not a pivot. Pivots to the real student must be embedded: *"Meera almost had it. {student_name}, can you help her? What's ten times one thousand?"*

---

## Part III — Voice and Character

### 14. Tone Calibration

- **Mr. Verma:** warm, patient, simple words. Treats Meera and the real student kindly. Never patronizing, never babyish. Uses tutor interjections — *"Aha"*, *"Wow"*, *"High five"*, *"Spot on"*, *"Got it"*, *"Let me ask you something"*.
- **Meera:** curious, friendly, not-quite-there-yet. Confident enough to guess aloud — sometimes right, sometimes wrong. Vocabulary slightly simpler than the tutor's. Uses student sounds — *"Hmm"*, *"Umm"*, *"Oh wait"*, *"Ohhh"*, *"Wait!"*. She has a body and a face: she gets excited, gets tired, gets confused.

### 15. Character Particulars

Meera has a life. The lesson plan picks 1-2 particulars at the start (younger sibling, a friend, a pet, a specific emotional reaction) and threads them through the dialogue for character continuity. Generic Meera is forgettable; particular Meera is a person the student remembers.

Particulars must be culturally Indian-everyday and concrete: *"my younger sister always takes more chocolate"*, *"my friend Aarav has a cricket bat"*, *"my dadi keeps ₹100 notes in a tin"*. Never abstract traits ("Meera is curious") — those are vibes, not particulars.

### 16. Emotional Reframing

Acknowledge the student's emotion in the dialogue. *"My head is spinning a little"* → tutor reframes: *"That is okay. Spinning means your brain is growing."* This is a *named move* (§5: `reframe`) and at least one such moment should appear when the dialogue covers a tricky concept. Confusion-as-progress is the growth-mindset frame.

### 17. Process Praise, Not Ability Praise

*"You figured that out."* / *"Brilliant thinking."* / *"You worked hard today."* — never *"You're smart."* Praise the work, not the trait. Dweck's growth mindset language; matches `evaluation.md` §pedagogy.

### 18. Student's World is the Default, Not a Variant

Per `easy-english.md` §8, write from *inside* the student's world — don't write *about* it. Their everyday life (rupees, cricket, chapati, Diwali, lakh/crore, Indian comma grouping, familiar names) is the baseline, not a flavor.

**Never label the student's context as "the Indian way" or compare it to a "Western / American / international" way.** This applies to misconception framing, disproofs, articulated rules, and visualisations. If a concept has a regional variant, teach the student's form as THE form.

- WRONG misconception name: *"Western comma placement carried into Indian system."* RIGHT: *"Comma placement at every 3 digits instead of 3-then-2."*
- WRONG articulate: *"3-2-2 grouping, not the Western 3-3-3."* RIGHT: *"Commas go after 3 digits from the right, then every 2 digits."*
- WRONG visual: side-by-side `1,00,000` vs `100,000` labelled "Indian / Western." RIGHT: just `1,00,000` with chunk borders highlighted.

Exception: keep the comparison only if the teaching guideline itself teaches the comparison. The spine (§3) is the primary real-world anchor; ad-hoc examples should usually reuse the spine rather than introduce new contexts.

---

## Part IV — Length, Schema Compliance, Authoring Test

### 19. Length Discipline

- **30–40 cards total per topic** (revised from 25–35; three trap-resolve cycles need the room).
- 1–3 short lines per card.
- Tutor sentences ≤12 words *per line*. Articulation cards (§5: `articulate`) may use up to 3 lines, but no card exceeds ~40 words total.
- Meera lines ≤10 words. Student-fall and reaction cards may be 2–4 words ("Hmm.", "Two pieces. Same size.").
- Talk-ratio is a heuristic, not a goal. Role variety matters more than balance.
- **Check-ins:** 2-3 per dialogue, ≥10 cards apart. They should not crowd out trap-resolve cycles. The dialogue's natural "tricky question" beats often substitute for explicit check-ins.

### 20. Schema & Personalization Compliance

- `{student_name}` placeholders only inside `lines[].audio` / `lines[].display` on tutor cards addressing the real student. Never on peer turns. Never inside `check_in.*` (those fields are pre-rendered as static audio).
- Audio strings: zero markdown, zero naked `=`, zero emoji. Display may use `**bold**`.
- Card types: `tutor_turn` / `peer_turn` / `visual` / `check_in` / `summary`.
- Schema details and check-in `activity_type` values: see `technical/baatcheet.md` and the dialogue-generation prompt.

### 21. Test: Read As a Student

Before finalizing, read the dialogue as a struggling Indian Grade-N ESL student. Where does the rhythm break? Where does a question not land? Where does Meera flatten into recitation? Where does the tutor lecture instead of elicit? Those are the rewrite targets — for the lesson plan, the generation prompt, the refine prompt, and the manual reviewer.

**Then read it once more, asking only one question:** *would a student who saw the Explain cards yesterday feel they're getting something different here?* If no, the architecture has not landed regardless of how clean the prose is.
