# PRD: Session Plan Redesign — Explanation-Aware Interactive Plans

**Status:** Draft
**Date:** 2026-03-19

---

## Context & Problem

### What We Have Today

Three independently generated components power teach_me sessions:

1. **Teaching Guidelines** (offline) — Curriculum scope: objectives, depth, prerequisites, misconceptions, scope boundary
2. **Pre-Computed Explanations** (offline) — 3 variants of 5-15 card explanations, each with teaching_notes, key analogies/examples
3. **Study Plans** (session-time) — 3-5 steps with types (explain/check/practice), building blocks, analogies, teaching approaches

The study plan generator receives only the guideline and student context. It has no knowledge of the pre-computed explanations.

### What's Wrong

**The study plan and explanations are uncoordinated.** Both are generated from the same guideline but independently. This creates:

- **Redundant explain steps.** The study plan generates "explain" steps with building blocks and analogies. But explanation cards already cover the concept comprehensively. The tutor gets two conflicting teaching roadmaps.
- **Contradictory analogies.** Cards explain addition using "marble bags." The study plan independently invents "cricket scores" as the analogy for the same concept. The tutor must reconcile.
- **Misaligned building blocks.** Cards build understanding as [what is a group → combining groups → writing equations]. Study plan building blocks might be [number bonds → part-whole → regrouping]. The tutor tracks card-covered vs. plan-covered blocks separately.
- **Wasted generation.** The study plan's explain-step scaffolding (approach, building_blocks, analogy, min_turns) is effectively discarded when cards exist. The pacing directive overrides it with "QUICK-CHECK (cards covered this)."

**The workaround is coarse.** `card_covered_concepts` is a set of concept names. The pacing directive says "cards covered this, don't re-explain." But it doesn't know WHICH building blocks the cards covered or HOW. The tutor gets a vague "don't repeat" instruction instead of a specific "the student learned X via Y, now check Z."

### Why This Matters

The interactive phase after cards is where the student proves understanding. A well-designed session plan should pick up exactly where the cards left off — referencing the same analogies, building on the same progression, testing the specific concepts that were explained. Today it's a disconnected follow-up that the tutor must stitch together on its own.

---

## Solution Overview

Redesign the study plan as a **post-explanation interactive session plan**. It receives explanation data as input and generates steps for what happens AFTER the student reads the cards.

| Before | After |
|--------|-------|
| Study plan doesn't know about explanations | Session plan receives explanation summary + card structure |
| Has "explain" steps with independent building blocks | No explain steps — cards handle explanation |
| Step types: explain, check, practice | Step types: check_understanding, guided_practice, independent_practice, extend |
| Generates its own analogies | References card analogies explicitly |
| Pacing directive hacks around card overlap | Plan is designed for post-card context natively |

---

## Requirements

### R1: Session Plan Generator — New Inputs

The session plan generator receives explanation data alongside the guideline.

**New inputs:**

```python
generate_session_plan(
    guideline: TeachingGuideline,         # Curriculum scope (as before)
    explanation_summary: dict,            # From TopicExplanation.summary_json
    card_titles: list[str],              # Ordered list of card titles
    student_context: Optional[StudentContext],  # Personalization (as before)
)
```

**Explanation summary fields available to the prompt:**

| Field | Example | Usage |
|-------|---------|-------|
| `teaching_notes` | "Explained addition using marble bag analogy — started with combining two bags, built to writing equations. Key insight: addition = joining groups." | Core context for what was taught and how |
| `key_analogies` | ["marble bag", "cricket score runs"] | Analogies to reference in practice |
| `key_examples` | ["3 + 4 = 7 with marbles", "23 + 14 = 37 cricket runs"] | Examples to build on |
| `approach_label` | "Everyday Analogies" | Which pedagogical approach cards used |
| `card_titles` | ["What is Addition?", "Combining Groups", "The + and = Signs", "Practice Together", "Quick Recap"] | The progressive building blocks from cards |

The `teaching_notes` field is the richest input — it's written as a briefing for "another tutor who will continue the session."

