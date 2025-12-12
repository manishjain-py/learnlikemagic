# Book Summary Feature - Design Document

## Overview

A progressive, rolling book summary that builds up as pages are processed during the book ingestion pipeline. Provides high-level context about "what the book is about so far" to downstream components like boundary detection and guideline generation.

## Problem Statement

Currently, boundary detection has access to:
- Current page text
- Last 5 page summaries (recent context)
- Open topics with their guidelines
- TOC hints

**Missing**: A holistic view of the entire book processed so far. When on page 100, the system doesn't know what happened in pages 1-94 (only 95-99 via recent summaries). This limits the LLM's ability to make informed decisions about topic boundaries and guideline extraction.

## Solution

A **single compact string** summarizing the entire book processed so far, updated after each page, stored in S3, and provided as input to boundary detection.

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Format** | Single concatenated string | Easy to inject into prompts, minimal parsing |
| **Max Size** | ~500 tokens | Keeps context window usage reasonable |
| **Chapter Detection** | Inferred by LLM from page text | Simple - no separate detection logic needed |
| **Consolidation** | Page-level → Chapter-level only | No multi-chapter consolidation needed |
| **Storage** | S3 JSON file | Consistent with existing pipeline patterns |
| **Update Trigger** | After each page processed | Real-time progressive building |

## Summary Format

The summary uses a compact format with two parts:

1. **Completed chapters**: `Ch1: [1-2 sentence summary]. Ch2: [1-2 sentence summary].`
2. **Current chapter pages**: `| pN: [brief note] | pN+1: [brief note] |`

### Example Progression

**After page 5 (Chapter 1 in progress):**
```
| p1: Intro to place value | p2: Ones and tens columns | p3: Hundreds place | p4: Comparing numbers | p5: Ordering exercises |
```

**After page 16 (Chapter 2 just started):**
```
Ch1: Place value fundamentals covering ones, tens, hundreds with visual base-10 block models and comparison exercises. | p16: Addition concept intro |
```

**After page 45:**
```
Ch1: Place value fundamentals with base-10 blocks. Ch2: Addition strategies including mental math and regrouping up to 3 digits. | p31: Subtraction intro | p32: Borrowing concept | p33: Multi-digit practice | p34: Word problems | p35: Review exercises |
```

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Page N Processing                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [Existing Steps 1-8: OCR → Minisummary → Boundary → Shard → Index] │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ STEP 9 (NEW): Update Book Summary                           │    │
│  │                                                              │    │
│  │  ┌──────────────┐      ┌─────────────────────┐              │    │
│  │  │ Load from S3 │ ───► │ BookSummaryService  │              │    │
│  │  │ book_summary │      │    .update()        │              │    │
│  │  └──────────────┘      └─────────┬───────────┘              │    │
│  │                                  │                           │    │
│  │         Inputs:                  │    Output:                │    │
│  │         - current_summary        │    - updated_summary      │    │
│  │         - page_text              │      (≤500 tokens)        │    │
│  │                                  │                           │    │
│  │                                  ▼                           │    │
│  │                        ┌─────────────────┐                   │    │
│  │                        │  Save to S3     │                   │    │
│  │                        │ book_summary.json│                   │    │
│  │                        └─────────────────┘                   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Integration with Boundary Detection

```
┌────────────────────────────────────────────────────────────────┐
│                  ContextPack (Enhanced)                         │
├────────────────────────────────────────────────────────────────┤
│  book_id: str                                                   │
│  current_page: int                                              │
│  book_metadata: {grade, subject, board}                         │
│  open_topics: List[OpenTopicInfo]         ◄── existing          │
│  recent_page_summaries: List[RecentPageSummary]  ◄── existing   │
│  toc_hints: {...}                         ◄── existing          │
│  book_summary: str                        ◄── NEW               │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│              BoundaryDetectionService                           │
│                                                                 │
│  Prompt now includes:                                           │
│  "BOOK SUMMARY SO FAR:                                          │
│   {book_summary}                                                │
│                                                                 │
│   This provides context about the entire book processed so far. │
│   Use this to understand where the current page fits in the     │
│   overall narrative and topic progression."                     │
└────────────────────────────────────────────────────────────────┘
```

## S3 Storage Structure

