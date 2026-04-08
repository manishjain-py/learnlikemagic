# Report Card — Technical

Service architecture, aggregation algorithm, and API for the student report card.

The report card is **deterministic only** — it shows coverage completion percentages (from Teach Me sessions) and latest exam scores. There are no AI-interpreted mastery scores, no aggregate scores at any level, no trend charts, no strengths/weaknesses rankings, and no misconception tracking.

---

## API Endpoints

| Method | Path | Auth | Response Model | Description |
|--------|------|------|----------------|-------------|
| `GET` | `/sessions/report-card` | Required | `ReportCardResponse` | Full student report card with coverage and exam data |
| `GET` | `/sessions/topic-progress` | Required | `TopicProgressResponse` | Lightweight progress map for curriculum picker badges |
| `GET` | `/sessions/resumable?guideline_id=` | Required | `ResumableSessionResponse` | Find paused Teach Me session for a topic (404 if none) |
| `GET` | `/sessions/guideline/{guideline_id}` | Required | `GuidelineSessionsResponse` | List sessions for a topic (mode selection, past exams, resume detection) |
| `GET` | `/sessions/{session_id}/exam-review` | Required | `ExamReviewResponse` | Detailed question-by-question review of a completed exam |

All endpoints are in `tutor/api/sessions.py`. The first two delegate to `ReportCardService`; the resumable endpoint queries `SessionModel` directly for paused teach_me sessions and validates state via `SessionState.model_validate_json`; the guideline sessions endpoint delegates to `SessionRepository.list_by_guideline()`; the exam-review endpoint loads the session, validates `mode == "exam"` and `exam_finished`, then parses `SessionState` directly to build `ExamReviewQuestion` entries.

---

## ReportCardService

**File:** `tutor/services/report_card_service.py`

**Class:** `ReportCardService(db)`

### Public Methods

- `get_report_card(user_id)` → Full report card dict (used by `/report-card`)
- `get_topic_progress(user_id)` → `{user_progress: {guideline_id: {coverage, session_count, status}}}`

### Private Methods

| Method | Purpose |
|--------|---------|
| `_load_user_sessions(user_id)` | Query sessions for user (columns: `id`, `state_json`, `subject`, `mastery`, `created_at`), ordered `created_at ASC`, `id ASC` |
| `_build_guideline_lookup(sessions)` | Batch-query `teaching_guidelines` to build `guideline_id → {chapter, topic, keys}` map |
| `_group_sessions(sessions, guideline_lookup)` | Group sessions into subject/chapter/topic hierarchy; accumulate coverage from teach_me sessions; track latest exam score from exam sessions |
| `_build_report(grouped)` | Build flat report structure with coverage computation per topic |
| `_empty_report_card()` | Return zero-valued report card for users with no sessions |

---

## Data Flow

```
Sessions (DB)
    │
    v
Load all sessions for user (ordered created_at ASC, id ASC)
    │
    v
Batch-query teaching_guidelines → build guideline_id → {chapter, topic, keys} lookup
    │
    v
Parse each session's state_json → extract:
  - subject, chapter/topic hierarchy
  - learning mode (teach_me / clarify_doubts / exam)
  - For teach_me: concepts_covered_set, plan concepts from mastery_estimates keys
  - For exam (finished only): exam_total_correct, len(exam_questions)
    │
    v
Group into subject → chapter_key → topic_key
  - Only teach_me sessions contribute to coverage accumulation
  - Latest finished exam wins for exam score
    │
    v
Build report (per topic):
  coverage    = |concepts covered ∩ plan concepts| / |plan concepts| × 100
  exam score  = latest finished exam's correct/total (or null if no exams)
  last_studied = date of most recent teach_me or finished exam session
```

### Coverage Computation

Coverage is computed in `_build_report` from accumulated data:

```python
plan_concepts = set(topic_info.get("plan_concepts", []))
covered = set(topic_info.get("concepts_covered", []))
coverage = round(len(covered & plan_concepts) / len(plan_concepts) * 100, 1)
```

Key details:
- Only **Teach Me** sessions contribute to coverage. Clarify Doubts and Exam sessions are excluded.
- `concepts_covered` is a **union** across all Teach Me sessions for the topic.
- `plan_concepts` comes from the **latest** Teach Me session's `mastery_estimates` keys (not a union). This prevents denominator drift when the study plan is updated.
- If `plan_concepts` is empty, coverage is 0.