### R2: New Step Types

Remove the `explain` step type. Replace with four interactive step types:

**`check_understanding`** — Verify the student absorbed card content.
- Quick recall/comprehension questions
- References specific card concepts: "Remember the marble bag idea? What happened when we combined the bags?"
- Probes for specific misconceptions from the guideline
- Light scaffolding, not re-teaching

**`guided_practice`** — Work through problems together with tutor support.
- Tutor walks through a problem step by step
- References card analogies: "Just like combining marble bags, let's try 5 + 3"
- Increasing difficulty within the step
- Tutor provides hints and feedback

**`independent_practice`** — Student solves problems with minimal support.
- Multiple problems of appropriate difficulty
- Tutor only intervenes on errors
- Tests procedural fluency, not just recall

**`extend`** — Apply concepts to new contexts or harder variations.
- Builds on earlier practice: "Now instead of marbles, what if we use bigger numbers?"
- Connects to real-world applications
- Tests transfer, not just memorization
- Uses student interests for personalization

### R3: Session Plan Step Model

**New `SessionPlanStep` model:**

```python
class SessionPlanStep(BaseModel):
    step_id: int
    type: Literal["check_understanding", "guided_practice", "independent_practice", "extend"]
    concept: str                              # What concept/skill this step focuses on
    description: str                          # What the tutor should do in this step
    card_references: list[str]                # Card concepts/analogies to reference
    misconceptions_to_probe: list[str]        # What errors to watch for
    success_criteria: str                     # How to know the student has passed this step
    difficulty: Literal["easy", "medium", "hard"]
    personalization_hint: Optional[str]       # How to use student interests
```

**Compared to current `StudyPlanStep`:**

| Current Field | New Field | Change |
|------|-------|--------|
| `type: explain/check/practice` | `type: check_understanding/guided_practice/independent_practice/extend` | New types |
| `content_hint` | `description` | Richer, references cards |
| `explanation_approach` | Removed | Cards handle this |
| `explanation_building_blocks` | Removed | Cards handle this |
| `explanation_analogy` | `card_references` | References cards, doesn't invent new ones |
| `min_explanation_turns` | Removed | No explain phase |
| `question_type` | Part of `description` | Folded in |
| `question_count` | Part of `description` | Folded in |
| — | `misconceptions_to_probe` | New: from guideline misconceptions |
| — | `difficulty` | New: progressive difficulty |
| — | `success_criteria` | Moved from generator metadata to per-step |
| — | `personalization_hint` | New: student interest hooks |

### R4: Session Plan Generator Prompt

The new prompt instructs the LLM to design an interactive follow-up session, not a teaching plan.

**Prompt structure:**

```
You are designing the INTERACTIVE SESSION that follows pre-computed explanation cards.

## What The Student Already Learned
The student just read explanation cards for this topic. Here's what they covered:

Topic: {topic}
Grade: {grade}
Approach: {approach_label}
Card Progression: {card_titles as numbered list}
Teaching Summary: {teaching_notes}
Key Analogies Used: {key_analogies}
Key Examples Used: {key_examples}

## Curriculum Scope
{guideline_text}

## Common Misconceptions To Address
{common_misconceptions}

{student_personality_section}

## Your Task
Design 3-5 interactive steps for AFTER the student reads the cards.
The student has the conceptual foundation — your job is to CHECK their understanding,
let them PRACTICE applying it, and EXTEND to harder problems.

## Rules
- Do NOT re-explain what the cards covered. The student already read them.
- REFERENCE the card analogies and examples. Build on them, don't introduce competing ones.
- Start easy (check recall), progress to harder (apply, extend).
- Every step must probe at least one common misconception.
- Use the student's interests for practice problems when possible.
- 3-5 steps total. Each step should take 3-8 minutes.
- Think about what a great tutor would do AFTER showing someone a lesson —
  they'd check understanding, then practice together, then let the student try alone.

## Output Schema
{json_schema}
```

### R5: Session Plan Storage

Reuse the existing `study_plans` DB table. The `plan_json` field stores the new structure.

