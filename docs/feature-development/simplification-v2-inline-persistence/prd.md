# PRD: "I Didn't Understand" v2 — Inline Expansion + Per-Student Persistence

**Status:** Draft
**Date:** 2026-04-10
**Supersedes:** `per-card-simplification/prd.md` (v1 — card insertion approach)

## Problem Statement

The v1 per-card simplification feature has two structural problems:

**1. Broken UX — simplified card is invisible to the user.**
When a student taps "I didn't understand", the backend generates a simplified card and the frontend inserts it as a new card in the carousel. Due to an off-by-one navigation bug, the new card is inserted _behind_ the user's current position. The user sees no change — they're still viewing the same card they were confused by. They'd have to press "Back" to find the simplified version.

Even without the bug, inserting a separate card is a poor UX: the student loses context. They can't see the original explanation alongside the simplified version. They must mentally map between two separate cards about the same concept.

**2. Simplifications are ephemeral — lost after the session ends.**
Simplified content is stored in `session.state_json.card_phase.remedial_cards`. When the student visits the same topic again, a new session is created with a blank slate. The student sees the same confusing card again, must tap "I didn't understand" again, and wait for a new generation.

The system generates valuable personalized content and then throws it away.

## Goal

1. Display simplified explanations **inline within the same card** — the student scrolls down to see the original explanation plus progressively simpler breakdowns, all in context.
2. **Persist simplifications per-student** — when a student revisits a topic, their personalized card experience loads automatically.

## User Stories

| Persona | Story | Outcome |
|---------|-------|---------|
| Confused student | "This card doesn't make sense to me" | Taps "I didn't understand", sees a simpler breakdown appear below the original content on the same card |
| Still confused | "The simpler version also doesn't help" | Taps again, a second even-simpler section appends below. All three versions visible by scrolling. |
| Returning student | "I studied this last week but want to review" | Opens the topic, card 3 already has the simplified sections from their previous session — no waiting |
| New student, same topic | Opens the same topic for the first time | Sees the generic base cards with no simplifications — clean slate |

## Current State (v1) vs. Proposed (v2)

| Aspect | v1 (Current) | v2 (Proposed) |
|--------|-------------|---------------|
| Simplification display | New card inserted into carousel | Inline expansion within same card |
| Navigation after simplify | Broken — user lands on original card, simplified card behind them | No navigation change — content appends below, auto-scrolls |
| Context | Original and simplified on separate cards | Both visible on same card by scrolling |
| Multiple simplifications | Multiple inserted cards cluttering carousel | Clean vertical stack within one card |
| Typewriter animation | Missing — simplified cards have flat `content`, no `lines[]` | Full typewriter + per-line audio (same quality as base cards) |
| Persistence | Session-only (`state_json`) — lost on new session | Per-student table — survives across sessions |
| Next visit | Fresh start, no memory of simplifications | Pre-loaded personalized cards |
| Loading feedback | "Simplifying..." text at 0.6 opacity | Animated skeleton/shimmer with smooth reveal |

## Functional Requirements

### 6.1 Inline Expansion Display

**FR-1**: When a student taps "I didn't understand", the simplified content is appended **below the original content within the same card**, separated by a visual divider.

**FR-2**: The card layout for a card with simplifications:
```
[Card Type Badge: Concept]
[Original Title]

Original explanation content...
[Original Visual]

─── Let me break this down ───          ← visual separator

Simplified explanation content...        ← typewriter animates this section
[Simplified Visual]

─── Even simpler ───                     ← if tapped again

Second simplification content...
[Second Visual]

[I didn't understand]  [Back]  [Next]    ← button stays at bottom
```

**FR-3**: Each simplification section includes:
- A visual separator line with warm text (e.g., "Let me break this down", "Even simpler", "One more way to think about it")
- The simplified explanation with full typewriter animation
- Its own PixiJS visual (if generated)

**FR-4**: After a new simplification is generated, the card auto-scrolls to the new section. The typewriter animation begins on the new section only — previously revealed content stays static.

**FR-5**: The "I didn't understand" button always appears at the bottom of the card, below all content (original + all simplifications). It remains accessible regardless of how many simplifications exist.

