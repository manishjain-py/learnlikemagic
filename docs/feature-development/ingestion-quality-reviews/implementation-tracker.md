# Implementation Tracker — Ingestion Quality Reviews

Live tracker for PR #105 implementation work. Updated after each commit lands.

**PRD:** `PRD.md`
**Plan:** `impl-plan.md`
**Review:** `impl-plan-review.md`

**Legend:** ⬜ not started · 🔄 in progress · ✅ done · ⏭️ skipped · ❌ blocked

---

## Phase 1 — Audio Text Review ✅ complete

| # | Commit | Status | Notes |
|---|---|---|---|
| 1.1 | `feat: add V2JobType.AUDIO_TEXT_REVIEW constant` | ✅ | Smallest change, unblocks everything |
| 1.2 | `feat: add audio text review prompt files` | ✅ | `audio_text_review.txt`, `_system.txt` |
| 1.3 | `feat: add AudioTextReviewService` | ✅ | Per-card LLM call, surgical revisions, drift guard |
| 1.4 | `feat: wire /generate-audio-review endpoint + background task` | ✅ | Mirrors `/generate-audio` |
| 1.5 | `feat: wire /audio-review-jobs/latest endpoint` | ✅ | Mirrors `/explanation-jobs/latest` |
| 1.6 | `feat: stage-6 soft guardrail on /generate-audio` | ✅ | 409 w/ `requires_confirmation` when no prior review job |
| 1.7 | `refactor: remove inline MP3 synth from stage 5` | ✅ | Riskiest; shipped LAST |
| 1.8 | `feat: audio review frontend — API client + BookV2Detail trigger + dialog` | ✅ | ApiError class + 409 dialog flow |
| 1.9 | `feat: audio review per-topic trigger on ExplanationAdmin` | ✅ | |
| 1.10 | `test: audio text review service unit tests` | ✅ | 18 tests pass |
| 1.11 | `test: audio review gold / defective fixture sets + eval script` | ✅ | 20+20 fixtures, manual eval script |
| 1.12 | `docs: update principles + technical docs for new pipeline ordering` | ✅ | 10-stage pipeline + Audio Text Review section |

## Phase 2 — Visual Rendering Review ✅ complete

| # | Commit | Status | Notes |
|---|---|---|---|
| 2.1 | `feat: visual_overlap_detector pure-python utility + tests` | ✅ | 14 tests pass |
| 2.2 | `feat: visual_preview_store + endpoints + tests` | ✅ | 9 tests pass, XSS-mitigated |
| 2.3 | `feat: VisualRenderPreview admin route (id-keyed)` | ✅ | Fetches code server-side |
| 2.4 | `feat: visual_render_harness (Playwright wrapper) with preflight` | ✅ | Graceful ImportError fallback |
| 2.5 | `chore: add playwright to requirements; install docs` | ✅ | Opt-in; dev-workflow.md updated |
| 2.6 | `feat: stage 7 preflight + post-refine gate + layout_warning flag` | ✅ | 4-path flow (clean / fixed / persists / skipped) |
| 2.7 | `feat: add one general rule to visual_code_generation prompt` | ✅ | Plus `{collision_report}` in review-refine prompt |
| 2.8 | `feat: student-facing layout_warning chip + type extension` | ✅ | |
| 2.9 | `feat: /visual-status layout_warning_count + admin badge` | ✅ | |
| 2.10 | `test: visual render harness integration tests` | ✅ | 4 skipped / 1 pass w/o playwright installed |
| 2.11 | `docs: Visual Rendering Review section in book-guidelines.md` | ✅ | |

---

## Change log

_Appended as commits land. Most recent first._

### 2026-04-19 — Phase 2 complete

All 11 Phase 2 commits landed. Backend: visual_overlap_detector + preview
store + render harness (with preflight) + stage-7 post-refine gate +
layout_warning flag + /visual-status extension + preventive + collision-
report prompt rules. Frontend: id-keyed admin preview page + student chip
+ admin badge. Tests: 14 + 9 pure-python unit tests (all pass), 5
skip-guarded integration tests (4 skipped, 1 pass without playwright).
Docs: Visual Rendering Review sub-stage section in book-guidelines.md.
Playwright added to requirements.txt (opt-in); dev-workflow.md documents
the stage-7 prerequisites.

### 2026-04-19 — Phase 1 complete

All 12 Phase 1 commits landed in commit order. Backend: job-type + prompts +
service + endpoints + soft guardrail + stage-5 MP3 call removal. Frontend:
ApiError class + generateAudioReview API + BookV2Detail Review-audio button
+ 409 dialog + ExplanationAdmin per-topic trigger. Tests: 18 unit tests
(all pass), 20-card defective + 20-card clean fixtures + manual eval script.
Docs: principles renumbered to 10-stage pipeline, book-guidelines.md gains
Audio Text Review section + updated TTS synth trigger section.
