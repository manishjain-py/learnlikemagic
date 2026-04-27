# Baatcheet Dialogue Quality V2 — Designed-Lesson Architecture

**Date:** 2026-04-27
**Status:** In progress — experimental
**Supersedes (content axis):** `dialogue-quality-progress.md` (V1 / PR #122)
**Companion:** `gold-example-fractions-class4.md` — the benchmark we're aiming for
**Mode:** try → evaluate → keep/discard/iterate. Log results in §6. Plan is not fixed.

## 1. Problem

After PR #122 (four-layer overhaul: max reasoning + craft prompt + exemplars + folded refine), Baatcheet dialogues still read as Explain-content-with-question-marks rather than natural conversation. Surface rules are right but insufficient. The *kind of experience* hasn't shifted: a student who saw the Explain cards and then opens Baatcheet feels they're getting the same content with a different face, not a different learning modality.

## 2. What V1 fixed and why it wasn't enough

PR #122 raised the floor — no question+answer in same card, no boilerplate pivots, max reasoning, validator-clean output, exemplars in the prompt. Necessary but not sufficient. V1 treated misconceptions as soft material, conversation as free-form, and Meera's arc as a confidence trajectory. The result: cleaner content, same shape.

## 3. Target — gold-standard example

40-card Class-4 Fractions tutoring dialogue (see `gold-example-fractions-class4.md`). Four patterns make it work:

- **Narrative spine.** Sister-fairness story threads Card 1 → 11 → 25 → 40. Math hangs on the story, not the curriculum.
- **Misconceptions = architecture.** 3 documented misconceptions (whole-number bias, equal-parts, different-whole), each gets one trap-resolve cycle (~6-8 cards): hypothetical trap → student falls → concrete experience or funnel question → student articulates rule.
- **Move grammar.** Each card does one specific pedagogical move (hook, elicit, trap-set, observe-physical, funnel-question, articulate, callback, escalate-analogy, check, close) — not just speaker/structural.
- **Student-does-the-concrete.** Cards 13-18: tutor instructs Meera to fold paper, Meera reports observation, tutor articulates from her observation. Highest-bandwidth disproof.

Plus: threading (opening hook recalled mid + closed at end), three closing takeaways each tied to one designed misconception, voice texture (Hmm / Umm / Oh wait / Ohhh + Aha / Wow / High five / Spot on), character particulars (younger sister, friend Aarav, gets angry over chocolate).

**Calibration deltas vs current spec:**
- Card count: gold = 40; current spec = 25-35. Revise upper bound — 3 misconception cycles × ~6-8 cards + intro + close needs the room.
- Tutor turn length: gold goes up to ~30-38 words at articulation cards. Current ≤12-words/line × 1-3 lines is roughly compatible; don't tighten further.
- Meera turn length: 2-17 words, very variable. Current ≤10 words/line is fine.

## 4. Architecture shift

**The dialogue is a designed lesson with disguised structure, not a free-form conversation about concepts.**

| | Today | V2 |
|---|---|---|
| Pipeline | `(concepts + misconceptions + variant A) → cards → refine` | `(concepts + misconceptions + variant A) → lesson plan → cards → refine` |
| Misconceptions | Soft material in prompt | Each gets one designed trap-resolve cycle (the macro-structure) |
| Card design | Speaker + structural type | Each card has a designated pedagogical move |
| Spine | None | One Indian-household lived situation, threaded |
| Student physical action | Optional | Required ≥2 moments |

The lesson plan is a structured intermediate artifact: misconceptions (with research notes), narrative spine, concrete materials, macro-structure (hook → activate → introduce → trap-resolve × N → check → close), per-card move list with target concept/misconception.

Why split: plan reviewable before card-fill; plan persists for audit + autoresearch; plan-design and prose-craft become separable optimisation surfaces.

## 5. Plan (sequenced — discard freely if a phase doesn't move the needle)

| # | Phase | Status | Notes |
|---|---|---|---|
| 0 | Document V2 framing (this doc + gold example companion) | done | |
| 1 | Rewrite `docs/principles/baatcheet-dialogue-craft.md` — layer architecture (spine, misconceptions-as-cycles, move grammar, student-concrete) atop existing surface rules | done | |
| 2 | Draft new lesson-plan prompt + rewrite dialogue-generation prompt that consumes it | done | New: `baatcheet_lesson_plan_generation*.txt`. Rewritten: `baatcheet_dialogue_generation*.txt`. |
| 3 | Generate 1 topic against new prompts (ad-hoc, no service changes); eyeball-judge against gold | **done — PASS on 1st try** | run01-high: 4.50/5 avg, 39 cards, 3/3 misconception cycles complete, talk-ratio 1.70:1 (V1 was 4.7:1). $1.02, ~5 min. |
| 4 | If shape recognizable: wire service (`baatcheet_dialogue_generator_service.py`) — add `_generate_lesson_plan()` step, persist plan; regen 3-5 topics; iterate | not started | Recommended next session. |
| 5 | Add Baatcheet-specific evaluation dimensions (LLM-judged: spine present + threaded? cycle per misconception? move variety? student-concrete moments? takeaways tied to misconceptions? voice texture?) | partial | Mechanical rubric in `baatcheet_v2_eval.py` works; LLM-judge dimensions still TODO. |
| 6 | Autoresearch within new shape | not started | Hold until V2 is in production for ≥1 batch. |
| 7 | Formalize misconceptions-research stage with citations | not started | Quality lift; not blocking. |

**Stop conditions per phase:** if Phase 3 output isn't visibly closer to gold, the prompts need rethinking, not the wiring. Log decisions in §6.

## 6. Experiment log

### 2026-04-27 — V2 framing locked
- Diagnosed gaps from V1 by comparing PR #122 prompt + craft doc against user's 40-card gold example.
- Decision: layer architecture (spine, misconceptions-as-cycles, move grammar, student-concrete) above existing surface rules. Two-step generation (plan → cards).
- Hand-tune first; autoresearch later (it optimises a working shape, doesn't find one).

### 2026-04-27 — Phase 1 done: principles doc rewrite
- `docs/principles/baatcheet-dialogue-craft.md` restructured into 4 parts:
  - Part I (Architecture): pedagogy & naturalness, designed-lesson framing, narrative spine, misconceptions-drive-macro-structure (each = trap-resolve cycle), move grammar (15 named moves), student-does-the-concrete, threading + closing takeaways.
  - Part II (Surface Rules): kept V1 rules — curiosity gaps, examples-before-rules, earn-the-aha, Meera-from-reaction, no-boilerplate-pivots.
  - Part III (Voice & Character): tone calibration with explicit interjection lists, character particulars, emotional reframing, process praise.
  - Part IV (Length & Test): card budget bumped 25-35 → 30-40, schema compliance, "read as a student" final test extended with the V2 question — would a student who saw Explain feel they're getting something different?

### 2026-04-27 — Phase 2 done: prompts written
- New file: `baatcheet_lesson_plan_generation_system.txt` (≈230 lines) — produces structured plan: misconceptions with research notes + concrete disproofs, narrative spine with particulars + opening_hook + callbacks + closing_resolution, concrete materials, macro-structure phases, flat 30-40 card_plan with {slot, move, speaker, card_type, target, intent}. Includes a fully-worked exemplar plan derived from the gold fractions dialogue.
- New file: `baatcheet_lesson_plan_generation.txt` (user prompt) — passes topic, grade, key concepts, misconceptions, variant A as starting points.
- Rewritten: `baatcheet_dialogue_generation_system.txt` — now consumes the lesson plan as primary input. Move-by-move craft guidance (how to realize each move type as prose), required voice texture (≥3 tutor interjections, ≥3 student sounds, ≥3 spine callbacks), prose exemplars for selected moves drawn from gold.
- Rewritten: `baatcheet_dialogue_generation.txt` (user prompt) — slimmed down: passes lesson_plan_json, variant A reference (content fidelity check only), prior topics.
- Refine prompts (`baatcheet_dialogue_review_refine*.txt`) NOT yet updated — to be addressed in Phase 4 wiring.

### 2026-04-27 — Phase 3 done: V2 generation works on first try, PASS

**Test topic:** Math Class 4 — "Reading and Writing 5- and 6-Digit Numbers (Indian Numbering System)" — same topic V1 was tested on, for direct comparison.

**Run:** `llm-backend/scripts/baatcheet_v2_outputs/5-6-digit-indian-numbers/run01-high/`
- Effort: high (claude-opus-4-7 via CLI subprocess)
- Plan stage: 79s, $0.38, 3 misconceptions + 39-slot card plan
- Dialogue stage: 217s, $0.64, 39 cards
- **Total: ~5 min, $1.02** — far cheaper/faster than the V1 max-effort baseline (13.5 min plan + 25.5 min refine, $6.71)

**Mechanical eval (`baatcheet_v2_eval.py`): AVG 4.50/5, PASS**

| Dim | Score | Note |
|---|---|---|
| Spine threaded | 5/5 | 16 callback cards (target ≥3) |
| Misconception cycles complete | 5/5 | 3/3 cycles have trap-set + fall + resolve + articulate |
| Closing takeaways | 3/5 | eval flagged 2/3 — false negative (see "eval bugs" below) |
| Card count 30-40 | 5/5 | 39 cards |
| Move variety | 5/5 | 16 distinct moves |
| Student-act moments | 5/5 | 3 (cover comma / write side-by-side / column-by-column add) |
| No consecutive-move violations | 3/5 | 1 flagged (peer-reframe → tutor-reframe pair, actually OK) |
| Tiny beats | 4/5 | 0 tutor overlong, 2 peer cards 29-31w (cards 3 & 32) |
| Tutor interjections | 5/5 | 8 different (Aha, Wow, High five, Spot on, Got it, Brilliant, Perfect, Let me ask you) |
| Student sounds | 5/5 | 5 different (Hmm, Umm, Oh wait, Ohhh, Wait!) |

**Surface compliance:** 0 audio violations (no markdown, no naked `=`, no emoji), 0 student_name flag mismatches, 0 peer cards leaking student_name. Talk ratio dropped V1 4.7:1 → V2 1.70:1.

**Qualitative read against gold:** the dialogue has the same shape as the fractions gold:
- Lived-Indian opening (Papa-on-road-trip vs gold's sister-fairness) — generalizes to a fresh spine, no regurgitation.
- All 3 misconceptions voiced by Meera with hesitation sounds + visible reasoning ("Hmm. Four-seven-three-five-two?", "Hmm. 100,000? I see it like that on calculator screens.", "Umm... 9,99,100? Or maybe 100,000?").
- Three concrete student-act moments where Meera/student physically writes/covers/adds and reports observation.
- Funnel questions doing the cognitive work ("Which grouping helps you say 'one lakh' out loud?").
- Articulate-only-after-student-does-work in every cycle.
- Spine callbacks: cards 17, 26, 35 reuse Papa/sign + a final close callback.
- Reframe cards 36-37 with growth-mindset ("Somersaults mean your brain is stretching").
- Closing card 40 names all three takeaways and resolves the spine ("Now when Papa points at any milestone sign, you read it loud and proud").

**Decision: PASS on first try, no iteration needed.** Architecture lands recognizably; further polish is autoresearch territory.

**What worked:**
- Two-stage generation (plan → cards) cleanly separates pedagogical design from prose craft. Plan output is auditable on its own — you can read just `plan.json` and tell whether the architecture is sound before spending tokens on prose.
- Move grammar in the plan + per-move craft guidance in the dialogue prompt forces the LLM out of "tutor explains chunk → Meera asks question" mode.
- Concrete-disproof field on each misconception primes the student-act moves naturally; the LLM didn't have to invent these on the fly.
- Voice texture explicit (interjection list, student-sound list) — the prompt's "≥3 different" framing translated into 8 + 5 in actual output.

**What didn't work as well:**
- Cards 33→34 are tutor→tutor (funnel question, then tutor articulates without giving Meera a chance to guess). Plan slot 34 should have been peer_turn (Meera tries) + slot 35 articulate. Minor flow issue.
- Card 3 peer turn ran 29 words (over 25-word soft cap). Card 32 ran 31 words. Both content-rich but slightly over budget.
- Eval bugs (cosmetic): close-takeaways scoring used full-string substring match for spine particulars and over-long misconception names — produced false negatives on a clearly-good closing card. Will tighten in next iteration.

**Costs and time vs V1:**

| | V1 (PR #122 baseline) | V2 |
|---|---|---|
| Stages | 1 generation + 1 refine | 1 plan + 1 dialogue |
| Time @ max effort | 39 min | n/a (used `high` for V2) |
| Time @ high effort | n/a | **~5 min** |
| Cost | $6.71 | **$1.02** |
| Talk ratio | 4.7:1 | **1.70:1** |
| Misconceptions surfaced | 2/4 | **3/3 with full trap-resolve cycles** |

V2 is 5-7× cheaper at lower-but-better-aligned effort. The architecture, not the effort, is doing the work.

### 2026-04-27 — Visual-pass (separate stage) added — works on 1st try

**Motivation:** generation pass shouldn't be overburdened with visuals (text quality is the goal). A separate post-pass reads the finalized dialogue and decides where a static diagram earns its keep — same separation as Stage 5c does for Explain cards. For the experiment, we generate inline SVG so it renders directly in the HTML viewer; production path uses the existing PixiJS generator.

**Implementation:**
- New prompt files: `baatcheet_visual_pass_system.txt` + `baatcheet_visual_pass.txt` — single LLM call selects 4-8 high-value cards AND emits SVG for each.
- New script: `llm-backend/scripts/baatcheet_v2_visualize.py` — calls the prompt, merges visuals into `dialogue_with_visuals.json`.
- HTML renderer auto-detects `dialogue_with_visuals.json` and renders SVGs inline below speech bubbles.

**Selection rules in the prompt:**
- 4-8 cards total, quality > quantity (a bad visual is worse than no visual).
- Pick cards that reference a concrete artifact, reinforce a misconception's concrete disproof, anchor a `student-act` move, or make a referenced scene visible.
- Skip greetings, hesitation sounds, simple Q&A.
- Distribute: at least one per misconception cycle, at least one in the closing/check phase. No clusters of 3 adjacent visuals.
- Visual-intent: one plain-language sentence saying WHAT to draw. SVG: viewBox 320×180, simple shapes only, max ~12 elements, Indian numbering format.

**Run on run01-high:**
- Effort: high. 151s. **$0.62.** All 6 SVGs validated as well-formed XML.
- Cards selected (one per cycle, well-spread): 2 (hook), 13 (M2), 21 (M1), 27 (guided practice), 32 (M3), 39 (independent check).
  - Card 2: blue Jaipur road sign with population 30,46,500 prominent — anchors the hook.
  - Card 13: number 47,352 with finger over comma, '47' and '352' boxed — disproves M2 visually.
  - Card 21: side-by-side 1,00,000 (Indian) vs 100,000 (Western) with chunk borders highlighted — disproves M1.
  - Card 27: 6,75,300 broken into three colored chunks labeled lakh / thousand / hundreds — guided practice.
  - Card 32: two place-value charts before/after 99,999 + 1 with rollover arrows — disproves M3.
  - Card 39: "three lakh forty thousand" → 3,40,000 with three labeled chunk-boxes — independent-check answer.

**Total experiment cost so far:** $1.02 (plan + dialogue) + $0.62 (visualize) = **$1.64** for a fully visualised 39-card dialogue.

### 2026-04-27 — Learning: Western-comparison rule was softened in V2 rewrite, restored

**What surfaced:** in run01, M1 was framed as *"Western comma placement carried into Indian system"* and its disproof literally placed `1,00,000` next to `100,000` labelled "Indian vs Western." Card 25 articulated *"Indian rule: 3-2-2, not 3-3-3."* Card 21 SVG showed the comparison side-by-side.

**Root cause:** Explain has a strong canonical rule (`explanation_generation_system.txt` line 28 + mirrors in 8 other prompts): *"Never label the student's context as 'the Indian way' or compare it to a 'Western / American / international' way. ... Only compare when the teaching guideline explicitly teaches comparison."* In the V2 rewrite this was reduced to a one-liner under §11 of the dialogue prompt; absent entirely from the lesson-plan prompt and the visual-pass prompt.

**Fix (applied this session, no regen):**
- `baatcheet_lesson_plan_generation_system.txt` — added a CRITICAL block right after concrete materials, with WRONG / RIGHT examples for misconception names, disproofs, and articulate phrasings.
- `baatcheet_dialogue_generation_system.txt` — replaced the one-liner with Explain's full canonical phrasing, including the "only compare when the guideline explicitly teaches comparison" exception.
- `baatcheet_visual_pass_system.txt` — added an explicit visual-side example: WRONG side-by-side `1,00,000` vs `100,000` labelled Indian/Western; RIGHT just `1,00,000` with chunk borders.
- `docs/principles/baatcheet-dialogue-craft.md` §18 — restored the canonical framing aligned with `easy-english.md` §8.
- run01 NOT regenerated. Future runs will get the corrected framing without further intervention.

**Generalisable learning for prompt rewrites:** when consolidating prompt rules into a new architecture, audit each rule from the source prompts at original strength — short paraphrases lose the WRONG/RIGHT examples that do most of the load-bearing. Especially rules that protect cultural framing or pedagogical defaults; those tend to have non-obvious failure modes that the examples are doing the work of preventing.

### 2026-04-27 — Phase 4.5: 2nd topic (non-math) — water cycle, PASS qualitatively

**Topic:** Science Class 4 — "The Water Cycle." Picked for non-math generalization test (handover suggested "Science weather cycles").

**Run:** `llm-backend/scripts/baatcheet_v2_outputs/water-cycle-class4/run01-high/`
- Plan: 86s, $0.30, 3 misconceptions (M1 evap-only-when-boiling, M2 clouds-are-cotton, M3 water-disappears), spine = "Meera's wet white school uniform on terrace clothesline, worried it won't dry by morning."
- Dialogue: 109s, $0.45, 39 cards.
- Visual pass: 165s, $0.62, **7 SVGs** (cards 5/13/22/26/28/34/40 — one per phase).
- **Total: 360s (6 min), $1.37.** Cheaper than math run01 ($1.64).

**Mechanical eval: AVG 4.20/5, "PARTIAL".** Strong (5/5): spine threading (25 cards, over-counts on common tokens like "Meera" / "rain" — known eval rubric weakness), misconception cycles (3/3 complete), card count (39), move variety (17 distinct, math: 16), tutor interjections (5: aha, spot on, brilliant, high five, let me ask you), student sounds (5: hmm, oh wait, umm, ohhh, wait!). Weaker: student-act (2/5 — eval undercount, see below); close-takeaways (3/5 — eval bug, see below); consecutive-moves (3/5 — peer-reframe→tutor-reframe, OK pedagogically); tiny-beats (4/5 — card 34 = 42w tutor, card 3 = 29w peer).

**Qualitative read against gold (the truth signal):**
- Lived-Indian opening — terrace clothesline, "Meera washed her white school uniform last evening."
- All 3 misconceptions voiced by Meera with hesitation: "Haan, only when it boils!" / "Cotton! Or maybe white smoke." / "Puddle just dries up and disappears."
- TWO student-act moments: card 5 (wet fingertip on hand, watch evaporate) tagged `concretize`, card 22 (cold glass, observe condensation droplets) tagged `student-act`.
- Funnel-then-articulate pattern in every cycle ("the sun warms the terrace, and even my hand is a little warm. Maybe that is enough?" → "Brilliant thinking, Meera. Any warmth turns water into vapour…").
- Spine callbacks: cards 13 (terrace heat check), 35 (uniform water rises to cloud), 40 (close: "Tomorrow's rain on Meera's terrace might be yesterday's uniform water").
- Growth-mindset reframe at cards 36-37 ("This feels like magic, sir" → "It is really just three steps repeating").
- Closing card 40 names all three takeaways tied 1-to-1 with the designed misconceptions, plus spine resolution.
- Indian household particulars sprinkled: "amma boils water for tea", "monsoon rain", "haan", steel glass from fridge.

**Visualizations** (7, all well-formed):
- Card 5: hand with single drop ("watch for 1 minute") — anchors student-act.
- Card 13: terrace clothesline + sun + vapour rising ("just sun's warmth — no stove") — disproves M1 in spine artifact.
- Card 22: cold steel glass with droplets — anchors M2 student-act.
- Card 26: cloud of droplets + rain streaks ("cloud = tiny droplets → join → fall as rain") — replaces cotton mental model at the articulate moment.
- Card 28: kettle steam rising to cold ceiling — guided practice example.
- Card 34: full water-cycle diagram (sun → evaporation → cloud → precipitation → water) — at the M3 synthesis articulation.
- Card 40: three icons (sun / cloud-of-droplets / circular arrow) — three takeaways.

**Decision: PASS qualitatively. Architecture generalizes to non-math.**
- The two "PARTIAL" dimensions are eval rubric bugs already noted in run01-math, not real quality issues:
  1. **Student-act undercount** — card 5 is functionally a student-act (physical action by student) but tagged `concretize` in plan. Eval should count `concretize` moves whose intent contains "wet/touch/place/wait/observe" verbs, OR architecture should consolidate `concretize` and `student-act` into one move.
  2. **Spine particular not in close** — eval substring-matches full particular sentences ("Meera washed her white school uniform last evening"). Close says "Tomorrow's rain on Meera's terrace might be yesterday's uniform water" — clear callback, but doesn't contain any particular sentence verbatim. Same bug logged on run01-math.
- One real observation: **talk ratio 2.45:1** vs math 1.70:1. Tutor cards average ~30w vs math ~25w. Science topic is more notation-heavy ("we call it evaporation", "we call it condensation", "we call it precipitation"). Watch this in Phase 4 — refine prompt should compress notate moves.

**Costs vs math run01:**

| | Math run01 | Water-cycle run01 |
|---|---|---|
| Plan | 79s / $0.38 | 86s / $0.30 |
| Dialogue | 217s / $0.64 | 109s / $0.45 |
| Visual | 151s / $0.62 | 165s / $0.62 |
| **Total** | **447s / $1.64** | **360s / $1.37** |
| Eval avg | 4.50/5 | 4.20/5 |
| Cards | 39 | 39 |
| Misconception cycles | 3/3 | 3/3 |
| Talk ratio | 1.70:1 | 2.45:1 |

**Verdict:** V2 architecture is robust to topic choice. Ready for Phase 4 service wiring without a third topic test (two topics across two domains is sufficient evidence — the architecture is doing the work, not topic-specific prompt features).

### 2026-04-27 — Phase 4 done: service wiring

V2 designed-lesson architecture is now wired into the production pipeline. Stage 5b's flow is `(variant A + misconceptions) → lesson plan → dialogue → refine`, with the plan persisted on `topic_dialogues.plan_json` for downstream provenance + autoresearch.

**Files changed:**
- `llm-backend/shared/models/entities.py` — `TopicDialogue.plan_json = Column(JSONB, nullable=True)` (nullable for V1 backward compat).
- `llm-backend/db.py` `_apply_topic_dialogues_table()` — idempotent ALTER TABLE adds `plan_json` for existing deployments.
- `llm-backend/shared/repositories/dialogue_repository.py` — `upsert(plan_json=...)` flows the plan through to the row.
- `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py` — major surgery:
  - New `_generate_lesson_plan()` method + `_build_lesson_plan_prompt()`.
  - `_LESSON_PLAN_PROMPT` + `_LESSON_PLAN_SYSTEM_FILE` loaded as module-level constants alongside generation/refine.
  - `LessonPlanValidationError` + `_validate_plan()` — backstop against LLM drift (top-level keys exist, 25-40 card_plan entries, 2-3 misconceptions, spine has situation).
  - `generate_for_guideline()` flow rewired: plan → dialogue → refine (N rounds with validator-issue feedback) → prepend welcome → final validate → upsert with `plan_json`.
  - `_build_generation_prompt(plan, guideline, variant_a)` — drops key_concepts/misconceptions/guideline_text (those go to plan stage); feeds `lesson_plan_json` placeholder.
  - `_build_refine_prompt(cards, plan, guideline, variant_a, validator_issues)` — same simplification.
  - `stage_collector` now snapshots the lesson plan as a separate stage entry (in addition to initial + refine_N).
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_review_refine_system.txt` — rewritten:
  - Top intro: "the plan is the SPEC. Your job is to make the dialogue realize it cleanly."
  - **R1 (validator defects):** kept verbatim per `feedback_prompt_rule_consolidation` memory. Card-count band updated 12-34 → 30-40 to match V2 plan budget. Cultural-framing rule now includes "only compare when guideline explicitly teaches comparison."
  - **R2 replaced:** was "coverage check (concepts variant A teaches)"; now "PLAN ADHERENCE" with 7 sub-rules (P1 move grammar, P2 cycle completeness, P3 misconceptions stay in peer's mouth, P4 spine threading, P5 funnel does cognitive work, P6 talk ratio ≤2:1 with notate-compression hint, P7 voice texture).
  - **R3 (naturalness):** kept verbatim — failure modes A-H are gold.
  - Bottom note: "Do NOT add or remove cards. The plan's card_plan is the spec."
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_review_refine.txt` — user prompt rewritten to feed `{lesson_plan_json}` (drops `{key_concepts_list}`, `{misconceptions_list}`, `{guideline_text}`).
- `llm-backend/tests/unit/test_baatcheet.py` — **+11 tests** (all passing): `TestLessonPlanValidator` (6), `TestTopicDialoguePlanJsonRoundTrip` (2), `TestDialogueRepositoryUpsertWithPlan` (3). 47/47 Baatcheet tests pass; zero new regressions in broader suite.

**No changes to:**
- `llm-backend/book_ingestion_v2/api/sync_routes.py` — Stage 5b orchestration already calls `service.generate_for_guideline(...)`, which now internally does plan → dialogue → refine. No route changes needed.
- LLM config — both plan and dialogue stages share the existing `baatcheet_dialogue_generator` config (claude-opus-4-7, admin-tunable effort). Separability deferred until evidence of needing different effort settings.

**Validation:** unit tests pass. End-to-end production-pipeline run (Stage 5b on a real guideline) still recommended before declaring V2 ready for the next book ingestion. Run command pattern: hit the `/run-baatcheet-dialogue` endpoint or call `service.generate_for_guideline(guideline)` from a shell.

**Next:**

- **Phase 4.6 — Stage 5c visual pass wiring.** Currently `BaatcheetVisualEnrichmentService` only enriches `card_type=visual` cards. Extend it to:
  - Run the visual selector (using `baatcheet_visual_pass_system.txt` minus the SVG generation; just selection + visual_intent).
  - For each selected card, inject `visual_intent` and call existing `PixiCodeGenerator.generate()`.
  - Persist `visual_explanation` on each enriched card.
- **Phase 5 (Baatcheet-specific eval dimensions):** the rubric in `baatcheet_v2_eval.py` is a starting point but needs hardening — token-based substring matching for spine close (currently matches full particular sentences); count `concretize` moves with physical-action verbs as student-acts; LLM-judge for qualitative dimensions like "does the misconception come from peer's mouth" and "does the funnel question do the cognitive work".
- **Phase 6 (autoresearch within new shape):** once shape is locked, optimise spine variety, trap wording, voice texture density. Don't run autoresearch until V2 is in production for at least one batch.
- **Phase 7 (formalize misconception research):** today the lesson-plan prompt is asked to cite plausible evidence for each misconception. For trust + rigor, a dedicated research stage with web tool use should produce a per-topic misconception bank.
- **Re-run at `max` effort once** to see if there's a meaningful prose-craft delta vs `high`. If not, default to `high` (5x cheaper).
