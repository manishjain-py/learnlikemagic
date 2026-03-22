# PRD: Interactive Explanation Visuals (Virtual Manipulatives)

**Date:** 2026-03-23
**Status:** Draft
**Author:** PRD Generator + Manish
**Depends on:** [Animated Explanation Visuals PRD](../animated-explanation-visuals/prd.md)

---

## 1. Problem Statement

The animated visuals on explanation cards help students *see* concepts, but students can't *do* anything with them. Research on virtual manipulatives shows that kids learn significantly better when they can manipulate objects — dragging 1 ball into a group of 9 to discover "9 + 1 = 10" builds deeper understanding than watching it happen. The current visuals are view-only: tap "Visualise", watch, replay. There's no way for a student to interact with the scene.

Adding interactivity transforms visuals from illustrations into learning tools — and makes the app more attractive and playful for kids, turning concept discovery into something that feels like play.

---

## 2. Goal

Add interactive visual templates to pre-computed explanation cards so students can manipulate objects (drag, slide, tap, sort) to discover concepts through hands-on exploration.

---

## 3. User Stories

- As a **student**, I want to drag objects in a visual to discover the answer myself, so that I understand the concept deeply instead of just watching.
- As a **student**, I want clear visual feedback when I interact (objects follow my finger, drop zones glow), so it feels responsive and fun.
- As an **admin**, I want interactive visuals to be generated automatically during the enrichment pipeline, so no manual authoring is needed per topic.
- As a **product owner**, I want a template-based approach where LLMs select and parameterize tested templates, so interactive visuals are reliable and don't break for kids.

---

## 4. Functional Requirements

### 4.1 New Visual Type: `interactive_visual`

- **FR-1:** The animation enrichment pipeline MUST support a new output type: `interactive_visual`, alongside existing `static_visual` and `animated_visual`.
- **FR-2:** The decision prompt MUST be updated to consider `interactive_visual` when a concept benefits from student manipulation — e.g., combining groups (addition), splitting sets (subtraction/division), positioning on a number line (ordering), sorting into categories (classification).
- **FR-3:** Selection criteria for `interactive_visual`:
  - **Yes**: Concepts where physically doing the operation builds understanding (counting, grouping, ordering, classifying, adjusting values)
  - **No**: Concepts where motion alone teaches (transformations, sequential processes) — use `animated_visual` instead
  - **No**: Concepts where a diagram suffices (labeling parts, showing structure) — use `static_visual`
  - **Default to animated over interactive when in doubt** — animation is simpler and more reliable

### 4.2 Template-Based Architecture

- **FR-4:** Interactive visuals MUST use human-authored PixiJS templates, NOT LLM-generated interactive code. LLMs are unreliable at generating drag-and-drop logic, hit testing, and state management.
- **FR-5:** Each template MUST be a self-contained JavaScript module that:
  - Receives a JSON `params` object with content-specific data (objects, labels, positions, goals)
  - Receives `app` (PIXI.Application) and `PIXI` as arguments (same as current visuals)
  - Handles all interaction logic internally (drag, snap, feedback, goal checking)
  - Posts interaction results to parent via `postMessage` (for analytics/future use)
- **FR-6:** The LLM's job is limited to:
  - Selecting which template fits the concept
  - Filling a JSON params object that matches the template's schema
  - This is structured output, not code generation — dramatically more reliable
- **FR-7:** Each template MUST define a JSON schema for its params, used for LLM output validation.

### 4.3 Starter Templates (Prioritized)

Six templates, implemented in priority order:

- **FR-8: `drag-between-containers`** — Move objects between two or more labeled containers. Use cases: addition (drag 1 apple to group of 9 → "9 + 1 = 10"), subtraction (remove items), grouping (make groups of 5).
  - Params: objects (shape, color, label, count), containers (label, initial count), goal (target counts per container), success message
- **FR-9: `drag-to-number-line`** — Position markers on a number line. Use cases: number ordering, fractions, rounding, comparing values.
  - Params: number line range (min, max, step), markers to place (value, label, color), snap positions, tolerance
