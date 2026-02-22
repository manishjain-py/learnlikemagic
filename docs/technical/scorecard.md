# Scorecard — Technical

Service architecture, aggregation algorithm, and API for the student scorecard.

---

## API Endpoints

| Method | Path | Auth | Response Model | Description |
|--------|------|------|----------------|-------------|
| `GET` | `/sessions/scorecard` | Required | `ScorecardResponse` | Full student scorecard |
| `GET` | `/sessions/report-card` | Required | `ReportCardResponse` | Same data as scorecard, with additional coverage and exam fields |
| `GET` | `/sessions/subtopic-progress` | Required | `SubtopicProgressResponse` | Lightweight progress map for curriculum picker badges |

All endpoints are in `tutor/api/sessions.py` and delegate to `ScorecardService`. Both `/scorecard` and `/report-card` call the same `get_scorecard()` method — the difference is in the Pydantic response model that selects which fields to include.

---

## ScorecardService

**File:** `tutor/services/scorecard_service.py`

**Class:** `ScorecardService(db)`

### Public Methods

- `get_scorecard(user_id)` → Full scorecard dict (used by both `/scorecard` and `/report-card`)
- `get_subtopic_progress(user_id)` → `{guideline_id: {score, session_count, status}}`

### Private Methods

| Method | Purpose |
|--------|---------|
| `_load_user_sessions(user_id)` | Query all sessions for user, ordered `created_at ASC`, `id ASC` |
| `_build_guideline_lookup(sessions)` | Batch-query `teaching_guidelines` to build `guideline_id → {topic, subtopic, keys}` map |
| `_group_sessions(sessions, guideline_lookup)` | Group sessions into subject/topic/subtopic hierarchy, accumulate cross-session data |
| `_compute_scores(grouped)` | Bottom-up score averaging, coverage computation, exam history, revision nudges |
| `_attach_trends(subjects_data, trends_raw)` | Attach trend data points to each subject |
| `_collect_all_subtopics(subjects_data)` | Flatten subtopics for strengths/needs-practice ranking |
| `_empty_scorecard()` | Return zero-valued scorecard for users with no sessions |
| `_get_revision_nudge(last_studied, coverage)` | Generate time-based revision suggestions |

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
  - subject, topic hierarchy, mastery, misconceptions
  - learning mode (teach_me / clarify_doubts / exam)
  - concepts_covered_set (accumulated across sessions)
  - exam results (score, total, feedback) for finished exams
    │
    v
Group into subject → topic_key → subtopic_key
  - Latest session per subtopic wins for mastery score
  - Cross-session accumulation: concepts covered, exam history, per-mode session counts
    │
    v
Compute bottom-up:
  subtopic score = latest session mastery
  topic score    = mean of subtopic scores
  subject score  = mean of topic scores
  overall        = mean of subject scores
    │
    v
Per subtopic, also compute:
  coverage         = |concepts covered ∩ plan concepts| / |plan concepts| × 100
  revision_nudge   = time-based suggestion (7/14/30 day thresholds)
  latest_exam_*    = most recent exam score, total, feedback
  per-mode counts  = teach_me_sessions, clarify_sessions, exam_count
    │
    v
Build trend data per subject: [{date, date_label, score}]
    │
    v