```
books/{book_id}/
├── pages/
│   └── ... (existing)
├── guidelines/
│   └── ... (existing)
└── summaries/                          ◄── NEW DIRECTORY
    └── book_summary.json
```

### book_summary.json Schema

```json
{
  "book_id": "uuid",
  "current_page": 45,
  "summary": "Ch1: Place value fundamentals with base-10 blocks. Ch2: Addition strategies including mental math and regrouping. | p31: Subtraction intro | p32: Borrowing concept | p33: Multi-digit practice |",
  "token_count": 87,
  "version": 45,
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:45:00Z"
}
```

## Implementation Components

### 1. Model: BookSummary

**File**: `llm-backend/features/book_ingestion/models/guideline_models.py`

```python
class BookSummary(BaseModel):
    """Rolling book summary that builds progressively."""
    book_id: str
    current_page: int
    summary: str  # The compact summary string
    token_count: int  # Approximate token count
    version: int  # Increments with each update
    created_at: datetime
    updated_at: datetime
```

### 2. Service: BookSummaryService

**File**: `llm-backend/features/book_ingestion/services/book_summary_service.py`

```python
class BookSummaryService:
    """Updates the rolling book summary after each page."""

    def __init__(self, openai_client, s3_client):
        self.openai_client = openai_client
        self.s3_client = s3_client
        self.max_tokens = 500
        self.prompt_template = self._load_prompt()

    async def update(
        self,
        book_id: str,
        page_num: int,
        page_text: str,
        current_summary: Optional[str] = None
    ) -> BookSummary:
        """
        Update book summary with new page content.

        Args:
            book_id: Book identifier
            page_num: Current page number
            page_text: OCR text from current page (truncated to 2000 chars)
            current_summary: Existing summary string (None for first page)

        Returns:
            Updated BookSummary object
        """
        # 1. Call LLM to update summary
        # 2. Validate token count
        # 3. Save to S3
        # 4. Return updated BookSummary
```

### 3. Prompt: book_summary_update.txt

**File**: `llm-backend/features/book_ingestion/prompts/book_summary_update.txt`

```
You are maintaining a running summary of a textbook as it is processed page by page.

CURRENT BOOK SUMMARY:
{current_summary}

NEW PAGE TEXT (Page {page_num}):
{page_text}

TASK:
Update the book summary to include this page's content.

RULES:
1. Add a brief note (~5-10 words) about this page
2. If this page starts a NEW CHAPTER (look for "Chapter X" headers, unit titles, or major topic shifts):
   - Consolidate ALL previous page notes into 1-2 sentences for that chapter
   - Format: "ChN: [consolidated summary]."
   - Start fresh page notes for the new chapter
3. Keep the TOTAL summary under 500 tokens
4. Be extremely concise - every word must count

FORMAT:
- Completed chapters: "Ch1: [summary]. Ch2: [summary]."
- Current chapter pages: "| pN: [note] | pN+1: [note] |"

EXAMPLE OUTPUT:
"Ch1: Place value from ones to thousands with base-10 models. Ch2: Addition strategies with regrouping. | p31: Subtraction intro | p32: Borrowing concept |"

OUTPUT:
Return ONLY the updated summary string. No explanations, no formatting, just the summary.
```

### 4. Orchestrator Integration

**File**: `llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator.py`

Add to `process_page()` method after index updates:

```python
# STEP 9: Update Book Summary
book_summary = await self._update_book_summary(book_id, page_num, page_text)
```

### 5. ContextPack Enhancement

**File**: `llm-backend/features/book_ingestion/models/guideline_models.py`

```python
class ContextPack(BaseModel):
    # ... existing fields ...
    book_summary: Optional[str] = None  # NEW: Rolling book summary
```

### 6. ContextPackService Enhancement

**File**: `llm-backend/features/book_ingestion/services/context_pack_service.py`

In `build()` method, add:

```python
# Load book summary from S3
book_summary = await self._load_book_summary(book_id)
context_pack.book_summary = book_summary.summary if book_summary else None
```

### 7. Boundary Detection Prompt Update

**File**: `llm-backend/features/book_ingestion/prompts/boundary_detection.txt`

Add section:

