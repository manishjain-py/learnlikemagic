# Baatcheet Dialogue V2 — Session Handover (2026-04-27)

**Purpose:** complete context to resume the V2 effort from a fresh session. Read this end-to-end before doing anything; everything important from this session is captured here.

---

## TL;DR

After PR #122's surface-level fixes, Baatcheet dialogues still read as Explain-with-question-marks. We diagnosed this as an *architectural* gap, not a tuning gap, and shipped a designed-lesson architecture with two-stage generation (lesson plan → cards) plus a separate visualization pass.

**One test run on Math G4 place-value PASSED on first try.** Mechanical rubric 4.50/5, all 3 misconception cycles structurally complete, talk ratio 1.70:1 (V1 was 4.7:1), total cost $1.64 / ~7.5 min for plan + dialogue + 6 visuals (V1 baseline was $6.71 / 39 min).

**Next gating step:** wire the prompts into `baatcheet_dialogue_generator_service.py` so generation runs in the production pipeline, not just from the standalone experiment harness.

---

## Where we are in the V2 plan

| # | Phase | Status |
|---|---|---|
| 0 | Document V2 framing | done |
| 1 | Rewrite principles doc | done |
| 2 | Lesson-plan + dialogue prompts | done |
| 3 | Run on a topic + eval | done — **PASS first try** |
| 3.5 | Visual pass (separate stage) | done — 6 SVGs inline |
| 3.6 | Cultural-framing rule restoration | done (post-review fix) |
| 4 | Service wiring | **not started — next gate to production** |
| 4.5 | 2nd topic test | not started — recommended before Phase 4 |
| 5 | LLM-judge eval dimensions | partial (mechanical only) |
| 6 | Autoresearch within new shape | not started — hold until prod |
| 7 | Dedicated misconception-research stage with citations | not started |

Full phases table + experiment log in `dialogue-quality-v2-designed-lesson.md`.

---

## What we built and why

### The diagnosis (re-validate this with the user before doing more work)

