---
date: 2026-04-09
status: proposal
audience: product, engineering, pedagogy
related_mode: Let's Practice (in PRD/impl)
---

# Top 2 Improvements: Worked Example Progression + Interleaved Practice

Both land inside the upcoming **Let's Practice** mode, both are backed by 30+ years of learning science, neither overlaps the 14 ideas already explored (spaced repetition, affective detection, gamification, interest weaving, visual manipulatives, narrative quests, study circles, snap-solve, parent dashboard, revision planner, metacognitive coaching, voice, teach-the-tutor, productive struggle guards).

---

## Context — What We Already Do Well, What's Missing

**Strong today:**
- Pre-computed explanation cards (concept-level, radical simplicity, Indian ESL-safe)
- Master tutor with mastery tracking per concept + scaffolded correction (probe → hint → explain)
- Mode separation: Teach Me (absorb) vs Let's Practice (reinforce, soon shipping)

**The gap:**
Let's Practice will launch students into **independent problem solving** from turn 1. For a grade 5 Indian ESL kid who just read the explanation cards, this is a cognitive cliff — they must parse English, recall the concept, pick a strategy, and execute the procedure in parallel. Most will fail the first problem, triggering the scaffolded-correction ladder. That ladder is reactive repair, not proactive scaffolding.

Also: every session is **one topic at a time, blocked**. Student does fractions, then does fractions again, then does fractions again. Feels good in the moment. Exam hits them with mixed topics. Collapse.

Both gaps are solvable with well-studied pedagogical moves the app does not yet have.

---

## Idea #1 — Worked Example Progression + Self-Explanation

### The move
Open every new practice set with a **fully worked example**, then a **partially worked** one, then a **mostly blank** one, then **independent**. At each step, ask the student to **explain in their own words why a step works** before proceeding. Classic "faded guidance" + "self-explanation" pairing.

### What a session looks like
```
Turn 1  [Tutor]  Here's how I solve this. Watch first.
                 Problem: 1/4 + 2/4 = ?
                 Step 1: Denominators same (both 4). Keep it.
                 Step 2: Add the tops: 1 + 2 = 3.
                 Step 3: Answer = 3/4.
                 
                 Quick check — in your own words, why do we
                 keep the bottom number the same? (1 line ok)

Turn 2  [Student] because the bottom is the size of the piece

Turn 3  [Tutor]  Yes — the size of each piece doesn't change
                 when we add. You got it.
                 
                 Now you try step 3 only. I'll do the rest.
                 Problem: 2/5 + 1/5
                 Step 1: Bottoms same (5). ✓
                 Step 2: Tops: 2 + 1 = 3. ✓
                 Step 3: Answer = ?

Turn 4  [Student] 3/5

Turn 5  [Tutor]  Perfect. Now one more where you do it all.
                 Problem: 3/7 + 2/7 = ?
```

Student climbs the fade: worked → one-step → full. Explains why at each level. By the time they hit independent, they have the procedure AND the justification in memory.

### Why this helps *our specific audience*
Cognitive Load Theory (Sweller, 1988 → present day) says novices learn faster from studying worked examples than from solving problems, because problem solving consumes working-memory for search instead of schema building. For an Indian ESL kid the load is **doubled** — English parsing competes with the math itself. Worked examples strip the search step and let the schema form.

Self-explanation doubles the effect: instead of passively reading the worked steps (which many kids do), the "why does this step work" prompt forces active processing. Meta-analysis of 64 studies finds g = 0.55 for self-explanation; math-specific studies hit effect sizes ~0.83.

### Why this is *new* vs what we have
- **Explanation cards** explain the *concept* ("a fraction is a part of a whole"). They do **not** demonstrate *solving a problem step by step*. Different thing.
- **Scaffolded correction** (probe → hint → explain) kicks in *after* a wrong answer. Worked examples are *before*. Proactive, not reactive.
- **Check-ins** (pick_one, fill_blank, etc.) test *recognition* of facts. Worked examples build *procedural fluency*.

### Fit with Let's Practice PRD
The current PRD has Let's Practice launching directly into questions. This proposal inserts a **"warm-up ladder"** at the start (1 worked → 1 faded → 1 independent) per concept, then resumes the existing mastery-based question flow. Pure additive change — the mastery engine, pause/resume, prerequisite detection all stay the same.

### Implementation sketch
- New response type: `worked_example` with structured `steps: [{action, reason, why_prompt}]`
- Prompt variant: tutor agent gets a `phase=warmup_ladder` flag → outputs worked example + self-explanation prompt instead of independent question
- State: `warmup_ladder_complete: bool` per concept in session state; once true, normal question flow starts
- Fallback: if student nails the first self-explanation perfectly on step 1, skip to independent (don't bore stronger students)
- No new infra, no new DB tables, no LLM chain changes. One extra tutor turn type + one state flag.

### Expected impact
- **Lower fail rate on first independent question** (kids arrive with schema, not from-scratch)
- **Higher retention of procedural reasoning** (why, not just what)
- **Fewer scaffolded-correction escalations** (less reactive repair because less failure)
- **Especially large lift for weaker / younger / ESL students** who currently hit the cognitive cliff hardest

---

## Idea #2 — Interleaved Practice Engine

### The move
Within a practice session, **mix problem types** instead of blocking. Across sessions, offer a **"Mixed Review"** mode that pulls questions from the student's last 2–3 topics and interleaves them.

### Two flavors

**A) Within-topic interleaving.** Fractions has ~5 sub-types: same-denominator add, same-denominator subtract, mixed-number, compare, simplify. Current design would do these in a block (5 adds in a row, then 5 subtracts). Interleaved: add, subtract, compare, add, simplify, mixed-number, compare, add… Student must recognize *which* rule applies each time, not apply the same rule 5x in a row.

