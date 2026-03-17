# PRD: Pre-Computed Explanations

## Context & Problem

### What We Have Today

When a student starts a topic, the system:
1. **Generates a study plan on-the-fly** — LLM creates 3-5 teaching steps, each with scaffolding metadata (`teaching_approach`, `building_blocks`, `analogy`, `success_criteria`)
2. **Master tutor dynamically generates explanation content turn-by-turn** — using the study plan's scaffolding, the tutor produces explanation turns during the live session, tracking progress through an `ExplanationPhase` state machine (`not_started → opening → explaining → informal_check → complete`)
3. **Student navigates with "OK"** through explanation turns, each taking 20-30+ seconds

The explanation phase is the student's **first impression** of a topic. It's the moment that determines whether a kid feels "this is interesting" or "this is boring/confusing."

### What's Wrong

**High latency kills engagement.** Each explanation turn takes 20-30+ seconds. Young students lose attention. The "explain" phase is mostly non-interactive (students say "OK" to advance), yet pays the full cost of a live LLM call per turn.

**Quality is capped by real-time constraints.** The tutor must generate explanations instantly, which means:
- No time for multi-pass refinement (generate → critique → improve)
- Can't use higher reasoning effort without worsening latency
- No opportunity for carefully designed visuals or examples
- Explanation quality varies across sessions for the same topic

**Redundant computation.** The explanation for "Addition of Fractions" in Grade 5 is ~90% identical for every student. Regenerating it per-session wastes compute and money.

### Why This Matters

Explanation is the foundation of learning. A well-crafted explanation with clear language, relatable examples, and helpful visuals makes the difference between a student who "gets it" in 2 minutes and one who struggles for 10. Today we're generating this critical content under the worst possible constraints — live, rushed, with no review.

---

## Solution Overview

Make explanations a **first-class, pre-computed artifact** in the topic pipeline. Generate them offline after topic sync — so they're ready instantly when a student starts a session.

| Concept | Description |
|---------|-------------|
| **Pre-computed explanation** | A structured, multi-card explanation generated offline for each topic. Instant to serve. |
| **Multiple variants** | 2-3 explanation approaches per topic (e.g., analogy-based, visual-heavy, step-by-step). Served as fallbacks if the student doesn't understand the first. |
| **Explanation-aware tutor** | The tutor knows exactly what was shown and how, enabling coherent follow-up when it takes over dynamically. |
| **Graceful fallback chain** | Pre-computed variant A → variant B → dynamic tutor. Covers both happy path and "I still don't get it." |

---

## Requirements

### R1: Offline Explanation Generation (New Pipeline Stage)

Add a new stage **after topic sync** (post-sync), triggered as part of the same admin action or as a follow-up step:

```
Plan → Extract → Consolidate/Finalize → Sync → Generate Explanations → Study Plan → Tutor
```

**Why post-sync (not pre-sync):** Explanations are keyed by `guideline_id`, which is created during sync. Generating post-sync ensures a stable FK relationship. Since sync may delete/recreate guideline rows on re-sync, explanations are regenerated alongside — acceptable because the underlying topic content may have changed.

**Input:** The synced `TeachingGuideline` record — its freeform `guideline` text contains learning objectives, prerequisites, misconceptions, scope boundary, and depth requirements. The generation prompt parses these from the guideline text (same as the tutor does today). Also uses `prior_topics_context` to weave references to earlier topics into explanation cards naturally.

**Output:** 2-3 `ExplanationVariant` objects per topic, each containing an ordered list of `ExplanationCard` items.

**Each `ExplanationCard` contains:**
- `card_type`: "concept", "example", "visual", "analogy", "summary"
- `title`: Short heading for the card
- `content`: The explanation text — simple language, short sentences. Should naturally incorporate `prior_topics_context` references where relevant ("Remember how we learned about place value? Now let's use that to compare numbers.")
- `visual`: Optional structured visual (ASCII diagram, formatted example, styled text illustration). V1 uses text-based visuals only — no PixiJS or image generation.

**Each `ExplanationVariant` represents a fundamentally different teaching approach:**
- Variant A: Primary approach (e.g., analogy-driven with everyday examples)
- Variant B: Alternative approach (e.g., visual/diagram-heavy)
- Variant C (optional): Step-by-step procedural walkthrough