V1 (PR #122) treated the gap as a *tuning* problem: better prompt rules, exemplars, max reasoning effort, refine round. Result: cleaner content, same shape — still curriculum-with-question-marks, not conversation-as-different-modality.

V2 reframes it as an *architectural* problem. The gold-standard 40-card Class 4 fractions dialogue (user shared, saved as `gold-example-fractions-class4.md`) has four load-bearing patterns V1 was missing:

1. **Narrative spine** — one Indian-household lived situation threaded through the entire dialogue.
2. **Misconceptions = architecture** — each documented misconception gets one trap-resolve cycle (~6-8 cards). The misconceptions become the macro-structure, not soft material.
3. **Move grammar** — each card does one specific pedagogical move (hook, trap-set, fall, student-act, funnel, articulate, callback, etc.) instead of just "tutor explains" / "Meera asks."
4. **Student-does-the-concrete** — at least 2 moments where the student physically acts (folds paper, covers a comma, stacks columns) and reports observation, then the tutor articulates from the observation.

### The two-stage generation

V1: `(concepts + misconceptions + variant A) → cards → refine`
V2: `(concepts + misconceptions + variant A) → **lesson plan** → cards → refine`

The lesson plan is a structured intermediate JSON: misconceptions with research notes + concrete disproofs, narrative spine (situation, particulars, opening hook, callbacks, closing resolution), concrete materials, macro-structure phases, and a flat per-card move sequence with `{slot, move, speaker, card_type, target, intent}`.

Card-fill becomes constrained ("realize this plan") instead of open-ended ("have a conversation"). This is what produces the architectural shape.

### The visualization pass (separate stage)

Generation prompt should not be overburdened with visuals. A separate post-pass reads the finalized dialogue, picks 4-8 high-value cards, writes a `visual_intent`, and (for the experiment) generates inline SVG. Production path uses the existing `PixiCodeGenerator` instead of SVG — the `visual_intent` strings are the universal interchange format.

The visual pass is intentionally additive: it does NOT change card text or card type; it just attaches a `visual_explanation` to existing cards (the schema already supports this on any card, not just `card_type=visual`).

---

## Critical files (all created or modified in this session)

### Documentation
- `docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md` — **the working doc.** Full diagnosis, plan, phases table, complete experiment log. Read this first.
- `docs/feature-development/baatcheet/gold-example-fractions-class4.md` — the 40-card benchmark dialogue (user-shared, AI-research-generated). What V2 is targeting.
- `docs/feature-development/baatcheet/session-handover-2026-04-27-v2.md` — this file.
- `docs/principles/baatcheet-dialogue-craft.md` — **rewritten.** 4 parts: Architecture / Surface Rules / Voice & Character / Length & Test. Card budget bumped 25-35 → 30-40.

### Prompts (in `llm-backend/book_ingestion_v2/prompts/`)

NEW:
- `baatcheet_lesson_plan_generation_system.txt` — produces structured lesson plan; includes a worked exemplar derived from the gold fractions dialogue.
- `baatcheet_lesson_plan_generation.txt` — user prompt for plan generation.
- `baatcheet_visual_pass_system.txt` — single-call visual selector + SVG generator.
- `baatcheet_visual_pass.txt` — user prompt for the visual pass.

REWRITTEN:
- `baatcheet_dialogue_generation_system.txt` — now consumes the lesson plan as primary input. Move-by-move craft guidance, voice texture rules, prose exemplars from gold.
- `baatcheet_dialogue_generation.txt` — user prompt slimmed to just lesson_plan_json + variant A reference.

NOT YET UPDATED (handle in Phase 4):
- `baatcheet_dialogue_review_refine_system.txt` and `_refine.txt` — refine prompts still reference the V1 input shape. Phase 4 must update these to validate plan-followed.

### Scripts (in `llm-backend/scripts/`)
- `baatcheet_v2_experiment.py` — standalone two-stage runner (no project imports; calls `claude` CLI directly). Hardcoded test topic.
- `baatcheet_v2_visualize.py` — runs visual pass on a completed run dir.
- `baatcheet_v2_render_html.py` — produces standalone HTML viewer of any run dir; auto-detects `dialogue_with_visuals.json` and renders SVGs inline.
- `baatcheet_v2_eval.py` — mechanical rubric eval; produces `eval_scores.json` + `rendered.md`.

### Test run output
Located at `llm-backend/scripts/baatcheet_v2_outputs/5-6-digit-indian-numbers/run01-high/`:
- `plan.json` — lesson plan (3 misconceptions, road-trip-with-Papa spine, 39 card slots)
- `dialogue.json` — generated cards
- `dialogue_with_visuals.json` — cards with 6 SVG visualizations merged in
- `visualizations.json` — raw visualization output (intent + svg + why per card)
- `dialogue.html` — pretty rendering with misconceptions panel, eval scores, phase dividers, chat bubbles, inline SVGs
- `rendered.md` — markdown render
- `eval_scores.json` — mechanical rubric scores
- `run_summary.json` — run metadata (cost, time, effort)
- `01_plan_*`, `02_dialogue_*`, `03_visual_pass_*` — per-stage prompt + raw response logs

### Memory entries (auto-loaded in future sessions)
- `project_baatcheet_dialogue_v2.md` — V2 effort pointer + status
- `feedback_experimentation_mode.md` — work in try → evaluate → keep/discard mode
- `feedback_prompt_rule_consolidation.md` — when consolidating prompts, copy strongest existing rule verbatim; don't paraphrase

---

## Test run summary (run01-high)

**Topic:** Math Class 4 — "Reading and Writing 5- and 6-Digit Numbers (Indian Numbering System)" — same topic V1 was tested on, for direct comparison.

**Plan stage:** 79s, $0.38, 3 misconceptions (M1 comma placement, M2 digit-by-digit reading, M3 lakh transition), 39 card slots, spine = "road trip with Papa, milestone signs, Papa challenges Meera to read big numbers."

**Dialogue stage:** 217s, $0.64, 39 cards. All three trap-resolve cycles structurally complete with full move sequence: trap-set → fall → student-act → observe → funnel → observe → articulate → escalate/callback.

**Visual pass:** 151s, $0.62, 6 SVGs (cards 2/13/21/27/32/39 — one per phase). All SVGs validated as well-formed XML.

**Total experiment cost: $1.64 / ~7.5 min.**

**Mechanical eval: 4.50/5 average, PASS.** Strongest dimensions (5/5): spine threading (16 callback cards), misconception cycles complete, card count 30-40, move variety (16 distinct), student-act moments (3), tutor interjections (8 different), student sounds (5 different). Weaker (3/5): closing takeaways (eval has cosmetic false-negative — see Known issues below); no-consecutive-moves (1 flagged, actually OK).

**Comparison vs V1 baseline:**

| | V1 (PR #122 max-effort) | V2 (high-effort) |
|---|---|---|
| Stages | 1 generation + 1 refine | 1 plan + 1 dialogue (+ 1 visual) |
| Time | 39 min | ~5 min (+ 2.5 min visual) |
| Cost | $6.71 | $1.02 (+ $0.62 visual) |
| Talk ratio | 4.7:1 | 1.70:1 |
| Misconceptions surfaced | 2/4 with weak treatment | 3/3 with full trap-resolve cycles |

V2 is 5-7× cheaper at lower effort. **Architecture, not effort, is doing the work.**

---

## Known issues in run01-high (don't be surprised)

1. **Western-comparison framing leak.** M1 was framed as "Western comma placement carried into Indian system" with side-by-side `1,00,000` vs `100,000` SVG and "3-2-2 not 3-3-3" articulation. Root cause: V2 rewrite softened Explain's canonical "student's world is default" rule to a one-liner; missing entirely from the lesson-plan + visual prompts. **Fix applied this session** to all 3 V2 prompts + principles doc §18 (with WRONG/RIGHT examples copied verbatim from Explain). run01-high NOT regenerated; future runs will get the corrected framing.

2. **Cards 33→34 are tutor→tutor.** Card 33 funnel question ("That new column to the left of ten-thousands. What could we call it?") is followed immediately by card 34 articulate from tutor — Meera doesn't get to guess "lakh" first. The plan should have inserted a peer slot between funnel and articulate. Fix in Phase 4: add a plan validator that requires post-funnel cards to hand off to peer.

3. **Cards 3 and 32 marginally over 25-word peer cap.** Content-rich; would tighten in refine round.

4. **Eval rubric cosmetic bugs.** `eval_scores.json` shows close-takeaways at 3/5 due to substring matching on the full misconception name; qualitative read shows the close clearly references all 3 misconceptions. Will tighten the rubric (token-based matching) in Phase 5.

---

## Next steps — recommended order

### Immediate (this is what a fresh session should pick up)

**Step 1: Run a 2nd topic to validate generalization.** ~$1.64, ~7.5 min. Pick a non-math topic (English grammar tense, Science weather cycles) — confirms architecture isn't fragile to topic choice. Procedure:
1. Edit `TEST_TOPIC` dict in `llm-backend/scripts/baatcheet_v2_experiment.py` (top of file, lines 22-50).
2. Update `SLUG` (line 53) to match.
3. Run: `python3 llm-backend/scripts/baatcheet_v2_experiment.py --effort high --run-label run01-high`
4. Visualize: `python3 llm-backend/scripts/baatcheet_v2_visualize.py llm-backend/scripts/baatcheet_v2_outputs/<slug>/run01-high/`
5. Render: `python3 llm-backend/scripts/baatcheet_v2_render_html.py llm-backend/scripts/baatcheet_v2_outputs/<slug>/run01-high/`
6. Eval: `python3 llm-backend/scripts/baatcheet_v2_eval.py llm-backend/scripts/baatcheet_v2_outputs/<slug>/run01-high/`
7. Show user the HTML; ask if shape holds for non-math.

**Step 2: Phase 4 — service wiring.** This is the gate to production. Touchpoints:
- `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py` — add `_generate_lesson_plan()` step before `_generate_dialogue()` (around line 324). Pass plan as primary input to `_build_generation_prompt()` (line 484).
- `llm-backend/shared/models/entities.py` — add `plan_json` JSONB column on `topic_dialogues` (line 341 area). Plus a Alembic migration.
- `llm-backend/book_ingestion_v2/repositories/dialogue_repository.py` — persist + retrieve plan.
- Refine prompts (`baatcheet_dialogue_review_refine_system.txt` + `_refine.txt`) — rewrite to validate plan-followed (each move's intent realized; each misconception cycle complete; spine threaded).
- `llm-backend/book_ingestion_v2/api/sync_routes.py` (line 2472) — Stage 5b orchestration: load variant A → **generate plan** → generate dialogue → refine → prepend welcome → validate → persist.
- Tests in `tests/unit/test_baatcheet.py` — add tests for plan generation + plan-input dialogue generation.

**Step 3: Wire visual pass into Stage 5c.** Currently Stage 5c only enriches `card_type=visual` cards. Extend `BaatcheetVisualEnrichmentService` to:
- Run the visual selector (using `baatcheet_visual_pass_system.txt` minus the SVG generation; just selection + visual_intent).
- For each selected card, inject `visual_intent` and call existing `PixiCodeGenerator.generate()`.
- Persist `visual_explanation` on each enriched card.

### Later

**Step 4: Phase 5 — eval dimensions.**
- Promote mechanical rubric (`baatcheet_v2_eval.py`) into `llm-backend/services/baatcheet_eval_service.py`.
- Add LLM-judge dimensions: "does the misconception come from peer's mouth?", "does the funnel question do the cognitive work?", "is the closing tied to designed misconceptions?". Output 1-5 scores plus a sentence of justification per dimension.
- Hook into existing tutor evaluation pipeline.

**Step 5: Phase 6 — autoresearch.** Hold until V2 is in production for ≥1 batch. Then optimise spine variety, trap wording, voice texture density. Don't run autoresearch on a non-working shape — it optimises, doesn't find.

**Step 6: Phase 7 — formalize misconception research.** Currently the lesson-plan prompt asks the LLM to cite plausible evidence inline. For trust + rigor, build a dedicated stage with web tool use that produces a per-topic misconception bank with real citations.

---

## How to resume in a fresh session

1. **Read first** (in this order):
   - `MEMORY.md` (auto-loaded, points at the project + feedback memories)
   - `docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md` (working doc — diagnosis + experiment log)
   - This handover doc
   - `docs/feature-development/baatcheet/gold-example-fractions-class4.md` (the benchmark)

2. **If user asks to continue Phase 4 wiring**, study these before editing:
   - `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py` (V1 service — extend, don't replace)
   - `llm-backend/book_ingestion_v2/api/sync_routes.py` lines 2472-2592 (V1 stage 5b orchestration)
   - `llm-backend/shared/models/entities.py` `TopicDialogue` table (line 341)

3. **If user asks to run another topic**, use the procedure in "Step 1" above. Don't burn budget — stick with `--effort high`.

4. **If user asks about V1 vs V2**, the comparison is in run01-high's `eval_scores.json` and the working doc's experiment log. V1's progress data is in `dialogue-quality-progress.md`.

5. **If user mentions "the gold example"** — that's the user-shared 40-card Class 4 fractions dialogue, saved as `gold-example-fractions-class4.md`. It is the benchmark, not a generated artifact.

6. **If user mentions "the Explain rule" / "easy-english.md"** — they're referring to the canonical "student's world is the default, not a variant" rule. We restored this across V2 prompts after they flagged it during review. The pattern is captured in the `feedback_prompt_rule_consolidation.md` memory.

---

## Decisions made this session (for context)

- **Two-stage generation, not one.** Discussed and chose plan → cards over a single richer prompt because (a) plan is reviewable before card-fill, (b) plan persists for autoresearch, (c) plan-design and prose-craft become separable optimisation surfaces.
- **`high` effort, not `max`.** V1 used max ($2.90/call). V2 PASS at high ($0.38 plan + $0.64 dialogue). Architecture beats effort. Default to `high`; reserve `max` for cases where output is below bar.
- **Visual pass as a separate stage, not part of generation.** Per user direction: don't overburden the text engine.
- **SVG for the experiment, PixiJS for production.** SVG renders inline in HTML reviews; PixiJS already exists in production via `PixiCodeGenerator`. The `visual_intent` string is the interchange format — same selector LLM call, different rendering backend.
- **Don't regenerate run01-high after the Western-comparison fix.** Cost vs value — the fix is in the prompts; future runs will get correct framing.
- **Card budget 30-40 (was 25-35).** Three misconception cycles need ~7 cards each plus intro + close.
- **Refine prompts not updated yet.** Defer to Phase 4 — they need to validate plan-followed, which requires the plan to exist in the service flow.

---

## References

**Working doc + experiment log:** `docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md`
**Gold standard:** `docs/feature-development/baatcheet/gold-example-fractions-class4.md`
**Principles V2:** `docs/principles/baatcheet-dialogue-craft.md`
**Test run output:** `llm-backend/scripts/baatcheet_v2_outputs/5-6-digit-indian-numbers/run01-high/`
**HTML viewer:** `llm-backend/scripts/baatcheet_v2_outputs/5-6-digit-indian-numbers/run01-high/dialogue.html`

**Prompts:**
- `llm-backend/book_ingestion_v2/prompts/baatcheet_lesson_plan_generation_system.txt`
- `llm-backend/book_ingestion_v2/prompts/baatcheet_lesson_plan_generation.txt`
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_generation_system.txt`
- `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_generation.txt`
- `llm-backend/book_ingestion_v2/prompts/baatcheet_visual_pass_system.txt`
- `llm-backend/book_ingestion_v2/prompts/baatcheet_visual_pass.txt`

**Scripts:**
- `llm-backend/scripts/baatcheet_v2_experiment.py`
- `llm-backend/scripts/baatcheet_v2_visualize.py`
- `llm-backend/scripts/baatcheet_v2_render_html.py`
- `llm-backend/scripts/baatcheet_v2_eval.py`

**Memory:**
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/MEMORY.md`
- `project_baatcheet_dialogue_v2.md`
- `feedback_experimentation_mode.md`
- `feedback_prompt_rule_consolidation.md`

**Predecessor (V1):**
- `docs/feature-development/baatcheet/dialogue-quality-progress.md` (PR #122)
- `docs/feature-development/baatcheet/dialogue-quality-impl-plan.md`
- PR #122 commit `47d6bf3`
