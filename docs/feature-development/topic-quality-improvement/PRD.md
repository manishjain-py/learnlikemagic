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
- A sensible number of topics — let the content dictate. Most chapters land around 5-7, but a short chapter with 3 natural topics is fine, and a dense chapter with 9 is fine too. No artificial floor or ceiling. The goal is lesson coherence, not a number.
- For each topic: title, primary page range, 1-sentence description, rationale for grouping
- Explicit teaching sequence with dependency reasoning

**Constraints:**
- Each page has a **primary topic assignment**. Transitional pages where one concept ends and another begins may be noted as boundary pages, but every page must have exactly one primary owner.
- Meta-skills (estimation checks, "does this make sense") are folded into relevant topics, not standalone
- Related skills serving the same learning outcome are grouped together
- The plan should read like a tutor's lesson plan for the week, not a textbook's table of contents

**LLM configuration:** The planning call makes high-stakes structural decisions for the entire chapter. It should use higher reasoning effort than chunk extraction (which currently uses `reasoning_effort="none"`).

**This planned skeleton becomes the blueprint for all subsequent extraction.**

### R2: Guided Chunk Extraction (Modified Existing Phase)

Modify the existing chunk extraction to **assign content to planned topics** rather than discovering topics freely.

**Changes to chunk extraction prompt:**
- Provide the planned topic skeleton as context (topic titles, descriptions, assigned page ranges)
- For each 3-page window, the LLM's job shifts from "what topics are here?" to "what does this content contribute to the planned topics?"
- Guidelines extraction remains the same (learning objectives, depth, prerequisites, misconceptions, scope boundary)
- The `is_new` field on `TopicUpdate` becomes largely obsolete in guided mode — the LLM always appends to planned topics. The prompt schema should reflect this shift.

**Plan deviation protocol:** The extraction LLM may encounter content that doesn't fit any planned topic (e.g., planner overlooked a section, OCR was poor for a page). When this happens:
- The extractor can propose an **unplanned topic** with a high justification bar — it must explain why no existing planned topic fits and what learning objective the content serves
- Unplanned topics are accumulated separately and flagged for consolidation (R3) to reconcile
- The extractor should NOT silently force-assign unrelated content to the nearest planned topic — that corrupts the guidelines

**The running state (chapter summary, accumulated guidelines per topic) stays as-is.** Only the topic discovery logic changes.

### R3: Smarter Consolidation (Modified Existing Phase)

Update the consolidation phase to work with the planned structure:

- Primary role shifts from "discover merges" to "validate plan against extracted content" and "finalize guidelines, summaries, and sequence"
- **Reconcile unplanned topics:** If extraction proposed unplanned topics, consolidation must either merge them into an existing planned topic (with justification) or ratify them as genuinely new topics that the planner missed
- If extraction reveals a planned topic was too broad (e.g., guidelines are huge and cover clearly distinct skills), the consolidation LLM can split it — but must justify the split
- If a planned topic turned out to be trivial (e.g., only 1 page, very thin guidelines), consolidation can merge it into an adjacent topic
- The bar for deviating from the plan should be high — the plan was made with full chapter visibility and should generally be trusted

**Planning failure guardrail:** If consolidation needs to deviate from the plan on more than ~30% of topics (splits, merges, or ratified unplanned topics), the chapter should be flagged for manual review rather than auto-completing. This makes the pipeline self-aware of planning failures and prevents bad plans from silently producing bad topics.

### R4: Topic Curriculum Context

Add a **"curriculum context" field** to each topic that tells the tutor where this topic sits in the chapter's learning progression.

**Important framing:** This is *curriculum context* — what the chapter's sequence builds on — NOT an assertion that the student has mastered prior topics. Students can start any topic (there's no prerequisite gate in session creation), revisit topics after gaps, or skip around. The tutor must use this context to make connections and check understanding, not to blindly skip explanations.

**For each topic (except the first), generate:**
- A concise summary of what prior topics in the chapter cover (2-4 sentences)
- Key concepts the chapter assumes by this point (bulleted list)
- Explicit instruction: "This topic builds on the concepts above. Check whether the student is comfortable with them before building on them — don't assume mastery just because they appear earlier in the chapter."

**When `prior_topics_context` is null** (first topic in chapter, or pre-existing topics from before this feature): the tutor prompt simply omits the section. No special handling needed.