Variants must be genuinely different pedagogical strategies (different analogies, different sequencing, different emphasis), not the same explanation rephrased.

**Generation quality levers (enabled by offline processing):**
- Multi-pass: generate → self-critique against explanation principles (see `docs/principles/how-to-explain.md`) → refine
- Higher reasoning effort (`reasoning_effort="high"`)
- Deliberate visual planning per card
- Each variant is independently coherent

**LLM configuration:** One call per variant per topic. Since this runs offline, cost and latency are not constraints. Quality is the only priority.

### R2: Structured Storage

**New DB table: `topic_explanations`**

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `guideline_id` | UUID | FK to `teaching_guidelines` (cascade delete) |
| `variant_key` | VARCHAR | "A", "B", "C" |
| `variant_label` | VARCHAR | Human-readable: "Everyday Analogies", "Visual Walkthrough", etc. |
| `cards_json` | JSONB | Ordered list of `ExplanationCard` objects |
| `generator_model` | VARCHAR | Model used for generation |
| `created_at` | TIMESTAMP | When generated |

**Why a separate table (not a field on `teaching_guidelines`):**
- Multiple variants per topic
- Cards are structured data, not a text blob
- Can regenerate explanations without touching guidelines
- Supports future per-variant analytics (which variant works best)

**Cascade delete on `guideline_id`:** When sync deletes/recreates guideline rows, explanation rows are cleaned up automatically. The post-sync explanation generation step recreates them.

**No S3 backup.** Cards are small structured JSON — DB (JSONB) is sufficient and queryable. S3 storage is unnecessary complexity for this data shape.

**Book/chapter hierarchy:** Queryable via JOIN through `teaching_guidelines` (which has `book_id`, `chapter` fields). No denormalization needed on `topic_explanations`.

### R3: Study Plan Integration

**Clarification on current study plan behavior:** Study plans do not contain explanation text. They contain scaffolding metadata (`teaching_approach`, `building_blocks`, `analogy`, `success_criteria`) that the master tutor uses to dynamically generate explanation turns at session time. The latency problem is in the tutor's turn-by-turn generation, not in study plan creation.

**Changes:**
- When pre-computed explanations exist for a guideline, the study plan's "explain" step is annotated with `"explanation_source": "pre_computed"` to signal the session orchestrator to use card mode
- The study plan still defines the overall teaching sequence (explain → check → practice). Its scaffolding metadata (`building_blocks`, `analogy`, etc.) is retained — it's used if the session falls back to dynamic tutoring (variant exhaustion or topics without pre-computed explanations)
- **Study plan generation itself does not get faster** — the win is session-time latency (no LLM calls during the explanation phase)

**Fallback:** If no pre-computed explanation exists (old topics, edge cases), the session uses the current dynamic `ExplanationPhase` behavior unchanged. No breaking change.

### R4: Session Runtime — Card Phase vs. Explanation Phase

Pre-computed explanations introduce a new runtime mode that replaces the current `ExplanationPhase` state machine for topics that have pre-computed content.

**Current state machine (retained for dynamic fallback):**
```
not_started → opening → explaining (multi-turn, building_blocks tracked) → informal_check → complete
```

**New card mode (for pre-computed topics):**
```
card_phase (no LLM calls, card navigation) → transition_prompt → check/practice phases
```

**How it works:**
1. **Session creation** detects pre-computed explanations exist for the guideline
2. Session state enters `CardPhase` instead of `ExplanationPhase`
3. Pre-computed explanation cards (variant A) are returned as part of session initialization — **no LLM call, no `generate_welcome_message()`**
4. A short pre-computed welcome is prepended: *"Let's learn about [topic]! I'll walk you through it, and then we can talk about any questions."*
5. Frontend renders cards; student navigates with tap/swipe
6. After the last card, transition prompt: *"That's the overview! Is everything clear, or would you like me to explain it differently?"*
7. Student response determines next state:
   - **"Clear"** → Session transitions to check-understanding / practice phases (interactive tutor)
   - **"Explain differently"** → Load variant B cards (instant), remain in `CardPhase`
   - **All variants exhausted + still confused** → Session transitions to dynamic `ExplanationPhase` with full tutor, using study plan scaffolding as before

