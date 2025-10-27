# Book-to-Curriculum Guide Mapping - Implementation Details

**Last Updated:** 2025-10-27
**Version:** 1.0 (Phase 6 Complete)
**Code Location:** `/llm-backend/features/book_ingestion/`

---

## 1. Project Structure

```
llm-backend/
├── features/book_ingestion/
│   ├── api/
│   │   └── routes.py                    # Book & guideline API endpoints
│   ├── models/
│   │   ├── database.py                  # SQLAlchemy ORM models
│   │   ├── schemas.py                   # Pydantic request/response models
│   │   └── guideline_models.py          # Phase 6 data models
│   ├── services/
│   │   ├── book_service.py              # Book CRUD operations
│   │   ├── guideline_extraction_orchestrator.py  # Main pipeline
│   │   ├── minisummary_service.py       # Page summarization
│   │   ├── context_pack_service.py      # Context building
│   │   ├── boundary_detection_service.py # Subtopic detection
│   │   ├── facts_extraction_service.py  # Content extraction
│   │   ├── reducer_service.py           # Merging & deduplication
│   │   ├── stability_detection_service.py # Confidence tracking
│   │   ├── teaching_description_generator.py # Pedagogical summary
│   │   ├── index_management_service.py  # Index operations
│   │   ├── db_sync_service.py           # Database sync
│   │   └── quality_gate_service.py      # Validation
│   └── utils/
│       └── s3_client.py                 # S3 operations
├── routers/
│   └── admin_guidelines.py              # Admin UI API endpoints
├── models/
│   └── database.py                      # Main database models
├── test_phase6_guideline_generation.py  # E2E integration test
└── test_admin_guidelines_api.py         # API tests
```

---

## 2. Core Components

### 2.1 Guideline Extraction Orchestrator

**Location:** `services/guideline_extraction_orchestrator.py`

**Purpose:** Main pipeline coordinator that processes all pages sequentially.

**Key Methods:**

```python
class GuidelineExtractionOrchestrator:
    def extract_guidelines_for_book(
        self,
        book_id: str,
        start_page: int,
        end_page: int,
        auto_sync_to_db: bool = False
    ) -> ExtractionStats:
        """
        Main entry point for guideline extraction.

        Steps for each page:
        1. Load OCR text
        2. Generate minisummary
        3. Build context pack
        4. Detect boundaries
        5. Extract facts
        6. Merge with existing shard
        7. Check stability
        8. Generate teaching description (if stable)
        9. Update indices
        """
        pass

    def process_page(
        self,
        book_id: str,
        page_num: int,
        context_pack: ContextPack
    ) -> PageProcessingResult:
        """Process a single page through the pipeline."""
        pass
```

**Configuration:**
```python
MINISUMMARY_MODEL = "gpt-4o-mini"  # Fast, cheap
FACTS_MODEL = "gpt-4o"             # High quality
BOUNDARY_MODEL = "gpt-4o"          # Accurate decisions

# Hysteresis thresholds
CONTINUE_THRESHOLD = 0.6  # Stay with current subtopic if score > 0.6
NEW_THRESHOLD = 0.75      # Start new subtopic if score > 0.75
```

### 2.2 Minisummary Service

**Location:** `services/minisummary_service.py`

**Purpose:** Reduce page text from ~24,500 tokens to ~300 tokens (98% reduction).

**Implementation:**
```python
class MinisummaryService:
    def generate_minisummary(self, page_text: str) -> str:
        """
        Generate concise summary focusing on:
        - Main teaching points
        - Key concepts
        - Examples and exercises
        - Pedagogical elements
        """
        prompt = """
        Summarize this textbook page in 3-4 sentences.
        Focus on teaching concepts, not formatting.
        Include: main topic, key points, examples.
        """
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an educational content analyzer."},
                {"role": "user", "content": f"{prompt}\n\n{page_text}"}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
```

**Token Efficiency:**
- Input: 24,500 tokens (full page)
- Output: 300 tokens (minisummary)
- Reduction: 98%
- Cost savings: ~80x per page

### 2.3 Context Pack Service

**Location:** `services/context_pack_service.py`

**Purpose:** Build sliding window of page summaries for context.