**Schema change:** None needed. `plan_json` is a Text/JSONB field that stores whatever the generator produces. The new format is:

```json
{
  "steps": [
    {
      "step_id": 1,
      "type": "check_understanding",
      "concept": "What are addends and sum",
      "description": "Quick recall check. Ask the student to identify addends and sum in a simple equation using the marble bag analogy from the cards.",
      "card_references": ["marble bag analogy", "combining groups"],
      "misconceptions_to_probe": ["confusing addends with sum"],
      "success_criteria": "Student correctly identifies addends and sum in 2 out of 3 examples",
      "difficulty": "easy",
      "personalization_hint": "Use cricket scores if student likes cricket"
    }
  ],
  "metadata": {
    "plan_version": 2,
    "explanation_variant": "A",
    "estimated_duration_minutes": 20,
    "is_generic": false
  }
}
```

**Version flag:** `plan_version: 2` distinguishes new session plans from legacy study plans. The topic adapter handles both formats.

### R6: Topic Adapter — Convert New Format to StudyPlan Model

The `topic_adapter.py` converts stored `plan_json` into `StudyPlan` model used by the session.

**Changes:**
- Detect `plan_version` to choose conversion path
- Map new step types to the `StudyPlanStep` model (expand the `type` Literal to include new types)
- Populate new fields (`card_references`, `misconceptions_to_probe`, `difficulty`, `success_criteria`, `personalization_hint`)
- Legacy plans (version 1) continue to work unchanged

### R7: Master Tutor Prompt — Session Plan Section

Update how the study plan is formatted in the system prompt. Currently:

```
Step 1 [explain] Introduction to Fractions: Use pizza slices...
Step 2 [check] Fraction Basics
Step 3 [practice] Fraction Practice
```

New format:

```
### Session Plan (post-explanation interactive steps)

The student has read explanation cards. Your job is to check understanding and practice.

Step 1 [check_understanding] What are addends and sum
  Ask recall questions using the marble bag analogy from the cards.
  Watch for: confusing addends with sum
  Pass when: Student identifies addends and sum correctly in 2+ examples

Step 2 [guided_practice] Apply addition to simple problems
  Work through problems together, referencing the combining groups idea.
  Watch for: forgetting to count all items when combining
  Pass when: Student solves 2 problems with minimal hints

Step 3 [independent_practice] Solve addition equations
  Student works problems independently. Only help on errors.
  Watch for: writing sum as an addend
  Pass when: 3 out of 4 correct without help

Step 4 [extend] Addition with bigger numbers
  Apply addition to 2-digit numbers. Use cricket scores.
  Watch for: not regrouping when ones exceed 9
  Pass when: Student explains regrouping in own words
```

This gives the tutor explicit instructions per step: what to do, what to watch for, when to advance.

### R8: Remove Explanation Phase State Machine for Card Sessions

Currently, the orchestrator maintains an `ExplanationPhase` state machine (opening → explaining → informal_check → complete) for explain steps, tracking building blocks covered.

**For sessions with pre-computed explanations (all sessions going forward):**
- No explain steps exist in the session plan
- The `ExplanationPhase` tracking code becomes dead for these sessions
- The pacing directive no longer needs the "QUICK-CHECK (cards covered this)" workaround — there are no explain steps to override

**Changes:**
- `_build_explanation_context()` returns empty for new-format plans (no explain steps)
- `_compute_pacing_directive()` simplified — new step types get appropriate directives:
  - `check_understanding` → "CHECK: Ask recall questions. Reference {card_references}."
  - `guided_practice` → "GUIDE: Work through problems together. Start easy."
  - `independent_practice` → "PRACTICE: Let the student work. Only intervene on errors."
  - `extend` → "EXTEND: Apply to new contexts. Build on earlier practice."
- `card_covered_concepts` set no longer needed — session plan is inherently post-card

### R9: Session Service — Load Explanations for Plan Generation

**Session creation flow changes:**

