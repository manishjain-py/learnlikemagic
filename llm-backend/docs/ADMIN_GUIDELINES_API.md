# Admin Guidelines API Documentation

API endpoints for reviewing and managing Phase 6 extracted teaching guidelines in the admin UI.

**Base URL:** `/admin/guidelines`

---

## Table of Contents
1. [List Books with Guidelines](#1-list-books-with-guidelines)
2. [Get Book Topics](#2-get-book-topics)
3. [Get Subtopic Guideline](#3-get-subtopic-guideline)
4. [Update Subtopic Guideline](#4-update-subtopic-guideline)
5. [Approve/Reject Guideline](#5-approvereject-guideline)
6. [Get Page Assignments](#6-get-page-assignments)
7. [Sync to Database](#7-sync-to-database)
8. [UI Integration Examples](#ui-integration-examples)

---

## 1. List Books with Guidelines

Get a list of all books with their guideline extraction status.

### Endpoint
```
GET /admin/guidelines/books
```

### Query Parameters
| Parameter | Type   | Required | Description                      |
|-----------|--------|----------|----------------------------------|
| status    | string | No       | Filter by extraction status      |

### Response
```json
[
  {
    "book_id": "ncert_mathematics_3_2024",
    "title": "Math Magic Grade 3",
    "grade": 3,
    "subject": "Mathematics",
    "total_pages": 8,
    "pages_processed": 8,
    "extraction_status": "completed",
    "topics_count": 1,
    "subtopics_count": 8,
    "subtopics_approved": 0,
    "last_updated": "2025-10-27T12:29:23Z"
  }
]
```

### Extraction Status Values
- `not_started` - No guidelines extracted yet
- `in_progress` - Extraction is running
- `completed` - All pages processed
- `failed` - Extraction encountered errors

---

## 2. Get Book Topics

Get all topics and subtopics for a book.

### Endpoint
```
GET /admin/guidelines/books/{book_id}/topics
```

### Path Parameters
| Parameter | Type   | Required | Description |
|-----------|--------|----------|-------------|
| book_id   | string | Yes      | Book ID     |

### Response
```json
[
  {
    "topic_key": "mathematics-grade-3",
    "topic_title": "Mathematics - Grade 3",
    "subtopics": [
      {
        "subtopic_key": "counting-animals",
        "subtopic_title": "Counting Animals",
        "status": "open",
        "page_range": "2-2"
      },
      {
        "subtopic_key": "counting-and-measurement",
        "subtopic_title": "Counting and Measurement",
        "status": "stable",
        "page_range": "1-1"
      }
    ]
  }
]
```

### Subtopic Status Values
- `open` - New, still being built
- `stable` - Confidence threshold met, ready for review
- `final` - Approved by reviewer
- `needs_review` - Rejected, needs revision

---

## 3. Get Subtopic Guideline

Get complete guideline details for a specific subtopic.

### Endpoint
```
GET /admin/guidelines/books/{book_id}/subtopics/{subtopic_key}
```

### Path Parameters
| Parameter     | Type   | Required | Description    |
|---------------|--------|----------|----------------|
| book_id       | string | Yes      | Book ID        |
| subtopic_key  | string | Yes      | Subtopic key   |

### Query Parameters
| Parameter  | Type   | Required | Description |
|------------|--------|----------|-------------|
| topic_key  | string | Yes      | Topic key   |

### Response
```json
{
  "book_id": "ncert_mathematics_3_2024",
  "topic_key": "mathematics-grade-3",
  "topic_title": "Mathematics - Grade 3",
  "subtopic_key": "counting-animals",
  "subtopic_title": "Counting Animals",

  "source_page_start": 2,
  "source_page_end": 2,
  "source_pages": [2],
  "page_range": "2-2",

  "status": "stable",
  "confidence": 0.85,
  "version": 1,
  "last_updated": "2025-10-27T12:29:23Z",

  "teaching_description": "Start by showing students pictures of different animals and asking them to count. Introduce the concept of counting objects in different groups...",

  "objectives": [
    {
      "statement": "Count animals in a picture accurately",
      "bloom_level": "Understanding",
      "difficulty": "easy"
    },
    {
      "statement": "Identify and count different types of animals",
      "bloom_level": "Applying",
      "difficulty": "medium"
    }
  ],

  "examples": [
    {
      "description": "Count the cows in the field",
      "context": "Picture showing 5 cows grazing",
      "answer": "5 cows"
    }
  ],

  "misconceptions": [
    {
      "misconception": "Students may count the same animal twice",
      "why_it_happens": "Lack of systematic counting strategy",
      "how_to_address": "Teach students to mark or point to each animal as they count"
    }
  ],

  "assessments": [
    {
      "question": "How many tigers are in this picture?",
      "answer": "3",
      "difficulty": "easy"
    }
  ],

  "evidence_summary": "Based on 1 page of evidence from the textbook"
}
```

---

## 4. Update Subtopic Guideline

Update the content of a subtopic guideline.

### Endpoint
```
PUT /admin/guidelines/books/{book_id}/subtopics/{subtopic_key}
```

### Path Parameters
| Parameter     | Type   | Required | Description    |
|---------------|--------|----------|----------------|
| book_id       | string | Yes      | Book ID        |
| subtopic_key  | string | Yes      | Subtopic key   |

### Query Parameters
| Parameter  | Type   | Required | Description |
|------------|--------|----------|-------------|
| topic_key  | string | Yes      | Topic key   |

### Request Body
```json
{
  "teaching_description": "Updated teaching approach...",
  "objectives": [
    {
      "statement": "New objective",
      "bloom_level": "Understanding",
      "difficulty": "easy"
    }
  ],
  "examples": [...],
  "misconceptions": [...],
  "assessments": [...],
  "status": "needs_review"
}
```

**Note:** All fields are optional. Only include fields you want to update.

### Response
```json
{
  "message": "Guideline updated successfully",
  "version": 2,
  "updated_at": "2025-10-27T13:00:00Z"
}
```

---

## 5. Approve/Reject Guideline

Approve or reject a subtopic guideline for publication.

### Endpoint
```
POST /admin/guidelines/books/{book_id}/subtopics/{subtopic_key}/approve
```

### Path Parameters
| Parameter     | Type   | Required | Description    |
|---------------|--------|----------|----------------|
| book_id       | string | Yes      | Book ID        |
| subtopic_key  | string | Yes      | Subtopic key   |

### Query Parameters
| Parameter  | Type   | Required | Description |
|------------|--------|----------|-------------|
| topic_key  | string | Yes      | Topic key   |

### Request Body
```json
{
  "approved": true,
  "reviewer_notes": "Looks good, approved for publication"
}
```

Or to reject:
```json
{
  "approved": false,
  "reviewer_notes": "Needs more examples. The teaching description is too brief."
}
```

### Response
```json
{
  "message": "Guideline approved",
  "status": "final",
  "previous_status": "stable",
  "version": 2,
  "updated_at": "2025-10-27T13:00:00Z"
}
```

### Status Changes
- **Approved:** `status` → `"final"`
- **Rejected:** `status` → `"needs_review"`

---

## 6. Get Page Assignments

Get the mapping of pages to subtopics for a book.

### Endpoint
```
GET /admin/guidelines/books/{book_id}/page-assignments
```

### Path Parameters
| Parameter | Type   | Required | Description |
|-----------|--------|----------|-------------|
| book_id   | string | Yes      | Book ID     |

### Response
```json
{
  "1": {
    "topic_key": "mathematics-grade-3",
    "subtopic_key": "counting-and-measurement",
    "confidence": 0.92
  },
  "2": {
    "topic_key": "mathematics-grade-3",
    "subtopic_key": "counting-animals",
    "confidence": 0.88
  }
}
```

**Use case:** Display which subtopic each page belongs to in a page-by-page review interface.

---

## 7. Sync to Database

Sync approved guidelines from S3 to the PostgreSQL database.

### Endpoint
```
POST /admin/guidelines/books/{book_id}/sync-to-database
```

### Path Parameters
| Parameter | Type   | Required | Description |
|-----------|--------|----------|-------------|
| book_id   | string | Yes      | Book ID     |

### Query Parameters
| Parameter     | Type   | Required | Default | Description                    |
|---------------|--------|----------|---------|--------------------------------|
| status_filter | string | No       | "final" | Only sync this status          |

### Response
```json
{
  "message": "Successfully synced 8 guidelines to database",
  "book_id": "ncert_mathematics_3_2024",
  "synced_count": 8
}
```

**When to use:**
- After approving guidelines (status="final")
- To make guidelines available via the standard teacher-facing API
- Before publishing a book's curriculum

---

## UI Integration Examples

### Example 1: Books Dashboard

```typescript
// Fetch books with guidelines
async function fetchBooks() {
  const response = await fetch('/admin/guidelines/books');
  const books = await response.json();

  return books.map(book => ({
    id: book.book_id,
    title: book.title,
    progress: (book.pages_processed / book.total_pages) * 100,
    status: book.extraction_status,
    subtopics: book.subtopics_count,
    approved: book.subtopics_approved,
    needsReview: book.subtopics_count - book.subtopics_approved
  }));
}
```

### Example 2: Topic Browser

```typescript
// Fetch topics for a book
async function fetchTopics(bookId: string) {
  const response = await fetch(`/admin/guidelines/books/${bookId}/topics`);
  const topics = await response.json();

  return topics.map(topic => ({
    key: topic.topic_key,
    title: topic.topic_title,
    subtopics: topic.subtopics.map(st => ({
      key: st.subtopic_key,
      title: st.subtopic_title,
      pages: st.page_range,
      status: st.status,
      statusColor: getStatusColor(st.status)
    }))
  }));
}

function getStatusColor(status: string) {
  switch (status) {
    case 'final': return 'green';
    case 'stable': return 'blue';
    case 'needs_review': return 'red';
    case 'open': return 'gray';
  }
}
```

### Example 3: Guideline Detail View

```typescript
// Fetch full guideline for editing/review
async function fetchGuideline(bookId: string, topicKey: string, subtopicKey: string) {
  const response = await fetch(
    `/admin/guidelines/books/${bookId}/subtopics/${subtopicKey}?topic_key=${topicKey}`
  );
  return await response.json();
}

// Display in UI
function GuidelineDetail({ guideline }) {
  return (
    <div>
      <h1>{guideline.subtopic_title}</h1>
      <Badge status={guideline.status} />
      <p>Pages: {guideline.page_range}</p>

      <Section title="Teaching Description">
        <EditableText value={guideline.teaching_description} />
      </Section>

      <Section title="Learning Objectives">
        <List items={guideline.objectives} />
      </Section>

      <Section title="Examples">
        <List items={guideline.examples} />
      </Section>

      <Section title="Common Misconceptions">
        <List items={guideline.misconceptions} />
      </Section>

      <Section title="Assessment Questions">
        <List items={guideline.assessments} />
      </Section>

      <Actions>
        <Button onClick={saveChanges}>Save Changes</Button>
        <Button onClick={approve}>Approve</Button>
        <Button onClick={reject}>Reject</Button>
      </Actions>
    </div>
  );
}
```

### Example 4: Approval Workflow

```typescript
// Approve a guideline
async function approveGuideline(
  bookId: string,
  topicKey: string,
  subtopicKey: string,
  notes: string
) {
  const response = await fetch(
    `/admin/guidelines/books/${bookId}/subtopics/${subtopicKey}/approve?topic_key=${topicKey}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approved: true,
        reviewer_notes: notes
      })
    }
  );

  return await response.json();
}

// Reject with feedback
async function rejectGuideline(
  bookId: string,
  topicKey: string,
  subtopicKey: string,
  feedback: string
) {
  const response = await fetch(
    `/admin/guidelines/books/${bookId}/subtopics/${subtopicKey}/approve?topic_key=${topicKey}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approved: false,
        reviewer_notes: feedback
      })
    }
  );

  return await response.json();
}
```

### Example 5: Batch Approval

```typescript
// Approve multiple guidelines at once
async function batchApprove(guidelines: Array<{ bookId, topicKey, subtopicKey }>) {
  const results = await Promise.all(
    guidelines.map(g =>
      approveGuideline(g.bookId, g.topicKey, g.subtopicKey, 'Batch approved')
    )
  );

  // Then sync to database
  const uniqueBooks = [...new Set(guidelines.map(g => g.bookId))];
  await Promise.all(
    uniqueBooks.map(bookId =>
      fetch(`/admin/guidelines/books/${bookId}/sync-to-database`, { method: 'POST' })
    )
  );

  return results;
}
```

---

## Testing the API

### Using curl

```bash
# List books
curl http://localhost:8000/admin/guidelines/books

# Get topics for a book
curl http://localhost:8000/admin/guidelines/books/ncert_mathematics_3_2024/topics

# Get guideline detail
curl "http://localhost:8000/admin/guidelines/books/ncert_mathematics_3_2024/subtopics/counting-animals?topic_key=mathematics-grade-3"

# Approve a guideline
curl -X POST "http://localhost:8000/admin/guidelines/books/ncert_mathematics_3_2024/subtopics/counting-animals/approve?topic_key=mathematics-grade-3" \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "reviewer_notes": "Looks good!"}'

# Sync to database
curl -X POST http://localhost:8000/admin/guidelines/books/ncert_mathematics_3_2024/sync-to-database
```

### Using FastAPI Docs

The API is automatically documented at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## Error Handling

All endpoints return standard HTTP status codes:

- `200` - Success
- `404` - Book or guideline not found
- `422` - Validation error
- `500` - Server error

Error response format:
```json
{
  "detail": "Book not found"
}
```

---

## Next Steps

1. **Frontend Integration:** Build React/Vue components using these endpoints
2. **Authentication:** Add admin authentication middleware
3. **Permissions:** Role-based access control for reviewers
4. **Webhooks:** Notify on approval/rejection
5. **Export:** Add PDF/DOCX export endpoints
6. **Analytics:** Track review metrics and approval rates
