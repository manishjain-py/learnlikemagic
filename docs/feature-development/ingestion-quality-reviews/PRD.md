# PRD: Ingestion Quality Review Stages

Two new review stages in the book ingestion pipeline that catch defect classes slipping through today's review-refine loops.

---

## Problem

The ingestion pipeline's existing review-refine stages optimize teaching quality holistically, but two specific defect classes slip through consistently:

### Defect Class A — Audio text defects

Audio strings are written by the LLM alongside display text in a single pass in `ExplanationGeneratorService`. Stage 5's review-refine inspects whole cards for teaching quality and touches audio text only as a side effect; it never contrasts `display` vs `audio` line-by-line or checks the audio flow for speakability. Check-in `audio_text` is produced the same way in stage 8 and reviewed only by the check-in review-refine (which focuses on factual accuracy — see `docs/feature-development/check-in-review-refine/PRD.md`).

Observed defects reaching students:

| Defect | Example |
|---|---|
| Symbols/markdown leak | `audio`: "5+3=8" (should be "five plus three equals eight") |
| Visual-only reference | `audio`: "As you can see in the diagram..." (violates the "skip visual-only content" rule) |
| Pacing | 40-word run-on audio line that takes 25s to speak — learner loses thread |
| Cross-line redundancy | Line 2's audio re-states what line 1 already said because each line was written in isolation |
| Hinglish quirks | English math terms code-switched without phrasing that the Chirp3 `hi-IN` voice can handle cleanly |

### Defect Class B — Visual layout overlap

