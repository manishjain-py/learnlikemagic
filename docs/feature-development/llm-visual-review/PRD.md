# PRD + Tech Plan: LLM Visual Review Gate

Replace stage-7's geometric overlap detector with an LLM-vision review of the rendered screenshot. Bump Claude Code provider from Opus 4.6 → 4.7 while we're here.

---

## Problem

Stage 7's post-refine overlap gate is a pure-geometry check (`visual_overlap_detector.py`) over Pixi `getBounds()` bounding boxes. It computes "IoU" using `min(area_a, area_b)` as the denominator — which is a **containment ratio**, not IoU — and flags any Text-on-dense-Graphics pair above 0.05.

The dominant layout pattern the code-gen LLM produces is **text inside a filled container shape** — a digit inside a circle, a letter inside a rounded rect, a `?` inside a dashed box. Every one of these trips containment = 1.0 and gets flagged.

Two real cards bitten today (screenshots on hand):
- "The ×10 Pattern Chain" — digits `1, 10, 100, 1,000, ?` inside colored circles → all flagged.
- "Four Places You Know" — `9` inside each place-value box, `?` inside the red dashed box → all flagged.

Both render cleanly. The validator is the defect.

Compounding issues: dense-Graphics heuristic treats any Graphics with ≥1 `fill` instruction as occluding (so a container background looks identical to an opaque blob); the refine loop cannot win (the spec *requires* the digit inside the circle); 0.05 threshold is extreme even as "IoU"; no Container-group or z-order awareness.

The underlying issue: **overlap is a perceptual concept, not a geometric one.** Text inside its container is intentional framing; two sibling labels colliding is a real defect. Bounding-box math cannot tell these apart.

---

## Solution

Delete the geometric detector. At the same point in the pipeline, screenshot the rendered Pixi canvas and ask a multimodal LLM (Claude Code Opus 4.7): "Does this image have a legibility or overlap issue that would confuse a Grade-3 student? If yes, describe it."

If flagged → one targeted refine round with the review note replacing the collision report → re-render → re-review. Same budget, same single-refine-round policy, same store-code-anyway semantics. If the review still flags after refine, the code is stored (no flag persisted, no student-facing chip — see below).

The rendered-screenshot path already exists in `visual_render_harness.py:135-143` (unused); the Claude Code adapter already has `call_vision_sync` (claude_code_adapter.py:233) that uses the CLI's `Read` tool for multimodal content. The plumbing is there.

### Also: model bump

Same PR bumps the Claude Code provider from `claude-opus-4-6` → `claude-opus-4-7` in the two live code paths:
- `shared/services/claude_code_adapter.py` (hardcoded CLI `--model` in both `call_sync` and `call_vision_sync`)
- `db.py` seed/ensure calls for `check_in_enrichment` and `practice_bank_generator`

Out of scope: `anthropic_adapter.py` (different provider), `llm_config_routes.py` (admin UI dropdown for `anthropic` provider), historical autoresearch run artifacts, test fixtures asserting the old default.

### Also: drop the student-facing warning chip

Per user ask. `VisualExplanation.tsx:138-151` is removed. Students no longer see "Note: this picture might have some overlap — we're improving it." Admin-side observability (`layout_warning_count` badge in `VisualsAdmin.tsx`) stays so we can monitor pipeline health, but its meaning now = "LLM visual review flagged a persistent issue after refine."

---

## Goals

- Eliminate false positives on the "text inside a container shape" pattern (the thing biting us today)
- Replace bounding-box math with perceptual judgment — the right tool for the defect class
- Reuse the existing render harness, refine prompt structure, single-round refine budget
- Bump the default Claude Code model to Opus 4.7 for the same cost as touching this code
- Net code reduction: delete the overlap detector, its tests, the student-facing chip

## Non-Goals

- **No new provider.** Vision call stays on Claude Code, same subprocess pattern, same auth.
- **No fallback to geometric detection.** If the vision call fails, we skip the gate (same behavior as a harness failure today — no false flag).
- **No second refine round.** Keep the one-refine-round budget; two rounds didn't help on the old gate either.
- **No admin UI for tuning review strictness.** If the review is too loose or too strict, iterate on the prompt.
- **No retroactive re-review of already-ingested visuals.** New topics and any admin-triggered re-enrichment get the new gate.

---

## File-level changes

### Delete

- `llm-backend/book_ingestion_v2/services/visual_overlap_detector.py`
- `llm-backend/tests/unit/test_visual_overlap_detector.py`

