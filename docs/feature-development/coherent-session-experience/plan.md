# Coherent Teach Me Session — Plan

## Core Principle

**Master tutor is the single brain that owns the entire session.** It sees everything (guidelines, study plan, explanation cards, student profile) and generates every student-facing message. No hardcoded messages. No separate prompts. No seams. One tutor, one voice, first word to last.

All other artifacts (study plan, explanation cards, guidelines) are supplemental context fed TO the master tutor. They inform it, they don't bypass it.

## Problem

Teach Me feels like individual pieces glued together, not a single teaching session.

**Current flow:**
1. Hardcoded welcome: "Let's learn about X! I'll walk you through it..." — no name, no curiosity, no expectations
2. Passive card carousel — student reads 5-12 cards with zero interaction
3. Hardcoded transition: "Great! Now let's make sure you've got it. Feel free to ask any questions!"
4. Interactive phase starts — suddenly a different experience with a live tutor
5. Session ends when study plan steps exhausted — no wrap-up

**Root cause:** multiple systems speak to the student (hardcoded strings, card content, master tutor) instead of one tutor speaking through all of them.

## Gaps

### G1: Cold Start — No Real Welcome
- Welcome hardcoded at `session_service.py:153`, orchestrator bypassed for card sessions
- Frontend hides even the hardcoded welcome during card phase — student sees nothing from tutor before cards
- No student name, no curiosity hook, no session framing
- **Code:** `create_new_session()` skips `orchestrator.generate_welcome_message()` when cards exist

### G2: Passive Handoff After Cards
- Transition hardcoded at `session_service.py:863`: "Great! Now let's make sure you've got it"
- Master tutor has good first-turn pacing directive (`master_tutor.py:163`) but it only fires AFTER student sends a message via `process_turn()`
- Most important moment in the lesson is passive — tutor waits instead of leading
- "Feel free to ask any questions!" contradicts what happens next (tutor asks THEM questions)

### G3: Fallback Re-Explanation → Generic Welcome (Without Card Context)
- When all card variants exhausted, `session_service.py:892` calls `generate_welcome_message()` — dynamic but generic (no card context, no awareness student is confused)
- Confused student who read 2-3 variants gets a generic welcome instead of a targeted re-explanation
- Should be master tutor with full context: teaching_notes from cards, awareness student is confused

### G4: Shallow Explanation Summary
- `_build_precomputed_summary()` captures only: card titles, analogy names, example names
- Missing: HOW analogies were used, conceptual progressions, specific framings
- Tutor references cards blindly — can say "pizza analogy" but not "remember cutting pizza into 4 slices and eating 1 = 1/4"

### G5: Non-Leading Explain Steps Re-Explain Card Content
- `_advance_past_explanation_steps()` only skips consecutive LEADING explain steps
- Plan: `explain(A) → check(A) → explain(B) → check(B)`. Cards cover A+B.
- After cards, skips explain(A), lands on check(A). Good.
- After check(A), hits explain(B) — pacing directive says "begin with curiosity hook", all building blocks `[TODO]`. System fights its own summary that says "build on cards."

### G6: Study Plan Uses Activity Titles as Concept IDs
- `topic_adapter.py:104`: `concept = item.get("title")` — titles like "Pizza Party Fractions Fun" become concept keys
- `topic_adapter.py:130-149`: step types inferred by keyword matching, fallback to heuristic pattern
- Mastery tracked against display labels, not real concepts

### G7: Session Ending — UI Overwrites Tutor's Farewell
- `ChatSession.tsx:468`: on `is_complete`, sets `isComplete(true)` immediately
- `ChatSession.tsx:1063`: replaces entire chat with summary card
- Tutor generates warm closing (Rule 10) but student may never see it — same state update triggers both

### G8: Progress Hidden in TeachMe
- `ChatSession.tsx:1033`: progress bar excluded via `sessionMode !== 'teach_me'`
- Student has no sense of where they are in the lesson
- Backend has step/mastery/coverage data, frontend has the state — just not shown

### G9: Duplicate Welcome in Non-Card Sessions
- `session_service.py:195`: welcome generated during REST session creation, added to conversation history
- `sessions.py:721`: WebSocket handler generates another welcome when `turn_count == 0`
- `turn_count` stays 0 because `add_message()` doesn't increment it (only `process_turn()` does)

### G10: Card Phase Resume Uses localStorage
- Card position stored in localStorage, not read from server `CardPhaseState`
- Coverage = 0 until card phase completes (`session_service.py:966`)
- Student who leaves mid-cards can't resume — session invisible in resume UI

## Plan

### Phase 1: Master Tutor Owns Welcome

**What:** Master tutor generates the welcome for ALL teach_me sessions, including card-phase.

**Changes:**
- `session_service.py` — stop hardcoding welcome. Call master tutor (via orchestrator) with full context: student profile, topic, study plan, card variant info
- Master tutor generates: greeting by name, curiosity hook, session framing ("I've put together some explanation cards, go through them and then we'll practice together")
- Welcome appears as first carousel slide BEFORE explanation cards
- Remove the `if explanations: skip orchestrator` branch — master tutor always speaks first

**Assumption:** all teach_me sessions have pre-computed explanation cards.

**Why first:** first impression. Highest impact per effort.

### Phase 2: Richer Explanation Summary

**What:** Give master tutor enough context to reference cards meaningfully.

