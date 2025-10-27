# Book-to-Curriculum Guide Mapping - Product Requirements Document

**Last Updated:** 2025-10-27
**Status:** Phase 6 Complete
**Version:** 1.0

---

## 1. Overview

The Book-to-Curriculum Guide Mapping feature enables Learn Like Magic to automatically extract structured teaching guidelines from educational textbooks. These guidelines serve as a curriculum-aligned reference system that the AI Tutor uses as a teaching baseline.

### System Components

1. **Book Ingestion Pipeline** - Upload, OCR, and store textbook pages
2. **Guideline Extraction Pipeline** (Phase 6) - Automatically extract teaching guidelines
3. **Admin Review Interface** - Review, edit, and approve generated guidelines
4. **AI Tutor Integration** - Use guidelines as context for personalized lessons

---

## 2. Business Objectives

### Primary Goals
- Convert textbooks into structured, searchable teaching guidelines
- Ensure AI-generated content aligns with curriculum standards
- Enable curriculum coverage across boards, grades, and subjects
- Maintain copyright compliance through synthesis and originality

### Success Metrics
- **Processing Speed:** <20 seconds per page
- **Accuracy:** >90% guideline quality score
- **Coverage:** Support for major Indian education boards (NCERT, CBSE, ICSE)
- **Adoption:** 80% of uploaded books have approved guidelines

---

## 3. User Roles

### Admin / Content Curator
**Responsibilities:**
- Upload textbooks (as images or PDFs)
- Review OCR output for accuracy
- Review and validate AI-generated guidelines
- Approve, edit, or regenerate guidelines
- Sync approved guidelines to production database

**Access:**
- Admin dashboard at `/admin/books`
- Full CRUD operations on books and guidelines

### System / AI Pipeline
**Responsibilities:**
- Convert images to text using OpenAI Vision API
- Store text and metadata in AWS S3
- Process pages through 9-step guideline extraction pipeline
- Generate structured JSON guidelines
- Maintain indices for efficient access

### AI Tutor Agent
**Responsibilities:**
- Query guidelines by topic/subtopic/page
- Use guidelines as context for lesson generation
- Adapt teaching based on guideline depth and examples

---

## 4. Functional Requirements

### 4.1 Book Upload & Management

**Book Creation**
- Admin creates book with metadata:
  - Title, author, publisher
  - Board (NCERT, CBSE, ICSE, etc.)
  - Grade (1-12)
  - Subject (Mathematics, Science, etc.)
  - Country (India, US, etc.)
- System assigns unique `book_id`
- Book starts in `draft` status

**Page Upload**
- Upload pages as images (PNG, JPG)
- Automatic OCR using OpenAI Vision API (gpt-4o-mini)
- Pages stored in S3 at `books/{book_id}/pages/{page_num}.png`
- OCR text stored at `books/{book_id}/ocr/{page_num}.txt`
- Admin reviews and approves each page
- Status flow: `pending_review` → `approved`

**Book Status Flow**
```
draft → uploading_pages → pages_complete →
generating_guidelines → guidelines_pending_review → approved
```

### 4.2 Guideline Extraction Pipeline (Phase 6)

**Automatic Extraction**
- Triggered after book reaches `pages_complete` status
- Processes all pages (1 to N) in sequence
- Extracts structured teaching guidelines
- Stores results in S3 sharded architecture

**Extracted Content**
For each detected subtopic:
- **Topic & Subtopic Identification**
  - Topic title and slugified key
  - Subtopic title and slugified key
  - Source page range

- **Learning Objectives**
  - Clear, measurable objectives
  - Bloom's taxonomy level (optional)
  - Difficulty rating (optional)

- **Examples**
  - Concrete examples from the book
  - Context and solutions
  - Progressive difficulty levels

- **Common Misconceptions**
  - Student misconceptions
  - Why they occur
  - How to address them

- **Assessment Questions**
  - Questions at various difficulty levels
  - Expected answers
  - Level (basic, proficient, advanced)

- **Teaching Description** (optional)
  - Pedagogical approach summary
  - Teaching sequence
  - Key concepts to emphasize

**Pipeline Steps**
1. Page OCR loading
2. Minisummary generation (98% token reduction)
3. Context pack building
4. Boundary detection (subtopic identification)
5. Facts extraction (objectives, examples, etc.)
6. Shard merging and deduplication
7. Stability detection
8. Teaching description generation
9. Database sync

### 4.3 Admin Review Interface

**Books Dashboard**
- List all books with filters (board, grade, subject, status)
- Show extraction progress
- Quick actions: View, Edit, Delete

**Book Detail Page**
- Book metadata display
- Page upload interface
- Page gallery with status badges
- Guidelines panel (when available)

**Guidelines Panel**
- List all subtopics with status indicators
- Click to view full guideline details
- Sections:
  - Teaching description
  - Learning objectives
  - Examples
  - Misconceptions
  - Assessments
  - Metadata (pages, confidence, version)
- Actions:
  - Generate/Regenerate guidelines
  - Approve & sync to database
  - Reject & delete for regeneration

**Status Indicators**
- `open` - New, still being built (yellow)
- `stable` - Confidence threshold met, ready for review (blue)
- `final` - Approved by admin (green)
- `needs_review` - Rejected, needs revision (red)

### 4.4 Data Storage

**PostgreSQL Database**
- Books table: metadata, status
- Pages table: page numbers, status
- Teaching guidelines table: synced, approved guidelines