**End-to-end data path requirement:** This context must flow through to **all systems that consume topic information**, not just the tutor prompt. The implementation must trace the full data path:
- **Storage:** New field on `chapter_topics` → synced through `topic_sync_service` into `teaching_guidelines`
- **Read path:** `guideline_repository` → `topic_adapter` / session service → tutor system prompt
- **Other consumers:** Study plan generation and exam generation also consume per-topic data. The implementation plan must assess whether these systems should also receive curriculum context (e.g., so study plans don't re-teach prior concepts, and exams can reference cross-topic knowledge).

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
| 7 | Chapter Review | 28-29 | Wrap-up with review exercises. Whether this is a standalone topic or folded into Topic 6 depends on the content — if it's just "check your answer" exercises, fold it in per Principle 7. |

And Topic 4's `prior_topics_context` would be:
> "Prior topics in this chapter cover: place value up to thousands (ones, tens, hundreds, thousands places), reading/writing 4-digit numbers in standard, word, and expanded forms, and comparing/ordering 4-digit numbers including ordinal numbers. Key concepts the chapter has introduced: place value chart, expanded form decomposition, comparison using >, <, =, ordinal position naming. This topic builds on those concepts. Check whether the student is comfortable with them before building on them — don't assume mastery just because they appear earlier in the chapter."

---

## Non-Goals

- **Re-ingesting existing books immediately.** This improves the pipeline for future processing. Existing books can be re-processed on-demand using the existing "Reprocess" button.
- **Changing the study plan generation logic.** Study plans within a topic are unaffected. This PRD only changes how topics themselves are defined and bounded. (Note: the implementation plan should assess whether study plan generation should receive curriculum context — but changing its core logic is out of scope.)
- **Changing the tutoring agent logic.** The tutor-side change is injecting `prior_topics_context` into the system prompt. No changes to tutoring flow, step handling, or response generation.
- **Admin UI changes.** The topic list, guidelines viewer, and editing tools remain as-is.
- **Cross-chapter continuity.** R4 adds curriculum context within a chapter (Topic 3 knows about Topics 1-2). Cross-chapter awareness (Chapter 2 Topic 1 knowing what Chapter 1 covered) is a natural future extension but is explicitly out of scope here. The data model should not preclude it, but we don't build it now.

---

## Technical Approach (High-Level)

### New: Chapter Topic Planner

- **New prompt:** `chapter_topic_planning.txt` — receives all chapter pages, outputs topic skeleton
- **New service:** `ChapterTopicPlanner` — called before `TopicExtractionOrchestrator`
- **New model:** `PlannedTopic` (topic_key, title, description, page_start, page_end, sequence_order, grouping_rationale)
- **Storage:** Planned topics stored as a JSON field on `ChapterProcessingJob` — keeps the plan coupled to the job that produced it. A separate table is only warranted if we need to query planned topics independently.
- **LLM config:** Higher reasoning effort than chunk extraction. The planning call is one per chapter (not per chunk), so higher cost is acceptable.

### Modified: Chunk Extraction

- **Updated prompt:** `chunk_topic_extraction.txt` — adds planned topic skeleton as context, shifts LLM role from "discover" to "assign and extract guidelines"
- **Updated orchestrator:** `TopicExtractionOrchestrator` — initializes `RunningState.topic_guidelines_map` from planned topics instead of empty
- **Schema change:** `is_new` on `TopicUpdate` becomes mostly obsolete — the LLM always appends to existing planned topics. Replace with a `topic_assignment` enum: `planned` (assigned to a planned topic) or `unplanned` (proposed new topic with justification).

### Modified: Finalization

- **Updated prompt:** `chapter_consolidation.txt` — shifts from "merge discovery" to "plan validation + reconciliation of unplanned topics"
- **Planning failure detection:** Count deviations (unplanned topics ratified, planned topics split/merged). If >30% of final topics differ from the plan, set chapter status to `needs_review` instead of `final`.
- **New field generation:** After consolidation, generate `prior_topics_context` for each topic (except first)
- **DB migration:** Add `prior_topics_context` TEXT column to `chapter_topics`

### End-to-End Data Path for Curriculum Context

The `prior_topics_context` field must reach the tutor at runtime. The current data path is: `chapter_topics` → `topic_sync_service` → `teaching_guidelines` → `guideline_repository` → `topic_adapter` → `master_tutor_prompts`. The implementation must:
- Add `prior_topics_context` to the sync in `topic_sync_service.py`
- Add the field to `GuidelineResponse` in `guideline_repository.py`
- Add the field to the `TopicGuidelines` model in `study_plan.py`
- Inject it in `topic_adapter.py` or the session service
- Add `{prior_topics_context}` section to the system prompt template in `master_tutor_prompts.py`

### Input Size Consideration

Sending all chapter pages to the planning LLM may hit token limits for large chapters. Mitigation options:
- For chapters under ~40 pages (most primary school chapters): send full OCR text
- For larger chapters: send page-level summaries (first pass) or table of contents + section headers
- The planning step needs breadth (see the whole chapter) more than depth (read every word), so summarized input is acceptable

---

## Success Criteria

1. **Lesson coherence:** A curriculum expert reviews the topic list and agrees each topic is a coherent, substantial lesson. Topic count is driven by content, not quotas.
2. **Minimal page overlap:** Each page has a clear primary topic. No two topics claim the same broad page range (e.g., both spanning 10+ pages).
3. **Logical sequence:** Topics follow a progressive teaching order where prerequisites come before dependent topics.
4. **Curriculum-aware tutoring:** The tutor for Topic N has context about Topics 1 to N-1 and uses it to check understanding and make connections — without blindly skipping explanations.
5. **Pipeline self-awareness:** When the planner produces a bad plan (>30% deviation at consolidation), the chapter is flagged for review rather than silently producing bad topics.
6. **Qualitative:** A parent looking at the topic list thinks "yes, this is a sensible lesson plan for the chapter."
