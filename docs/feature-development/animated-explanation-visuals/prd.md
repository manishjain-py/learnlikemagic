# PRD: Instructional Visual Enrichment for Explanation Cards

**Date:** 2026-03-22
**Status:** Draft
**Author:** PRD Generator + Manish

---

## 1. Problem Statement

Kids find the learning experience unattractive. The current explanation cards are text-only (with occasional ASCII diagrams), which doesn't leverage the visual, interactive nature of the medium. Research consistently shows that children learn better with visual representations — yet our cards rely entirely on words.

The app already has a PixiJS v8 POC that generates animated visuals from natural language prompts and renders them in sandboxed iframes. However, this capability is only used in the **interactive tutor flow** (real-time, per-turn generation) and on an admin test page. It is **not used in pre-computed explanation cards** — the highest-impact surface for visuals, since every student sees these cards for every topic.

---

## 2. Goal

Add a selective, offline enrichment pipeline that generates PixiJS visuals for pre-computed explanation cards — making the learning experience visually engaging while amplifying conceptual clarity.

The core principle: **only generate a visual if it makes the concept clearer immediately.** If a visual is cute but not clearer, it should not exist. Static diagrams are the default; animation only when motion is the teaching mechanism.

---

## 3. User Stories

- As a **student viewing explanation cards**, I want to see visuals that show me how a concept works, so that I understand it faster and find the experience more engaging.
- As an **admin**, I want to trigger visual enrichment for a book/chapter/topic after explanations are generated, so that cards get visuals without manual effort.
- As the **master tutor**, I want to know what visuals the student saw (e.g., "student saw 10 ones bundling into 1 ten"), so I can reference them during the interactive session.
- As a **product owner**, I want the visual generation to be selective (not every card gets one) and reliable (no broken visuals shown to kids), so that quality stays high.

---

## 4. Functional Requirements

### 4.1 Visual Decision (Which Cards Get Visuals)

- **FR-1:** A new `AnimationEnrichmentService` MUST process all cards for a given variant in a single LLM call, deciding which cards benefit from a visual.
- **FR-2:** The LLM MUST receive:
  - All cards for the variant (full context of the topic being taught)
  - The teaching guideline (topic, chapter, subject, grade level)
  - The variant approach (e.g., "Everyday Analogies", "Visual Walkthrough")
- **FR-3:** The LLM MUST return a three-way decision per card:
  - `no_visual` — Card doesn't benefit from a visual (default)
  - `static_visual` — A static diagram/illustration helps
  - `animated_visual` — Motion is the teaching mechanism (e.g., number line jumps, objects combining, transformations)
- **FR-4:** For each card selected for a visual, the LLM MUST also return:
  - `card_idx`: Which card gets the visual
  - `title`: Short label for the "Visualise" button (e.g., "3 + 4 = 7")
  - `visual_summary`: One-sentence natural language description of what the visual shows (e.g., "3 red apples and 4 blue apples merging into a group of 7")
- **FR-5:** Selection criteria the LLM MUST follow:
  - **Yes**: Concepts that can be *seen* (geometry, number lines, fractions, physical processes, comparisons, transformations, cause-and-effect)
  - **No**: Summary cards, simple text definitions, cards where a visual would just restate the text without adding understanding
  - **Static by default**: Use `static_visual` unless the concept is inherently about motion or transformation
  - **Animated only when motion teaches**: `animated_visual` reserved for processes where the movement itself is the lesson — carrying in addition, regrouping, jumps on a number line, objects combining
  - **If in doubt, skip** — a missing visual is better than a bad one
- **FR-6:** The pipeline MUST generate a visual for EVERY card. The student chooses whether to tap "Visualise" — having one available never hurts. Even simple concepts benefit from a clean diagram.

### 4.2 Learning Clarity Requirements for Generated Visuals

The primary goal of generated visuals is **learning clarity**, not visual impressiveness. Every generated PixiJS code MUST produce output that a child can immediately understand.

