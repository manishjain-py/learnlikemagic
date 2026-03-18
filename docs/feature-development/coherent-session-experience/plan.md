# Coherent Teach Me Session — Plan

## Problem

Teach Me flow feels like individual pieces glued together, not a single teaching session.

**Current flow:**
1. Hardcoded welcome: "Let's learn about X! I'll walk you through it..." — no name, no curiosity, no expectations
2. Passive card carousel — student reads 5-12 cards with zero interaction, like a textbook
3. Hardcoded transition: "Great! Now let's make sure you've got it. Feel free to ask any questions!" — confusing (who asks questions?)
4. Interactive phase starts — suddenly a different experience with a live tutor asking diagnostic questions
5. Session ends when study plan steps exhausted — no wrap-up, no sense of accomplishment

**Core issue:** no orchestrating narrative. Cards feel like a slideshow glued to a chatbot. Student never feels guided by one tutor through one coherent lesson.

## Specific Gaps

### G1: Cold Start — No Real Welcome
- Welcome is hardcoded, not personalized (`session_service.py:153`)
- Doesn't use student name, doesn't build curiosity, doesn't set expectations
- No session orientation ("here's what we'll cover")
- No prior knowledge check ("have you seen fractions before?")

### G2: Cards Are Passive — Reading, Not Tutoring
- Zero interaction during card phase — no check-ins, no micro-questions
- Student can rush through 10 cards in 20 seconds with no guardrails
- No way to ask "what does this mean?" on a specific card
- Feels like reading, not being taught

### G3: Jarring Transition
- Hardcoded message, no personality
- "Feel free to ask any questions!" contradicts what happens next (tutor asks *them* questions)
- No bridge connecting cards to interactive phase
- No "what confused you?" before moving to checks

### G4: Shallow Explanation Summary
- `_build_precomputed_summary()` only captures: card titles, analogy names, example names
- Missing: HOW analogies were used, key conceptual progressions, specific framings
- Tutor references cards blindly — can say "pizza analogy" but not "remember cutting pizza into 4 slices and eating 1 = 1/4"

### G5: Re-Explanation Bug (Non-Leading Explain Steps)
- `_advance_past_explanation_steps()` only skips consecutive LEADING explain steps
- Study plan: `explain(A) → check(A) → explain(B) → check(B)`
- Cards cover entire topic (A+B). After cards, skips explain(A), lands on check(A). Good.
- After check(A), hits explain(B) — tutor re-explains what cards already covered
- System prompt says "build on cards" but step structure has all building blocks `[TODO]` — system fights itself

### G6: No Prior Knowledge Check
- Never asks what student already knows
- Binary choice: read all cards or skip everything ("I understand!")
- No calibrated response — can't say "I know basics, explain the hard parts"

### G7: No Session Arc
- Missing: orientation → prior check → teach → bridge → verify → practice → wrap-up
- Student doesn't know what's coming or where they are in the lesson
- Study plan is invisible — could be a lesson outline showing progress

### G8: "Two Tutors" Problem
- Card phase: no personality, no warmth, no conversation
- Interactive phase: warm, adaptive, responsive
- Feels like two different products, not one tutor

## Plan

### Phase 1: Warm Welcome + Session Orientation

**What:** Replace hardcoded welcome with LLM-generated personalized welcome, even for card-phase sessions.

**Changes:**
- `session_service.py` — call `orchestrator.generate_welcome_message()` for card-phase sessions too (currently skipped)
- Welcome prompt should include: student name, curiosity hook, brief session outline ("we'll go through X, then I'll check if you've got it"), warm tone
- Welcome appears as first carousel slide BEFORE explanation cards
- Add "session outline" data to response — list of what the session will cover (derived from study plan step concepts)

**Why first:** cold start is the very first impression. Highest impact per effort.

### Phase 2: Richer Explanation Summary

**What:** Give master tutor enough context to reference cards meaningfully, not just analogy names.

**Changes:**
- `explanation_generator_service.py` — generate a `tutor_handoff_summary` per variant during offline generation: 2-3 sentence narrative of what was explained and how (not just titles/labels)
- `summary_json` schema — add `tutor_handoff_summary` field
- `_build_precomputed_summary()` — include handoff summary in what gets injected into system prompt
- Tutor can now say "remember when we showed that cutting pizza into 4 slices..." instead of just "pizza analogy"