- **FR-10: `slider-adjust`** — Slide to change a value with real-time visual update. Use cases: fractions (adjust numerator/denominator, bar fills), scaling (resize shape), percentages.
  - Params: slider range (min, max, step), initial value, visual binding (what updates), labels, goal value
- **FR-11: `sort-and-classify`** — Drag items into labeled category buckets. Use cases: even/odd, shapes by property, greater/less than, word types.
  - Params: items (label, shape, correct category), categories (name, color), success message
- **FR-12: `step-by-step-build`** — Advance through multi-step operations with student agency. Use cases: long division steps, carrying in addition, multi-step word problems.
  - Params: steps (instruction, expected action, visual state), hints per step
- **FR-13: `tap-to-reveal`** — Tap hidden elements to reveal them in sequence. Use cases: counting, sequencing, cause-and-effect, matching.
  - Params: items (position, hidden content, reveal order), reveal mode (any order vs. sequence), completion message

### 4.4 Interaction Design Rules (Enforced in All Templates)

- **FR-14:** Touch targets MUST be 64x64px minimum with 16px spacing between interactive elements.
- **FR-15:** Single-finger interactions only. No pinch, rotate, or multi-touch gestures. Only: tap, drag-and-drop.
- **FR-16:** Every touch MUST produce visual feedback:
  - Drag: object follows finger, origin shows ghost/shadow, valid drop zones highlight
  - Drop on valid target: snap to position, brief green glow
  - Drop on invalid target: spring back to origin, brief orange highlight + gentle shake
  - Tap: brief scale pulse (1.1x) on interactive elements
- **FR-17:** Undo MUST always work — students can drag objects back to their original position.
- **FR-18:** The interactive visual MUST be self-contained — it shows its own success feedback (e.g., "9 + 1 = 10!" label appears, confetti-free success indicator) without requiring tutor intervention.
- **FR-19:** No sound effects in v1. Visual-only feedback.
- **FR-20:** No decorative interaction. Every draggable element, every tappable target MUST serve the concept being taught. If an element isn't part of the learning goal, it MUST NOT be interactive.

### 4.5 Delayed Feedback Pattern

- **FR-21:** Interactive visuals MUST use the "commit-then-reveal" pattern inspired by Desmos:
  1. Student performs the action (drag, slide, place)
  2. Visual does NOT immediately show right/wrong during the action
  3. A "Check" button or completion trigger (all items placed) reveals the result
  4. Result shown: correct placements stay with success indicator, incorrect placements highlighted gently with the correct answer shown
- **FR-22:** This prevents mindless guess-and-check. The student commits to their answer before seeing feedback.
- **FR-23:** After revealing results, a "Try Again" button MUST reset the interactive to its initial state for retry.

### 4.6 Storage

- **FR-24:** Interactive visuals MUST be stored in the same `visual_explanation` object within `cards_json`, with these additions:
  ```json
  {
    "visual_explanation": {
      "output_type": "interactive_visual",
      "title": "Make 10!",
      "visual_summary": "Student drags 1 apple from box A (9 apples) to box B to discover 9 + 1 = 10",
      "template_id": "drag-between-containers",
      "template_params": {
        "objects": [{ "shape": "circle", "color": "0x4ECDC4", "emoji": "apple", "count": 9 }],
        "containers": [
          { "label": "Box A", "initial": 9 },
          { "label": "Box B", "initial": 0 }
        ],
        "goal": { "Box B": 1 },
        "success_message": "9 + 1 = 10!"
      }
    }
  }
  ```
- **FR-25:** Interactive visuals do NOT store `pixi_code`. The `template_id` + `template_params` replace it. The template code is bundled in the frontend.
- **FR-26:** The `ExplanationCard` model and `CardVisualExplanation` model MUST add optional fields: `template_id` (string) and `template_params` (dict/JSON). Existing `pixi_code` field remains for static/animated visuals.
- **FR-27:** No database migration needed — these fields live inside the existing JSONB `cards_json` column.