**AWS S3 (Primary Storage)**
```
books/{book_id}/
├── pages/
│   └── {page_num}.png
├── ocr/
│   └── {page_num}.txt
└── guidelines/
    ├── index.json                     # Topics/subtopics index
    ├── page_index.json                # Page-to-subtopic mapping
    └── topics/
        └── {topic_key}/
            └── subtopics/
                └── {subtopic_key}.latest.json  # Guideline shard
```

### 4.5 API Endpoints

**Book Management**
- `POST /admin/books` - Create book
- `GET /admin/books` - List books (with filters)
- `GET /admin/books/{book_id}` - Get book details
- `PUT /admin/books/{book_id}/status` - Update status
- `DELETE /admin/books/{book_id}` - Delete book

**Page Management**
- `POST /admin/books/{book_id}/pages` - Upload page
- `PUT /admin/books/{book_id}/pages/{page_num}/approve` - Approve page
- `DELETE /admin/books/{book_id}/pages/{page_num}` - Delete page
- `GET /admin/books/{book_id}/pages/{page_num}` - Get page details

**Guideline Management (Phase 6)**
- `POST /admin/books/{book_id}/generate-guidelines` - Start extraction
- `GET /admin/books/{book_id}/guidelines` - List all guidelines
- `GET /admin/books/{book_id}/guidelines/{topic}/{subtopic}` - Get detail
- `PUT /admin/books/{book_id}/guidelines/approve` - Approve & sync to DB
- `DELETE /admin/books/{book_id}/guidelines` - Delete for regeneration

**Admin Guidelines API (Alternative)**
- `GET /admin/guidelines/books` - Books with extraction status
- `GET /admin/guidelines/books/{book_id}/topics` - Topics & subtopics
- `GET /admin/guidelines/books/{book_id}/subtopics/{key}` - Guideline detail
- `PUT /admin/guidelines/books/{book_id}/subtopics/{key}` - Update
- `POST /admin/guidelines/books/{book_id}/subtopics/{key}/approve` - Approve single
- `GET /admin/guidelines/books/{book_id}/page-assignments` - Page mappings
- `POST /admin/guidelines/books/{book_id}/sync-to-database` - Sync to DB

---

## 5. Non-Functional Requirements

### Performance
- Page OCR: <5 seconds per page
- Guideline extraction: <20 seconds per page
- Index loading: <1 second
- API response time: <2 seconds

### Scalability
- Support books up to 500 pages
- Handle concurrent uploads (5 books simultaneously)
- Support 100+ books per board/grade combination

### Reliability
- S3 as source of truth (PostgreSQL is cache)
- Graceful error handling with continuation
- Automatic retry for transient failures
- Detailed logging for debugging

### Security
- Admin-only access (authentication required)
- AWS credentials via IAM roles
- OpenAI API key in environment variables
- Input validation on all endpoints

### Maintainability
- Modular service architecture
- Comprehensive documentation
- Type safety with Pydantic
- Integration and unit tests

---

## 6. Out of Scope (Future Phases)

### Phase 7+
- Multi-book guideline merging
- Quality scoring and ranking
- Automated topic taxonomy
- Cross-board curriculum mapping
- Student-facing guideline search
- Guideline versioning and history
- Bulk operations (batch upload, batch approve)

### Not Planned
- Direct PDF upload (use image conversion)
- Manual guideline authoring (extraction only)
- Real-time collaboration on guidelines
- Mobile app admin interface

---

## 7. Success Criteria

### Phase 6 Completion Criteria ✅
- [x] 9-step extraction pipeline implemented
- [x] End-to-end test passing (100% success rate)
- [x] Admin API implemented (7 endpoints)
- [x] Integration with React frontend
- [x] Database migration for Phase 6 fields
- [x] Comprehensive documentation
- [x] S3 sharded storage working
- [x] All critical bugs fixed

### Production Readiness
- [ ] 50-page full book test
- [ ] Database sync tested
- [ ] Teaching description quality validation
- [ ] Load testing (10 concurrent books)
- [ ] Security audit
- [ ] Deployment to staging environment

---

## 8. Dependencies

### External Services
- **OpenAI API** - Vision (gpt-4o-mini) for OCR, GPT-4o for extraction
- **AWS S3** - Primary storage for pages and guidelines
- **PostgreSQL** - Metadata and synced guidelines

### Internal Dependencies
- **React Frontend** - Admin UI at `/llm-frontend`
- **FastAPI Backend** - REST API
- **Database Migrations** - Phase 6 schema changes

### Third-Party Libraries
- `openai` - OpenAI API client
- `boto3` - AWS SDK
- `pydantic` - Data validation
- `sqlalchemy` - ORM
- `fastapi` - Web framework

---

## 9. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| OpenAI API rate limits | High | Medium | Implement exponential backoff, queue system |
| Poor OCR quality | High | Low | Manual review step, Vision API is accurate |
| Incorrect subtopic boundaries | Medium | Medium | Hysteresis-based detection, admin review |
| S3 storage costs | Low | High | Optimize image compression, lifecycle policies |
| Database sync failures | Medium | Low | Retry logic, detailed error logging |

---

## 10. Timeline

- **Phase 1-5:** Book ingestion (Complete)
- **Phase 6:** Guideline extraction (Complete - 2025-10-27)
- **Phase 7:** Production testing & optimization (Planned)
- **Phase 8:** Multi-book merging (Future)

---

**Document Owner:** Product Team
**Technical Lead:** Engineering Team
**Last Review:** 2025-10-27
