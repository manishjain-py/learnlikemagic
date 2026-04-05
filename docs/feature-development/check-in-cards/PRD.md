# PRD: Check-In Cards During Explanation Phase

## Problem

Card phase is one-way. Student reads 5-15 cards passively, can only "simplify" or switch variant. No comprehension verification before moving on. For Grade 3-8 kids on phones, this is a long stretch of passive consumption with dropping engagement.

The interactive phase (live tutor) only starts *after all cards*. By then, misconceptions may have compounded across multiple cards.

## Solution

Insert **interactive check-in cards** between explanation cards at natural concept boundaries. After every 2-3 cards covering one idea, the student does a quick match-the-pairs activity before continuing.

Not a quiz. A warm, low-stakes **readiness signal** — "let's make sure that clicked before we move on." Passing a check-in does not mean the student understands the concept deeply. It means they're ready for the interactive tutor to probe further. Match-pairs tests recognition/recall, not reasoning — that's intentional for v1 (deterministic, mobile-friendly, fast). Deep WHY-understanding is tested by the live tutor in the interactive phase.

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

Check-ins consolidate what was just taught. They introduce no new information — only reference concepts, terms, and examples from the preceding 2-3 cards.

### Match-the-pairs interaction

- Two columns: 3-4 items on left, 3-4 on right
- **Tap-tap** mechanic: tap left item (highlights), tap right item (evaluates)
- Correct match: both boxes turn green, lock, checkmark
- Wrong match: shake animation, hint text appears
- All matched: success message + brief reinforcement
- "Continue" button appears only after all pairs correct

### Gate behavior

- Student **cannot advance** past a check-in until all pairs correct
- No scoring, no timer, no wrong-count — unlimited retries with hints
- No LLM evaluation — correctness is deterministic (answer key baked in at generation time)
- **Safety valve**: if a student gets the *same pair* wrong 5+ times, that pair auto-reveals with its explanation and locks. Prevents a bad generated pair from trapping the student.
- Tone is warm: "Let's check!" not "Test time"

### Simplify action on check-ins

The "I didn't understand" / simplify button does **not** appear on check-in cards. Hints serve that role during the activity. The student can always swipe back to re-read preceding explanation cards (back navigation is unrestricted).

### TTS behavior

- **Instruction** read aloud on card entry
- **Hint** read aloud on wrong match
- **Success message** read aloud on completion
- Individual pair items are *not* read on tap (too noisy)

### Client-side answer key

Pairs are stored in correct order; right column shuffled client-side; validation by index match. The student's browser knows the answer key. This is a deliberate trade-off — acceptable for Grade 3-8 kids, and the alternative (server-side validation per tap) adds latency and complexity with no real benefit for this audience.

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

### Stable card identity

Every deck item gets a stable `card_id` (UUID), separate from `card_idx` (display order). This prevents identity drift when check-in cards are inserted and `card_idx` is re-numbered.

`card_idx` = display order (re-numbered on insert). `card_id` = stable identity (set once, never changes). Simplification, replay, analytics, and progress tracking reference `card_id`, not `card_idx`.

### ExplanationCard — extended

```
ExplanationCard:
  card_id: str                    # NEW — stable UUID
  card_idx: int                   # display order (re-numbered on insert)
  card_type: str                  # adds "check_in" to existing types
  title: str
  content: str
  visual: Optional[str]
  audio_text: Optional[str]
  visual_explanation: Optional[CardVisualExplanation]
  check_in: Optional[CheckInActivity]   # NEW — populated when card_type="check_in"
```

Note: `card_type` on `ExplanationCard` (backend Pydantic model + frontend TypeScript union) and `Slide.type` in the frontend carousel (`ChatSession.tsx`) are **separate fields**. Both need `check_in` added. The carousel maps `ExplanationCard.card_type == "check_in"` → `Slide.type = "check_in"`.

### CheckInActivity

```
CheckInActivity:
  activity_type: "match_pairs"    # extensible later
  instruction: str                # "Match each fraction to its meaning"
  pairs: [{left, right}, ...]     # 3-4 pairs, stored in correct order
  hint: str                       # shown on wrong match
  success_message: str            # shown when all correct
  audio_text: str                 # TTS for instruction
```

## State Contracts

### Gate scope

The check-in gate is a **forward-navigation constraint within a live client session**. It is not server-enforced. Backend persists `current_card_idx` for session resume but does not persist check-in completion state.

On resume: student is placed at their server-persisted card position. If they were past a check-in, they stay past it. If before one, they redo it. Acceptable for v1 — the primary goal is engagement during the active learning flow.

### Regeneration rules

