# PRD: Pre-Computed Explanations

## Context & Problem

### What We Have Today

When a student starts a topic, the system:
1. **Generates a study plan on-the-fly** — LLM creates 3-5 teaching steps including an "explain" step
2. **Dynamically generates explanation content turn-by-turn** — each sentence/paragraph is an LLM call during the live session
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

Make explanations a **first-class, pre-computed artifact** in the topic pipeline. Generate them offline during book ingestion — after topic finalization, before sync — so they're ready instantly when a student starts a session.

| Concept | Description |
|---------|-------------|
| **Pre-computed explanation** | A structured, multi-card explanation generated offline for each topic. Instant to serve. |
| **Multiple variants** | 2-3 explanation approaches per topic (e.g., analogy-based, visual-heavy, step-by-step). Served as fallbacks if the student doesn't understand the first. |
| **Explanation-aware tutor** | The tutor knows exactly what was shown and how, enabling coherent follow-up when it takes over dynamically. |
| **Graceful fallback chain** | Pre-computed variant A → variant B → dynamic tutor. Covers both happy path and "I still don't get it." |

---

## Requirements

### R1: Offline Explanation Generation (New Pipeline Stage)

Add a new stage after topic finalization (Stage 3) and before sync (Stage 4):

```
Plan → Extract → Consolidate/Finalize → Generate Explanations → Sync → Study Plan → Tutor
```

**Input:** Finalized topic with merged guidelines, learning objectives, prerequisites, misconceptions, scope boundary, and `prior_topics_context`.

**Output:** 2-3 `ExplanationVariant` objects per topic, each containing an ordered list of `ExplanationCard` items.

**Each `ExplanationCard` contains:**
- `card_type`: "concept", "example", "visual", "analogy", "summary"
- `title`: Short heading for the card
- `content`: The explanation text — simple language, short sentences
- `visual`: Optional structured visual description (ASCII diagram, image prompt, or reference to a pre-generated image)

**Each `ExplanationVariant` represents a different teaching approach:**
- Variant A: Primary approach (e.g., analogy-driven with everyday examples)
- Variant B: Alternative approach (e.g., visual/diagram-heavy)
- Variant C (optional): Step-by-step procedural walkthrough

**Generation quality levers (enabled by offline processing):**
- Multi-pass: generate → self-critique against explanation principles (see `docs/principles/how-to-explain.md`) → refine
- Higher reasoning effort (`reasoning_effort="high"`)
- Deliberate visual planning per card
- Each variant is independently coherent (not just a reshuffled version of another)

**LLM configuration:** One call per variant per topic. Since this runs offline during ingestion, cost and latency are not constraints. Quality is the only priority.

### R2: Structured Storage

**New DB table: `topic_explanations`**

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `guideline_id` | UUID | FK to `teaching_guidelines` |
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

### R3: Study Plan Integration

The study plan's "explain" step changes from "generate explanation content" to "serve pre-computed explanation."

**Changes to study plan generation:**
- When a pre-computed explanation exists, the "explain" step references it: `"source": "pre_computed", "variant_key": "A"`
- The study plan still defines the overall sequence (explain → check → practice), but the explain step's content is pre-built
- Study plan generation becomes faster since it doesn't need to plan explanation content

**Fallback:** If no pre-computed explanation exists (old topics, edge cases), the study plan falls back to the current dynamic explanation behavior. No breaking change.

### R4: Frontend Explanation Experience

The explanation phase shifts from chat-style turns to a **card-by-card reading experience.**

**UX flow:**
1. Student opens a topic → sees first explanation card immediately (no loading spinner)
2. Student taps/swipes to advance through cards — each card appears instantly
3. After the last card, a transition message: *"That's the overview! Is everything clear, or would you like me to explain it differently?"*
4. Student responds:
   - **"Clear"** → Tutor moves to check-understanding / practice phase (interactive)
   - **"Explain differently"** → Load variant B cards (instant again)
   - **Still confused after all variants** → Dynamic tutor takes over with personalized re-explanation