**FR-6**: The card's vertical scrolling (already supported via `overflow-y: auto` on `.focus-slide`) accommodates growing content naturally.

### 6.2 Backend Response Format

**FR-7**: The `POST /sessions/{id}/simplify-card` endpoint response changes from:
```json
{"action": "insert_card", "card": {...}, "card_id": "remedial_A_3_1", "insert_after": "A_3"}
```
to:
```json
{
  "action": "append_to_card",
  "source_card_idx": 3,
  "simplification": {
    "content": "...",
    "lines": [{"display": "...", "audio": "..."}],
    "audio_text": "...",
    "visual_prompt": "...",
    "visual_explanation": {...}
  },
  "depth": 1,
  "card_id": "remedial_A_3_1"
}
```

**FR-8**: The `SimplifiedCardOutput` schema adds a `lines` field — list of `{display, audio}` pairs matching the base card structure. This enables per-line typewriter animation and TTS sync.

**FR-9**: The simplification prompt instructs the LLM to return structured `lines` (one idea per line, each with display + audio text) instead of flat `content`.

### 6.3 Frontend State Management

**FR-10**: `ExplanationCard` gains a `simplifications` field:
```typescript
interface ExplanationCard {
  // ... existing fields
  simplifications?: {
    content: string;
    lines?: ExplanationLine[];
    audio_text?: string;
    visual_explanation?: VisualExplanation | null;
  }[];
}
```

**FR-11**: When the backend returns `append_to_card`, the frontend appends to the card's `simplifications[]` array. No new card is created. No carousel indices change. No navigation state changes.

**FR-12**: The carousel slide derivation (`carouselSlides` memo) does NOT change — the same card renders with more content, it doesn't create additional slides.

### 6.4 Card Index Contract

**FR-13**: `card_idx` has ONE canonical meaning everywhere — backend, frontend, persistence, replay, tests:
- **0-based index into `variant.cards_json`** (which includes the welcome card at index 0)
- Content cards start at index 1
- The welcome card (index 0) is never simplifiable (button hidden in frontend)
- Frontend `explanationCards` array maps 1:1 to `cards_json` — `explanationCards[i]` = `cards_json[i]`
- Frontend `carouselSlides` maps 1:1 to `explanationCards` during card_phase — `currentSlideIdx` = array index directly
- **No offset math anywhere.** Frontend sends `currentSlideIdx` to backend as `card_idx`. Backend uses it directly as the index into `all_cards`.

### 6.5 Per-Student Persistence

**FR-14**: New database table — **one row per (user, guideline, variant)**:
```sql
CREATE TABLE student_topic_cards (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    guideline_id    TEXT NOT NULL REFERENCES teaching_guidelines(id) ON DELETE CASCADE,
    variant_key     TEXT NOT NULL,
    explanation_id  TEXT NOT NULL,
    simplifications JSONB NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, guideline_id, variant_key)
);
CREATE INDEX idx_student_topic_cards_user ON student_topic_cards(user_id);
```

Key design decisions:
- **`UNIQUE (user_id, guideline_id, variant_key)`** — each variant's simplifications are stored separately. Switching from variant A to B doesn't destroy A's data. Switching back restores it.
- **`explanation_id`** — the `TopicExplanation.id` (UUID) at the time simplifications were saved. If explanations are regenerated, the UUID changes. On read, if the current explanation has a different ID, saved simplifications are discarded (stale guard). This is stronger than card-count comparison — catches same-count regenerations, reordered cards, and content changes.

**FR-15**: The `simplifications` JSONB column stores the overlay:
```json
{
  "3": [
    {"content": "...", "lines": [...], "audio_text": "...", "visual_explanation": {...}},
    {"content": "...", "lines": [...], "audio_text": "...", "visual_explanation": {...}}
  ],
  "7": [
    {"content": "...", "lines": [...], "audio_text": "...", "visual_explanation": {...}}
  ]
}
```
Keys are `card_idx` values (as strings, per FR-13 contract). Values are ordered lists of simplification objects.