**Implementation:**
```python
class ContextPackService:
    def build_context_pack(
        self,
        book_id: str,
        current_page: int,
        window_size: int = 3
    ) -> ContextPack:
        """
        Build context from previous pages.

        Window size = 3 means:
        - 2 pages before current
        - Current page
        """
        pages = []
        for i in range(max(1, current_page - window_size + 1), current_page + 1):
            minisummary = self._load_minisummary(book_id, i)
            pages.append(PageSummary(page_num=i, summary=minisummary))

        return ContextPack(pages=pages, current_page=current_page)
```

### 2.4 Boundary Detection Service

**Location:** `services/boundary_detection_service.py`

**Purpose:** Detect when page belongs to new subtopic vs continuing current.

**Hysteresis Logic:**
```python
class BoundaryDetectionService:
    def detect_boundary(
        self,
        context_pack: ContextPack,
        current_subtopic: Optional[str]
    ) -> BoundaryDecision:
        """
        Use LLM to score: should we continue or start new?

        Returns:
        - "continue": stay with current (score < 0.75)
        - "new": start new subtopic (score >= 0.75)
        - "uncertain": unclear (0.6 < score < 0.75)
        """
        if current_subtopic is None:
            return BoundaryDecision(decision="new", ...)

        prompt = f"""
        Current subtopic: {current_subtopic}
        Context: {context_pack}

        Score (0-1): How likely is current page a NEW subtopic?
        - 0.0-0.6: Definitely continues current
        - 0.6-0.75: Uncertain (use hysteresis)
        - 0.75-1.0: Definitely new subtopic

        Return JSON: {{"score": 0.0-1.0, "reasoning": "..."}}
        """

        score = llm_call(prompt)

        if score >= 0.75:
            return "new"
        elif score <= 0.6:
            return "continue"
        else:
            return "uncertain"  # Default to continue in uncertainty
```

**Why Hysteresis?**
- Prevents rapid topic switching
- Creates stable subtopic boundaries
- Mimics how humans perceive topic changes

### 2.5 Facts Extraction Service

**Location:** `services/facts_extraction_service.py`

**Purpose:** Extract structured educational content from page.

**Implementation:**
```python
class FactsExtractionService:
    def extract_facts(self, page_text: str) -> PageFacts:
        """
        Extract structured content using GPT-4o.

        Returns:
        - Objectives: Learning goals
        - Examples: Concrete examples
        - Misconceptions: Common errors
        - Assessments: Practice questions
        """
        prompt = """
        Extract educational content from this page:

        1. OBJECTIVES (2-5 clear learning goals)
        2. EXAMPLES (concrete examples with solutions)
        3. MISCONCEPTIONS (common student errors + fixes)
        4. ASSESSMENTS (practice questions + answers)

        Return JSON following this schema:
        {
          "objectives": [{"statement": "...", "bloom_level": "...", "difficulty": "..."}],
          "examples": [{"description": "...", "context": "...", "answer": "..."}],
          "misconceptions": [{"misconception": "...", "why": "...", "fix": "..."}],
          "assessments": [{"prompt": "...", "answer": "...", "level": "..."}]
        }
        """

        response = llm_call(prompt, page_text)
        return PageFacts(**response)
```

**Few-Shot Examples:**
Prompts include 2-3 examples of well-structured facts to guide LLM output.

### 2.6 Reducer Service

**Location:** `services/reducer_service.py`

**Purpose:** Merge new facts with existing shard, deduplicate.

**Implementation:**
```python
class ReducerService:
    def merge_page_facts(
        self,
        existing_shard: SubtopicShard,
        new_facts: PageFacts
    ) -> SubtopicShard:
        """
        Merge new facts into existing shard.

        Strategy:
        1. Combine all items
        2. Deduplicate based on semantic similarity
        3. Keep top N items by quality
        """
        # Merge objectives
        all_objectives = existing_shard.objectives + new_facts.objectives
        unique_objectives = self._deduplicate(all_objectives)

        # Similar for examples, misconceptions, assessments

        return SubtopicShard(
            ...
            objectives=unique_objectives[:10],  # Keep top 10
            ...
        )

    def _deduplicate(self, items: List[T]) -> List[T]:
        """
        Remove semantic duplicates using embedding similarity.
        """
        # Use OpenAI embeddings to find similar items
        # Keep items with cosine similarity < 0.85
        pass
```

### 2.7 Stability Detection Service

**Location:** `services/stability_detection_service.py`

**Purpose:** Determine when subtopic has enough content.

