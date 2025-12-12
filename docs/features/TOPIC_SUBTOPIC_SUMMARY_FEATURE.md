# Topic/Subtopic Summary Feature - Design Document

## Overview

A **one-line summary** for each topic and subtopic that concisely describes "what is this about" - automatically generated and kept in sync across all storage locations as content evolves during the book ingestion pipeline.

## Problem Statement

Currently, when the system needs to understand what a topic/subtopic covers:

| Operation | Current Approach | Problem |
|-----------|------------------|---------|
| **Merging** | Read full guidelines text (500+ words) | Slow, token-heavy |
| **Deduplication** | Compare full text of multiple subtopics | Expensive LLM calls |
| **Consolidation** | No quick semantic understanding | Must parse entire content |
| **Boundary Detection** | Open topics have full guidelines in ContextPack | Token inefficient |

**Missing**: A concise, always-current summary that enables quick semantic understanding without parsing full guidelines.

## Solution

| Level | Summary Format | Length | Example |
|-------|----------------|--------|---------|
| **Subtopic** | One line describing what this subtopic teaches | 15-30 words | "Teaches adding fractions with same denominators by summing numerators while keeping denominator unchanged" |
| **Topic** | One line synthesizing all subtopic summaries | 20-40 words | "Covers fraction addition from basic same-denominator cases through unlike denominators using visual models and algorithms" |

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Scope** | Both topic and subtopic levels | Full hierarchy coverage for all use cases |
| **Storage** | Shard + Index + Database (all locations) | Available at every stage of pipeline |
| **Length** | Single line (15-40 words) | Quick parsing, token efficient, easy to scan |
| **Update strategy** | Real-time on content change | Always current for downstream consumers |
| **LLM model** | gpt-4o-mini | Cost-efficient, sufficient quality for summarization |
| **Regeneration** | Full regeneration on change | Ensures consistency, avoids drift |

## Relationship to Book Summary Feature

This is a **separate feature** from the Book Summary feature (see `BOOK_SUMMARY_FEATURE.md`).

| Aspect | Book Summary | Topic/Subtopic Summary |
|--------|--------------|------------------------|
| **Question answered** | "What has the book covered so far?" | "What does this specific topic/subtopic teach?" |
| **Scope** | Entire book (rolling, progressive) | Per topic/subtopic (discrete units) |
| **Format** | Chapters + recent pages (~500 tokens) | Single line per unit (15-40 words) |
| **Update trigger** | Every page processed | When subtopic content changes |
| **Storage** | `book_summary.json` only | Shard + Index + Database |
| **Primary consumer** | BoundaryDetectionService (global context) | MergeService, DeduplicationService, ConsolidationService |
| **Growth pattern** | Bounded by consolidation | Grows with topic/subtopic count |

## Data Model Changes

### 1. SubtopicShard (add field)

**File**: `llm-backend/features/book_ingestion/models/guideline_models.py`

```python
class SubtopicShard(BaseModel):
    """A shard containing guidelines for a single subtopic."""
    topic_key: str
    topic_title: str
    subtopic_key: str
    subtopic_title: str
    subtopic_summary: str          # NEW: One-line summary (15-30 words)
    source_page_start: int
    source_page_end: int
    guidelines: str
    version: int
    created_at: datetime
    updated_at: datetime
```

### 2. GuidelinesIndex (add fields)

**File**: `llm-backend/features/book_ingestion/models/guideline_models.py`

```python
class TopicIndexEntry(BaseModel):
    """Entry for a topic in the guidelines index."""
    topic_key: str
    topic_title: str
    topic_summary: str             # NEW: Aggregated summary (20-40 words)
    subtopics: List[SubtopicIndexEntry]

class SubtopicIndexEntry(BaseModel):
    """Entry for a subtopic in the guidelines index."""
    subtopic_key: str
    subtopic_title: str
    subtopic_summary: str          # NEW: One-line summary (15-30 words)
    status: Literal["open", "stable", "final", "needs_review"]
    page_range: str
```

### 3. TeachingGuideline Table (add columns)

**File**: `llm-backend/models/database.py`

