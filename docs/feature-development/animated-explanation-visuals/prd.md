# PRD: Animated Explanation Visuals

**Date:** 2026-03-22
**Status:** Draft
**Author:** PRD Generator + Manish

---

## 1. Problem Statement

Kids find the learning experience unattractive. The current explanation cards are text-only (with occasional ASCII diagrams), which doesn't leverage the visual, interactive nature of the medium. Research consistently shows that children learn better with visual representations — yet our cards rely entirely on words.

The app already has a PixiJS v8 POC that generates animated visuals from natural language prompts and renders them in sandboxed iframes. However, this capability is only used in the **interactive tutor flow** (real-time, per-turn generation) and on an admin test page. It is **not used in pre-computed explanation cards** — the highest-impact surface for visuals, since every student sees these cards for every topic.

---

## 2. Goal

Add an offline enrichment pipeline that generates PixiJS animated visuals for pre-computed explanation cards, making the learning experience visually engaging while amplifying conceptual clarity. The visuals MUST enhance understanding — they are pedagogical tools, not decorations.

---

## 3. User Stories

- As a **student viewing explanation cards**, I want to see animated visuals that show me how a concept works, so that I understand it faster and find the experience more engaging.
- As an **admin**, I want to trigger visual enrichment for a book/chapter/topic after explanations are generated, so that cards get animations without manual effort.
- As the **master tutor**, I want to know which cards have animations, so I can reference them during the interactive session ("remember the animation that showed you...").
- As a **product owner**, I want the visual generation to be selective (not every card gets one) and reliable (no broken animations shown to kids), so that quality stays high.

---

## 4. Functional Requirements

### 4.1 Animation Decision (Which Cards Get Visuals)

- **FR-1:** A new `AnimationEnrichmentService` MUST process all cards for a given variant in a single LLM call, deciding which cards benefit from an animated visual.
- **FR-2:** The LLM MUST receive:
  - All cards for the variant (full context of the topic being taught)
  - The teaching guideline (topic, chapter, subject, grade level)
  - The variant approach (e.g., "Everyday Analogies", "Visual Walkthrough")
- **FR-3:** The LLM MUST return, for each card it selects:
  - `card_idx`: Which card gets the animation
  - `visual_prompt`: Natural language description of what the animation should show
  - `output_type`: `"image"` (static diagram) or `"animation"` (ticker-based motion)
  - `title`: Short label for the "Visualise" button (e.g., "3 + 4 = 7")
- **FR-4:** Selection criteria the LLM MUST follow:
  - **Yes**: Concepts that can be *seen* (geometry, number lines, fractions, physical processes, comparisons, transformations, cause-and-effect)
  - **No**: Summary cards, cards that are already simple text definitions, cards where a visual would just restate the text without adding understanding
  - **Guideline**: If in doubt, skip — a missing animation is better than a bad one
- **FR-5:** The LLM SHOULD select 30-60% of cards (not every card, not zero). A variant with 8 cards should typically get 3-5 animations.

### 4.2 Learning Clarity Requirements for Generated Visuals

The primary goal of generated visuals is **learning clarity**, not visual impressiveness. Every generated PixiJS code MUST produce output that a child can immediately understand.