- **FR-7:** The PixiJS generation prompt MUST enforce these learning clarity rules:
  - **Large readable text**: All labels MUST be >= 20px font size. Key values (numbers, names) >= 28px. No tiny annotations.
  - **High contrast**: Dark text on light backgrounds OR light text on dark backgrounds. Never medium-on-medium. Minimum contrast ratio suitable for children's readability.
  - **Clean background**: Solid color background (not gradients or patterns). White or very light pastel preferred for educational diagrams. Dark (#1a1a2e) acceptable for space/night scenes.
  - **One concept per visual**: The visual should illustrate exactly one idea from the card. If the card says "3 + 4 = 7", show exactly that — not addition plus subtraction plus number lines.
  - **Clear visual hierarchy**: What the student should look at first MUST be the largest, most prominent element. Secondary elements smaller and dimmer. No visual clutter.
  - **Progressive reveal**: Elements should appear sequentially, matching how a human would draw or explain a concept piece by piece. Show step 1, then step 2, then the result — not everything at once.
  - **Slow, deliberate animations**: Minimum 1.5 seconds per animation step. Kids need time to process. No rapid transitions. Use easing for smooth motion.
  - **Labels that connect to the card**: Every element in the visual MUST be labeled. Labels should use the same words as the card content. If the card says "parts", the visual says "parts", not "fractions".
  - **Maximum 5 distinct visual elements**: More than 5 objects on screen creates clutter. Group related items into containers.
  - **Kid-friendly colors**: Bright, warm colors (not neon). Use color to encode meaning (e.g., red group + blue group = purple combined group), not just for decoration.
  - **No text walls**: If the visual needs text, max 10 words total on screen at any time. The card already has the text — the visual shows, it doesn't tell.
  - **No decorative movement**: Every animation step must teach something. No bouncing, spinning, or pulsing for effect.
  - **Minimalism**: Use only essential shapes. No decorative elements. Fewer elements with clear meaning beats many elements with ambiguous meaning.
  - **Readable on mobile**: Canvas is 500x350, but rendered full-width on phones. All elements must remain legible at small screen sizes.
- **FR-8:** The generation prompt MUST include 2-3 examples of good visual specs with expected code patterns, so the LLM has concrete reference points for quality.
- **FR-9:** For `animated_visual`, ticker-based animations MUST:
  - Have a clear start state and end state (not loop infinitely by default)
  - Pause for 2+ seconds at the end state so the student can absorb the result
  - Use `app.ticker.add()` with delta-time for frame-rate independence
  - Complete the full animation in 3-8 seconds (not too fast, not boring)
  - Use progressive reveal: build the scene element by element

### 4.3 Two-Step Generation: Visual Spec Then PixiJS Code

The pipeline MUST NOT jump directly from card text to PixiJS code. A two-step approach produces more reliable, clearer visuals.

- **FR-10:** **Step 1 — Visual Spec Generation:** After the decision step selects a card for a visual, the pipeline MUST first generate a structured **visual spec** describing:
  - What shapes/objects to draw (e.g., "3 red circles on the left, 4 blue circles on the right")
  - Position and size of each element (e.g., "circles 40px diameter, spaced 60px apart, centered vertically")
  - Labels and their placement (e.g., "label '3' below the red group, label '4' below the blue group")
  - Color assignments with meaning (e.g., "red = first addend, blue = second addend, green = sum")
  - For animations: step-by-step sequence (e.g., "Step 1: show red circles. Step 2: show blue circles. Step 3: animate both groups sliding to center. Step 4: show label '7' above merged group")
  - Expected final state (what the student sees when animation completes)
- **FR-11:** The visual spec MUST be human-readable and stored alongside the final code (for debugging and tutor context).
- **FR-12:** The visual spec generation and the decision step MAY be combined into a single LLM call for efficiency — the decision output can include the spec for selected cards.
- **FR-13:** **Step 2 — PixiJS Code Generation:** A separate LLM call takes the visual spec and generates executable PixiJS v8 JavaScript code.
- **FR-14:** The code-generation LLM receives:
  - The visual spec (primary input — this is what to implement)
  - The learning clarity rules from FR-7 (constraints)
  - PixiJS v8 API reference/examples (technical context)
  - The card content (so labels match the card's vocabulary)
- **FR-15:** Generated code MUST follow existing PixiJS conventions: canvas 500x350, `app` and `PIXI` as globals, no imports, hex colors, `app.stage.addChild()`.

**Why two steps:** When a single LLM call goes from prose to code, it makes two kinds of decisions simultaneously: *what* to draw and *how* to draw it. Separating these means: (a) the spec can be validated for pedagogical correctness before committing to code generation, (b) code failures can be retried from the spec without re-deciding what to show, (c) the spec is debuggable by humans, (d) the spec provides a natural `visual_summary` for tutor context.

### 4.4 Code Validation

- **FR-16:** After generating PixiJS code, the pipeline MUST attempt basic validation:
  - Syntax check: The code MUST parse without JavaScript syntax errors
  - Structural check: The code MUST contain `app.stage.addChild` (at least one display object added)
  - Size check: The code MUST be under 5000 characters (overly long code is usually buggy)
- **FR-17:** If validation fails, the pipeline MUST retry code generation once from the same visual spec, with the error message fed back to the LLM. If the second attempt also fails, discard (the card gets no visual — this is acceptable).
- **FR-18:** (v2 — Screenshot Validation) Render the code in a headless browser (Puppeteer/Playwright), take a screenshot, and review it with an LLM against a clarity rubric: text readable? layout clean? idea obvious? no answer-spoiling? This is the gold standard for quality — planned for v2 after v1 validates the core pipeline.

### 4.5 Storage

- **FR-19:** Each card that receives a visual MUST store the result as a nested `visual_explanation` object within the card's JSON:
  ```json
  {
    "card_idx": 3,
    "card_type": "concept",
    "title": "Adding Groups Together",
    "content": "When we add 3 + 4, we combine...",
    "visual": "  [ooo] + [oooo] = [ooooooo]",
    "audio_text": "When we add three plus four...",
    "visual_explanation": {
      "output_type": "animated_visual",
      "title": "3 + 4 = 7",
      "visual_summary": "3 red apples and 4 blue apples slide together to form a group of 7",
      "visual_spec": "Draw 3 red circles (40px) on the left labeled '3'. Draw 4 blue circles on the right labeled '4'. Animate both groups sliding to center. Show '= 7' label above merged group.",
      "pixi_code": "const leftGroup = new PIXI.Container(); ..."
    }
  }
  ```
- **FR-20:** The nested structure mirrors the frontend's existing `VisualExplanation` interface. Fields:
  - `output_type`: `"static_visual"` or `"animated_visual"`
  - `title`: Short label for the "Visualise" button
  - `visual_summary`: One-sentence description of what the student sees (used for tutor context)
  - `visual_spec`: Structured description of the visual (used for debugging and retry)
  - `pixi_code`: Executable PixiJS v8 JavaScript code
- **FR-21:** These fields live inside the existing JSONB `cards_json` column — no database migration needed. Existing cards without `visual_explanation` remain valid.
- **FR-22:** The enrichment pipeline MUST update `cards_json` in-place by reading the existing cards, adding `visual_explanation` to enriched cards, and writing back. The `summary_json` and other fields remain unchanged.
- **FR-23:** The existing `visual` field (ASCII diagrams) is preserved. A card can have both an ASCII `visual` and a `visual_explanation` with PixiJS code — the ASCII stays for non-JS contexts, the PixiJS is the rich version.

### 4.6 Pipeline Execution

- **FR-24:** The enrichment pipeline MUST be triggerable at three scopes:
  - Single guideline (one topic)
  - Chapter (all guidelines in a chapter)
  - Book (all guidelines in a book)
- **FR-25:** The pipeline MUST skip cards that already have `visual_explanation.pixi_code` (idempotent — safe to re-run). A `--force` flag SHOULD allow re-generation.
- **FR-26:** The pipeline MUST be exposed as an admin API endpoint: `POST /admin/v2/books/{book_id}/generate-visuals` with optional `chapter_id` and `guideline_id` query params.
- **FR-27:** Like explanation generation, this MUST run as a background job tracked in `chapter_processing_jobs` with progress updates.
- **FR-28:** The pipeline MUST also be runnable as a CLI script for batch processing.

### 4.7 Frontend Display

- **FR-29:** Explanation cards in the card-phase carousel MUST render the `VisualExplanationComponent` when a card has `visual_explanation.pixi_code`.
- **FR-30:** The visual MUST appear below the card content, behind a "Visualise: {title}" button (using existing `VisualExplanation.tsx` component).
- **FR-31:** The `ExplanationCard` TypeScript interface MUST add: `visual_explanation?: VisualExplanation | null` (reusing the existing `VisualExplanation` interface which already has `pixi_code`, `output_type`, `title`, `narration`).
- **FR-32:** Card slides MUST pass `card.visual_explanation` directly to `VisualExplanationComponent` — the nested structure matches the component's expected props.
- **FR-33:** TTS audio playback and visual rendering MUST NOT interfere with each other. Audio plays automatically on slide view; visual plays on user tap.

### 4.8 Master Tutor Awareness

- **FR-34:** The `precomputed_explanation_summary` injected into the master tutor's system prompt MUST include the `visual_summary` from each card that has a visual, e.g.: "Card 3 included a visual: student saw 3 red apples and 4 blue apples merging into a group of 7."
- **FR-35:** The tutor SHOULD reference card visuals using the summary language: "Remember when you saw the apples coming together to make 7?"
- **FR-36:** The `pixi_code` and `visual_spec` MUST NOT be included in the tutor prompt — too large, not useful for the LLM. Only `visual_summary` and `title` go into the prompt.

---

## 5. UX Requirements

- The "Visualise" button MUST be clearly visible but not distracting — the card text is primary, the visual is supplementary.
- Tapping "Visualise" should feel instant — the code is pre-computed, only rendering happens client-side.
- If the visual fails to render (iframe error), show nothing — do not show error messages to kids. Silently degrade to text-only card.
- The visual MUST NOT auto-play. Students tap when they're ready. This avoids overwhelming them during card reading.
- When the student taps "Visualise", the view MUST auto-scroll to bring the visual canvas into view. This prevents the animation from playing off-screen below the fold.
- On replay, the animation MUST restart from the beginning (existing behavior in `VisualExplanation.tsx`).
- The canvas MUST be responsive — fill the card width on mobile (existing 500:350 aspect ratio, 100% width CSS).

---

## 6. Technical Considerations

### Integration Points

- **Backend modules affected:**
  - `shared/repositories/explanation_repository.py` — `ExplanationCard` model gets `visual_explanation` field
  - `shared/models/entities.py` — No change (JSONB is schema-flexible)
  - `tutor/services/pixi_code_generator.py` — Reused or subclassed for offline generation
  - New: `book_ingestion_v2/services/animation_enrichment_service.py` — Decision + spec + generation + validation pipeline
  - New: `book_ingestion_v2/prompts/visual_decision_and_spec.txt` — LLM prompt for card selection + spec generation
  - New: `book_ingestion_v2/prompts/visual_code_generation.txt` — PixiJS generation prompt with clarity rules
  - `book_ingestion_v2/api/sync_routes.py` — New endpoint for visual generation
  - `tutor/prompts/master_tutor_prompts.py` — Add `visual_summary` references to explanation summary section
- **Database changes:** None. New fields live inside existing JSONB column.
- **Frontend changes:**
  - `api.ts` — Add `visual_explanation` to `ExplanationCard` interface
  - `ChatSession.tsx` — Pass `card.visual_explanation` to `VisualExplanationComponent` on card slides
  - No new components needed — `VisualExplanation.tsx` is reused as-is.

### Architecture

```
Existing Pipeline                    New Enrichment Pipeline
─────────────────                    ──────────────────────
ExplanationGeneratorService          AnimationEnrichmentService
  ├── generate cards                   ├── Read stored cards from DB
  ├── critique cards                   ├── Step 1: LLM decides which cards get visuals
  ├── refine cards                     │   └── Returns: card_idx, type, title, visual_summary, visual_spec
  ├── store in topic_explanations      ├── Step 2: For each selected card:
  └── Done                             │   ├── Generate PixiJS code FROM the visual spec
                                       │   ├── Validate code (syntax, structure, size)
                                       │   └── Retry once from spec on failure
                                       ├── Update cards_json with visual_explanation objects
                                       └── Done
```

The two pipelines are fully decoupled. Animation enrichment reads from and writes back to the same `topic_explanations` table. It can run immediately after explanation generation or days later.

### LLM Model Configuration

- **Decision + spec call:** Lightweight-to-medium model (GPT-4.1-mini or equivalent). Input is card text + guideline context, output is JSON with decisions and specs. Low-to-moderate cost.
- **Code generation:** Heavier model needed for reliable code (GPT-5.2 or Claude Opus 4.6). Same reasoning effort as existing `PixiCodeGenerator`.
- Both configurable via `llm_configs` table with component key `animation_enrichment`.

### Cost Estimate (v1 Rollout Scope)

For v1: math topics only, ~5 chapters × 10 guidelines × variant B only = 50 variants:
- Decision + spec: 50 LLM calls (one per variant) — ~$1
- Code generation: ~75-150 cards selected (1-3 per variant) × 1 call each — ~$4-8
- Retry: ~10% failure rate = 8-15 retries — ~$0.50
- **Total for v1 rollout: ~$6-10**

At full scale (all variants, all subjects):
- Multiply by ~3x for all variants, ~2-3x for additional subjects
- **Total per chapter (full scale): ~$12-20**

---

## 7. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Explanation Cards (card phase) | **Major** | Cards gain interactive visuals — new rendering path |
| Master Tutor (interactive) | **Minor** | Summary prompt gains `visual_summary` text per visual card |
| Explanation Generation | **None** | Enrichment runs after, doesn't modify the generation pipeline |
| PixiJS interactive visuals | **None** | Existing per-turn visual generation unchanged |
| Card action (clear/explain differently) | **None** | Variant switching loads cards with their visual_explanation intact |
| Session resume | **None** | Cards re-fetched from DB on resume, visual_explanation included |
| TTS audio | **None** | Audio and visual are independent — audio auto-plays, visual is on-tap |

---

## 8. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Card has `pixi_code` but it fails to render in iframe | Frontend silently hides the visual. Card text remains fully functional. No error message shown to student. |
| LLM selects 0 cards for visuals | Valid. Some topics (e.g., grammar definitions) may not benefit from visuals. Pipeline stores cards unchanged. |
| Visual spec is good but code generation fails twice | Discard. Card gets no visual. Log the spec for manual review. |
| Very long PixiJS code (>5000 chars) | Discard. Long code is usually over-engineered and buggy. |
| Enrichment runs before explanations exist | No-op. Pipeline checks for existing cards first, skips guidelines with no explanations. |
| Enrichment runs twice on same cards | Idempotent. Cards with existing `visual_explanation.pixi_code` are skipped unless `--force` flag is set. |
| Card content changes after enrichment | Visual may be stale. Re-running explanation generation clears `visual_explanation` (since cards_json is fully replaced on upsert). Re-run enrichment to regenerate. |
| Student on slow device / old phone | Iframe only loads on tap (not auto-play). If rendering is slow, student sees the card text immediately while visual loads. |
| Variant B ("Visual Walkthrough") cards | These already have ASCII visuals in the `visual` field. They can ALSO get PixiJS visuals. The ASCII stays; the PixiJS is the rich version. |
| Visual spoils the answer for a check/practice card | The decision prompt MUST instruct: never generate visuals that reveal answers the student is meant to figure out. |

---

## 9. v1 Rollout Scope

Start narrow, validate quality, then expand.

- **Subjects**: Math only. Science in v2. Language arts likely never.
- **Variants**: Start with Variant B (Visual Walkthrough) — these cards already have a visual intent. Expand to A and C after quality is validated.
- **Volume**: 1-3 visuals per topic variant. Not every card.
- **Visual type**: Static diagrams preferred. Animation only when motion is the teaching mechanism.
- **Card types**: Cards tagged `visual` and `concept` are the primary targets. `example` cards are secondary. `summary` and `analogy` cards are skipped by default.
- **Interaction**: Existing "Visualise" button, not autoplay. No new UI patterns.
- **Validation**: Manual QA of all v1 visuals before launch. At this volume (~100-150 visuals), manual review is feasible.

---

## 10. v2 Roadmap

- **Screenshot-based validation**: Render code in headless browser, take screenshot, review with LLM against clarity rubric (text readable? layout clean? idea obvious? no answer spoiling?). Automates QA and enables safe scaling beyond manual review.
- **Expand to all variants**: Variant A (Analogies) and C (Step-by-Step) get their own visuals, each matching the variant's teaching approach.
- **Expand to Science**: Physical processes, biological systems, simple machines — high visual potential.
- **Visual clarity auto-research**: A `VisualClarityEvaluator` pipeline that scores generated visuals and iterates on the generation prompts.
- **Accessibility**: Alt-text generated from `visual_summary`, screen reader support.

---

## 11. Out of Scope

- **Real-time visual generation during sessions**: The interactive tutor already has this. This PRD is about pre-computed visuals for explanation cards only.
- **User-generated visuals**: Students cannot request or modify visuals.
- **3D visuals or WebGL**: Pixi.js v8 2D only. 3D is unnecessary for the target subjects.
- **Animation caching/CDN**: Code is stored as text in DB, rendered client-side. No server-side rendering.

---

## 12. Open Questions

1. **Canvas size for cards?** The existing `VisualExplanation.tsx` uses 500x350. Should card-embedded visuals use a different size (e.g., full card width, shorter height) for a better mobile experience?
2. **Combined decision+spec call?** FR-12 allows combining the decision and spec into one LLM call. Is a single call with structured output reliable enough, or should these be separate for quality?

---

## 13. Success Metrics

### Technical Metrics
- **Render reliability**: >= 95% of cards with `pixi_code` render successfully in the frontend (no iframe errors).
- **Performance**: Visual renders in < 2 seconds after tap on a mid-range phone.

### Learning Metrics
- **Learning clarity**: Spot-check all v1 visuals manually — each should make the concept clearer than the card text alone. A child should be able to understand the visual without reading the card.
- **"I understand!" rate**: Track ratio of "I understand!" vs "Explain differently" for topics with visuals vs without. Target: improvement in "I understand!" rate.
- **Post-card bridge performance**: Students who viewed visuals should answer the bridge question correctly more often.
- **Session continuation**: More students continue past card phase into interactive session for topics with visuals.

### Engagement Metrics
- **Visualise tap rate**: Track how many students tap the "Visualise" button. Target: >= 60% of students tap at least one visual per topic.
- **Card completion rate**: Card phase completion rate stays the same or improves.
- **Reduction in fallback**: Fewer students hitting "I still don't get it" after exhausting all variants.