```python
class TeachingGuideline(Base):
    """Production guidelines for tutor workflow."""
    __tablename__ = "teaching_guidelines"

    # ... existing columns ...

    topic_summary = Column(Text, nullable=True)      # NEW: Topic-level summary
    subtopic_summary = Column(Text, nullable=True)   # NEW: Subtopic-level summary
```

**Migration SQL**:
```sql
ALTER TABLE teaching_guidelines ADD COLUMN topic_summary TEXT;
ALTER TABLE teaching_guidelines ADD COLUMN subtopic_summary TEXT;
```

## S3 Storage Structure

```
books/{book_id}/
├── guidelines/
│   ├── index.json                              # Includes topic_summary, subtopic_summary
│   │   {
│   │     "topics": [{
│   │       "topic_key": "adding-fractions",
│   │       "topic_title": "Adding Fractions",
│   │       "topic_summary": "Covers fraction addition...",  ◄── NEW
│   │       "subtopics": [{
│   │         "subtopic_key": "same-denominator",
│   │         "subtopic_title": "Same Denominator Addition",
│   │         "subtopic_summary": "Teaches adding fractions...",  ◄── NEW
│   │         "status": "stable",
│   │         "page_range": "5-8"
│   │       }]
│   │     }]
│   │   }
│   ├── page_index.json
│   └── topics/
│       └── {topic_key}/
│           └── subtopics/
│               └── {subtopic_key}.latest.json  # Includes subtopic_summary
│                   {
│                     "subtopic_summary": "Teaches adding...",  ◄── NEW
│                     "guidelines": "...",
│                     ...
│                   }
├── summaries/
│   └── book_summary.json                       # From Book Summary feature (separate)
└── pages/
    └── ...
```

## Implementation Components

### 1. Service: TopicSubtopicSummaryService

**File**: `llm-backend/features/book_ingestion/services/topic_subtopic_summary_service.py`

```python
class TopicSubtopicSummaryService:
    """Generates and updates one-line summaries for topics and subtopics."""

    def __init__(self, openai_client):
        self.openai_client = openai_client
        self.subtopic_prompt = self._load_prompt("subtopic_summary.txt")
        self.topic_prompt = self._load_prompt("topic_summary.txt")

    async def generate_subtopic_summary(
        self,
        subtopic_title: str,
        guidelines: str
    ) -> str:
        """
        Generate one-line summary from guidelines text.

        Args:
            subtopic_title: Human-readable subtopic name
            guidelines: Full guidelines text (will be truncated if >3000 chars)

        Returns:
            One-line summary (15-30 words)
        """
        response = await self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": self.subtopic_prompt.format(
                    subtopic_title=subtopic_title,
                    guidelines=guidelines[:3000]
                )
            }]
        )
        return response.choices[0].message.content.strip()

    async def generate_topic_summary(
        self,
        topic_title: str,
        subtopic_summaries: List[str]
    ) -> str:
        """
        Generate topic summary by synthesizing subtopic summaries.

        Args:
            topic_title: Human-readable topic name
            subtopic_summaries: List of subtopic summary strings

        Returns:
            One-line topic summary (20-40 words)
        """
        formatted_subtopics = "\n".join(f"- {s}" for s in subtopic_summaries)

        response = await self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": self.topic_prompt.format(
                    topic_title=topic_title,
                    subtopic_summaries=formatted_subtopics
                )
            }]
        )
        return response.choices[0].message.content.strip()

    def _load_prompt(self, filename: str) -> str:
        """Load prompt template from file."""
        prompt_path = Path(__file__).parent.parent / "prompts" / filename
        return prompt_path.read_text()
```

### 2. Prompt: subtopic_summary.txt

**File**: `llm-backend/features/book_ingestion/prompts/subtopic_summary.txt`

