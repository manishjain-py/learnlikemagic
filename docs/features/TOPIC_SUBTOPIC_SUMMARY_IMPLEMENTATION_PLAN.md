# Topic/Subtopic Summary Feature - Implementation Plan

## Executive Summary

Add one-line summaries (15-40 words) to topics and subtopics, auto-generated via LLM and kept in sync across S3 shards, index, and database. Estimated effort: ~6-8 hours implementation + 2-3 hours testing.

**Impact:** Enables token-efficient operations for merging, deduplication, and consolidation without parsing full guidelines text.

---

## Phase 1: Data Model Updates

### 1.1 Update SubtopicShard Model

**File:** `llm-backend/features/book_ingestion/models/guideline_models.py`
**Location:** Lines 30-59 (SubtopicShard class)

```python
# CURRENT (line 30-59)
class SubtopicShard(BaseModel):
    """A shard containing guidelines for a single subtopic."""
    topic_key: str
    topic_title: str
    subtopic_key: str
    subtopic_title: str
    source_page_start: int
    source_page_end: int
    guidelines: str
    version: int
    created_at: datetime
    updated_at: datetime

# ADD after subtopic_title (line ~37):
    subtopic_summary: str = ""  # One-line summary (15-30 words)
```

**Change:** Add `subtopic_summary: str = ""` field with empty default for backward compatibility with existing shards.

### 1.2 Update Index Entry Models

**File:** `llm-backend/features/book_ingestion/models/guideline_models.py`
**Location:** Lines 66-80

```python
# CURRENT SubtopicIndexEntry (lines 66-73)
class SubtopicIndexEntry(BaseModel):
    subtopic_key: str
    subtopic_title: str
    status: Literal["open", "stable", "final", "needs_review"]
    page_range: str

# ADD after subtopic_title:
    subtopic_summary: str = ""  # One-line summary (15-30 words)


# CURRENT TopicIndexEntry (lines 76-80)
class TopicIndexEntry(BaseModel):
    topic_key: str
    topic_title: str
    subtopics: List[SubtopicIndexEntry]

# ADD after topic_title:
    topic_summary: str = ""  # Aggregated summary (20-40 words)
```

### 1.3 Update TeachingGuideline Database Model

**File:** `llm-backend/models/database.py`
**Location:** Lines 60-120 (TeachingGuideline class)

```python
# ADD after existing columns (around line 85):
    topic_summary = Column(Text, nullable=True)      # Topic-level summary (20-40 words)
    subtopic_summary = Column(Text, nullable=True)   # Subtopic-level summary (15-30 words)
```

### 1.4 Create Database Migration

**File:** `llm-backend/alembic/versions/xxxx_add_summary_columns.py` (NEW)

```python
"""Add topic_summary and subtopic_summary columns to teaching_guidelines

Revision ID: xxxx
Revises: [previous_revision]
Create Date: 2024-xx-xx
"""
from alembic import op
import sqlalchemy as sa

revision = 'xxxx_add_summary_columns'
down_revision = '[previous_revision]'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('teaching_guidelines',
        sa.Column('topic_summary', sa.Text(), nullable=True))
    op.add_column('teaching_guidelines',
        sa.Column('subtopic_summary', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('teaching_guidelines', 'subtopic_summary')
    op.drop_column('teaching_guidelines', 'topic_summary')
```

**Alternative (if not using Alembic):** Add to `llm-backend/features/book_ingestion/migrations.py`

---

## Phase 2: Create TopicSubtopicSummaryService

### 2.1 Create Service File

**File:** `llm-backend/features/book_ingestion/services/topic_subtopic_summary_service.py` (NEW)

