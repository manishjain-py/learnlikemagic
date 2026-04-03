# PRD: Chapter Prerequisites (Refresher Topics)

**Status:** Draft | **Date:** 2026-04-03 | **Principles:** `docs/principles/prerequisites.md`

---

## Problem

Topics assume prerequisite knowledge (e.g., place value for multiplication). Today the system only detects gaps reactively (3+ wrong answers). By then the student is frustrated and the explanation cards — which assumed the prerequisite — already failed to land.

`prior_topics_context` only covers within-chapter. Prerequisites from prior chapters/grades are invisible.

---

## Solution

Auto-generate a **refresher topic** as the first topic (`topic_sequence = 0`) of every chapter. Covers the 3-5 foundational concepts the chapter assumes. Uses existing infrastructure (cards, tutor, scorecard) but with refresher-aware study plan and tutor behavior.

---

## Requirements

### R1: Refresher Generation (New Pipeline Stage)

```
Plan → Extract → Finalize → Sync → Generate Refresher → Generate Explanations
```

LLM receives all synced guidelines for the chapter + other chapters' topics (cross-reference). Identifies 3-5 critical prerequisites not covered by earlier chapters. Outputs a `TeachingGuideline` with `topic_key = "get-ready"`, `topic_sequence = 0`, `metadata_json = {"is_refresher": true, "prerequisite_concepts": [...]}`.

**Scope rules:** Only genuinely needed prerequisites. Cap at 3-5. Focus on specific aspect needed, not entire prerequisite topic. Skip generation if chapter has no meaningful prerequisites.

### R2: Refresher Guideline Content

Same format as regular guidelines but with prerequisite-specific structure:
- Lists each prerequisite concept, why it's needed, which topics use it
- Teaching approach: warm-up framing, 1-2 cards per concept, bridge to chapter
- Scope boundary: only what's needed for this chapter, no deep dives

### R3: Explanation Cards

Goes through existing explanation generation pipeline. Same ELIF principles, same 3 variants, same review-and-refine. Differences driven by guideline text: fewer cards (3-6 total), one per prerequisite, each bridges forward to the chapter.

### R4: Refresher-Aware Study Plan and Tutor

The refresher covers 3-5 concepts at shallow depth — structurally different from a regular topic.

| Aspect | Regular | Refresher |
|--------|---------|-----------|
| Concepts | 1-2, deep | 3-5, shallow |
| Steps | explain → check → practice → extend | check_understanding per concept only |
| Mastery goal | ~80%+ | ~60% (gets the gist) |
| Session length | 20-40 min | 5-10 min |

**Study plan:** `is_refresher = true` → lighter plan. One `check_understanding` step per prerequisite. No practice/extend steps. Quick advance on correct answers, brief re-explanation + move on for wrong answers.

**Tutor:** Refresher-mode prompt rules — move quickly, don't deep-dive, clean transitions between concepts ("Next building block..."), easier completion bar, don't spiral on wrong answers.

### R5: Idempotent

Re-running replaces existing refresher. Re-sync deletes all guidelines including refresher (existing cascade).

---

## Non-Goals

- Per-topic prerequisite checks
- Diagnostic quizzes before the refresher
- Cross-session prerequisite knowledge profile
- Prerequisite dependency graphs
- Gating or forced sequencing
- Custom UI for the refresher

---

## Success Criteria

1. Every chapter gets a refresher topic (except introductory chapters with no prerequisites)
2. Content is prerequisite-specific — each concept bridges to the chapter
3. Same quality bar (ELIF, variants, review passes) but lighter depth
4. Students spend 5-10 min max, feel "ready"
5. Fits naturally as post-sync pipeline step