```
Summarize this teaching guideline in ONE concise line.

SUBTOPIC: {subtopic_title}

GUIDELINES:
{guidelines}

TASK:
Write a single line (15-30 words) capturing what this subtopic teaches.
Include: the core concept, key technique/method, and learning outcome.

EXAMPLES:
- Teaches adding fractions with same denominators by summing numerators while keeping the denominator unchanged
- Introduces place value concepts using base-10 blocks to represent ones, tens, and hundreds
- Covers multi-digit subtraction with regrouping through step-by-step borrowing procedures
- Explains equivalent fractions using visual fraction strips and multiplication relationships

OUTPUT:
Return ONLY the summary line. No quotes, no bullet point, no explanation, no prefix.
```

### 3. Prompt: topic_summary.txt

**File**: `llm-backend/features/book_ingestion/prompts/topic_summary.txt`

```
Create a topic-level summary from its subtopic summaries.

TOPIC: {topic_title}

SUBTOPICS:
{subtopic_summaries}

TASK:
Write ONE line (20-40 words) synthesizing what this entire topic covers.
Capture the progression and scope across all subtopics.

EXAMPLES:
- Covers fraction addition from basic same-denominator cases through unlike denominators, including visual models, common denominator algorithms, and mixed number operations
- Teaches place value system from ones through thousands, with base-10 representations, number comparison, rounding, and ordering strategies
- Develops multiplication skills from basic facts through multi-digit procedures, covering arrays, area models, partial products, and standard algorithm

OUTPUT:
Return ONLY the summary line. No quotes, no bullet point, no explanation, no prefix.
```

## Update Triggers

### Trigger 1: New Subtopic Created

**When**: `BoundaryDetectionService` returns `is_new_topic=True`

**Flow**:
```
1. Create new SubtopicShard with initial guidelines
2. Generate subtopic_summary from guidelines
3. Store subtopic_summary in shard
4. Save shard to S3
5. Add subtopic entry to index (with subtopic_summary)
6. Collect all subtopic_summaries for this topic
7. Generate/regenerate topic_summary
8. Update topic entry in index (with topic_summary)
9. Save index to S3
```

### Trigger 2: Existing Subtopic Merged

**When**: `BoundaryDetectionService` returns `is_new_topic=False`

**Flow**:
```
1. Load existing shard
2. Merge new page guidelines into existing guidelines
3. Regenerate subtopic_summary (content changed)
4. Update shard with new subtopic_summary
5. Save shard to S3
6. Update subtopic entry in index
7. Regenerate topic_summary (subtopic content changed)
8. Update topic entry in index
9. Save index to S3
```

### Trigger 3: During Finalization

**When**: `POST /admin/books/{id}/finalize`

**Flow**:
```
TopicNameRefinementService:
  - Names may change, summaries likely still valid
  - Optional: Regenerate if summary references old name explicitly

TopicDeduplicationService:
  - Identifies duplicate subtopics
  - Merges duplicate shards into one
  - Regenerate subtopic_summary for merged shard
  - Delete redundant shard
  - Regenerate topic_summary for affected topic
```

### Trigger 4: Database Sync

**When**: `PUT /admin/books/{id}/guidelines/approve`

**Flow**:
```
DBSyncService.sync_shard():
  - Read topic_summary from index
  - Read subtopic_summary from shard
  - Include both in INSERT statement:

    INSERT INTO teaching_guidelines (
        ...existing columns...,
        topic_summary,        ← From index
        subtopic_summary      ← From shard
    )
```

## Processing Flow (Complete Pipeline)