**FR-16**: **Write path** — on each simplification event, upsert to `student_topic_cards`:
1. Load existing record for (user_id, guideline_id, variant_key) if any
2. Merge the new simplification into the `simplifications` dict under the correct card_idx
3. Upsert with current explanation_id and updated_at
4. Both the session state write and student_topic_cards write happen **in the same DB transaction** — no partial-failure states.

**FR-17**: **Read path** — on new Teach Me session creation:
1. After loading base cards from `TopicExplanation`, check `student_topic_cards` for (user_id, guideline_id, variant_key)
2. If found AND `explanation_id` matches the current `TopicExplanation.id`: attach `simplifications` to the corresponding cards
3. If found but `explanation_id` differs (explanations were regenerated): delete the stale record, start fresh
4. If not found OR user is anonymous: normal flow, no pre-loading

**FR-18**: Pre-loaded simplifications render inline from the start — no typewriter animation for pre-loaded content (treated as already-revealed). Typewriter only applies to newly generated simplifications during the current session.

**FR-19**: **Variant switch behavior** — when a student clicks "Explain differently":
1. The current variant's simplifications are already persisted (written on each simplification event)
2. The new variant loads fresh from `TopicExplanation`
3. Check `student_topic_cards` for (user_id, guideline_id, new_variant_key) — if the student previously simplified cards on this variant, those simplifications are restored
4. Session state's `remedial_cards` is reset for the new variant (or populated from saved data if found)
5. No data is lost — both variants' simplifications coexist as separate rows

**FR-20**: **Variant selection on revisit** — when creating a new session, use the student's most recently used variant (from `student_topic_cards.updated_at`) instead of always defaulting to variant "A". Fall back to first available variant if no saved data exists.

### 6.6 Simplification Content Quality

**FR-21**: The simplification prompt focuses on one strategy: break it down further, use simpler words, fill missing steps. No tiered depth levels — every simplification gets the same directive.

**FR-22**: The LLM receives all previous simplifications for the same card (so it avoids repeating the same approach) and the full lesson card list (for context).

**FR-23**: Each simplification must return structured `lines[]` matching the format:
```json
[
  {"display": "Think of 4 boxes in a row.", "audio": "Think of four boxes in a row."},
  {"display": "Each box has a name.", "audio": "Each box has a name."},
  {"display": "The first box is **Ones**.", "audio": "The first box is Ones."}
]
```

### 6.7 Loading UX

**FR-24**: While simplification is generating, show an animated skeleton/shimmer below the current card content where the new section will appear. The separator line ("Let me break this down") appears immediately.

**FR-25**: When generation completes, the skeleton is replaced with the actual content and typewriter animation begins.

**FR-26**: All navigation (Back/Next) remains disabled during generation (unchanged from v1).

### 6.8 Session State (Unchanged from v1)

**FR-27**: `card_phase.remedial_cards` continues to track simplifications in session state — this is the source of truth for the current session and for replay.

**FR-28**: `card_phase.confusion_events` continues to track per-card confusion — used for tutor context and analytics.

**FR-29**: Replay endpoint reconstructs cards with inline simplifications (instead of inserted cards).

## Technical Architecture

```
Student taps "I didn't understand" on card 3
    |
    v
Frontend: POST /sessions/{id}/simplify-card  { card_idx: 3 }
    |
    v
Backend: SessionService.simplify_card()
    |-- Load session state, validate card_phase active
    |-- Determine depth from remedial_cards[3] count
    |-- Gather context (card, all cards, prior attempts)
    |
    v
Orchestrator: generate_simplified_card()
    |-- Build prompt (break down further, simpler words, fill gaps)
    |-- Call LLM -> returns structured lines[] + visual_prompt
    |-- Generate PixiJS visual from visual_prompt
    |
    v
Backend:
    |-- Store in session.card_phase.remedial_cards[3]
    |-- Upsert to student_topic_cards (user_id, guideline_id)   <-- NEW
    |-- Log card_confusion_tap event
    |-- Persist session state
    |
    v
Response: { action: "append_to_card", source_card_idx: 3, simplification: {...} }
    |
    v
Frontend:
    |-- Append to explanationCards[card_idx].simplifications[]
    |-- Auto-scroll card to new section
    |-- Typewriter animation on new section only
    |-- No carousel index changes
```

