# Scorecard — Technical

Service architecture, aggregation algorithm, and API for the student scorecard.

---

## API Endpoint

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/sessions/scorecard` | Required | Full student scorecard |
| `GET` | `/sessions/subtopic-progress` | Required | Lightweight progress map for curriculum picker badges |

Both endpoints are in `tutor/api/sessions.py` and delegate to `ScorecardService`.

---

## ScorecardService

**File:** `tutor/services/scorecard_service.py`

**Class:** `ScorecardService(db)`

### Public Methods

- `get_scorecard(user_id)` → Full scorecard dict
- `get_subtopic_progress(user_id)` → `{guideline_id: {score, session_count, status}}`

---

## Data Flow

```
Sessions (DB)
    │
    v
Load all sessions for user (ordered created_at ASC)
    │
    v
Batch-query teaching_guidelines → build guideline_id → {topic, subtopic, keys} lookup
    │
    v
Parse each session's state_json → extract subject, topic hierarchy, mastery, misconceptions
    │
    v
Group into subject → topic_key → subtopic_key (last session per subtopic wins)
    │
    v
Compute averages bottom-up:
  subtopic score = session mastery
  topic score = mean of subtopics
  subject score = mean of topics
  overall = mean of subjects
    │
    v
Build trend data per subject: [{date, date_label, score}]
    │
    v
Identify top-5 strengths (score >= 0.65) and top-5 needs-practice (score < 0.65)
```

### Aggregation Details

- Sessions are ordered ASC by `created_at`, so the latest session per subtopic naturally overwrites earlier ones
- Subtopics with zero scores (attempted but no mastery) are included in averages
- Trend data is built from all sessions, not just the latest per subtopic
- Misconceptions are aggregated from all sessions per subtopic

### Subtopic Progress (Lightweight)

Used by the curriculum picker to show progress badges:

- `status = "mastered"` if score >= 0.85
- `status = "in_progress"` otherwise

---

## Response Schema

```python
{
    "overall_score": float,
    "total_sessions": int,
    "total_topics_studied": int,
    "subjects": [
        {
            "subject": str,
            "score": float,
            "session_count": int,
            "topics": [
                {
                    "topic": str,
                    "topic_key": str,
                    "score": float,
                    "subtopics": [
                        {
                            "subtopic": str,
                            "subtopic_key": str,
                            "guideline_id": str,
                            "score": float,
                            "session_count": int,
                            "latest_session_date": str,
                            "concepts": {"concept_name": float},
                            "misconceptions": [
                                {"description": str, "resolved": bool}
                            ]
                        }
                    ]
                }
            ],
            "trend": [{"date": str, "date_label": str, "score": float}]
        }
    ],
    "strengths": [{"subtopic": str, "subject": str, "score": float}],
    "needs_practice": [{"subtopic": str, "subject": str, "score": float}]
}
```

---

## Frontend

**File:** `llm-frontend/src/pages/ScorecardPage.tsx`

### Mastery Labels

| Score | Label | Color |
|-------|-------|-------|
| >= 0.85 | Mastered | Green |
| >= 0.65 | Getting Strong | Purple |
| >= 0.45 | Getting There | Orange |
| < 0.45 | Needs Practice | Red |

### Practice Again Flow

1. User taps "Practice Again" on a subtopic
2. Frontend calls `createSession()` with `guideline_id`
3. Navigates to `/` with `location.state = {sessionId, firstTurn}`
4. `TutorApp` reads state and jumps directly into chat mode

---

## Key Files

| File | Purpose |
|------|---------|
| `tutor/services/scorecard_service.py` | Aggregation logic, scorecard building |
| `tutor/api/sessions.py` | `/scorecard` and `/subtopic-progress` endpoints |
| `llm-frontend/src/pages/ScorecardPage.tsx` | Scorecard UI (overview + subject detail) |
