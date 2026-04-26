# Baatcheet — Dialogue Quality Analysis & Improvement Plan

**Date:** 2026-04-25
**Status:** Diagnosis complete. Locked decisions and final approach live in `dialogue-quality-impl-plan.md`. Progress: `dialogue-quality-progress.md`.
**Depends on:** Baatcheet V1 (`PRD.md`, `impl-plan.md`)

---

## 1. Context

Baatcheet V1 is shipped. Pre-scripted dialogue between Mr. Verma (tutor) + Meera (peer) generated at ingestion (Stage 5b), one dialogue per topic, 25–35 cards. Pipeline working end-to-end. **Quality of the conversation itself is the gap.**

## 2. Problem

Generated dialogues feel artificial. Read like dialogue-shaped monologue, not classroom conversation. Tutor states facts → Meera echoes/reacts → next fact. Rules come before examples. Questions get answered in the same card. No earned curiosity, no real-world anchor, no scaffolded misconception correction. Doesn't feel like a teacher and a curious peer figuring something out together.

## 3. What we examined

Math G4 Ch1 T1 — *Reading and Writing 5- and 6-Digit Numbers* (guideline `23632b15`, dialogue `0bb9f74b`, 34 cards, generated 2026-04-25 by `claude-opus-4-7`).

| Metric | Value |
|---|---|
| Card types | welcome 1, tutor_turn 16, peer_turn 9, visual 3, check_in 4, summary 1 |
| Tutor word count (incl. visual narration) | 287 |
| Meera word count | 61 |
| Talk ratio | tutor : Meera ≈ 4.7 : 1 |
| Tutor cards with Q + A in same card | 4 (cards 6, 18, 21, 24) |
| Cards 2–5 | greeting filler — ~12% of deck |
| Genuine misconception turns by Meera | 2 (cards 15, 19) — only strong peer turns |
| Pivots ending "your turn now!" | 2 (cards 9, 29) — boilerplate |

## 4. Findings (with card refs)