```
Student revisits topic (new session)
    |
    v
Backend: create_new_session(user_id, guideline_id)
    |-- Load base cards from TopicExplanation (variant A)
    |-- Check student_topic_cards for (user_id, guideline_id)   <-- NEW
    |
    v
    Found? --> Attach saved simplifications to matching cards
    Not found? --> Normal flow, no pre-loading
    |
    v
Frontend receives cards with pre-loaded simplifications
    |-- Cards with simplifications render inline sections immediately
    |-- No typewriter for pre-loaded content
    |-- Student can tap "I didn't understand" for additional simplifications
```

## Impact on Existing Features

| Feature | Impact | Action Required |
|---------|--------|-----------------|
| Carousel navigation | Simplified — no card insertion, no index shifting | Remove splice logic, update to append-to-card |
| Card rendering | Cards render inline simplification sections | New section in card component |
| TypewriterMarkdown | Must support animating appended content | Extend component for dynamic sections |
| Replay/resume | Reconstructs cards with inline simplifications (not inserted cards) | Modify replay merge logic |
| Session creation | Checks student_topic_cards on teach_me session creation | New lookup in create_new_session |
| Variant switching | Updates student_topic_cards with new variant | Add upsert on variant switch |
| TTS/audio | Simplified sections get per-line audio (new — v1 didn't have this) | lines[] in prompt output |
| PixiJS visuals | Simplified sections get visuals (already in v1) | Render within card, not separate card |
| Analytics | card_confusion_tap events — unchanged | None |
| Bridge/tutor context | confusion_events — unchanged | None |

## Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| LLM call fails | Show error message in place of skeleton. Student stays on card, can retry. |
| Card grows very long (5+ simplifications) | Natural scrolling handles it. Consider: after 3 simplifications, change button text to "Want to try a different approach?" suggesting variant switch. |
| Student revisits but base cards were regenerated | `explanation_id` won't match → discard saved simplifications, delete stale record, start fresh. Log event for monitoring. |
| Anonymous user (no user_id) | Inline expansion works for current session. No persistence (student_topic_cards requires user_id). |
| Student simplifies, then variant-switches, then switches back | Each variant has its own row in `student_topic_cards`. Switching back restores the original variant's simplifications. No data loss. |
| Page refresh mid-generation | Request lost. On replay, previously saved simplifications render. Student can re-tap. |
| Pre-loaded simplification has stale visual (old PixiJS version) | Render as-is. PixiJS is sandboxed iframe — old code should still work. |

## v1 Scope (This PRD)

- Inline expansion rendering (same card, vertical stack)
- Structured `lines[]` output from simplification prompt
- Per-line typewriter + audio for simplified sections
- PixiJS visual per simplification section
- `student_topic_cards` table + repository
- Write on each simplification event
- Read on session creation (pre-load saved simplifications)
- Skeleton loading state during generation
- Auto-scroll to new section
- Backend response format change (`append_to_card`)
- Remove card insertion logic from frontend
- Replay reconstruction with inline format

## Out of Scope

- Progressive depth tiers (different prompt per depth) — keep it simple, one strategy
- Escalation to interactive mode after N simplifications
- Improving base cards from confusion data (Problem B — future content pipeline work)
- Proactive base card improvement from confusion data (Problem B — future pipeline work)
- Proactive simplification (reading time signals)
- Free-text "what confused you?" input

## Success Metrics

| Category | Metric | Target |
|----------|--------|--------|
| Bug fix | Simplified content visible to user after tap | 100% (currently 0% due to nav bug) |
| Engagement | % of students who scroll through simplified content | >80% |
| Effectiveness | % of simplifications after which student taps Next (not "I didn't understand" again) | >70% |
| Persistence value | % of returning students who benefit from pre-loaded simplifications | Track (no target yet) |
| Latency | P95 simplification generation time | <5 seconds |
| Session completion | Completion rate before vs after | No regression |