### New

- `llm-backend/book_ingestion_v2/prompts/visual_review.txt` — vision prompt. Asks the model to look at the rendered screenshot and reply either `OK` or a short list of specific issues. Grade-level aware (passed via `{grade_level}`). Kept tight; the refine prompt does the heavy lifting on the fix.
- `docs/feature-development/llm-visual-review/PRD.md` — this file.

### Modify

- `llm-backend/book_ingestion_v2/services/animation_enrichment_service.py`
  - Rename `_overlap_gate` → `_visual_review_gate`. Replace the `detect_overlaps` call with a new `_visual_review(screenshot_path, decision, card, guideline) -> tuple[bool, str]` method that invokes `claude_code_adapter.call_vision_sync`. Parse response: `OK` (case-insensitive, leading) → no issue; anything else → flagged with the response text as the review note.
  - Call `harness.render(..., screenshot_path=<tmp>)` explicitly. Screenshot path is a `tempfile.NamedTemporaryFile(suffix=".png")`; cleaned up after the gate returns.
  - Feed the review note through the existing `{collision_report}` slot of the refine prompt (renamed to `{review_note}` for clarity — see prompt change below).
  - Update the preflight docstring (still checks `localhost:3000`, wording changes from "overlap gate" to "visual review gate").
- `llm-backend/book_ingestion_v2/prompts/visual_code_review_refine.txt`
  - Replace `{collision_report}` → `{review_note}`. Rewrite the preamble for item 4b from "Specific overlaps detected by the renderer..." to "Visual issues flagged by the reviewer: the rendered output was reviewed by a vision model and these issues were found. Fix each one directly."
- `llm-backend/book_ingestion_v2/services/visual_render_harness.py`
  - Docstring wording: "overlap gate" → "visual review gate". No behavior change.
- `llm-backend/shared/services/claude_code_adapter.py`
  - `call_sync` line 108: `claude-opus-4-6` → `claude-opus-4-7`.
  - `call_vision_sync` line 286: same bump.
- `llm-backend/db.py`
  - Lines 77, 83, 757, 820: `claude-opus-4-6` → `claude-opus-4-7` in seed/ensure rows for `check_in_enrichment` and `practice_bank_generator`.
- `llm-frontend/src/components/VisualExplanation.tsx`
  - Delete lines 138-151 (the `{visual.layout_warning && ...}` chip block). Leave the `layout_warning?: boolean` field on the API type — backend still emits it for admin observability; the student just doesn't see it.
- `llm-frontend/src/features/admin/pages/VisualsAdmin.tsx`
  - Badge title and label reworded from "overlap" to "visual issue" so admin signal matches the new semantics.

### Tests

- Delete `test_visual_overlap_detector.py`.
- `test_topic_pipeline_status.py::test_layout_warning_flips_visuals_to_warning` — stays as-is; the field name and shape are unchanged.
- Add unit coverage in `tests/unit/test_animation_enrichment_visual_review.py`:
  - `OK` response → gate passes, `layout_warning=False`, no refine call.
  - Non-`OK` response → refine invoked, re-review called on refined code.
  - Refined code still flagged → `layout_warning=True`, refined code stored.
  - Harness render failure → gate skipped, `layout_warning=False` (parity with current behavior).
  - Vision call raises → gate skipped, `layout_warning=False`, error logged.

Mock the vision adapter and the harness — no real browser, no real CLI. Tests should run in the standard unit suite.

---

## Rollout / ops

- Preflight stays. Frontend dev server still required because the harness renders via the admin preview page.
- No new env vars, no new deps. Playwright and Claude Code CLI are already dependencies.
- Cost delta per card: +1 vision call (~$0.01-0.03 depending on refine round firing). Stage 7 runs offline and is admin-triggered, not per-student.
- Latency delta per card: ~3-8s for the vision call, plus ~3-8s for the re-review if refine fires. Acceptable at ingestion time.
- Idempotency: same as today. Re-running stage 7 on an already-enriched guideline with `force=True` re-runs the gate.

## Success criteria

- Both reference cards ("×10 Pattern Chain", "Four Places You Know") pass the gate with no flag.
- A deliberately-broken card (two text labels deliberately overlapping each other by 80%) is still flagged.
- No regression in pipeline wall-clock for ingestion end-to-end (dominated by other stages).
- Admin dashboard `layout_warning_count` continues to tick for cards where the vision review + refine cannot resolve — expected rate noticeably lower than today.