Identify top-5 strengths (score >= 0.65) and top-5 needs-practice (score < 0.65)
```

### Aggregation Details

- Sessions are ordered ASC by `created_at` (then `id`), so the latest session per subtopic naturally overwrites earlier ones
- Subtopics with zero scores (attempted but no mastery) are included in averages
- Trend data is built from all sessions, not just the latest per subtopic
- Misconceptions are aggregated from all sessions per subtopic
- `concepts_covered_set` is accumulated as a union across all sessions for a subtopic
- Exam history only records completed exams (`exam_finished == True` and `mode == "exam"`)

### Cross-Session Accumulation

The `_group_sessions` method accumulates data across all sessions for the same subtopic:

| Accumulated Field | Source | Logic |
|-------------------|--------|-------|
| `session_count` | Incremented per session | Total sessions on this subtopic |
| `teach_me_sessions` | `state.mode == "teach_me"` | Count of Teach Me sessions |
| `clarify_sessions` | `state.mode == "clarify_doubts"` | Count of Clarify Doubts sessions |
| `exam_count` | `mode == "exam" and exam_finished` | Count of completed exams |
| `all_concepts_covered` | `state.concepts_covered_set` | Union of concepts covered across all sessions |
| `exam_history` | Exam results from completed exams | List of `{date, score, total, percentage}` |
| `exam_feedback` | `state.exam_feedback` | Most recent exam's AI feedback |

### Coverage Computation

Coverage is computed in `_compute_scores` from accumulated data:

```python
all_covered = set(sub_info["all_concepts_covered"])
all_plan_concepts = set(sub_info["concepts"].keys())  # from mastery_estimates
coverage = len(all_covered & all_plan_concepts) / len(all_plan_concepts) * 100
```

This measures what fraction of the subtopic's study plan concepts the student has encountered across all sessions, not just the latest.

### Revision Nudge Logic

The `_get_revision_nudge` method generates time-based revision suggestions:

| Days Since Last Study | Coverage Threshold | Nudge |
|----------------------|-------------------|-------|
| >= 30 | >= 20% | "It's been over a month -- take a quick exam to check how much you remember" |
| >= 14 | >= 20% | "It's been a while -- consider revising" |
| >= 7 | >= 60% | "Time to revisit? A quick exam can show where you stand" |
| < 7 or < 20% coverage | — | No nudge |

### Subtopic Progress (Lightweight)

Used by the curriculum picker to show progress badges:

- `status = "mastered"` if score >= 0.85
- `status = "in_progress"` otherwise
- Returns `{user_progress: {guideline_id: {score, session_count, status}}}`

### Date Label Formatting

When sessions span multiple calendar years, date labels include the year (`"Feb 22, 2026"`). When all sessions are in the same year, only month and day are shown (`"Feb 22"`).

---

## Response Schemas

### ScorecardResponse (`/sessions/scorecard`)

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
                            "guideline_id": str | None,
                            "score": float,
                            "session_count": int,
                            "latest_session_date": str | None,
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

### ReportCardResponse (`/sessions/report-card`)

Same top-level structure, but subtopics include additional fields:

```python
{
    # ... same top-level fields as ScorecardResponse ...
    "subjects": [
        {
            # ... same subject fields ...
            "topics": [
                {
                    # ... same topic fields ...
                    "subtopics": [
                        {
                            # All ScorecardSubtopic fields, plus:
                            "coverage": float,           # % of plan concepts covered
                            "last_studied": str | None,  # ISO date of latest session
                            "revision_nudge": str | None, # Time-based revision suggestion
                            "latest_exam_score": int | None,
                            "latest_exam_total": int | None,
                            "latest_exam_feedback": {    # AI feedback from latest exam
                                "strengths": [str],
                                "weak_areas": [str],
                                "patterns": [str],
                                "next_steps": [str]
                            } | None,
                            "exam_count": int,
                            "exam_history": [
                                {"date": str, "score": int, "total": int, "percentage": float}
                            ],
                            "teach_me_sessions": int,
                            "clarify_sessions": int
                        }
                    ]
                }
            ]
        }
    ]
}
```

The `ScorecardResponse` model filters out the extra fields via its Pydantic schema (`ScorecardSubtopic`), while `ReportCardResponse` uses `ReportCardSubtopic` which includes all of them.

---

## Topic Hierarchy Resolution

The service resolves topic/subtopic names from two sources, in order of preference:

1. **TeachingGuideline table** — If the session's `topic_id` matches a guideline, use `topic_title`/`subtopic_title` (with fallback to `topic`/`subtopic`), plus `topic_key`/`subtopic_key`
2. **Topic name splitting** — If no guideline match, split `topic_name` on `" - "` to derive topic and subtopic
3. **Raw name** — If no separator found, use the full `topic_name` as both topic and subtopic

---

## Frontend

**File:** `llm-frontend/src/pages/ScorecardPage.tsx`

The frontend only uses the `ScorecardResponse` schema (not the extended report card fields). It renders the scorecard in two views:

- **Overview** — Overall hero, strengths/needs-practice highlights, subject cards, multi-subject trend chart
- **Subject Detail** — Single-subject trend, expandable topic/subtopic tree, subject-level misconceptions summary

### Mastery Labels

| Score | Label | Color |
|-------|-------|-------|
| >= 0.85 | Mastered | Green (`#38a169`) |
| >= 0.65 | Getting Strong | Purple (`#667eea`) |
| >= 0.45 | Getting There | Orange (`#ff9800`) |
| < 0.45 | Needs Practice | Red (`#e53e3e`) |

### Practice Again Flow

1. User taps "Practice Again" on a subtopic
2. Frontend calls `createSession()` with `guideline_id`
3. Navigates to `/` with `location.state = {sessionId, firstTurn}`
4. `TutorApp` reads state and jumps directly into chat mode

### Routing

| Path | Component | Description |
|------|-----------|-------------|
| `/scorecard` | `ScorecardPage` | Primary scorecard view |
| `/report-card` | `ScorecardPage` | Alias route, same component |

Both routes are protected (require authentication).

### Frontend API

| Function | Endpoint | Return Type |
|----------|----------|-------------|
| `getScorecard()` | `GET /sessions/scorecard` | `ScorecardResponse` |
| `getReportCard()` | `GET /sessions/report-card` | `ScorecardResponse` |
| `getSubtopicProgress()` | `GET /sessions/subtopic-progress` | `Record<string, SubtopicProgress>` |

Types are defined in `llm-frontend/src/api.ts`.

---

## Key Files

| File | Purpose |
|------|---------|
| `tutor/services/scorecard_service.py` | Aggregation logic, scorecard building, coverage, revision nudges |
| `tutor/api/sessions.py` | `/scorecard`, `/report-card`, and `/subtopic-progress` endpoints |
| `shared/models/schemas.py` | Response schemas (`ScorecardResponse`, `ReportCardResponse`, `SubtopicProgressResponse`) |
| `llm-frontend/src/pages/ScorecardPage.tsx` | Scorecard UI (overview + subject detail) |
| `llm-frontend/src/api.ts` | Frontend API functions and TypeScript types |
| `tests/unit/test_scorecard_service.py` | Unit tests for aggregation logic |