**Changes:**
- `explanation_generator_service.py` — during offline generation, produce a `teaching_notes` field per variant: 2-3 sentence narrative of what was explained and how (not just titles/labels)
- `summary_json` schema — add `teaching_notes` field
- `_build_precomputed_summary()` — include teaching notes in system prompt injection
- Master tutor can now say "remember when we showed that cutting pizza into 4 slices..." instead of just "pizza analogy"

**Naming:** `teaching_notes`, not `handoff_summary` — these are the tutor's own notes about what it taught via cards, not a handoff between systems.

**Why second:** enables all downstream improvements. Without this, tutor is blind to card content.

### Phase 3: Master Tutor Owns the Bridge

**What:** After cards, master tutor generates the bridge turn. No hardcoded message. No waiting for student.

**Changes:**
- `complete_card_phase()` — remove hardcoded transition message. Instead, trigger a master tutor turn with synthetic context: `[Student completed explanation cards and indicated understanding]`
- Master tutor uses its existing first-turn pacing directive (`master_tutor.py:163`) — references card analogies, asks student to explain back
- This is teacher-led, not passive. Student sees tutor's bridge immediately after clicking "I understand!"
- If student had clicked "explain differently" and variants exhausted: same mechanism — master tutor with context `[Student read all card variants and is still confused]`. No separate prompt. No `generate_welcome_message()`.

**Depends on:** Phase 2 (needs rich summary to reference cards meaningfully)

### Phase 4: Card-Aware Pacing for Non-Leading Explain Steps

**What:** When master tutor reaches an explain step whose concept was already covered by cards, pacing directive tells it to do a quick check instead of full re-explanation.

**Changes:**
- `_compute_pacing_directive()` — detect when current step is `explain` AND concept is in `precomputed_explanation_summary`
- Pacing directive: "This concept was already explained via cards. Do a quick 'what do you remember about X?' check. If student remembers, set phase_update='complete' and advance. If not, re-explain briefly using a different angle."
- No complex skip/convert logic in `_advance_past_explanation_steps()` — keep it simple (skip leading only). Trust master tutor to handle non-leading ones via pacing
- `_advance_past_explanation_steps()` stays as safety net for leading explain steps

**Why this approach:** master tutor has the context (summary, mastery, student responses). Let it decide rather than building system-level machinery.

### Phase 5: Session Ending — Show Tutor's Farewell

**What:** Student sees master tutor's closing message before summary screen.

**Changes:**
- `ChatSession.tsx` — when `is_complete` arrives, DON'T immediately swap to summary card. Instead, show the tutor's final message as the last carousel slide
- Add "View Summary" button after tutor's farewell. Student taps to see summary.
- Master tutor's closing is the last thing student reads from the tutor

### Phase 6: TeachMe Progress Frame

**What:** Show students where they are in the lesson.

**Changes:**
- `ChatSession.tsx:1033` — remove `sessionMode !== 'teach_me'` exclusion
- Show simple progress: "Understanding → Practice → Done" derived from study plan step types and current position
- Not raw study plan internals — just orientation

### Phase 7: Bug Fixes

**G9 — Duplicate welcome:** `sessions.py:721` — change guard from `turn_count == 0` to `len(session.conversation_history) == 0`

**G10 — Card resume:** Frontend should read card position from server `CardPhaseState` on resume, not localStorage. Server state is already persisted.

### Phase 8: Study Plan Improvements (Deferred)

**G6 — Activity titles as concepts:** Study plan generator should output explicit `concept` field distinct from `title`. Adapter should use `concept` for mastery tracking, `title` for display. Important for data quality long-term.

**Study plan redesign:** Since all sessions have cards, study plan's explain steps are always redundant. Generator should produce `verify → practice` structure when cards exist. Keep explain metadata (building blocks, approaches) as fallback reference. Longer-term: study plan evolves from step-by-step script to curriculum outline that the master tutor interprets.

### Deferred: Interactive Card Phase

Add micro-interactions during card reading. Options: check-in cards between content cards, chat alongside cards, or tutor narration per card. Largest UX + backend change. Phases 1-7 fix the most painful gaps first.

## Priority & Dependencies

```
Phase 1 (Welcome)        — standalone, do first
Phase 2 (Rich Summary)   — standalone, do second
Phase 3 (Bridge Turn)    — depends on Phase 2
Phase 4 (Pacing Fix)     — depends on Phase 2
Phase 5 (Session End)    — standalone, can parallel with 3/4
Phase 6 (Progress Frame) — standalone, can parallel with 3/4
Phase 7 (Bug Fixes)      — standalone, can parallel with anything
Phase 8 (Study Plan)     — deferred
```

## What Study Plan Means Now

All sessions have cards → explain steps always redundant.

| Before (dynamic) | Now (with cards) |
|---|---|
| Explain steps = tutor explains live | Explain steps = covered by cards, tutor does quick-check if non-leading |
| Check steps = verify understanding | Unchanged |
| Practice steps = guided problems | Unchanged |
| Study plan = tutor's full script | Study plan = supplemental context fed to master tutor |

Study plan is input to the master tutor, not its boss. Master tutor uses it as a curriculum outline — what concepts to verify and practice, in what order — while owning the pedagogy.

## Non-Goals

- Removing study plan — still needed for check/practice structure
- Making cards interactive — deferred
- Separate system prompts — welcome/bridge use purpose-specific turn prompts but share the master tutor's system prompt (one brain, different moments)
- Redesigning frontend carousel — cosmetic changes only
