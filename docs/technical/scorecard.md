# Report Card — Technical

Service architecture, aggregation algorithm, and API for the student report card.

The report card is **deterministic only** — it shows coverage completion percentages (from Teach Me sessions) and latest exam scores. There are no AI-interpreted mastery scores, no aggregate scores at any level, no trend charts, no strengths/weaknesses rankings, and no misconception tracking.

---

## API Endpoints

| Method | Path | Auth | Response Model | Description |
|--------|------|------|----------------|-------------|
| `GET` | `/sessions/report-card` | Required | `ReportCardResponse` | Full student report card with coverage and exam data |
| `GET` | `/sessions/subtopic-progress` | Required | `SubtopicProgressResponse` | Lightweight progress map for curriculum picker badges |

Both endpoints are in `tutor/api/sessions.py` and delegate to `ScorecardService`.

---

## ScorecardService

**File:** `tutor/services/scorecard_service.py`

**Class:** `ScorecardService(db)`

### Public Methods

- `get_scorecard(user_id)` → Full report card dict (used by `/report-card`)
- `get_subtopic_progress(user_id)` → `{user_progress: {guideline_id: {coverage, session_count, status}}}`

### Private Methods

| Method | Purpose |
|--------|---------|
| `_load_user_sessions(user_id)` | Query all sessions for user, ordered `created_at ASC`, `id ASC` |
| `_build_guideline_lookup(sessions)` | Batch-query `teaching_guidelines` to build `guideline_id → {topic, subtopic, keys}` map |
| `_group_sessions(sessions, guideline_lookup)` | Group sessions into subject/topic/subtopic hierarchy; accumulate coverage from teach_me sessions; track latest exam score from exam sessions |
| `_build_report(grouped)` | Build flat report structure with coverage computation per subtopic |
| `_empty_scorecard()` | Return zero-valued report card for users with no sessions |

---

## Data Flow

```
Sessions (DB)
    │
    v
Load all sessions for user (ordered created_at ASC, id ASC)
    │
    v
Batch-query teaching_guidelines → build guideline_id → {topic, subtopic, keys} lookup
    │
    v
Parse each session's state_json → extract:
  - subject, topic hierarchy
  - learning mode (teach_me / clarify_doubts / exam)
  - For teach_me: concepts_covered_set, plan concepts from mastery_estimates keys
  - For exam (finished only): exam_total_correct, len(exam_questions)
    │
    v
Group into subject → topic_key → subtopic_key
  - Only teach_me sessions contribute to coverage accumulation
  - Latest finished exam wins for exam score
    │
    v
Build report (per subtopic):
  coverage    = |concepts covered ∩ plan concepts| / |plan concepts| × 100
  exam score  = latest finished exam's correct/total (or null if no exams)
  last_studied = date of most recent teach_me or finished exam session
```

### Coverage Computation

Coverage is computed in `_build_report` from accumulated data:

```python
plan_concepts = set(sub_info.get("plan_concepts", []))
covered = set(sub_info.get("concepts_covered", []))
coverage = round(len(covered & plan_concepts) / len(plan_concepts) * 100, 1)
```

Key details:
- Only **Teach Me** sessions contribute to coverage. Clarify Doubts and Exam sessions are excluded.
- `concepts_covered` is a **union** across all Teach Me sessions for the subtopic.
- `plan_concepts` comes from the **latest** Teach Me session's `mastery_estimates` keys (not a union). This prevents denominator drift when the study plan is updated.
- If `plan_concepts` is empty, coverage is 0.

### Exam Score Tracking

The `_group_sessions` method tracks the latest completed exam:

```python
if mode == "exam" and state.get("exam_finished", False):
    exam_score = int(state.get("exam_total_correct", 0))
    exam_total = len(state.get("exam_questions", []))
    if exam_total > 0:
        existing_exam_score = exam_score
        existing_exam_total = exam_total
```

- Only records exams where `exam_finished == True` and `exam_total > 0`
- Since sessions are processed in chronological order, the latest exam naturally overwrites earlier ones
- Includes type guards for legacy data (`exam_total_correct` may be float or string)

### Cross-Session Accumulation

The `_group_sessions` method accumulates data across all sessions for the same subtopic:

| Accumulated Field | Source | Logic |
|-------------------|--------|-------|
| `concepts_covered` | `state.concepts_covered_set` (teach_me only) | Union of concepts covered across all Teach Me sessions |
| `plan_concepts` | `state.mastery_estimates` keys (teach_me only) | Latest Teach Me session's plan concepts (overwrites previous) |
| `last_studied` | Session date | Updated by teach_me sessions and finished exam sessions |
| `latest_exam_score` | `state.exam_total_correct` (exam, finished only) | Latest finished exam's correct count |
| `latest_exam_total` | `len(state.exam_questions)` (exam, finished only) | Latest finished exam's total questions |

