# Guidelines Extraction Architecture Overview

**Created**: 2025-11-05
**Status**: ✅ Complete Reference Documentation
**Purpose**: High-level architectural documentation for the guideline extraction pipeline

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [High-Level Flow](#high-level-flow)
3. [The 9-Step Pipeline](#the-9-step-pipeline)
4. [Boundary Detection Deep Dive](#boundary-detection-deep-dive)
5. [Context Window & Token Optimization](#context-window--token-optimization)
6. [Key Design Decisions](#key-design-decisions)
7. [Success Metrics](#success-metrics)

---

## Overview

### Purpose

Convert PDF textbook pages into structured teaching guidelines with:
- Topics and subtopics (learning objectives)
- Objectives, examples, misconceptions, assessments
- Teaching descriptions (concise 3-6 line instructions)
- Comprehensive descriptions (200-300 word overviews)
- Page-range mappings

### Architecture Philosophy

**Single Responsibility Principle**: Each service handles one task
- `MinisummaryService`: Generate page summaries
- `BoundaryDetectionService`: Detect topic boundaries
- `FactsExtractionService`: Extract structured teaching data
- `ReducerService`: Merge facts into shards
- `DescriptionGenerator`: Generate comprehensive descriptions
- `QualityValidationService`: Validate guideline quality

**Token Efficiency**: Aggressive optimization to reduce costs
- Context packing: 97% token reduction (24,500 → 300 tokens)
- Only send recent 2 page summaries to AI
- Compact evidence summaries instead of full content

**Real-time Processing**: Page-by-page pipeline with streaming updates
- Process pages as they're uploaded
- Save intermediate state to S3
- Can stop/resume at any time

---

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     INPUT: PDF Textbook                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 1: Page Upload & OCR Extraction (Vision API)          │
│  • Convert pages to images                                   │
│  • Extract text with gpt-4o-mini vision                     │
│  • Store text in S3: books/{id}/pages/001.page.json         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 2: Page-by-Page Processing Loop                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  For each page (1 to N):                            │   │
│  │                                                       │   │
│  │  2.1  Generate Mini-Summary (2-3 sentences)         │   │
│  │       ↓                                              │   │
│  │  2.2  Boundary Detection (CONTINUE vs NEW)          │   │
│  │       ↓                                              │   │
│  │  2.3  Extract Facts (objectives, examples, etc)     │   │
│  │       ↓                                              │   │
│  │  2.4  Update or Create Shard                        │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 3: Stability Detection                                 │
│  • Check if subtopics are stable (no new pages for 3+)      │
│  • Mark stable subtopics for finalization                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 4: Finalization (When Stable)                          │
│  • 4.1  Generate evidence summary (rule-based)              │
│  • 4.2  Generate teaching description (3-6 lines)           │
│  • 4.3  Generate comprehensive description (200-300 words)  │
│  • 4.4  Quality validation (0.0-1.0 score)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 5: Save to S3 (Staging Area)                          │
│  • Save shards: books/{id}/shards/{topic}/{subtopic}.json  │
│  • Update index: books/{id}/guidelines/index.json           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 6: User Review (Admin UI)                             │
│  • Display all subtopics with details                       │
│  • User approves or rejects                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 7: Database Sync (After Approval)                     │
│  • Sync approved shards to teaching_guidelines table        │
│  • Production database update                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           OUTPUT: Structured Teaching Guidelines             │
│  • Topics, subtopics with page ranges                       │
│  • Objectives, examples, misconceptions, assessments        │
│  • Teaching description + comprehensive description         │
└─────────────────────────────────────────────────────────────┘
```

---

## The 9-Step Pipeline

### Step 1: Page Upload & OCR Extraction

**Service**: Vision API (gpt-4o-mini)
**Input**: PDF page images
**Output**: Extracted text stored in S3

```python
# Example extracted text
{
  "page": 1,
  "text": "Let's count cows using tally marks. Tally marks help us organize and count objects...",
  "ocr_model": "gpt-4o-mini",
  "timestamp": "2025-11-05T10:00:00Z"
}
```

**Location**: `books/{book_id}/pages/001.page.json`

---

### Step 2: Page-by-Page Processing Loop

The orchestrator processes each page through 4 sub-steps:

#### Step 2.1: Generate Mini-Summary

**Service**: `MinisummaryService`
**Purpose**: Condense page content into 2-3 sentences
**Model**: gpt-4o-mini (200 tokens max)

**Example**:
```
Input (Page 1): "Let's count cows using tally marks. Tally marks help us organize and count objects. Draw one line for each object. After four lines, draw a diagonal line across them to make groups of five..."

Output: "This page introduces tally marks as a visual method for counting and organizing data. Students learn to draw tally marks in groups of five for easier counting. The example demonstrates counting 12 cows using tally marks."
```

**Why 2-3 sentences?**
- Captures essence without overwhelming context
- Used in boundary detection for recent page context
- Token efficient (30-50 tokens vs 500+ for full page)

---

#### Step 2.2: Boundary Detection 🎯

**Service**: `BoundaryDetectionService`
**Purpose**: Decide if page CONTINUES current subtopic or starts NEW one
**Model**: gpt-4o-mini (300 tokens max, temperature 0.2)

**This is the most critical step for subtopic cohesion!**

##### Context Window: What AI Sees

```python
CONTEXT = {
    # 1. Book Metadata
    "grade": 3,
    "subject": "Mathematics",
    "board": "NCERT",

    # 2. Current Page Number
    "current_page": 8,

    # 3. Recent Page Summaries (Last 2 pages)
    "recent_page_summaries": [
        {
            "page": 6,
            "summary": "This page discusses organizing data using tables..."
        },
        {
            "page": 7,
            "summary": "Students practice categorizing household items by type and size..."
        }
    ],

    # 4. All Open Subtopics (not finalized yet)
    "open_subtopics": [
        {
            "topic_key": "data-handling",
            "topic_title": "Data Handling",
            "subtopic_key": "organizing-information",
            "subtopic_title": "Organizing Information",
            "page_start": 1,
            "page_end": 7,
            "total_pages": 7,
            "evidence_summary": "Pages 1-7: 3 objectives, 6 examples"
        }
    ],

    # 5. Current Page Mini-Summary
    "current_page_minisummary": "Students categorize hair styles (long, short, curly, straight)..."
}
```

##### Recent Pages Window

**Configuration**: Last **2 pages** (configurable)

```python
# File: context_pack_service.py:226
def _get_recent_summaries(
    self,
    book_id: str,
    current_page: int,
    num_recent: int = 2  # ← DEFAULT: 2 PAGES
) -> List[RecentPageSummary]:
```

**Why only 2 pages?**

Token efficiency optimization:

```
WITHOUT context packing (full page content):
- Page 1: ~500 tokens
- Page 2: ~500 tokens
- ...
- Page 7: ~500 tokens
Total: 3,500 tokens PER BOUNDARY DECISION

WITH context packing (2 recent summaries):
- Page 6 summary: ~30 tokens
- Page 7 summary: ~30 tokens
- Open subtopic info: ~50 tokens
Total: ~110 tokens PER BOUNDARY DECISION

Reduction: 97% fewer tokens! 🎉
```

**Trade-off**:
- ✅ Massive cost savings
- ✅ Faster processing
- ⚠️ Less historical context
- ✅ Mitigated by: Open subtopic evidence summary covers ALL previous pages

##### The Prompt (Enhanced with Pedagogical Principles)

```text
You are analyzing a textbook page to determine if it continues the current subtopic or starts a new one.

CONTEXT (Previous State):
Book: Grade 3 Mathematics (NCERT)
Current Page: 8

Open Subtopics:
Topic: Data Handling
  - Organizing Information (organizing-information)
    Evidence: Pages 1-7: 3 objectives, 6 examples

Recent Page Summaries:
Page 6: This page discusses organizing data using tables...
Page 7: Students practice categorizing household items by type and size...

CURRENT PAGE SUMMARY:
Students categorize hair styles (long, short, curly, straight)...

IMPORTANT - PEDAGOGICAL PRINCIPLES:
A subtopic represents a LEARNING OBJECTIVE, not individual activities or examples.
Multiple activities can teach the SAME learning objective.

GUIDELINES FOR CONTINUATION (favor CONTINUE over NEW):
1. Same Learning Objective: If pages teach the same concept through different examples → CONTINUE
   - Example: "Categorizing household items" and "Categorizing hairstyles" both teach categorization → CONTINUE

2. Different Activities, Same Skill: Multiple exercises/activities for one concept → CONTINUE
   - Counting with tally marks, organizing data, categorizing objects = all "Data Handling" → CONTINUE

3. Common Grade-Level Topics:
   - Grade 3 Math: Data Handling (tally marks, tables, categorizing), Number Operations, Geometry
   - If activities fit the same curriculum topic → CONTINUE

4. Look for CONCEPTUAL similarity, not surface-level activity similarity

BIAS TOWARDS CONTINUATION:
- When in doubt, CONTINUE rather than create NEW
- Subtopics should be BROADER, not narrower
- Target: 10-20 pages per subtopic (not 1-2 pages)

OUTPUT JSON:
{
  "decision": "continue|new",
  "continue_score": 0.00,
  "new_score": 0.00,
  "continue_subtopic_key": "string or null",
  "new_subtopic_key": "string or null",
  "new_subtopic_title": "string or null",
  "reasoning": "Brief explanation"
}
```

**File**: `/llm-backend/features/book_ingestion/prompts/boundary_detection.txt`

##### AI's Decision Process

**Example for Page 8 (Categorizing Hair Styles):**

```
AI analyzes:
1. Current page (8): Categorizing hair styles
2. Previous page (7): Categorizing household items
3. Open subtopic: "Organizing Information" (pages 1-7)

AI's internal reasoning:
┌─────────────────────────────────────────────────────────────┐
│ Question: Is categorizing hair styles the SAME learning     │
│           objective as categorizing household items?        │
│ Answer: YES - both teach the skill of categorization        │
│                                                              │
│ Question: Are these different activities or concepts?       │
│ Answer: Different activities, SAME concept                  │
│         (organizing/categorizing)                           │
│                                                              │
│ Question: Should this be a NEW subtopic                     │
│           "Categorizing Hair Styles"?                       │
│ Answer: NO - that would be treating an activity            │
│         as a subtopic (pedagogical error)                   │
│                                                              │
│ Question: What's the broader learning objective?            │
│ Answer: Data Handling / Organizing Information              │
│                                                              │
│ Decision: CONTINUE with "Organizing Information"            │
└─────────────────────────────────────────────────────────────┘
```

##### AI's JSON Response

```json
{
  "decision": "continue",
  "continue_score": 0.85,
  "new_score": 0.15,
  "continue_subtopic_key": "organizing-information",
  "new_subtopic_key": null,
  "new_subtopic_title": null,
  "reasoning": "Page 8 teaches the same skill (categorization) as page 7, just with a different example (hair styles vs household items). Both are data handling activities. Same learning objective = CONTINUE."
}
```

##### Hysteresis Application

**Purpose**: Prevent "boundary flapping" (oscillating between CONTINUE/NEW)

```python
# Thresholds (boundary_detection_service.py:43-44)
CONTINUE_THRESHOLD = 0.6   # Need ≥60% confidence to continue
NEW_THRESHOLD = 0.75       # Need ≥75% confidence to start new

# Decision logic for Page 8:
continue_score = 0.85  # AI's continue confidence
new_score = 0.15       # AI's new confidence

# Check: continue_score (0.85) ≥ 0.6 AND new_score (0.15) < 0.7?
if continue_score >= 0.6 and new_score < 0.7:
    # YES → STRONG CONTINUE SIGNAL
    final_decision = "continue"
    confidence = 0.85
```

**Hysteresis Zones:**

```
┌──────────────────────────────────────────────────────────┐
│  Confidence Distribution                                  │
│                                                           │
│  0.0 ─────────────────────────────────────────────── 1.0 │
│       │                    │              │               │
│       └─ Weak ─────────────┼──Ambiguous──┼─── Strong ──┘ │
│                            │              │               │
│                         0.6 (CONTINUE)  0.75 (NEW)        │
│                                                           │
│  STRONG CONTINUE:  continue ≥ 0.6  AND  new < 0.7        │
│  STRONG NEW:       new ≥ 0.75                             │
│  AMBIGUOUS:        In between (use best guess, cap 0.65)  │
└──────────────────────────────────────────────────────────┘
```

##### Confidence Scores Breakdown

| Scenario | Continue | New | Final | Confidence | Notes |
|----------|----------|-----|-------|------------|-------|
| **Clear continuation** | 0.90 | 0.10 | CONTINUE | 0.90 | Same activity repeated |
| **Strong continuation** | 0.85 | 0.15 | CONTINUE | 0.85 | Different activity, same concept |
| **Weak continuation** | 0.65 | 0.35 | CONTINUE | 0.65 | Minor topic drift |
| **Ambiguous** | 0.62 | 0.68 | Best guess | 0.65 | Capped confidence |
| **Strong new** | 0.20 | 0.80 | NEW | 0.80 | Clear conceptual shift |
| **Clear new** | 0.05 | 0.95 | NEW | 0.95 | Chapter header detected |

##### Real Example: Over-segmentation Issue

**Before Enhancement (Wrong Behavior):**

```
Page 1 (Tally Marks):
  AI sees: No open subtopics
  Decision: NEW → "Counting Cows with Tally Marks"

Page 3 (Animal Names):
  AI sees: Recent=[Page 1 summary], Open=["Counting Cows"]
  Reasoning: "Different activity (measuring names vs counting)"
  Decision: NEW → "Animal Name Lengths"  ❌ WRONG

Page 7 (Categorizing Items):
  AI sees: Recent=[Page 5, 6], Open=["Counting", "Animal Names", "Number Names"]
  Reasoning: "New activity (categorizing vs counting)"
  Decision: NEW → "Categorizing Household Items"  ❌ WRONG

Page 8 (Categorizing Hair):
  AI sees: Recent=[Page 6, 7], Open=[... "Categorizing Items"]
  Reasoning: "Different example (hair vs items)"
  Decision: NEW → "Categorizing Hair Styles"  ❌ WRONG

Result: 8 pages → 5 subtopics (over-segmentation!)
```

**After Enhancement (Correct Behavior):**

```
Page 1 (Tally Marks):
  AI sees: No open subtopics
  Decision: NEW → "Data Handling and Organization"

Page 3 (Animal Names):
  AI sees: Recent=[Page 1, 2], Open=["Data Handling"]
  Reasoning: "Counting letters = organizing data = SAME OBJECTIVE"
  Decision: CONTINUE → "Data Handling"  ✅ CORRECT

Page 7 (Categorizing Items):
  AI sees: Recent=[Page 5, 6], Open=["Data Handling (1-6)"]
  Reasoning: "Categorizing = organizing = SAME OBJECTIVE"
  Decision: CONTINUE → "Data Handling"  ✅ CORRECT

Page 8 (Categorizing Hair):
  AI sees: Recent=[Page 6, 7], Open=["Data Handling (1-7)"]
  Reasoning: "Same activity as Page 7 (categorizing), same concept"
  Decision: CONTINUE → "Data Handling"  ✅ CORRECT

Result: 8 pages → 1 subtopic (proper cohesion!)
```

##### Key Parameters

| Parameter | Value | File:Line | Purpose |
|-----------|-------|-----------|---------|
| **Recent pages window** | 2 pages | `context_pack_service.py:226` | Balance context vs tokens |
| **Continue threshold** | 0.6 (60%) | `boundary_detection_service.py:43` | Min confidence to continue |
| **New threshold** | 0.75 (75%) | `boundary_detection_service.py:44` | Min confidence to start new |
| **LLM model** | gpt-4o-mini | `boundary_detection_service.py:54` | Fast + accurate + cheap |
| **Max tokens** | 300 | `boundary_detection_service.py:55` | Decisions are concise |
| **Temperature** | 0.2 | `boundary_detection_service.py:118` | Low = consistent decisions |

---

#### Step 2.3: Extract Facts

**Service**: `FactsExtractionService`
**Purpose**: Extract structured teaching data from page
**Model**: gpt-4o-mini (800 tokens max)

**Extracts**:
- **Objectives**: What students should learn (learning goals)
- **Examples**: Specific problems, activities, exercises
- **Misconceptions**: Common student errors or confusions
- **Assessments**: Questions to test understanding (with answers and difficulty levels)

**Example Output**:

```json
{
  "objectives": [
    "Use tally marks to represent counts",
    "Organize data using visual marks",
    "Group tally marks in sets of five for easier counting"
  ],
  "examples": [
    "Counting 12 cows using tally marks: |||| |||| ||",
    "Counting 8 books: |||| |||",
    "Counting 15 pencils: |||| |||| |||| "
  ],
  "misconceptions": [
    "Students may not group tally marks in 5s, making counting harder",
    "Students may draw all marks horizontally without diagonal lines"
  ],
  "assessments": [
    {
      "prompt": "Draw tally marks for 8 books",
      "answer": "|||| |||",
      "level": "basic"
    },
    {
      "prompt": "Count the tally marks: |||| |||| ||",
      "answer": "12",
      "level": "proficient"
    },
    {
      "prompt": "Why do we group tally marks in 5s?",
      "answer": "To make counting faster and avoid mistakes",
      "level": "advanced"
    }
  ]
}
```

**File**: `/llm-backend/features/book_ingestion/services/facts_extraction_service.py`

---

#### Step 2.4: Update or Create Shard

**Service**: `ReducerService`
**Purpose**: Merge extracted facts into subtopic shards
**Logic**: Based on boundary decision

##### If CONTINUE:

```python
# Load existing shard
shard = load_shard(topic_key, subtopic_key)

# Merge facts (append, deduplicate)
shard.objectives.extend(new_objectives)
shard.examples.extend(new_examples)
shard.misconceptions.extend(new_misconceptions)
shard.assessments.extend(new_assessments)

# Update page range
shard.source_page_end = current_page

# Save updated shard
save_shard(shard)
```

##### If NEW:

```python
# Create new shard
shard = SubtopicShard(
    topic_key=new_topic_key,
    topic_title=new_topic_title,
    subtopic_key=new_subtopic_key,
    subtopic_title=new_subtopic_title,
    source_page_start=current_page,
    source_page_end=current_page,
    status="open",  # Not finalized yet
    objectives=new_objectives,
    examples=new_examples,
    misconceptions=new_misconceptions,
    assessments=new_assessments,
    confidence=boundary_confidence
)

# Save new shard
save_shard(shard)
```

**Storage**: `s3://books/{book_id}/guidelines/topics/{topic_key}/subtopics/{subtopic_key}.latest.json`

---

### Step 3: Stability Detection

**Purpose**: Determine when subtopics are "done growing"
**Logic**: Subtopic is stable if no new pages added for 3+ consecutive pages

**Example**:

```
Pages processed: 1, 2, 3, 4, 5, 6, 7, 8
Subtopic "Data Handling": Pages 1-5

Processing Page 8:
- Last page for "Data Handling": 5
- Current page: 8
- Gap: 8 - 5 = 3 pages
- Status: STABLE ✅

Trigger: Generate teaching description + comprehensive description
```

**Why wait for stability?**
- Avoid regenerating descriptions on every page
- Ensure we have enough content for quality descriptions
- Optimize API costs (only generate once per subtopic)

---

### Step 4: Finalization (When Stable)

When a subtopic becomes stable, run these generation steps:

#### Step 4.1: Generate Evidence Summary

**Service**: `ReducerService` (rule-based, no AI)
**Purpose**: Quick summary of what was extracted

**Example**:
```
"Extracted 4 objectives, 8 examples, 2 misconceptions, and 5 assessments from pages 1-8"
```

---

#### Step 4.2: Generate Teaching Description

**Service**: `TeachingDescriptionGenerator`
**Purpose**: Concise 3-6 line teaching instructions
**Model**: gpt-4o-mini (400 tokens max)

**Prompt Template**: `/llm-backend/features/book_ingestion/prompts/teaching_description_generation.txt`

**Example Output**:
```
Start with concrete examples like counting objects using tally marks.
Progress to categorizing items by attributes (size, type, color).
Use hands-on activities where students physically sort and organize objects.
Emphasize the "why" - organizing data makes it easier to understand and compare.
Practice reading and creating simple tables and charts.
```

---

#### Step 4.3: Generate Comprehensive Description ✨

**Service**: `DescriptionGenerator`
**Purpose**: Comprehensive 200-300 word paragraph covering everything
**Model**: gpt-4o-mini (600 tokens max)

**Prompt Template**: `/llm-backend/features/book_ingestion/prompts/description_generation.txt`

**Covers**:
- WHAT the topic is (concepts, skills)
- HOW to teach it (teaching strategies, progression)
- HOW to assess it (assessment approaches)
- MISCONCEPTIONS to watch for

**Example Output**:
```
This subtopic introduces students to the fundamental concept of data handling through
hands-on organizing activities. Students learn to represent information using tally marks,
which are visual tools for counting and grouping data in sets of five. The chapter
progresses through various activities including measuring the length of words, comparing
animal names, and categorizing everyday objects like household items and hairstyles.

The pedagogical approach emphasizes concrete, relatable examples that connect to students'
daily experiences. Activities start with simple counting exercises using tally marks and
gradually introduce more complex categorization tasks. Students learn to organize objects
by multiple attributes (size, type, color, length) and understand that data organization
makes information easier to analyze and compare.

Assessment should focus on students' ability to create accurate tally marks in groups of
five, correctly categorize objects based on given criteria, and explain why organizing
data is useful. Watch for common misconceptions: students may not group tally marks
properly, struggle with categorizing objects that fit multiple categories, or fail to
see the practical value of data organization.

Teaching tip: Use physical objects for sorting activities before moving to paper-based
exercises. Encourage students to explain their categorization choices and discuss
alternative ways to group the same objects.
```

**Validation**: 150-350 words accepted, 200-300 target
**Retry Logic**: Up to 2 retries if validation fails

---

#### Step 4.4: Quality Validation

**Service**: `QualityValidationService`
**Purpose**: Validate guideline completeness and quality
**Model**: gpt-4o-mini (300 tokens max)

**Checks**:
- Are objectives clear and measurable?
- Are examples relevant and diverse?
- Are assessments properly leveled (basic, proficient, advanced)?
- Is the teaching description actionable?
- Is the comprehensive description comprehensive?

**Output**: Quality score (0.0-1.0)

```
Score ≥ 0.9: Excellent
Score ≥ 0.7: Good
Score ≥ 0.5: Acceptable
Score < 0.5: Needs Review
```

---

### Step 5: Save to S3

**Storage Structure**:

```
s3://books/
  └── {book_id}/
      ├── guidelines/
      │   ├── index.json                    # Metadata index
      │   └── topics/
      │       └── {topic_key}/
      │           └── subtopics/
      │               └── {subtopic_key}.latest.json  # Shard file
      └── pages/
          ├── 001.page.json                 # OCR extracted text
          ├── 001.page_guideline.json       # Page processing results
          └── ...
```

**Shard File Contents**:

```json
{
  "topic_key": "data-handling",
  "topic_title": "Data Handling",
  "subtopic_key": "organizing-information",
  "subtopic_title": "Organizing Information",
  "source_page_start": 1,
  "source_page_end": 8,
  "status": "final",
  "confidence": 0.85,
  "version": 1,
  "objectives": [...],
  "examples": [...],
  "misconceptions": [...],
  "assessments": [...],
  "evidence_summary": "Extracted 4 objectives, 8 examples, 2 misconceptions, and 5 assessments from pages 1-8",
  "teaching_description": "Start with concrete examples...",
  "description": "This subtopic introduces students to the fundamental concept...",
  "quality_score": 0.92
}
```

---

### Step 6: Database Sync (After User Approval)

**Service**: `DBSyncService`
**Trigger**: User clicks "Approve & Sync to DB" in admin UI

**Process**:

1. Load all finalized shards from S3
2. For each shard:
   - Check if guideline exists in DB (by topic_key + subtopic_key)
   - If exists: UPDATE
   - If not: INSERT
3. Sync all fields including new `description` field

**SQL Example**:

```sql
INSERT INTO teaching_guidelines (
    topic_key, subtopic_key, topic_title, subtopic_title,
    objectives_json, examples_json, misconceptions_json, assessments_json,
    teaching_description, description,
    source_page_start, source_page_end,
    evidence_summary, status, confidence, version, quality_score,
    book_id, source_pages, grade, subject
) VALUES (
    :topic_key, :subtopic_key, :topic_title, :subtopic_title,
    :objectives_json, :examples_json, :misconceptions_json, :assessments_json,
    :teaching_description, :description,
    :source_page_start, :source_page_end,
    :evidence_summary, :status, :confidence, :version, :quality_score,
    :book_id, :source_pages, :grade, :subject
)
ON CONFLICT (book_id, topic_key, subtopic_key)
DO UPDATE SET
    objectives_json = EXCLUDED.objectives_json,
    examples_json = EXCLUDED.examples_json,
    -- ... all fields ...
    description = EXCLUDED.description,
    updated_at = NOW()
```

---

## Context Window & Token Optimization

### The Token Explosion Problem

**Naive Approach (Without Optimization)**:

For a 100-page book:

```
Page 50 boundary decision needs:
- All previous 49 pages: 49 × 500 tokens = 24,500 tokens
- Cost per decision: ~$0.25
- Total for 100 pages: ~$25
```

This is **unsustainable**!

---

### Solution: Context Packing

**Optimized Approach**:

```
Page 50 boundary decision needs:
- Last 2 page summaries: 2 × 30 tokens = 60 tokens
- Open subtopics info: ~50 tokens
- Current page summary: ~30 tokens
- Prompt + guidelines: ~200 tokens
Total: ~340 tokens per decision
Cost per decision: ~$0.003
Total for 100 pages: ~$0.30
```

**Reduction: 98.8% cost savings!**

---

### What's Included in Context Pack

```python
class ContextPack(BaseModel):
    """Compact context for boundary detection"""

    book_id: str
    current_page: int
    book_metadata: Dict[str, Any]  # grade, subject, board

    # Recent page summaries (last 2 pages)
    recent_page_summaries: List[RecentPageSummary]
    # RecentPageSummary = { page: int, summary: str }

    # All open (unfinalalized) subtopics with evidence
    open_topics: List[OpenTopicInfo]
    # OpenTopicInfo contains:
    #   - topic_key, topic_title
    #   - open_subtopics: List[OpenSubtopicInfo]
    #     - subtopic_key, subtopic_title
    #     - page_start, page_end
    #     - evidence_summary (e.g., "Pages 1-7: 3 obj, 6 examples")

    # ToC hints (simplified for MVP)
    toc_hints: ToCHints
```

**File**: `/llm-backend/features/book_ingestion/models/guideline_models.py`

---

### Token Usage Breakdown

| Component | Tokens | Percentage |
|-----------|--------|------------|
| Recent page summaries (2 pages) | 60 | 17% |
| Open subtopics info | 50 | 15% |
| Current page summary | 30 | 9% |
| Prompt template | 150 | 44% |
| Guidelines (pedagogical principles) | 50 | 15% |
| **Total** | **340** | **100%** |

**Compared to naive approach**: 340 vs 24,500 = **98.6% reduction**

---

## Key Design Decisions

### 1. Page-by-Page Processing (Not Batch)

**Why?**
- Real-time feedback to user
- Can stop/resume at any time
- Easier debugging (can inspect each step)
- Scales to any book size

**Trade-off**: Can't use future pages for context

---

### 2. Hysteresis-Based Boundary Detection

**Why?**
- Prevents "boundary flapping" (oscillating decisions)
- Requires strong evidence to change state
- More stable subtopic boundaries

**Zones**:
- Strong Continue: ≥60% continue + <70% new
- Strong New: ≥75% new
- Ambiguous: Use best guess, mark low confidence

---

### 3. Stability-Based Finalization

**Why?**
- Avoid regenerating expensive descriptions on every page
- Ensure enough content for quality descriptions
- Optimize API costs

**Definition**: No new pages for 3+ consecutive pages

---

### 4. Shard-Based Storage (S3 JSON Files)

**Why?**
- Easy to merge/split subtopics
- Version control friendly (can diff JSON)
- Fast reads/writes
- Separates staging (S3) from production (DB)

**Structure**: One JSON file per subtopic

---

### 5. Two-Stage Approval (S3 → Database)

**Why?**
- Human review before production
- Can regenerate without affecting production
- Rollback capability (delete S3, keep DB)

**Workflow**: Generate → Review → Approve → Sync

---

### 6. Service-Oriented Architecture

**Why?**
- Single Responsibility Principle
- Easy to test each service independently
- Easy to replace/upgrade services (e.g., swap OpenAI for Claude)
- Clear separation of concerns

**Services**:
- `MinisummaryService`
- `BoundaryDetectionService`
- `FactsExtractionService`
- `ReducerService`
- `DescriptionGenerator`
- `QualityValidationService`
- `DBSyncService`
- `ContextPackService`

---

### 7. Pedagogical Prompt Engineering

**Why?**
- Standard prompts treat activities as topics
- Need explicit guidance: "Subtopic = Learning Objective"
- Curriculum awareness improves cohesion

**Key Additions**:
- Pedagogical principles section
- Explicit examples (categorizing items + hair = same subtopic)
- Bias towards continuation
- Target: 10-20 pages per subtopic

**File**: `/llm-backend/features/book_ingestion/prompts/boundary_detection.txt`

---

## Success Metrics

### Subtopic Granularity

**Target**: 0.10-0.20 subtopics per page

```
Good:
- 10 pages → 1-2 subtopics ✅
- 50 pages → 5-10 subtopics ✅

Bad:
- 8 pages → 5 subtopics ❌ (over-segmentation)
- 100 pages → 2 subtopics ❌ (under-segmentation)
```

---

### Boundary Decision Distribution

**Target**: 80% CONTINUE, 20% NEW

```
For typical textbook chapter (50 pages):
- CONTINUE decisions: ~40 (80%)
- NEW decisions: ~10 (20%)
- Result: ~10 subtopics

If you see 60% NEW decisions:
- Over-segmentation likely
- Review boundary detection prompt
```

---

### Quality Score Distribution

**Target**:
- 70%+ of subtopics with quality score ≥ 0.7
- 90%+ of subtopics with quality score ≥ 0.5

```
Quality Score Distribution:
  0.9-1.0 (Excellent):   40% ✅
  0.7-0.9 (Good):        35% ✅
  0.5-0.7 (Acceptable):  20% ⚠️
  0.0-0.5 (Needs Review): 5% ❌
```

---

### Token Efficiency

**Target**: <500 tokens per page processed

```
Per-Page Token Budget:
- Mini-summary: 150 tokens (input) + 50 tokens (output) = 200
- Boundary detection: 340 tokens (input) + 100 tokens (output) = 440
- Facts extraction: 600 tokens (input) + 200 tokens (output) = 800
- Finalization (stable pages only): ~1,500 tokens

Average per page (assuming 1 finalization per 10 pages):
  (200 + 440 + 800) × 10 + 1,500
  --------------------------------- = ~1,590 tokens/page
              10

Cost per page: ~$0.016 (at gpt-4o-mini pricing)
Cost per 100-page book: ~$1.60
```

**Actual results**: Typically 1,200-1,800 tokens per page ✅

---

### Processing Speed

**Target**: <10 seconds per page

```
Per-Page Processing Time:
- OCR extraction: ~2 seconds
- Mini-summary: ~1 second
- Boundary detection: ~1 second
- Facts extraction: ~2 seconds
- Shard update: ~0.5 seconds
- S3 save: ~0.5 seconds

Total: ~7 seconds per page ✅

For 100-page book: ~12 minutes
```

---

## Related Documentation

- [Boundary Detection Issue Analysis](./BOUNDARY_DETECTION_ISSUE_ANALYSIS.md)
- [Simplified Description Implementation](./SIMPLIFIED_DESCRIPTION_IMPLEMENTATION.md)
- [Admin Guidelines API](../ADMIN_GUIDELINES_API.md)

---

**Last Updated**: 2025-11-05
**Maintainer**: Development Team