### Exam Score Tracking

The `_group_sessions` method tracks the latest completed exam:

```python
if mode == "exam" and state.get("exam_finished", False):
    raw_score = state.get("exam_total_correct", 0)
    exam_score = int(raw_score) if isinstance(raw_score, (int, float)) else 0
    raw_questions = state.get("exam_questions", [])
    exam_total = len(raw_questions) if isinstance(raw_questions, list) else 0
    if exam_total > 0:
        existing_exam_score = exam_score
        existing_exam_total = exam_total
        existing_last_studied = session_date
```

- Only records exams where `exam_finished == True` and `exam_total > 0`
- Since sessions are processed in chronological order, the latest exam naturally overwrites earlier ones
- Type guards handle legacy data: `exam_total_correct` may be float or string (cast via `isinstance`); `exam_questions` may be non-list (guarded with `isinstance`)
- A finished exam also updates `last_studied` for the topic

### Cross-Session Accumulation

The `_group_sessions` method accumulates data across all sessions for the same topic:

| Accumulated Field | Source | Logic |
|-------------------|--------|-------|
| `concepts_covered` | `state.concepts_covered_set` (teach_me only) | Union of concepts covered across all Teach Me sessions |
| `plan_concepts` | `state.mastery_estimates` keys (teach_me only) | Latest Teach Me session's plan concepts (overwrites previous) |
| `last_studied` | Session date | Updated by teach_me sessions and finished exam sessions |
| `latest_exam_score` | `state.exam_total_correct` (exam, finished only) | Latest finished exam's correct count |
| `latest_exam_total` | `len(state.exam_questions)` (exam, finished only) | Latest finished exam's total questions |

### Topic Progress (Lightweight)

Used by the curriculum picker to show coverage indicators. Both `ChapterSelect.tsx` and `TopicSelect.tsx` call `getTopicProgress()` on mount and use the returned map to render progress badges alongside each chapter or topic.