```python
"""
TopicSubtopicSummaryService - Generates one-line summaries for topics and subtopics.

Usage:
    service = TopicSubtopicSummaryService(openai_client)
    subtopic_summary = await service.generate_subtopic_summary(title, guidelines)
    topic_summary = await service.generate_topic_summary(title, subtopic_summaries)
"""
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class TopicSubtopicSummaryService:
    """Generates and updates one-line summaries for topics and subtopics."""

    def __init__(self, openai_client):
        self.openai_client = openai_client
        self.subtopic_prompt = self._load_prompt("subtopic_summary.txt")
        self.topic_prompt = self._load_prompt("topic_summary.txt")

    async def generate_subtopic_summary(
        self,
        subtopic_title: str,
        guidelines: str,
        max_chars: int = 3000
    ) -> str:
        """
        Generate one-line summary from guidelines text.

        Args:
            subtopic_title: Human-readable subtopic name
            guidelines: Full guidelines text (truncated if >max_chars)
            max_chars: Maximum characters to send to LLM

        Returns:
            One-line summary (15-30 words)
        """
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.3,
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": self.subtopic_prompt.format(
                        subtopic_title=subtopic_title,
                        guidelines=guidelines[:max_chars]
                    )
                }]
            )
            summary = response.choices[0].message.content.strip()
            logger.info(f"Generated subtopic summary for '{subtopic_title}': {len(summary.split())} words")
            return summary
        except Exception as e:
            logger.error(f"Failed to generate subtopic summary for '{subtopic_title}': {e}")
            return self._fallback_summary(subtopic_title)

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
        if not subtopic_summaries:
            return self._fallback_summary(topic_title)

        # Single subtopic case: rephrase the subtopic summary
        if len(subtopic_summaries) == 1:
            logger.info(f"Single subtopic for '{topic_title}', using subtopic summary as base")
            # Still call LLM to rephrase at topic level

        formatted_subtopics = "\n".join(f"- {s}" for s in subtopic_summaries)

        try:
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
            summary = response.choices[0].message.content.strip()
            logger.info(f"Generated topic summary for '{topic_title}': {len(summary.split())} words")
            return summary
        except Exception as e:
            logger.error(f"Failed to generate topic summary for '{topic_title}': {e}")
            return self._fallback_summary(topic_title)

    def _fallback_summary(self, title: str) -> str:
        """Generate fallback summary when LLM fails."""
        return f"{title} - teaching guidelines"

    def _load_prompt(self, filename: str) -> str:
        """Load prompt template from prompts directory."""
        prompt_path = Path(__file__).parent.parent / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text()
        else:
            logger.warning(f"Prompt file not found: {prompt_path}")
            return self._default_prompt(filename)

    def _default_prompt(self, filename: str) -> str:
        """Return default prompt if file not found."""
        if "subtopic" in filename:
            return """Summarize this teaching guideline in ONE concise line (15-30 words).
SUBTOPIC: {subtopic_title}
GUIDELINES: {guidelines}
Return ONLY the summary line."""
        else:
            return """Create a topic-level summary (20-40 words) from subtopic summaries.
TOPIC: {topic_title}
SUBTOPICS: {subtopic_summaries}
Return ONLY the summary line."""
```

### 2.2 Create Prompts

**File:** `llm-backend/features/book_ingestion/prompts/subtopic_summary.txt` (NEW)

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

**File:** `llm-backend/features/book_ingestion/prompts/topic_summary.txt` (NEW)

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

---

## Phase 3: Pipeline Integration

### 3.1 Update GuidelineExtractionOrchestrator

**File:** `llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator.py`

#### 3.1.1 Add Service Initialization

**Location:** Lines 80-108 (`__init__` method)

```python
# ADD import at top of file:
from .topic_subtopic_summary_service import TopicSubtopicSummaryService

# ADD in __init__ (around line 105):
self.summary_service = TopicSubtopicSummaryService(openai_client)
```

#### 3.1.2 Update process_page Method

**Location:** Lines 237-420 (`process_page` method)

Find the section after shard creation/merge (approximately lines 350-380). Add summary generation:

```python
# AFTER shard is created or merged (around line 370):

# === NEW: Generate subtopic summary ===
subtopic_summary = await self.summary_service.generate_subtopic_summary(
    subtopic_title=shard.subtopic_title,
    guidelines=shard.guidelines
)
shard.subtopic_summary = subtopic_summary

# Save shard (existing code)
await self._save_shard_v2(book_id, shard)

# === NEW: Generate topic summary ===
# Collect all subtopic summaries for this topic
topic_subtopic_summaries = await self._collect_subtopic_summaries(
    book_id, shard.topic_key
)
topic_summary = await self.summary_service.generate_topic_summary(
    topic_title=shard.topic_title,
    subtopic_summaries=topic_subtopic_summaries
)

# Update indices with summaries (modify existing call)
await self._update_indices(
    book_id, page_num, shard,
    subtopic_summary=subtopic_summary,
    topic_summary=topic_summary
)
```

#### 3.1.3 Add Helper Method for Collecting Summaries

**Location:** Add after line 743 (after `_load_all_shards_v2`)

```python
async def _collect_subtopic_summaries(
    self,
    book_id: str,
    topic_key: str
) -> List[str]:
    """Collect all subtopic summaries for a topic."""
    try:
        index = await self.index_service.load_index(book_id)
        for topic in index.topics:
            if topic.topic_key == topic_key:
                return [
                    st.subtopic_summary
                    for st in topic.subtopics
                    if st.subtopic_summary
                ]
        return []
    except Exception as e:
        logger.warning(f"Could not collect subtopic summaries: {e}")
        return []
```