```
Page N arrives for processing:

 1. LOAD_OCR
    └── Read: books/{book_id}/pages/{N:03d}.ocr.txt

 2. GENERATE_MINISUMMARY
    └── LLM: page_text → 5-6 sentence summary

 3. BUILD_CONTEXT_PACK
    ├── Load: index.json (includes topic/subtopic summaries)
    ├── Load: Last 5 page summaries
    ├── Load: Open topic shards
    └── Load: book_summary.json (from Book Summary feature)

 4. BOUNDARY_DETECTION
    ├── Input: context_pack + page_text
    └── Output: is_new_topic, topic_key, subtopic_key, guidelines

 5. CREATE_OR_MERGE_SHARD
    ├── If is_new_topic: Create new SubtopicShard
    └── Else: Load existing shard + merge guidelines

 6. GENERATE_SUBTOPIC_SUMMARY  ◄── THIS FEATURE
    ├── LLM: guidelines → subtopic_summary (15-30 words)
    └── Store in shard.subtopic_summary

 7. SAVE_SHARD
    └── Write: topics/{topic_key}/subtopics/{subtopic_key}.latest.json

 8. UPDATE_SUBTOPIC_INDEX_ENTRY
    └── Update/add subtopic entry with subtopic_summary

 9. GENERATE_TOPIC_SUMMARY  ◄── THIS FEATURE
    ├── Collect all subtopic_summaries for this topic
    ├── LLM: subtopic_summaries → topic_summary (20-40 words)
    └── Update topic entry with topic_summary

10. SAVE_INDICES
    └── Write: index.json, page_index.json

11. SAVE_PAGE_GUIDELINE
    └── Write: pages/{N:03d}.page_guideline.json

12. UPDATE_BOOK_SUMMARY (Book Summary feature)
    └── LLM: update rolling book summary

13. CHECK_STABILITY
    └── Mark subtopic "stable" if 5-page gap
```

## Use Cases

### Primary: Consolidation & Merging

#### 1. Smarter Merge Decisions

```python
# Current: Must read full guidelines to understand context
existing_shard = load_shard(book_id, topic_key, subtopic_key)
# existing_shard.guidelines could be 500+ words

# With summaries: Quick semantic check
if semantic_similarity(existing_shard.subtopic_summary, page_content_summary) > threshold:
    # High confidence: merge into existing
    merge_into_shard(existing_shard, new_guidelines)
else:
    # Low similarity: might be new subtopic, investigate further
    ...
```

#### 2. Efficient Deduplication

```python
# Current: Compare full text of all subtopics (expensive)
for shard_a, shard_b in combinations(all_shards, 2):
    similarity = llm_compare(shard_a.guidelines, shard_b.guidelines)  # Costly

# With summaries: Two-phase approach
# Phase 1: Quick filter using summaries (cheap)
candidates = []
for shard_a, shard_b in combinations(all_shards, 2):
    if embedding_similarity(shard_a.subtopic_summary, shard_b.subtopic_summary) > 0.8:
        candidates.append((shard_a, shard_b))

# Phase 2: Full comparison only on candidates (fewer calls)
for shard_a, shard_b in candidates:
    if llm_confirm_duplicate(shard_a.guidelines, shard_b.guidelines):
        merge_shards(shard_a, shard_b)
```

#### 3. ContextPack Optimization (Future Enhancement)

```python
# Current ContextPack.open_topics includes full guidelines
class OpenTopicInfo:
    topic_key: str
    topic_title: str
    guidelines: str  # 500+ words per subtopic

# Enhanced: Include summaries for quick scanning
class OpenTopicInfo:
    topic_key: str
    topic_title: str
    topic_summary: str           # 20-40 words - quick overview
    subtopics: List[OpenSubtopicInfo]

class OpenSubtopicInfo:
    subtopic_key: str
    subtopic_title: str
    subtopic_summary: str        # 15-30 words - quick overview
    guidelines: str              # Full text (load on demand?)

# BoundaryDetection can:
# 1. Scan summaries to understand existing topic landscape
# 2. Request full guidelines only for most relevant topics
# 3. Better token efficiency in context window
```

### Secondary: Admin UI (Future)

```
┌─────────────────────────────────────────────────────────────┐
│ Guidelines Review                                            │
├─────────────────────────────────────────────────────────────┤
│ Topic: Adding Fractions                                      │
│ Summary: Covers fraction addition from same-denominator...   │
│                                                              │
│ ├── Same Denominator Addition                               │
│ │   Summary: Teaches adding fractions with same denominators │
│ │   [View Full Guidelines]                                  │
│ │                                                           │
│ ├── Unlike Denominators                                     │
│ │   Summary: Covers finding common denominators and adding  │
│ │   [View Full Guidelines]                                  │
└─────────────────────────────────────────────────────────────┘
```

## Edge Cases

