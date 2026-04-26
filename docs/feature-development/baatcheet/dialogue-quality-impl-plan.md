# Baatcheet — Dialogue Quality Implementation Plan

**Date:** 2026-04-26
**Status:** Approved (interview alignment 2026-04-26)
**Depends on:** Baatcheet V1 (`PRD.md`, `impl-plan.md`)
**Analysis:** `dialogue-quality-analysis.md`
**Tracker:** `dialogue-quality-progress.md`
**Principles:** `docs/principles/baatcheet-dialogue-craft.md` (new, this PR)

---

## 1. Goal

Pedagogy primary; naturalness as a quality bar. Make Baatcheet dialogues teach better — discovery rhythm, scaffolded misconception correction, examples-before-rules — while the conversational form reads natural, not stilted.

Detailed diagnosis: `dialogue-quality-analysis.md`.

## 2. Locked decisions (interview 2026-04-26)

| Area | Decision |
|---|---|
| Goal | Pedagogy primary, naturalness as quality bar |
| Coupling to variant A | Same concepts, free choreography; variant A unchanged |
| Meera | Co-learner with arc within each topic; "got it" moments fine |
| Validation | Manual review for now |
| Autoresearch | Pattern reuse only (no offline loop this round) |
| Sequencing | All 4 layers, single cohesive PR |
| Layer 1 (reasoning) | Adapter `effort_map` fix + Baatcheet service `reasoning_effort="max"` |
| Layer 2 (prompt) | Craft directives + 1 annotated GOOD + 1 BAD exemplar (real-but-different topic) + decouple inputs (guideline + flat key-concepts list + misconceptions) |
| Layer 2 (anchors) | Drop hard requirement; soft suggestion only |
| Layer 3 (critic) | Folded into existing refine round (defects + coverage + naturalness in one prompt) |
| Layer 4 (admin) | `reasoning_effort` per-component on LLM Config page (default `max`); `review_rounds` on individual admin pages; no temperature/max_tokens/UI prompt editing |
| Backfill | None — forward only |
| Comparison doc when piloting | Skip; just regen + read fresh |
| Scope | Text dialogue craft only — TTS/avatar/visual out of scope |

## 3. Implementation

### Layer 1 — Reasoning at max

**Adapter fix** (`shared/services/claude_code_adapter.py:127`):
- Replace `effort_map = {"low":"low","medium":"medium","high":"high","xhigh":"max"}` with `{"low":"low","medium":"medium","high":"high","xhigh":"xhigh","max":"max"}`. Each service-level value maps to its own CLI level. Removes the existing silent xhigh→max conflation.

**Service bump** (`book_ingestion_v2/services/baatcheet_dialogue_generator_service.py:450,474`):
- `reasoning_effort="high"` → `"max"` on both gen and refine calls.

**DB default:** Layer 4 schema migration sets `reasoning_effort="max"` for all `llm_config` rows.

### Layer 2 — Generation prompt rewrite

**(a) Craft directives** added to `book_ingestion_v2/prompts/baatcheet_dialogue_generation_system.txt`:
- Question and its answer never in the same tutor card. Questions live alone.
- ≥2 earned aha-moments per dialogue: build tension, reveal a card or two later.
- Meera doesn't volunteer rehearsal numbers. She speaks because something just happened.
- Banned phrase: `{student_name}, your turn now!` — pivots embedded in conversation flow.
- Examples before rules. State a rule → next card must apply it concretely.
- Soft real-world example: use a culturally-grounded Indian context only when it makes a concept land naturally; do not force one.
- Meera's arc within a topic: uncertain → wrong attempt(s) → scaffold → click → confident by summary. Later questions sharper than early ones.

**(b) Few-shot exemplars** appended to system prompt:
- 1 GOOD exemplar (~10 cards, real-but-different topic — e.g., G3 fractions). Inline annotations showing why each turn works.
- 1 BAD exemplar (~6 cards, paraphrased from observed failure modes). Annotations showing why each turn fails.
- Authored by the AI engineer, redlined by Manish before lock.

**(c) Decouple inputs** in `_build_generation_prompt` (`baatcheet_dialogue_generator_service.py:484`):
- Replace `VARIANT A EXPLANATION CARDS` JSON dump.
- New input `KEY CONCEPTS TO COVER` — flat bulleted list extracted from variant A card titles + summary. No card structure.
- Keep `VARIANT A REFERENCE` available, flagged "for content fidelity verification, not structural template."
- Misconceptions section unchanged.
- Anchors not added (per locked decision).

### Layer 3 — Folded refine round