**Backend** (`ReportCardService.get_topic_progress`):
- Only counts **Teach Me** sessions (clarify_doubts and exam sessions are excluded entirely)
- Coverage uses `mastery_estimates` keys from the latest teach_me session as the plan denominator (same logic as the full report card)
- Returns map keyed by `topic_id` (the session's `state.topic.topic_id`, which is the guideline id)
- Returned `status` is always `"studied"` in practice — entries only exist for guidelines the user has touched. The frontend treats missing keys as "not started" implicitly
- Returns `{user_progress: {guideline_id: {coverage, session_count, status}}}`

**Frontend badge mapping** — Both components define a local `ProgressStatus` type (`completed | in_progress | not_started`) derived from backend coverage values:

- `TopicSelect.tsx`: `coverage >= 80` = completed, `coverage > 0` = in_progress, else not_started. Shows "X% covered" text when coverage > 0.
- `ChapterSelect.tsx`: averages coverage across all `guideline_ids` in the chapter. `avg >= 80` = completed, `avg > 0` = in_progress, else not_started.

Completed items show a checkmark; in_progress and not_started show the sequence number with different styling.

---

## Response Schemas

### ReportCardResponse (`/sessions/report-card`)

```python
{
    "total_sessions": int,
    "total_chapters_studied": int,
    "subjects": [
        {
            "subject": str,
            "chapters": [
                {
                    "chapter": str,
                    "chapter_key": str,
                    "topics": [
                        {
                            "topic": str,
                            "topic_key": str,
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

### TopicProgressResponse (`/sessions/topic-progress`)

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

### ResumableSessionResponse (`/sessions/resumable`)

```python
{
    "session_id": str,
    "coverage": float,           # 0-100%
    "current_step": int,
    "total_steps": int,
    "concepts_covered": [str]
}
```

### GuidelineSessionsResponse (`/sessions/guideline/{guideline_id}`)

```python
{
    "sessions": [
        {
            "session_id": str,
            "mode": str,                      # "teach_me" | "clarify_doubts" | "exam"
            "created_at": str | None,         # ISO datetime
            "is_complete": bool,
            "exam_finished": bool,
            "exam_score": float | None,       # sum of fractional scores (exam only)
            "exam_total": int | None,         # number of questions (exam only)
            "exam_answered": int | None,      # questions with a student answer (exam only)
            "coverage": float | None          # 0-100% (teach_me only)
        }
    ]
}
```

### ExamReviewResponse (`/sessions/{session_id}/exam-review`)

```python
{
    "session_id": str,
    "created_at": str | None,
    "exam_feedback": {                        # null if no feedback generated
        "score": float,
        "total": int,
        "percentage": float,
        "strengths": [str],
        "weak_areas": [str],
        "patterns": [str],
        "next_steps": [str]
    } | None,
    "questions": [
        {
            "question_idx": int,
            "question_text": str,
            "student_answer": str | None,
            "expected_answer": str,
            "result": str | None,
            "score": float,                   # 0-1 fractional
            "marks_rationale": str,
            "feedback": str,
            "concept": str,
            "difficulty": str
        }
    ]
}
```

---

## Guideline Sessions

The `/sessions/guideline/{guideline_id}` endpoint powers the mode selection screen. It returns all sessions for a user+guideline pair, with optional `mode` and `finished_only` query parameters.

`SessionRepository.list_by_guideline()` computes per-session metadata from `state_json`:

| Field | Logic |
|-------|-------|
| `is_complete` | teach_me: `current_step > total_steps`; exam: `exam_finished`; clarify_doubts: `clarify_complete` |
| `exam_score` | Sum of fractional `score` fields across `exam_questions` (rounded to 1 decimal) |
| `exam_answered` | Count of questions with a non-empty `student_answer` |
| `coverage` | teach_me only: `\|concepts_covered_set & plan_concepts\| / \|plan_concepts\| * 100` (plan_concepts from `study_plan.steps[].concept`, not `mastery_estimates`) |

The frontend (`ModeSelection.tsx`) uses this to:
- Detect incomplete teach_me sessions with progress (`coverage > 0`) and show "Continue Lesson"
- Detect incomplete exams with progress (`exam_answered > 0`) and show "Resume Exam"
- Hide the "Take Exam" button while an incomplete exam exists (prevents duplicate exams)
- List completed exams in an expandable "Past Exams" section with date, score, and percentage (color-coded: green >=70%, orange >=40%, red <40%)

Refresher topics (`topic.topic_key === 'get-ready'`) suppress the exam path entirely: no resume-exam, no Take Exam button, no Past Exams section, no Clarify Doubts option. Only the Teach Me ("Get Ready") card is shown.

---

## Exam Review

The `/sessions/{session_id}/exam-review` endpoint returns a question-by-question breakdown of a completed exam. It requires the session to be an exam with `exam_finished == True`.

Each question includes:
- `question_text`, `student_answer`, `expected_answer`
- `score` (0-1 fractional), `result`, `marks_rationale`
- `feedback`, `concept`, `difficulty`

The response also includes `exam_feedback` (when available) with `score`, `total`, `percentage`, `strengths`, `weak_areas`, `patterns`, and `next_steps`.

**Frontend rendering note:** `ExamReviewPage.tsx` currently only renders `next_steps` from `exam_feedback`. The `strengths`, `weak_areas`, and `patterns` fields are returned by the API but not displayed. Per-question score color-coding: green (>= 0.8), orange (>= 0.2), red (< 0.2). Overall score color: green (>= 70%), orange (>= 40%), red (< 40%).

---

## Topic Hierarchy Resolution

The service resolves chapter/topic names from two sources, in order of preference:

1. **TeachingGuideline table** — If the session's `topic_id` matches a guideline, use `chapter_title`/`topic_title` (with fallback to `chapter`/`topic`), plus `chapter_key`/`topic_key`
2. **Topic name splitting** — If no guideline match, split `topic_name` on `" - "` to derive chapter and topic
3. **Raw name** — If no separator found, use the full `topic_name` as both chapter and topic

---

## Frontend

### Report Card Page

**File:** `llm-frontend/src/pages/ReportCardPage.tsx`

The frontend calls `getReportCard()` which hits `/sessions/report-card`. It renders the report card in two views:

- **Overview** — Title "My Report Card", session/chapter counts, subject cards grid
- **Subject Detail** — Back navigation, chapter/topic tree with coverage bars, exam scores, last-studied dates, and "Practice Again" buttons

`ChapterSection` filters out topics where `topic_key === 'get-ready'` so refresher/prerequisite warm-ups don't pollute the report card. "Practice Again" is only rendered when `topic.guideline_id` is set (sessions without a guideline link can't be replayed).

### Mode Selection (Past Exams and Resume)

**File:** `llm-frontend/src/components/ModeSelection.tsx`

On the topic mode selection screen, `ModeSelection` calls `getGuidelineSessions()` on mount. It uses the returned session list to:
- Show "Continue Lesson" if an incomplete teach_me session with coverage > 0 exists
- Show "Resume Exam" if an incomplete exam with answered questions exists
- Show an expandable "Past Exams" section listing completed exams with date and score; tapping an entry navigates to the exam review page

### Exam Review Page

**File:** `llm-frontend/src/pages/ExamReviewPage.tsx`

Calls `getExamReview(sessionId)` and displays the overall score/percentage, a question-by-question breakdown (question text, student answer, expected answer, score, grading rationale), and next steps when available. Score color-coding: green (>= 70%), orange (>= 40%), red (< 40%).

### Practice Again Flow

1. User taps "Practice Again" on a topic
2. Frontend calls `createSession()` with `guideline_id`
3. Navigates to `/session/{session_id}` with `location.state = {firstTurn, mode, subject}`

### Routing

| Path | Component | Description |
|------|-----------|-------------|
| `/report-card` | `ReportCardPage` | Report card view |
| `/learn/:subject/:chapter/:topic/exam-review/:sessionId` | `ExamReviewPage` | Detailed exam review |

All routes are protected (require authentication).

### Frontend API

| Function | Endpoint | Return Type |
|----------|----------|-------------|
| `getReportCard()` | `GET /sessions/report-card` | `ReportCardResponse` |
| `getTopicProgress()` | `GET /sessions/topic-progress` | `Record<string, TopicProgress>` |
| `getResumableSession(guidelineId)` | `GET /sessions/resumable?guideline_id=` | `ResumableSession \| null` |
| `getGuidelineSessions(guidelineId, mode?, finishedOnly?)` | `GET /sessions/guideline/{id}` | `GuidelineSessionEntry[]` |
| `getExamReview(sessionId)` | `GET /sessions/{id}/exam-review` | `ExamReviewResponse` |

Types are defined in `llm-frontend/src/api.ts`.

### Navigation Entry Points

The report card is accessible from:
- User menu in `AppShell.tsx` ("My Report Card" button, navigates to `/report-card`)
- Session history page (`SessionHistoryPage.tsx`, "View Report Card" link)

---

## Key Files

| File | Purpose |
|------|---------|
| `tutor/services/report_card_service.py` | Aggregation logic: coverage computation, exam score tracking, hierarchy grouping |
| `tutor/api/sessions.py` | `/report-card`, `/topic-progress`, `/resumable`, `/guideline/{id}`, and `/exam-review` endpoints |
| `shared/models/schemas.py` | Response schemas (`ReportCardResponse`, `ReportCardSubject`, `ReportCardChapter`, `ReportCardTopic`, `TopicProgressResponse`, `TopicProgressEntry`, `ResumableSessionResponse`, `GuidelineSessionsResponse`, `GuidelineSessionEntry`, `ExamReviewResponse`, `ExamReviewQuestion`) |
| `shared/repositories/session_repository.py` | `list_by_guideline()` — computes per-session completion, exam score, and coverage from `state_json` |
| `llm-frontend/src/pages/ReportCardPage.tsx` | Report card UI (overview + subject detail) |
| `llm-frontend/src/pages/ExamReviewPage.tsx` | Question-by-question exam review page |
| `llm-frontend/src/components/ModeSelection.tsx` | Mode selection with resume detection and past exams list |
| `llm-frontend/src/pages/ModeSelectPage.tsx` | Hosts `ModeSelection` and handles exam review navigation |
| `llm-frontend/src/pages/ChapterSelect.tsx` | Consumes `getTopicProgress()` to show progress badges per chapter |
| `llm-frontend/src/pages/TopicSelect.tsx` | Consumes `getTopicProgress()` to show progress badges per topic |
| `llm-frontend/src/api.ts` | Frontend API functions and TypeScript types |
| `tests/unit/test_report_card_service.py` | Unit tests for coverage, exam score, hierarchy resolution, and resilience |