- **FR-6:** The PixiJS generation prompt MUST enforce these learning clarity rules:
  - **Large readable text**: All labels MUST be >= 20px font size. Key values (numbers, names) >= 28px. No tiny annotations.
  - **High contrast**: Dark text on light backgrounds OR light text on dark backgrounds. Never medium-on-medium. Minimum contrast ratio suitable for children's readability.
  - **Clean background**: Solid color background (not gradients or patterns). White or very light pastel preferred for educational diagrams. Dark (#1a1a2e) acceptable for space/night scenes.
  - **One concept per visual**: The animation should illustrate exactly one idea from the card. If the card says "3 + 4 = 7", show exactly that — not addition plus subtraction plus number lines.
  - **Clear visual hierarchy**: What the student should look at first MUST be the largest, most prominent element. Secondary elements smaller and dimmer. No visual clutter.
  - **Slow, deliberate animations**: Minimum 1.5 seconds per animation step. Kids need time to process. No rapid transitions. Use easing for smooth motion.
  - **Labels that connect to the card**: Every element in the visual MUST be labeled. Labels should use the same words as the card content. If the card says "parts", the visual says "parts", not "fractions".
  - **Maximum 5 distinct visual elements**: More than 5 objects on screen creates clutter. Group related items into containers.
  - **Kid-friendly colors**: Bright, warm colors (not neon). Use color to encode meaning (e.g., red group + blue group = purple combined group), not just for decoration.
  - **No text walls**: If the visual needs text, max 10 words total on screen at any time. The card already has the text — the visual shows, it doesn't tell.
- **FR-7:** The generation prompt MUST include 2-3 examples of good visual prompts with expected code patterns, so the LLM has concrete reference points for quality.
- **FR-8:** For `output_type: "animation"`, ticker-based animations MUST:
  - Have a clear start state and end state (not loop infinitely by default)
  - Pause for 2+ seconds at the end state so the student can absorb the result
  - Use `app.ticker.add()` with delta-time for frame-rate independence
  - Complete the full animation in 3-8 seconds (not too fast, not boring)

### 4.3 PixiJS Code Generation

- **FR-9:** Code generation MUST use the existing `PixiCodeGenerator` service (or a specialized subclass) to generate PixiJS v8 JavaScript code from the `visual_prompt`.
- **FR-10:** The generation prompt MUST be enhanced beyond the current interactive-use prompt with:
  - The full card content (so the visual matches the explanation)
  - The student's grade level (from the teaching guideline)
  - The learning clarity rules from FR-6
  - The card's specific analogy/example (so the visual uses the same vocabulary)
- **FR-11:** Generated code MUST follow existing PixiJS conventions: canvas 500x350, `app` and `PIXI` as globals, no imports, hex colors, `app.stage.addChild()`.

### 4.4 Code Validation

- **FR-12:** After generating PixiJS code, the pipeline SHOULD attempt basic validation:
  - Syntax check: The code MUST parse without JavaScript syntax errors
  - Structural check: The code MUST contain `app.stage.addChild` (at least one display object added)
  - Size check: The code MUST be under 5000 characters (overly long code is usually buggy)
- **FR-13:** If validation fails, the pipeline MUST retry once with the error message fed back to the LLM. If the second attempt also fails, discard (the card gets no animation — this is acceptable).
- **FR-14:** (Future/Optional) Headless browser validation: Execute the code in Puppeteer and check for runtime JS errors. Not required for v1 but recommended for v2.

### 4.5 Storage

- **FR-15:** The `ExplanationCard` schema MUST add a new field: `pixi_code: Optional[str]` — the generated PixiJS JavaScript code.
- **FR-16:** The `ExplanationCard` schema MUST add: `pixi_title: Optional[str]` — the title shown on the "Visualise" button.
- **FR-17:** The `ExplanationCard` schema MUST add: `pixi_output_type: Optional[str]` — `"image"` or `"animation"`.
- **FR-18:** These fields are added to the JSONB `cards_json` column — no database migration needed. Existing cards without these fields remain valid (Optional fields, default None).
- **FR-19:** The enrichment pipeline MUST update `cards_json` in-place by reading the existing cards, adding pixi fields to enriched cards, and writing back. The `summary_json` and other fields remain unchanged.

### 4.6 Pipeline Execution

- **FR-20:** The enrichment pipeline MUST be triggerable at three scopes:
  - Single guideline (one topic)
  - Chapter (all guidelines in a chapter)
  - Book (all guidelines in a book)
- **FR-21:** The pipeline MUST skip cards that already have `pixi_code` (idempotent — safe to re-run). A `--force` flag SHOULD allow re-generation.
- **FR-22:** The pipeline MUST be exposed as an admin API endpoint: `POST /admin/v2/books/{book_id}/generate-animations` with optional `chapter_id` and `guideline_id` query params.
- **FR-23:** Like explanation generation, this MUST run as a background job tracked in `chapter_processing_jobs` with progress updates.
- **FR-24:** The pipeline MUST also be runnable as a CLI script for batch processing.

### 4.7 Frontend Display

- **FR-25:** Explanation cards in the card-phase carousel MUST render the `VisualExplanationComponent` when a card has `pixi_code`.
- **FR-26:** The visual MUST appear below the card content, behind a "Visualise: {title}" button (using existing `VisualExplanation.tsx` component).
- **FR-27:** The `ExplanationCard` TypeScript interface MUST add: `pixi_code?: string | null`, `pixi_title?: string | null`, `pixi_output_type?: 'image' | 'animation' | null`.
- **FR-28:** Card slides MUST pass the pixi fields to `VisualExplanationComponent` by mapping them to the existing `VisualExplanation` interface format: `{ pixi_code, output_type: pixi_output_type, title: pixi_title }`.
- **FR-29:** TTS audio playback and visual rendering MUST NOT interfere with each other. Audio plays automatically on slide view; visual plays on user tap.

### 4.8 Master Tutor Awareness

- **FR-30:** The `precomputed_explanation_summary` injected into the master tutor's system prompt MUST note which cards had animated visuals, e.g.: "Cards 2, 5, and 7 included animated visuals that the student could play."
- **FR-31:** The tutor SHOULD reference card visuals when relevant: "Remember the animation that showed the pizza being divided into parts?"
- **FR-32:** The pixi_code itself MUST NOT be included in the tutor prompt (too large, not useful for the LLM).

---

## 5. UX Requirements

- The "Visualise" button MUST be clearly visible but not distracting — the card text is primary, the visual is supplementary.
- Tapping "Visualise" should feel instant — the code is pre-computed, only rendering happens client-side.
- If the visual fails to render (iframe error), show nothing — do not show error messages to kids. Silently degrade to text-only card.
- The visual MUST NOT auto-play. Students tap when they're ready. This avoids overwhelming them during card reading.
- On replay, the animation MUST restart from the beginning (existing behavior in `VisualExplanation.tsx`).
- The canvas MUST be responsive — fill the card width on mobile (existing 500:350 aspect ratio, 100% width CSS).

---

## 6. Technical Considerations

### Integration Points

- **Backend modules affected:**
  - `shared/repositories/explanation_repository.py` — `ExplanationCard` model gets new fields
  - `shared/models/entities.py` — No change (JSONB is schema-flexible)
  - `tutor/services/pixi_code_generator.py` — Reused or subclassed for offline generation
  - New: `book_ingestion_v2/services/animation_enrichment_service.py` — Decision + generation + validation pipeline
  - New: `book_ingestion_v2/prompts/animation_decision.txt` — LLM prompt for card selection
  - New: `book_ingestion_v2/prompts/animation_generation.txt` — Enhanced PixiJS generation prompt with clarity rules
  - `book_ingestion_v2/api/sync_routes.py` — New endpoint for animation generation
  - `tutor/prompts/master_tutor_prompts.py` — Add visual card references to summary section
- **Database changes:** None. New fields live inside existing JSONB column.
- **Frontend changes:**
  - `api.ts` — Extend `ExplanationCard` interface
  - `ChatSession.tsx` — Map pixi fields to `VisualExplanation` prop on card slides
  - No new components needed — `VisualExplanation.tsx` is reused as-is.

### Architecture

```
Existing Pipeline                    New Enrichment Pipeline
─────────────────                    ──────────────────────
ExplanationGeneratorService          AnimationEnrichmentService
  ├── generate cards                   ├── Read stored cards from DB
  ├── critique cards                   ├── LLM: decide which cards get visuals
  ├── refine cards                     ├── For each selected card:
  ├── store in topic_explanations      │   ├── Generate PixiJS code
  └── Done                             │   ├── Validate code
                                       │   └── Retry once on failure
                                       ├── Update cards_json with pixi fields
                                       └── Done
```

The two pipelines are fully decoupled. Animation enrichment reads from and writes back to the same `topic_explanations` table. It can run immediately after explanation generation or days later.

### LLM Model Configuration

- **Decision call:** Lightweight (GPT-4.1-mini or equivalent). Input is card text, output is a short JSON list. Low cost.
- **Code generation:** Heavier model needed for reliable code (GPT-5.2 or Claude Opus 4.6). Same reasoning effort as existing `PixiCodeGenerator`.
- Both configurable via `llm_configs` table with component key `animation_enrichment`.

### Cost Estimate

For a typical chapter (10 guidelines × 3 variants × 7 cards avg = 210 cards):
- Decision: 30 LLM calls (one per variant) — ~$0.50
- Generation: ~90 cards selected (40%) × 1 call each — ~$5-10
- Retry: ~10% failure rate = 9 retries — ~$0.50
- **Total per chapter: ~$6-11**

---

## 7. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Explanation Cards (card phase) | **Major** | Cards gain animated visuals — new rendering path |
| Master Tutor (interactive) | **Minor** | Summary prompt gains "cards with visuals" metadata |
| Explanation Generation | **None** | Enrichment runs after, doesn't modify the generation pipeline |
| PixiJS interactive visuals | **None** | Existing per-turn visual generation unchanged |
| Card action (clear/explain differently) | **None** | Variant switching loads cards with their pixi fields intact |
| Session resume | **None** | Cards re-fetched from DB on resume, pixi fields included |
| TTS audio | **None** | Audio and visual are independent — audio auto-plays, visual is on-tap |

---

## 8. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Card has `pixi_code` but it fails to render in iframe | Frontend silently hides the visual. Card text remains fully functional. No error message shown to student. |
| LLM selects 0 cards for animation | Valid. Some topics (e.g., grammar definitions) may not benefit from visuals. Pipeline stores cards unchanged. |
| LLM selects all cards for animation | Unusual but valid. Pipeline generates code for all. The prompt guidance (30-60%) makes this unlikely. |
| Very long PixiJS code (>5000 chars) | Discard. Long code is usually over-engineered and buggy. Card gets no animation. |
| Enrichment runs before explanations exist | No-op. Pipeline checks for existing cards first, skips guidelines with no explanations. |
| Enrichment runs twice on same cards | Idempotent. Cards with existing `pixi_code` are skipped unless `--force` flag is set. |
| Card content changes after enrichment | Animation may be stale. Re-running explanation generation clears `pixi_code` (since cards_json is fully replaced on upsert). Re-run enrichment to regenerate. |
| Student on slow device / old phone | Iframe only loads on tap (not auto-play). If rendering is slow, student sees the card text immediately while visual loads. |
| Variant B ("Visual Walkthrough") cards | These already have ASCII visuals in the `visual` field. They can ALSO get pixi animations. The ASCII visual stays for non-JS contexts; the pixi animation is the rich version. |

---

## 9. Out of Scope

- **Real-time animation generation during sessions**: The interactive tutor already has this. This PRD is about pre-computed animations for explanation cards only.
- **User-generated animations**: Students cannot request or modify animations.
- **Animation quality auto-research**: No auto-research loop for visual quality in v1. Future work could add a `VisualClarityEvaluator`.
- **3D visuals or WebGL**: Pixi.js v8 2D only. 3D is unnecessary for the target subjects (Grade 3-5 Math/Science).
- **Animation caching/CDN**: Code is stored as text in DB, rendered client-side. No server-side rendering or image caching.
- **Accessibility**: Alt-text for visuals, screen reader support — important but out of scope for v1.

---

## 10. Open Questions

1. **Headless validation in v1?** Adding Puppeteer validation guarantees no broken animations reach students, but adds infrastructure complexity (Node.js dependency in the Python backend). Worth it for v1, or defer to v2?
2. **Subject filtering?** Should the pipeline skip animation enrichment for subjects unlikely to benefit (e.g., language arts), or always let the LLM decide? LLM-decides is simpler but costs more.
3. **Canvas size for cards?** The existing `VisualExplanation.tsx` uses 500x350. Should card-embedded visuals use a different size (e.g., full card width, shorter height) for a better mobile experience?

---

## 11. Success Metrics

- **Coverage**: 30-60% of explanation cards across Math and Science topics have animations after enrichment.
- **Render reliability**: >= 95% of cards with `pixi_code` render successfully in the frontend (no iframe errors).
- **Learning clarity**: Spot-check 20 animations manually — each should make the concept clearer than the card text alone. A child should be able to understand the visual without reading the card.
- **Engagement**: (Future measurement) Track "Visualise" button tap rate in analytics. Target: >= 60% of students tap at least one visual per topic.
- **Performance**: Visual renders in < 2 seconds after tap on a mid-range phone.
- **No regression**: Explanation card phase completion rate stays the same or improves. Card phase duration may increase slightly (students watching animations) — this is expected and positive.
