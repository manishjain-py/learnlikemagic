# Phase 6: LangGraph Guideline Extraction - Comprehensive Design Document

**Date:** October 26, 2025
**Status:** Design Phase - Pre-Implementation Analysis
**Estimated Complexity:** High
**Estimated Implementation Time:** 6-8 hours

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Core Design Challenges](#core-design-challenges)
3. [Architecture Options Analysis](#architecture-options-analysis)
4. [Selected Architecture](#selected-architecture)
5. [State Management Design](#state-management-design)
6. [Node-by-Node Design](#node-by-node-design)
7. [Prompt Engineering Strategy](#prompt-engineering-strategy)
8. [Error Handling & Validation](#error-handling--validation)
9. [Performance & Scalability](#performance--scalability)
10. [Integration Design](#integration-design)
11. [Testing Strategy](#testing-strategy)
12. [Open Questions & Decisions Needed](#open-questions--decisions-needed)

---

## 1. Executive Summary

### Goal
Build a LangGraph-based workflow that automatically extracts structured teaching guidelines from uploaded textbook pages, transforming raw OCR text into pedagogically sound, AI-tutor-ready teaching materials.

### Input
- Book metadata (title, author, board, grade, subject)
- 20-200 approved pages with OCR text
- Each page: 500-2000 tokens
- Total: 10k-400k tokens

### Output
```json
{
  "book_id": "ncert_math_3_2024",
  "book_metadata": {...},
  "topics": [
    {
      "topic": "Fractions",
      "subtopics": [
        {
          "subtopic": "Comparing Like Denominators",
          "guideline": "Detailed teaching instructions...",
          "metadata": {
            "learning_objectives": [...],
            "prerequisites": [...],
            "common_misconceptions": [...],
            "scaffolding_strategies": [...],
            "assessment_criteria": {...}
          },
          "source_pages": [15, 16, 17]
        }
      ]
    }
  ]
}
```

### Success Criteria
1. **Accuracy**: Topics/subtopics match actual book content (no hallucinations)
2. **Granularity**: Subtopics are appropriately sized (not too broad/narrow)
3. **Pedagogical Quality**: Guidelines are actionable and age-appropriate
4. **Completeness**: All book content is covered
5. **Performance**: Processing completes in < 10 minutes for 50-page book
6. **Cost**: Token usage < $1 per book (using gpt-4o-mini)

---

## 2. Core Design Challenges

### Challenge 2.1: Context Window Limitations

**Problem**: Cannot fit entire textbook in single LLM call
- 50-page book ≈ 50k-100k tokens
- GPT-4 context window: 128k tokens (but expensive)
- Need multiple passes with chunking

**Implications**:
- Must process incrementally
- Need strategy to maintain context across chunks
- Risk of losing global coherence

**Solution Approaches**:
1. **Hierarchical Processing**: Extract high-level structure first (topics), then details (subtopics)
2. **Rolling Context Window**: Pass summary of previous N pages to next chunk
3. **Two-Pass Strategy**: First pass for structure, second pass for enrichment

**Decision**: Use **hierarchical + two-pass hybrid**
- Pass 1: Analyze all pages to extract topic structure
- Pass 2: Process pages incrementally to extract subtopics with context
- Pass 3: Enrich each subtopic with detailed metadata

---

### Challenge 2.2: Topic Boundary Detection

**Problem**: How to identify where topics and subtopics begin/end?

**Complicating Factors**:
- OCR might miss headers or formatting
- Some books have clear "Chapter 1, Chapter 2" markers
- Others have fluid transitions
- Subtopics often span multiple pages

**Example**:
```
Page 15: "Comparing Fractions" (header + intro)
Page 16: Examples of comparing fractions (continuation)
Page 17: Practice problems (continuation) + "Adding Fractions" (new subtopic starts)
```

**Detection Strategies**:
1. **Header-based**: Look for "Chapter", "Section", numbered headers
2. **Semantic shift**: Detect topic changes via embedding similarity
3. **Contextual LLM**: Ask LLM "is this a new topic or continuation?"

**Decision**: **Contextual LLM with header hints**
- Include previous page summary in prompt
- Ask LLM to explicitly detect new vs continuation
- Use header text as strong signal when available

---

### Challenge 2.3: Subtopic Granularity Control

**Problem**: What is the right level of granularity for subtopics?

**Too Coarse** (entire chapter):
```
Topic: "Fractions"
Subtopic: "Fractions"
❌ Not useful - too broad
```

**Too Fine** (individual examples):
```
Topic: "Fractions"
Subtopic: "Comparing 3/8 and 5/8"
Subtopic: "Comparing 1/4 and 3/4"
❌ Too granular - should be one subtopic
```

**Just Right** (conceptual skill):
```
Topic: "Fractions"
Subtopic: "Comparing fractions with like denominators"
✅ Appropriate granularity
```

**Control Mechanisms**:
1. **Explicit Guidelines in Prompt**: "A subtopic should represent a single teachable skill or concept"
2. **Examples**: Provide 2-3 examples of good subtopic names
3. **Validation**: Check subtopic count (3-8 per topic is reasonable)
4. **Post-Processing**: Merge if too many, split if too few

**Decision**: **Prompt engineering + validation + manual review**

---

### Challenge 2.4: State Management Complexity

**Problem**: State must accumulate information across multiple nodes

**State Requirements**:
- Track current processing position (which page)
- Accumulate topics as they're discovered
- Maintain context from previous pages
- Handle overlapping subtopics
- Support error recovery and retries

**LangGraph State Options**:
1. **Simple TypedDict**: Easy but no helper functions
2. **TypedDict with Annotated fields**: Can use `operator.add` for accumulation
3. **Custom State Class**: More control but more complex

**Key Question**: How to handle accumulation of topics/subtopics?
- Option A: Replace entire list each time (risk of data loss)
- Option B: Append-only using `Annotated[List[T], add]` (safer)
- Option C: Merge updates intelligently (complex but flexible)

**Decision**: **Annotated TypedDict with append semantics**
```python
from typing import Annotated
from operator import add

class GuidelineState(TypedDict):
    topics: Annotated[List[TopicData], add]  # Append-only
    ...
```

---

### Challenge 2.5: Incremental Processing with Memory

**Problem**: Processing page-by-page requires carrying context forward

**What Context to Carry**:
1. Current subtopic name and when it started
2. Current topic name
3. Key concepts mentioned so far in current subtopic
4. Summary of last 1-2 pages

**Context Size Management**:
- Cannot keep growing indefinitely
- Need to summarize/compress as we go
- Balance: enough context vs token limits

**Design**:
```python
context_from_previous_page = {
    "current_topic": "Fractions",
    "current_subtopic": "Comparing Like Denominators",
    "subtopic_started_on_page": 15,
    "key_concepts_so_far": ["numerator", "denominator", "comparison"],
    "last_page_summary": "Page 16 showed visual examples..."
}
```

**Decision**: **Structured context object with auto-summarization**

---

## 3. Architecture Options Analysis

### Option A: Sequential Pipeline (Simple)

```
extract_topics
  ↓
extract_all_subtopics_at_once
  ↓
enrich_all_subtopics_at_once
  ↓
synthesize_final_json
```

**Pros**:
- Simple, linear flow
- Easy to understand and debug
- Clear separation of concerns

**Cons**:
- Less granular control
- Harder to track incremental progress
- All-or-nothing processing

**Token Usage**: ~3 full passes through book = 3× book size in tokens

---

### Option B: Nested Loop Architecture (Granular)

```
extract_topics
  ↓
for each topic:
  extract_subtopics_for_this_topic
    ↓
  for each subtopic:
    extract_objectives
      ↓
    extract_misconceptions
      ↓
    extract_assessment
      ↓
    generate_guideline
  ↓
synthesize_final_json
```

**Pros**:
- Very granular control
- Can retry individual steps
- Process subtopic completely before moving on

**Cons**:
- Complex state management
- Many LLM calls (expensive)
- LangGraph doesn't naturally support nested loops

**Token Usage**: Could be higher due to repeated context loading

---

### Option C: Hybrid Two-Phase (Selected ✅)

**Phase 1: Structure Extraction**
```
extract_topics (analyze all pages → identify 3-10 main topics)
  ↓
extract_subtopics_incrementally (process pages sequentially → build subtopic list)
```

**Phase 2: Content Enrichment**
```
enrich_subtopics_parallel (for each subtopic → extract all metadata)
  ↓
generate_guidelines (for each subtopic → synthesize teaching guide)
  ↓
synthesize_final_json (assemble complete guideline.json)
```

**Pros**:
- Good balance of structure and detail
- Two-pass minimizes token usage
- Can parallelize enrichment phase
- Clear checkpoints for debugging

**Cons**:
- More complex than Option A
- Still need careful state management

**Token Usage**: ~2 passes + per-subtopic enrichment = reasonable

**Decision**: ✅ **Selected - Best balance of quality and efficiency**

---

## 4. Selected Architecture

### Graph Visualization

```
                   START
                     ↓
         ┌─────────────────────┐
         │  extract_topics     │  ← Analyze all pages
         │  Output: ["Topic1", │    Identify 3-10 main topics
         │   "Topic2", ...]    │
         └──────────┬──────────┘
                    ↓
         ┌─────────────────────┐
         │ extract_subtopics   │  ← Process pages incrementally
         │ _incrementally      │    Build subtopic list with page ranges
         │  Loop: page 1 → N   │    Maintain context between pages
         └──────────┬──────────┘
                    ↓
         ┌─────────────────────┐
         │ enrich_subtopics    │  ← For each subtopic:
         │  For each subtopic: │    - Extract objectives
         │   - objectives      │    - Identify misconceptions
         │   - misconceptions  │    - Define assessment criteria
         │   - assessment      │
         └──────────┬──────────┘
                    ↓
         ┌─────────────────────┐
         │ generate_guidelines │  ← For each subtopic:
         │  For each subtopic: │    Synthesize comprehensive
         │   Synthesize text   │    teaching guideline
         └──────────┬──────────┘
                    ↓
         ┌─────────────────────┐
         │ synthesize_final    │  ← Assemble guideline.json
         │   Validate & save   │    Validate structure
         └──────────┬──────────┘
                    ↓
                   END
```

### Node Responsibilities

| Node | Input | Processing | Output |
|------|-------|------------|--------|
| **extract_topics** | All page texts | LLM analyzes full book, identifies chapters/topics | List of topic names |
| **extract_subtopics_incrementally** | Pages + context | Loop: For each page, detect new/continuing subtopic | List of subtopics with page ranges |
| **enrich_subtopics** | Subtopics + page texts | For each subtopic: LLM extracts objectives, misconceptions, assessment | Enriched subtopic metadata |
| **generate_guidelines** | Enriched subtopics | For each subtopic: LLM synthesizes teaching guideline | Complete subtopic guidelines |
| **synthesize_final** | All topics + subtopics | Assemble into guideline.json structure | Final guideline.json |

---

## 5. State Management Design

### State Schema

```python
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from operator import add

class PageData(TypedDict):
    page_num: int
    text: str

class SubtopicMetadata(TypedDict):
    learning_objectives: List[str]
    depth_level: str
    prerequisites: List[str]
    common_misconceptions: List[str]
    scaffolding_strategies: List[str]
    assessment_criteria: Dict[str, str]

class SubtopicData(TypedDict):
    subtopic: str
    topic: str  # Parent topic
    source_pages: List[int]
    page_range_start: int
    page_range_end: int
    guideline: Optional[str]  # Filled in later
    metadata: Optional[SubtopicMetadata]  # Filled in later

class TopicData(TypedDict):
    topic: str
    subtopics: List[SubtopicData]

class GuidelineState(TypedDict):
    # ===== Inputs (Immutable) =====
    book_id: str
    book_metadata: Dict[str, Any]
    pages: List[PageData]

    # ===== Processing State (Mutable) =====
    current_page_idx: int
    current_topic: Optional[str]
    current_subtopic: Optional[str]
    context_from_previous_page: str

    # ===== Accumulated Data (Append-only) =====
    topic_names: List[str]  # Just names from extract_topics
    subtopics: Annotated[List[SubtopicData], add]  # Growing list

    # ===== Final Output =====
    guideline_json: Optional[Dict[str, Any]]

    # ===== Error Tracking =====
    error: Optional[str]
    error_node: Optional[str]
    warnings: Annotated[List[str], add]
```

### State Evolution Example

**After extract_topics**:
```python
{
    "topic_names": ["Fractions", "Multiplication", "Division"],
    "subtopics": [],
    ...
}
```

**After extract_subtopics_incrementally** (page 17):
```python
{
    "topic_names": ["Fractions", "Multiplication", "Division"],
    "current_page_idx": 17,
    "current_topic": "Fractions",
    "current_subtopic": "Comparing Like Denominators",
    "context_from_previous_page": "Page 16 showed examples of...",
    "subtopics": [
        {
            "subtopic": "Understanding Fractions",
            "topic": "Fractions",
            "source_pages": [12, 13, 14],
            "page_range_start": 12,
            "page_range_end": 14,
            "guideline": None,
            "metadata": None
        },
        {
            "subtopic": "Comparing Like Denominators",
            "topic": "Fractions",
            "source_pages": [15, 16, 17],
            "page_range_start": 15,
            "page_range_end": 17,  # Still in progress
            "guideline": None,
            "metadata": None
        }
    ],
    ...
}
```

**After enrich_subtopics**:
```python
{
    "subtopics": [
        {
            "subtopic": "Comparing Like Denominators",
            "topic": "Fractions",
            "source_pages": [15, 16, 17],
            "page_range_start": 15,
            "page_range_end": 17,
            "guideline": None,
            "metadata": {  # ← Filled in
                "learning_objectives": [
                    "Compare fractions with like denominators",
                    "Identify which fraction is larger"
                ],
                "prerequisites": ["Understanding numerator and denominator"],
                "common_misconceptions": ["Students may compare only numerators"],
                ...
            }
        }
    ],
    ...
}
```

---

## 6. Node-by-Node Design

### Node 1: `extract_topics`

**Purpose**: Analyze entire book to identify main topics/chapters

**Input**:
- `state.pages`: All page texts
- `state.book_metadata`: Grade, subject, etc.

**Processing**:
1. Concatenate all page texts (with page separators)
2. Send to LLM with prompt: "Identify the main topics/chapters in this textbook"
3. Parse response into list of topic names

**Output**:
- `state.topic_names`: ["Fractions", "Multiplication", ...]

**Prompt Strategy**:
```
You are analyzing a grade {grade} {subject} textbook.

Read through all {num_pages} pages and identify the main topics or chapters.

Tips:
- Look for chapter headings or major section titles
- Typical textbooks have 3-10 main topics
- Topics should be broad concepts (e.g., "Fractions", "Geometry")

Return JSON: {"topics": ["Topic 1", "Topic 2", ...]}
```

**Validation**:
- Check 3-15 topics (reasonable range)
- Each topic name is non-empty string
- No duplicates

**Error Handling**:
- If < 3 topics: warning (might be too coarse)
- If > 15 topics: error (likely extraction error)
- If invalid JSON: retry once with schema example

**Token Estimation**:
- Input: Full book (~50k tokens for 50-page book)
- Output: ~100 tokens
- Total: ~50k tokens per call
- Cost: ~$0.01 per book (gpt-4o-mini)

---

### Node 2: `extract_subtopics_incrementally`

**Purpose**: Process pages sequentially to extract subtopics with boundaries

**Input**:
- `state.pages`: All pages
- `state.topic_names`: Topics from previous node
- `state.context_from_previous_page`: Summary (initially empty)

**Processing**:
```python
for page_idx, page in enumerate(state.pages):
    # Build prompt with context
    prompt = build_subtopic_prompt(
        page_text=page.text,
        page_num=page.page_num,
        previous_context=state.context_from_previous_page,
        identified_topics=state.topic_names
    )

    # Call LLM
    response = llm.invoke(prompt)

    # Parse response
    result = parse_json(response)

    # Update state based on response
    if result["is_continuation"]:
        # Update existing subtopic's end page
        update_current_subtopic_end(state, page.page_num)
    else:
        # Start new subtopic
        create_new_subtopic(state, result)

    # Update context for next page
    state.context_from_previous_page = result["context_summary"]
```

**Output**:
- `state.subtopics`: Growing list of subtopics with page ranges

**Prompt Strategy**:
```
CONTEXT FROM PREVIOUS PAGE:
{previous_context}

CURRENT PAGE (Page {page_num}):
{page_text}

IDENTIFIED TOPICS: {topics}

Determine:
1. Is this page a continuation of the previous subtopic? (true/false)
2. If new subtopic, what is its name?
3. Which main topic does this belong to?

Return JSON:
{
  "is_continuation": true/false,
  "topic": "Fractions",  // If new subtopic
  "subtopic": "Comparing Like Denominators",  // If new
  "key_concepts": ["numerator", "denominator"],
  "context_summary": "Brief summary for next page"
}
```

**Validation**:
- Subtopic name is non-empty
- Topic matches one from topic_names
- Context summary is reasonable length (< 500 chars)

**Error Handling**:
- Invalid JSON: retry with schema
- Topic mismatch: use closest match or add warning
- Missing fields: use defaults

**Token Estimation**:
- Per page: ~1k tokens (page) + 500 (context) + 100 (output) = ~1.6k tokens
- 50 pages: ~80k tokens total
- Cost: ~$0.02 per book

---

### Node 3: `enrich_subtopics`

**Purpose**: Extract detailed pedagogical metadata for each subtopic

**Input**:
- `state.subtopics`: List of subtopics with page ranges
- `state.pages`: To get text for relevant pages

**Processing**:
```python
for subtopic in state.subtopics:
    # Get text from all pages in this subtopic
    subtopic_text = get_pages_text(
        state.pages,
        subtopic.source_pages
    )

    # Extract objectives
    objectives = extract_learning_objectives(
        topic=subtopic.topic,
        subtopic=subtopic.subtopic,
        content=subtopic_text,
        grade=state.book_metadata.grade
    )

    # Extract misconceptions
    misconceptions = extract_misconceptions(
        topic=subtopic.topic,
        subtopic=subtopic.subtopic,
        content=subtopic_text
    )

    # Extract assessment criteria
    assessment = extract_assessment(
        topic=subtopic.topic,
        subtopic=subtopic.subtopic,
        content=subtopic_text,
        objectives=objectives
    )

    # Update subtopic metadata
    subtopic.metadata = {
        "learning_objectives": objectives.learning_objectives,
        "depth_level": objectives.depth_level,
        "prerequisites": objectives.prerequisites,
        "common_misconceptions": misconceptions.misconceptions,
        "scaffolding_strategies": misconceptions.scaffolding,
        "assessment_criteria": assessment.criteria
    }
```

**Alternative**: Combine all three extractions into single LLM call
- Pros: Fewer calls, shared context
- Cons: Longer prompt, risk of incomplete responses

**Decision**: **Single combined call for efficiency**

**Combined Prompt**:
```
Extract pedagogical metadata for this subtopic:

TOPIC: {topic}
SUBTOPIC: {subtopic}
GRADE: {grade}

CONTENT:
{subtopic_text}

Extract:
1. Learning objectives (3-5 clear, measurable objectives)
2. Prerequisites (what students need to know first)
3. Common misconceptions (2-4 typical errors)
4. Scaffolding strategies (how to teach correctly)
5. Assessment criteria (mastery/proficient/developing levels)

Return JSON: {
  "learning_objectives": [...],
  "depth_level": "basic/intermediate/advanced",
  "prerequisites": [...],
  "common_misconceptions": [...],
  "scaffolding_strategies": [...],
  "assessment_criteria": {
    "mastery": "...",
    "proficient": "...",
    "developing": "..."
  }
}
```

**Validation**:
- 2-8 learning objectives
- Each objective is non-empty, starts with action verb
- Assessment criteria has all three levels
- Misconceptions are concrete (not vague)

**Token Estimation**:
- Per subtopic: ~3k tokens (content) + 1k (prompt) + 500 (output) = ~4.5k tokens
- 20 subtopics: ~90k tokens
- Cost: ~$0.02 per book

---

### Node 4: `generate_guidelines`

**Purpose**: Synthesize comprehensive teaching guideline for each subtopic

**Input**:
- `state.subtopics`: With complete metadata

**Processing**:
```python
for subtopic in state.subtopics:
    # Get pages text
    content = get_pages_text(state.pages, subtopic.source_pages)

    # Generate guideline
    guideline_text = synthesize_guideline(
        topic=subtopic.topic,
        subtopic=subtopic.subtopic,
        content=content,
        metadata=subtopic.metadata,
        grade=state.book_metadata.grade
    )

    # Update subtopic
    subtopic.guideline = guideline_text
```

**Prompt Strategy**:
```
Create a comprehensive teaching guideline for:

TOPIC: {topic}
SUBTOPIC: {subtopic}
GRADE: {grade}

EXTRACTED METADATA:
- Objectives: {objectives}
- Prerequisites: {prerequisites}
- Misconceptions: {misconceptions}
- Scaffolding: {scaffolding}
- Assessment: {assessment}

TEXTBOOK CONTENT:
{content}

Write a step-by-step teaching guideline (3-5 paragraphs) that:
1. Introduces the concept building on prerequisites
2. Explains how to teach clearly
3. Addresses common misconceptions
4. Suggests scaffolding strategies
5. Describes how to assess mastery

Make it actionable for an AI tutor or teacher.

Return JSON: {"guideline": "Your comprehensive text here..."}
```

**Validation**:
- Guideline is 200-1500 words
- Mentions key concepts from objectives
- References misconceptions
- Includes assessment approach

**Token Estimation**:
- Per subtopic: ~4k tokens (input) + 1k (output) = ~5k tokens
- 20 subtopics: ~100k tokens
- Cost: ~$0.025 per book

---

### Node 5: `synthesize_final`

**Purpose**: Assemble complete guideline.json structure

**Input**:
- `state.book_metadata`
- `state.topic_names`
- `state.subtopics`: Fully enriched

**Processing**:
```python
# Group subtopics by topic
topics_with_subtopics = []
for topic_name in state.topic_names:
    subtopics_for_topic = [
        s for s in state.subtopics
        if s.topic == topic_name
    ]

    topics_with_subtopics.append({
        "topic": topic_name,
        "subtopics": [
            {
                "subtopic": s.subtopic,
                "guideline": s.guideline,
                "metadata": s.metadata,
                "source_pages": s.source_pages
            }
            for s in subtopics_for_topic
        ]
    })

# Assemble final structure
guideline_json = {
    "book_id": state.book_id,
    "book_metadata": state.book_metadata,
    "topics": topics_with_subtopics
}

# Validate
validate_guideline_json(guideline_json)

state.guideline_json = guideline_json
```

**Validation**:
- All topics have at least one subtopic
- All subtopics have non-empty guideline
- All source_pages reference valid page numbers
- Total subtopics: 10-50 (reasonable for textbook)

**Output**: Complete `guideline.json` ready for S3 storage

---

## 7. Prompt Engineering Strategy

### Principle 1: Explicit Structure

**Bad Prompt** (vague):
```
Tell me about the topics in this book.
```

**Good Prompt** (explicit):
```
Analyze this grade 3 mathematics textbook and identify the main topics.

Requirements:
- Return 3-10 main topics
- Use clear, concise topic names
- Topics should be broad (e.g., "Fractions", not "Adding 1/4 and 1/4")

Return JSON: {"topics": ["Topic 1", "Topic 2", ...]}
```

### Principle 2: Grounding in Source Material

**Bad Prompt** (allows hallucination):
```
What are common misconceptions for fractions?
```

**Good Prompt** (grounded):
```
Based on the textbook content below, identify common misconceptions that
students might have when learning this subtopic.

TEXTBOOK CONTENT:
{content}

Return JSON: {"common_misconceptions": [...]}
```

### Principle 3: Pedagogical Framing

**Bad Prompt** (generic):
```
Summarize this content.
```

**Good Prompt** (pedagogical):
```
You are an expert educator for grade {grade} students.

Create learning objectives that are:
- Clear and measurable
- Age-appropriate for grade {grade}
- Based on Bloom's taxonomy
- Actionable for teachers

Content: {content}
```

### Principle 4: JSON Mode + Schema Validation

**Implementation**:
```python
from openai import OpenAI
from pydantic import BaseModel

class TopicsResponse(BaseModel):
    topics: List[str]

client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
    response_format={"type": "json_object"},  # ← JSON mode
)

# Validate with Pydantic
result = TopicsResponse.model_validate_json(response.choices[0].message.content)
```

### Principle 5: Examples in Prompts

**For subtopic extraction**:
```
Example of good subtopic granularity:
- "Comparing fractions with like denominators" ✅
- "Understanding the numerator" ✅
- "Comparing 3/8 and 5/8" ❌ (too specific)
- "Fractions" ❌ (too broad)
```

---

## 8. Error Handling & Validation

### Validation Layers

**Layer 1: Schema Validation** (Pydantic)
```python
from pydantic import BaseModel, Field, validator

class LearningObjectivesResponse(BaseModel):
    learning_objectives: List[str] = Field(..., min_items=2, max_items=8)
    depth_level: str = Field(..., pattern="^(basic|intermediate|advanced)$")
    prerequisites: List[str]

    @validator('learning_objectives')
    def validate_objectives(cls, v):
        for obj in v:
            if len(obj) < 10:
                raise ValueError("Objective too short")
            if not any(verb in obj.lower() for verb in ['explain', 'identify', 'compare', 'solve', 'create']):
                raise ValueError("Objective should start with action verb")
        return v
```

**Layer 2: Content Validation**
```python
def validate_subtopic(subtopic: SubtopicData, pages: List[PageData]):
    # Check page references
    for page_num in subtopic.source_pages:
        if not any(p.page_num == page_num for p in pages):
            raise ValueError(f"Invalid page reference: {page_num}")

    # Check guideline length
    if subtopic.guideline and len(subtopic.guideline.split()) < 100:
        raise ValueError("Guideline too short (< 100 words)")

    # Check metadata completeness
    if subtopic.metadata:
        if len(subtopic.metadata.learning_objectives) < 2:
            raise ValueError("Need at least 2 learning objectives")
```

**Layer 3: Semantic Validation**
```python
def validate_guideline_quality(guideline: str, objectives: List[str]):
    # Check if guideline mentions key objectives
    mentioned = sum(1 for obj in objectives if any(word in guideline.lower() for word in obj.lower().split()))

    if mentioned < len(objectives) * 0.5:
        return Warning("Guideline doesn't reference most objectives")

    return None
```

### Error Recovery Strategies

| Error Type | Strategy |
|------------|----------|
| **Invalid JSON** | Retry with schema example in prompt |
| **Missing fields** | Use default values or prompt for specific field |
| **Hallucinated topics** | Validate against page content, re-extract |
| **LLM API failure** | Exponential backoff retry (3 attempts) |
| **Token limit exceeded** | Chunk content, process in parts |
| **Poor quality output** | Log warning, flag for manual review |

### Retry Logic

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def call_llm_with_retry(prompt: str) -> dict:
    response = llm.invoke(prompt)

    try:
        result = json.loads(response.content)
        validate_schema(result)
        return result
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(f"LLM output validation failed: {e}")
        raise  # Will trigger retry
```

### Checkpointing Strategy

**Problem**: If graph fails after 30 minutes of processing, lose all work

**Solution**: Save intermediate state to S3
```python
def save_checkpoint(state: GuidelineState, node_name: str):
    checkpoint_key = f"books/{state.book_id}/checkpoints/{node_name}.json"
    s3_client.upload_json(checkpoint_key, {
        "node": node_name,
        "timestamp": datetime.utcnow().isoformat(),
        "state": state
    })

def load_checkpoint(book_id: str, node_name: str) -> Optional[GuidelineState]:
    checkpoint_key = f"books/{book_id}/checkpoints/{node_name}.json"
    return s3_client.download_json(checkpoint_key)
```

---

## 9. Performance & Scalability

### Token Usage Analysis

| Node | Tokens per Call | Calls | Total Tokens |
|------|----------------|-------|--------------|
| extract_topics | 50k | 1 | 50k |
| extract_subtopics (per page) | 1.6k | 50 | 80k |
| enrich_subtopics (per subtopic) | 4.5k | 20 | 90k |
| generate_guidelines (per subtopic) | 5k | 20 | 100k |
| synthesize_final | 5k | 1 | 5k |
| **TOTAL** | | | **~325k tokens** |

**Cost Estimate** (gpt-4o-mini):
- Input: ~$0.15 per 1M tokens
- Output: ~$0.60 per 1M tokens
- Total: ~$0.10-0.15 per book

### Time Estimation

| Node | LLM Calls | Seconds per Call | Total Time |
|------|-----------|------------------|------------|
| extract_topics | 1 | 10s | 10s |
| extract_subtopics | 50 | 3s | 150s (2.5 min) |
| enrich_subtopics | 20 | 8s | 160s (2.7 min) |
| generate_guidelines | 20 | 8s | 160s (2.7 min) |
| synthesize_final | 1 | 5s | 5s |
| **TOTAL** | | | **~8 minutes** |

### Optimization Strategies

**Strategy 1: Batch Processing**
- Enrich multiple subtopics in parallel
- Use async/await for concurrent LLM calls
- Reduce from 8 min to ~4 min

**Strategy 2: Caching**
- Cache LLM responses (same input = same output)
- Useful for retries and regeneration

**Strategy 3: Model Selection**
- Use gpt-4o-mini for most tasks (cheap, fast)
- Use gpt-4o only for complex synthesis if needed

**Strategy 4: Progressive Processing**
- Start generating guidelines while still extracting subtopics
- Stream results back to user

---

## 10. Integration Design

### 10.1 Integration with Book Service

**Trigger Point**: Admin clicks "Generate Guidelines" button

**Flow**:
```python
# In BookService
def trigger_guideline_generation(book_id: str) -> str:
    # 1. Validate book status
    book = self.repository.get_by_id(book_id)
    if book.status != "pages_complete":
        raise ValueError("Book must be in pages_complete status")

    # 2. Update status
    self.repository.update_status(book_id, "generating_guidelines")

    # 3. Create book_guideline record
    guideline = BookGuideline(
        id=f"{book_id}_guideline_v1",
        book_id=book_id,
        guideline_s3_key=f"books/{book_id}/guideline.json",
        status="draft",
        version=1
    )
    guideline_repo.create(guideline)

    # 4. Start async task
    task_id = start_guideline_generation_task(book_id)

    return task_id
```

**Async Task** (using background worker or celery):
```python
def guideline_generation_task(book_id: str):
    try:
        # 1. Load book and pages
        book = load_book_from_db(book_id)
        pages = load_pages_from_s3(book_id)

        # 2. Run LangGraph workflow
        result = run_guideline_extraction_graph(book, pages)

        # 3. Save guideline.json to S3
        save_guideline_to_s3(book_id, result.guideline_json)

        # 4. Update status
        update_book_status(book_id, "guidelines_pending_review")
        update_guideline_status(book_id, "pending_review")

        logger.info(f"Guideline generation complete for {book_id}")

    except Exception as e:
        logger.error(f"Guideline generation failed for {book_id}: {e}")
        update_book_status(book_id, "pages_complete")  # Reset
        update_guideline_status(book_id, "draft")
        raise
```

### 10.2 Integration with Teaching Guidelines Table

**Trigger Point**: Admin approves guideline

**Flow**:
```python
def approve_guideline(book_id: str, reviewed_by: str) -> int:
    # 1. Load guideline.json from S3
    guideline_json = s3_client.download_json(f"books/{book_id}/guideline.json")

    # 2. Validate structure
    validate_guideline_json(guideline_json)

    # 3. Get book metadata
    book = book_repo.get_by_id(book_id)

    # 4. Parse and create teaching_guideline rows
    count = 0
    for topic in guideline_json["topics"]:
        for subtopic_data in topic["subtopics"]:
            teaching_guideline = TeachingGuideline(
                id=generate_uuid(),
                country=book.country,
                board=book.board,
                grade=book.grade,
                subject=book.subject,
                topic=topic["topic"],
                subtopic=subtopic_data["subtopic"],
                guideline=subtopic_data["guideline"],
                metadata_json=json.dumps(subtopic_data["metadata"]),
                book_id=book_id,
                source_pages=json.dumps(subtopic_data["source_pages"]),
                created_at=datetime.utcnow()
            )
            teaching_guideline_repo.create(teaching_guideline)
            count += 1

    # 5. Update book and guideline status
    book_repo.update_status(book_id, "approved")
    book_guideline_repo.update_status(book_id, "approved", reviewed_by)

    logger.info(f"Created {count} teaching guidelines from book {book_id}")
    return count
```

### 10.3 API Endpoints

```python
# POST /admin/books/{book_id}/generate-guidelines
@router.post("/{book_id}/generate-guidelines")
async def generate_guidelines(book_id: str, background_tasks: BackgroundTasks):
    book_service = BookService(db)

    # Validate
    book = book_service.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if book.status != "pages_complete":
        raise HTTPException(400, f"Book must be in pages_complete status, currently {book.status}")

    # Start background task
    background_tasks.add_task(guideline_generation_task, book_id)

    # Update status immediately
    book_service.update_book_status(book_id, "generating_guidelines")

    return {
        "message": "Guideline generation started",
        "book_id": book_id,
        "estimated_time_minutes": 5
    }

# GET /admin/books/{book_id}/guidelines
@router.get("/{book_id}/guidelines")
async def get_guidelines(book_id: str):
    # Load from S3
    guideline_json = s3_client.download_json(f"books/{book_id}/guideline.json")

    # Get status
    guideline = book_guideline_repo.get_by_book_id(book_id)

    return {
        "book_id": book_id,
        "status": guideline.status if guideline else "not_generated",
        "guideline": guideline_json,
        "generated_at": guideline.generated_at if guideline else None
    }

# PUT /admin/books/{book_id}/guidelines/approve
@router.put("/{book_id}/guidelines/approve")
async def approve_guidelines(book_id: str, reviewed_by: str = "admin"):
    guideline_service = GuidelineService(db)
    count = guideline_service.approve_guideline(book_id, reviewed_by)

    return {
        "message": "Guideline approved and populated to teaching_guidelines",
        "teaching_guidelines_created": count
    }

# PUT /admin/books/{book_id}/guidelines/reject
@router.put("/{book_id}/guidelines/reject")
async def reject_guidelines(book_id: str, request: GuidelineRejectRequest):
    # Update status
    book_guideline_repo.update_status(book_id, "rejected")
    book_repo.update_status(book_id, "pages_complete")  # Allow retry

    # Log reason
    logger.info(f"Guideline rejected for {book_id}: {request.reason}")

    return {
        "message": "Guideline rejected, can be regenerated",
        "reason": request.reason
    }
```

---

## 11. Testing Strategy

### Unit Tests

**Test 1: State Management**
```python
def test_state_accumulation():
    state = GuidelineState(
        topics=[],
        subtopics=[],
        ...
    )

    # Simulate node adding subtopic
    new_subtopic = SubtopicData(...)
    state["subtopics"].append(new_subtopic)

    assert len(state["subtopics"]) == 1
```

**Test 2: Node Logic (Mocked LLM)**
```python
@patch('openai.Client.chat.completions.create')
def test_extract_topics_node(mock_llm):
    mock_llm.return_value.choices[0].message.content = '{"topics": ["Fractions", "Multiplication"]}'

    state = {
        "pages": [{"page_num": 1, "text": "Chapter 1: Fractions..."}],
        "book_metadata": {"grade": 3, "subject": "Math"}
    }

    result = extract_topics_node(state)

    assert result["topic_names"] == ["Fractions", "Multiplication"]
```

**Test 3: Validation**
```python
def test_validate_guideline_json():
    valid_json = {
        "book_id": "test_book",
        "book_metadata": {...},
        "topics": [
            {
                "topic": "Fractions",
                "subtopics": [
                    {
                        "subtopic": "Comparing",
                        "guideline": "...",
                        "metadata": {...},
                        "source_pages": [1, 2]
                    }
                ]
            }
        ]
    }

    assert validate_guideline_json(valid_json) == True

    # Test invalid
    invalid_json = {"book_id": "test"}  # Missing fields
    with pytest.raises(ValidationError):
        validate_guideline_json(invalid_json)
```

### Integration Tests

**Test 4: Full Graph Execution (Small Sample)**
```python
def test_guideline_graph_small_book():
    # Prepare test data (3 pages)
    pages = [
        {"page_num": 1, "text": "Chapter 1: Fractions. A fraction represents..."},
        {"page_num": 2, "text": "Comparing fractions. When denominators are the same..."},
        {"page_num": 3, "text": "Practice problems: Compare 3/8 and 5/8..."}
    ]

    book_metadata = {
        "title": "Test Math Book",
        "grade": 3,
        "subject": "Mathematics",
        "board": "CBSE"
    }

    # Run graph
    result = run_guideline_graph(book_id="test_book", book_metadata=book_metadata, pages=pages)

    # Assertions
    assert result["guideline_json"] is not None
    assert len(result["guideline_json"]["topics"]) >= 1
    assert all(len(topic["subtopics"]) >= 1 for topic in result["guideline_json"]["topics"])
```

### E2E Tests

**Test 5: Real Book (Manual)**
1. Upload NCERT Math Magic Grade 3 pages (10-20 pages)
2. Trigger guideline generation
3. Wait for completion
4. Manual review of generated guideline.json:
   - Topics match table of contents?
   - Subtopics are appropriately granular?
   - Learning objectives are clear and measurable?
   - Misconceptions are realistic?
   - Guidelines are actionable?
5. Approve and verify teaching_guidelines table population

### Evaluation Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Topic Accuracy** | 90%+ | Compare extracted topics to book's table of contents |
| **Subtopic Granularity** | 3-8 per topic | Count distribution |
| **Guideline Quality** | 4/5+ rating | Manual review by educator (rubric) |
| **Processing Time** | < 10 min for 50-page book | Time measurement |
| **Token Usage** | < 500k tokens per book | OpenAI API logs |
| **Cost** | < $0.20 per book | Calculate from token usage |
| **Error Rate** | < 5% | Track failures vs successes |

---

## 12. Open Questions & Decisions Needed

### Question 1: Graph Execution Mode
**Options**:
- A. Synchronous (block until complete)
- B. Async with polling (return task ID, poll for status)
- C. Async with webhooks (callback when done)

**Recommendation**: **B - Async with polling**
- Simpler than webhooks
- Frontend can poll /guidelines endpoint
- Show progress indicators

---

### Question 2: Parallelization Strategy
**Question**: Should we parallelize subtopic enrichment?

**Options**:
- A. Process subtopics sequentially (simple, slower)
- B. Process subtopics in parallel (complex, faster)

**Analysis**:
- 20 subtopics × 8 seconds = 160 seconds sequential
- 20 subtopics / 5 parallel = 4 batches × 8 seconds = 32 seconds parallel
- **Speedup**: 5×

**Recommendation**: **B - Parallel processing** (worth the complexity)

---

### Question 3: Retry Budget
**Question**: How many retries per node before giving up?

**Recommendation**:
- LLM API failures: 3 retries with exponential backoff
- Validation failures: 2 retries with refined prompt
- After exhausting retries: Mark for manual review, don't fail entire workflow

---

### Question 4: Context Window for Incremental Processing
**Question**: How much context to pass between pages?

**Options**:
- A. Last 2 pages full text (more context, more tokens)
- B. Summary of last page (balanced)
- C. Just current subtopic metadata (minimal)

**Recommendation**: **B - Summary of last page** (~200-300 words)
- Enough to detect continuations
- Not too expensive

---

### Question 5: Quality Threshold
**Question**: Should we auto-reject low-quality guidelines?

**Criteria**:
- Guideline < 100 words
- < 2 learning objectives
- No misconceptions identified
- Generic text (high similarity to prompt)

**Options**:
- A. Auto-reject and retry (risky, might loop)
- B. Flag for manual review but allow approval (safer)

**Recommendation**: **B - Flag but don't block**

---

## 13. Implementation Checklist

### Phase 6A: Core Graph Implementation (4 hours)
- [ ] Create state.py with GuidelineState schema
- [ ] Create prompts.py with all prompt templates
- [ ] Implement extract_topics_node with validation
- [ ] Implement extract_subtopics_incrementally_node
- [ ] Implement enrich_subtopics_node (combined extraction)
- [ ] Implement generate_guidelines_node
- [ ] Implement synthesize_final_node
- [ ] Create build_graph.py to compile workflow
- [ ] Add error handling and retries
- [ ] Add checkpointing

### Phase 6B: Service Layer (2 hours)
- [ ] Create GuidelineService class
- [ ] Implement run_guideline_extraction method
- [ ] Implement approve_guideline method (auto-populate logic)
- [ ] Add API endpoints to routes.py
- [ ] Add async task execution
- [ ] Add progress tracking

### Phase 6C: Frontend Integration (2 hours)
- [ ] Create GuidelinesPanel component
- [ ] Display topics/subtopics in tree view
- [ ] Show metadata (objectives, misconceptions, etc.)
- [ ] Add approve/reject buttons
- [ ] Add "Generate Guidelines" button to BookDetail
- [ ] Add loading states and progress indicators

### Phase 6D: Testing (2 hours)
- [ ] Unit tests for each node
- [ ] Integration test with 5-page sample
- [ ] E2E test with real book pages
- [ ] Manual quality review
- [ ] Performance benchmarking

---

## 14. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **LLM output quality issues** | High | High | Schema validation, manual review, retry logic |
| **Token costs exceed budget** | Medium | Medium | Use gpt-4o-mini, cache results, optimize prompts |
| **Processing time too long** | Medium | Medium | Parallelize, show progress, async execution |
| **Graph execution failures** | Medium | High | Checkpointing, error handling, retries |
| **Hallucinated topics** | Medium | High | Ground in source, validate, human review |
| **Subtopic granularity wrong** | High | Medium | Prompt engineering, examples, validation |
| **Integration bugs** | Low | Medium | Comprehensive testing, staged rollout |

---

## 15. Success Metrics

**Phase 6 is successful when**:
1. ✅ Full graph executes without errors on 20-page sample
2. ✅ Generated guideline.json passes all validations
3. ✅ Manual review: 4/5+ quality rating from educator
4. ✅ Topics match book's table of contents (90%+ accuracy)
5. ✅ Subtopics are appropriately granular (3-8 per topic)
6. ✅ Processing completes in < 10 minutes for 50-page book
7. ✅ Token usage < $0.20 per book
8. ✅ Auto-population creates correct teaching_guidelines rows
9. ✅ Frontend displays guidelines in structured format
10. ✅ Approve/reject workflow functions correctly

---

## 16. Next Steps After This Document

1. **Review this design doc** - Get feedback, address concerns
2. **Make final decisions** - Answer open questions
3. **Create implementation tasks** - Break down into small PRs
4. **Implement Phase 6A** - Core graph (most critical)
5. **Test with sample data** - Validate approach early
6. **Iterate on prompts** - Refine based on output quality
7. **Implement Phase 6B** - Service layer
8. **Implement Phase 6C** - Frontend
9. **E2E testing** - Real book workflow
10. **Documentation** - Update implementation plan

---

**Document Status**: ✅ Ready for review and approval
**Next Action**: Review design decisions, answer open questions, begin implementation