`visual_code_review_refine.txt` (stage 7's review loop) reads Pixi.js source code and has `"no overlapping text"` in its rubric — but **LLMs cannot compute text bounding boxes from source code**. Predicting overlap requires font metrics, text widths, and actual layout math that only a real browser can do. So the rubric item is aspirational today.

Observed defect: in a place-value visual for `5,23,476`, three labeled brackets render as `"Lakhs PeTioodsands Period"` because adjacent labels exceed their group widths and collide. The student sees unreadable garbled text.

### Why this matters

Both defects reach students. Audio defects degrade the "real teacher talking" experience that pre-computed audio was built to deliver (see `docs/feature-development/pre-computed-audio/PRD.md`). Visual defects ship unreadable content. Both are trust-breaking.

---

## Solution

Two stages, shipped in order. Each is a narrow, scoped pass targeted at exactly one defect class.

### Stage 1 — Audio Text Review (ship first)

A dedicated LLM pass that runs after stage 5 (explanations) AND stage 8 (check-ins), BEFORE stage 6 (MP3 synthesis). Per card, it reviews the audio strings in context of their display text and emits a **surgical list of revisions** — only the lines it wants to change, each with a reason. Untouched lines pass through unchanged.

**Pipeline change:** Remove the inline MP3 synthesis call from stage 5 (`explanation_generator_service.py:193`). MP3 synthesis (stage 6) becomes a fully explicit, always-separate job that runs after audio review. Admin workflow moves from three clicks (generate → check-ins → MP3) to four (generate → check-ins → audio review → MP3).

**Scope is deliberately narrow: audio text rewrites only.** The reviewer cannot touch display text, cannot split/merge/drop lines, cannot reshape cards. It rewrites individual audio strings in place.

### Stage 2 — Visual Rendering Review (ship second)

A sub-stage inside the existing stage 7 (visual enrichment), running after the last review-refine round. The generated Pixi.js code is rendered in headless Chrome (Playwright pointed at the local frontend dev server), `getBounds()` is called on every display object, and pairwise overlaps are computed. If overlap is detected, one extra targeted refine round runs with the collision report appended to the prompt. If overlap persists, the code is stored anyway with a `layout_warning` flag, and the student-facing UI renders a subdued chip.

**No vision LLM in v1.** The programmatic check deterministically catches text-on-text and text-on-dense-graphics overlap, which is where the observed defect lives. Vision LLM (non-overlap defects like off-screen content, unreadable fonts, conceptual mismatch) is deferred to a future phase.

---

## Goals

- Catch audio text defects (symbol leak, visual-only reference, run-on pacing, cross-line redundancy) before stage 6 synthesizes MP3s on bad input
- Catch visual layout overlap deterministically via browser-side bbox checks — not rubric items the LLM cannot enforce from source
- Reuse existing patterns everywhere: `stage_snapshots_json` for observability, manual trigger via admin dashboard, per-stage job types, `LLMService` + Claude Code subprocess
- Zero regression in current content quality (preventive prompt changes stay light-touch)
- Render harness uses the same code path the student sees (highest fidelity)

---

## Non-Goals

- **No STT loopback verification of MP3s.** Reviewer does not listen to the synthesized audio. Catches text-level defects only. Future phase, opt-in.
- **No vision LLM review of rendered visuals.** Programmatic bbox check only. Future phase.
- **No auto-chaining of stages.** Every stage stays manually triggered by admin. Matches current pattern.
- **No automatic backfill of existing books.** Admin triggers per topic/chapter/book on demand, same as today.
- **No cross-card flow review for audio.** Per-card granularity only. A reviewer that sees all cards in one prompt is a future phase.
- **No audio line reshaping** (split/merge/drop). Rewrites only.
- **No display text edits.** Stage 5's review-refine owns display quality.
- **No new admin pages.** All new controls live on existing dashboards via badges and soft guardrails.

---

## User Experience

### Admin

**Before:** Admin clicks Explanations → Check-ins → Visuals → MP3 synth. MP3 synth also auto-fires at the end of stage 5 as a side effect.

**After:**

- Stage 5 no longer auto-synths MP3s. MP3 synth is always a distinct step.
- New button on the book detail page and per-chapter controls: **"Review audio text"**. Runs as a background job per guideline / chapter / book scope. Progress tracked via the same job heartbeat pattern.
- When admin clicks **"Generate audio"** (stage 6), the endpoint checks whether a completed `v2_audio_text_review` job exists for that scope. If not, a soft guardrail asks *"Proceed without audio text review?"* with a confirm dialog. Admin can skip if they know what they're doing.
- For visuals: the post-refine rendering check runs inline during stage 7. No new button. `/visual-status` endpoint gains a warning count per topic; the dashboard shows a small badge next to topics with warnings.

### Student

- Audio text review is invisible to students — they hear the reviewed MP3s, nothing else changes.
- Visual rendering review is invisible when it passes. When a card's visual is retry-exhausted (overlap persists after one extra refine round), the student sees a **small, subdued chip** on that visual card: *"Note: this picture might have some overlap — we're improving it."* Chip copy is warm and honest, matching `docs/principles/ux-design.md`.

---

## Observability

### Audio Text Review

- Every revisions list is captured in the `stage_snapshots_json` column on the `chapter_processing_jobs` row. Admin opens the stage viewer (same one used for explanation review-refine rounds) and sees per-card diffs: `original_audio → revised_audio`, plus the reviewer's reason string.
- New endpoint: `GET /admin/v2/books/{book_id}/audio-review-jobs/latest?chapter_id=&guideline_id=` mirrors `/explanation-jobs/latest`.

### Visual Rendering Review

- `/visual-status` response extended with `layout_warning_count` per topic.
- Admin dashboard (`TopicsAdmin.tsx` / `BookV2Detail.tsx`) renders a small badge on topics with warnings.
- Per-card warnings visible when admin drills into the topic detail.

---

## Scope Details

### Audio Text Review

| Aspect | Decision |
|---|---|
| **Timing** | After stage 5 + stage 8, before stage 6 |
| **Cards covered** | Explanation cards (`lines[].audio`), check-in cards (`audio_text`), refresher topic cards |
| **Variants covered** | All variants present in DB (A/B/C) |
| **Granularity** | Per card — one LLM call per card, parallelizable |
| **Output shape** | Surgical revisions list with per-change reason; untouched lines pass through |
| **Reviewer changes** | Audio text strings only. No display edits. No line reshape (split/merge/drop) |
| **Trigger** | Manual only (admin dashboard button) |
| **Rounds** | Single pass per card (no N-round refine-the-review) |
| **LLM config key** | `audio_text_review`, falls back to `explanation_generator` |
| **Job type** | `V2JobType.AUDIO_TEXT_REVIEW = "v2_audio_text_review"` |
| **Endpoint** | `POST /admin/v2/books/{book_id}/generate-audio-review?chapter_id=&guideline_id=` |
| **Stage 6 guardrail** | Soft — MP3 synth endpoint returns a warning flag if no completed review job; admin confirms via a dialog in the UI |
| **Execution env** | Localhost backend + Claude Code subprocess |

### Visual Rendering Review

| Aspect | Decision |
|---|---|
| **Approach tier** | Preventive prompt nudge + programmatic rendering check |
| **Preventive prompt** | One general rule added to `visual_code_generation.txt` about avoiding crowded adjacent elements. No templates. No prescriptive patterns |
| **Integration point** | Post-refine gate within stage 7 — runs after the last existing review-refine round |
| **Rendering infra** | Playwright + new admin preview route `/admin/visual-render-preview?code=<base64>` on the frontend; renders via the same `VisualExplanation.tsx` component students see |
| **Animated visuals** | End state only — one screenshot during the 2+s end-state pause |
| **Overlap check scope** | Text-on-text AND text-on-"dense" graphics (non-transparent fills) |
| **IoU threshold** | `> 0.05` (5% of the smaller box area) |
| **On overlap detected** | One extra targeted refine round with collision report appended to prompt |
| **Retry exhaustion** | Store overlapping code anyway, log warning, set `visual_explanation.layout_warning = true` on the card |
| **Student UX** | Subdued chip: *"Note: this picture might have some overlap — we're improving it"* |
| **Admin observability** | Extend `/visual-status` with per-topic warning counts; badge on dashboard |
| **Trigger** | Inline within stage 7 (no separate admin button) |
| **Execution env** | Localhost backend + local dev frontend (`http://localhost:3000`) + local Playwright |

---

## Success Criteria

### Audio Text Review

1. Runs as a manual background job scoped by guideline, chapter, or book.
2. On a test set of 20 cards with known audio text defects, catches and rewrites ≥ 80% of symbol-leak and visual-only-reference defects.
3. On a gold set of 20 known-clean cards, reviewer returns an empty revisions list (zero false rewrites) on ≥ 90% of cards.
4. Admin can view per-card revisions via the existing stage viewer UI.
5. Soft guardrail on stage 6 fires when admin tries to synth MP3 without a prior review job for the scope.
6. `review_rounds=0`-equivalent (skip the reviewer entirely) remains available via admin action — admin can bypass review and go straight to MP3 synth if needed.

### Visual Rendering Review

1. Detects text-on-text and text-on-dense-graphics overlap via `getBounds()` with IoU > 0.05.
2. Catches the observed defect (`5,23,476` place-value labels) when the code is regenerated with the new pipeline.
3. Render harness completes in ≤ 10 seconds per card on the admin's localhost.
4. Retry-exhausted cards get `layout_warning = true`; `VisualExplanation.tsx` renders the student-facing chip.
5. `/visual-status` returns per-topic warning counts; dashboard renders a badge.
6. Preventive prompt change does not visibly degrade generation quality on a smoke test of 10 existing topics (spot-check against current outputs).

---

## Edge Cases & Error Handling

| Scenario | Expected behavior |
|---|---|
| Audio review LLM call fails for a single card | Retry with exponential backoff (3 attempts); on exhaustion, log error and skip the card; job continues with other cards; final status `completed_with_errors` |
| Audio review returns invalid JSON | Same as above — retry then skip |
| Audio review returns revisions that violate the "no symbols" rule (new text still has `5+3`) | Validator drops those revisions; other valid revisions apply; error logged |
| Admin re-runs audio review on already-reviewed cards | Reviewer runs again on the latest audio strings; if no defects remain, returns empty revisions list per card (no-op) |
| Admin triggers stage 6 without review | Soft guardrail asks for confirmation; admin can proceed |
| Revised audio text changes for a line that already has `audio_url` set (MP3 exists) | Clear `audio_url` on that line so next stage 6 run regenerates only the changed MP3s (idempotent) |
| Render harness fails to reach `localhost:3000` | Post-refine gate logs error and stores the current code without the warning flag (don't false-flag cards when the check itself failed) |
| Playwright timeout / render hang | 30-second timeout per card; skip with error logged; job continues |
| Code throws an exception at render time | Treat as render failure; skip overlap check for that card; continue |
| `getBounds()` returns infinite or NaN coords | Skip the overlap check for that object; don't false-flag |
| Extra refine round introduces a new, different overlap | Store the (still-overlapping) code with `layout_warning = true`; we don't spiral into more refine rounds |
| Existing cards have no `layout_warning` field | Defaults to `false` / absent; frontend chip only renders when explicitly `true` |
| Admin regenerates a variant; new code passes the check | Any stale `layout_warning` flag is cleared because the card's `visual_explanation` is overwritten |

---

## Impact on Existing Features

| Feature | Impact | Details |
|---|---|---|
| Stage 5 Explanation Generation | Minor | Remove the inline `AudioGenerationService` call at `explanation_generator_service.py:193`. Cards are saved without MP3s; admin runs MP3 synth separately |
| Stage 6 Audio Generation (MP3 synth) | Minor | Endpoint unchanged, but adds a soft guardrail that warns when no audio review has run for the scope |
| Stage 7 Visual Enrichment | Internal change | Post-refine gate added. No API changes. `visual_explanation` object gains an optional `layout_warning: bool` field |
| Stage 8 Check-in Enrichment | None — but audio text review operates on the check-ins it produces |
| Stage 9 Practice Bank | None (no audio or visual review for practice banks in v1) |
| Tutor runtime (student-facing) | Minor | `VisualExplanation.tsx` renders a small warning chip when `layout_warning === true` on the visual |
| `/visual-status` endpoint | Extended | Response gains per-topic `layout_warning_count` |
| Admin dashboards (`BookV2Detail`, `TopicsAdmin`) | Minor | New "Review audio text" trigger button; new warning badges on topics with layout warnings |
| Principles doc | Stage numbering | Audio Text Review slots before MP3 synth; MP3 synth docs move to reflect no-longer-inline behavior |

---

## Rollout

- **Phase 1 (this PR):** Audio Text Review end-to-end — service, prompt, job type, endpoint, admin trigger, stage viewer integration. Tech impl plan (companion doc) describes the exact sequencing.
- **Phase 2 (follow-up PR):** Visual Rendering Review — preventive prompt update, render harness (admin preview route + Playwright), bbox extraction, post-refine gate integration, warning chip on student UI, `/visual-status` extension.
- **No migration / backfill.** Admin re-runs the pipeline per book at their own pace.
- **Rollback plan for Phase 1:** revert the stage-5 inline-MP3 removal; audio review job type remains harmless (admin just doesn't use it). Revert is one PR.
- **Rollback plan for Phase 2:** set the post-refine gate to always skip; revert the preventive prompt line; revert the student-facing chip. Three small reverts.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Audio reviewer rewrites things it shouldn't (display text, tone) | Scope locked to audio strings only via Pydantic output schema; display text fields not even passed to the prompt for modification |
| Audio reviewer over-rewrites (touches clean lines unnecessarily) | Surgical revisions format: prompt instructs "return empty list if no defects"; gold-set success criterion enforces this |
| Reviewer produces invalid JSON / shape drift | Pydantic validation drops bad output; retry with backoff; on exhaustion skip the card |
| Playwright render flakiness (localhost not running, browser hang) | 30s timeout per card; failure logged but does NOT set warning flag (don't false-flag clean cards when the check itself failed) |
| Preventive prompt change degrades visual quality | Single general rule only; success criterion #6 spot-checks 10 existing topics; easy to revert |
| Bbox false positives on intentional text-inside-box layouts | IoU threshold tunable (default 0.05); documented as expected; LLM can address via the extra refine round by repositioning |
| Admin forgets audio review, synths MP3s on unreviewed text | Soft guardrail asks for confirmation; pattern matches existing UX |
| Stage 6 breakage from removed inline call | End-to-end test with a known book; rollback is a single-line revert |

---

## References

- Existing review-refine pattern: `llm-backend/book_ingestion_v2/services/explanation_generator_service.py` (`_review_and_refine`, similar flow)
- Existing check-in review-refine: `docs/feature-development/check-in-review-refine/PRD.md`
- Existing audio pipeline: `docs/feature-development/pre-computed-audio/PRD.md`
- Pipeline principles: `docs/principles/book-ingestion-pipeline.md`
- Visual enrichment technical reference: `docs/technical/book-guidelines.md` (§ Visual Enrichment, § Audio Generation)
- Observed visual defect screenshot: place-value periods example (`5,23,476` → `Lakhs PeTioodsands Period`)

---

## Open Questions

- Target volume for the gold/test set of 20 cards each (R1 success criteria). Are we building this test set from scratch or harvesting from existing ingested content? — **Defer to tech impl plan.**
- Should the audio reviewer explicitly receive the topic's `language` field (`en` / `hi` / `hinglish`) so it can apply language-specific rules (Indian place-value reading conventions, Hinglish phrasing)? — **Default: yes, pass the language to the prompt. Document in tech impl plan.**
- Long term: should audio text review and visual rendering review eventually gate downstream stages (hard guardrails instead of soft)? — **Out of scope for v1. Revisit after usage data.**