| Scenario | Handling |
|----------|----------|
| **First subtopic in a topic** | `topic_summary` = rephrased `subtopic_summary` (single subtopic) |
| **Single-page subtopic** | Generate summary from minimal guidelines (may be brief) |
| **Very long guidelines (>3000 chars)** | Truncate to 3000 chars before passing to LLM |
| **Topic with 10+ subtopics** | LLM synthesizes all into concise 20-40 word topic_summary |
| **LLM returns too-long summary** | Truncate at sentence boundary, log warning |
| **LLM call fails** | Use fallback: `"{title} - teaching guidelines"`, log error, continue pipeline |
| **Deduplication merges 2 subtopics** | Regenerate summary from combined/merged guidelines |
| **Name refinement changes titles** | Summaries remain valid (content-based, not name-based) |
| **Re-processing subset of pages** | Affected subtopic summaries regenerated, topic summary regenerated |

## Error Handling

```python
async def generate_subtopic_summary_safe(
    self,
    subtopic_title: str,
    guidelines: str
) -> str:
    """Generate summary with fallback on failure."""
    try:
        return await self.generate_subtopic_summary(subtopic_title, guidelines)
    except Exception as e:
        logger.error(f"Failed to generate subtopic summary: {e}")
        # Fallback: Use title as minimal summary
        return f"{subtopic_title} - teaching guidelines"
```

## Cost Analysis

| LLM Call | Frequency | Model | Input Tokens | Output Tokens | Est. Cost |
|----------|-----------|-------|--------------|---------------|-----------|
| Subtopic summary | 1 per subtopic create/update | gpt-4o-mini | ~800 | ~50 | ~$0.0001 |
| Topic summary | 1 per subtopic create/update | gpt-4o-mini | ~200 | ~60 | ~$0.0001 |
| **Total per page** | ~2 calls (if content changes) | | | | ~$0.0002 |

**For a 200-page book**:
- Assuming ~50 subtopics created/updated
- Subtopic summaries: 50 × $0.0001 = $0.005
- Topic summaries: 50 × $0.0001 = $0.005
- **Total additional cost**: ~$0.01

Combined with Book Summary feature (~$0.02), total additional cost: ~$0.03 per book.

## Testing Strategy

### Unit Tests

```python
# test_topic_subtopic_summary_service.py

async def test_generate_subtopic_summary_basic():
    """Test basic subtopic summary generation."""
    service = TopicSubtopicSummaryService(mock_openai)
    summary = await service.generate_subtopic_summary(
        "Same Denominator Addition",
        "Guidelines about adding fractions with same denominators..."
    )
    assert len(summary.split()) <= 35  # Max ~30 words + buffer
    assert len(summary.split()) >= 10  # Min ~15 words

async def test_generate_topic_summary_single_subtopic():
    """Test topic summary with single subtopic."""
    service = TopicSubtopicSummaryService(mock_openai)
    summary = await service.generate_topic_summary(
        "Adding Fractions",
        ["Teaches adding fractions with same denominators..."]
    )
    assert len(summary.split()) <= 50  # Max ~40 words + buffer

async def test_generate_topic_summary_multiple_subtopics():
    """Test topic summary synthesizes multiple subtopics."""
    service = TopicSubtopicSummaryService(mock_openai)
    summary = await service.generate_topic_summary(
        "Adding Fractions",
        [
            "Teaches adding with same denominators...",
            "Covers finding common denominators...",
            "Explains mixed number addition..."
        ]
    )
    # Summary should synthesize, not just concatenate
    assert len(summary.split()) <= 50

async def test_fallback_on_llm_failure():
    """Test graceful fallback when LLM fails."""
    mock_openai.chat.completions.create.side_effect = Exception("API Error")
    service = TopicSubtopicSummaryService(mock_openai)
    summary = await service.generate_subtopic_summary_safe(
        "Same Denominator Addition",
        "Guidelines..."
    )
    assert summary == "Same Denominator Addition - teaching guidelines"
```

### Integration Tests

