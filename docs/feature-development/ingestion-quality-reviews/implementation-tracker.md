# Implementation Tracker — Ingestion Quality Reviews

Live tracker for PR #105 implementation work. Updated after each commit lands.

**PRD:** `PRD.md`
**Plan:** `impl-plan.md`
**Review:** `impl-plan-review.md`

**Legend:** ⬜ not started · 🔄 in progress · ✅ done · ⏭️ skipped · ❌ blocked

---

## Phase 1 — Audio Text Review

| # | Commit | Status | Notes |
|---|---|---|---|
| 1.1 | `feat: add V2JobType.AUDIO_TEXT_REVIEW constant` | ⬜ | Smallest change, unblocks everything |
| 1.2 | `feat: add audio text review prompt files` | ⬜ | `audio_text_review.txt`, `_system.txt` |
| 1.3 | `feat: add AudioTextReviewService` | ⬜ | Per-card LLM call, surgical revisions, drift guard |
| 1.4 | `feat: wire /generate-audio-review endpoint + background task` | ⬜ | Mirrors `/generate-audio` |
| 1.5 | `feat: wire /audio-review-jobs/latest endpoint` | ⬜ | Mirrors `/explanation-jobs/latest` |
| 1.6 | `feat: stage-6 soft guardrail on /generate-audio` | ⬜ | 409 w/ `requires_confirmation` when no prior review job |
| 1.7 | `refactor: remove inline MP3 synth from stage 5` | ⬜ | Riskiest; ship LAST |
| 1.8 | `feat: audio review frontend — API client + BookV2Detail trigger + dialog` | ⬜ | |
| 1.9 | `feat: audio review per-topic trigger on ExplanationAdmin` | ⬜ | |
| 1.10 | `test: audio text review service unit tests` | ⬜ | |
| 1.11 | `test: audio review gold / defective fixture sets + eval script` | ⬜ | |
| 1.12 | `docs: update principles + technical docs for new pipeline ordering` | ⬜ | |

## Phase 2 — Visual Rendering Review

| # | Commit | Status | Notes |
|---|---|---|---|
| 2.1 | `feat: visual_overlap_detector pure-python utility + tests` | ⬜ | No external deps |
| 2.2 | `feat: visual_preview_store + endpoints + tests` | ⬜ | Server-side ephemerals (XSS mitigation) |
| 2.3 | `feat: VisualRenderPreview admin route (id-keyed)` | ⬜ | Fetches code from preview store |
| 2.4 | `feat: visual_render_harness (Playwright wrapper) with preflight` | ⬜ | |
| 2.5 | `chore: add playwright to requirements; install docs` | ⬜ | |
| 2.6 | `feat: stage 7 preflight + post-refine gate + layout_warning flag` | ⬜ | |
| 2.7 | `feat: add one general rule to visual_code_generation prompt` | ⬜ | |
| 2.8 | `feat: student-facing layout_warning chip + type extension` | ⬜ | |
| 2.9 | `feat: /visual-status layout_warning_count + admin badge` | ⬜ | |
| 2.10 | `test: visual render harness integration tests` | ⬜ | Skip-guarded on playwright availability |
| 2.11 | `docs: Visual Rendering Review section in book-guidelines.md` | ⬜ | |

---

## Change log

_Appended as commits land. Most recent first._
