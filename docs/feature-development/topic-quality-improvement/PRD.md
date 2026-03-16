# PRD: Improve Chapter-to-Topic Breakdown Quality

## Context & Problem

### What We Have Today

The book ingestion v2 pipeline extracts topics from textbook chapters using a chunk-by-chunk approach:

1. **Chunk extraction** — Chapter pages are processed in 3-page windows. For each window, an LLM identifies NEW topics or marks content as EXISTING (continuation of a prior topic). Topics accumulate across chunks.
2. **Finalization** — All extracted topics go through guideline merging (per-topic), then a consolidation LLM merges overlapping topics, renames them, assigns sequence order, and writes summaries.

The extraction prompt encourages granularity: *"A topic should fit a 10-20 minute learning unit"* and *"Prefer conceptually atomic skills/concepts over broad umbrellas."*

### What's Wrong

Using Chapter 1 "Place Value and Numbers to 10,000" (Grade 3, 23 pages) as a concrete example, the pipeline produced **13 topics** with these problems:

**Too many topics.** 13 topics for a single chapter overwhelms a young student. The topic list feels endless and kills motivation.

**Overlapping page ranges.** Topics like "Standard, Word, and Expanded Forms" and "Comparing and Ordering 4-Digit Numbers" both span pp. 10-27 — nearly the entire chapter. This means overlapping content and redundant teaching.

**Illogical sequence.** "Ordinal Numbers: 1st to 40th" (pp. 16-18) appears as topic 7 after topics referencing pp. 10-27. The student's journey feels jumbled.

**Fragmented concepts.** "Reviewing 3-Digit Place Value" (pp. 7-9) and "The Thousands Place and 4-Digit Numbers" (pp. 7-9) share the same pages and are naturally one introductory lesson, yet they're separate topics.

**Meta-skills as standalone topics.** "Does My Answer Make Sense?" is a metacognitive strategy that should be woven into practice, not its own lesson.

**No cross-topic awareness during tutoring.** The tutor for Topic 5 has zero knowledge of what Topics 1-4 already taught. It may re-explain prerequisite concepts the student just learned, wasting time and feeling repetitive.

### Root Cause

The fundamental issue is **bottom-up extraction without top-down planning.** Processing 3 pages at a time forces local decisions without global chapter awareness. By the time the consolidation step runs, there are too many granular topics, and the merge rules are too conservative ("only merge topics that cover the SAME learning objective").

### Why This Matters

Topics are the primary unit of learning in our platform. A student sees the topic list as their roadmap through a chapter. Bad topics → confusing roadmap → frustrated student → low engagement. The tutor's quality is also capped by topic quality — if the scope is wrong, the tutoring is wrong.

---

## Requirements

### R1: Chapter-Level Topic Planning (New Phase)

Before chunk-by-chunk extraction, add a **chapter-level planning phase** where the LLM sees the full chapter content and produces a topic skeleton.

**Input:** All OCR'd pages for the chapter + book/chapter metadata.

**Output:** A planned topic structure containing:
- A sensible number of topics — let the content dictate. Most chapters land around 5-7, but a short chapter with 3 natural topics is fine. No artificial minimum. The hard rule: don't go so granular that the list overwhelms the student.
- For each topic: title, assigned page range (non-overlapping), 1-sentence description, rationale for grouping
- Explicit teaching sequence with dependency reasoning

**Constraints:**
- No page overlap between topics — every page maps to exactly one topic
- Meta-skills (estimation checks, "does this make sense") are folded into relevant topics, not standalone
- Related skills serving the same learning outcome are grouped together
- The plan should read like a tutor's lesson plan for the week, not a textbook's table of contents

**This planned skeleton becomes the blueprint for all subsequent extraction.**

### R2: Guided Chunk Extraction (Modified Existing Phase)

Modify the existing chunk extraction to **assign content to planned topics** rather than discovering topics freely.

**Changes to chunk extraction prompt:**
- Provide the planned topic skeleton as context (topic titles, descriptions, assigned page ranges)
- For each 3-page window, the LLM's job shifts from "what topics are here?" to "what does this content contribute to the planned topics?"
- The LLM can still flag edge cases: "this content doesn't fit any planned topic" or "this content spans two planned topics" — but it should not freely create new topics
- Guidelines extraction remains the same (learning objectives, depth, prerequisites, misconceptions, scope boundary)

**The running state (chapter summary, accumulated guidelines per topic) stays as-is.** Only the topic discovery logic changes.

### R3: Smarter Consolidation (Modified Existing Phase)

Update the consolidation phase to work with the planned structure:

- Primary role shifts from "discover merges" to "validate plan against extracted content" and "finalize guidelines, summaries, and sequence"
- If extraction reveals a planned topic was too broad (e.g., guidelines are huge and cover clearly distinct skills), the consolidation LLM can split it — but must justify the split
- If a planned topic turned out to be trivial (e.g., only 1 page, very thin guidelines), consolidation can merge it into an adjacent topic
- The bar for deviating from the plan should be high — the plan was made with full chapter visibility and should generally be trusted