**Implementation:**
```python
class StabilityDetectionService:
    def is_stable(self, shard: SubtopicShard) -> bool:
        """
        Subtopic is stable when:
        - Has ≥3 pages of content, OR
        - Confidence score ≥ 0.9

        This signals it's ready for teaching description.
        """
        page_count = len(shard.source_pages)
        confidence = shard.confidence

        return page_count >= 3 or confidence >= 0.9

    def update_status(self, shard: SubtopicShard) -> str:
        """
        Update shard status based on stability:
        - "open": Still building
        - "stable": Ready for review
        - "final": Approved by admin
        - "needs_review": Rejected
        """
        if self.is_stable(shard):
            return "stable"
        return "open"
```

### 2.8 Index Management Service

**Location:** `services/index_management_service.py`

**Purpose:** Manage central index files for efficient access.

**Key Operations:**
```python
class IndexManagementService:
    def update_index_with_new_subtopic(
        self,
        index: GuidelinesIndex,
        topic_key: str,
        subtopic_key: str,
        subtopic_title: str,
        page_range: str
    ) -> GuidelinesIndex:
        """Add new subtopic to index."""
        pass

    def update_page_assignment(
        self,
        page_index: PageIndex,
        page_num: int,
        topic_key: str,
        subtopic_key: str,
        confidence: float
    ) -> PageIndex:
        """Assign page to subtopic."""
        pass

    def save_index(
        self,
        index: GuidelinesIndex,
        create_snapshot: bool = False
    ) -> None:
        """
        Save index to S3.

        If create_snapshot=True, also save versioned copy.
        """
        pass
```

**Concurrency:**
- Indices use version numbers
- Load-modify-save pattern with optimistic locking
- Conflicts resolved by last-write-wins (acceptable for admin use)

---

## 3. Data Models

### 3.1 SubtopicShard (Core Model)

**Location:** `models/guideline_models.py`

```python
class SubtopicShard(BaseModel):
    """
    Authoritative state for a single subtopic.
    Stored in S3 at: books/{book_id}/guidelines/topics/{topic}/subtopics/{key}.latest.json
    """
    model_config = {"validate_assignment": False}  # Allow mutations

    # Identity
    book_id: str
    topic_key: str = Field(description="Slugified, e.g. 'mathematics-grade-3'")
    subtopic_key: str = Field(description="Slugified, e.g. 'counting-and-tally-marks'")
    topic_title: str = Field(description="Human-readable")
    subtopic_title: str = Field(description="Human-readable")

    # Content
    objectives: List[Objective] = Field(default_factory=list)
    examples: List[Example] = Field(default_factory=list)
    misconceptions: List[Misconception] = Field(default_factory=list)
    assessments: List[Assessment] = Field(default_factory=list)
    teaching_description: Optional[str] = None

    # Source tracking
    source_page_start: int
    source_page_end: int
    source_pages: List[int] = Field(default_factory=list)
    evidence_summary: str = ""

    # State
    status: Literal["open", "stable", "final", "needs_review"]
    confidence: float = 0.0
    version: int = 1
    quality_flags: QualityFlags = Field(default_factory=QualityFlags)
```

### 3.2 Supporting Models

```python
class Objective(BaseModel):
    statement: str
    bloom_level: Optional[str] = None  # e.g., "Understanding", "Applying"
    difficulty: Optional[str] = None   # e.g., "easy", "medium", "hard"

class Example(BaseModel):
    description: str
    context: Optional[str] = None
    answer: Optional[str] = None

class Misconception(BaseModel):
    misconception: str
    why_it_happens: Optional[str] = None
    how_to_address: Optional[str] = None

class Assessment(BaseModel):
    prompt: str
    answer: str
    level: str  # "basic", "proficient", "advanced"

class QualityFlags(BaseModel):
    has_min_objectives: bool = False
    has_misconception: bool = False
    has_assessments: bool = False
    teaching_description_valid: bool = False
```

---

## 4. API Implementation

### 4.1 Book Management APIs

**Location:** `features/book_ingestion/api/routes.py`

**Create Book:**
```python
@router.post("/admin/books", response_model=BookResponse)
def create_book(request: CreateBookRequest, db: Session = Depends(get_db)):
    """
    Create new book with metadata.

    Request:
    {
      "title": "Math Magic Grade 3",
      "author": "NCERT",
      "board": "NCERT",
      "grade": 3,
      "subject": "Mathematics",
      "country": "India"
    }

    Response:
    {
      "id": "ncert_mathematics_3_2024",
      "title": "Math Magic Grade 3",
      "status": "draft",
      ...
    }
    """
    service = BookService(db)
    return service.create_book(request)
```