Update `book_ingestion_v2/prompts/baatcheet_dialogue_review_refine_system.txt` with three responsibilities in a single LLM call:

1. **Fix validator defects** (current — banned chars, counts, missing visual_intent, etc.).
2. **Coverage check** — for each concept variant A teaches, ensure it appears in the dialogue. Add cards if any concept missing.
3. **Naturalness rewrite** — find the most artificial-feeling turns (Q+A in same card, Meera as script-prop, boilerplate pivots, unearned wow, rules before examples) and rewrite them with surrounding context.

Reasoning effort `"max"` (Layer 1). Existing rounds unchanged: 0 on `fast`, 1 on `balanced`, 2 on `thorough`.

### Layer 4 — Admin config

**Schema migration** (Alembic): add `reasoning_effort VARCHAR(10) NOT NULL DEFAULT 'max'` to `llm_config` table. Backfill all existing rows to `"max"`.

**Backend:**
- `LLMConfigService` returns `reasoning_effort` alongside `provider`, `model_id`.
- `LLMService.from_config()` reads `reasoning_effort` from config; `.call()` consumes it as the default when caller passes `"none"`.
- Components passing explicit `reasoning_effort=` in code keep working (override path).

**Important — call-site overrides win.** The admin DB knob is the *default*; explicit `reasoning_effort=` arguments on `.call()` still override. Eight production services deliberately pin a lower value for latency/cost reasons:
| Service | Pinned effort |
|---|---|
| `explanation_generator_service.py:356,439` | `"high"` |
| `chapter_topic_planner_service.py:54` | `"high"` |
| `refresher_topic_generator_service.py:215` | `"high"` |
| `study_plans/services/generator_service.py:141` | `"high"` |
| `audio_text_review_service.py:298` | `"medium"` |
| `practice_bank_generator_service.py:417,459` | `"medium"` |
| `check_in_enrichment_service.py:434,489` | `"medium"` |
| `animation_enrichment_service.py:538,606` | `"low"` / `"medium"` |

These were not changed in this PR — they encode deliberate per-stage choices. To change them, drop the explicit arg in code (admin then tunes via the UI knob). The tracker captures this for reviewers.

**LLM Config admin page** (`llm-frontend/src/features/admin/pages/LLMConfigPage.tsx`):
- New column "Reasoning effort" with dropdown: low/medium/high/xhigh/max.
- Per-row save updates `reasoning_effort` alongside provider+model.

**Topic pipeline admin** (`llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx`):
- Surface `review_rounds` per stage. Read from `topic_pipeline_orchestrator.py` quality-level defaults; editable override in a follow-up if needed (read-only display sufficient for V1).

## 4. Test plan

**Local manual** (Math G4 Ch1 T1):
- Regen via "Generate Baatcheet dialogue" admin button.
- Confirm: generator_model = `claude-opus-4-7`, refine round logs `reasoning_effort=max`.
- Read full dialogue. Compare informally against `/tmp/baatcheet_g4_c1_t1.txt` (current state on disk).
- Validate: questions never bundled with answers; Meera arc visible; no boilerplate pivots; misconceptions explored not just named.

**LLM Config admin page:**
- Reasoning effort dropdown shows for all components.
- Save persists to DB.
- Baatcheet's next regen reads new setting.

**Unit tests:**
- `tests/test_claude_code_adapter.py`: `effort_map` returns CLI value for all 5 inputs (low/medium/high/xhigh/max), distinct.
- `tests/test_llm_config_service.py`: returned config includes `reasoning_effort`.
- `tests/test_baatcheet_dialogue_generator_service.py`: `_generate_dialogue` and `_review_and_refine` pass `reasoning_effort="max"` to LLM call (when config-default applied).

## 5. Out of scope (this PR)

- TTS voice tuning, Meera voice selection, audio pacing.
- Avatar redesign.
- Visual narration craft on Stage 5c cards.
- Backfill of existing dialogues.
- Hindi/Hinglish code-switching.
- Cross-topic continuity for Meera.
- Meera asking the real student.
- Autoresearch offline prompt evolution loop.
- Dedicated coverage validator beyond what the refine round catches.
- `temperature` / `max_tokens` / UI prompt editing in admin.

## 6. References

- Analysis: `dialogue-quality-analysis.md`
- Tracker: `dialogue-quality-progress.md`
- Craft principles: `docs/principles/baatcheet-dialogue-craft.md`
- Baatcheet V1 PRD: `PRD.md`
- Baatcheet V1 impl: `impl-plan.md`
- Cross-cutting principles: `docs/principles/interactive-teaching.md`, `how-to-explain.md`, `easy-english.md`, `autoresearch.md`
