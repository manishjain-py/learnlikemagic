# PRD: Per-Card "I Didn't Understand" Simplification

## Problem Statement

During the card phase, students read pre-computed explanation cards sequentially. If a student gets stuck on one specific card, their only option is to finish all remaining cards and then click "Explain differently" at the end — which replaces the **entire deck** with a different variant.

This is the wrong granularity. A student confused by card 3 (e.g., "carrying in addition") may understand cards 1, 2, 4, and 5 perfectly well. Replacing the whole deck wastes the content they already absorbed and forces them to re-read everything.

The system thinks in terms of whole explanation decks. The student thinks in terms of individual cards.

## Goal

Let students flag confusion on any individual card and receive an inline, dynamically simplified re-explanation of just that card's content — without leaving the card flow.

## User Stories

| Persona | Story | Outcome |
|---------|-------|---------|
| Struggling student | "I understood the first two cards but this third one lost me" | Taps "I didn't understand" on card 3, gets a simpler version as the next card, continues normally |
| Curious student | Understands the card but wants it explained differently | Taps the button, sees the same concept from a fresh angle |
| Deeply stuck student | Still confused after 2 simplified versions of the same card | System transitions to interactive mode focused on that specific concept |
| Teacher (post-session) | Wants to know which cards cause confusion | Per-card confusion taps are logged; high-confusion cards surface for improvement |

## Current State

| Aspect | Today | Gap |
|--------|-------|-----|
| Confusion action | "Explain differently" at end of all cards | No per-card action |
| Scope of re-explanation | Entire variant replacement (all cards) | No single-card re-explanation |
| LLM calls during card phase | Zero (all pre-computed) | No dynamic generation mid-phase |
| Card identity | Array-index-based (`card-${i}`) | Insertion breaks indices |
| Replay/resume | Loads cards from `ExplanationRepository` only | No mechanism for session-specific inserted cards |
| Post-card tutor context | Binary: "understood" or "globally confused" | No per-card confusion detail |

## Functional Requirements

### 5.1 Per-Card Action Button

**FR-1**: Every explanation card displays an "I didn't understand" button alongside the existing Back/Next navigation.

**FR-2**: The button does NOT appear on the welcome slide (type `message`) — only on slides with type `explanation`.

**FR-3**: While a simplification request is in-flight, the button shows a loading state and navigation is disabled to prevent race conditions.

**FR-4**: The button text is "I didn't understand" for all simplification depths. No alternate labels needed.

### 5.2 Stable Card Identity

**FR-5**: Every card in the carousel gets a stable `card_id` that does not change when cards are inserted or removed.

**FR-6**: Base card IDs follow the pattern: `{variant_key}_{card_idx}` (e.g., `A_0`, `A_1`, `A_3`).

**FR-7**: Remedial card IDs follow the pattern: `remedial_{source_card_id}_{depth}` (e.g., `remedial_A_3_1`, `remedial_A_3_2`).

**FR-8**: Frontend carousel keys by `card_id`, not array index. Slide position persistence uses `card_id`.

### 5.3 Dynamic Simplification Generation

**FR-9**: New API endpoint: `POST /sessions/{session_id}/simplify-card` with request body `{ card_idx: int }`.

**FR-10**: This is a separate endpoint from `/card-action`. Card-action remains exclusively for phase-completion operations (`clear`, `explain_differently`). Simplification is a mid-phase interaction.

**FR-11**: The backend computes the simplification depth from session state. The frontend does NOT send the depth — backend is the single source of truth.

