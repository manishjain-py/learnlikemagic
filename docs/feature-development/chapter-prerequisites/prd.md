# PRD: Chapter Prerequisites (Refresher Topics)

**Status:** Draft
**Date:** 2026-04-03
**Principles:** `docs/principles/prerequisites.md`

---

## Context & Problem

### What Happens Today

When a student starts a topic, the system assumes they already know certain foundational concepts. For example, "Addition with Carrying Over" assumes the student understands place value (tens and ones). "Comparing 4-Digit Numbers" assumes they know how to read large numbers.

These assumptions are baked into:
- **Explanation cards** — which use prerequisite concepts without re-introducing them
- **Teaching guidelines** — which scope what to teach, not what should already be known
- **The tutor's interactive phase** — which builds on card content the student may not have fully grasped

### What Goes Wrong

**Student doesn't know the prerequisite.** They read explanation cards that reference "ones place" and "tens place" — but those terms are fuzzy. The cards don't make sense. They click through, the tutor starts asking questions, they get them wrong.

**Detection is reactive.** The current system detects prerequisite gaps only after 3+ consecutive wrong answers during interactive teaching. By then, the student has already experienced confusion and frustration. Their confidence is damaged.

**No structured prerequisite content.** When the tutor detects a gap, it improvises a prerequisite explanation on the fly. This ad-hoc explanation lacks the quality of pre-computed content — no multiple variants, no review-and-refine passes, no visual aids.

**Cross-boundary blindness.** `prior_topics_context` only covers earlier topics within the same chapter. Prerequisites from prior chapters or prior grades are invisible to the system.

### Why This Matters

A student who doesn't understand the foundation can't build on it. The entire learning experience for a chapter is undermined if the prerequisites aren't solid. And the worst part: the student blames themselves ("I'm bad at math") rather than recognizing they just need a quick refresher on something they learned last year.

---

## Solution Overview

Add a **refresher topic** as the first topic of every chapter. This topic covers the foundational concepts the chapter assumes — briefly, warmly, and explicitly connected to what's coming.

| Concept | Description |
|---------|-------------|
| **Refresher topic** | A regular topic (same cards, same interactive teaching) that covers the chapter's prerequisite concepts |
| **First in sequence** | Always `topic_sequence = 0`, appearing before the chapter's content topics |
| **Auto-generated** | Created during the ingestion pipeline by analyzing all topics in the chapter |
| **Uses existing infrastructure** | Same explanation cards, same variants, same tutor, same scorecard tracking |
| **Optional** | Students can skip it and start with Topic 1 directly |

---

## Requirements

### R1: Refresher Topic Generation (New Pipeline Stage)

Add a new stage **after sync**, triggered independently or as part of the pipeline:

```
Plan → Extract → Finalize → Sync → Generate Refresher → Generate Explanations (all topics)
```

**Input:** All synced `TeachingGuideline` records for the chapter — their guidelines text, topic summaries, prior_topics_context, and the chapter summary.