### 4.7 Pipeline Changes

- **FR-28:** The enrichment pipeline's Step 1 (decision + spec) MUST be updated:
  - New output option: `interactive_visual` with `template_id` selection
  - Prompt includes the list of available templates with their param schemas and example use cases
  - For `interactive_visual`, the spec step outputs `template_id` + `template_params` JSON instead of a visual spec
- **FR-29:** Step 2 (code generation) is SKIPPED for `interactive_visual` — there is no PixiJS code to generate. The template is pre-built.
- **FR-30:** Validation for `interactive_visual`:
  - `template_id` MUST match a known template
  - `template_params` MUST validate against the template's JSON schema
  - If validation fails, retry once with the schema error fed back to the LLM. If second attempt fails, fall back to `animated_visual` generation for this card.

### 4.8 Frontend Rendering

- **FR-31:** `VisualExplanation.tsx` MUST detect `template_id` in the visual data and use a template renderer instead of raw `pixi_code` execution.
- **FR-32:** The iframe `srcdoc` for interactive visuals MUST:
  - Load PixiJS v8 from CDN (same as today)
  - Load the template JS (bundled inline or from a separate CDN-hosted file)
  - Initialize the PIXI.Application (500x350, same as today)
  - Call the template function with `(app, PIXI, params)`
- **FR-33:** Templates MUST be bundled as part of the frontend build (e.g., `public/templates/drag-between-containers.js`). They are inlined into the iframe srcdoc at render time.
- **FR-34:** The iframe sandbox remains `sandbox="allow-scripts"`. A CSP meta tag SHOULD be added inside the iframe: `script-src 'unsafe-inline' https://cdnjs.cloudflare.com; default-src 'none'; style-src 'unsafe-inline'`.
- **FR-35:** The "Visualise: {title}" button remains the entry point. No auto-play.
- **FR-36:** The "Replay" button MUST reset the interactive to its initial state (not replay an animation).
- **FR-37:** Two-way `postMessage` between iframe and parent:
  - iframe → parent: `{ type: 'pixi-ready' }` (existing), `{ type: 'interaction-complete', result: { correct: true, answer: "10" } }` (new, for analytics)
  - parent → iframe: `{ type: 'reset' }` (for replay/retry)

### 4.9 Master Tutor Awareness

- **FR-38:** The `visual_summary` for interactive visuals MUST describe what the student can do, not just what they see. E.g.: "Student can drag apples between boxes to discover 9 + 1 = 10" (not "Shows 9 apples and 1 apple").
- **FR-39:** The tutor does NOT react in real-time to interaction results. The interactive visual is self-contained during the card phase.
- **FR-40:** When the card phase ends and the tutor takes over, it MAY reference interactive visuals using the `visual_summary`: "Remember when you moved that apple to make 10?"

---

## 5. UX Requirements

- The "Visualise" button for interactive visuals SHOULD include a subtle indicator that it's interactive (e.g., "Interact: Make 10!" instead of "Visualise: Make 10!"), so students know this one is different.
- The interactive canvas MUST feel responsive — objects follow the finger with zero perceptible lag.
- Error feedback MUST be gentle. No red "WRONG". Use orange highlight + gentle shake for incorrect placement, then show the correct answer after a beat.
- Success feedback MUST be warm but not over-the-top. A brief glow + the result label appearing (e.g., "9 + 1 = 10!") is sufficient. No confetti, no fireworks — follow the "calibrate praise" principle.
- Interactive elements MUST have a `cursor: pointer` (or touch equivalent) visual cue so students know what's tappable/draggable.
- On mobile, the interactive visual MUST NOT interfere with page scrolling. Drag gestures inside the canvas MUST be captured; vertical swipes outside interactive elements MUST propagate to the page.
- The canvas MUST be 500x350px (consistent with all other visuals). This naturally enforces the "max 5 interactive elements" constraint.

---

## 6. Technical Considerations