**Upload Page:**
```python
@router.post("/admin/books/{book_id}/pages")
async def upload_page(book_id: str, image: UploadFile):
    """
    Upload page image, perform OCR, return for review.

    Steps:
    1. Save image to S3: books/{book_id}/pages/{next_num}.png
    2. Call OpenAI Vision API for OCR
    3. Save text to S3: books/{book_id}/ocr/{next_num}.txt
    4. Create page record with status="pending_review"

    Response:
    {
      "page_num": 1,
      "status": "pending_review",
      "text_preview": "First 200 characters...",
      "image_url": "https://s3.../page.png"
    }
    """
    pass
```

### 4.2 Guideline APIs

**Generate Guidelines:**
```python
@router.post("/admin/books/{book_id}/generate-guidelines")
async def generate_guidelines(
    book_id: str,
    request: GenerateGuidelinesRequest
):
    """
    Start guideline extraction pipeline.

    Request:
    {
      "start_page": 1,
      "end_page": 10,
      "auto_sync_to_db": false
    }

    Response:
    {
      "pages_processed": 10,
      "subtopics_created": 3,
      "subtopics_finalized": 1,
      "errors": []
    }
    """
    orchestrator = GuidelineExtractionOrchestrator(s3_client, openai_client)
    stats = orchestrator.extract_guidelines_for_book(
        book_id=book_id,
        start_page=request.start_page,
        end_page=request.end_page,
        auto_sync_to_db=request.auto_sync_to_db
    )
    return stats
```

**Get Guidelines:**
```python
@router.get("/admin/books/{book_id}/guidelines")
def get_guidelines(book_id: str):
    """
    List all guidelines for a book.

    Response:
    {
      "book_id": "ncert_mathematics_3_2024",
      "total_subtopics": 2,
      "guidelines": [
        {
          "topic_key": "mathematics-grade-3",
          "subtopic_key": "counting-and-tally-marks",
          "subtopic_title": "Counting and Tally Marks",
          "status": "stable",
          "source_page_start": 1,
          "source_page_end": 6,
          "objectives": [...],
          ...
        }
      ]
    }
    """
    # Load index from S3
    index = index_mgr.load_index(book_id)

    # Load all shards
    guidelines = []
    for topic in index.topics:
        for subtopic in topic.subtopics:
            shard = s3.download_json(f"books/{book_id}/guidelines/topics/{topic.topic_key}/subtopics/{subtopic.subtopic_key}.latest.json")
            guidelines.append(shard)

    return {"book_id": book_id, "guidelines": guidelines}
```

---

## 5. Testing

### 5.1 End-to-End Test

**Location:** `test_phase6_guideline_generation.py`

**Purpose:** Test complete pipeline on real book.

```python
def test_phase6_extraction():
    """
    Test guideline extraction on NCERT Math Grade 3.

    Steps:
    1. Verify book exists
    2. Check 8 pages uploaded
    3. Run extraction pipeline
    4. Verify results:
       - All pages processed
       - Subtopics created
       - Shards in S3
       - Indices updated
    """
    book_id = "ncert_mathematics_3_2024"

    orchestrator = GuidelineExtractionOrchestrator(s3, openai)
    stats = orchestrator.extract_guidelines_for_book(
        book_id=book_id,
        start_page=1,
        end_page=8
    )

    assert stats.pages_processed == 8
    assert stats.errors == 0
    assert stats.subtopics_created > 0
```

**Results:**
- ✅ 8/8 pages processed
- ✅ 2 subtopics created
- ✅ 4 S3 files created
- ✅ 0 errors
- ⏱️ 2.10 minutes (15.7 sec/page)

### 5.2 API Tests

**Location:** `test_admin_guidelines_api.py`

```python
def test_list_books():
    """Test GET /admin/guidelines/books"""
    response = client.get("/admin/guidelines/books")
    assert response.status_code == 200
    books = response.json()
    assert len(books) > 0

def test_get_topics():
    """Test GET /admin/guidelines/books/{id}/topics"""
    response = client.get("/admin/guidelines/books/ncert_mathematics_3_2024/topics")
    assert response.status_code == 200
    topics = response.json()
    assert len(topics) == 1
```

