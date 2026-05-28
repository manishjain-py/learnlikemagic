# Implementation Handover — Baatcheet Dialogue Generation Principles Alignment

**For:** the next session that will implement the approved changes.
**Date:** 2026-05-28
**Status:** Punch-list approved & committed. **No prompt/code changes made yet.** Your job is to implement the 7 changes.

---

## Mission

Implement the 7 approved changes from the alignment audit. The full spec (frozen principle text, file/line targets, before→after, rationale) is in the companion report — read it first:

- **Punch-list (read this first):** `docs/feature-development/alignment-baatcheet-dialogue-generation/2026-05-28.md`
- **Audit PR (context):** https://github.com/manishjain-py/learnlikemagic/pull/143
- This handover adds: git state, run/test commands, recommended order, and the non-obvious constraints that came out of the live interview with Manish.

## Git state

- Audit report + this handover are committed on branch `docs/alignment-baatcheet-dialogue-generation` (PR #143, docs-only).
- **Start the implementation on a fresh branch off `main`** (e.g. `fix/baatcheet-dialogue-generation-principles-align`) and open a **separate PR**. Keep the docs/punch-list PR and the code-change PR distinct.
- Base branch for PRs: `main`.

## Files you will touch

Prompts (all in `llm-backend/book_ingestion_v2/prompts/`):
- `baatcheet_lesson_plan_generation_system.txt` — Changes 1, 3, 4, 5, 6
- `baatcheet_dialogue_generation_system.txt` — Changes 1, 5, 6, 7
- `baatcheet_dialogue_review_refine_system.txt` — Changes 2, 6 (and remove the old check-in line, Change 1)
- `baatcheet_dialogue_review_refine.txt` — Change 2 (Variant A is already passed here)
- `baatcheet_visual_intent.txt` — Change 5

Code:
- `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py` — `_validate_cards` (check-in pairing/spacing → Change 1), the Pydantic output schema (`DialogueGenerationOutput` / card / check-in models → spine optional Change 3, misconception `minItems` Change 4). Grep for `_validate_cards`, `class .*Output`, `minItems`, `spine`, `check_in`.

Reference (do NOT change — use as the model for Change 2's fact-check facet):
- `llm-backend/book_ingestion_v2/prompts/explanation_review_refine.txt` line ~18 — the sibling Explain fact-check facet to mirror.

## The 7 changes (summary — full detail in the report)

1. **HIGH — Check-in model.** Replace "2-3 total, ≥10 apart" (plan `…lesson_plan_generation_system.txt:66`) + remove "≥4 apart / no back-to-back" (review `…review_refine_system.txt:17`) with: **paired light(recall)+heavy(analysis) check-ins after every 2–3 content cards; ≥2 content cards between pairs; never before card 3; never after summary.** Add light/heavy distinction + activity_type→tier mapping to the generation prompt. **Rebuild the baked-in exemplar plan to model the pairs.** Put structural enforcement in `_validate_cards` (NOT the refine prompt).
2. **HIGH — Refine = naturalness + factual error only.** In `…review_refine_system.txt`: keep RESP 3 (naturalness, A–H); **add a factual-error facet** (mirror `explanation_review_refine.txt:18`, check vs Variant A); **drop RESP 2 (plan adherence) entirely**; reduce RESP 1 to "fix the validator issues handed to you."
3. **HIGH — Conditional spine.** `…lesson_plan_generation_system.txt:21–33` + schema + callbacks L95–96: spine is used **only when the topic invites it**; procedural/abstract topics use multiple small examples. Make `spine` optional in the schema; gate the ≥3-callback + close-resolves-spine rules on spine presence.
4. **MED — Conditional misconceptions.** Relax schema `minItems:2`→ allow 0–1; add "if no documented misconception, teach directly."
5. **MED — ESL/language consistency (PROMPT GUIDANCE ONLY).** Add ESL emphasis to the planner (student-visible fields), `visual_intent.txt` (ESL + Indian numbering/₹), and generation (daily-vocab as *examples not a banned list*, one-`if`-per-sentence, extend ≤12-word/SVO/no-idiom to `check_in.*` strings, Indian-context substitution emphasis). Fix the "figured out" idiom self-contradiction.
6. **MED — Craft naturalness.** Add §8 "Meera speaks from reaction, not service" to the **generation** prompt + a planner caution against scripting Meera to supply answers/pivots; fold no-leaps + rhythm into the refine **naturalness** dimension; add a light check-in right after a student-act so the *real* student reports their observation.
7. **LOW — Exemplar banned-phrase.** In `…dialogue_generation_system.txt` (~L147), the exemplar tutor says "Aha! Lots of kids think exactly that." — rewrite to validate confusion without the §5-banned "lots of kids think" framing.

## CRITICAL constraints (from the live interview — easy to get wrong)

1. **Change 2 is a deliberate scope CUT.** Manish explicitly wants the refine pass to judge **only naturalness + factual error**. Do **not** "helpfully" keep plan-adherence (RESP 2) in the refine prompt. Plan adherence (cycle completeness, fall-stays-in-Meera's-mouth, funnel-does-the-work, spine threading) is now **solely owned by the generation prompt** — make sure the generation system prompt carries those firmly (it mostly does today; verify, don't weaken).
2. **Change 5 is PROMPT GUIDANCE ONLY.** Manish was explicit: "don't add any hardcoded validations or any strict validation that only these words have to be used … simply highlight this important ESL point in the prompt." **No new code validators, no word-allowlists, no banned-word lists** for language/ESL. (Saved as a durable preference in memory: `feedback_soft_prompt_guidance.md`.) Mechanical validators are fine only for *structural* invariants (check-in pairing/spacing, JSON shape, no-markdown-in-audio).
3. **Change 1 card-budget reconciliation.** "A pair every 2–3 **content** cards" means check-ins are counted **separate from** the "Total cards = 30-40" budget — a lesson grows by ~16–24 check-in cards. Reconcile the budget language so check-ins don't crowd out trap-resolve cycles (recommend: 30–40 = content cards; check-ins additional). Confirm with Manish if unsure.
4. **Two parallel schemas must stay in sync.** The generation-time Pydantic schema in `baatcheet_dialogue_generator_service.py` (no `card_id`/`audio_url`/`visual_explanation`) vs the storage/read schema in `shared/repositories/dialogue_repository.py` + frontend `llm-frontend/src/api.ts`. Changes 3/4 touch the generation schema; check whether the storage/read side needs a matching tweak (spine optional likely lives in `plan_json`, so probably generation-side only — verify).
5. **Do NOT edit anything under `docs/principles/`.** Principles are founder-owned and frozen. Zero items were referred to `/principles-review` — all fixes are code/prompt. If implementation reveals a principle should change, surface it to Manish; don't edit.

## How to run & test

Environment (from project memory):
- Backend venv: `source llm-backend/venv/bin/activate` (it's `venv`, NOT `.venv`). Bare `python3` lacks deps.
- LLM provider: when admin is set to `claude_code`, the pipeline shells out to the `claude` CLI. See CLAUDE.md "Claude Code as LLM Provider" — don't silently switch providers.

Generate sample output to eyeball (these run Stage 5b/5c directly against the configured DB/provider):
- Stage 5b (dialogue): `llm-backend/scripts/baatcheet_v2_run_stage5b.py` — dumps plan + cards to disk.
- Stage 5c (visuals): `llm-backend/scripts/baatcheet_v2_run_stage5c.py`
- Mechanical metrics: `llm-backend/scripts/baatcheet_v2_eval.py` (word counts, talk-ratio, move distribution — deterministic, no LLM judge).
- Render to inspect: `llm-backend/scripts/baatcheet_v2_render_html.py`
- Standalone two-step harness (no project imports, calls `claude` CLI): `llm-backend/scripts/baatcheet_v2_experiment.py` — fastest loop for prompt iteration.

Unit tests (these PIN current behavior — several will need updating for Changes 1–4):
- `llm-backend/tests/unit/test_baatcheet.py` — pins `_validate_cards` (check-in spacing, banned audio patterns, student_name, activity_type). **Change 1 will require updating the check-in spacing assertions.**
- `llm-backend/tests/unit/test_baatcheet_visual_enrichment.py` — Stage 5c.
- `llm-backend/tests/unit/test_dialogue_quality.py` — reasoning-effort plumbing + `_extract_key_concepts`.
- Run: `cd llm-backend && source venv/bin/activate && pytest tests/unit/test_baatcheet.py -q` (etc.)

Acceptance check (from the report's checklist):
- Regenerate a Stage 5b dialogue for **a spine-friendly topic** (e.g. a fractions/money topic) AND **a procedural/abstract topic** (e.g. long division or a grammar/tense topic).
- Eyeball: check-in pairing & frequency (Change 1), factual correctness of worked examples (Change 2), spine present only on the spine-friendly topic (Change 3), no forced misconceptions on a topic without them (Change 4).
- Verify L13 (shake animation) is a frontend render behavior — grep `llm-frontend/src` for the check-in wrong/correct handling; if frontend-owned, leave it (it's not a prompt concern).

## Recommended implementation order

1. **Change 3 + 4** (schema relaxations: spine optional, misconception `minItems`) — smallest, unblock the plan prompt edits.
2. **Change 1** (check-in model) — biggest; touches plan prompt + generation prompt + `_validate_cards` + exemplar + budget. Update `test_baatcheet.py` accordingly.
3. **Change 2** (refine restructure) — rewrite `…review_refine_system.txt` to two dimensions; remove the old check-in line here as part of the slimming.
4. **Change 6** (craft naturalness) — generation §8 + planner caution + refine naturalness folds + post-student-act check-in.
5. **Change 5** (ESL guidance) — planner + visual_intent + generation, prompt-only.
6. **Change 7** (exemplar banned-phrase) — one-line fix; do it while you're in the generation prompt for Change 1/5.
7. Regenerate samples, run/adjust unit tests, open the PR.

Commit message suggestion: `fix(baatcheet-dialogue-generation): align generation prompts with principles`

## Key references

- Punch-list report: `docs/feature-development/alignment-baatcheet-dialogue-generation/2026-05-28.md`
- Audit PR: https://github.com/manishjain-py/learnlikemagic/pull/143
- Principles audited: `docs/principles/{baatcheet-dialogue-craft,check-in-cards,how-to-explain,easy-english,target-audience,content-extraction-from-books,book-ingestion-pipeline,breaking-down-chapters-into-topics}.md` (frozen — do not edit)
- Design background: `docs/feature-development/baatcheet/` (PRD, dialogue-quality-v2-designed-lesson.md, gold-example-fractions-class4.md = source of the exemplar in the plan prompt)
- Memory preference: `feedback_soft_prompt_guidance.md` (soft prompt guidance over validators for language rules)