**FR-12**: The backend gathers context for the LLM call:
- The specific card content that confused the student
- All cards in the current variant (for learning journey context)
- The teaching guideline (topic, building blocks, student context)
- Previous simplification attempts for this card (so the LLM doesn't repeat the same approach)
- The simplification depth (for progressive simplification directives)

**FR-13**: Progressive simplification prompt strategy:
- Depth 1: "Explain the same concept using simpler everyday words and a different analogy. Shorter sentences. One idea at a time."
- Depth 2: "Explain like the student has zero background. Use the most basic real-world example possible. Maximum 3 sentences. No technical terms whatsoever."
- Depth 3: No further simplification. Escalate to interactive mode (FR-20).

**FR-14**: The LLM returns a single `ExplanationCard` with:
- `card_type: "simplification"` (distinct type for styling/analytics)
- `title`: A simplified version of the original card's title
- `content`: The simplified explanation
- `audio_text`: TTS-friendly spoken version (required)
- `visual`: null (no ASCII diagrams for remedial cards)
- `visual_explanation`: null (no PixiJS — too slow for real-time)

**FR-15**: The generated card is validated: content must be non-empty, under 500 words, and must include `audio_text`.

### 5.4 Card Insertion & Navigation

**FR-16**: The simplified card is inserted immediately after the current card in the carousel array.

**FR-17**: After insertion, the frontend auto-advances `currentSlideIdx` by 1 so the student lands on the new simplified card.

**FR-18**: The slide counter updates to reflect the new total: if it showed "3/7" before, it now shows "3/8" (or "4/8" after auto-advance).

**FR-19**: The simplified card also has the "I didn't understand" button. Tapping it generates a depth-2 simplification of the same base card.

### 5.5 Escalation to Interactive Mode

**FR-20**: After 2 simplification attempts on the same base card (depth 2 exhausted), the "I didn't understand" button on the depth-2 card triggers escalation instead of depth-3 generation.

**FR-21**: Escalation transitions to interactive mode focused on the specific card's concept:
- Complete the card phase
- Build a structured confusion summary (FR-25)
- Generate a bridge turn with `bridge_type="card_stuck"` (new type)
- The bridge prompt tells the tutor exactly which concept the student struggled with and what simplification approaches were already tried

**FR-22**: The escalation bridge prompt: "The student was reading explanation cards. They got stuck on card [N]: '[title]'. They saw the original explanation and [X] simplified versions but still couldn't grasp it. The simplified versions tried: [summary of approaches]. Begin a conversational exploration to find their specific point of confusion. Ask a probing question — don't re-explain yet."

### 5.6 Session State & Replay

**FR-23**: `CardPhaseState` gains a new field:
```python
remedial_cards: dict[int, list[RemedialCard]]
# Maps base card_idx → ordered list of generated remedial cards
```

**FR-24**: `RemedialCard` model:
```python
class RemedialCard(BaseModel):
    card_id: str           # "remedial_A_3_1"
    source_card_idx: int   # base card index this simplifies
    depth: int             # 1 or 2
    card: dict             # ExplanationCard content (title, content, audio_text, card_type)
```

**FR-25**: `CardPhaseState` gains a confusion tracking field:
```python
confusion_events: list[ConfusionEvent]
```
```python
class ConfusionEvent(BaseModel):
    base_card_idx: int        # which card confused the student
    base_card_title: str      # title for human readability
    depth_reached: int        # how many simplifications were tried
    escalated: bool           # whether it escalated to interactive mode
    resolved: bool            # whether student moved past it (clicked Next after simplified card)
```

**FR-26**: The replay endpoint (`GET /sessions/{id}/replay`) reconstructs the full card deck by:
1. Loading base cards from `ExplanationRepository` (as today)
2. Reading `remedial_cards` from session state
3. Inserting remedial cards at the correct positions after their source cards
4. Returning the merged deck with stable `card_id` values

**FR-27**: On page refresh during card phase, the frontend receives the merged deck and restores the student's position using `card_id` (not array index).

### 5.7 Post-Card Tutor Context

**FR-28**: `_build_precomputed_summary()` includes a per-card confusion section when confusion events exist:
```
Cards that needed simplification:
- Card 3 "Carrying in Addition": 2 simplifications attempted, resolved after depth-2
- Card 5 "Regrouping Tens": 1 simplification attempted, student moved on
```

**FR-29**: The bridge prompt receives this structured confusion data. For `bridge_type="understood"`, the tutor probes the previously-confused concepts first. For `bridge_type="confused"`, it focuses on those concepts.

**FR-30**: The v2 session plan generator receives confusion events so it can add extra practice steps for concepts the student struggled with during card phase.

### 5.8 End-of-Deck Action Relabeling

**FR-31**: With per-card simplification available, the end-of-deck buttons change:
- "I understand!" becomes **"Start practice"** (more accurate — student has had per-card help opportunities)
- "Explain differently" becomes **"Try a different approach"** (clearer about what changes — the entire deck)
- When all variants exhausted: **"I still need help"** (unchanged)

### 5.9 Analytics

**FR-32**: Every "I didn't understand" tap is logged as a first-class analytics event:
```python
{
    "event": "card_confusion_tap",
    "session_id": str,
    "guideline_id": str,
    "variant_key": str,
    "base_card_idx": int,
    "base_card_title": str,
    "simplification_depth": int,  # 0 = first tap on base card
    "timestamp": datetime
}
```

**FR-33**: High-confusion cards (>30% confusion rate across sessions) surface in admin analytics for explanation quality improvement.

## UX Requirements

**UX-1**: The "I didn't understand" button must be visually secondary to Next (not competing for attention). Suggested: text link or ghost button below the card content, above Back/Next.

**UX-2**: Simplified cards get a distinct visual badge (e.g., "Simplified" pill) so the student knows this is a re-explanation, not a new concept.

**UX-3**: Loading state during LLM generation: show a gentle skeleton/shimmer on the current card with text like "Simplifying..." (expected latency: 2-5 seconds).

**UX-4**: TTS auto-play behavior: if the student has audio enabled, auto-play the simplified card's audio when it appears (same as other cards).

**UX-5**: When escalating to interactive mode (FR-20), show a brief transition message: "Let's talk through this together" before switching to chat mode.

## Technical Architecture

```
Student taps "I didn't understand" on card 3
    │
    ▼
Frontend: POST /sessions/{id}/simplify-card  { card_idx: 3 }
    │
    ▼
Backend: SessionService.simplify_card()
    ├─ Load session state, validate card_phase active
    ├─ Determine depth from remedial_cards[3] count
    ├─ If depth >= 2: escalate (FR-20)
    ├─ Else: gather context (card, variant, guideline, prior attempts)
    │
    ▼
Orchestrator: generate_simplified_card()
    ├─ Build prompt with progressive simplification directives
    ├─ Call LLM (master tutor model)
    ├─ Parse + validate ExplanationCard output
    │
    ▼
Backend:
    ├─ Store RemedialCard in session.card_phase.remedial_cards[3]
    ├─ Log confusion analytics event
    ├─ Persist session state
    │
    ▼
Response: { action: "insert_card", card: {...}, card_id: "remedial_A_3_1", insert_after: "A_3" }
    │
    ▼
Frontend:
    ├─ Insert card into explanationCards array after source card
    ├─ Recalculate carouselSlides
    ├─ Auto-advance currentSlideIdx
    └─ Update slide counter
```

## Impact on Existing Features

| Feature | Impact | Action Required |
|---------|--------|-----------------|
| Pre-computed card phase | Introduces LLM calls mid-phase (only when student taps) | New endpoint + session state fields |
| Variant switching ("Explain differently") | Unchanged. Per-card simplification and whole-deck switching coexist | Remedial cards discarded on variant switch |
| Replay/resume | Must merge remedial cards into deck on replay | Modify replay endpoint |
| Bridge turn generation | Needs structured confusion context (not just binary) | New `bridge_type="card_stuck"` + confusion summary |
| Session plan generation (v2) | Should factor in per-card confusion | Pass confusion events to generator |
| Scorecard / coverage | No impact — coverage is topic-level | None |
| Evaluation pipeline | Simplified card quality is evaluable | Future: add remedial quality dimension |
| Visual enrichment | No impact — remedial cards skip visuals | None |
| TTS | Remedial cards must include `audio_text` | LLM prompt enforces this |

## Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| LLM call fails during simplification | Return error to frontend; show "Couldn't simplify right now, try again" toast. Student stays on current card. |
| Student taps "I didn't understand" then immediately navigates Back | Cancel in-flight request. No card inserted. |
| Student simplifies card 3, goes back to card 2, simplifies card 2 | Both remedial cards stored independently under their respective base card indices. Deck order: [1, 2, 2-simplified, 3, 3-simplified, 4, ...] |
| Student simplifies card 3, then at end-of-deck clicks "Try a different approach" (variant switch) | All remedial cards discarded. New variant loads clean. Confusion events retained in session state for tutor context. |
| Student refreshes page mid-simplification (LLM call in flight) | Request lost. On replay, deck shows only previously persisted remedial cards. Student can re-tap "I didn't understand." |
| Depth-2 escalation triggered but orchestrator bridge call fails | Fallback message: "Let's talk this through — what part is confusing you?" Transition to interactive. |
| Card has only 1 sentence of content | Simplification still works — LLM may use analogy, concrete example, or break the single idea into even smaller pieces. |

## v1 Scope

- Per-card "I didn't understand" button on all explanation cards
- Dynamic LLM simplification (depth 1 and 2)
- Escalation to interactive mode after depth 2
- Remedial cards in session state + replay reconstruction
- Stable card IDs (frontend + backend)
- Structured confusion summary for bridge/session-plan
- Analytics event logging
- End-of-deck button relabeling
- Text-only remedial cards (no PixiJS visuals)

## v2 Roadmap

- **Visual generation for remedial cards**: If the original card had a visual, generate a simpler visual for the remedial card (async, appears after card loads)
- **Prerequisite detection**: If a student can't understand a card after 2 simplifications, check whether they're missing a prerequisite concept and redirect to that topic
- **Base card improvement pipeline**: Feed high-confusion-rate cards into autoresearch for automated rewriting
- **Proactive confusion detection**: Use reading time signals (if student lingers on a card far longer than average) to proactively suggest simplification

## Out of Scope

- Changing the existing whole-deck "Explain differently" / variant switching mechanism
- Per-card simplification in exam mode or clarify-doubts mode
- Generating practice questions for individual cards mid-card-phase
- Real-time visual generation for remedial cards (v2)
- Student-typed free-text questions during card phase

## Success Metrics

| Category | Metric | Target |
|----------|--------|--------|
| Adoption | % of sessions where "I didn't understand" is tapped at least once | >15% (validates the need exists) |
| Effectiveness | % of depth-1 simplifications after which student clicks Next (not "I didn't understand" again) | >70% (one simplification usually enough) |
| Escalation rate | % of simplification sequences that escalate to interactive mode | <20% (most confusion resolved by depth 2) |
| Card quality signal | Cards with >30% confusion rate identified and flagged | 100% coverage |
| Latency | P95 simplification generation time | <5 seconds |
| Session completion | Session completion rate before vs after feature launch | No regression |
