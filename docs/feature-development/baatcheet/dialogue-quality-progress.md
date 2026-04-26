# Baatcheet Dialogue Quality — Progress Tracker

**Plan:** `dialogue-quality-impl-plan.md`
**Last updated:** 2026-04-26
**Branch:** `docs/baatcheet-dialogue-quality-plan`
**PR:** #122

## Status

| # | Item | Status |
|---|---|---|
| 1 | Plan doc | done |
| 2 | Progress tracker | done |
| 3 | Principles doc — `docs/principles/baatcheet-dialogue-craft.md` | done |
| 4 | CLAUDE.md — index entry for new principles doc | done |
| 5 | Layer 1 — adapter `effort_map` fix (5 distinct levels) | done |
| 6 | Layer 1 — Baatcheet service bump to `reasoning_effort="max"` | done (via config — service no longer hardcodes) |
| 7 | Layer 4 — `reasoning_effort` schema migration on `llm_config` | done |
| 8 | Layer 4 — `LLMConfigService` returns `reasoning_effort` | done |
| 9 | Layer 4 — `LLMService.from_config()` plumbs `reasoning_effort` | done |
| 10 | Layer 4 — LLM Config admin UI dropdown | done |
| 11 | Layer 4 — `review_rounds` surfaced on topic pipeline admin | done (via `QualitySelector` display, dialogue rounds added) |
| 12 | Few-shot exemplars draft (1 GOOD annotated + 1 BAD) | done |
| 13 | Layer 2 — generation prompt craft directives | done |
| 14 | Layer 2 — exemplars wired into prompt file | done |
| 15 | Layer 2 — decouple inputs (key concepts list, no variant A spine) | done |
| 16 | Layer 3 — refine prompt rewrite (defects + coverage + naturalness) | done |
| 17 | Unit tests | done (9 new tests, all green) |
| 18 | Local regen + manual review (Math G4 Ch1 T1) | partial — pipeline ran end-to-end with `review_rounds=1`; final validator caught a stray `=` in `check_in.instruction` so output didn't persist (validator working as designed). Re-run with `review_rounds=2` (balanced default) recommended for clean end-to-end. |
| 19 | PR title/body update to reflect full scope | done |

## Updates

### 2026-04-26 — Interview alignment + plan locked
- 12 alignment Qs answered. Decisions locked in `dialogue-quality-impl-plan.md` §2.
- Plan doc + tracker created.
- Single-PR strategy locked. All four layers + docs ride on PR #122.
- Next: principles doc, then Layer 1.

### 2026-04-26 — Code-review pass: 8 findings addressed
- **#1 ChapterChunk crash (block):** dropped `reasoning_effort` from both `ChapterChunk(...)` calls in `topic_extraction_orchestrator.py:391, 415`. The over-broad regex insertion that caused this is the lesson; tests now guard.
- **#2 `call_vision_sync` conflation + silent downgrade (block):** extracted shared `_resolve_cli_effort(reasoning_effort, fallback)` helper; both `call_sync` (fallback=`max`) and `call_vision_sync` (fallback=`low`) now use the 5-key identity map. No more `xhigh→max` conflation; no more `max→low` downgrade.
- **#3 Streaming path bypass (block):** `LLMService.call_stream` now applies the same `effort = caller_value if not "none" else self.reasoning_effort` fallback as `.call()`. Live tutor streaming (OpenAI) now honors the `tutor` row's `reasoning_effort` setting. Base agent's existing `_reasoning_effort="none"` default routes through the new fallback so no agent-side change required.
- **#4 `_extract_key_concepts` dropped `analogy` (block, cheap):** added `analogy` to teaching types; corrected docstring (variant A's actual vocab is concept|example|visual|analogy|summary|welcome).
- **#5 Exemplar contradicts CRAFT rule (block, cheap):** GOOD exemplar card 3 now uses "my friend" instead of `{student_name}`; removed contradictory inline note. The exemplar now matches the rule it's teaching.
- **#7 Permissive `__init__` default:** LLMService logs a `warning` when constructed with `reasoning_effort="none"` to surface forgotten-callsite plumbing.
- **#8 Test coverage:** added 8 tests covering the bug surface — `_resolve_cli_effort` round-trips, `call_vision_sync` doesn't downgrade `max`, `call_stream` honors construction default + override, `ChapterChunk` constructs with the orchestrator's exact kwargs (success + failure branches), `_extract_key_concepts` includes `analogy`. Total now 17 tests, all green.
- **#6 PR narrative (decided):** updated `dialogue-quality-impl-plan.md` to make explicit that the DB-row default is `max` but eight production services deliberately pin lower values via explicit `.call()` args — those are intentional per-stage choices, not bugs.