**Key UX properties:**
- Zero latency during explanation card navigation
- Progress indicator (card 3 of 7)
- Cards support rich content: text, visuals/diagrams, highlighted examples
- No text input box during explanation phase — just navigation controls + "I don't understand" button

### R5: Tutor Awareness of Pre-Computed Content

When the session transitions from pre-computed explanation to interactive tutoring, the tutor must know:

1. **What was explained** — the full content of the variant(s) shown
2. **How it was explained** — which analogies, examples, visuals were used
3. **Which variants were seen** — so it doesn't repeat the same approach

**Implementation:** Inject the shown explanation content into the tutor's context (system prompt or conversation history preamble). The tutor prompt should include instructions like: *"The student has already seen the following explanation. Do not repeat these analogies. If they're confused, try a fundamentally different approach."*

**Data flow:**
```
topic_explanations (DB)
  → session_service loads variant(s) shown
  → injected into tutor system prompt as "explanation_context"
  → master_tutor_prompts uses {explanation_context} section
```

---

## Non-Goals

- **Personalized pre-computed explanations.** Explanations are generic (grade-appropriate). Personalization happens in the dynamic tutor phase after explanation. Future: we may generate age-band variants, but not per-student.
- **Replacing the dynamic tutor.** The tutor remains essential for Q&A, re-explanation, check-understanding, and practice. Pre-computed explanations only replace the initial "explain" phase.
- **Image generation in v1.** Visuals in v1 are structured text descriptions (ASCII diagrams, formatted examples). Actual image generation (DALL-E, etc.) is a future enhancement.
- **Re-ingesting all books immediately.** Explanations generate for newly processed topics. Existing topics can be backfilled on-demand.
- **Admin UI for editing explanations.** Initially, explanations are LLM-generated and reviewed by inspecting the DB/S3 output. A dedicated editor is a future tool.

---

## Technical Approach (High-Level)

### New: Explanation Generator Service

- **New service:** `ExplanationGeneratorService` — takes a finalized topic + guidelines, produces structured explanation variants
- **New prompts:** `explanation_generation.txt` (generate), `explanation_critique.txt` (self-review against principles)
- **Multi-pass pipeline:** Generate variant → critique against `how-to-explain` principles → refine → store
- **Storage:** Cards JSON in DB (`topic_explanations` table) + S3 backup at `books/{book_id}/chapters/{ch_num}/output/explanations/{topic_key}/variant_{key}.json`

### Modified: Topic Sync Service

- After syncing `TeachingGuideline` rows, also sync/generate explanation variants for each topic
- Or: explanation generation runs as a separate post-sync step triggered by the same admin action

### Modified: Session Service

- On session creation, load pre-computed explanations for the guideline
- Pass explanation content to the frontend as part of session initialization
- Track which variants the student has viewed in session state

### Modified: Study Plan Generator

- "explain" step checks for pre-computed explanations
- If available: references them instead of planning dynamic explanation content
- Study plan still controls the overall flow (explain → check → practice)

### Modified: Tutor System Prompt

- New `{explanation_context}` section injected when transitioning from pre-computed to interactive
- Contains the shown explanation content + instructions not to repeat

### Frontend Changes

- New `ExplanationViewer` component: card-based, swipeable/tappable, no text input
- Transition UI: "Clear / Explain differently" choice after last card
- Integration with existing `ChatSession`: explanation viewer replaces chat during explain phase, chat resumes for interactive phase

---

## Success Criteria

1. **Zero latency during explanation.** Student sees explanation cards instantly — no loading spinners, no 20-30 second waits.
2. **Higher explanation quality.** Explanations use simple language, relatable examples, and structured visuals. A curriculum expert rates them higher than current dynamic explanations.
3. **Smooth fallback chain.** Variant A → Variant B → dynamic tutor works seamlessly. The tutor doesn't repeat what was already shown.
4. **No regression in interactive tutoring.** The Q&A, check-understanding, and practice phases work exactly as before, with the added benefit of the tutor knowing what was already explained.
5. **Pipeline integration.** Explanation generation fits naturally into the existing ingestion pipeline without breaking existing flows.
6. **Qualitative.** A kid opening a topic for the first time feels "this makes sense" within the first 30 seconds.