```
BOOK SUMMARY SO FAR:
{book_summary}

This summary shows what the book has covered from page 1 to now. Use it to:
- Understand the overall progression and structure
- Identify if the current page continues existing themes or introduces new ones
- Make more informed decisions about topic boundaries
```

## Processing Flow (Complete)

```
Page N arrives for processing:

1. LOAD_OCR
   └── Read: books/{book_id}/pages/{N:03d}.ocr.txt

2. GENERATE_MINISUMMARY
   └── LLM: page_text → 5-6 sentence summary

3. BUILD_CONTEXT_PACK
   ├── Load: index.json (topics/subtopics)
   ├── Load: Last 5 page summaries
   ├── Load: Open topic shards (full guidelines)
   └── Load: book_summary.json  ◄── NEW

4. BOUNDARY_DETECTION
   ├── Input: context_pack (now includes book_summary) + page_text
   └── Output: is_new_topic, topic_key, subtopic_key, guidelines

5. CREATE_OR_MERGE_SHARD
   ├── If is_new_topic: Create new SubtopicShard
   └── Else: Load existing + merge guidelines

6. SAVE_SHARD
   └── Write: topics/{topic_key}/subtopics/{subtopic_key}.latest.json

7. UPDATE_INDICES
   ├── Update: index.json
   └── Update: page_index.json

8. SAVE_PAGE_GUIDELINE
   └── Write: pages/{N:03d}.page_guideline.json

9. UPDATE_BOOK_SUMMARY  ◄── NEW
   ├── Load: current book_summary.json (or empty if page 1)
   ├── Call: BookSummaryService.update(page_text, current_summary)
   ├── LLM: Updates summary, detects chapter boundaries, consolidates
   └── Save: book_summary.json

10. CHECK_STABILITY
    └── Mark subtopic "stable" if 5-page gap
```

## Edge Cases

| Scenario | Handling |
|----------|----------|
| **First page** | `current_summary` is empty string, LLM starts fresh |
| **Chapter 1 in progress** | No "Ch1:" prefix yet, just page notes |
| **500 token limit exceeded** | Log warning, accept output (will naturally condense next update) |
| **Very long page text** | Truncate to 2000 chars before passing to LLM |
| **LLM fails** | Log error, continue pipeline without summary update |
| **Empty page** | Add note like "| pN: [blank/image page] |" |

## Token Estimation

Simple approximation: `len(text.split()) * 1.3`

For accurate counting, use tiktoken with gpt-4o-mini encoding.

## API Impact

No new endpoints required. Book summary is:
- Created/updated automatically during `POST /admin/books/{book_id}/generate-guidelines`
- Stored in S3, accessible via existing S3 patterns
- Consumed internally by boundary detection

## Future Enhancements (Out of Scope)

1. **UI Display**: Show book summary progress in admin dashboard
2. **Summary Refinement**: Post-processing step to polish final summary
3. **Multi-book Context**: Use summaries from related books for better context
4. **Export**: Include book summary in final guideline export

## Testing Strategy

1. **Unit Tests**:
   - BookSummaryService.update() with various inputs
   - Token counting accuracy
   - S3 save/load operations

2. **Integration Tests**:
   - Full page processing with summary update
   - ContextPack includes book_summary
   - Boundary detection receives summary

3. **Manual Testing**:
   - Process sample book, verify summary quality
   - Check consolidation at chapter boundaries
   - Verify token limit compliance

## Implementation Checklist

- [ ] Create `BookSummary` model in `guideline_models.py`
- [ ] Create `book_summary_update.txt` prompt
- [ ] Create `BookSummaryService` class
- [ ] Add `book_summary` field to `ContextPack` model
- [ ] Update `ContextPackService.build()` to load book summary
- [ ] Update `boundary_detection.txt` prompt to include book summary
- [ ] Update `GuidelineExtractionOrchestrator.process_page()` to call BookSummaryService
- [ ] Add S3 helper methods for book summary operations
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Manual testing with sample book

## Dependencies

- Existing: `openai`, `boto3`, `pydantic`
- New: `tiktoken` (optional, for accurate token counting)

## Estimated Complexity

- **New Files**: 2 (service + prompt)
- **Modified Files**: 5 (models, context_pack_service, orchestrator, boundary_detection prompt, s3_client)
- **New LLM Calls**: 1 per page (gpt-4o-mini, ~$0.0001 per call)