#### 3.1.4 Update _update_indices Method Signature

**Location:** Lines 744-780 (`_update_indices` method)

```python
# CHANGE signature from:
async def _update_indices(self, book_id: str, page_num: int, shard: SubtopicShard):

# TO:
async def _update_indices(
    self,
    book_id: str,
    page_num: int,
    shard: SubtopicShard,
    subtopic_summary: str = "",
    topic_summary: str = ""
):
```

Then pass summaries to `IndexManagementService` calls inside this method.

### 3.2 Update IndexManagementService

**File:** `llm-backend/features/book_ingestion/services/index_management_service.py`

#### 3.2.1 Update add_or_update_subtopic Method

**Location:** Lines 161-243

```python
# CHANGE signature from:
def add_or_update_subtopic(
    self,
    index: GuidelinesIndex,
    topic_key: str,
    topic_title: str,
    subtopic_key: str,
    subtopic_title: str,
    status: str,
    page_range: str
) -> GuidelinesIndex:

# TO:
def add_or_update_subtopic(
    self,
    index: GuidelinesIndex,
    topic_key: str,
    topic_title: str,
    subtopic_key: str,
    subtopic_title: str,
    status: str,
    page_range: str,
    subtopic_summary: str = "",
    topic_summary: str = ""
) -> GuidelinesIndex:
```

**Inside the method, update the subtopic entry creation (around line 210):**

```python
# When creating/updating SubtopicIndexEntry:
subtopic_entry = SubtopicIndexEntry(
    subtopic_key=subtopic_key,
    subtopic_title=subtopic_title,
    subtopic_summary=subtopic_summary,  # NEW
    status=status,
    page_range=page_range
)

# When updating TopicIndexEntry:
topic_entry.topic_summary = topic_summary  # NEW (if topic_summary provided)
```

### 3.3 Update DBSyncService

**File:** `llm-backend/features/book_ingestion/services/db_sync_service.py`

#### 3.3.1 Update _insert_guideline Method

**Location:** Lines 136-205

Add summary columns to the INSERT:

```python
# FIND the INSERT statement (around line 170)
# ADD to the column list:
    topic_summary=topic_summary,      # NEW: From index
    subtopic_summary=shard.subtopic_summary,  # NEW: From shard
```

#### 3.3.2 Update _update_guideline Method

**Location:** Lines 207-266

Add summary columns to the UPDATE:

```python
# ADD to the update dict:
    "topic_summary": topic_summary,
    "subtopic_summary": shard.subtopic_summary,
```

#### 3.3.3 Update sync_book_guidelines Method

**Location:** Lines 308-428

The method needs to pass `topic_summary` from index when syncing each shard:

```python
# Around line 380, when calling sync_shard:
# Load topic_summary from index for this shard's topic
topic_summary = ""
for topic in index.topics:
    if topic.topic_key == shard.topic_key:
        topic_summary = topic.topic_summary
        break

await self.sync_shard(
    shard=shard,
    book_id=book_id,
    grade=book_metadata.get("grade"),
    subject=book_metadata.get("subject"),
    board=book_metadata.get("board"),
    country=book_metadata.get("country", "India"),
    topic_summary=topic_summary  # NEW parameter
)
```

---

## Phase 4: Finalization Integration

### 4.1 Update TopicDeduplicationService

**File:** `llm-backend/features/book_ingestion/services/topic_deduplication_service.py`

After merging duplicate shards, regenerate summaries:

```python
# After shard merge (find the merge section):

# Regenerate subtopic summary for merged shard
merged_shard.subtopic_summary = await self.summary_service.generate_subtopic_summary(
    subtopic_title=merged_shard.subtopic_title,
    guidelines=merged_shard.guidelines
)

# Topic summary will be regenerated when index is updated
```

**Note:** The `TopicDeduplicationService` may need `summary_service` injected via constructor.

### 4.2 Update finalize_book Method

**File:** `llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator.py`
**Location:** Lines 422-573

After deduplication merges are complete, regenerate topic summaries for affected topics:

```python
# Around line 530, after deduplication:

# Regenerate topic summaries for all topics (content may have changed)
index = await self.index_service.load_index(book_id)
for topic in index.topics:
    subtopic_summaries = [st.subtopic_summary for st in topic.subtopics if st.subtopic_summary]
    if subtopic_summaries:
        topic.topic_summary = await self.summary_service.generate_topic_summary(
            topic_title=topic.topic_title,
            subtopic_summaries=subtopic_summaries
        )
await self.index_service.save_index(index)
```