**What this replaces:**
- The `ExplanationPhase` state machine (`opening`, `explaining`, `informal_check` sub-phases) — skipped entirely for pre-computed topics
- The `generate_welcome_message()` LLM call — replaced by a pre-computed welcome string
- Building blocks tracking during explanation — the cards *are* the building blocks, pre-sequenced
- Minimum-turn enforcement and advancement guards during explanation — not applicable to card navigation

**What this does NOT replace:**
- `ExplanationPhase` for dynamic fallback (when all variants are exhausted)
- `ExplanationPhase` for topics without pre-computed explanations (backward compatibility)
- All post-explanation phases (check understanding, practice, Q&A)

**`student_shows_prior_knowledge` detection:** Does not apply during card phase (no student text input). This is an acceptable trade-off — prior knowledge is detected in the post-card interactive phase instead. If a student already knows the material, the check-understanding phase will surface that quickly.

**Hard-gated interaction during cards:** No text input during card phase. Navigation controls only (next/previous) plus an "I don't understand" button that triggers variant switch. Students are accustomed to swiping through content. Cards are short (15-30 seconds each per principle #7 in `how-to-explain.md`). Questions are asked after the explanation completes. An "ask mid-explanation" escape hatch may be added in v2 if usage data shows students dropping off mid-cards.

### R5: Frontend Explanation Experience

The explanation phase shifts from chat-style turns to a **card-by-card reading experience.**

**UX flow:**
1. Student opens a topic → sees pre-computed welcome + first explanation card immediately (no loading spinner, no LLM call)
2. Student taps/swipes to advance through cards — each card appears instantly
3. After the last card, transition message: *"That's the overview! Is everything clear, or would you like me to explain it differently?"*
4. Student responds:
   - **"Clear"** → Tutor moves to check-understanding / practice phase (interactive chat resumes)
   - **"Explain differently"** → Load variant B cards (instant again)
   - **Still confused after all variants** → Dynamic tutor takes over with personalized re-explanation

**Key UX properties:**
- Zero latency during explanation card navigation
- Progress indicator (card 3 of 7)
- Cards support rich content: styled text, formatted examples, ASCII diagrams, highlighted key terms
- No text input box during explanation phase — navigation controls + "I don't understand" button only
- V1 visual system: text-based visuals (formatted examples, ASCII diagrams, styled text). Separate from the chat's PixiJS visual pipeline. PixiJS integration is a future enhancement.

**Session state and history:**
- Card phase content is tracked in session state (which variant was shown, which cards were viewed)
- When chat resumes after cards, conversation history starts fresh from the transition prompt — card content is not replayed as chat messages
- On session resume/refresh, if the student was in card phase, restore card position from session state

**Frontend architecture:**
- New `ExplanationViewer` component: card-based, swipeable/tappable, renders card types (concept, example, visual, analogy, summary)
- Sits alongside `ChatSession` — explanation viewer is active during `CardPhase`, chat is active during interactive phases
- Requires new session initialization response shape: must include `explanation_cards` array + `session_phase: "card_phase"` alongside existing session data

### R6: Tutor Awareness of Pre-Computed Content

When the session transitions from pre-computed explanation to interactive tutoring, the tutor must know what was already shown — but efficiently.

**Inject a summary, not full card text.** The tutor's system prompt is already dense. Injecting 2-3 full card sets (7-12 cards each) would bloat token usage. Instead, inject:
- Card titles (the concept sequence)
- Key analogies and examples used
- Which variants the student saw
- Instruction: *"The student has already seen the following explanation approaches. Do not repeat these analogies or examples. If they're confused, try a fundamentally different approach."*

**Data flow:**
```
topic_explanations (DB)
  → session_service loads variant(s) shown
  → generates summary: titles + key analogies + variant labels
  → injected into tutor system prompt as {explanation_context} section
  → master_tutor_prompts uses this to avoid repetition
```

---

## Non-Goals

- **Personalized pre-computed explanations.** Explanations are generic (grade-appropriate). Personalization happens in the dynamic tutor phase after explanation. Future: we may generate age-band or persona variants, but not per-student.
- **Replacing the dynamic tutor.** The tutor remains essential for Q&A, re-explanation, check-understanding, and practice. Pre-computed explanations only replace the initial "explain" phase.
- **PixiJS or image generation in v1.** Visuals in v1 are text-based (ASCII diagrams, formatted examples, styled text). The card viewer has its own simple rendering — it does not use the chat's PixiJS visual pipeline. Image generation (DALL-E, etc.) and PixiJS integration are future enhancements.
- **Re-ingesting all books immediately.** Explanations generate for newly processed/synced topics. Existing topics can be backfilled on-demand.
- **Admin UI for editing explanations.** Initially, explanations are LLM-generated and reviewed by inspecting the DB output. A dedicated editor is a future tool.
- **Mid-explanation interruption.** V1 is hard-gated to card navigation. No freeform text input during card phase. May revisit in v2 based on usage data.

---

## Technical Approach (High-Level)

### New: Explanation Generator Service

- **New service:** `ExplanationGeneratorService` — takes a `TeachingGuideline` record, produces structured explanation variants
- **New prompts:** `explanation_generation.txt` (generate), `explanation_critique.txt` (self-review against principles)
- **Multi-pass pipeline:** Generate variant → critique against `how-to-explain` principles → refine → store
- **Storage:** `topic_explanations` table (JSONB). No S3 backup — cards are small structured JSON.
- **Trigger:** Runs post-sync as part of the same admin pipeline action, after `TeachingGuideline` rows are created/updated

### Modified: Topic Sync Service

- After syncing `TeachingGuideline` rows, trigger explanation generation for each synced guideline
- On re-sync (delete/recreate), cascade-deleted explanations are regenerated automatically
- Explanation generation can also run independently for backfilling existing topics

### Modified: Session Service

- On session creation, check for pre-computed explanations via `guideline_id`
- If found: set `session_phase: "card_phase"`, include `explanation_cards` in session initialization response, skip `generate_welcome_message()` LLM call
- If not found: fall back to current `ExplanationPhase` behavior unchanged
- Track in session state: current variant key, card index, variants already shown

### Modified: Session Orchestrator

- New `CardPhase` handling alongside existing `ExplanationPhase`
- `CardPhase` processes only navigation events (next card, previous card, "explain differently", "clear")
- No LLM calls during `CardPhase` — all responses are pre-computed or templated
- Transition from `CardPhase` to interactive phases triggers `{explanation_context}` injection into tutor prompt
- Fallback: when all variants exhausted and student still confused, transitions to `ExplanationPhase` with dynamic tutor

### Modified: Study Plan Generator

- Annotates "explain" steps with `"explanation_source": "pre_computed"` when pre-computed explanations exist
- Retains all scaffolding metadata (`building_blocks`, `analogy`, etc.) — needed for dynamic fallback
- No changes to the generation prompt's core logic

### Modified: Master Tutor System Prompt

- New `{explanation_context}` section: summary of shown cards (titles, key analogies, variant labels)
- Instructions not to repeat shown approaches
- Active only when transitioning from `CardPhase` to interactive tutoring

### Frontend Changes

- New `ExplanationViewer` component: card-based, swipeable/tappable, text-based visual rendering
- New session initialization response shape: `explanation_cards` array + `session_phase` field
- `ExplanationViewer` is active during `CardPhase`; `ChatSession` resumes for interactive phases
- Session state persistence: card position restored on refresh/resume
- Conversation history starts fresh from transition prompt — cards are not replayed as chat messages

### API / Protocol Changes

- Session creation response gains: `session_phase`, `explanation_cards`, `current_variant_key`
- New card navigation events (next, previous, switch_variant, mark_clear) — can be REST calls or WebSocket messages
- Session state must track card progress for resume/refresh scenarios

---

## Success Criteria

1. **Zero latency during explanation.** Student sees explanation cards instantly — no loading spinners, no 20-30 second waits.
2. **Higher explanation quality.** Explanations use simple language, relatable examples, and structured visuals. A curriculum expert rates them higher than current dynamic explanations.
3. **Smooth fallback chain.** Variant A → Variant B → dynamic tutor works seamlessly. The tutor doesn't repeat what was already shown.
4. **No regression in interactive tutoring.** The Q&A, check-understanding, and practice phases work exactly as before, with the added benefit of the tutor knowing what was already explained.
5. **Pipeline integration.** Explanation generation fits naturally as a post-sync step without breaking existing flows.
6. **Backward compatibility.** Topics without pre-computed explanations use the existing `ExplanationPhase` dynamic behavior unchanged.
7. **Qualitative.** A kid opening a topic for the first time feels "this makes sense" within the first 30 seconds.