### Subtopic Progress (Lightweight)

Used by the curriculum picker to show coverage indicators:

- Only counts **Teach Me** sessions (clarify_doubts and exam sessions are excluded entirely)
- `status = "studied"` if `session_count > 0`
- `status = "not_started"` otherwise
- Returns `{user_progress: {guideline_id: {coverage, session_count, status}}}`

---

## Response Schemas

### ReportCardResponse (`/sessions/report-card`)

```python
{
    "total_sessions": int,
    "total_topics_studied": int,
    "subjects": [
        {
            "subject": str,
            "topics": [
                {
                    "topic": str,
                    "topic_key": str,
                    "subtopics": [
                        {
                            "subtopic": str,
                            "subtopic_key": str,
                            "guideline_id": str | None,
                            "coverage": float,                # 0-100%, teach_me only
                            "latest_exam_score": int | None,  # X in X/Y
                            "latest_exam_total": int | None,  # Y in X/Y
                            "last_studied": str | None        # ISO date
                        }
                    ]
                }
            ]
        }
    ]
}
```

### SubtopicProgressResponse (`/sessions/subtopic-progress`)

```python
{
    "user_progress": {
        "<guideline_id>": {
            "coverage": float,       # 0-100%
            "session_count": int,    # teach_me sessions only
            "status": str            # "studied" | "not_started"
        }
    }
}
```

---

## Topic Hierarchy Resolution

The service resolves topic/subtopic names from two sources, in order of preference:

1. **TeachingGuideline table** — If the session's `topic_id` matches a guideline, use `topic_title`/`subtopic_title` (with fallback to `topic`/`subtopic`), plus `topic_key`/`subtopic_key`
2. **Topic name splitting** — If no guideline match, split `topic_name` on `" - "` to derive topic and subtopic
3. **Raw name** — If no separator found, use the full `topic_name` as both topic and subtopic

---

## Frontend

**File:** `llm-frontend/src/pages/ScorecardPage.tsx`

The frontend calls `getReportCard()` which hits `/sessions/report-card`. It renders the report card in two views:

- **Overview** — Title "My Report Card", session/topic counts, subject cards grid
- **Subject Detail** — Back navigation, expandable topic/subtopic tree with coverage bars, exam scores, last-studied dates, and "Practice Again" buttons

### Practice Again Flow

1. User taps "Practice Again" on a subtopic
2. Frontend calls `createSession()` with `guideline_id`
3. Navigates to `/session/{session_id}` with `location.state = {firstTurn, mode, subject}`

### Routing

| Path | Component | Description |
|------|-----------|-------------|
| `/scorecard` | `ScorecardPage` | Primary report card view |
| `/report-card` | `ScorecardPage` | Alias route, same component |

Both routes are protected (require authentication). The page is titled "My Report Card" regardless of which URL is used.

### Frontend API

| Function | Endpoint | Return Type |
|----------|----------|-------------|
| `getReportCard()` | `GET /sessions/report-card` | `ReportCardResponse` |
| `getSubtopicProgress()` | `GET /sessions/subtopic-progress` | `Record<string, SubtopicProgress>` |

Types are defined in `llm-frontend/src/api.ts`.

### Navigation Entry Points

The report card is accessible from:
- User menu in `LearnLayout.tsx` ("My Scorecard" button, navigates to `/scorecard`)
- Session history page (`SessionHistoryPage.tsx`, "View Scorecard" link)
- End-of-session screen in `ChatSession.tsx` (button navigates to `/scorecard`)

---

## Key Files

| File | Purpose |
|------|---------|
| `tutor/services/scorecard_service.py` | Aggregation logic: coverage computation, exam score tracking, hierarchy grouping |
| `tutor/api/sessions.py` | `/report-card` and `/subtopic-progress` endpoints |
| `shared/models/schemas.py` | Response schemas (`ReportCardResponse`, `ReportCardSubtopic`, `SubtopicProgressResponse`) |
| `llm-frontend/src/pages/ScorecardPage.tsx` | Report card UI (overview + subject detail) |
| `llm-frontend/src/api.ts` | Frontend API functions and TypeScript types |
| `tests/unit/test_scorecard_service.py` | Unit tests for coverage, exam score, hierarchy resolution, and resilience |