**A. Meera is a script-prop, not a peer.** Volunteers facts unprompted (card 5: *"Yes, biggest 4-digit number is 9,999"* — no question asked). Mechanically applies rules tutor just stated (card 7 applies card 6's rule — not discovery). Invents rehearsal numbers (card 28: *"Take 3,52,100. Is the value of 5 just 5?"*).

**B. Curiosity gaps collapsed inside single cards.** Cards 6, 18, 21 bundle question + answer in one tutor turn. Card 21: *"What is 99,999 plus 1? It is 1,00,000. We call this one lakh!"* — question and reveal in one breath. Lakh has no payoff because no gap was opened.

**C. Rules before examples** — backwards from `how-to-explain.md` §5. Card 18 lists 4 abstract steps for comma placement *before* showing one example. Lakh concept (card 21) introduced *after* the comma rule (card 18) — even though the comma rule only makes sense once you've felt the need for lakh.

**D. Misconceptions named, not explored.** Card 15: Meera reads "47,352" as "four seven three five two." Card 16 corrects mechanically: *"Oh Meera, that is digit by digit. Say: forty-seven thousand…"* No probing question, no scaffold. Violates `interactive-teaching.md` §4 (3-stage scaffolded correction).

**E. Cardboard pivots to real student.** Cards 9, 16, 29 break out with the same canned phrase: *"{student_name}, your turn now!"* — stage directions, not natural pivots.

**F. No anchor in student's world.** Topic literally built for Indian context (lakh) but opens with *"Today we learn big numbers."* No cricket stadium, no Diwali sales, no exam ranks. Lakh lands as a definition, not as a "wait — that big a number has its own name?" surprise.

**G. Greeting filler.** Cards 2–5 (~12% of deck) re-introduce Meera *after* the welcome card already did, plus content-thin "you know the four places already" / "yes, biggest 4-digit is 9,999."

**H. No earned emotion.** Card 22: Meera says *"Wow, one lakh has 6 digits!"* Wow not earned — no setup tension.

## 5. Root cause

Three structural issues. **Model is not the bottleneck — prompt and pipeline are.**

1. **Prompt is a coverage spec, not a craft spec.** `baatcheet_dialogue_generation_system.txt` is heavy on negative constraints (word caps, banned chars, schema, counts, spacing) and thin on craft directives. Lists Meera's four roles, doesn't show what natural rhythm looks like. No exemplar. No "leave the question unanswered." No "anchor first." Strong model + coverage spec + don'ts → correct, dull output.

2. **Variant A is fed as the structural spine, not just content.** User-prompt builder (`baatcheet_dialogue_generator_service.py:484`) injects variant A's full card JSON. Model uses variant A's ordering as the dialogue spine and adds Meera around it. Dialogue inherits monologue-shaped pacing.

3. **One generation pass + one validator-driven refine.** Refine receives mechanical validator issues (counts, banned `**`, missing `visual_intent`). Refinement targets defects, not naturalness. No critic asks "where does this feel artificial?"

## 6. Model & config audit

| Item | Status |
|---|---|
| Model | OK — `claude-opus-4-7` |
| Provider | OK — `claude_code` |
| Reasoning effort | **Below max.** Hardcoded `"high"` in service. Adapter supports `"xhigh"` → CLI `--effort max` (`claude_code_adapter.py:127`). One notch below max. |
| Provider/model admin-configurable | OK — `llm_config.baatcheet_dialogue_generator`, `LLMConfigPage.tsx` |
| Reasoning effort admin-configurable | **Missing.** Hardcoded |
| Review rounds admin-configurable | Partial — per quality level only, no UI |
| Prompts admin-configurable | No — `.txt` files on disk |

## 7. Proposed approach — four layers

Independently shippable. Priority order.

### Layer 1 — Crank the existing dial (≤1 hr)
- `reasoning_effort="high"` → `"xhigh"` in `baatcheet_dialogue_generator_service.py:450,474`.
- Bump `thorough` review rounds 2 → 3 in `topic_pipeline_orchestrator.py`.
- Regen one topic. Baseline read on model-effort vs prompt-craft contribution.

### Layer 2 — Rewrite prompt for craft (the big one)

Three changes to `baatcheet_dialogue_generation_system.txt`:

**(a) Positive craft directives** — target observed failures:
- Never put question + answer in same tutor card. Questions live alone.
- Open with a real-world anchor in student's life — never *"Today we learn X."*
- ≥2 earned aha-moments per dialogue: build tension, reveal a card or two later.
- Meera doesn't volunteer rehearsal numbers — speaks because something just happened.
- Banned phrase: *"{student_name}, your turn now!"*. Pivots embedded in flow.
- Examples before rules. State a rule → next card must apply it concretely.

**(b) Few-shot exemplars** — 1 GOOD + 1 BAD pair (different topic, ~10 cards each). Models learn craft from examples, not rules.

**(c) Stop feeding variant A as spine.** Replace the full card-JSON dump with: full guideline text + bulleted "key concepts to cover" (flat, no card structure) + misconceptions + 2–3 real-world anchors per topic. Model choreographs, doesn't transcribe.

### Layer 3 — Naturalness-critic pass

Insert between generation and validator-refine. New LLM call:

> *"You are a classroom teacher reviewing this tutoring dialogue. Read as a struggling 4th-grade Indian student. Find the 5 most artificial turns — Meera saying something a real kid wouldn't, tutor giving a rule before an example, Q + A in same card, unearned wow!, broken pivot. Rewrite those turns and the surrounding cards. Output the full revised deck."*

Run with `reasoning_effort="xhigh"`. Mirrors autoresearch critic+improver pattern. Cost: 1 extra LLM call per topic at Stage 5b, ~30–60s, fits existing parallel branch. Can be gated behind `thorough` quality level for non-priority regens.

### Layer 4 — Admin configurability

Extend `llm_config` schema + `LLMConfigPage.tsx`:
- `reasoning_effort` (low/medium/high/xhigh) per component
- `review_rounds` (0–4) per component

Default `baatcheet_dialogue_generator` → `xhigh` + `2`. Other components unchanged. Optional: surface prompt file path as read-only field for editors.

## 8. Tradeoffs

- **Layer 2(c) loosens variant A coupling.** Mitigation: keep variant A as reference (flagged "concepts only, do not inherit ordering") + add coverage validator (every variant A heading must appear somewhere in dialogue text).
- **Layer 3 doubles per-topic LLM cost** at Stage 5b. Gate behind `thorough` quality level for non-priority regenerations.
- **Few-shot exemplars must be high quality.** Bad exemplars → bad dialogues at scale. Draft together with curriculum review before committing.
- **All existing dialogues become craft-stale** post-Layers 2+3 (content-hash won't trigger — naturalness is a separate axis). Phased regen — Math G4 Ch1 first, evaluate, expand.

## 9. Order of operations

1. **Draft 1 GOOD + 1 BAD few-shot exemplar pair** for one topic — review together. Foundation; everything else rests on it.
2. **Layer 1** — flip effort dial, regen one topic, eyeball.
3. **Layer 4** — expose `reasoning_effort` + `review_rounds` in LLM config page.
4. **Layer 2** — rewrite prompt. Gated on exemplars approved.
5. **Layer 3** — naturalness-critic pass. Last; amplifies Layer 2.
6. **Regen Math G4 Ch1** (6 topics) end-to-end, side-by-side compare with current, iterate.

## 10. Open items

- Exemplar topic — which one? (Suggestion: G3 fractions, broad coverage, lots of misconception material.)
- Real-world anchors — auto-extract from chapter, hand-curated, or LLM-generated upstream?
- Coverage validator — regex-based (variant A heading match) or LLM-based?
- Layer 3 critic gate — always-on, or `thorough` only?
- Exemplars in source repo or external store?