---

## 6. Configuration

### 6.1 Environment Variables

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# AWS
AWS_S3_BUCKET=learnlikemagic-books
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...      # Or use IAM role
AWS_SECRET_ACCESS_KEY=...  # Or use IAM role

# Database
DATABASE_URL=postgresql://user:pass@host:5432/learnlikemagic

# API
API_HOST=0.0.0.0
API_PORT=8000
```

### 6.2 Pipeline Configuration

**Location:** `services/guideline_extraction_orchestrator.py`

```python
# LLM Models
MINISUMMARY_MODEL = "gpt-4o-mini"  # Fast, cost-effective
BOUNDARY_MODEL = "gpt-4o"          # Accurate decisions
FACTS_MODEL = "gpt-4o"             # High-quality extraction

# Hysteresis Thresholds
CONTINUE_THRESHOLD = 0.6
NEW_THRESHOLD = 0.75

# Context Window
CONTEXT_WINDOW_SIZE = 3  # Pages

# Stability Thresholds
MIN_PAGES_FOR_STABILITY = 3
MIN_CONFIDENCE_FOR_STABILITY = 0.9

# Quality Gates
MIN_OBJECTIVES_FOR_QUALITY = 2
```

---

## 7. Deployment

### 7.1 Local Development

```bash
# 1. Clone repository
git clone https://github.com/manishjain-py/learnlikemagic.git
cd learnlikemagic/llm-backend

# 2. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
export OPENAI_API_KEY=sk-...
export DATABASE_URL=postgresql://...
export AWS_S3_BUCKET=learnlikemagic-books

# 5. Run database migrations
alembic upgrade head

# 6. Start server
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 7. Access API
# http://localhost:8000/docs
```

### 7.2 Production Deployment

**AWS App Runner Configuration:**
```yaml
runtime: python
build:
  commands:
    build:
      - pip install -r requirements.txt
run:
  command: uvicorn main:app --host 0.0.0.0 --port 8000
  network:
    port: 8000
  env:
    - name: OPENAI_API_KEY
      value: <secret>
    - name: DATABASE_URL
      value: <rds-connection>
    - name: AWS_S3_BUCKET
      value: learnlikemagic-books
```

---

## 8. Troubleshooting

### Common Issues

**1. S3 Upload Fails: "unhashable type: 'dict'"**
- **Cause:** Reversed arguments in `upload_json()`
- **Fix:** Use `upload_json(data=dict, s3_key=str)`

**2. Pydantic Validation Error: "Field required"**
- **Cause:** Model definition missing required fields
- **Fix:** Check model matches shard structure

**3. Pipeline Skips Pages**
- **Cause:** Error in one page stops processing
- **Fix:** Check logs for specific page error

**4. Empty Guidelines Returned**
- **Cause:** Index doesn't exist or empty
- **Fix:** Run generation first, check S3 bucket

**5. Database Sync Fails**
- **Cause:** Missing Phase 6 migration
- **Fix:** Run `alembic upgrade head`

---

## 9. Performance Optimization

### Current Performance
- **Per Page:** ~15.7 seconds
- **Per Book (50 pages):** ~13 minutes
- **Bottleneck:** Sequential LLM calls

### Optimization Strategies

**1. Parallel Page Processing**
- Process multiple pages concurrently
- Requires coordination for boundary detection

**2. Batch LLM Calls**
- Extract facts from multiple pages in one call
- Reduces API overhead

**3. Cache Minisummaries**
- Store minisummaries permanently
- Reuse for regeneration

**4. Optimize Context Window**
- Reduce window size from 3 to 2 pages
- Test impact on boundary accuracy

---

## 10. Known Limitations & Future Work

### Current Limitations
1. **Sequential Processing** - One page at a time
2. **Single Book Focus** - No cross-book merging
3. **Manual Review Required** - No automated quality scoring
4. **Teaching Descriptions** - Not always generated
5. **No Version Control** - Can't track changes over time

### Planned Improvements
1. **Parallel Pipeline** - Process multiple pages concurrently
2. **Quality Scoring** - Automated guideline quality assessment
3. **Smart Merging** - Combine similar subtopics across books
4. **Version Control** - Git-like versioning for guidelines
5. **Real-time Updates** - WebSocket for live progress

---

**Document Owner:** Engineering Team
**Last Review:** 2025-10-27
**Next Review:** After Phase 7 completion