**Why second:** enables all downstream improvements. Without this, tutor is blind to card content.

### Phase 3: Fix Non-Leading Explain Step Re-Explanation

**What:** After card phase, mark ALL explain steps as covered (not just leading ones).

**Changes:**
- `_advance_past_explanation_steps()` — iterate ALL steps, mark explain steps as covered in `concepts_covered_set`, but only advance `current_step` past leading ones
- When tutor reaches a non-leading explain step that's already in `concepts_covered_set`, auto-advance past it OR convert to a brief "let me check what you remember about X" turn instead of full re-explanation
- Alternative: add `skip_covered_explain_steps` flag — if precomputed summary exists, tutor skips explain steps whose concepts were in cards

**Design decision needed:** skip silently vs. convert to quick-check? Quick-check is better pedagogically — confirms retention of each concept before practice.

### Phase 4: Bridge Turn — From Cards to Interactive

**What:** Replace hardcoded transition with LLM-generated bridge that references what was just learned.

**Changes:**
- `complete_card_phase()` — instead of hardcoded "Great! Now let's make sure you've got it", generate a bridge message via orchestrator
- Bridge prompt: "Student just read cards about X. Ask what confused them or what stood out. Reference a specific example from the cards. Warm, conversational."
- This becomes the first interactive message — student responds with confusion points or "all good"
- If student flags confusion → tutor addresses it before moving to checks
- If student says all clear → tutor moves to first check with a natural segue

**Why after Phase 2:** needs rich summary to reference card content meaningfully.

### Phase 5: Interactive Card Phase (Future — Larger Change)

**What:** Add micro-interactions during card reading so it feels like tutoring, not reading.

**Options (pick one):**
- **Option A — Check-in cards:** Insert auto-generated "check-in" cards between content cards (e.g., after every 3 cards: "Quick — in your own words, what is a numerator?"). Student types response, tutor evaluates inline.
- **Option B — Chat alongside cards:** Small chat bubble below cards where student can ask questions about current card. Tutor responds in context of the card being viewed.
- **Option C — Card narration:** Tutor "narrates" each card with brief personalized commentary before/after, making it feel conversational even though content is pre-computed.

**Recommendation:** Option C is lowest-effort highest-impact. Tutor generates a 1-sentence personalized intro per card batch ("Let me show you something cool about fractions...") without full LLM calls per card — can be pre-generated.

**Deferred:** this is a larger UX + backend change. Phases 1-4 fix the most painful gaps first.

### Phase 6: Session Wrap-Up

**What:** Add a proper ending instead of session just stopping.

**Changes:**
- When tutor sets `session_complete=true`, add wrap-up directive to prompt: "Summarize 2-3 things the student did well, mention one thing to keep practicing, end on a high note"
- Frontend: show a "lesson complete" card with: concepts mastered, session duration, encouragement, "what's next" pointer
- This already partially exists in Rule 10 ("End naturally. Wrap up in 2-4 sentences") — issue is enforcement, not design

## Priority & Dependencies

```
Phase 1 (Welcome)          — standalone, do first
Phase 2 (Rich Summary)     — standalone, do second
Phase 3 (Re-Explain Fix)   — needs Phase 2 for best results
Phase 4 (Bridge Turn)      — needs Phase 2
Phase 5 (Interactive Cards) — deferred, larger change
Phase 6 (Wrap-Up)          — standalone, can parallel with 3/4
```

## What Study Plan Means Now

With pre-computed explanations, study plan's role shifts:

| Before (dynamic) | Now (with cards) |
|---|---|
| Explain steps = tutor explains live | Explain steps = covered by cards (leading) or quick-checks (non-leading) |
| Check steps = verify understanding | Check steps = unchanged, still valuable |
| Practice steps = guided problems | Practice steps = unchanged, still valuable |
| Study plan = tutor's full script | Study plan = session structure + check/practice sequencing |

Study plan is still needed — it defines WHAT to check and practice, in what order. But its explain steps become redundant for topics with pre-computed cards. The plan should evolve toward: `orientation → verify-understanding → practice → wrap-up` when cards exist.

## Non-Goals

- Removing study plan entirely — still needed for check/practice structure
- Making cards fully interactive (Phase 5) — deferred
- Changing card generation pipeline — only adding summary field (Phase 2)
- Redesigning frontend carousel — cosmetic changes only
