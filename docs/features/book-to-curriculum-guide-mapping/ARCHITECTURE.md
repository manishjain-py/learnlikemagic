# Book-to-Curriculum Guide Mapping - System Architecture

**Last Updated:** 2025-10-27
**Version:** 1.0 (Phase 6 Complete)

---

## 1. System Overview

The Book-to-Curriculum Guide Mapping system consists of three main subsystems:

1. **Book Ingestion Pipeline** - Upload and OCR textbook pages
2. **Guideline Extraction Pipeline** (Phase 6) - Extract teaching guidelines
3. **Admin UI & APIs** - Review and manage content

```
┌─────────────────────────────────────────────────────────────┐
│                     Admin UI (React)                        │
│  - Books Dashboard                                          │
│  - Book Detail Page                                         │
│  - Guidelines Panel                                         │
└─────────────────────────┬───────────────────────────────────┘
                          │ REST API
┌─────────────────────────▼───────────────────────────────────┐
│                  FastAPI Backend                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Book Management APIs                                 │   │
│  │  - Create, list, get, update, delete books          │   │
│  │  - Upload, approve, delete pages                    │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Guideline APIs (Phase 6)                            │   │
│  │  - Generate guidelines                               │   │
│  │  - List/get guidelines                               │   │
│  │  - Approve/reject                                    │   │
│  │  - Sync to database                                  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────┬───────────────────────────┬───────────────────┘
              │                           │
         ┌────▼────┐               ┌─────▼──────┐
         │   S3    │               │ PostgreSQL │
         │ (Primary│               │   (Cache)  │
         │ Storage)│               └────────────┘
         └─────────┘
```

---

## 2. Data Architecture

### 2.1 Storage Strategy

**Primary Storage: AWS S3**
- Source of truth for all book content
- Sharded guideline storage for scalability
- Direct access via signed URLs

**Secondary Storage: PostgreSQL**
- Book and page metadata
- Approved guidelines (synced from S3)
- Fast queries for list operations

### 2.2 S3 Structure

```
s3://learnlikemagic-books/
└── books/
    └── {book_id}/
        ├── pages/
        │   ├── 1.png
        │   ├── 2.png
        │   └── ...
        ├── ocr/
        │   ├── 1.txt
        │   ├── 2.txt
        │   └── ...
        └── guidelines/
            ├── index.json                    # Master index
            ├── page_index.json               # Page→Subtopic mapping
            └── topics/
                └── {topic_key}/              # e.g., "mathematics-grade-3"
                    └── subtopics/
                        ├── {subtopic_key}.latest.json   # Current version
                        └── {subtopic_key}.v{N}.json     # Historical versions
```

**Key Design Decisions:**
1. **Sharding** - Each subtopic is a separate file for parallel access
2. **Indices** - Central indices for efficient listing without scanning all shards
3. **Versioning** - `.latest.json` always points to current version
4. **Flat Subtopics** - No nested subtopics for simplicity

### 2.3 Index Files

**index.json** - Master topic/subtopic index
```json
{
  "book_id": "ncert_mathematics_3_2024",
  "topics": [
    {
      "topic_key": "mathematics-grade-3",
      "topic_title": "Mathematics Grade 3",
      "subtopics": [
        {
          "subtopic_key": "counting-and-tally-marks",
          "subtopic_title": "Counting and Tally Marks",
          "status": "stable",
          "page_range": "1-6"
        }
      ]
    }
  ],
  "version": 1,
  "last_updated": "2025-10-27T12:00:00Z"
}
```

**page_index.json** - Page-to-subtopic mapping
```json
{
  "book_id": "ncert_mathematics_3_2024",
  "pages": {
    "1": {
      "topic_key": "mathematics-grade-3",
      "subtopic_key": "counting-and-tally-marks",
      "confidence": 1.0
    },
    "2": {
      "topic_key": "mathematics-grade-3",
      "subtopic_key": "counting-and-tally-marks",
      "confidence": 0.95
    }
  },
  "version": 1,
  "last_updated": "2025-10-27T12:00:00Z"
}
```

