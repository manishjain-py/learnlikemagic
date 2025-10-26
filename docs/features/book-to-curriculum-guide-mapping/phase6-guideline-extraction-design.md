# Phase 6: Guideline Extraction System - Detailed Design

**Document Version:** 1.0
**Date:** October 27, 2025
**Status:** Design Complete - Ready for MVP v1 Implementation
**Implementation Scope:** MVP v1 (Simplified, Core Features Only)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Purpose & Scope](#2-purpose--scope)
3. [Architecture Overview](#3-architecture-overview)
4. [Storage Design](#4-storage-design)
5. [Data Models](#5-data-models)
6. [Context Pack: Token Efficiency](#6-context-pack-token-efficiency)
7. [Boundary Detection](#7-boundary-detection)
8. [Teaching Description](#8-teaching-description)
9. [Pipeline Components](#9-pipeline-components)
10. [Database Schema](#10-database-schema)
11. [Quality Gates](#11-quality-gates)
12. [MVP v1 Scope](#12-mvp-v1-scope)
13. [Implementation Plan](#13-implementation-plan)
14. [Testing Strategy](#14-testing-strategy)
15. [Cost Analysis](#15-cost-analysis)
16. [Future Enhancements (v2/v3)](#16-future-enhancements-v2v3)

---

## 1. Executive Summary

### The Challenge
Convert a 50-page scanned textbook into structured, subtopic-level teaching guidelines that an AI tutor can use to teach students effectively.

### The Solution
An **incremental, page-by-page pipeline** that:
- Processes pages sequentially while maintaining context
- Uses a **Context Pack** to avoid token explosion (98% token reduction)
- Detects topic/subtopic boundaries with **hybrid signals + hysteresis**
- Stores state in **sharded per-subtopic files** for scalability
- Generates **teaching descriptions** as first-class, teacher-ready instructions
- Syncs to database when subtopics stabilize

### Key Innovation: Teaching Description
Instead of nested metadata that AI must parse, we generate a **single 3-6 line field** that contains everything needed to teach a subtopic:
- What to teach (concept definition)
- How to teach (sequence: models → examples → checks)
- What to watch for (common misconceptions + corrections)
- How to verify (understanding checks)

### MVP v1 vs Full Design

**MVP v1** (10-12 hours):
- ✅ Sharded storage (future-proof)
- ✅ Context Pack (token efficiency)
- ✅ Teaching description generation
- ✅ LLM-based boundary detection with simple hysteresis
- ✅ Quality gates (validation)
- ❌ No reconciliation window (accept ~5-10% boundary errors)
- ❌ No event sourcing (add in v2 if debugging needed)
- ❌ No embedding-based signals (LLM-only sufficient)

**Full Design** (26 hours):
- All MVP v1 features +
- Reconciliation window (reassign last M pages if needed)
- Event sourcing (`.log.jsonl` for audit/replay)
- ETag-based optimistic concurrency control
- Embedding-based boundary signals
- Advanced ToC extraction

---

## 2. Purpose & Scope

### 2.1 Goal
Build an incremental, page-by-page pipeline that converts a scanned book (images + OCR text) into teaching guidelines organized by **topic → subtopic**.

The system continuously updates a **single source of truth** for each subtopic as pages are processed, producing teacher-ready **teaching descriptions** that are sufficient for instructing the subtopic in isolation.

### 2.2 In-Scope (MVP v1)
- ✅ Page OCR → compact page summaries (minisummaries)
- ✅ Boundary detection for topics/subtopics with hysteresis
- ✅ Incremental, idempotent merges into per-subtopic guideline shards
- ✅ Teacher-ready teaching_description (concise but complete)
- ✅ Admin UI for monitoring, review, and export to DB
- ✅ Quality gates for minimum standards

### 2.3 Out-of-Scope (MVP v1, deferred to v2/v3)
- ❌ Reconciliation window (boundary reassignment)
- ❌ Event sourcing (audit logs)
- ❌ Embedding-based boundary signals
- ❌ ETag-based optimistic concurrency control
- ❌ Full curriculum ontology & synonym canonicalization
- ❌ Multi-book cross-linking and mastery modeling

---

## 3. Architecture Overview

### 3.1 High-Level Flow

```
1. Pages already uploaded (Phases 1-5)
   └─> books/{book_id}/1.png, 1.txt, 2.png, 2.txt, ...

2. Admin clicks "Generate Guidelines"
   └─> Status: pages_complete → generating_guidelines

3. For each page (sequential):
   a) Generate minisummary (≤60 words)
   b) Build Context Pack (open subtopics + recent summaries)
   c) Boundary detection (continue vs new subtopic)
   d) Extract structured facts (objectives, examples, misconceptions, assessments)
   e) Write provisional page guideline

4. Reducer merges page facts into authoritative subtopic shard
   └─> Deterministic merge, version increments

5. Stability detector marks subtopic as stable after K pages
   └─> Generate teaching_description

6. DB sync on stability
   └─> Upsert to teaching_guidelines table

7. Admin reviews and approves
   └─> Status: guidelines_pending_review → approved
```

### 3.2 Key Design Principles

**Principle 1: Sharded State**
- Each subtopic has its own `.latest.json` file
- Smaller files = faster reads/writes
- Enables per-subtopic concurrency (future)
- Easy to diff and debug

**Principle 2: Context Pack (Not Full History)**
- Passing 49 pages of text to LLM = 24,500 tokens
- Context Pack = 300-500 tokens (98% reduction)
- Contains: open subtopics summary + last 2 page summaries + ToC hints
- Maintains continuity without token explosion

**Principle 3: Incremental & Idempotent**
- Process pages one at a time
- Merges are deterministic (same delta applied twice = same result)
- Can replay processing if needed

**Principle 4: Teaching Description First**
- Single field contains complete teaching approach
- AI tutor reads ONE field, not nested metadata
- Generated when subtopic stabilizes

---

## 4. Storage Design

### 4.1 S3 Layout

```
books/{book_id}/
  # Existing (Phases 1-5):
  metadata.json              # Page approval status
  1.png, 1.txt
  2.png, 2.txt
  ...

  # New (Phase 6):
  pages/
    001.page_guideline.json  # Provisional, page-scoped
    002.page_guideline.json
    ...

  guidelines/
    index.json               # Registry of topics/subtopics
    page_index.json          # Page → assigned topic/subtopic (authoritative)

    topics/
      fractions/
        subtopics/
          adding-like-fractions.latest.json      # Authoritative shard
          subtracting-like-fractions.latest.json
          ...

      multiplication/
        subtopics/
          single-digit.latest.json
          ...
```

### 4.2 Why This Layout?

**Page Artifacts Next to Page Assets**
- `001.page_guideline.json` next to `001.txt`
- Easy debugging: "What did we extract from page 5?"

**Authoritative State Per Subtopic**
- Small shards (2-5 KB each) vs one giant file
- Fast, conflict-light updates
- Future: parallel processing

**Central Indices**
- `index.json`: Quick lookup of all topics/subtopics
- `page_index.json`: Which page belongs to which subtopic

### 4.3 Storage Scalability

**50-page book, 20 subtopics**:
- 50 × `.page_guideline.json` = 50 files × 3 KB = 150 KB
- 20 × `.latest.json` = 20 files × 4 KB = 80 KB
- 2 × index files = 7 KB
- **Total**: ~237 KB, ~72 files

**Comparison to single guideline.json**:
- Original plan: 1 file × 100 KB
- New design: 72 files × ~237 KB
- **Trade-off**: 2.4x more storage, but better scalability and debugging

---

## 5. Data Models

### 5.1 Provisional Page Guideline

**Location**: `books/{book_id}/pages/NNN.page_guideline.json`

```json
{
  "book_id": "ncert_mathematics_3_2024",
  "page": 6,
  "assigned_topic_key": "fractions",
  "assigned_subtopic_key": "adding-like-fractions",
  "confidence": 0.68,
  "summary": "Practice adding like denominators; recap numerator-only addition.",
  "facts": {
    "objectives_add": ["Add fractions with same denominators up to 12"],
    "examples_add": ["3/8 + 2/8 = 5/8"],
    "misconceptions_add": ["Add denominators (WRONG)"],
    "assessments_add": [
      {
        "level": "basic",
        "prompt": "Add 1/4 + 2/4",
        "answer": "3/4"
      }
    ]
  },
  "provisional": true,
  "decision_metadata": {
    "continue_score": 0.63,
    "new_score": 0.41,
    "reasoning": "Strong continuation signals; same practice pattern as previous pages"
  }
}
```

### 5.2 Subtopic Shard (Authoritative)

**Location**: `books/{book_id}/guidelines/topics/{topic_key}/subtopics/{subtopic_key}.latest.json`

```json
{
  "book_id": "ncert_mathematics_3_2024",
  "topic_key": "fractions",
  "subtopic_key": "adding-like-fractions",
  "aliases": ["add-like-fractions", "sum-like-denominators"],
  "status": "stable",

  "source_page_start": 2,
  "source_page_end": 6,
  "source_pages": [2, 3, 4, 5, 6],

  "objectives": [
    "Add fractions with same denominators up to 12",
    "Explain why denominators remain unchanged when adding like fractions"
  ],

  "examples": [
    "1/4 + 2/4 = 3/4",
    "3/8 + 2/8 = 5/8"
  ],

  "misconceptions": [
    "Adding denominators (e.g., 1/4 + 2/4 = 3/8)"
  ],

  "assessments": [
    {
      "level": "basic",
      "prompt": "Add 1/6 + 2/6",
      "answer": "3/6"
    },
    {
      "level": "proficient",
      "prompt": "Add 3/10 + 6/10",
      "answer": "9/10"
    }
  ],

  "teaching_description": "Teach that like fractions share the same denominator, so only numerators are added. Start with concrete partition models (quarters, eighths), link to number-line addition, and stress that denominators represent equal parts that do not change when combining. Provide counterexamples that incorrectly add denominators and have learners correct them.",

  "evidence_summary": "Worked examples across pages 2–6, practice sets on pages 4–5; misconception surfaced on page 4.",

  "confidence": 0.88,
  "last_updated_page": 6,
  "version": 5,

  "quality_flags": {
    "has_min_objectives": true,
    "has_misconception": true,
    "has_assessments": true,
    "teaching_description_valid": true
  }
}
```

### 5.3 Guidelines Index

**Location**: `books/{book_id}/guidelines/index.json`

```json
{
  "book_id": "ncert_mathematics_3_2024",
  "topics": [
    {
      "topic_key": "fractions",
      "topic_title": "Fractions",
      "subtopics": [
        {
          "subtopic_key": "adding-like-fractions",
          "subtopic_title": "Adding Like Fractions",
          "status": "stable",
          "page_range": "2-6"
        },
        {
          "subtopic_key": "subtracting-like-fractions",
          "subtopic_title": "Subtracting Like Fractions",
          "status": "open",
          "page_range": "7-?"
        }
      ]
    },
    {
      "topic_key": "multiplication",
      "topic_title": "Multiplication",
      "subtopics": []
    }
  ],
  "last_updated": "2025-10-27T04:50:00Z"
}
```

### 5.4 Page Index

**Location**: `books/{book_id}/guidelines/page_index.json`

```json
{
  "1": {"topic_key": "fractions", "subtopic_key": "intro-to-fractions", "confidence": 0.73},
  "2": {"topic_key": "fractions", "subtopic_key": "adding-like-fractions", "confidence": 0.71},
  "3": {"topic_key": "fractions", "subtopic_key": "adding-like-fractions", "confidence": 0.75},
  "4": {"topic_key": "fractions", "subtopic_key": "adding-like-fractions", "confidence": 0.80},
  "5": {"topic_key": "fractions", "subtopic_key": "adding-like-fractions", "confidence": 0.76},
  "6": {"topic_key": "fractions", "subtopic_key": "adding-like-fractions", "confidence": 0.68}
}
```

### 5.5 Context Pack (Fed to LLM)

```json
{
  "book_id": "ncert_mathematics_3_2024",
  "current_page": 6,
  "book_metadata": {
    "grade": 3,
    "subject": "Mathematics",
    "board": "CBSE"
  },
  "open_topics": [
    {
      "topic_key": "fractions",
      "topic_title": "Fractions",
      "open_subtopics": [
        {
          "subtopic_key": "adding-like-fractions",
          "subtopic_title": "Adding Like Fractions",
          "evidence_summary": "Pages 2-5: numerator-only addition; practice on p5.",
          "objectives_count": 2,
          "examples_count": 4
        }
      ]
    }
  ],
  "recent_page_summaries": [
    {
      "page": 5,
      "summary": "Practice adding 1/8 multiples; recap numerator-only addition."
    },
    {
      "page": 4,
      "summary": "Examples of 1/4+2/4; highlighted common error adding denominators."
    }
  ],
  "toc_hints": {
    "current_chapter": "Fractions",
    "next_section_candidate": "Unlike denominators"
  }
}
```

---

## 6. Context Pack: Token Efficiency

### 6.1 The Problem
Processing page 50 of a book:
- **Naive approach**: Pass all 49 previous pages of OCR text to LLM
- **Token cost**: 49 pages × 500 tokens/page = 24,500 tokens
- **Result**: Exceeds context limits, expensive, slow

### 6.2 The Solution: Context Pack
Distill historical context into a compact summary:

**Components**:
1. **Open Subtopics** (~100 tokens)
   - Which subtopics are currently active
   - Evidence summary (rule-based, not LLM-generated)
   - Count of objectives/examples extracted so far

2. **Recent Page Summaries** (~100 tokens)
   - Last 1-2 page minisummaries
   - Provides immediate context

3. **ToC Hints** (~50 tokens)
   - Current chapter/section from initial scan
   - Next section candidate (if detected)

**Total**: ~250-300 tokens (vs 24,500 tokens)

### 6.3 Evidence Summary Generation

**Rule-Based** (MVP v1):
```python
def generate_evidence_summary(shard: dict) -> str:
    return (
        f"Pages {shard['source_page_start']}-{shard['source_page_end']}: "
        f"{len(shard['objectives'])} objectives, "
        f"{len(shard['examples'])} examples, "
        f"{len(shard['misconceptions'])} misconceptions"
    )
```

**LLM-Generated** (Future v2):
```python
def generate_evidence_summary_llm(shard: dict) -> str:
    prompt = f"""Summarize this subtopic's content in one sentence:
    Objectives: {shard['objectives']}
    Examples: {shard['examples']}
    """
    return llm.invoke(prompt)
```

### 6.4 Token Reduction Impact

| Approach | Tokens per Page | Total (50 pages) |
|----------|----------------|------------------|
| **Naive (all previous pages)** | Page 50: 24,500 | 625,000 |
| **Context Pack** | Page 50: 300 | 15,000 |
| **Reduction** | **98%** | **98%** |

---

## 7. Boundary Detection

### 7.1 The Challenge
Textbooks don't have machine-readable boundaries. How do you detect:
- When a subtopic ends and a new one starts?
- When a page continues the previous subtopic?
- When to reconcile ambiguous assignments?

### 7.2 Hybrid Signals (MVP v1: LLM-Only)

**Full Design** (Future v2/v3):
```python
# 4 independent signals
layout_signal = detect_headers(page_text)      # Font size, bold, "Chapter X"
lexical_signal = keyword_match(page_text)      # Anchor words
embedding_signal = cosine_similarity(vectors)  # Semantic similarity
llm_signal = llm_judgment(context, summary)    # LLM reasoning
```

**MVP v1** (Simplified):
```python
# LLM-only signal
llm_response = llm_boundary_decision(context_pack, minisummary)
continue_score = llm_response["continue_score"]
new_score = llm_response["new_score"]
```

### 7.3 Decision Logic with Hysteresis

**Purpose**: Prevent "boundary flapping" (rapidly switching between continue/new)

```python
def decide_boundary(continue_score: float, new_score: float) -> str:
    """
    Decision logic with hysteresis zone (0.6-0.75)

    0.0 -------- 0.6 -------- 0.75 -------- 1.0
        CONTINUE    AMBIGUOUS      NEW
    """
    if continue_score >= 0.6 and new_score < 0.7:
        return "continue"  # Strong continue signal

    elif new_score >= 0.75:
        return "new"  # Strong new signal

    else:  # Ambiguous zone (0.6-0.75)
        # Provisional: assign to best match, revisit later if needed
        if continue_score > new_score:
            return "provisional_continue"
        else:
            return "provisional_new"
```

**Example**:
```
Page 5: continue=0.82, new=0.35 → CONTINUE (clear)
Page 6: continue=0.65, new=0.62 → PROVISIONAL_CONTINUE (ambiguous)
Page 7: continue=0.58, new=0.85 → NEW (clear)

Result: Pages 1-5 → Subtopic A
        Pages 7+  → Subtopic B
        Page 6: Initially assigned to A, but could be reassigned (future reconciliation)
```

### 7.4 Reconciliation Window (Not in MVP v1)

**Concept** (Future v2):
- Keep last M=3 pages in a "reconciliation window"
- If page N has strong "new" signal, look back at pages N-1, N-2, N-3
- Reassign if those pages better fit the new subtopic
- Update both shards and rewrite page files

**Deferred Reason**: Adds significant complexity (~3 hours), MVP can accept ~5-10% boundary errors

---

## 8. Teaching Description

### 8.1 The Innovation

**Problem with Nested Metadata**:
```json
{
  "subtopic": "Comparing Like Denominators",
  "metadata": {
    "learning_objectives": ["Compare fractions with like denominators"],
    "common_misconceptions": ["Students might compare only numerators"],
    "scaffolding_strategies": ["Use visual models like pie charts"]
  }
}
```
AI tutor must:
1. Parse nested structure
2. Extract relevant pieces
3. Synthesize teaching approach
4. Risk missing key information

**Solution: Single Teaching Description Field**:
```json
{
  "teaching_description": "Teach that like fractions share the same denominator, so only numerators are compared. Start with concrete partition models (pie charts for quarters, eighths), then transition to abstract number comparison. Common error: comparing denominators instead—surface this by showing 3/8 vs 2/8 visually. Check understanding with 'Which is bigger: 5/12 or 7/12?' before moving to addition."
}
```
AI tutor reads **ONE field** and has:
- ✅ What to teach (concept)
- ✅ How to teach (sequence)
- ✅ What to watch for (misconceptions)
- ✅ How to verify (check question)

### 8.2 Content Requirements

A teaching description must include:

1. **Concept Definition** (1 sentence)
   - What is the subtopic?
   - What's the core idea?

2. **Scope & Depth** (brief)
   - What's included/excluded?
   - Grade-appropriate boundaries

3. **Teaching Sequence** (1-2 sentences)
   - Concrete → abstract
   - Models → examples → practice
   - Prerequisite links

4. **Misconceptions** (1 sentence)
   - Common student errors
   - How to surface and correct

5. **Understanding Check** (optional)
   - Quick verification question
   - Mastery indicator

### 8.3 Generation Prompt

```python
TEACHING_DESCRIPTION_PROMPT = """You are an expert curriculum designer for grade {grade} {subject}.

Given this subtopic data, write a teaching_description (3-6 lines) that fully equips a teacher to teach this subtopic.

REQUIREMENTS:
1. State the concept clearly (what students will learn)
2. Specify depth and scope (what's in/out of scope for this grade)
3. Prescribe the teaching sequence (concrete models → examples → checks)
4. Name common misconceptions and how to surface/correct them
5. Include a quick understanding check (if applicable)

SUBTOPIC: {subtopic_title}

OBJECTIVES:
{objectives}

EXAMPLES:
{examples}

MISCONCEPTIONS:
{misconceptions}

ASSESSMENTS:
{assessments}

EVIDENCE:
{evidence_summary}

OUTPUT FORMAT:
- 3-6 lines of direct, actionable instructions
- Use concise, clear sentences
- No fluff or redundancy
- Focus on HOW to teach, not just WHAT to teach

Teaching Description:"""
```

### 8.4 Validation

**Automated Quality Check**:
```python
def validate_teaching_description(desc: str) -> dict:
    """Return validation results"""
    checks = {
        "has_teaching_verb": any(word in desc.lower() for word in
            ["teach", "start with", "introduce", "explain", "show"]),

        "has_sequence": any(word in desc.lower() for word in
            ["first", "then", "before", "after", "start", "begin"]),

        "mentions_misconception": any(word in desc.lower() for word in
            ["error", "mistake", "misconception", "common", "incorrect", "wrong"]),

        "has_verification": "?" in desc or "check" in desc.lower(),

        "length_ok": 100 <= len(desc) <= 800,  # ~3-6 lines

        "not_too_short": len(desc.split()) >= 30  # At least 30 words
    }

    return {
        "valid": all(checks.values()),
        "checks": checks,
        "score": sum(checks.values()) / len(checks)
    }
```

### 8.5 Examples

**Good Teaching Description**:
```
Teach that like fractions share the same denominator, so only numerators
are compared. Start with concrete partition models (pie charts for quarters,
eighths), then transition to abstract number comparison. Common error:
comparing denominators instead—surface this by showing 3/8 vs 2/8 visually.
Check understanding with "Which is bigger: 5/12 or 7/12?" before moving to addition.
```
✅ Has concept, sequence, misconception, check
✅ 63 words, clear and actionable

**Bad Teaching Description**:
```
This subtopic covers comparing fractions. Students will learn to compare
fractions with the same denominator.
```
❌ No teaching sequence
❌ No misconceptions
❌ No verification
❌ Too short, not actionable

---

## 9. Pipeline Components

### 9.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Guideline Extraction Pipeline             │
└─────────────────────────────────────────────────────────────┘

Input: books/{book_id}/1.txt, 2.txt, ..., 50.txt (from Phase 4 OCR)

┌──────────────────┐
│ 1. Minisummary   │  Per page: Extract 60-word summary
│    Generator     │  Output: pages/001.page_guideline.json (partial)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 2. Context Pack  │  Build context for current page
│    Builder       │  Input: Open shards + recent summaries
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 3. Boundary      │  Decide: continue vs new subtopic
│    Detector      │  LLM-based (MVP v1)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 4. Facts         │  Extract objectives, examples, misconceptions
│    Extractor     │  Output: Complete page_guideline.json
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 5. Reducer       │  Merge page facts into subtopic shard
│                  │  Deterministic, idempotent
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 6. Stability     │  Mark subtopic as stable after K pages
│    Detector      │  Trigger teaching_description generation
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 7. Teaching Desc │  Generate teacher-ready description
│    Generator     │  LLM prompt → 3-6 line output
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 8. Quality Gates │  Validate: ≥2 objectives, ≥1 misconception
│                  │  Mark needs_review if fails
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 9. DB Sync       │  Upsert to teaching_guidelines table
│                  │  On stability or final
└──────────────────┘

Output: DB rows + guidelines/ folder with shards
```

### 9.2 Component Details

#### **1. Minisummary Generator**

**Purpose**: Compress page OCR text into 60-word extractive summary

**Input**:
- `page_text`: Full OCR text from `books/{book_id}/N.txt`

**Output**:
- `summary`: 2-3 bullet points, ≤60 words

**Prompt**:
```python
MINISUMMARY_PROMPT = """Read this textbook page and provide a brief summary (≤60 words).

Focus on:
- Main concept or topic covered
- Key examples or problems shown
- Teaching approach (definition, practice, assessment, etc.)

Be factual and extractive. No interpretation.

PAGE TEXT:
{page_text}

SUMMARY (≤60 words):"""
```

**Caching**: Store in `pages/NNN.page_guideline.json` to avoid regeneration

---

#### **2. Context Pack Builder**

**Purpose**: Build compact context (~300 tokens) from current state

**Input**:
- `current_page`: Page number being processed
- `index.json`: Current topics/subtopics
- `open_shards`: `.latest.json` files for open subtopics
- `recent_pages`: Last 1-2 page summaries

**Output**: Context Pack JSON (see section 5.5)

**Logic**:
```python
def build_context_pack(book_id: str, current_page: int) -> dict:
    # Load index
    index = load_json(f"{book_id}/guidelines/index.json")

    # Find open subtopics
    open_subtopics = []
    for topic in index["topics"]:
        for subtopic in topic["subtopics"]:
            if subtopic["status"] == "open":
                shard = load_json(f"{book_id}/guidelines/topics/{topic['topic_key']}/subtopics/{subtopic['subtopic_key']}.latest.json")

                open_subtopics.append({
                    "subtopic_key": subtopic["subtopic_key"],
                    "subtopic_title": subtopic["subtopic_title"],
                    "evidence_summary": generate_evidence_summary(shard),
                    "objectives_count": len(shard["objectives"]),
                    "examples_count": len(shard["examples"])
                })

    # Get recent page summaries
    recent = []
    for page_num in range(max(1, current_page - 2), current_page):
        page_guideline = load_json(f"{book_id}/pages/{page_num:03d}.page_guideline.json")
        recent.append({
            "page": page_num,
            "summary": page_guideline["summary"]
        })

    return {
        "book_id": book_id,
        "current_page": current_page,
        "open_topics": open_subtopics,
        "recent_page_summaries": recent,
        "toc_hints": {}  # Simplified for MVP v1
    }
```

---

#### **3. Boundary Detector**

**Purpose**: Decide if current page continues existing subtopic or starts new one

**Input**:
- `context_pack`: Current state
- `minisummary`: Current page summary

**Output**:
```json
{
  "decision": "continue|new",
  "continue_score": 0.65,
  "new_score": 0.58,
  "assigned_subtopic_key": "adding-like-fractions",
  "reasoning": "Content continues numerator addition practice from previous pages"
}
```

**Prompt**:
```python
BOUNDARY_DETECTION_PROMPT = """You are analyzing a textbook page to determine if it continues the current subtopic or starts a new one.

CONTEXT (Previous State):
{context_pack}

CURRENT PAGE SUMMARY:
{minisummary}

TASK:
1. Analyze if this page CONTINUES an existing open subtopic or starts a NEW subtopic
2. Provide confidence scores (0.0-1.0) for both decisions
3. If continuing, identify which subtopic
4. If new, suggest a subtopic name (kebab-case)

GUIDELINES:
- Practice problems usually CONTINUE the current subtopic
- Headers like "Chapter X" or "Section Y" usually indicate NEW subtopic
- Gradual topic drift = CONTINUE (don't split on minor variations)
- Clear conceptual shift = NEW

OUTPUT JSON:
{{
  "decision": "continue|new",
  "continue_score": 0.00,
  "new_score": 0.00,
  "continue_subtopic_key": "string or null",
  "new_subtopic_key": "string or null",
  "new_subtopic_title": "string or null",
  "reasoning": "Brief explanation"
}}
"""
```

**Decision Logic**: See section 7.3

---

#### **4. Facts Extractor**

**Purpose**: Extract structured facts from page text

**Input**:
- `page_text`: Full OCR text
- `assigned_subtopic`: From boundary detector

**Output**:
```json
{
  "objectives_add": ["Add fractions with same denominators up to 12"],
  "examples_add": ["3/8 + 2/8 = 5/8"],
  "misconceptions_add": ["Adding denominators"],
  "assessments_add": [
    {
      "level": "basic",
      "prompt": "Add 1/4 + 2/4",
      "answer": "3/4"
    }
  ]
}
```

**Prompt**:
```python
FACTS_EXTRACTION_PROMPT = """Extract structured facts from this textbook page.

SUBTOPIC: {subtopic_title}

PAGE TEXT:
{page_text}

Extract:
1. OBJECTIVES: What should students learn? (bullet points)
2. EXAMPLES: Worked examples or demonstrations (with answers if shown)
3. MISCONCEPTIONS: Common errors mentioned or implied
4. ASSESSMENTS: Practice problems (with difficulty level: basic/proficient/advanced)

OUTPUT JSON:
{{
  "objectives_add": ["objective 1", "objective 2"],
  "examples_add": ["example 1", "example 2"],
  "misconceptions_add": ["misconception 1"],
  "assessments_add": [
    {{"level": "basic", "prompt": "question", "answer": "answer"}}
  ]
}}

Rules:
- Only extract what's explicitly present
- Empty arrays if nothing found
- Be concise but complete
"""
```

---

#### **5. Reducer**

**Purpose**: Merge page facts into authoritative subtopic shard

**Input**:
- `subtopic_key`: Target shard
- `page_delta`: Facts from page

**Output**: Updated `.latest.json` shard

**Logic**:
```python
def merge_page_facts(shard: dict, delta: dict, page: int) -> dict:
    """
    Deterministic, idempotent merge

    Rules:
    - Deduplicate objectives, examples, misconceptions
    - Extend page range
    - Increment version
    """
    # Deduplicate objectives (case-insensitive)
    existing_obj_lower = {obj.lower() for obj in shard["objectives"]}
    for obj in delta.get("objectives_add", []):
        if obj.lower() not in existing_obj_lower:
            shard["objectives"].append(obj)
            existing_obj_lower.add(obj.lower())

    # Deduplicate examples (by hash)
    example_hashes = {hash(ex) for ex in shard["examples"]}
    for ex in delta.get("examples_add", []):
        if hash(ex) not in example_hashes:
            shard["examples"].append(ex)

    # Deduplicate misconceptions
    existing_misc_lower = {m.lower() for m in shard["misconceptions"]}
    for m in delta.get("misconceptions_add", []):
        if m.lower() not in existing_misc_lower:
            shard["misconceptions"].append(m)

    # Merge assessments (allow duplicates at different levels)
    shard["assessments"].extend(delta.get("assessments_add", []))

    # Update page range
    if page not in shard["source_pages"]:
        shard["source_pages"].append(page)
        shard["source_pages"].sort()

    if page < shard["source_page_start"]:
        shard["source_page_start"] = page
    if page > shard["source_page_end"]:
        shard["source_page_end"] = page

    # Increment version
    shard["version"] += 1
    shard["last_updated_page"] = page

    return shard
```

**Idempotency**: Applying same delta twice = same result (no duplicates added)

---

#### **6. Stability Detector**

**Purpose**: Mark subtopic as "stable" when ready for teaching description

**Trigger Conditions**:
- ✅ No new pages added to this subtopic for K=3 pages (other subtopic is active)
- ✅ OR hard boundary detected (strong "new" signal on next page)
- ✅ OR book processing complete

**Logic**:
```python
def check_stability(subtopic_key: str, current_page: int, index: dict) -> bool:
    """Determine if subtopic is stable"""
    shard = load_shard(subtopic_key)

    # Condition 1: No updates for K pages
    pages_since_update = current_page - shard["last_updated_page"]
    if pages_since_update >= 3:
        return True

    # Condition 2: Hard boundary (checked by boundary detector)
    # This is handled externally

    # Condition 3: Book complete (checked by pipeline orchestrator)

    return False

def mark_stable(subtopic_key: str):
    """Mark subtopic as stable and generate teaching description"""
    shard = load_shard(subtopic_key)
    shard["status"] = "stable"

    # Generate teaching description
    teaching_desc = generate_teaching_description(shard)
    shard["teaching_description"] = teaching_desc

    # Validate
    validation = validate_teaching_description(teaching_desc)
    shard["quality_flags"]["teaching_description_valid"] = validation["valid"]

    save_shard(subtopic_key, shard)
```

---

#### **7. Teaching Description Generator**

See section 8.3 for prompt details.

**LLM Call**:
```python
def generate_teaching_description(shard: dict) -> str:
    """Generate teacher-ready teaching description"""
    prompt = TEACHING_DESCRIPTION_PROMPT.format(
        grade=shard["book_metadata"]["grade"],
        subject=shard["book_metadata"]["subject"],
        subtopic_title=shard["subtopic_title"],
        objectives="\n".join(f"- {obj}" for obj in shard["objectives"]),
        examples="\n".join(f"- {ex}" for ex in shard["examples"]),
        misconceptions="\n".join(f"- {m}" for m in shard["misconceptions"]),
        assessments=json.dumps(shard["assessments"], indent=2),
        evidence_summary=shard["evidence_summary"]
    )

    response = llm.invoke(prompt, max_tokens=400)
    return response.strip()
```

---

#### **8. Quality Gates**

**Purpose**: Ensure minimum standards before marking final

**Hard Requirements**:
```python
def check_quality_gates(shard: dict) -> dict:
    """Validate subtopic meets minimum standards"""
    checks = {
        "has_min_objectives": len(shard["objectives"]) >= 2,
        "has_misconception": len(shard["misconceptions"]) >= 1,
        "has_assessments": len(shard["assessments"]) >= 1,
        "teaching_description_present": bool(shard.get("teaching_description")),
        "teaching_description_valid": False
    }

    # Validate teaching description
    if checks["teaching_description_present"]:
        validation = validate_teaching_description(shard["teaching_description"])
        checks["teaching_description_valid"] = validation["valid"]

    passed = all(checks.values())

    return {
        "passed": passed,
        "checks": checks,
        "score": sum(checks.values()) / len(checks)
    }
```

**On Failure**:
```python
if not quality_gates["passed"]:
    shard["status"] = "needs_review"
    shard["quality_flags"].update(quality_gates["checks"])
    # Admin must manually review and fix
```

---

#### **9. DB Sync**

**Purpose**: Upsert subtopic to `teaching_guidelines` table

**Trigger**: When subtopic marked as stable

**Logic**:
```python
def sync_subtopic_to_db(book_id: str, shard: dict):
    """Upsert subtopic to teaching_guidelines table"""
    book = get_book(book_id)

    # Map shard to teaching_guidelines row
    guideline = {
        "country": book.country,
        "board": book.board,
        "grade": book.grade,
        "subject": book.subject,

        # New schema columns (adopted from user design)
        "topic_key": shard["topic_key"],
        "subtopic_key": shard["subtopic_key"],

        "topic": shard["topic_title"],  # Human-readable
        "subtopic": shard["subtopic_title"],

        # Core teaching field
        "teaching_description": shard["teaching_description"],

        # Structured metadata (keep in JSON for flexibility)
        "objectives_json": json.dumps(shard["objectives"]),
        "examples_json": json.dumps(shard["examples"]),
        "misconceptions_json": json.dumps(shard["misconceptions"]),
        "assessments_json": json.dumps(shard["assessments"]),

        # Source tracking
        "book_id": book_id,
        "source_pages": json.dumps(shard["source_pages"]),
        "source_page_start": shard["source_page_start"],
        "source_page_end": shard["source_page_end"],

        # Metadata
        "status": "draft",  # Will be "final" when book approved
        "confidence": shard["confidence"],
        "evidence_summary": shard["evidence_summary"]
    }

    # Upsert (insert or update if exists)
    upsert_teaching_guideline(guideline)
```

---

## 10. Database Schema

### 10.1 New Schema (Adopted)

**Extended `teaching_guidelines` table**:

```sql
-- Existing columns (unchanged):
id VARCHAR PRIMARY KEY
country VARCHAR NOT NULL
board VARCHAR NOT NULL
grade INTEGER NOT NULL
subject VARCHAR NOT NULL
created_at TIMESTAMP DEFAULT NOW()

-- Existing columns (kept for compatibility):
topic VARCHAR NOT NULL              -- Human-readable: "Fractions"
subtopic VARCHAR NOT NULL           -- Human-readable: "Adding Like Fractions"
guideline TEXT                      -- Deprecated, use teaching_description instead

-- Existing columns (enhanced):
book_id VARCHAR REFERENCES books(id) ON DELETE SET NULL
source_pages VARCHAR                -- JSON array: "[2,3,4,5,6]"

-- NEW COLUMNS (Phase 6):
topic_key VARCHAR NOT NULL          -- Slugified: "fractions"
subtopic_key VARCHAR NOT NULL       -- Slugified: "adding-like-fractions"

objectives_json TEXT                -- JSON array of objectives
examples_json TEXT                  -- JSON array of examples
misconceptions_json TEXT            -- JSON array of misconceptions
assessments_json TEXT               -- JSON array of assessments

teaching_description TEXT NOT NULL  -- Core teaching field (3-6 lines)

source_page_start INTEGER           -- First page of subtopic
source_page_end INTEGER             -- Last page of subtopic
evidence_summary TEXT               -- Brief content summary

status VARCHAR DEFAULT 'draft'      -- draft|final
confidence FLOAT                    -- 0.0-1.0
version INTEGER DEFAULT 1           -- For tracking updates

-- Indices:
CREATE INDEX idx_teaching_guidelines_keys ON teaching_guidelines(topic_key, subtopic_key);
CREATE INDEX idx_teaching_guidelines_book ON teaching_guidelines(book_id);
CREATE INDEX idx_teaching_guidelines_curriculum ON teaching_guidelines(country, board, grade, subject);
```

### 10.2 Migration Script

```python
# alembic/versions/XXX_phase6_guideline_schema.py

def upgrade():
    # Add new columns
    op.add_column('teaching_guidelines', sa.Column('topic_key', sa.String(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('subtopic_key', sa.String(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('objectives_json', sa.Text(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('examples_json', sa.Text(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('misconceptions_json', sa.Text(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('assessments_json', sa.Text(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('teaching_description', sa.Text(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('source_page_start', sa.Integer(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('source_page_end', sa.Integer(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('evidence_summary', sa.Text(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('status', sa.String(), server_default='draft'))
    op.add_column('teaching_guidelines', sa.Column('confidence', sa.Float(), nullable=True))
    op.add_column('teaching_guidelines', sa.Column('version', sa.Integer(), server_default='1'))

    # Create indices
    op.create_index('idx_teaching_guidelines_keys', 'teaching_guidelines', ['topic_key', 'subtopic_key'])

    # Backfill topic_key/subtopic_key from existing topic/subtopic (slugify)
    op.execute("""
        UPDATE teaching_guidelines
        SET
            topic_key = LOWER(REPLACE(topic, ' ', '-')),
            subtopic_key = LOWER(REPLACE(subtopic, ' ', '-'))
        WHERE topic_key IS NULL
    """)

    # Make NOT NULL after backfill
    op.alter_column('teaching_guidelines', 'topic_key', nullable=False)
    op.alter_column('teaching_guidelines', 'subtopic_key', nullable=False)

def downgrade():
    # Drop indices
    op.drop_index('idx_teaching_guidelines_keys', 'teaching_guidelines')

    # Drop columns
    op.drop_column('teaching_guidelines', 'version')
    op.drop_column('teaching_guidelines', 'confidence')
    op.drop_column('teaching_guidelines', 'status')
    op.drop_column('teaching_guidelines', 'evidence_summary')
    op.drop_column('teaching_guidelines', 'source_page_end')
    op.drop_column('teaching_guidelines', 'source_page_start')
    op.drop_column('teaching_guidelines', 'teaching_description')
    op.drop_column('teaching_guidelines', 'assessments_json')
    op.drop_column('teaching_guidelines', 'misconceptions_json')
    op.drop_column('teaching_guidelines', 'examples_json')
    op.drop_column('teaching_guidelines', 'objectives_json')
    op.drop_column('teaching_guidelines', 'subtopic_key')
    op.drop_column('teaching_guidelines', 'topic_key')
```

---

## 11. Quality Gates

### 11.1 Validation Rules

**Minimum Requirements**:
```python
QUALITY_GATES = {
    "objectives": {
        "min_count": 2,
        "error_message": "Subtopic must have at least 2 learning objectives"
    },
    "misconceptions": {
        "min_count": 1,
        "error_message": "Subtopic must identify at least 1 common misconception"
    },
    "assessments": {
        "min_count": 1,
        "error_message": "Subtopic must have at least 1 assessment item"
    },
    "teaching_description": {
        "required": True,
        "min_length": 100,
        "max_length": 800,
        "min_words": 30,
        "must_contain": ["teach", "misconception|error|mistake"],
        "error_message": "Teaching description must be 3-6 lines and include teaching approach and misconceptions"
    }
}
```

### 11.2 Automated Enforcement

```python
def enforce_quality_gates(shard: dict) -> tuple[bool, list[str]]:
    """
    Enforce quality gates, return (passed, errors)
    """
    errors = []

    # Check objectives
    if len(shard["objectives"]) < QUALITY_GATES["objectives"]["min_count"]:
        errors.append(QUALITY_GATES["objectives"]["error_message"])

    # Check misconceptions
    if len(shard["misconceptions"]) < QUALITY_GATES["misconceptions"]["min_count"]:
        errors.append(QUALITY_GATES["misconceptions"]["error_message"])

    # Check assessments
    if len(shard["assessments"]) < QUALITY_GATES["assessments"]["min_count"]:
        errors.append(QUALITY_GATES["assessments"]["error_message"])

    # Check teaching description
    td = shard.get("teaching_description", "")
    if not td:
        errors.append("Teaching description is missing")
    else:
        if len(td) < QUALITY_GATES["teaching_description"]["min_length"]:
            errors.append("Teaching description too short (min 100 chars)")
        if len(td) > QUALITY_GATES["teaching_description"]["max_length"]:
            errors.append("Teaching description too long (max 800 chars)")
        if len(td.split()) < QUALITY_GATES["teaching_description"]["min_words"]:
            errors.append("Teaching description too brief (min 30 words)")
        if not any(word in td.lower() for word in ["teach", "start", "introduce"]):
            errors.append("Teaching description must include teaching approach")
        if not any(word in td.lower() for word in ["misconception", "error", "mistake"]):
            errors.append("Teaching description must mention common misconceptions")

    passed = len(errors) == 0
    return passed, errors
```

### 11.3 Admin Review Workflow

**When gates fail**:
1. Mark subtopic `status = "needs_review"`
2. Store errors in `quality_flags`
3. Display in Admin UI with specific issues
4. Admin can:
   - Manually edit subtopic (future enhancement)
   - Regenerate teaching description
   - Override and approve anyway (with warning)

---

## 12. MVP v1 Scope

### 12.1 What's Included

✅ **Core Architecture**:
- Sharded storage (`.latest.json` per subtopic)
- Context Pack for token efficiency
- Provisional page guidelines

✅ **Pipeline Components**:
- Minisummary generation
- Context Pack builder
- LLM-based boundary detection (simple hysteresis)
- Facts extraction
- Deterministic reducer
- Stability detection
- Teaching description generation
- Quality gates
- DB sync

✅ **Admin UI**:
- Progress indicator during generation
- Subtopic list view
- Teaching description review
- Approve/regenerate controls

### 12.2 What's Deferred (v2/v3)

❌ **Reconciliation Window**:
- Reassigning last M pages if boundary unclear
- Reason: Adds 3+ hours, accept ~5-10% boundary errors for MVP

❌ **Event Sourcing**:
- `.log.jsonl` append-only logs
- Replay capability
- Reason: Useful for debugging, but not critical for MVP

❌ **Embedding-Based Signals**:
- Vector similarity for boundary detection
- Reason: LLM judgment sufficient, adds complexity

❌ **ETag-Based Concurrency Control**:
- Optimistic locking for parallel processing
- Reason: Single-threaded processing sufficient for 50-page MVP

❌ **Advanced ToC Scanner**:
- LLM-based chapter/section extraction
- Reason: Simple regex sufficient for MVP

❌ **Inline Subtopic Editing**:
- Admin can edit objectives, examples directly in UI
- Reason: Regeneration sufficient for MVP

### 12.3 MVP v1 Limitations

**Known Issues** (acceptable for MVP):
1. **Boundary Errors**: ~5-10% of pages may be assigned to wrong subtopic
   - Impact: Minor; usually off by 1 page at boundaries
   - Mitigation: Admin review can catch major issues

2. **No Replay**: If pipeline crashes mid-processing, must restart
   - Impact: Lose partial progress (not data, just computation)
   - Mitigation: Process small books first to validate

3. **Sequential Processing**: Takes ~5-10 minutes for 50-page book
   - Impact: Not ideal UX, but acceptable for admin use case
   - Mitigation: Show progress indicator

4. **No Boundary Reassignment**: Once assigned, page stays with subtopic
   - Impact: Occasional suboptimal grouping
   - Mitigation: Rare in practice; can manually regenerate if needed

---

## 13. Implementation Plan

### 13.1 Phases

**Phase 6a: Core Pipeline** (~6 hours)
1. Data model schemas (JSON) - 0.5 hours
2. S3 layout setup - 0.5 hours
3. Minisummary generator - 1 hour
4. Context Pack builder - 1.5 hours
5. Boundary detector (LLM-only) - 1.5 hours
6. Facts extractor - 1 hour

**Phase 6b: State Management** (~3 hours)
7. Reducer (deterministic merge) - 1.5 hours
8. Stability detector - 0.5 hours
9. Index management (index.json, page_index.json) - 1 hour

**Phase 6c: Quality & Sync** (~2 hours)
10. Teaching description generator - 1 hour
11. Quality gates - 0.5 hours
12. DB sync - 0.5 hours

**Phase 6d: Admin UI** (~3 hours)
13. Guideline review page - 1.5 hours
14. Progress indicator - 0.5 hours
15. Approve/regenerate controls - 1 hour

**Total: ~14 hours** (slightly over 10-12 estimate, but includes buffer)

### 13.2 Implementation Order

**Day 1** (6 hours):
- [ ] Data models and S3 layout
- [ ] Minisummary generator
- [ ] Context Pack builder
- [ ] Boundary detector

**Day 2** (5 hours):
- [ ] Facts extractor
- [ ] Reducer
- [ ] Stability detector
- [ ] Index management

**Day 3** (3 hours):
- [ ] Teaching description generator
- [ ] Quality gates
- [ ] DB sync
- [ ] Testing with 10-page sample

**Day 4** (3 hours):
- [ ] Admin UI components
- [ ] Integration testing
- [ ] 50-page full book test

### 13.3 Code Structure

```
llm-backend/features/book_ingestion/
├── services/
│   ├── guideline_extraction_service.py     # Main orchestrator
│   ├── minisummary_service.py              # Component 1
│   ├── context_pack_service.py             # Component 2
│   ├── boundary_detection_service.py       # Component 3
│   ├── facts_extraction_service.py         # Component 4
│   ├── reducer_service.py                  # Component 5
│   ├── stability_service.py                # Component 6
│   ├── teaching_description_service.py     # Component 7
│   └── quality_gates_service.py            # Component 8
│
├── models/
│   ├── guideline_models.py                 # Pydantic models for all JSON schemas
│   └── schemas.py                          # (existing, add Phase 6 schemas)
│
├── utils/
│   ├── s3_client.py                        # (existing)
│   └── guideline_helpers.py                # Helper functions (slugify, dedup, etc.)
│
├── prompts/
│   ├── minisummary.txt
│   ├── boundary_detection.txt
│   ├── facts_extraction.txt
│   └── teaching_description.txt
│
├── api/
│   └── routes.py                           # (existing, add Phase 6 endpoints)
│
└── tests/
    ├── test_guideline_extraction.py
    ├── test_boundary_detection.py
    └── test_teaching_description.py
```

---

## 14. Testing Strategy

### 14.1 Unit Tests

**Component-Level**:
```python
# test_minisummary_service.py
def test_minisummary_generation():
    page_text = "Chapter 3: Fractions. A fraction represents..."
    summary = MinisummaryService().generate(page_text)
    assert len(summary.split()) <= 60
    assert "fraction" in summary.lower()

# test_boundary_detection_service.py
def test_continue_decision():
    context = {...}  # Mock context with open subtopic
    summary = "More practice problems on adding fractions"
    decision = BoundaryDetectionService().decide(context, summary)
    assert decision["decision"] == "continue"
    assert decision["continue_score"] > 0.6

# test_reducer_service.py
def test_idempotent_merge():
    shard = initialize_shard()
    delta = {"objectives_add": ["Objective A"], "page": 5}

    result1 = ReducerService().merge(shard, delta)
    result2 = ReducerService().merge(result1, delta)  # Apply same delta again

    assert result1 == result2  # Idempotent
    assert len(result2["objectives"]) == 1  # No duplicates

# test_teaching_description_service.py
def test_teaching_description_generation():
    shard = {
        "objectives": ["Add like fractions", "Explain denominator rule"],
        "examples": ["1/4 + 2/4 = 3/4"],
        "misconceptions": ["Adding denominators"]
    }
    desc = TeachingDescriptionService().generate(shard)
    validation = validate_teaching_description(desc)
    assert validation["valid"]
    assert len(desc.split()) >= 30
```

### 14.2 Integration Tests

**Pipeline-Level**:
```python
# test_guideline_extraction_integration.py
def test_full_pipeline_10_pages():
    """Process a 10-page sample book end-to-end"""
    book_id = "test_book_10pages"

    # Setup: Create book with 10 approved pages
    setup_test_book(book_id, num_pages=10)

    # Run extraction
    service = GuidelineExtractionService(book_id)
    service.run()

    # Verify shards created
    index = load_json(f"{book_id}/guidelines/index.json")
    assert len(index["topics"]) >= 1

    # Verify teaching descriptions
    for topic in index["topics"]:
        for subtopic in topic["subtopics"]:
            shard = load_shard(book_id, topic["topic_key"], subtopic["subtopic_key"])
            assert shard["status"] == "stable"
            assert shard["teaching_description"]
            assert len(shard["objectives"]) >= 2

    # Verify DB sync
    guidelines = db.query(TeachingGuideline).filter_by(book_id=book_id).all()
    assert len(guidelines) >= 1

def test_boundary_detection_edge_cases():
    """Test boundary detection with ambiguous pages"""
    book_id = "test_boundary_cases"

    # Create pages with deliberate ambiguity:
    # Pages 1-3: Clear topic A
    # Page 4: Ambiguous (could be A or B)
    # Pages 5-7: Clear topic B

    service = GuidelineExtractionService(book_id)
    service.run()

    page_index = load_json(f"{book_id}/guidelines/page_index.json")

    # Page 4 should be assigned (even if uncertain)
    assert "4" in page_index
    assert page_index["4"]["confidence"] < 0.75  # Ambiguous
```

### 14.3 E2E Test

**Full NCERT Math Magic Book**:
```python
# test_ncert_math_magic.py
def test_full_ncert_book():
    """
    End-to-end test with real NCERT Math Magic Grade 3 book (~50 pages)

    Success Criteria:
    - Completes within 10 minutes
    - Generates 15-25 subtopics
    - All subtopics pass quality gates
    - < 15% boundary errors (manual spot-check)
    - Teaching descriptions are coherent and actionable
    """
    book_id = "ncert_math_3_2024"

    start_time = time.time()

    # Run extraction
    service = GuidelineExtractionService(book_id)
    service.run()

    elapsed = time.time() - start_time
    assert elapsed < 600  # 10 minutes

    # Check guideline count
    index = load_json(f"{book_id}/guidelines/index.json")
    subtopic_count = sum(len(t["subtopics"]) for t in index["topics"])
    assert 15 <= subtopic_count <= 25

    # Check quality gates
    failed_count = 0
    for topic in index["topics"]:
        for subtopic in topic["subtopics"]:
            shard = load_shard(book_id, topic["topic_key"], subtopic["subtopic_key"])
            passed, errors = enforce_quality_gates(shard)
            if not passed:
                print(f"Failed: {subtopic['subtopic_key']}: {errors}")
                failed_count += 1

    assert failed_count == 0  # All pass quality gates

    # Manual boundary check (sample 10 pages)
    # Admin manually verifies page assignments are reasonable
    print("\n=== MANUAL BOUNDARY CHECK ===")
    for page in random.sample(range(1, 51), 10):
        assignment = page_index[str(page)]
        print(f"Page {page}: {assignment['topic_key']} > {assignment['subtopic_key']} (conf={assignment['confidence']:.2f})")

    # Check DB sync
    guidelines = db.query(TeachingGuideline).filter_by(book_id=book_id).all()
    assert len(guidelines) == subtopic_count
```

### 14.4 Quality Metrics

**Collected During Testing**:
1. **Processing Time**: Total time per book
2. **Token Usage**: Total input/output tokens, cost
3. **Boundary Accuracy**: % of pages correctly assigned (manual spot-check)
4. **Quality Gate Pass Rate**: % of subtopics passing all gates
5. **Teaching Description Quality**: Manual review (coherent, actionable, complete)

**Target Metrics** (MVP v1):
- Processing time: < 10 minutes for 50-page book
- Token cost: < $0.05 per book
- Boundary accuracy: > 85% (manual check of 20 pages)
- Quality gate pass rate: > 90%
- Teaching description quality: > 80% rated "good" or "excellent" by admin

---

## 15. Cost Analysis

### 15.1 Token Usage Breakdown

**50-page book, 20 subtopics, gpt-4o-mini ($0.15/1M input, $0.60/1M output)**:

| Component | Calls | Input Tokens/Call | Output Tokens/Call | Total Input | Total Output | Cost |
|-----------|-------|-------------------|-------------------|-------------|--------------|------|
| **Minisummary** | 50 | 500 | 100 | 25,000 | 5,000 | $0.007 |
| **Boundary Detection** | 50 | 300 | 200 | 15,000 | 10,000 | $0.008 |
| **Facts Extraction** | 50 | 500 | 300 | 25,000 | 15,000 | $0.013 |
| **Teaching Description** | 20 | 500 | 150 | 10,000 | 3,000 | $0.003 |
| **Total** | 170 | - | - | **75,000** | **33,000** | **$0.031** |

### 15.2 Comparison to Context-Less Approach

**Without Context Pack** (passing all previous pages to LLM):
- Page 50 boundary decision: 24,500 tokens input
- Total for 50 pages: ~625,000 tokens input
- Cost: ~$0.094 (3x more expensive)

**With Context Pack**:
- Page 50 boundary decision: 300 tokens input
- Total for 50 pages: 75,000 tokens input
- Cost: $0.031 (3x cheaper)

### 15.3 Scalability

**100 books** (5,000 pages):
- Total cost: 100 × $0.031 = **$3.10**
- Token usage: 7.5M input, 3.3M output

**Conclusion**: Cost is negligible, not a constraint for MVP or production.

---

## 16. Future Enhancements (v2/v3)

### 16.1 Reconciliation Window (v2)

**Feature**: Reassign last M=3 pages if later context reveals boundary misplacement

**Scenario**:
```
Pages 5-7: Assigned to "Adding Like Fractions" (confidence ~0.65)
Page 8: Strong header "Subtracting Fractions" (new_score=0.92)

Reconciliation:
- Look back at pages 5-7
- Re-evaluate with new context
- If page 7 better fits "Subtracting", reassign
- Update both shards, rewrite page files
```

**Benefits**:
- Reduces boundary errors from ~10% to ~2%
- More accurate page ranges

**Complexity**: +3 hours implementation

---

### 16.2 Event Sourcing (v2)

**Feature**: Append-only event log per subtopic

**File**: `{subtopic_key}.log.jsonl`

```jsonl
{"ts":"2025-10-27T04:50:00Z","page":2,"delta":{"objectives_add":["Add like fractions"]}}
{"ts":"2025-10-27T04:50:15Z","page":3,"delta":{"examples_add":["1/4 + 2/4 = 3/4"]}}
```

**Benefits**:
- Audit trail: "When was misconception X added?"
- Replay: Rebuild shard from log if corrupted
- Debugging: Trace how shard evolved

**Complexity**: +1.5 hours implementation

---

### 16.3 Embedding-Based Boundary Signals (v2)

**Feature**: Use vector similarity for boundary detection

**Logic**:
```python
# Compute centroid of current subtopic
subtopic_embeddings = [embed(obj) for obj in shard["objectives"]] + [embed(ex) for ex in shard["examples"]]
centroid = np.mean(subtopic_embeddings, axis=0)

# Compare page summary embedding to centroid
page_embedding = embed(minisummary)
affinity = cosine_similarity(page_embedding, centroid)

# High affinity → likely continuation
# Low affinity → likely new subtopic
```

**Benefits**:
- More robust than LLM-only (complements, doesn't replace)
- Catches semantic drift

**Complexity**: +1.5 hours implementation, +$0.0001 per book (embeddings API)

---

### 16.4 ETag-Based Concurrency Control (v3)

**Feature**: Allow parallel processing of pages with optimistic locking

**Logic**:
```python
# Read shard with ETag
shard, etag = s3.get_object_with_etag(shard_key)

# Merge delta
updated = merge(shard, delta)

# Write with If-Match (atomic compare-and-swap)
try:
    s3.put_object(shard_key, updated, if_match=etag)
except PreconditionFailed:
    # Someone else modified, retry
    retry_with_backoff()
```

**Benefits**:
- Process pages in parallel → 3-5x faster
- Reduces 10-minute pipeline to 2-3 minutes

**Complexity**: +3 hours implementation, requires careful testing

---

### 16.5 Advanced ToC Scanner (v3)

**Feature**: LLM-based chapter/section extraction from first 5 pages

**Logic**:
```python
# Scan first 5 pages for ToC
toc_pages = [load_page(i) for i in range(1, 6)]
toc = extract_table_of_contents(toc_pages)

# Use as hints for boundary detection
{
  "chapters": [
    {"title": "Fractions", "page_start": 15, "sections": ["Adding", "Subtracting"]},
    {"title": "Multiplication", "page_start": 30, "sections": ["Single Digit", "Two Digit"]}
  ]
}
```

**Benefits**:
- Better boundary detection (know expected chapters)
- Pre-seed topic structure

**Complexity**: +2 hours implementation

---

## 17. Risk Assessment

### 17.1 Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Boundary errors > 15%** | Medium | Low | Accept for MVP; add reconciliation in v2 |
| **Teaching descriptions too generic** | High | Medium | Iterate on prompt; add examples; quality gates |
| **Pipeline crashes mid-run** | Low | Low | Restart from page N; future: checkpointing |
| **LLM API rate limits** | Low | Low | Add retry with backoff; use per-minute cap |
| **S3 storage costs** | Low | Very Low | ~$0.23/month for 10GB; negligible |

### 17.2 Quality Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Missed objectives/misconceptions** | Medium | Medium | Quality gates enforce minimums; admin review |
| **Incorrect subtopic grouping** | Medium | Medium | Hysteresis reduces flapping; manual spot-check |
| **Teaching descriptions not actionable** | High | Low | Validation checks; prompt engineering |

### 17.3 Timeline Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Implementation > 14 hours** | Low | Medium | MVP v1 scope is flexible; defer v2 features |
| **Testing reveals major bugs** | Medium | Low | Unit tests catch early; integration tests validate |
| **Admin UX unclear** | Low | Low | Iterate with stakeholder feedback |

---

## 18. Success Criteria

### 18.1 MVP v1 Complete When:

✅ **Functional**:
- [ ] Admin can click "Generate Guidelines" on `pages_complete` book
- [ ] Pipeline processes 50-page book in < 10 minutes
- [ ] Sharded storage created (`.latest.json` per subtopic)
- [ ] Teaching descriptions generated for all stable subtopics
- [ ] Subtopics synced to `teaching_guidelines` table
- [ ] Admin can review subtopics in UI
- [ ] Admin can approve and mark book as `approved`

✅ **Quality**:
- [ ] > 90% of subtopics pass quality gates
- [ ] Teaching descriptions are coherent and actionable (manual review)
- [ ] < 15% boundary errors (manual spot-check of 20 pages)

✅ **Integration**:
- [ ] Existing AI tutor can query and use new guidelines
- [ ] No breaking changes to phases 1-5
- [ ] Database migration runs cleanly

✅ **Testing**:
- [ ] Unit tests pass (all components)
- [ ] Integration test passes (10-page sample)
- [ ] E2E test passes (50-page NCERT book)

---

## 19. Next Steps

### 19.1 Immediate (Before Implementation)

1. ✅ Review this design document
2. ✅ Confirm MVP v1 scope with stakeholders
3. ✅ Update other documentation (implementation-plan.txt, IMPLEMENTATION_SUMMARY.md)

### 19.2 Implementation (Day 1-4)

4. [ ] Set up Phase 6 code structure
5. [ ] Implement core pipeline components
6. [ ] Build state management (reducer, indices)
7. [ ] Add teaching description generation
8. [ ] Create admin UI components
9. [ ] Write unit and integration tests

### 19.3 Testing & Validation (Day 4)

10. [ ] Test with 10-page sample
11. [ ] Test with full 50-page NCERT book
12. [ ] Manual quality review (boundary accuracy, teaching descriptions)
13. [ ] Fix bugs and iterate

### 19.4 Post-MVP

14. [ ] Evaluate v2 features based on MVP results
15. [ ] Implement reconciliation if boundary errors > 10%
16. [ ] Add event sourcing if debugging challenges arise
17. [ ] Consider embeddings if LLM-only insufficient

---

**Document Status**: ✅ Ready for Implementation
**Last Updated**: October 27, 2025
**Prepared By**: AI Assistant & User Collaboration
**Next Review**: After MVP v1 testing complete