```
Current:
1. Load guideline
2. Load study plan (or generate from guideline + student_context)
3. Load explanations → card phase
4. Build precomputed_explanation_summary for tutor prompt

New:
1. Load guideline
2. Load explanations (always exist)
3. Generate session plan from guideline + explanation summary + student_context
4. Initialize card phase
```

The key change: explanation loading moves BEFORE plan generation, so explanation data can be passed to the generator.

**Caching:** Session plans can still be cached per user+guideline. But they should be regenerated if the explanation variant changes (unlikely — variants are stable after generation).

### R10: Pre-Computed Explanation Summary — Simplified Injection

The current system builds `precomputed_explanation_summary` and injects it into the tutor prompt. With the new session plan, this is still needed (the tutor should know what analogies/examples were used), but the session plan steps ALSO reference card content. This creates natural coherence:

- System prompt: "Student read cards using marble bag analogy..."
- Step 1: "Ask recall questions using the marble bag analogy from the cards"
- Tutor output: "Remember the marble bags we talked about? What happened when..."

The summary injection (`{precomputed_explanation_summary_section}`) stays as-is. The session plan steps add step-level specificity.

---

## Non-Goals

- **Changing how explanations are generated.** Explanation generation pipeline is unchanged. This PRD only changes what happens downstream of explanations.
- **Changing the card phase UX.** Students still read cards the same way. Only what happens AFTER cards changes.
- **Supporting sessions without explanations.** All topics have pre-computed explanations. No fallback to dynamic explanation needed.
- **Changing exam or clarify_doubts modes.** This only affects teach_me mode.
- **Real-time plan adaptation.** Mid-session plan regeneration (feedback-driven) is out of scope. The current feedback mechanism can be updated separately.

---

## Technical Approach

### Modified: Study Plan Generator Service
- New prompt template: `session_plan_generator.txt`
- New inputs: explanation summary, card titles alongside guideline and student context
- New output schema matching the `SessionPlanStep` structure
- Old prompt retained for backward compatibility (plan_version detection)

### Modified: Study Plan Model (`study_plan.py`)
- Expand `StudyPlanStep.type` Literal to include new types
- Add new fields: `card_references`, `misconceptions_to_probe`, `difficulty`, `success_criteria`, `personalization_hint`
- Old fields (`explanation_approach`, `explanation_building_blocks`, etc.) become Optional/deprecated

### Modified: Topic Adapter (`topic_adapter.py`)
- Detect plan_version in `_convert_study_plan()`
- Version 2: map new step types and fields directly
- Version 1: existing conversion logic unchanged

### Modified: Session Service (`session_service.py`)
- Reorder session creation: load explanations before generating plan
- Pass explanation summary to plan generator
- Remove `_extract_card_covered_concepts()` (no longer needed)
- Simplify `card_covered_concepts` usage

### Modified: Master Tutor Agent (`master_tutor.py`)
- New `_format_session_plan_steps()` for version 2 plans
- New pacing directives for new step types
- `_build_explanation_context()` returns empty for new-format plans
- Simplified `_compute_pacing_directive()` — no card-covered workaround

### Modified: Master Tutor Prompts (`master_tutor_prompts.py`)
- Update study plan section header and format
- Add step-type-specific tutor instructions
- Remove explain-step-specific rules (building block tracking, min turns)

---

## Success Criteria

1. **Coherent analogies.** The session plan references the same analogies and examples as the explanation cards. No competing metaphors.
2. **No redundant explanation.** The tutor doesn't re-explain what cards already covered. Check-understanding steps verify, not re-teach.
3. **Progressive difficulty.** Steps go from easy (recall) to hard (extend). The difficulty field enforces this.
4. **Misconception coverage.** Every guideline misconception appears in at least one step's `misconceptions_to_probe`.
5. **Card content referenced.** Every step has at least one `card_reference` connecting it to the explanation.
6. **Backward compatible.** Legacy study plans (version 1) continue to work. New plans are version 2.
7. **Qualitative.** The tutor's interactive phase feels like a natural continuation of the cards, not a disconnected follow-up.
