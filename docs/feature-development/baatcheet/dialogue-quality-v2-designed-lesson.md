# Baatcheet Dialogue Quality V2 — Designed-Lesson Architecture

**Date:** 2026-04-27 (updated 2026-04-28)
**Status:** Phases 0-4.5 done + prod-validated end-to-end on math G4 ch1 topic 1. Phase 4.6 (Stage 5c V2 visual-pass wiring) is the recommended next step — it's the gate to prod visuals on V2 dialogues.
**Supersedes (content axis):** `dialogue-quality-progress.md` (V1 / PR #122)
**Companion:** `gold-example-fractions-class4.md` — the benchmark we're aiming for
**Mode:** try → evaluate → keep/discard/iterate. Log results in §6. Plan is not fixed.
**Resume here:** §7 "Current state and resume guide" is the single source of truth for where we are + what's next. Read it first if you're picking up from a fresh session.

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
| 3 | Generate 1 topic against new prompts (ad-hoc, no service changes); eyeball-judge against gold | done — PASS on 1st try | run01-high: 4.50/5 avg, 39 cards, 3/3 misconception cycles complete, talk-ratio 1.70:1 (V1 was 4.7:1). $1.02, ~5 min. |
| 3.5 | Visual-pass (separate stage) | done | 6 SVGs on math run01, $0.62, all well-formed. Selection-by-judgement, 4-8 cards, "quality > quantity". |
| 3.6 | Cultural-framing rule restoration | done | `feedback_prompt_rule_consolidation` honored — Explain canonical phrasing copied verbatim into V2 lesson-plan + dialogue + visual-pass prompts. |
| 4 | Wire service (`baatcheet_dialogue_generator_service.py`) — `_generate_lesson_plan()` step, persist plan, refine consumes plan | **done — end-to-end validated on math G4 ch1 topic 1** | Service wiring + DB column + `_validate_plan` + 11 unit tests (commit `484f562`). End-to-end prod run produced dialogue `0b90b017-…`, 4.30/5 mechanical eval, talk ratio 1.78:1. Two real bugs surfaced + fixed: JSON preamble tolerance (`0fa0d88`), card-cap 35→42 (`522f9c4`). |
| 4.5 | 2nd topic generalization test (non-math) | done — PASS qualitatively | Water cycle Class 4: 4.20/5, talk ratio 2.45:1 (science is more notation-heavy), $1.37 / 6 min, 7 SVGs. Architecture generalizes. Two domains is sufficient evidence — skipped a 3rd topic test. |
| 4.6 | **Stage 5c V2 visual-pass wiring** — gate to prod visuals on V2 dialogues | **not started — recommended next** | V1 `BaatcheetVisualEnrichmentService` only enriches `card_type=visual` cards; V2 plans don't generate those → prod visuals on V2 dialogues = 0 today. Visual-pass prompts already updated to default-generate + `visual_required` (commit `356b147`); just need to wire the production service. See §7. |
| 5 | Add Baatcheet-specific evaluation dimensions (LLM-judged: spine present + threaded? cycle per misconception? move variety? student-concrete moments? takeaways tied to misconceptions? voice texture?) | partial | Mechanical rubric in `baatcheet_v2_eval.py` works; has known cosmetic bugs (close-takeaways substring matching, student-act undercount on `concretize` moves). LLM-judge dimensions + token-based matching = Phase 5. |
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

### 2026-04-27 evening — End-to-end prod-pipeline run on math G4 ch1 topic 1

Goal: validate the full Phase-4 wiring on a real guideline, against the production DB, end to end. Two real bugs surfaced and were fixed during this run.

**Driver:** `llm-backend/scripts/baatcheet_v2_run_stage5b.py` — calls `service.generate_for_guideline()` directly against the prod DB without the HTTP / `chapter_jobs` plumbing. Useful for end-to-end V2 validation on real guidelines without going through the full ingestion harness.

**Guideline:** `23632b15-a6bf-45d5-990e-a04c89bf29ee` — math G4 / "Reading and Writing 5- and 6-Digit Numbers." Variant A existed (24 cards). Existing V1 dialogue (27 cards, no `plan_json`) was overwritten by the V2 output.

**Bug 1 — JSON preamble in refine output (commit `0fa0d88`).**
- V2 refine prompt's combined R1+R2+R3 density (validator defects + PLAN ADHERENCE + naturalness) is dense enough that even at max effort the model sometimes narrates analysis before the JSON ("Looking at this dialogue, I need to fix several issues: …") despite the explicit "JSON only" instruction.
- `shared/services/llm_service.parse_json_response` uses strict `json.loads` and crashed.
- Fix: replaced the 3 service call sites (`_generate_lesson_plan`, `_generate_dialogue`, `_review_and_refine`) with `_parse_json_with_preamble_tolerance`, which:
  1. Tries strict `json.loads` (fast path for clean output).
  2. Unwraps ` ```json ` fenced blocks if present.
  3. Walks each `{` position with `json.JSONDecoder.raw_decode` and returns the first valid object.
- The naive "first `{` to last `}`" approach fails when preambles contain curly-brace literals like `{student_name}` or `{topic_name}` (the analysis bullets routinely do). The raw_decode-per-position walk skips past them because they don't parse as valid JSON.
- Belt-and-suspenders: strengthened the refine system prompt's top with "respond with ONE JSON object … your response must start with `{` and end with `}`. Any other text fails the pipeline."
- +6 unit tests in `TestJSONPreambleTolerance` cover clean JSON, preamble, trailing prose, fenced blocks, the real failure mode (preamble with curly-brace literals), and the no-JSON error path.

**Bug 2 — V1-era card-cap constants (commit `522f9c4`).**
- V2 plan target is 30-40 slots → final deck (with welcome) is 31-41 cards.
- `MAX_TOTAL_CARDS = 35` (V1 PRD §FR-11 hard cap from when the budget was 25-30) rejected valid V2 dialogues at the final-validation step. Surfaced as `DialogueValidationError: card count 39 outside [25,35]` after plan + dialogue + refine all completed correctly.
- Bumped to 42 (V2 cap 41 + 1 slack for the rare extra card). Floor stays at 25 — the plan validator's lenient lower bound. Don't bump again without thinking; runaway dialogues should still fail.

**Resume from partial collector** rather than re-paying ~$2.50 for plan+dialogue+refine. The plan and refined cards were already in `stage_collector_partial.json`, just hadn't survived final validation. Inline resume (one-off Python invocation): `_validate_plan(plan)` → reconstruct `DialogueCardOutput` from cards → prepend welcome → `_validate_cards` → `repo.upsert(plan_json=plan, …)`. Validates the fix without re-running the LLM stages that already succeeded.

**Persisted dialogue (production DB):**
- `topic_dialogues.id = 0b90b017-4825-40fd-be09-a6a455de8239`
- 39 cards (V2), `plan_json` populated (38 slots, 3 misconceptions)
- `generator_model = 'claude-opus-4-7'`
- `source_content_hash = '541595eb5620b871e4e0…'`

**Mechanical eval: AVG 4.30/5 (PARTIAL by rubric).**
- Strong (5/5): spine threading (16 cards), 3/3 misconception cycles complete, 39 cards, 16 distinct moves, **0 consecutive-move violations**, 7 tutor interjections, 5 student sounds, talk ratio **1.78:1** (right at V2 target ≤2:1).
- Weaker: close-takeaways (1/5 — same eval rubric bug as prior runs; close clearly names all 3 takeaways but uses paraphrasing rather than verbatim misconception names), tiny-beats (3/5 — 1 tutor 42w + 4 peer cards 26-33w over caps).

**Spine generated:** "Road trip to Naani's village; Meera saw a population board '4,06,253', her brother Aarav kept asking 'didi, how many people?'" — Indian-household lived setting, 3 misconceptions (digit-by-digit reading, Western 3-3-3 commas, face-vs-place value).

**Open issue surfaced — talk-ratio compression on prod run.** Refine prompt's P6 (talk ratio ≤2:1, with notate-compression hint) is helping in aggregate (1.78:1, on target), but it didn't compress 4 peer-overlong cards (cards 3 / 22 / 35 / 38 at 26-33w over the 25w soft cap). Worth an even stricter peer-cap reminder if it persists across more runs.

### 2026-04-27 evening — Visual generator: default-generate + `visual_required` (commit `356b147`)

User feedback: *"encourage the visual generator to put visuals in more cards. so it could be — where it makes no sense, skip … otherwise generate a suitable visual. but wherever the dialogue generator has marked visuals_required, there it's absolutely necessary."* The 7-of-39 (~18%) coverage from the math run01 visual pass was clean but left many concept-anchoring cards without the diagram that would help them land.

Two changes shift the default from "skip unless clearly worth it" to "generate unless clearly filler", with a hard guarantee on the cards the planner thinks need a visual most.

1. **Plan schema gains `visual_required: boolean` per `card_plan` slot** (required field; planner sets explicitly).
   - `baatcheet_lesson_plan_generation_system.txt` — schema updated, instructional section "VISUAL_REQUIRED — mark cards where a diagram is essential, not decorative" with explicit true/false guidance per move type. The Class-4 fractions exemplar in the same prompt extended with `visual_required` on every slot (~36% true) so the LLM has a worked reference for setting the field.
   - **True for:** each misconception's articulate, every student-act, the first notate after a concept lands, any card whose intent references a specific number / chart / artifact, the close.
   - **False for:** greetings, hook-as-words-only, fall (peer voicing misconception verbally), reframe (emotion), pure observation reports, activate transitions.

2. **Visual pass system prompt rewritten** (`baatcheet_visual_pass_system.txt`):
   - **HARD:** every card with `visual_required: true` MUST be visualized. No "couldn't think of a strong one" outs — the planner already decided.
   - **DEFAULT:** generate for any card with concrete content (numbers, expressions, charts, comparisons, artifacts, observed scenes). Target shifted from 4-8 to **12-18** on a 30-40-card dialogue.
   - **SKIP:** only when ALL of (purely conversational filler / no number-or-expression-or-artifact / would only decorate).
   - Existing genres list moved up so the LLM doesn't agonise over which template — match a card to a genre, generate, move on.
   - User-prompt instruction line reflects the new contract.
   - Backward-compat: existing plans without the `visual_required` field still work — the visual pass falls back to default-generate logic.

**Test on existing math G4 ch1 topic 1 dialogue** (plan was generated *before* this change, so no `visual_required` flags — tests the default-generate logic alone):

| | Before | After |
|---|---|---|
| Visuals | 7 | **18** |
| Coverage | 18% of cards | **46%** |
| Cost | $0.58 | $0.88 |
| Time | 120s | 270s |
| $/visual | $0.083 | $0.049 |

Distribution: cards 2/5/6/8/10/11/13/16/17/21/22/24/27/30/31/32/35/39 — spread across hook → all 3 misconception cycles → guided practice → independent check → close. The 7-SVG prior run is preserved as `dialogue.html.7svgs.bak`, `visualizations.json.7svgs.bak`, `dialogue_with_visuals.json.7svgs.bak` in the same run dir.

**Note:** the prod-DB plan (`0b90b017-…`) lacks `visual_required` flags. To test the full new flow with `visual_required` honored as a hard contract, regenerate plan + dialogue + visual pass on the same guideline (~$2.50, ~15 min) — see §7 step A.

## 7. Current state and resume guide

This section is the single source of truth for "where are we / what's next." If you're picking up from a fresh session, read this first; the rest of the doc is the chronology that produced this state.

### What's in production (Stage 5b)

- **Service wiring (commit `484f562`):** `BaatcheetDialogueGeneratorService.generate_for_guideline()` does plan → dialogue → refine → upsert. Plan persists on `topic_dialogues.plan_json`. Stage collector snapshots plan + initial + refine_N. Refine prompt's R1 (validator defects) and R3 (naturalness failure modes A-H) kept verbatim per `feedback_prompt_rule_consolidation`; only R2 was replaced (V1's coverage check → PLAN ADHERENCE with 7 sub-rules P1-P7).
- **JSON tolerance (commit `0fa0d88`):** `_parse_json_with_preamble_tolerance` walks each `{` and runs `JSONDecoder.raw_decode` to skip past curly-brace literals like `{student_name}` in LLM preambles. 6 unit tests in `TestJSONPreambleTolerance`.
- **Card caps (commit `522f9c4`):** `MIN_TOTAL_CARDS=25, MAX_TOTAL_CARDS=42` (V2 plan target 30-40 + welcome + 1 slack). Don't bump further without thinking — runaway dialogues should still fail.
- **Visual generator prompts (commit `356b147`):** plan slots have `visual_required: bool` (planner sets explicitly); visual pass defaults to generate (target 12-18 visuals on a 30-40-card dialogue) with a hard requirement on every `visual_required: true` slot. **Caveat:** these prompts run via the experiment harness (`baatcheet_v2_visualize.py`); production Stage 5c still uses the V1 path — see Phase 4.6 below.

### Math G4 ch1 topic 1 — DB state of record

- `topic_dialogues.id = 0b90b017-4825-40fd-be09-a6a455de8239`
- `guideline_id = 23632b15-a6bf-45d5-990e-a04c89bf29ee`
- 39 cards (V2), `plan_json` populated (38 slots, 3 misconceptions, spine = "road trip to Naani's village; Aarav asking 'didi, how many people?'")
- `generator_model = 'claude-opus-4-7'`
- `source_content_hash = '541595eb5620b871e4e0…'`
- **Cards do NOT have visuals attached** (Stage 5c V1 didn't run on this V2 dialogue, and even if it had, it only enriches `card_type=visual` cards which the V2 plan didn't generate).
- Audio synthesis hasn't run on this dialogue (separate pipeline; not blocking).

**Confirm DB state from a fresh session:**
```bash
cd /Users/manishjain/repos/learnlikemagic
/Users/manishjain/repos/learnlikemagic/llm-backend/venv/bin/python -c "
import sys; sys.path.insert(0, '/Users/manishjain/repos/learnlikemagic/llm-backend')
from database import get_db_manager
from sqlalchemy import text
db = get_db_manager().get_session()
td = db.execute(text(\"\"\"
  SELECT id, jsonb_array_length(cards_json) AS card_count, (plan_json IS NOT NULL) AS has_plan
  FROM topic_dialogues WHERE guideline_id='23632b15-a6bf-45d5-990e-a04c89bf29ee'
\"\"\")).first()
print(td)
"
```
Expected: `(0b90b017-..., 39, True)`.

### Open issues / observations

1. **Phase 4.6 — Stage 5c V2 visual-pass wiring not done.** This is the gate to **prod visuals on V2 dialogues = 0**. V1 `BaatcheetVisualEnrichmentService` only enriches `card_type=visual` cards which V2 plans don't generate. Touchpoints when picking this up:
   - `llm-backend/book_ingestion_v2/services/baatcheet_visual_enrichment_service.py` — extend, don't replace. Run the visual selector via `baatcheet_visual_pass_system.txt` (selection + `visual_intent` only, drop the SVG generation). For each selected card inject `visual_intent` and call `tutor/services/pixi_code_generator.PixiCodeGenerator.generate()`. Persist `visual_explanation` on each enriched card via the existing pixi_code field on `topic_dialogues.cards_json`.
   - `llm-backend/book_ingestion_v2/api/sync_routes.py` `_run_baatcheet_visual_enrichment` — the route that triggers Stage 5c.
   - `llm-backend/scripts/baatcheet_v2_visualize.py` — the experiment-harness pattern for prompt-feeding (joins by `slot` / `card_idx`).
   - Test: round-trip a V2 plan + dialogue through the enrichment service; assert PixiJS code is on every `visual_required: true` card.

2. **Existing prod plan lacks `visual_required` flags.** The plan was generated before commit `356b147`. Re-running the visual pass on it tested only the default-generate logic (which produced 18 SVGs, up from 7). To test the full new flow with `visual_required` honored as a hard contract, regenerate plan + dialogue + visual pass on the same guideline — see step A below.

3. **Eval rubric cosmetic bugs persist** (already noted on math run01 + water-cycle run01 + prod run):
   - `student-act` undercount: `concretize` moves with physical-action verbs ("touch / wet / observe") aren't counted.
   - `close-takeaways` substring matching is too strict for spine particulars and full misconception names. Card 39 of the prod run names all 3 takeaways but rubric scored 1/5 because it uses paraphrasing.
   - Fix lives in **Phase 5** — token-based matching + LLM-judge dimensions.

4. **Talk ratio ≤2:1 is consistently met** at high effort (math run01 1.70:1, prod 1.78:1) and *almost* met at lower-effort science (water cycle 2.45:1, ~25% over). Refine prompt's P6 is helping in aggregate but didn't compress 4 peer-overlong cards (cards 3 / 22 / 35 / 38 at 26-33w over the 25w cap) on the prod run. Watch — if it persists, P6 needs a stricter peer-cap reminder.

5. **Refine prompts are V2-aligned** but lack a "schema only" reminder — no explicit instruction about the dialogue card schema's allowed `card_type` enum. If refine LLM ever invents a card_type value (e.g., `"question_card"`), the card-validator catches it at final validation. Worth adding to R1 if it ever fires in practice.

### Recommended next steps in priority order

**A. Regenerate math G4 ch1 topic 1 with the new prompt set** (~$2.50, ~15 min). Tests the full new flow including `visual_required` being set by the planner (existing prod plan was generated before that change):

```bash
cd /Users/manishjain/repos/learnlikemagic
/Users/manishjain/repos/learnlikemagic/llm-backend/venv/bin/python \
  /Users/manishjain/repos/learnlikemagic/llm-backend/scripts/baatcheet_v2_run_stage5b.py \
  23632b15-a6bf-45d5-990e-a04c89bf29ee --review-rounds 1
# Then visual pass:
/Users/manishjain/repos/learnlikemagic/llm-backend/venv/bin/python \
  /Users/manishjain/repos/learnlikemagic/llm-backend/scripts/baatcheet_v2_visualize.py \
  /Users/manishjain/repos/learnlikemagic/llm-backend/scripts/baatcheet_v2_outputs/prod-23632b15/prod-stage5b-v2/ \
  --effort high --subject Mathematics
# Then render + eval:
/Users/manishjain/repos/learnlikemagic/llm-backend/venv/bin/python \
  /Users/manishjain/repos/learnlikemagic/llm-backend/scripts/baatcheet_v2_render_html.py \
  /Users/manishjain/repos/learnlikemagic/llm-backend/scripts/baatcheet_v2_outputs/prod-23632b15/prod-stage5b-v2/
/Users/manishjain/repos/learnlikemagic/llm-backend/venv/bin/python \
  /Users/manishjain/repos/learnlikemagic/llm-backend/scripts/baatcheet_v2_eval.py \
  /Users/manishjain/repos/learnlikemagic/llm-backend/scripts/baatcheet_v2_outputs/prod-23632b15/prod-stage5b-v2/
```
Verify: count of `visual_required: true` slots in the new plan, count of visuals from the visual pass should be ≥ that count (every `visual_required: true` slot must get an SVG; default-generate adds more).

**B. Phase 4.6 — Stage 5c V2 visual-pass wiring.** Gate to prod visuals on V2 dialogues. Touchpoints listed in Open Issue #1 above.

**C. Audio synthesis for math G4 ch1 topic 1.** Trigger the audio synthesis stage on the persisted dialogue (`AudioGenerationService` — see `virtual_teacher_poc.md` memory for the Google Cloud TTS Chirp 3 HD Kore details). Existing-stage task — no new code needed.

**Later:**
- **Phase 5 — eval rubric hardening.** Promote `baatcheet_v2_eval.py` mechanical rubric into `llm-backend/services/baatcheet_eval_service.py`. Token-based matching for spine close + misconception names. Count `concretize` moves with physical-action verbs as student-acts. Add LLM-judge dimensions ("does the misconception come from peer's mouth?", "does the funnel question do the cognitive work?", "is the closing tied to designed misconceptions?").
- **Phase 6 — autoresearch within new shape.** Hold until V2 is in production for ≥1 batch. Optimise spine variety, trap wording, voice texture density, peer-cap compression.
- **Phase 7 — formalize misconception research.** Dedicated stage with web tool use producing per-topic misconception bank with real citations.
- **Re-run at `max` effort once** to see if there's a meaningful prose-craft delta vs `high`. If not, default to `high` (5x cheaper).

### Critical files

**Code (committed; 5 commits ahead of `origin/main`, not pushed):**
- `llm-backend/shared/models/entities.py` — `TopicDialogue.plan_json` JSONB column.
- `llm-backend/db.py` — `_apply_topic_dialogues_table()` migration (idempotent ALTER TABLE).
- `llm-backend/shared/repositories/dialogue_repository.py` — `upsert(plan_json=...)`.
- `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py` — V2 flow, `_validate_plan`, `_parse_json_with_preamble_tolerance`, card-cap 35→42.
- `llm-backend/book_ingestion_v2/prompts/baatcheet_lesson_plan_generation_system.txt` + `.txt` — schema with `visual_required`, instructional section, exemplar.
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_generation_system.txt` + `.txt` — consumes `lesson_plan_json`, move-by-move craft guidance.
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_review_refine_system.txt` — R2 PLAN ADHERENCE (P1-P7), R1 + R3 verbatim from V1, top-of-prompt JSON-only emphasis.
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_review_refine.txt` — `lesson_plan_json` placeholder.
- `llm-backend/book_ingestion_v2/prompts/baatcheet_visual_pass_system.txt` + `.txt` — default-generate, hard `visual_required` requirement, target 12-18.
- `llm-backend/scripts/baatcheet_v2_run_stage5b.py` — driver for end-to-end Stage 5b runs against prod DB without HTTP plumbing.
- `llm-backend/tests/unit/test_baatcheet.py` — +17 tests this session (11 in Phase 4: `TestLessonPlanValidator` ×6, `TestTopicDialoguePlanJsonRoundTrip` ×2, `TestDialogueRepositoryUpsertWithPlan` ×3; 6 in `TestJSONPreambleTolerance`). 47/47 Baatcheet tests pass.

**Test outputs (gitignored — `llm-backend/scripts/baatcheet_v2_outputs/`):**
- `5-6-digit-indian-numbers/run01-high/` — math run01 (Phase 3, prior session).
- `water-cycle-class4/run01-high/` — water-cycle run01 (Phase 4.5).
- `prod-23632b15/prod-stage5b-v2/` — math G4 ch1 topic 1 production run (Phase 4 + visual generator update). Has `plan.json`, `dialogue.json`, `dialogue_with_visuals.json` (18 SVGs), `dialogue.html`, `eval_scores.json`, plus the 7-SVG backups.

**Scripts (all at `llm-backend/scripts/`):**
- `baatcheet_v2_experiment.py` — standalone two-stage harness (no project imports, edit `TEST_TOPIC` at top).
- `baatcheet_v2_run_stage5b.py` — end-to-end via prod service against prod DB. **Use for production validation.**
- `baatcheet_v2_visualize.py` — visual pass on a run dir.
- `baatcheet_v2_render_html.py` — HTML viewer.
- `baatcheet_v2_eval.py` — mechanical rubric.

### Commits this session

5 commits, all on `main`, ahead of `origin/main`, not pushed:

| Commit | Subject |
|---|---|
| `484f562` | feat: Baatcheet V2 — designed-lesson architecture + service wiring |
| `1c6c77f` | docs: daily memory + Predict-Then-Learn / Knowledge-Component idea note |
| `0fa0d88` | fix(baatcheet): tolerate JSON preamble in V2 LLM responses |
| `522f9c4` | fix(baatcheet): bump V2 card-count validator constants (35 -> 42) |
| `356b147` | feat(baatcheet): plan marks visual_required slots; visual pass defaults to generate |

### Key decisions (for context)

- **`feedback_prompt_rule_consolidation` honored** — V1 refine R1 (validator defects) and R3 (naturalness failure modes A-H) kept verbatim into V2. Only R2 was replaced because it was V1-shape-specific (coverage check on concepts variant A teaches).
- **Card-cap bump 35 → 42, not unlimited.** V1 PRD §FR-11 was a deliberate hard cap; V2 has its own deliberate budget (30-40). Runaway dialogues should still fail at validation.
- **Visual pass count 4-8 → 12-18, not unlimited.** A bad visual is still worse than no visual; the floor is "every concrete card", not "every card".
- **Resume from partial collector** rather than re-paying $2.50 when the constants bug was fixed. Validates the fix without re-running LLM stages that already succeeded.
- **`visual_required` lives in plan, not in dialogue cards.** Plan is the spec; dialogue realizes the spec. Visual pass joins on `slot` / `card_idx`. Avoids a new field on the dialogue card schema.
- **Reused `baatcheet_dialogue_generator` LLM config for both plan + dialogue stages.** Didn't add a separate `baatcheet_lesson_plan_generator` config. Separability deferred until evidence of needing different effort settings.
- **Two topics across two domains is sufficient evidence** for "V2 generalizes." Skipped a 3rd topic test.