---

## Phase 5: Testing

### 5.1 Unit Tests

**File:** `llm-backend/features/book_ingestion/tests/test_topic_subtopic_summary_service.py` (NEW)

```python
"""Unit tests for TopicSubtopicSummaryService."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ..services.topic_subtopic_summary_service import TopicSubtopicSummaryService


class TestTopicSubtopicSummaryService:

    @pytest.fixture
    def mock_openai(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_openai):
        with patch.object(TopicSubtopicSummaryService, '_load_prompt', return_value="{subtopic_title} {guidelines}"):
            return TopicSubtopicSummaryService(mock_openai)

    @pytest.mark.asyncio
    async def test_generate_subtopic_summary_basic(self, service, mock_openai):
        """Test basic subtopic summary generation."""
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(
                content="Teaches adding fractions with same denominators by summing numerators"
            ))]
        )

        summary = await service.generate_subtopic_summary(
            "Same Denominator Addition",
            "Guidelines about adding fractions..."
        )

        assert len(summary.split()) <= 35
        assert len(summary.split()) >= 5
        mock_openai.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_topic_summary_multiple_subtopics(self, service, mock_openai):
        """Test topic summary synthesizes multiple subtopics."""
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(
                content="Covers fraction addition from basic same-denominator cases through unlike denominators"
            ))]
        )

        summary = await service.generate_topic_summary(
            "Adding Fractions",
            [
                "Teaches adding with same denominators",
                "Covers finding common denominators",
                "Explains mixed number addition"
            ]
        )

        assert len(summary.split()) <= 50
        mock_openai.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, service, mock_openai):
        """Test graceful fallback when LLM fails."""
        mock_openai.chat.completions.create.side_effect = Exception("API Error")

        summary = await service.generate_subtopic_summary(
            "Same Denominator Addition",
            "Guidelines..."
        )

        assert summary == "Same Denominator Addition - teaching guidelines"

    @pytest.mark.asyncio
    async def test_empty_subtopic_summaries(self, service, mock_openai):
        """Test topic summary with empty subtopic list."""
        summary = await service.generate_topic_summary("Empty Topic", [])
        assert summary == "Empty Topic - teaching guidelines"

    @pytest.mark.asyncio
    async def test_truncates_long_guidelines(self, service, mock_openai):
        """Test that very long guidelines are truncated."""
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Short summary"))]
        )

        long_guidelines = "x" * 5000
        await service.generate_subtopic_summary("Test", long_guidelines)

        # Verify the prompt was truncated
        call_args = mock_openai.chat.completions.create.call_args
        content = call_args.kwargs['messages'][0]['content']
        assert len(content) < 5000  # Should be truncated
```

### 5.2 Integration Tests

**File:** `llm-backend/features/book_ingestion/tests/test_summary_integration.py` (NEW)

```python
"""Integration tests for summary generation in pipeline."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSummaryIntegration:

    @pytest.mark.asyncio
    async def test_process_page_generates_summaries(self):
        """Test that process_page generates both summaries."""
        # Setup mocks for orchestrator dependencies
        # ... (full integration test setup)
        pass

    @pytest.mark.asyncio
    async def test_db_sync_includes_summaries(self):
        """Test that DB sync includes summaries in INSERT."""
        # ... (full integration test setup)
        pass

    @pytest.mark.asyncio
    async def test_finalization_regenerates_summaries(self):
        """Test that finalization regenerates summaries after dedup."""
        # ... (full integration test setup)
        pass
```

### 5.3 Manual Testing Checklist

- [ ] Upload a new book with 10+ pages
- [ ] Verify `subtopic_summary` appears in shard JSON files
- [ ] Verify `topic_summary` and `subtopic_summary` appear in `index.json`
- [ ] Run finalization, verify summaries are regenerated if needed
- [ ] Sync to database, verify columns are populated
- [ ] Query `teaching_guidelines` table, confirm both summary columns have values
- [ ] Test with LLM failure (disconnect network), verify fallback works

---

## Phase 6: Frontend Updates (Optional/Future)

### 6.1 Update TypeScript Types

**File:** `llm-frontend/src/features/admin/types/index.ts`

