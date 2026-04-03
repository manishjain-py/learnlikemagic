# PRD: Chapter Prerequisites (Refresher Topics)

**Status:** Draft | **Date:** 2026-04-03 | **Principles:** `docs/principles/prerequisites.md`

---

## Problem

Topics assume prerequisite knowledge (e.g., place value for multiplication). Today the system only detects gaps reactively (3+ wrong answers). By then the student is frustrated and the explanation cards — which assumed the prerequisite — already failed to land.

`prior_topics_context` only covers within-chapter. Prerequisites from prior chapters/grades are invisible.

---

## Solution

Auto-generate a **refresher topic** as the first topic (`topic_sequence = 0`) of every chapter. Covers the critical foundational concepts the chapter assumes — including those from earlier chapters in the same book. Cards-only session (no interactive teaching), one explanation variant, no mastery tracking.

Additionally, a **chapter landing page** shows students what they'll learn and what prerequisites the chapter assumes, with a natural entry point to the refresher.

---

## Requirements

### R1: Refresher Generation (Single Pipeline Step)

Runs **after explanation generation** for regular topics — so it can use explanation cards as input for richer prerequisite identification.

```
Plan → Extract → Finalize → Sync → Generate Explanations → Generate Refresher
```

Single step that:
1. Reads all synced guidelines + their explanation cards for the chapter
2. LLM identifies critical prerequisites (recommends 3-5, but LLM uses judgment)
3. Same step generates the refresher teaching guideline AND its explanation cards (1 variant)
4. Stores both `TeachingGuideline` and `TopicExplanation` records

**Output TeachingGuideline:**
- `topic_key = "get-ready"`, `topic_sequence = 0`
- `metadata_json = {"is_refresher": true, "prerequisite_concepts": [...]}`

**Scope:** All prerequisites the chapter assumes — including from earlier chapters in the same book, prior grades, or external concepts. If chapter has no meaningful prerequisites, skip generation.

### R2: Refresher Guideline Content

Same format as regular guidelines but prerequisite-specific:
- Lists each prerequisite concept, why it's needed, which topics use it
- Teaching approach: warm-up framing, 1-2 cards per concept, bridge to chapter
- Scope boundary: only what's needed for this chapter, no deep dives

### R3: Explanation Cards

Generated in the same step as the guideline (not via separate explanation generation run). **One variant only** (not three). Same ELIF principles, same radical simplicity. Fewer cards (one per prerequisite concept), each bridges forward to the chapter.

### R4: Session Flow

- **Teach Me mode only** — no Exam or Clarify Doubts for refresher topics
- Creates a session, goes through card phase (same as regular topics)
- After cards: student says "clear" → session complete with a warm closing message ("You've refreshed the basics and are ready to dive into the chapter!")
- "Explain differently" is not available (single variant)
- **No interactive study plan phase** — cards only, then done
- **No mastery tracking, no scoring** — session just marks as complete
- **No scorecard entry** — refresher is not an assessed activity

### R5: Chapter Landing Page

New chapter-level UI shown when a student visits a chapter (above the topic list):

- **"What you'll learn"** — summary of what the chapter covers (from `chapter_summary`)
- **"What you'll need"** — list of prerequisite concepts the chapter assumes (from refresher topic's `metadata_json.prerequisite_concepts`)
- Natural entry point to the refresher topic for students who want the warm-up

Data source: reuses `prerequisite_concepts` from the refresher's `metadata_json`. Single source of truth.

### R6: Idempotent

Re-running replaces existing refresher (guideline + cards). Re-sync deletes all guidelines including refresher (existing cascade).

---

## Non-Goals

- Interactive teaching phase for refresher (MVP is cards only)
- Multiple explanation variants for refresher
- Mastery tracking or scoring for refresher
- Per-topic prerequisite checks
- Prerequisite dependency graphs
- Gating or forced sequencing

---

## Success Criteria

1. Every chapter gets a refresher topic (except introductory chapters with no prerequisites)
2. Content is prerequisite-specific — each concept bridges to the chapter
3. Cards follow ELIF/radical simplicity principles
4. Students read cards in 3-5 min, feel "ready"
5. Chapter landing page clearly shows what the chapter covers and what it assumes
6. Single pipeline step, runs after explanation generation
