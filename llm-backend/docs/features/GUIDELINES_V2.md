# Guidelines Extraction V2 - Simplified Architecture

**Created**: 2025-11-05
**Status**: ✅ Implementation Complete | 🐛 Bug Fixing & Testing
**Version**: 2.0 (Breaking Change)

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Requirements Summary](#requirements-summary)
3. [V1 vs V2 Comparison](#v1-vs-v2-comparison)
4. [Architecture Changes](#architecture-changes)
5. [Data Model Changes](#data-model-changes)
6. [Service Layer Changes](#service-layer-changes)
7. [Implementation Plan](#implementation-plan)
8. [Progress Tracking](#progress-tracking)

---

## Overview

### Purpose

Simplify the guidelines extraction architecture by:
- Reducing structured fields to single `guidelines` text field
- Improving context (full page text + 5 recent summaries)
- Using LLM-based merging instead of rule-based appending
- Adding end-of-book deduplication pass

### Breaking Changes

⚠️ **This is a V2 architecture requiring deletion of existing guidelines**

- New data schema (single `guidelines` field)
- New API response format
- New boundary detection logic
- New merge logic

---

## Requirements Summary

### ✅ Confirmed Requirements

#### 1. **Enhanced Mini-Summaries**
- **V1**: 2-3 lines per page
- **V2**: 5-6 lines per page
- **Why**: More detailed context for better decisions

#### 2. **Expanded Context Window**
- **V1**: Last 2 page summaries
- **V2**: Last 5 page summaries (5-6 lines each)
- **Why**: Better understanding of topic progression

#### 3. **Full Page Text for Boundary Detection**
- **V1**: Send current page summary (30 tokens)
- **V2**: Send current page **full text** (500+ tokens)
- **Why**: AI makes better decisions with complete information

#### 4. **Increased Stability Threshold**
- **V1**: 3 pages without update → finalize
- **V2**: 5 pages without update → finalize
- **Why**: More conservative, reduces premature closures

#### 5. **Book-End Finalization**
- **V1**: Only finalize after 3-page gap
- **V2**: Also finalize all open topics when book ends
- **Why**: Don't leave topics unclosed

#### 6. **Simplified Boundary Detection Output**
```json
// OLD SCHEMA (V1)
{
  "decision": "continue|new",
  "continue_score": 0.85,
  "new_score": 0.15,
  "continue_subtopic_key": "organizing-information",
  "new_subtopic_key": null,
  "new_subtopic_title": null,
  "reasoning": "..."
}

// NEW SCHEMA (V2)
{
  "is_new_topic": true,  // boolean: new topic/subtopic?
  "topic_name": "data-handling",  // lowercase, exact match if existing
  "subtopic_name": "organizing-information",  // lowercase, exact match if existing
  "page_guidelines": "Complete teaching guidelines text..."  // Everything in one field
}
```

#### 7. **Single Guidelines Field**
```python
# OLD (V1) - Structured
class SubtopicShard:
    objectives: List[str]
    examples: List[str]
    misconceptions: List[str]
    assessments: List[Assessment]
    teaching_description: str
    description: str
    evidence_summary: str

# NEW (V2) - Simple
class SubtopicShard:
    guidelines: str  # Single text field with everything
    # No separate objectives, examples, etc.
```

#### 8. **LLM-Based Guideline Merging**
- **V1**: Rule-based (append arrays, deduplicate)
- **V2**: LLM merges text intelligently
- **Why**: Better consolidation, natural language output

#### 9. **End-of-Book Deduplication**
- **V1**: No deduplication
- **V2**: After all pages processed, pass all topics/subtopics to LLM to remove duplicates
- **Why**: Catch over-segmentation (e.g., "Data Handling" + "data-handling-basics")

#### 10. **Context for Boundary Detection**
- **V2**: Send existing topics/subtopics WITH their guidelines text
- **Why**: LLM can see what each topic/subtopic covers, make better matching decisions

### ⏸️ Parked (Not Implementing Now)

1. ❌ **Topic-level guidelines** (subtopic can be NULL) - Complexity not worth it
2. ❌ **One-line descriptions** - Not needed, send full guidelines instead
3. ❌ **Quality validation** - Will revisit later
4. ❌ **Backward compatibility** - Delete old data, fresh start

---

## V1 vs V2 Comparison

| Feature | V1 | V2 | Change Impact |
|---------|----|----|---------------|
| **Page summary length** | 2-3 lines | 5-6 lines | +2x tokens |
| **Context window** | 2 pages | 5 pages | +2.5x tokens |
| **Boundary input** | Page summary | Full page text | +16x tokens |
| **Boundary output** | 7 fields + scores | 3 fields (topic, subtopic, guidelines) | Simpler |
| **Guidelines schema** | 7+ structured fields | 1 text field | **Major simplification** |
| **Merging logic** | Rule-based append | LLM merge | +1 LLM call per CONTINUE |
| **Stability threshold** | 3 pages | 5 pages | More conservative |
| **Book-end handling** | None | Finalize all open | Complete closure |
| **Deduplication** | None | End-of-book LLM pass | Catch over-segmentation |
| **Confidence scores** | Yes | No | Lose debugging info |
| **Total cost** | ~$0.10/book | ~$1.20/book | **12x increase** (acceptable) |
| **Processing time** | ~12 min/100 pages | ~20 min/100 pages | ~1.67x slower |

---

## Architecture Changes

### High-Level Flow (V2)

```
┌─────────────────────────────────────────────────────────────┐
│  STEP 1: Page Upload & OCR (unchanged)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 2: Generate Mini-Summary (5-6 lines)                  │
│  NEW: Longer summaries for better context                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 3: Build Context Pack (5 recent summaries)            │
│  NEW: 5 pages instead of 2                                  │
│  NEW: Include existing guidelines text for each topic       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 4: Boundary Detection                                 │
│  INPUT:                                                      │
│    - Current page FULL TEXT (not summary)                   │
│    - Last 5 page summaries                                  │
│    - All open topics/subtopics with guidelines              │
│  OUTPUT:                                                     │
│    - is_new_topic: bool                                     │
│    - topic_name: str (lowercase)                            │
│    - subtopic_name: str (lowercase)                         │
│    - page_guidelines: str (everything)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                      Decision?
                      /        \
                   NEW          CONTINUE
                    ▼              ▼
┌────────────────────────┐  ┌────────────────────────────────┐
│  STEP 5a: Create Shard │  │  STEP 5b: Merge Guidelines     │
│  - New topic/subtopic  │  │  - Load existing shard         │
│  - Store guidelines    │  │  - LLM merge old + new         │
│  - Mark as "open"      │  │  - Update shard                │
└────────────────────────┘  └────────────────────────────────┘
                    \              /
                     \            /
                      ▼          ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 6: Check Stability                                     │
│  - 5 pages without update? → finalize                       │
│  - Book ended? → finalize all open                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 7: End-of-Book Deduplication                          │
│  - Pass all topics/subtopics to LLM                         │
│  - LLM identifies duplicates                                │
│  - Merge duplicate shards                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 8: User Review & Approval (unchanged)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 9: Database Sync (new schema)                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Model Changes

### SubtopicShard Model (V2)

**File**: `/llm-backend/features/book_ingestion/models/guideline_models.py`

```python
class SubtopicShard(BaseModel):
    """
    V2 SubtopicShard - Simplified with single guidelines field.

    Breaking change from V1:
    - Removed: objectives, examples, misconceptions, assessments,
               teaching_description, description, evidence_summary
    - Added: guidelines (single comprehensive text field)
    """

    # Identifiers
    topic_key: str = Field(..., description="Slugified topic identifier (lowercase)")
    topic_title: str = Field(..., description="Human-readable topic name")
    subtopic_key: str = Field(..., description="Slugified subtopic identifier (lowercase)")
    subtopic_title: str = Field(..., description="Human-readable subtopic name")

    # Page range
    source_page_start: int = Field(..., description="First page of this subtopic")
    source_page_end: int = Field(..., description="Last page of this subtopic")

    # Status
    status: Literal["open", "stable", "final"] = Field(
        default="open",
        description="open=actively growing, stable=no updates for 5 pages, final=book ended or explicitly finalized"
    )

    # Single guidelines field (V2 simplification)
    guidelines: str = Field(
        ...,
        description="Complete teaching guidelines in natural language text. Includes objectives, examples, teaching strategies, misconceptions, and assessments."
    )

    # Metadata
    version: int = Field(default=1, description="Shard version for tracking updates")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    # REMOVED FIELDS (from V1):
    # - objectives: List[str]
    # - examples: List[str]
    # - misconceptions: List[str]
    # - assessments: List[Assessment]
    # - teaching_description: str
    # - description: str
    # - evidence_summary: str
    # - confidence: float
    # - quality_score: Optional[float]
```

### BoundaryDecision Model (V2)

**File**: `/llm-backend/features/book_ingestion/models/guideline_models.py`

```python
class BoundaryDecisionV2(BaseModel):
    """
    V2 Boundary Detection Output - Simplified.

    Breaking change from V1:
    - Removed: decision, continue_score, new_score, continue_subtopic_key,
               new_subtopic_key, new_subtopic_title, reasoning
    - Changed: Single decision + extracted guidelines
    """

    is_new_topic: bool = Field(
        ...,
        description="True if this page starts a new topic/subtopic, False if it continues an existing one"
    )

    topic_name: str = Field(
        ...,
        description="Topic name (lowercase, kebab-case). MUST exactly match existing topic if is_new_topic=False"
    )

    subtopic_name: str = Field(
        ...,
        description="Subtopic name (lowercase, kebab-case). MUST exactly match existing subtopic if is_new_topic=False"
    )

    page_guidelines: str = Field(
        ...,
        description="Complete teaching guidelines extracted from this page. Natural language text covering objectives, examples, teaching strategies, misconceptions, and assessments."
    )
```

### Database Schema Changes

**File**: `/llm-backend/models/database.py`

```python
class TeachingGuideline(Base):
    """V2 schema - simplified"""
    __tablename__ = "teaching_guidelines"

    id = Column(Integer, primary_key=True)

    # V2: Simplified identifiers
    topic_key = Column(String, nullable=False)
    topic_title = Column(String, nullable=False)
    subtopic_key = Column(String, nullable=False)
    subtopic_title = Column(String, nullable=False)

    # V2: Single guidelines field
    guidelines = Column(Text, nullable=False)  # NEW: Replaces all structured fields

    # Page range
    source_page_start = Column(Integer)
    source_page_end = Column(Integer)

    # Status
    status = Column(String, default="final")

    # Book relation
    book_id = Column(String, ForeignKey("books.id"))

    # Metadata
    grade = Column(Integer)
    subject = Column(String)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # REMOVED FIELDS (from V1):
    # - objectives_json
    # - examples_json
    # - misconceptions_json
    # - assessments_json
    # - teaching_description
    # - description
    # - evidence_summary
    # - confidence
    # - quality_score
```

---

## Service Layer Changes

### 1. MinisummaryService (Update)

**File**: `/llm-backend/features/book_ingestion/services/minisummary_service.py`

**Changes**:
- Update prompt: Request 5-6 lines instead of 2-3
- Increase max_tokens: 200 → 300

**Single Responsibility**: Generate detailed page summaries

```python
class MinisummaryService:
    """Generate 5-6 line page summaries (V2)"""

    def __init__(self, openai_client: Optional[OpenAI] = None):
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 300  # V2: Increased from 200

    def generate(self, page_text: str, grade: int, subject: str) -> str:
        """Generate 5-6 line summary"""
        # Prompt updated to request 5-6 lines
        ...
```

**Prompt Template**: `/llm-backend/features/book_ingestion/prompts/minisummary_v2.txt`

```text
You are analyzing a textbook page. Generate a 5-6 line summary.

REQUIREMENTS:
- 5-6 complete sentences
- Cover main concepts, activities, and examples
- Mention any explicit learning objectives
- Note any assessment questions or practice problems
- Be specific (don't just say "introduces topic", say WHAT is introduced)

Grade {grade} {subject}
Page text:
{page_text}

OUTPUT:
5-6 line summary only, no extra text.
```

---

### 2. ContextPackService (Update)

**File**: `/llm-backend/features/book_ingestion/services/context_pack_service.py`

**Changes**:
- Update `_get_recent_summaries()`: num_recent = 2 → 5
- Update `_extract_open_topics()`: Include `guidelines` text for each subtopic

**Single Responsibility**: Build context packs with enhanced information

```python
class ContextPackService:
    """Build context packs with 5 recent summaries + guidelines text (V2)"""

    def _get_recent_summaries(
        self,
        book_id: str,
        current_page: int,
        num_recent: int = 5  # V2: Changed from 2
    ) -> List[RecentPageSummary]:
        """Get summaries of last 5 pages"""
        ...

    def _extract_open_topics(
        self,
        book_id: str,
        index: GuidelinesIndex
    ) -> List[OpenTopicInfo]:
        """
        Extract open topics with guidelines text (V2).

        V2 Change: Include shard.guidelines in OpenSubtopicInfo
        """
        open_topics = []

        for topic_entry in index.topics:
            open_subtopics = []

            for subtopic_entry in topic_entry.subtopics:
                if subtopic_entry.status in ["open", "stable"]:
                    # V2: Load shard to get guidelines text
                    shard = self._load_shard(book_id, topic_entry.topic_key, subtopic_entry.subtopic_key)

                    open_subtopics.append(
                        OpenSubtopicInfo(
                            subtopic_key=subtopic_entry.subtopic_key,
                            subtopic_title=subtopic_entry.subtopic_title,
                            page_start=shard.source_page_start,
                            page_end=shard.source_page_end,
                            guidelines=shard.guidelines  # V2: Include full guidelines
                        )
                    )

            if open_subtopics:
                open_topics.append(
                    OpenTopicInfo(
                        topic_key=topic_entry.topic_key,
                        topic_title=topic_entry.topic_title,
                        open_subtopics=open_subtopics
                    )
                )

        return open_topics
```

**Model Update**: Add `guidelines` to `OpenSubtopicInfo`

```python
class OpenSubtopicInfo(BaseModel):
    """Info about an open subtopic (V2 with guidelines)"""
    subtopic_key: str
    subtopic_title: str
    page_start: int
    page_end: int
    guidelines: str  # V2: Added full guidelines text
```

---

### 3. BoundaryDetectionServiceV2 (Rewrite)

**File**: `/llm-backend/features/book_ingestion/services/boundary_detection_service_v2.py`

**Changes**:
- NEW file (copy and modify from V1)
- Input: Full page text (not summary)
- Input: Context pack with guidelines
- Output: BoundaryDecisionV2
- No hysteresis (no confidence scores)

**Single Responsibility**: Detect boundaries and extract page guidelines

```python
class BoundaryDetectionServiceV2:
    """
    V2 Boundary Detection - Simplified output with page guidelines.

    Key changes from V1:
    - Input: Full page text instead of summary
    - Input: Open topics include guidelines text
    - Output: is_new_topic, topic_name, subtopic_name, page_guidelines
    - No confidence scores or hysteresis
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 1000  # V2: Increased for guidelines extraction
        self.prompt_template = self._load_prompt_template()

    def detect(
        self,
        context_pack: ContextPack,
        page_text: str  # V2: Full text, not summary
    ) -> Tuple[bool, str, str, str, str]:
        """
        Detect boundary and extract guidelines.

        Args:
            context_pack: Current context with 5 recent summaries + guidelines
            page_text: Full page text (not summary)

        Returns:
            Tuple of (is_new, topic_key, topic_title, subtopic_key, subtopic_title, page_guidelines)
        """
        prompt = self._build_prompt(context_pack, page_text)

        # Call LLM
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a textbook structure analyzer."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=self.max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        # Parse response
        raw_response = response.choices[0].message.content.strip()
        decision_data = json.loads(raw_response)
        decision = BoundaryDecisionV2(**decision_data)

        # Normalize keys (lowercase, slugified)
        topic_key = slugify(decision.topic_name)
        subtopic_key = slugify(decision.subtopic_name)

        # Infer titles if needed
        topic_title = deslugify(topic_key)
        subtopic_title = deslugify(subtopic_key)

        logger.info(
            f"Boundary decision: {'NEW' if decision.is_new_topic else 'CONTINUE'} "
            f"→ {topic_key}/{subtopic_key}"
        )

        return (
            decision.is_new_topic,
            topic_key,
            topic_title,
            subtopic_key,
            subtopic_title,
            decision.page_guidelines
        )

    def _build_prompt(self, context_pack: ContextPack, page_text: str) -> str:
        """Build boundary detection prompt (V2)"""
        # Format open topics with guidelines
        open_topics_str = ""
        for topic in context_pack.open_topics:
            open_topics_str += f"\nTopic: {topic.topic_title} ({topic.topic_key})\n"
            for subtopic in topic.open_subtopics:
                open_topics_str += (
                    f"  Subtopic: {subtopic.subtopic_title} ({subtopic.subtopic_key})\n"
                    f"  Pages: {subtopic.page_start}-{subtopic.page_end}\n"
                    f"  Guidelines:\n{subtopic.guidelines}\n\n"
                )

        if not open_topics_str:
            open_topics_str = "(No open topics yet - this is the first page)"

        # Format recent summaries
        recent_summaries_str = ""
        for summary in context_pack.recent_page_summaries:
            recent_summaries_str += f"Page {summary.page}:\n{summary.summary}\n\n"

        if not recent_summaries_str:
            recent_summaries_str = "(No recent pages)"

        # Fill template
        return self.prompt_template.format(
            grade=context_pack.book_metadata.get("grade", "?"),
            subject=context_pack.book_metadata.get("subject", "?"),
            board=context_pack.book_metadata.get("board", "?"),
            current_page=context_pack.current_page,
            open_topics=open_topics_str,
            recent_summaries=recent_summaries_str,
            page_text=page_text
        )
```

**Prompt Template**: `/llm-backend/features/book_ingestion/prompts/boundary_detection_v2.txt`

```text
You are analyzing a textbook page to determine if it continues an existing topic/subtopic or starts a new one, AND extract teaching guidelines from this page.

CONTEXT:
Book: Grade {grade} {subject} ({board})
Current Page: {current_page}

EXISTING OPEN TOPICS/SUBTOPICS:
{open_topics}

RECENT PAGE SUMMARIES (last 5 pages):
{recent_summaries}

CURRENT PAGE FULL TEXT:
{page_text}

TASK:
1. Determine if this page CONTINUES an existing topic/subtopic or starts a NEW one
2. Identify the topic and subtopic names
3. Extract complete teaching guidelines from this page

DECISION GUIDELINES:
- A topic/subtopic represents a LEARNING OBJECTIVE, not individual activities
- Multiple activities can teach the SAME learning objective → CONTINUE
- Look for CONCEPTUAL similarity, not surface-level changes
- When in doubt, CONTINUE rather than create NEW
- If CONTINUING: topic_name and subtopic_name MUST EXACTLY MATCH an existing one from the list above

TOPIC/SUBTOPIC NAMING:
- Use lowercase, kebab-case (e.g., "data-handling", "adding-fractions")
- If NEW: Create descriptive, broad names (not activity-specific)
- If CONTINUE: Copy exact name from existing topics list

GUIDELINES EXTRACTION:
Extract from this page in natural language text:
- Learning objectives (what students should learn)
- Examples and activities shown
- Teaching strategies or instructions for teachers
- Common misconceptions mentioned
- Assessment questions or practice problems

Format as a comprehensive paragraph or bulleted text (your choice - natural language).

OUTPUT JSON:
{
  "is_new_topic": true|false,
  "topic_name": "lowercase-topic-name",
  "subtopic_name": "lowercase-subtopic-name",
  "page_guidelines": "Complete teaching guidelines text extracted from this page..."
}
```

---

### 4. GuidelineMergeService (NEW)

**File**: `/llm-backend/features/book_ingestion/services/guideline_merge_service.py`

**Changes**: Brand new service for LLM-based merging

**Single Responsibility**: Merge guidelines text using LLM

```python
class GuidelineMergeService:
    """
    V2 service for merging guidelines using LLM.

    Replaces V1's rule-based array appending with intelligent text merging.
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 1500
        self.prompt_template = self._load_prompt_template()

    def merge(
        self,
        existing_guidelines: str,
        new_page_guidelines: str,
        topic_title: str,
        subtopic_title: str,
        grade: int,
        subject: str
    ) -> str:
        """
        Merge new page guidelines into existing guidelines.

        Args:
            existing_guidelines: Current guidelines text
            new_page_guidelines: Guidelines from new page
            topic_title: Topic name (for context)
            subtopic_title: Subtopic name (for context)
            grade: Grade level
            subject: Subject

        Returns:
            Merged guidelines text
        """
        prompt = self._build_prompt(
            existing_guidelines,
            new_page_guidelines,
            topic_title,
            subtopic_title,
            grade,
            subject
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a teaching guidelines consolidation expert."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=self.max_tokens,
            temperature=0.3  # Some creativity for natural merging
        )

        merged_guidelines = response.choices[0].message.content.strip()

        logger.info(
            f"Merged guidelines for {topic_title}/{subtopic_title}: "
            f"{len(existing_guidelines)} + {len(new_page_guidelines)} → {len(merged_guidelines)} chars"
        )

        return merged_guidelines

    def _build_prompt(
        self,
        existing: str,
        new: str,
        topic: str,
        subtopic: str,
        grade: int,
        subject: str
    ) -> str:
        return self.prompt_template.format(
            topic=topic,
            subtopic=subtopic,
            grade=grade,
            subject=subject,
            existing_guidelines=existing,
            new_page_guidelines=new
        )

    def _load_prompt_template(self) -> str:
        prompt_path = Path(__file__).parent.parent / "prompts" / "guideline_merge_v2.txt"
        return prompt_path.read_text()
```

**Prompt Template**: `/llm-backend/features/book_ingestion/prompts/guideline_merge_v2.txt`

```text
You are merging teaching guidelines for a textbook topic.

TOPIC: {topic}
SUBTOPIC: {subtopic}
GRADE: {grade}
SUBJECT: {subject}

EXISTING GUIDELINES:
{existing_guidelines}

NEW PAGE GUIDELINES:
{new_page_guidelines}

TASK:
Merge the new page guidelines into the existing guidelines to create a comprehensive, consolidated text.

REQUIREMENTS:
1. Combine information without duplication
2. Maintain natural language flow
3. Keep all unique objectives, examples, misconceptions, and assessments
4. Organize logically (objectives → teaching strategies → examples → misconceptions → assessments)
5. If formats differ, consolidate into a coherent structure
6. If information overlaps, keep the more detailed version

OUTPUT:
Return ONLY the merged guidelines text (no extra commentary).
```

---

### 5. TopicDeduplicationService (NEW)

**File**: `/llm-backend/features/book_ingestion/services/topic_deduplication_service.py`

**Changes**: Brand new service for end-of-book deduplication

**Single Responsibility**: Identify and merge duplicate topics/subtopics

```python
class TopicDeduplicationService:
    """
    V2 service for end-of-book topic/subtopic deduplication.

    After all pages processed, identify duplicate topics (e.g., "Data Handling" vs "data-handling-basics")
    and merge them.
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 2000
        self.prompt_template = self._load_prompt_template()

    def deduplicate(
        self,
        all_shards: List[SubtopicShard],
        grade: int,
        subject: str
    ) -> List[Tuple[str, str, str, str]]:
        """
        Identify duplicate topics/subtopics.

        Args:
            all_shards: All subtopic shards from the book
            grade: Grade level
            subject: Subject

        Returns:
            List of tuples: (topic_key1, subtopic_key1, topic_key2, subtopic_key2)
            Each tuple represents a duplicate pair that should be merged.
        """
        # Build summary of all topics
        topics_summary = self._build_topics_summary(all_shards)

        prompt = self._build_prompt(topics_summary, grade, subject)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a curriculum structure analyzer specializing in identifying duplicate topics."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=self.max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        raw_response = response.choices[0].message.content.strip()
        result = json.loads(raw_response)

        # Parse duplicates
        duplicates = []
        for dup in result.get("duplicates", []):
            duplicates.append((
                dup["topic_key1"],
                dup["subtopic_key1"],
                dup["topic_key2"],
                dup["subtopic_key2"]
            ))

        logger.info(f"Found {len(duplicates)} duplicate topic/subtopic pairs")

        return duplicates

    def _build_topics_summary(self, shards: List[SubtopicShard]) -> str:
        """Build a summary of all topics for LLM analysis"""
        summary = ""

        for shard in shards:
            summary += (
                f"\nTopic: {shard.topic_title} ({shard.topic_key})\n"
                f"Subtopic: {shard.subtopic_title} ({shard.subtopic_key})\n"
                f"Pages: {shard.source_page_start}-{shard.source_page_end}\n"
                f"Guidelines Preview: {shard.guidelines[:200]}...\n"
            )

        return summary

    def _build_prompt(self, topics_summary: str, grade: int, subject: str) -> str:
        return self.prompt_template.format(
            grade=grade,
            subject=subject,
            topics_summary=topics_summary
        )

    def _load_prompt_template(self) -> str:
        prompt_path = Path(__file__).parent.parent / "prompts" / "topic_deduplication_v2.txt"
        return prompt_path.read_text()
```

**Prompt Template**: `/llm-backend/features/book_ingestion/prompts/topic_deduplication_v2.txt`

```text
You are analyzing all topics/subtopics extracted from a Grade {grade} {subject} textbook to identify duplicates.

ALL TOPICS/SUBTOPICS:
{topics_summary}

TASK:
Identify any duplicate or highly overlapping topics/subtopics that should be merged.

CRITERIA FOR DUPLICATES:
1. Same concept with different wording (e.g., "Data Handling" vs "Organizing Data")
2. One is subset of another (e.g., "Addition" vs "Adding Two-Digit Numbers")
3. Nearly identical page ranges (likely same content, different naming)
4. Guidelines preview shows same concepts

DO NOT mark as duplicate if:
- Different concepts (e.g., "Addition" vs "Subtraction")
- Sequential progression (e.g., "Basic Fractions" → "Advanced Fractions")
- Clear pedagogical separation

OUTPUT JSON:
{
  "duplicates": [
    {
      "topic_key1": "data-handling",
      "subtopic_key1": "organizing-information",
      "topic_key2": "data-organization",
      "subtopic_key2": "categorizing-data",
      "reason": "Both cover same concept of organizing and categorizing data"
    }
  ]
}

If no duplicates found, return {"duplicates": []}.
```

---

### 6. GuidelineExtractionOrchestratorV2 (Rewrite)

**File**: `/llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator_v2.py`

**Changes**: Major rewrite to use new services

**Single Responsibility**: Orchestrate the entire V2 pipeline

```python
class GuidelineExtractionOrchestratorV2:
    """
    V2 Orchestrator - Simplified pipeline with LLM-based merging.

    Key changes from V1:
    - Use BoundaryDetectionServiceV2
    - Use GuidelineMergeService for CONTINUE
    - No FactsExtractionService (done in boundary detection)
    - Add end-of-book deduplication
    - 5-page stability threshold
    - Book-end finalization
    """

    def __init__(self):
        self.openai_client = OpenAI()
        self.s3 = S3Client()

        # V2 Services
        self.minisummary = MinisummaryService(self.openai_client)
        self.context_pack = ContextPackService(self.s3)
        self.boundary_detector = BoundaryDetectionServiceV2(self.openai_client)
        self.merge_service = GuidelineMergeService(self.openai_client)
        self.dedup_service = TopicDeduplicationService(self.openai_client)

        # V2 Config
        self.stability_threshold = 5  # V2: Changed from 3

    async def process_page(
        self,
        book_id: str,
        page_num: int,
        page_text: str,
        book_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single page (V2 pipeline).

        Steps:
        1. Generate 5-6 line mini-summary
        2. Build context pack (5 recent pages + guidelines)
        3. Boundary detection with full page text
        4. Create new shard OR merge guidelines
        5. Check stability (5-page threshold)
        6. Save shard
        """
        logger.info(f"Processing page {page_num} (V2 pipeline)")

        # Step 1: Generate mini-summary (5-6 lines)
        minisummary = self.minisummary.generate(
            page_text=page_text,
            grade=book_metadata.get("grade", 3),
            subject=book_metadata.get("subject", "Math")
        )

        # Step 2: Build context pack (5 recent + guidelines)
        context_pack = self.context_pack.build(
            book_id=book_id,
            current_page=page_num,
            book_metadata=book_metadata
        )

        # Step 3: Boundary detection (with full page text)
        is_new, topic_key, topic_title, subtopic_key, subtopic_title, page_guidelines = (
            self.boundary_detector.detect(
                context_pack=context_pack,
                page_text=page_text  # V2: Full text, not summary
            )
        )

        # Step 4: Create or merge shard
        if is_new:
            # Create new shard
            shard = SubtopicShard(
                topic_key=topic_key,
                topic_title=topic_title,
                subtopic_key=subtopic_key,
                subtopic_title=subtopic_title,
                source_page_start=page_num,
                source_page_end=page_num,
                status="open",
                guidelines=page_guidelines,  # V2: Single field
                version=1
            )
            logger.info(f"Created NEW shard: {topic_key}/{subtopic_key}")
        else:
            # Load existing shard and merge
            shard = self._load_shard(book_id, topic_key, subtopic_key)

            # V2: LLM-based merge
            merged_guidelines = self.merge_service.merge(
                existing_guidelines=shard.guidelines,
                new_page_guidelines=page_guidelines,
                topic_title=topic_title,
                subtopic_title=subtopic_title,
                grade=book_metadata.get("grade", 3),
                subject=book_metadata.get("subject", "Math")
            )

            shard.guidelines = merged_guidelines
            shard.source_page_end = page_num
            shard.version += 1
            shard.updated_at = datetime.utcnow().isoformat()

            logger.info(f"Merged into existing shard: {topic_key}/{subtopic_key}")

        # Step 5: Check stability (5-page threshold)
        await self._check_and_finalize_stable_subtopics(
            book_id=book_id,
            current_page=page_num,
            book_metadata=book_metadata
        )

        # Step 6: Save shard
        self._save_shard(book_id, shard)

        # Save page guideline (for context pack)
        self._save_page_guideline(book_id, page_num, minisummary)

        return {
            "page": page_num,
            "decision": "new" if is_new else "continue",
            "topic": topic_key,
            "subtopic": subtopic_key
        }

    async def finalize_book(
        self,
        book_id: str,
        book_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        End-of-book processing (V2).

        Steps:
        1. Finalize all open topics/subtopics
        2. Run deduplication pass
        3. Merge duplicate shards
        """
        logger.info(f"Finalizing book {book_id} (V2 pipeline)")

        # Step 1: Finalize all open shards
        index = self._load_index(book_id)
        for topic in index.topics:
            for subtopic in topic.subtopics:
                if subtopic.status in ["open", "stable"]:
                    shard = self._load_shard(book_id, topic.topic_key, subtopic.subtopic_key)
                    shard.status = "final"
                    self._save_shard(book_id, shard)

        # Step 2: Load all shards for deduplication
        all_shards = self._load_all_shards(book_id)

        # Step 3: Identify duplicates
        duplicates = self.dedup_service.deduplicate(
            all_shards=all_shards,
            grade=book_metadata.get("grade", 3),
            subject=book_metadata.get("subject", "Math")
        )

        # Step 4: Merge duplicate shards
        merged_count = 0
        for topic1, subtopic1, topic2, subtopic2 in duplicates:
            self._merge_duplicate_shards(book_id, topic1, subtopic1, topic2, subtopic2)
            merged_count += 1

        logger.info(f"Book finalized: {merged_count} duplicate pairs merged")

        return {
            "status": "finalized",
            "duplicates_merged": merged_count,
            "total_topics": len(index.topics)
        }

    async def _check_and_finalize_stable_subtopics(
        self,
        book_id: str,
        current_page: int,
        book_metadata: Dict[str, Any]
    ):
        """
        Check for stable subtopics (V2: 5-page threshold).
        """
        index = self._load_index(book_id)

        for topic in index.topics:
            for subtopic in topic.subtopics:
                if subtopic.status == "open":
                    shard = self._load_shard(book_id, topic.topic_key, subtopic.subtopic_key)

                    # V2: 5-page gap threshold
                    if current_page - shard.source_page_end >= 5:
                        shard.status = "stable"
                        self._save_shard(book_id, shard)
                        logger.info(
                            f"Marked stable: {topic.topic_key}/{subtopic.subtopic_key} "
                            f"(last page: {shard.source_page_end}, current: {current_page})"
                        )

    def _merge_duplicate_shards(
        self,
        book_id: str,
        topic1: str,
        subtopic1: str,
        topic2: str,
        subtopic2: str
    ):
        """Merge two duplicate shards"""
        shard1 = self._load_shard(book_id, topic1, subtopic1)
        shard2 = self._load_shard(book_id, topic2, subtopic2)

        # Merge guidelines using LLM
        merged_guidelines = self.merge_service.merge(
            existing_guidelines=shard1.guidelines,
            new_page_guidelines=shard2.guidelines,
            topic_title=shard1.topic_title,
            subtopic_title=shard1.subtopic_title,
            grade=3,  # TODO: Get from book metadata
            subject="Math"
        )

        # Keep shard1, update it
        shard1.guidelines = merged_guidelines
        shard1.source_page_start = min(shard1.source_page_start, shard2.source_page_start)
        shard1.source_page_end = max(shard1.source_page_end, shard2.source_page_end)
        shard1.version += 1

        # Save merged shard
        self._save_shard(book_id, shard1)

        # Delete shard2
        self._delete_shard(book_id, topic2, subtopic2)

        logger.info(f"Merged {topic1}/{subtopic1} ← {topic2}/{subtopic2}")
```

---

## Implementation Plan

### Phase 1: Preparation & Data Models (2 hours)

#### Tasks:
1. **Create V2 branch**
   ```bash
   git checkout -b feature/guidelines-v2
   ```

2. **Update data models**
   - [ ] Update `SubtopicShard` in `guideline_models.py`
   - [ ] Create `BoundaryDecisionV2` model
   - [ ] Update `OpenSubtopicInfo` (add `guidelines` field)
   - [ ] Update database schema in `database.py`

3. **Create migration script**
   - [ ] Write `migrate_to_v2.py`
   - [ ] Function to delete existing V1 guidelines
   - [ ] Function to create V2 schema

**Acceptance Criteria:**
- ✅ Models import without errors
- ✅ V2 schema defined
- ✅ Migration script ready

---

### Phase 2: Core Services - Part 1 (4 hours)

#### Tasks:
1. **Update MinisummaryService**
   - [ ] Update prompt template → 5-6 lines
   - [ ] Increase max_tokens: 200 → 300
   - [ ] Test with sample page

2. **Update ContextPackService**
   - [ ] Change `num_recent` parameter: 2 → 5
   - [ ] Update `_extract_open_topics()` to include `guidelines`
   - [ ] Test context pack building

3. **Create BoundaryDetectionServiceV2**
   - [ ] Copy from V1, rename file
   - [ ] Update input: accept `page_text` instead of `minisummary`
   - [ ] Update output: return `BoundaryDecisionV2`
   - [ ] Remove hysteresis logic (no confidence scores)
   - [ ] Create new prompt template `boundary_detection_v2.txt`
   - [ ] Test with sample page

**Acceptance Criteria:**
- ✅ Services import and initialize
- ✅ Can generate 5-6 line summaries
- ✅ Context pack includes guidelines
- ✅ Boundary detection returns V2 schema

---

### Phase 3: Core Services - Part 2 (4 hours)

#### Tasks:
1. **Create GuidelineMergeService**
   - [ ] Create new file
   - [ ] Implement `merge()` method
   - [ ] Create prompt template `guideline_merge_v2.txt`
   - [ ] Test merging with sample guidelines

2. **Create TopicDeduplicationService**
   - [ ] Create new file
   - [ ] Implement `deduplicate()` method
   - [ ] Create prompt template `topic_deduplication_v2.txt`
   - [ ] Test with sample topic list

**Acceptance Criteria:**
- ✅ Merge service produces coherent text
- ✅ Deduplication identifies obvious duplicates
- ✅ Prompt templates tested

---

### Phase 4: Orchestrator Rewrite (5 hours)

#### Tasks:
1. **Create GuidelineExtractionOrchestratorV2**
   - [ ] Copy from V1, rename file
   - [ ] Update `process_page()` method:
     - Use BoundaryDetectionServiceV2
     - Use GuidelineMergeService for CONTINUE
     - Remove FactsExtractionService calls
     - Update stability check: 3 → 5 pages
   - [ ] Create `finalize_book()` method:
     - Finalize all open topics
     - Run deduplication
     - Merge duplicates
   - [ ] Update shard save/load for V2 schema

**Acceptance Criteria:**
- ✅ Can process pages end-to-end
- ✅ Creates V2 shards correctly
- ✅ Merges guidelines on CONTINUE
- ✅ Finalizes book with deduplication

---

### Phase 5: API & Database (3 hours)

#### Tasks:
1. **Run database migration**
   - [ ] Execute migration script (delete V1 data)
   - [ ] Verify V2 schema created

2. **Update DBSyncService**
   - [ ] Update INSERT query for V2 schema
   - [ ] Update UPDATE query
   - [ ] Remove V1 fields from sync

3. **Update API endpoints**
   - [ ] Update `GuidelineSubtopicResponse` model
   - [ ] Remove structured fields (objectives, examples, etc.)
   - [ ] Add `guidelines` field
   - [ ] Test API responses

4. **Update routes to use V2 orchestrator**
   - [ ] Import GuidelineExtractionOrchestratorV2
   - [ ] Update generate guidelines endpoint
   - [ ] Update approval endpoint

**Acceptance Criteria:**
- ✅ Database has V2 schema
- ✅ API returns V2 format
- ✅ Can sync V2 guidelines to database

---

### Phase 6: Frontend (2 hours)

#### Tasks:
1. **Update TypeScript types**
   - [ ] Update `GuidelineSubtopic` interface
   - [ ] Remove structured fields
   - [ ] Add `guidelines: string`

2. **Update GuidelinesPanel component**
   - [ ] Remove sections for objectives, examples, etc.
   - [ ] Display `guidelines` as single text block
   - [ ] Add basic formatting (preserve newlines)

**Acceptance Criteria:**
- ✅ No TypeScript errors
- ✅ Guidelines display in UI
- ✅ Readable formatting

---

### Phase 7: Testing (4 hours)

#### Tasks:
1. **Unit tests**
   - [ ] Test MinisummaryService (5-6 lines)
   - [ ] Test BoundaryDetectionServiceV2
   - [ ] Test GuidelineMergeService
   - [ ] Test TopicDeduplicationService

2. **Integration tests**
   - [ ] Test full page processing pipeline
   - [ ] Test book finalization
   - [ ] Test deduplication

3. **End-to-end test**
   - [ ] Upload test book (10 pages)
   - [ ] Generate guidelines
   - [ ] Verify shards created
   - [ ] Verify deduplication works
   - [ ] Approve and sync to DB
   - [ ] Check database records

**Acceptance Criteria:**
- ✅ All unit tests pass
- ✅ Integration tests pass
- ✅ E2E test successful
- ✅ No regressions

---

### Phase 8: Documentation & Cleanup (1 hour)

#### Tasks:
1. **Update documentation**
   - [ ] Update this file with results
   - [ ] Update architecture overview
   - [ ] Add V2 migration guide

2. **Code cleanup**
   - [ ] Remove dead code
   - [ ] Add docstrings
   - [ ] Format with black

3. **Merge to main**
   - [ ] Create PR
   - [ ] Code review
   - [ ] Merge

**Acceptance Criteria:**
- ✅ Documentation complete
- ✅ Code clean and formatted
- ✅ PR merged

---

## Progress Tracking

### Summary

| Phase | Status | Tasks Complete | Time Spent | Notes |
|-------|--------|----------------|------------|-------|
| **Phase 1: Data Models** | ✅ Complete | 6/6 | 1.5h | All V2 models created |
| **Phase 2: Core Services 1** | ✅ Complete | 7/7 | 3h | MinisummaryV2, ContextPackV2, BoundaryDetectionV2 |
| **Phase 3: Core Services 2** | ✅ Complete | 6/6 | 2.5h | GuidelineMerge, TopicDeduplication |
| **Phase 4: Orchestrator** | ✅ Complete | 5/5 | 3h | Full V2 pipeline with deduplication |
| **Phase 5: API & DB** | ✅ Complete | 4/4 | 2h | DBSyncV2, API routes, response models |
| **Phase 6: Frontend** | ✅ Complete | 2/2 | 1h | TypeScript types, GuidelinesPanel |
| **Phase 7: Testing** | 🐛 In Progress | 0/3 | 2h | Bug fixes: shard loading, S3 methods |
| **Phase 8: Docs** | ⏳ Pending | 0/3 | 0h | Update docs, cleanup, PR |
| **TOTAL** | **88%** | **30/36** | **15h / 25h** | Ahead of schedule! |

---

### Detailed Progress

#### Phase 1: Preparation & Data Models
- [ ] Create V2 branch
- [ ] Update `SubtopicShard` model
- [ ] Create `BoundaryDecisionV2` model
- [ ] Update `OpenSubtopicInfo` model
- [ ] Update `TeachingGuideline` database model
- [ ] Create migration script

#### Phase 2: Core Services - Part 1
- [ ] Update MinisummaryService prompt
- [ ] Update MinisummaryService max_tokens
- [ ] Update ContextPackService num_recent
- [ ] Update ContextPackService _extract_open_topics
- [ ] Create BoundaryDetectionServiceV2 file
- [ ] Implement BoundaryDetectionServiceV2.detect()
- [ ] Create boundary_detection_v2.txt prompt

#### Phase 3: Core Services - Part 2
- [ ] Create GuidelineMergeService file
- [ ] Implement GuidelineMergeService.merge()
- [ ] Create guideline_merge_v2.txt prompt
- [ ] Create TopicDeduplicationService file
- [ ] Implement TopicDeduplicationService.deduplicate()
- [ ] Create topic_deduplication_v2.txt prompt

#### Phase 4: Orchestrator Rewrite
- [ ] Create GuidelineExtractionOrchestratorV2 file
- [ ] Implement process_page() with V2 services
- [ ] Implement finalize_book() with deduplication
- [ ] Update stability threshold to 5 pages
- [ ] Update shard save/load for V2 schema

#### Phase 5: API & Database
- [ ] Run database migration script
- [ ] Update DBSyncService INSERT query
- [ ] Update DBSyncService UPDATE query
- [ ] Update GuidelineSubtopicResponse model
- [ ] Update generate guidelines endpoint
- [ ] Update approval endpoint

#### Phase 6: Frontend
- [ ] Update TypeScript GuidelineSubtopic interface
- [ ] Update GuidelinesPanel component
- [ ] Remove structured field sections
- [ ] Add guidelines text display

#### Phase 7: Testing
- [ ] Write unit tests for new services
- [ ] Write integration tests
- [ ] Run E2E test with sample book
- [ ] Verify all tests pass

#### Phase 8: Documentation & Cleanup
- [ ] Update documentation
- [ ] Code cleanup and formatting
- [ ] Create PR and merge

---

## Design Principles

### Single Responsibility Principle (SRP)

Each service has ONE job:

| Service | Responsibility |
|---------|----------------|
| `MinisummaryService` | Generate 5-6 line page summaries |
| `ContextPackService` | Build context packs with 5 recent pages + guidelines |
| `BoundaryDetectionServiceV2` | Detect boundaries + extract page guidelines |
| `GuidelineMergeService` | Merge guidelines text using LLM |
| `TopicDeduplicationService` | Identify duplicate topics at book-end |
| `GuidelineExtractionOrchestratorV2` | Orchestrate the entire V2 pipeline |
| `DBSyncService` | Sync approved shards to database |

### Testability

- Each service can be unit tested independently
- Mock OpenAI client for testing
- Mock S3 client for testing
- Integration tests cover full pipeline

### Maintainability

- V2 services in separate files (don't modify V1)
- Clear naming: `*_v2.py`, `*_v2.txt`
- Comprehensive docstrings
- Type hints throughout

---

## Cost & Performance Estimates

### Token Usage (V2)

```
Per page:
- Mini-summary: 500 (in) + 100 (out) = 600 tokens
- Context pack: 5 summaries × 100 = 500 tokens
- Boundary detection: 1000 (in) + 300 (out) = 1300 tokens
- Merge (50% of pages): 800 (in) + 500 (out) = 1300 tokens × 0.5 = 650 tokens

Average per page: 600 + 1300 + 650 = 2,550 tokens

100-page book: 255,000 tokens ≈ $1.20
```

### Processing Time (V2)

```
Per page:
- OCR: 2 sec
- Mini-summary: 1.5 sec
- Boundary detection: 2 sec
- Merge (50% of pages): 1.5 sec × 0.5 = 0.75 sec
- Save: 0.5 sec

Average per page: ~7 seconds

100-page book: ~12 minutes
+ Deduplication: ~30 seconds
Total: ~13 minutes
```

---

## 🐛 Bugs Found & Fixed During Testing

### Bug #1: Shard Not Found on CONTINUE Decision
**Date**: 2025-11-05
**Severity**: Critical (Blocking)

**Problem**: When boundary detection returns `is_new=False` (CONTINUE), the orchestrator attempted to load an existing shard that might not exist yet. This occurred when:
- First page of the book
- LLM incorrectly decides CONTINUE before any shard is created
- Shard file doesn't exist in S3 yet

**Error**:
```
NoSuchKey: The specified key does not exist.
books/ncert_mathematics_3_2024/guidelines/v2/topics/.../subtopics/....latest.json
```

**Root Cause**: `process_page()` in orchestrator_v2 line 290 called `self._load_shard_v2()` without checking if shard exists.

**Fix**: Wrapped shard loading in try-except block. If shard doesn't exist, treat as NEW and create fresh shard.

```python
# BEFORE (buggy)
else:
    shard = self._load_shard_v2(book_id, topic_key, subtopic_key)
    # merge logic...

# AFTER (fixed)
else:
    try:
        shard = self._load_shard_v2(book_id, topic_key, subtopic_key)
        # merge logic...
    except Exception as e:
        logger.warning(f"Shard not found, creating new: {topic_key}/{subtopic_key}")
        shard = SubtopicShardV2(...)  # Create new shard
```

**Status**: ✅ Fixed

---

### Bug #2: Missing S3Client.download_text() Method
**Date**: 2025-11-05
**Severity**: Critical (Blocking)

**Problem**: Orchestrator V2 called `self.s3.download_text(page_key)` but S3Client only has:
- `download_bytes()`
- `download_json()`
- `download_file()`

**Error**:
```
AttributeError: 'S3Client' object has no attribute 'download_text'
```

**Root Cause**: Assumed S3Client had a text download method, but it only returns bytes.

**Fix**: Updated `_load_page_text()` to use `download_bytes()` and decode to UTF-8. Added fallback for alternate S3 key paths.

```python
# BEFORE (buggy)
def _load_page_text(self, book_id: str, page_num: int) -> str:
    page_key = f"books/{book_id}/pages/{page_num:03d}.ocr.txt"
    return self.s3.download_text(page_key)  # Doesn't exist!

# AFTER (fixed)
def _load_page_text(self, book_id: str, page_num: int) -> str:
    page_key = f"books/{book_id}/pages/{page_num:03d}.ocr.txt"
    try:
        text_bytes = self.s3.download_bytes(page_key)
        return text_bytes.decode('utf-8')
    except Exception:
        # Fallback: try alternate path
        page_key = f"books/{book_id}/{page_num}.txt"
        text_bytes = self.s3.download_bytes(page_key)
        return text_bytes.decode('utf-8')
```

**Status**: ✅ Fixed

---

**Last Updated**: 2025-11-05
**Status**: Implementation Complete, Bug Fixing in Progress