**B) Cross-topic interleaving.** New session mode: **"Mixed Review"**. Picks 8–12 questions from the student's last 2–3 mastered topics and shuffles them. Fractions + area + percentages, all in one session. Student has to cold-recall the right approach for each problem.

### Why it's so powerful
Rohrer & Taylor's classic study: students practicing interleaved volume formulas scored **72% vs 38%** on the delayed test, despite feeling like they were doing worse during practice. Bjork calls this a **desirable difficulty** — it *feels* harder, the learning is *deeper*.

The reason: blocked practice hides the **"which technique do I use?"** decision. The context tells you. When you do 10 fraction-adds in a row, you never practice *recognizing* that this is an add problem — you just execute. On the exam, when problems are jumbled, the recognition skill is missing.

### Why this matters for Indian board exams
**Board exams are interleaved by design.** The CBSE Class 10 math paper mixes algebra, geometry, trig, statistics on the same sheet. A student who practiced only in blocks can execute each skill but freezes on "wait, which one is this?" Interleaved practice *is* exam prep in its purest form.

### Why this is *new* vs what we have
- **Spaced repetition** (idea #1 from March 18) is *when* to review — days/weeks between sessions. Interleaving is *how* to sequence within a session. Orthogonal. Both can ship; they multiply.
- **Smart Revision Planner** (April 5) generates a day-by-day schedule. It does not say anything about how problems are ordered *inside* a practice set.
- **Current Let's Practice PRD** is single-topic, blocked. This proposal adds a sequencing layer on top of the question generator.

### Implementation sketch

**Within-topic interleaving** (small):
- Tag each generated/retrieved question with a `subtype` (e.g., `fractions.add_same_denom`, `fractions.compare`)
- Question generator samples across subtypes instead of sampling one subtype to exhaustion
- Constraint: each subtype must appear at least once before any subtype appears 3x
- No new infra. One change in the question sampling loop.

**Cross-topic "Mixed Review" mode** (medium):
- New mode card on the home screen: "Mixed Review — last 3 topics"
- Eligibility: student has hit ≥70% mastery on ≥2 topics in the last 14 days
- Question pool: draw from those topics' existing question banks, interleave
- Mastery tracking: updates across all source topics' mastery scores simultaneously
- New UX: when a new topic's question appears, the card header shows "Now from: Fractions" so the student knows the domain shifted (prevents disorientation — critical for ESL kids)
- Reuses mastery engine, reuses question bank, reuses Let's Practice turn flow. Mostly a new mode router + sampling strategy.

### Expected impact
- **10–20% lift on delayed retention tests** (well-replicated in math-specific studies)
- **Direct exam-prep signal** — Mixed Review matches actual board-exam format
- **Differentiator vs every Indian competitor** — iBookGPT, Abhyas AI, AINA, Khanmigo all do blocked practice today
- **Cheap to ship** — sampling strategy change, not a new agent or pipeline

---

## Why These Two Together

| | Worked Example Progression | Interleaved Practice |
|---|---|---|
| **Phase of learning** | Early (first exposure to solving) | Middle → Late (consolidation) |
| **Mechanism** | Reduces cognitive load, builds schemas | Forces discrimination, builds transfer |
| **Best for** | Novices, ESL, weaker students | Strong learners, exam prep |
| **Feels** | Easier than current flow | Harder than current flow |
| **Learns** | More, faster | More, deeper |

They cover different ends of the mastery curve. **Worked examples** help students *get off the ground* on a new topic; **interleaved practice** helps students *not forget it* and *transfer it*. Ship both and the Let's Practice mode covers novice-to-exam-ready in one coherent loop.

Neither requires new infra. Both drop into the Let's Practice mode that's already in implementation. Both are the kind of move that a learning-science PhD would immediately recognize and ask "why weren't you doing this already?"

---

## Sources

- [Rohrer & Taylor — Interleaved Practice Improves Mathematics Learning (ERIC)](https://files.eric.ed.gov/fulltext/ED557355.pdf)
- [Bisra et al. — Inducing Self-Explanation: Meta-Analysis (Ed. Psych. Review, g=0.55)](https://link.springer.com/article/10.1007/s10648-018-9434-x)
- [Worked example effect on learning solution steps and transfer (Taylor & Francis)](https://www.tandfonline.com/doi/full/10.1080/01443410.2023.2273762)
- [Effects of Self-Explanation Prompts and Fading Worked-Out Examples (Atkinson et al., mr barton maths)](https://mrbartonmaths.com/resourcesnew/8.%20Research/Making%20the%20most%20of%20examples/Fading%20out%20and%20Prompts.pdf)
- [Interleaving beyond superficially similar problems (PubMed)](https://pubmed.ncbi.nlm.nih.gov/24578089/)
- [What research says about spiral review in math (NWEA, 2025)](https://www.nwea.org/blog/2025/what-does-research-say-about-spiral-review-in-mathematics/)
- [Khanmigo review 2026 — Socratic, but topic-blocked (kidsaitools)](https://www.kidsaitools.com/en/articles/khanmigo-review-parents-complete-2026)
- [Managing cognitive load with AI in education (Faculty Focus)](https://www.facultyfocus.com/articles/effective-teaching-strategies/managing-the-load-ai-and-cognitive-load-in-education/)