### Integration Points

- **Backend modules affected:**
  - `book_ingestion_v2/services/animation_enrichment_service.py` — Add `interactive_visual` decision path, template selection, param generation
  - `book_ingestion_v2/prompts/visual_decision_and_spec.txt` — Update with `interactive_visual` option, template catalog, param schemas
  - `shared/repositories/explanation_repository.py` — `CardVisualExplanation` model adds `template_id`, `template_params` fields
- **Database changes:** None. New fields in existing JSONB.
- **New frontend files:**
  - `public/templates/drag-between-containers.js` (and one file per template)
  - Template registry/loader utility
- **Modified frontend files:**
  - `VisualExplanation.tsx` — Template detection, inline template loading, two-way postMessage, "Interact" button label
  - `api.ts` — `VisualExplanation` interface adds `template_id`, `template_params`

### Architecture

```
Existing Enrichment Pipeline              Interactive Extension
───────────────────────────              ────────────────────────
AnimationEnrichmentService               Same service, extended
  ├── Step 1: LLM decision               ├── Decision now includes interactive_visual
  │   └── no_visual / static / animated   │   └── + interactive_visual with template_id
  ├── Step 2: Code generation             ├── Step 2: SKIPPED for interactive
  │   └── spec → PixiJS code              │   └── template_params validated against schema
  └── Store in cards_json                 └── Store template_id + template_params in cards_json

Frontend                                  Frontend
────────                                  ────────
VisualExplanation.tsx                     Same component, extended
  ├── Detects pixi_code → raw execution   ├── Detects template_id → template renderer
  └── Sandboxed iframe                    └── Same sandboxed iframe, loads template + params
```

### Template File Structure

```
llm-frontend/public/templates/
├── drag-between-containers.js
├── drag-to-number-line.js
├── slider-adjust.js
├── sort-and-classify.js
├── step-by-step-build.js
├── tap-to-reveal.js
└── template-utils.js          # Shared: createDraggable(), snapToTarget(), showFeedback()
```

Each template exports a single function: `function render(app, PIXI, params) { ... }`

### LLM Model Configuration