Check-ins are derived from explanation content. If explanations are regenerated:
- Check-ins are **discarded** (entire `cards_json` is replaced by `repo.upsert()`)
- Must be re-generated by running the check-in enrichment pipeline again
- Pipeline order: Explanation Generation → Visual Enrichment → Check-In Enrichment
- Regenerating any stage invalidates all downstream stages

### Struggle signal propagation

Check-in interaction data (which pairs were hard, retry count, hints shown) is captured client-side during the card phase. When transitioning to the interactive phase, this data is forwarded as **tutor context** in the bridge/transition summary. The interactive tutor can use it to probe weak spots: "Student struggled matching X to Y — revisit this concept."

## Generation Pipeline

Follows the visual enrichment pattern — separate, decoupled pipeline stage that runs after explanations (and optionally after visuals) exist.

```
Explanation Generation (existing)
   ↓
Visual Enrichment (existing)
   ↓
Check-In Enrichment (NEW) — named stage: "check_in_enrichment"
```

### Pipeline steps

1. **Analyze**: LLM reads all cards for a variant, identifies concept boundaries (groups of 2-3 related cards that cover one idea)
2. **Generate**: For each boundary, LLM creates a check-in — match pairs testing the preceding cards' content, plus hint and success message
3. **Validate**: strict criteria (see below), fail-open — if validation fails, skip that check-in entirely rather than inserting a bad one
4. **Insert**: New `card_type="check_in"` cards inserted into `cards_json`. Existing cards get stable `card_id` assigned (if not already present). New check-in cards get fresh UUIDs. `card_idx` re-numbered for display order.

### Validation criteria

- **2-4 pairs** per check-in (not fewer, not more)
- **Exactly one unambiguous correct mapping** per pair — no synonym collisions, no pairs where multiple matches feel right
- **No visual-dependent pairs** — matching must work from text alone (the student may not have opened the PixiJS visual)
- **Pairs test preceding cards only** — not content from later or unrelated cards
- Hint and success message both present and non-empty
- **Fail-open**: if any criterion fails, that check-in is not inserted. A missing check-in is better than a broken gate.

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
- Safety valve: auto-reveal pair after 5 wrong attempts on same pair

### Carousel integration

Two fields need `check_in` added:
- `ExplanationCard.card_type` union in `api.ts` (currently: `concept | example | visual | analogy | summary | simplification`)
- `Slide.type` in `ChatSession.tsx` (currently: `explanation | message`)

Mapping: `card_type == "check_in"` → `Slide.type = "check_in"`, with `slide.checkIn` populated from `card.check_in`.

Gate logic: Next/swipe disabled when `currentSlide.type === 'check_in' && !completedCheckIns.has(currentSlideIdx)`.

## Scope — What to Build

| Component | Work |
|-----------|------|
| Backend models | `MatchPair`, `CheckInActivity` Pydantic models, add `card_id` + `check_in` to `ExplanationCard` |
| Backend service | `CheckInEnrichmentService` (mirrors `AnimationEnrichmentService`) |
| Backend prompt | `check_in_generation.txt` |
| Backend script | `run_check_in_enrichment.py` |
| Pipeline integration | Register as named stage in chapter job flow |
| Frontend types | Add `check_in` to `ExplanationCard.card_type` and `Slide.type` in `api.ts` |
| Frontend component | `MatchActivity.tsx` |
| Frontend integration | `ChatSession.tsx` carousel + gate logic + struggle signal capture |
| Frontend styles | Match activity CSS (select, correct, wrong, complete, auto-reveal states) |
| Admin | Add `check_in` badge color to `ExplanationAdmin.tsx` card type display |

## Scope — What NOT to Build

- **Multiple activity types** — only match-pairs for now. `activity_type` field makes it extensible later (sort, sequence, true/false).
- **Backend grading** — deterministic, client-side only.
- **Scoring/analytics** — no scorecard integration. These are formative, not summative.
- **Skip button** — the gate is the point. Safety valve (auto-reveal after 5 wrong) handles bad pairs.
- **Server-persisted check-in state** — client-side tracking for v1. Gate is forward-nav only.

## Alignment with Principles

| Principle | How it applies |
|-----------|---------------|
| Interactive Teaching #1 — Explain Before Testing | Check understanding with a concrete task before moving on |
| Interactive Teaching #11 — Structured Input | Tapping to match, no typing |
| UX #1 — One Thing Per Screen | Each check-in is one focused activity |
| UX #2 — Minimal Typing | Pure tap interaction |
| How to Explain #8 — Build Progressively | Check-ins are verified checkpoints that consolidate the preceding cards, introducing no new information |
| Evaluation #6 — Card-to-Session Coherence | Check-ins reuse the same analogies/examples from preceding cards, strengthening coherence into the interactive phase |
| Pipeline Principles — Decoupled Stages | Separate enrichment pipeline, same pattern as visuals |