### 2.4 Database Schema

**books** table
```sql
CREATE TABLE books (
    id VARCHAR PRIMARY KEY,
    title VARCHAR NOT NULL,
    author VARCHAR,
    publisher VARCHAR,
    country VARCHAR NOT NULL,
    board VARCHAR NOT NULL,
    grade INTEGER NOT NULL,
    subject VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**pages** table (tracked separately for status)
```sql
CREATE TABLE pages (
    book_id VARCHAR REFERENCES books(id),
    page_num INTEGER,
    status VARCHAR NOT NULL,
    s3_key VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (book_id, page_num)
);
```

**teaching_guidelines** table (Phase 6)
```sql
CREATE TABLE teaching_guidelines (
    id SERIAL PRIMARY KEY,
    curriculum VARCHAR,
    grade INTEGER,
    subject VARCHAR,
    topic_key VARCHAR,
    subtopic_key VARCHAR,
    topic_title VARCHAR,
    subtopic_title VARCHAR,

    -- Core content (JSON fields)
    objectives_json TEXT,
    examples_json TEXT,
    misconceptions_json TEXT,
    assessments_json TEXT,
    teaching_description TEXT,

    -- Metadata
    book_id VARCHAR,
    source_page_start INTEGER,
    source_page_end INTEGER,
    source_pages VARCHAR,
    evidence_summary TEXT,

    -- Phase 6 fields
    status VARCHAR DEFAULT 'draft',
    confidence FLOAT,
    version INTEGER DEFAULT 1,

    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX idx_guidelines_curriculum_grade_subject
    ON teaching_guidelines(curriculum, grade, subject);
CREATE INDEX idx_guidelines_topic_subtopic
    ON teaching_guidelines(topic_key, subtopic_key);
CREATE INDEX idx_guidelines_book_id
    ON teaching_guidelines(book_id);
```

---

## 3. Phase 6 Pipeline Architecture

### 3.1 Pipeline Flow

```
Page N
  │
  ├─► 1. Load OCR Text ────► S3: books/{id}/ocr/{N}.txt
  │
  ├─► 2. Generate Minisummary ────► Reduce 24,500 → 300 tokens (98%)
  │
  ├─► 3. Build Context Pack ────► Window of 3 pages for context
  │
  ├─► 4. Boundary Detection ────► Is this a new subtopic?
  │        (Hysteresis: 0.6 continue, 0.75 new)
  │
  ├─► 5. Extract Facts ────► Objectives, Examples, Misconceptions, Assessments
  │
  ├─► 6. Merge/Reduce ────► Deduplicate and merge with existing shard
  │
  ├─► 7. Stability Check ────► Has shard reached confidence threshold?
  │
  ├─► 8. Teaching Description ────► Generate pedagogical summary (if stable)
  │
  └─► 9. Update Indices ────► Update index.json, page_index.json
       │
       └─► Save to S3 ────► books/{id}/guidelines/topics/{topic}/subtopics/{key}.latest.json
```

### 3.2 Services Architecture

**Single Responsibility Principle** - Each service has one job:

1. **GuidelineExtractionOrchestrator**
   - Coordinates the entire pipeline
   - Processes pages sequentially
   - Handles error recovery
   - Updates indices

2. **MinisummaryService**
   - Generates concise page summaries
   - Uses GPT-4o-mini for speed
   - Achieves 98% token reduction

3. **ContextPackService**
   - Builds sliding window of page summaries
   - Provides context for boundary detection
   - Configurable window size (default: 3 pages)

4. **BoundaryDetectionService**
   - Hysteresis-based subtopic detection
   - Prevents rapid topic switching
   - Returns: continue, new, or uncertain

5. **FactsExtractionService**
   - Extracts educational content from pages
   - Uses structured prompts with examples
   - Returns objectives, examples, misconceptions, assessments

6. **ReducerService**
   - Merges new facts with existing shard
   - Deduplicates similar content
   - Maintains fact quality

7. **StabilityDetectionService**
   - Tracks page count and confidence
   - Determines when subtopic is "stable"
   - Threshold: ≥3 pages OR confidence ≥0.9

8. **TeachingDescriptionGenerator**
   - Generates pedagogical summaries
   - Requires stable shard with objectives
   - Optional enhancement feature

9. **IndexManagementService**
   - Manages index.json and page_index.json
   - Updates subtopic statuses
   - Creates snapshots

10. **DatabaseSyncService**
    - Syncs S3 shards to PostgreSQL
    - Maps SubtopicShard → teaching_guidelines
    - Performs upserts

11. **QualityGateService**
    - Validates guideline quality
    - Checks for minimum content
    - Flags low-quality shards

### 3.3 Data Models

**SubtopicShard** (Primary data structure)
```python
class SubtopicShard(BaseModel):
    book_id: str

    # Identity
    topic_key: str
    subtopic_key: str
    topic_title: str
    subtopic_title: str

    # Content
    objectives: List[Objective]
    examples: List[Example]
    misconceptions: List[Misconception]
    assessments: List[Assessment]
    teaching_description: Optional[str]

    # Metadata
    source_page_start: int
    source_page_end: int
    source_pages: List[int]
    evidence_summary: str

    # State
    status: Literal["open", "stable", "final", "needs_review"]
    confidence: float
    version: int
    quality_flags: QualityFlags
```

**Supporting Models**
```python
class Objective(BaseModel):
    statement: str
    bloom_level: Optional[str]
    difficulty: Optional[str]

class Example(BaseModel):
    description: str
    context: Optional[str]
    answer: Optional[str]

class Misconception(BaseModel):
    misconception: str
    why_it_happens: Optional[str]
    how_to_address: Optional[str]

class Assessment(BaseModel):
    prompt: str
    answer: str
    level: str
```

---

## 4. API Architecture

### 4.1 Layered Architecture

```
┌────────────────────────────────────────┐
│         API Routes Layer               │
│  - Request validation (Pydantic)       │
│  - Response formatting                 │
│  - Error handling                      │
└────────────┬───────────────────────────┘
             │
┌────────────▼───────────────────────────┐
│         Service Layer                  │
│  - Business logic                      │
│  - Orchestration                       │
│  - S3 operations                       │
└────────────┬───────────────────────────┘
             │
┌────────────▼───────────────────────────┐
│       Repository Layer                 │
│  - Database queries                    │
│  - ORM operations                      │
│  - Transaction management              │
└────────────────────────────────────────┘
```

### 4.2 Route Organization

**Book Management Routes** (`features/book_ingestion/api/routes.py`)
- `/admin/books/*` - CRUD operations
- Includes Phase 5 guideline endpoints (updated for Phase 6)

**Admin Guidelines Routes** (`routers/admin_guidelines.py`)
- `/admin/guidelines/*` - Phase 6 specific endpoints
- More detailed guideline management
- Alternative to book-centric endpoints

### 4.3 Authentication & Authorization

**Current:** No authentication (admin-only by network)
**Planned:**
- JWT-based authentication
- Role-based access control (Admin, Reviewer, Viewer)
- API key for programmatic access

---

## 5. Technology Stack

### Backend
- **FastAPI** - Web framework
- **Python 3.11** - Language
- **SQLAlchemy** - ORM
- **Pydantic v2** - Data validation
- **boto3** - AWS SDK
- **openai** - OpenAI API client

### Frontend
- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **TailwindCSS** - Styling

### Infrastructure
- **AWS S3** - Object storage
- **PostgreSQL** - Relational database
- **OpenAI API** - Vision (OCR) and GPT-4o (extraction)

### Development
- **Git** - Version control
- **pytest** - Testing
- **uvicorn** - ASGI server
- **Claude Code** - AI-assisted development

---

## 6. Scalability Considerations

### Current Limits
- Single-threaded pipeline processing
- Sequential page processing
- In-memory context packs

### Scaling Strategies

**Horizontal Scaling**
- Separate worker processes per book
- Message queue (SQS) for job distribution
- Multiple API instances behind load balancer

**Vertical Scaling**
- Increase worker memory for larger context packs
- GPU instances for faster LLM inference
- Read replicas for PostgreSQL

**Optimization Opportunities**
- Batch LLM calls (process multiple pages together)
- Cache minisummaries and context packs
- Parallel facts extraction for different content types
- Lazy loading of shard data

---

## 7. Error Handling & Recovery

### Error Types

1. **Transient Errors** (retry automatically)
   - OpenAI API rate limits
   - S3 connection timeouts
   - Database connection drops

2. **Permanent Errors** (log and continue)
   - Invalid page content
   - Model validation failures
   - Corrupted shard data

3. **Critical Errors** (stop pipeline)
   - S3 bucket not accessible
   - OpenAI API key invalid
   - Database migration needed

### Recovery Strategies

**Checkpoint System**
- Index tracks last processed page
- Can resume from any page
- Idempotent operations

**Graceful Degradation**
- If teaching description fails, shard still saved
- If one page fails, continue with next
- If boundary detection uncertain, default to continue

---

## 8. Security Architecture

### Data Security
- **Encryption at rest** - S3 server-side encryption
- **Encryption in transit** - HTTPS for all API calls
- **Access control** - S3 bucket policies, IAM roles

### API Security
- **Input validation** - Pydantic schemas
- **SQL injection prevention** - Parameterized queries
- **XSS prevention** - React auto-escaping

### Secrets Management
- AWS credentials via IAM roles (no hardcoded keys)
- OpenAI API key in environment variables
- Database credentials in AWS Secrets Manager

---

## 9. Monitoring & Observability

### Logging
- **Application logs** - Python logging module
- **Access logs** - uvicorn
- **Error tracking** - Structured exception logging

### Metrics (Planned)
- Pipeline processing time per page
- LLM API call latency
- Guideline extraction success rate
- S3 upload/download performance

### Alerts (Planned)
- Pipeline failures
- High error rates
- API latency spikes
- S3 storage capacity

---

## 10. Deployment Architecture

### Development
```
Local Machine
├── PostgreSQL (Docker)
├── FastAPI (uvicorn --reload)
└── React (npm run dev)
```

### Staging/Production
```
┌─────────────────────────────────┐
│          CloudFront             │
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│      S3 Static Hosting          │
│      (React Frontend)           │
└─────────────────────────────────┘
             │
┌────────────▼────────────────────┐
│       Application Load          │
│         Balancer                │
└────────────┬────────────────────┘
             │
     ┌───────┴───────┐
     │               │
┌────▼────┐     ┌───▼─────┐
│ FastAPI │     │ FastAPI │
│Instance1│     │Instance2│
└─────────┘     └─────────┘
     │               │
     └───────┬───────┘
             │
     ┌───────┴────────┐
     │                │
┌────▼───┐       ┌───▼────┐
│   S3   │       │  RDS   │
│(Primary│       │(Cache) │
│Storage)│       │        │
└────────┘       └────────┘
```

---

## 11. Future Architecture Considerations

### Phase 7+
- **Real-time processing** - WebSocket updates during extraction
- **Distributed pipeline** - Multiple workers via message queue
- **Caching layer** - Redis for frequently accessed guidelines
- **CDN integration** - CloudFront for S3 object delivery
- **Multi-region** - Global deployment for low latency

### Advanced Features
- **Version control** - Git-like versioning for guidelines
- **Diff visualization** - Compare versions
- **Merge conflicts** - Handle concurrent edits
- **Automated testing** - Quality checks on generated content

---

**Document Owner:** Engineering Team
**Last Review:** 2025-10-27