```python
async def test_process_page_generates_summaries():
    """Test that process_page generates both summaries."""
    orchestrator = GuidelineExtractionOrchestrator(...)
    await orchestrator.process_page(book_id, page_num=5, metadata)

    # Check shard has subtopic_summary
    shard = await load_shard(book_id, topic_key, subtopic_key)
    assert shard.subtopic_summary is not None
    assert len(shard.subtopic_summary) > 0

    # Check index has both summaries
    index = await load_index(book_id)
    topic_entry = index.get_topic(topic_key)
    assert topic_entry.topic_summary is not None
    subtopic_entry = topic_entry.get_subtopic(subtopic_key)
    assert subtopic_entry.subtopic_summary is not None

async def test_db_sync_includes_summaries():
    """Test that DB sync includes summaries in INSERT."""
    await db_sync_service.sync_book(book_id)

    guidelines = await db.query(TeachingGuideline).filter_by(book_id=book_id).all()
    for g in guidelines:
        assert g.topic_summary is not None
        assert g.subtopic_summary is not None
```

## Implementation Checklist

### Phase 1: Data Models
- [ ] Add `subtopic_summary` field to `SubtopicShard` model
- [ ] Add `topic_summary` field to `TopicIndexEntry` model
- [ ] Add `subtopic_summary` field to `SubtopicIndexEntry` model
- [ ] Add `topic_summary` column to `TeachingGuideline` table
- [ ] Add `subtopic_summary` column to `TeachingGuideline` table
- [ ] Create database migration script

### Phase 2: Service & Prompts
- [ ] Create `TopicSubtopicSummaryService` class
- [ ] Create `subtopic_summary.txt` prompt file
- [ ] Create `topic_summary.txt` prompt file
- [ ] Add error handling with fallback

### Phase 3: Pipeline Integration
- [ ] Update `GuidelineExtractionOrchestrator.process_page()`:
  - [ ] Call `generate_subtopic_summary()` after shard create/merge
  - [ ] Call `generate_topic_summary()` after index update
- [ ] Update `IndexManagementService`:
  - [ ] Store `subtopic_summary` in subtopic entries
  - [ ] Store `topic_summary` in topic entries
- [ ] Update `DBSyncService.sync_shard()`:
  - [ ] Include `topic_summary` in INSERT
  - [ ] Include `subtopic_summary` in INSERT

### Phase 4: Finalization Integration
- [ ] Update `TopicDeduplicationService`:
  - [ ] Regenerate `subtopic_summary` after merge
  - [ ] Regenerate `topic_summary` after changes

### Phase 5: Testing
- [ ] Write unit tests for `TopicSubtopicSummaryService`
- [ ] Write integration tests for pipeline flow
- [ ] Write integration tests for DB sync
- [ ] Manual testing with sample book

### Phase 6: Frontend (Future/Optional)
- [ ] Update TypeScript types to include summaries
- [ ] Display summaries in GuidelinesReview page
- [ ] Display summaries in BookDetail page

## Dependencies

- **Existing**: `openai`, `boto3`, `pydantic`, `sqlalchemy`
- **New**: None (uses existing OpenAI client)

## Files to Create/Modify

| Action | File | Changes |
|--------|------|---------|
| **Create** | `services/topic_subtopic_summary_service.py` | New service class |
| **Create** | `prompts/subtopic_summary.txt` | New prompt |
| **Create** | `prompts/topic_summary.txt` | New prompt |
| **Modify** | `models/guideline_models.py` | Add summary fields to models |
| **Modify** | `models/database.py` (main) | Add columns to TeachingGuideline |
| **Modify** | `services/guideline_extraction_orchestrator.py` | Call summary service |
| **Modify** | `services/index_management_service.py` | Store summaries in index |
| **Modify** | `services/db_sync_service.py` | Include summaries in INSERT |
| **Modify** | `services/topic_deduplication_service.py` | Regenerate after merge |
| **Create** | `migrations/xxx_add_summary_columns.py` | Database migration |

## Open Questions (For Future Consideration)

1. **Should summaries be editable by admins?** Currently auto-generated only.
2. **Should we version summaries separately?** Currently tied to shard version.
3. **Should summaries be included in ContextPack?** Could optimize token usage.
4. **Should we use embeddings for similarity checks?** Currently using LLM for comparison.
