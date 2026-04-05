# PRD: Check-In Cards During Explanation Phase

## Problem

Card phase is one-way. Student reads 5-15 cards passively, can only "simplify" or switch variant. No comprehension verification before moving on. For Grade 3-8 kids on phones, this is a long stretch of passive consumption with dropping engagement.

The interactive phase (live tutor) only starts *after all cards*. By then, misconceptions may have compounded across multiple cards.

## Solution

Insert **interactive check-in cards** between explanation cards at natural concept boundaries. After every 2-3 cards covering one idea, the student does a quick match-the-pairs activity before continuing.

Not a quiz. A warm, low-stakes comprehension check — "let's make sure that clicked before we move on."

## User Experience

### Card flow with check-ins

```
[Card 1: What is a fraction?]
[Card 2: Naming fractions — numerator & denominator]
   ↓
[CHECK-IN: Match each fraction to its meaning]
   ↓
[Card 3: Comparing fractions]
[Card 4: Which is bigger — 1/2 or 1/4?]
   ↓
[CHECK-IN: Match each fraction to its picture]
   ↓
[Card 5: Summary]
```

### Match-the-pairs interaction

- Two columns: 3-4 items on left, 3-4 on right
- **Tap-tap** mechanic: tap left item (highlights), tap right item (evaluates)
- Correct match: both boxes turn green, lock, checkmark
- Wrong match: shake animation, hint text appears
- All matched: success message + brief reinforcement
- "Continue" button appears only after all pairs correct

### Key rules

- Student **cannot advance** past a check-in until all pairs correct
- No scoring, no timer, no wrong-count — unlimited retries with hints
- No LLM evaluation — correctness is deterministic (answer key baked in at generation time)
- Tone is warm: "Let's check!" not "Test time"

## Examples

**After cards explaining place value (tens and ones):**

| Left | Right |
|------|-------|
| 34 | 3 tens and 4 ones |
| 56 | 5 tens and 6 ones |
| 12 | 1 ten and 2 ones |

Hint: "The first digit tells you how many tens."
Success: "You've got it! The tens place is always the first digit."

**After cards explaining shapes:**

| Left | Right |
|------|-------|
| Triangle | 3 sides |
| Rectangle | 4 sides |
| Pentagon | 5 sides |

Hint: "Try counting the sides of each shape in your head."
Success: "Nice! The name of a shape often tells you how many sides it has."

## Data Model

New card type `check_in` added to explanation cards. New field `check_in` on `ExplanationCard`:

```
CheckInActivity:
  activity_type: "match_pairs"    # extensible later
  instruction: str                # "Match each fraction to its meaning"
  pairs: [{left, right}, ...]     # 3-4 pairs, stored in correct order
  hint: str                       # shown on wrong match
  success_message: str            # shown when all correct
  audio_text: str                 # TTS for instruction
```

Right column shuffled client-side on render. Correct pairs validated client-side by index.

## Generation Pipeline

Follows the visual enrichment pattern — separate, decoupled pipeline stage that runs after explanations (and optionally after visuals) exist.

```
Stage 5: Explanation Generation (existing)
Stage 6: Visual Enrichment (existing)
Stage 7: Check-In Enrichment (NEW)
```

### Pipeline steps

1. **Analyze**: LLM reads all cards for a variant, identifies concept boundaries (groups of 2-3 related cards that cover one idea)
2. **Generate**: For each boundary, LLM creates a check-in — match pairs testing the preceding cards' content, plus hint and success message
3. **Validate**: 2-4 pairs per check-in, no duplicate items, hint and success exist, pairs are relevant to preceding cards
4. **Insert**: New `card_type="check_in"` cards inserted into `cards_json`, card_idx re-numbered

### Placement rules

- Typically 2-3 check-ins per variant (not every card boundary needs one)
- Never before the first 2 cards (student needs content to match against)
- Never immediately after another check-in
- Never after the summary card

## Frontend

### New component: `MatchActivity.tsx`

- Renders two-column tap-to-match UI
- State machine: `IDLE -> LEFT_SELECTED -> EVALUATING -> (CORRECT|WRONG) -> IDLE`
- All matched -> `COMPLETE`
- Large tap targets (48px+ height), mobile-first
- Animations: highlight on select, checkmark on correct, shake on wrong

### Carousel integration

- New slide type `check_in` alongside `explanation` and `message`
- Gate logic: Next/swipe disabled when on incomplete check-in
- TTS: instruction read aloud on card entry, success message read on completion

### No backend state for check-in completion

All tracking is client-side. On session resume, student re-does check-ins (good for reinforcement).

## Scope — What to Build

| Component | Work |
|-----------|------|
| Backend models | `MatchPair`, `CheckInActivity` Pydantic models, extend `ExplanationCard` |
| Backend service | `CheckInEnrichmentService` (mirrors `AnimationEnrichmentService`) |
| Backend prompt | `check_in_generation.txt` |
| Backend script | `run_check_in_enrichment.py` |
| Pipeline integration | Register as stage in chapter job flow |
| Frontend types | Extend `ExplanationCard` and `Slide` in `api.ts` |
| Frontend component | `MatchActivity.tsx` |
| Frontend integration | `ChatSession.tsx` carousel + gate logic |
| Frontend styles | Match activity CSS (select, correct, wrong, complete states) |

## Scope — What NOT to Build

- **Multiple activity types** — only match-pairs for now. `activity_type` field makes it extensible later (sort, sequence, true/false).
- **Backend grading** — deterministic, client-side only.
- **Scoring/analytics** — no scorecard integration. These are formative, not summative.
- **Skip button** — the gate is the point.

## Alignment with Principles

| Principle | How it applies |
|-----------|---------------|
| Interactive Teaching #1 — Explain Before Testing | Check understanding with a task, not just reading |
| Interactive Teaching #11 — Structured Input | Tapping to match, no typing |
| UX #1 — One Thing Per Screen | Each check-in is one focused activity |
| UX #2 — Minimal Typing | Pure tap interaction |
| How to Explain #8 — Build Progressively | Verified checkpoints in the progression |
| Pipeline Principles — Decoupled Stages | Separate enrichment pipeline, same pattern as visuals |