### R4: Topic Continuity Context

Add a **"prior topics" context field** to each topic that tells the tutor what the student has already learned.

**For each topic (except the first), generate:**
- A concise summary of what all prior topics in the chapter covered (2-4 sentences)
- Key concepts the student already knows (bulleted list)
- Explicit instruction: "Do not re-explain these concepts. Build on them."

**Storage:** New field `prior_topics_context` on the `chapter_topics` table (TEXT, nullable). Generated during finalization.

**Tutor integration:** Inject `prior_topics_context` into the tutor's system prompt when a session starts, alongside the existing topic guidelines and study plan.

---

## What This Should Look Like

Using the same Chapter 1 example, the improved pipeline should produce something like:

| # | Topic | Pages | Why it's one unit |
|---|-------|-------|-------------------|
| 1 | Place Value: Hundreds to Thousands | 7-9 | Review 3-digit → extend to thousands. Natural warm-up into the chapter. |
| 2 | Reading and Writing 4-Digit Numbers | 10-12 | Standard, word, expanded forms + skip counting. All about representing the number. |
| 3 | Comparing, Ordering & Building Numbers | 13-18 | Compare, order, greatest/smallest, ordinal numbers. All about relationships between numbers. |
| 4 | Odd/Even Numbers and Rounding | 19-21 | Properties of numbers + estimation. Natural grouping of number classification skills. |
| 5 | Mental Math with 4-Digit Numbers | 22-24 | Applied strategies. Builds on all prior representation and comparison skills. |
| 6 | Roman Numerals and Number Patterns | 25-27 | Special number systems. Exploratory, fun topic near chapter end. |
| 7 | Chapter Review | 28-29 | Wrap-up with "Does my answer make sense?" as a review strategy, not standalone topic. |

And Topic 4's `prior_topics_context` would be:
> "The student has completed: place value up to thousands (ones, tens, hundreds, thousands places), reading/writing 4-digit numbers in standard, word, and expanded forms, and comparing/ordering 4-digit numbers including ordinal numbers. Key concepts they know: place value chart, expanded form decomposition, comparison using >, <, =, ordinal position naming. Do not re-explain these — build on them."

---

## Non-Goals

- **Re-ingesting existing books immediately.** This improves the pipeline for future processing. Existing books can be re-processed on-demand using the existing "Reprocess" button.
- **Changing the study plan generation.** Study plans within a topic are unaffected. This PRD only changes how topics themselves are defined and bounded.
- **Changing the tutoring agent logic.** The only tutor-side change is injecting `prior_topics_context` into the system prompt. No changes to tutoring flow, step handling, or response generation.
- **Admin UI changes.** The topic list, guidelines viewer, and editing tools remain as-is.

---

## Technical Approach (High-Level)

### New: Chapter Topic Planner

- **New prompt:** `chapter_topic_planning.txt` — receives all chapter pages, outputs 5-7 topic skeleton
- **New service:** `ChapterTopicPlanner` — called before `TopicExtractionOrchestrator`
- **New model:** `PlannedTopic` (topic_key, title, description, page_start, page_end, sequence_order, grouping_rationale)
- **Storage:** Planned topics stored in a new `planned_chapter_topics` table or as a JSON field on the chapter processing job

### Modified: Chunk Extraction

- **Updated prompt:** `chunk_topic_extraction.txt` — adds planned topic skeleton as context, shifts LLM role from "discover" to "assign and extract guidelines"
- **Updated orchestrator:** `TopicExtractionOrchestrator` — initializes `RunningState.topic_guidelines_map` from planned topics instead of empty

### Modified: Finalization

- **Updated prompt:** `chapter_consolidation.txt` — shifts from "merge discovery" to "plan validation + finalize"
- **New field generation:** After consolidation, generate `prior_topics_context` for each topic (except first)
- **DB migration:** Add `prior_topics_context` TEXT column to `chapter_topics`

### Modified: Tutor System Prompt

- **Updated prompt:** `master_tutor_prompts.py` — add `{prior_topics_context}` section to system prompt
- **Updated adapter:** `topic_adapter.py` or session service — load and inject prior topics context

### Input Size Consideration

Sending all chapter pages to the planning LLM may hit token limits for large chapters. Mitigation options:
- For chapters under ~40 pages (most primary school chapters): send full OCR text
- For larger chapters: send page-level summaries (first pass) or table of contents + section headers
- The planning step needs breadth (see the whole chapter) more than depth (read every word), so summarized input is acceptable

---

## Success Criteria

1. **Topic count:** Topic count is driven by content, not quotas. Most chapters land around 5-7 topics, but fewer is fine if the chapter is short. The key metric: no chapter produces 10+ topics.
2. **No page overlap:** Every page maps to exactly one topic
3. **Logical sequence:** Topics follow a progressive teaching order reviewable by a curriculum expert
4. **No redundant tutoring:** The tutor for Topic N does not re-explain concepts from Topics 1 to N-1
5. **Qualitative:** A parent looking at the topic list thinks "yes, this is a sensible lesson plan for the chapter"
