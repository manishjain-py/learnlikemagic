# Guidelines Extraction Audit: "What to Teach" vs "How to Teach"

## Problem Statement

The book ingestion pipeline should extract **what** to teach (topics, depth, scope, prerequisites, misconceptions) — not **how** to teach it (examples, exercises, teaching strategies). The "how" should be generated dynamically by the AI tutor, personalized to each kid's personality and learning style.

Currently, the pipeline extracts both, leaking the book's pedagogy into the tutor's behavior.

## The Data Flow

```
Book Pages (OCR)
  → chunk_topic_extraction.txt    (3-page windows → topics + guidelines)
  → topic_guidelines_merge.txt    (merge multi-chunk guidelines per topic)
  → chapter_consolidation.txt     (dedup, sequence, summarize)
  → teaching_guidelines table     (stored as guideline + metadata_json)
  → topic_adapter.py              (DB → TopicGuidelines model)
  → master_tutor_prompts.py       (injected as "Teaching Approach")
```

## What the Extraction Prompt Currently Asks For

**File:** `llm-backend/book_ingestion_v2/prompts/chunk_topic_extraction.txt:35-41`

```
GUIDELINES FORMAT:
Write practical teaching guidelines that include:
- What concepts/skills to teach              ← SCOPE (correct)
- Key examples from the pages                ← HOW  (wrong)
- Common misconceptions to address           ← SCOPE (correct)
- How to assess understanding                ← HOW  (wrong)
- Specific problems or exercises mentioned   ← HOW  (wrong)
```

3 of 5 bullets extract the book's pedagogy, not just its curriculum scope.

## What the Merge Prompt Reinforces

**File:** `llm-backend/book_ingestion_v2/prompts/topic_guidelines_merge.txt:7`

```
Organize logically: objectives → teaching strategies → examples → misconceptions → assessments
```

Explicitly preserves teaching strategies, examples, and assessments from the book.

## How It Reaches the Tutor

**File:** `llm-backend/tutor/services/topic_adapter.py:46,53-54`

```python
teaching_approach = "\n".join(guideline.metadata.scaffolding_strategies or [])
# fallback: raw guideline text (first 500 chars)
teaching_approach = guideline.guideline[:500]
```

**File:** `llm-backend/tutor/prompts/master_tutor_prompts.py:19-20`

```
### Teaching Approach
{teaching_approach}
```

The book's examples and methodology flow straight into the tutor's system prompt as its "teaching approach."

## Impact

| Consequence | Detail |
|---|---|
| Book's examples override AI creativity | Tutor uses "pizza fractions" because the book did, instead of using the kid's interests |
| Personalization is constrained | Kid personality data can't fully steer teaching style if the book's style is baked in |
| Assessment is prescriptive | Book's exercises are injected rather than letting AI generate level-appropriate questions |
| Guidelines bloat | Free-form text accumulates examples, exercises, page references — noise for the tutor |

## What Should Be Extracted (Scope Only)

| Extract | Don't Extract |
|---|---|
| Learning objectives for this grade level | Worked examples from the book |
| Depth required (conceptual / procedural / both) | Specific exercises or problem sets |
| Prerequisite concepts | Teaching strategies or scaffolding sequence |
| Common misconceptions to watch for | Assessment methods |
| Boundary: what's in-scope vs out-of-scope | Page-specific references |

## Files That Need Changes

| File | Change |
|---|---|
| `book_ingestion_v2/prompts/chunk_topic_extraction.txt` | Rewrite GUIDELINES FORMAT to scope-only |
| `book_ingestion_v2/prompts/topic_guidelines_merge.txt` | Remove teaching strategies/examples/assessments from org structure |
| `tutor/services/topic_adapter.py` | Adapt to new structured fields (no more free-form fallback) |
| `tutor/models/study_plan.py` | Update `TopicGuidelines` fields to match scope-only model |
| `shared/models/entities.py` | Update `metadata_json` schema if structured fields change |

## Desired Guideline Output (Example)

**Before (current):**
> Teach addition of unlike fractions. Start with pizza examples — show 1/2 pizza + 1/4 pizza visually. Walk through finding LCD. Common error: students add denominators. Practice: Page 42 problems 1-5. Assess by asking students to explain why 1/2 + 1/3 ≠ 2/5.

**After (scope-only):**
> **Objective:** Add fractions with unlike denominators (up to single-digit denominators). **Depth:** Conceptual understanding of LCD + procedural fluency. **Prerequisites:** Equivalent fractions, multiplication tables. **Misconceptions:** Adding numerators and denominators separately (e.g., 1/2 + 1/3 = 2/5). **Boundary:** Does not cover mixed numbers or denominators > 10.