### 2026-04-26 — End-to-end regen attempt (Math G4 Ch1 T1)
- Ran `service.generate_for_guideline(force=True, review_rounds=1)` on the production topic.
- Generation pass: 13.5 min, $2.90, 21KB JSON output, claude-opus-4-7 + `--effort max`. New system prompt (with craft directives + exemplars) used as `--append-system-prompt-file`.
- Refine pass: 25.5 min, $3.81, 17KB JSON output, new refine system prompt used.
- Final validator (raise_on_fail=True) FAILED on: `card 9: banned pattern in check_in.instruction (/(?<![a-zA-Z])=(?![a-zA-Z])/)` — the LLM left a stray naked `=` sign inside a check_in.instruction. Output not persisted; old dialogue still in DB.
- Verdict: pipeline is wired correctly end-to-end; validator caught a real defect (working as designed). Single refine round wasn't enough to fully clean the LLM output — a second round (the `thorough` quality default) would have received the validator issue list and corrected it.
- No re-run executed in this session ($6.71 spent so far). Recommended next step for the editor: regen this topic via the admin UI with `thorough` quality, which runs 2 refine rounds. If similar defects keep slipping past round 1, consider bumping `balanced` baatcheet_dialogue rounds from 1 → 2 in `topic_pipeline_orchestrator.py`.

### 2026-04-26 — Layers 2 + 3 landed; tests green
- Generation system prompt rewritten: pedagogy-first framing, CRAFT section with positive directives (no Q+A in same card, examples-before-rules, ≥2 earned aha-moments, Meera arc, banned `{student_name}, your turn now!`, soft real-world examples, no greeting filler), + 1 annotated GOOD exemplar (Halves and Thirds, ~12 cards) + 1 BAD exemplar (~6 cards) showing what to avoid.
- Generation user prompt rewritten: feeds `KEY CONCEPTS TO COVER` (flat bulleted list extracted from variant A teaching cards), keeps variant A reference for content fidelity only.
- Refine system prompt rewritten: three responsibilities in one pass — (1) validator defects, (2) coverage check against KEY CONCEPTS, (3) naturalness rewrite hunting 8 specific failure modes.
- Refine user prompt updated to include KEY CONCEPTS TO COVER.
- `_extract_key_concepts` helper added to BaatcheetDialogueGeneratorService — pulls titles from concept/visual/example cards, dedupes, skips welcome/check_in/summary.
- 9 new unit tests cover adapter effort_map (5 distinct levels, fallback default = max), LLMService init plumbing + override, LLMConfigService reasoning_effort surface, and key-concept extraction.
- Smoke test confirms both prompts build end-to-end against real DB data.
- Next: local regen on Math G4 Ch1 T1, eyeball the new dialogue, update PR title/body.

### 2026-04-26 — Layers 1 + 4 landed; principles doc shipped
- Principles doc + CLAUDE.md index entry committed.
- Adapter `effort_map` now has 5 distinct levels (low/medium/high/xhigh/max); fallback default bumped from `high` to `max`.
- `llm_config.reasoning_effort` column migrated; all existing rows backfilled to `max`.
- LLMConfigService + repository + admin route plumb `reasoning_effort`.
- LLMService accepts `reasoning_effort` at construction time; `.call()` honors it as default.
- All production LLMService instantiations updated to pass `reasoning_effort=config["reasoning_effort"]` (sync_routes, processing_routes, toc_routes, topic_extraction_orchestrator, personality_service, practice_service — 16 callsites total).
- Baatcheet service stops hardcoding `"high"` — admin tunes via config.
- Admin LLM Config page has a Reasoning dropdown column; QualitySelector now shows baatcheet_dialogue rounds.
- Frontend builds clean.
- Next: few-shot exemplars (G3 fractions), then Layer 2 prompt rewrite, then Layer 3 refine prompt.