```typescript
// Add to existing interfaces:

interface SubtopicShard {
  // ... existing fields
  subtopic_summary: string;  // NEW
}

interface TopicIndexEntry {
  // ... existing fields
  topic_summary: string;  // NEW
}

interface SubtopicIndexEntry {
  // ... existing fields
  subtopic_summary: string;  // NEW
}

interface TeachingGuideline {
  // ... existing fields
  topic_summary: string | null;  // NEW
  subtopic_summary: string | null;  // NEW
}
```

### 6.2 Display in GuidelinesReview Page

**File:** `llm-frontend/src/features/admin/pages/GuidelinesReview.tsx`

Add summary display in the guidelines list:

```tsx
// In the guideline card/row component:
<div className="text-sm text-gray-600 italic">
  {guideline.subtopic_summary}
</div>
```

---

## Implementation Order & Dependencies

```
Phase 1: Data Models (no dependencies)
    ├── 1.1 SubtopicShard model
    ├── 1.2 Index entry models
    ├── 1.3 TeachingGuideline model
    └── 1.4 Database migration

Phase 2: Service & Prompts (depends on Phase 1)
    ├── 2.1 TopicSubtopicSummaryService
    └── 2.2 Prompt files

Phase 3: Pipeline Integration (depends on Phase 2)
    ├── 3.1 GuidelineExtractionOrchestrator
    ├── 3.2 IndexManagementService
    └── 3.3 DBSyncService

Phase 4: Finalization Integration (depends on Phase 3)
    ├── 4.1 TopicDeduplicationService
    └── 4.2 finalize_book method

Phase 5: Testing (depends on Phase 4)
    ├── 5.1 Unit tests
    ├── 5.2 Integration tests
    └── 5.3 Manual testing

Phase 6: Frontend (optional, depends on Phase 3)
    ├── 6.1 TypeScript types
    └── 6.2 UI display
```

---

## Files Changed Summary

| Action | File | Changes |
|--------|------|---------|
| **MODIFY** | `features/book_ingestion/models/guideline_models.py` | Add `subtopic_summary` to SubtopicShard, SubtopicIndexEntry; add `topic_summary` to TopicIndexEntry |
| **MODIFY** | `models/database.py` | Add `topic_summary`, `subtopic_summary` columns to TeachingGuideline |
| **CREATE** | `alembic/versions/xxxx_add_summary_columns.py` | Database migration |
| **CREATE** | `features/book_ingestion/services/topic_subtopic_summary_service.py` | New service (100 lines) |
| **CREATE** | `features/book_ingestion/prompts/subtopic_summary.txt` | New prompt |
| **CREATE** | `features/book_ingestion/prompts/topic_summary.txt` | New prompt |
| **MODIFY** | `features/book_ingestion/services/guideline_extraction_orchestrator.py` | Import service, call in process_page, add helper method |
| **MODIFY** | `features/book_ingestion/services/index_management_service.py` | Update `add_or_update_subtopic` signature and implementation |
| **MODIFY** | `features/book_ingestion/services/db_sync_service.py` | Add summary columns to INSERT/UPDATE |
| **MODIFY** | `features/book_ingestion/services/topic_deduplication_service.py` | Regenerate summaries after merge |
| **CREATE** | `features/book_ingestion/tests/test_topic_subtopic_summary_service.py` | Unit tests |
| **CREATE** | `features/book_ingestion/tests/test_summary_integration.py` | Integration tests |

---

## Cost Impact

| Operation | Cost per Call | Frequency | Total per Book |
|-----------|---------------|-----------|----------------|
| Subtopic summary | ~$0.0001 | 1 per subtopic create/update | ~$0.005 (50 subtopics) |
| Topic summary | ~$0.0001 | 1 per subtopic create/update | ~$0.005 (50 calls) |
| **Total** | | | **~$0.01 per book** |

---

## Rollback Plan

If issues arise:
1. **Model changes:** Fields have defaults, existing data unaffected
2. **Database:** Migration is additive (nullable columns), can be reversed
3. **Pipeline:** Service calls wrapped in try/catch with fallbacks
4. **Feature flag:** Can add `ENABLE_SUMMARY_GENERATION=false` env var to skip

---

## Open Questions

1. **Should summaries be editable by admins?** (Currently auto-generated only)
2. **Should we regenerate summaries on name refinement?** (Currently: no, summaries are content-based)
3. **Should ContextPack use summaries instead of full guidelines?** (Future optimization)

---

## Approval Checklist

- [ ] Phase 1-4 implementation complete
- [ ] Unit tests passing
- [ ] Integration tests passing
- [ ] Manual testing complete
- [ ] Database migration tested on staging
- [ ] Cost analysis confirmed
- [ ] Ready for production deployment