- Template selection + param generation uses the same `animation_enrichment` LLM config as the decision step (lightweight model sufficient — it's structured JSON output, not code generation).
- No new `llm_config` rows needed.

---

## 7. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Explanation Cards (card phase) | **Major** | Cards can now contain interactive visuals alongside static/animated |
| Animated Visuals Pipeline | **Minor** | Decision prompt updated with new option; code gen step skipped for interactive |
| VisualExplanation.tsx | **Major** | Component gains template rendering path alongside raw pixi_code path |
| Master Tutor | **Minor** | `visual_summary` text slightly different for interactive visuals (describes action, not scene) |
| Card action (explain differently) | **None** | Variant switching loads cards with their visual_explanation intact |
| Session resume | **None** | Cards re-fetched from DB, template_id + params included |
| TTS audio | **None** | Audio and visual remain independent |
| Real-time tutor visuals | **None** | Not affected — interactive visuals are pre-computed only |

---

## 8. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Template JS fails to load in iframe | Fall back to showing the `visual_summary` as plain text. No error shown to student. |
| `template_params` validation fails during enrichment | Retry once with schema error. If still fails, fall back to `animated_visual` generation for this card. |
| LLM selects unknown `template_id` | Reject. Retry with the list of valid template IDs. If still invalid, fall back to `animated_visual`. |
| Student drags object outside canvas bounds | Object stays clamped to canvas edges. On release, springs back to nearest valid position. |
| Student abandons interaction mid-way (swipes to next card) | No problem. Interactive state is not saved. If they come back, the visual resets to initial state. |
| Device with no touch support (desktop) | Templates use PixiJS pointer events which handle both mouse and touch. Works on desktop with click-and-drag. |
| Very slow device | Templates use simple graphics (circles, rectangles, text) — no sprites or textures. Performance should be fine. If the iframe doesn't send `pixi-ready` within 10 seconds, hide the visual silently. |
| Canvas too small for template params (e.g., 8 items with 64px targets) | Template MUST enforce a max item count per template type. If LLM generates too many items, validation rejects it. |
| Student completes interaction, then taps "Replay" | Interactive resets to initial state. Student can try again. |

---

## 9. Out of Scope

- **Real-time interactive visuals during tutoring sessions** — Interactive visuals are pre-computed for explanation cards only. The real-time tutor pipeline continues generating static/animated visuals.
- **Tutor responding to interaction results** — The interactive visual is self-contained. The tutor gets a summary but doesn't react in real-time.
- **Sound effects** — v1 is visual-only feedback. Sound can be added in v2.
- **Multi-touch or complex gestures** — Single-finger only (tap, drag). No pinch, rotate, swipe.
- **Student-created or student-modified visuals** — Templates are parameterized by the LLM, not by students.
- **Saving interaction state** — If a student leaves and returns, the interactive resets. No state persistence.
- **Accessibility (screen reader)** — v1 focuses on visual interaction. Accessible alternatives (keyboard navigation, ARIA) are v2.
- **Analytics dashboard** — Interaction completion events are posted via `postMessage` but not yet stored or displayed. Analytics infrastructure is v2.

---

## 10. Open Questions

1. **Template bundling strategy** — Should templates be inlined into the iframe srcdoc (simpler, larger HTML string) or loaded from a CDN/public path within the iframe (requires network access, needs `sandbox` adjustment)? Recommendation: inline for v1, since templates are small (<5KB each).
2. **Max items per template** — Each template needs a hard cap on interactive elements to prevent overcrowding the 500x350 canvas. Suggested: drag-between-containers (6 objects), number-line (4 markers), slider (1 slider), sort-and-classify (6 items / 3 categories), step-by-step (5 steps), tap-to-reveal (8 items). Finalize during template implementation.
3. **Template versioning** — When a template is updated (bug fix, UX improvement), should we version templates so older cards still render correctly? Or is "latest template always wins" acceptable since params are stable?

---

## 11. Success Metrics

### Technical Metrics
- **Template render reliability**: >= 98% of cards with `template_id` render successfully (higher bar than animated visuals since templates are human-authored and tested).
- **Interaction responsiveness**: Object follows finger with < 16ms lag (one frame at 60fps).
- **Param generation accuracy**: >= 90% of LLM-generated `template_params` pass schema validation on first attempt.

### Learning Metrics
- **Interaction completion rate**: >= 70% of students who tap "Interact" complete the interaction (reach the goal state).
- **Retry rate**: Students who get it wrong try again at least once (indicates engagement, not frustration).
- **"I understand!" rate**: Cards with interactive visuals SHOULD show higher "I understand!" rates than cards with animated-only visuals.
- **Post-card performance**: Students who interacted with visuals SHOULD score higher on the first check-understanding question.

### Engagement Metrics
- **Interact tap rate**: >= 70% of students tap the "Interact" button when available (higher bar than the 60% "Visualise" target, since interactivity is more compelling).
- **Time on interactive**: Students spend 10-30 seconds on interactive visuals (too short = not engaging, too long = stuck).

---

## 12. Implementation Phases

### Phase 1: Foundation
- Add `interactive_visual` to decision prompt and enrichment pipeline
- Build `drag-between-containers` template (covers addition, subtraction, grouping)
- Update `VisualExplanation.tsx` with template detection and rendering
- Add two-way `postMessage` support
- Validate with 10-15 math topics manually

### Phase 2: Expand Templates
- Build 3 more templates: `drag-to-number-line`, `slider-adjust`, `sort-and-classify`
- Add `template-utils.js` shared library for common interaction patterns
- Expand to more math topics

### Phase 3: Polish & Remaining
- Build `step-by-step-build` and `tap-to-reveal` templates
- Add sound effects (v2)
- Add interaction analytics storage and dashboard
- Add accessibility (keyboard nav, ARIA labels)
- Expand to science topics