**Process:** The LLM analyzes the chapter's topics and identifies:
1. What foundational concepts the chapter assumes students already know
2. Which of these are NOT covered by earlier chapters in the same book (cross-referencing other chapters' topics)
3. The 3-5 most critical prerequisites — ranked by how many topics depend on them and how likely students are to have gaps

**Output:** A `TeachingGuideline` record for the refresher topic with:
- `topic_key`: `"get-ready"` 
- `topic_title`: `"Get Ready for [Chapter Name]"`
- `topic_sequence`: `0` (before all content topics)
- `guideline`: Teaching guidelines structured around the identified prerequisites. Each prerequisite gets: a brief explanation, a connection to the chapter ("you'll need this for..."), and a suggested check question
- `topic_summary`: "Quick refresher of the building blocks you'll need for this chapter"
- `metadata_json`: Includes `{"is_refresher": true, "prerequisite_concepts": [...]}` for identification and querying

**Scope rules:**
- Only prerequisites that are genuinely needed across the chapter's topics — not nice-to-haves
- Cap at 3-5 concepts — more than that and the refresher becomes a lesson itself
- Focus on the *specific aspect* needed, not the entire prerequisite topic (e.g., "place value: understanding tens and ones" for multiplication, not all of place value)
- If a chapter has no meaningful prerequisites (e.g., the very first chapter of a subject), skip refresher generation

### R2: Teaching Guidelines for the Refresher

The refresher topic's `guideline` text follows the same format as regular topics but with prerequisite-specific instructions:

**Guideline structure:**
```
Learning Objectives:
- Review foundational concepts needed for [Chapter Name]
- Build confidence before starting new content

Prerequisites Covered:
1. [Concept A] — [brief description] — Needed for: [which topics use it]
2. [Concept B] — [brief description] — Needed for: [which topics use it]
...

Teaching Approach:
- Frame as a warm-up, not remediation
- Keep each concept to 1-2 explanation cards
- Bridge every concept to the chapter: "You'll use this when we..."
- If student demonstrates prior knowledge, acknowledge and move on quickly
- Tone: encouraging, casual, building anticipation for the chapter ahead

Scope Boundary:
- ONLY what's needed for this chapter — no deep dives
- IN scope: [specific aspects of each prerequisite]
- OUT of scope: [broader aspects not relevant to this chapter]
```

### R3: Explanation Card Generation

After the refresher `TeachingGuideline` is created and synced, it goes through the **existing explanation generation pipeline** — same as any other topic:
- 3 variants (A: Everyday Analogies, B: Visual Walkthrough, C: Step-by-Step)
- Multi-pass refinement
- Same radical simplicity principles
- Same card structure (`card_type`, `title`, `content`, `audio_text`, `visual`)

**Refresher-specific generation guidance** (via the guideline text, not special code paths):
- Fewer cards than a typical topic: 3-6 cards total (covering 3-5 prerequisites)
- Each card covers one prerequisite concept
- Every card includes a forward bridge: "This is key for what we'll learn next in [Chapter]"
- Final card ties it together: "You're all set! These building blocks will make [Chapter] click."

### R4: Student Experience

**In the topic list:** The refresher appears as the first topic:
```
Chapter 3: Multiplication
  0. Get Ready for Multiplication    ← refresher
  1. Multiplying Single-Digit Numbers
  2. Multiplying by Multiples of 10
  3. Multiplying 2-Digit Numbers
  ...
```

**Learning experience:** Identical to any other topic — explanation cards, then interactive teaching. The difference is only in content (prerequisite review vs. new material) and length (shorter).

**Skippable:** Students who feel confident can skip directly to Topic 1. The refresher is recommended, not required.

### R5: Idempotent Generation

- Running refresher generation multiple times for the same chapter replaces the previous refresher (delete old `TeachingGuideline` with `topic_key = "get-ready"`, create new)
- Re-sync of a chapter deletes all guidelines including the refresher (existing cascade behavior)
- Explanation generation then runs normally for the new refresher guideline

---

## Non-Goals

- **Per-topic prerequisite checks.** One refresher per chapter is enough. Per-topic warm-ups fragment the experience.
- **Diagnostic quizzes before the refresher.** The refresher IS the check — the interactive teaching phase tests whether the student knows each prerequisite.
- **Student knowledge profile tracking.** Not building a cross-session prerequisite mastery database. The scorecard already tracks per-topic mastery, which includes the refresher topic.
- **Prerequisite dependency graphs.** Not building a formal graph of topic dependencies. The LLM identifies prerequisites from content analysis, not from a structured graph.
- **Gating or forced sequencing.** Never block a student from starting any topic. The refresher is always optional.
- **Custom UI for the refresher.** It's a regular topic. No special frontend components needed.

---

## Technical Approach (High-Level)

### New: RefresherTopicGeneratorService

- **New service:** `RefresherTopicGeneratorService` — reads all TeachingGuidelines for a chapter, calls LLM to identify prerequisites, creates a new TeachingGuideline for the refresher
- **New prompt:** `refresher_topic_generation.txt` — instructions for analyzing chapter content and generating prerequisite-focused teaching guidelines
- **Identification:** Refresher topics have `topic_key = "get-ready"` and `metadata_json` containing `{"is_refresher": true}`
- **Idempotent:** Deletes any existing refresher for the chapter before creating a new one

### New: API Endpoint

- `POST /admin/v2/books/{book_id}/chapters/{chapter_id}/refresher/generate`
- Runs as a background job (same pattern as explanation generation)
- Returns job status

### Modified: Explanation Generation

- No code changes needed — the refresher is a regular TeachingGuideline. Explanation generation picks it up automatically when run for the chapter.

### Modified: Frontend Topic List

- Minor ordering change: ensure topics display ordered by `topic_sequence`, with the refresher (sequence 0) appearing first
- Potentially a small visual indicator that it's a warm-up topic (optional)

### No Changes Needed

- Session service, orchestrator, master tutor, card phase, study plan — all work as-is because the refresher is a regular topic
- Database schema — no new tables, just a new TeachingGuideline row per chapter
- Scorecard — tracks the refresher like any other topic automatically

---

## Success Criteria

1. **Every chapter has a refresher topic** (except chapters with no meaningful prerequisites). Generated automatically during the pipeline.
2. **Refresher content is prerequisite-specific.** Covers only what THIS chapter needs — not generic review content. Each concept bridges forward to the chapter.
3. **Same quality bar as regular topics.** 3 explanation variants, radical simplicity, review-and-refine passes. A student doing the refresher gets the same high-quality experience as any other topic.
4. **Zero infrastructure overhead.** No new tables, no new session phases, no new frontend components. The refresher is indistinguishable from a regular topic in terms of system behavior.
5. **Optional and frictionless.** Students can skip the refresher with zero penalty. Students who do the refresher spend 3-5 minutes max and feel "ready" for the chapter.
6. **Pipeline integration.** Refresher generation fits naturally as a post-sync step. Can be run independently or as part of a full chapter processing pipeline.
