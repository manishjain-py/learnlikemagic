# Student Scorecard — Product Requirements Document

**Status:** Draft
**Date:** 2026-02-19
**Author:** AI-assisted product planning

---

## 1. Problem Statement

Students complete tutoring sessions but have no way to see their cumulative progress across subjects, topics, and concepts. The existing Session History page shows a flat list of past sessions with per-session mastery scores, but provides no aggregated view of strengths, weaknesses, or learning trends. Students (and soon, parents) cannot answer basic questions like:

- "How am I doing in Mathematics overall?"
- "Which topics do I need to focus on?"
- "Am I improving over time?"

## 2. Feature Overview

A **Student Scorecard** page that aggregates performance data from all tutoring sessions into a hierarchical, drill-down view organized by **Subject > Topic > Subtopic > Concept**. Students see where they are strong, where they need improvement, and how they are progressing over time.

## 3. Product Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Audience | Students only (V1) | Keep scope tight; parent/teacher views can layer on later |
| Scoring method | Latest session per subtopic | Reflects current ability; encourages retrying weak topics |
| Gamification | Light — labels + colors, no badges/XP | Matches warm-and-encouraging UX principles without gamifying learning |
| Trend visualization | Yes — simple line chart per subject | High-value insight with minimal complexity (Recharts library) |
| Chart library | Recharts | Lightweight, React-native, widely adopted, supports responsive charts |

## 4. Data Available (No New Collection Needed)

All data already exists in the `sessions` table. Each session's `state_json` contains:

```
state_json.topic.subject         → "Mathematics"
state_json.topic.topic_name      → "Fractions - Comparing Like Denominators"
state_json.topic.topic_id        → guideline_id (links to teaching_guidelines table)
state_json.mastery_estimates     → {"concept_A": 0.85, "concept_B": 0.6, ...}
state_json.misconceptions[]      → [{concept, description, resolved}, ...]
state_json.weak_areas[]          → ["concept_B", ...]
state_json.session_summary.progress_trend → "improving" | "steady" | "struggling"
state_json.session_summary.stuck_points   → ["concept_B explanation"]
sessions.mastery                 → 0.72 (overall session mastery, denormalized)
sessions.subject                 → "Mathematics" (denormalized)
sessions.created_at              → timestamp
```

The `teaching_guidelines` table provides the curriculum hierarchy:
```
subject → topic_title → subtopic_title (with topic_key, subtopic_key for grouping)
```

## 5. Scorecard Hierarchy & Scoring Logic

```
Student
├── Subject (e.g., Mathematics)          → avg of topic scores
│   ├── Topic (e.g., Fractions)          → avg of subtopic scores
│   │   ├── Subtopic (e.g., Comparing)   → latest session mastery
│   │   │   ├── Concept A               → from mastery_estimates
│   │   │   └── Concept B               → from mastery_estimates
│   │   └── Subtopic (e.g., Adding)
│   └── Topic (e.g., Geometry)
└── Subject (e.g., Science)
```

**Scoring rules:**
- **Subtopic score** = `overall_mastery` from the student's most recent session on that subtopic
- **Topic score** = average of its subtopic scores (only subtopics the student has studied)
- **Subject score** = average of its topic scores
- **Overall score** = average of all subject scores
- **Concept scores** = pulled from `mastery_estimates` of the latest session per subtopic

**Mastery labels (student-friendly):**

| Range | Label | Color | Meaning |
|-------|-------|-------|---------|
| >= 0.85 | Mastered | Green (#38a169) | Solid understanding |
| >= 0.65 | Getting Strong | Blue (#667eea) | Good progress, almost there |
| >= 0.45 | Getting There | Orange (#ff9800) | Making progress, keep going |
| < 0.45 | Needs Practice | Red (#e53e3e) | Focus area |

## 6. UI Design

### 6.1 Navigation

New route: `/scorecard` accessible from:
- Main navigation (alongside existing Home `/` and History `/history`)
- Profile page as a link
- Session completion screen as a CTA ("View your Scorecard")

### 6.2 Page Structure — Overview (default view)

```
┌──────────────────────────────────────────┐
│  ← Back              My Scorecard        │
├──────────────────────────────────────────┤
│                                          │
│  ┌────────────────────────────────────┐  │
│  │        Overall Performance         │  │
│  │                                    │  │
│  │    ┌──────┐                        │  │
│  │    │ 72%  │   Getting Strong       │  │
│  │    │ ████ │                        │  │
│  │    └──────┘                        │  │
│  │                                    │  │
│  │  15 sessions · 6 topics studied    │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ── Strengths ────────────────────────   │
│  ┌────────────────────────────────────┐  │
│  │  ✓ Comparing Fractions     92%    │  │
│  │  ✓ Addition of Numbers     88%    │  │
│  │  ✓ Shapes & Patterns      85%    │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ── Needs Practice ───────────────────   │
│  ┌────────────────────────────────────┐  │
│  │  ⚠ Long Division           38%    │  │
│  │  ⚠ Word Problems           42%    │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ── Subjects ─────────────────────────   │
│                                          │
│  ┌────────────────┐ ┌────────────────┐  │
│  │  Mathematics   │ │   Science      │  │
│  │  ▓▓▓▓▓▓░░ 75% │ │  ▓▓▓▓▓▓▓░ 82% │  │
│  │  4 topics      │ │  2 topics      │  │
│  │  ›             │ │  ›             │  │
│  └────────────────┘ └────────────────┘  │
│                                          │
│  ── Recent Progress ──────────────────   │
│  ┌────────────────────────────────────┐  │
│  │  [Line chart: mastery over time]   │  │
│  │  x-axis: session dates             │  │
│  │  y-axis: mastery % (0-100)         │  │
│  │  one line per subject              │  │
│  └────────────────────────────────────┘  │
│                                          │
└──────────────────────────────────────────┘
```

### 6.3 Subject Drill-down View

Tapping a subject card navigates to the subject detail view.

```
┌──────────────────────────────────────────┐
│  ← Scorecard       Mathematics    75%    │
├──────────────────────────────────────────┤
│                                          │
│  ── Mastery Trend ────────────────────   │
│  ┌────────────────────────────────────┐  │
│  │  [Line chart: math mastery trend]  │  │
│  │  data points = session end scores  │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ── Topics ───────────────────────────   │
│                                          │
│  ┌─ Numbers & Operations ──── 78% ───┐  │
│  │                                    │  │
│  │  Addition of Numbers    92%  ✓     │  │
│  │  ▓▓▓▓▓▓▓▓▓░                       │  │
│  │                                    │  │
│  │  Subtraction            85%  ✓     │  │
│  │  ▓▓▓▓▓▓▓▓░░                       │  │
│  │                                    │  │
│  │  Multiplication         72%        │  │
│  │  ▓▓▓▓▓▓▓░░░                       │  │
│  │                                    │  │
│  │  Long Division          38%  ⚠     │  │
│  │  ▓▓▓░░░░░░░                       │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌─ Fractions ──────────── 88% ──────┐  │
│  │                                    │  │
│  │  Comparing Fractions    92%  ✓     │  │
│  │  Adding Fractions       82%        │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ── Misconceptions ───────────────────   │
│  ┌────────────────────────────────────┐  │
│  │  ⚠ "Larger denominator means a    │  │
│  │     larger fraction"               │  │
│  │     Topic: Fractions · Resolved ✓  │  │
│  │                                    │  │
│  │  ⚠ "Division always makes the     │  │
│  │     number smaller"                │  │
│  │     Topic: Division · Active ●     │  │
│  └────────────────────────────────────┘  │
│                                          │
└──────────────────────────────────────────┘
```

### 6.4 Subtopic Detail (expandable within topic)

Tapping a subtopic row within the topic card expands to show concept-level detail.

```
┌─ Comparing Fractions ─────── 92% ─────┐
│  ▓▓▓▓▓▓▓▓▓░  Mastered                 │
│                                        │
│  Concepts:                             │
│    Like denominators       0.95  ✓     │
│    Unlike denominators     0.88  ✓     │
│    Equivalent fractions    0.92  ✓     │
│                                        │
│  Sessions: 3 (latest: Feb 15, 2026)   │
│                                        │
│  ┌ Practice Again ─────────────────┐   │
│  └─────────────────────────────────┘   │
└────────────────────────────────────────┘
```

### 6.5 Empty State

```
┌──────────────────────────────────────────┐
│  ← Back              My Scorecard        │
├──────────────────────────────────────────┤
│                                          │
│         📊                               │
│                                          │
│    Your scorecard is empty!              │
│                                          │
│    Complete a learning session to see     │
│    how you're doing across subjects      │
│    and topics.                           │
│                                          │
│    ┌─── Start Learning ──────────────┐   │
│    └─────────────────────────────────┘   │
│                                          │
└──────────────────────────────────────────┘
```

### 6.6 Design Principles (from existing UX)

- **Mobile-first**: Cards stack vertically, 44px tap targets, no hover-only interactions
- **Warm & encouraging**: "Getting Strong" not "Insufficient", green/blue before red
- **One thing per screen**: Overview → Subject → Topic detail is progressive disclosure
- **Consistent**: Same card styles, gradients, spacing as existing app
- **Fast**: Scorecard data loaded in a single API call, chart renders after initial paint

## 7. API Design

### 7.1 New Endpoint: `GET /sessions/scorecard`

**Auth:** Required (Bearer token)

**Response:**

```json
{
  "overall_score": 0.72,
  "total_sessions": 15,
  "total_topics_studied": 6,
  "subjects": [
    {
      "subject": "Mathematics",
      "score": 0.75,
      "session_count": 12,
      "topics": [
        {
          "topic": "Numbers & Operations",
          "topic_key": "numbers-and-operations",
          "score": 0.78,
          "subtopics": [
            {
              "subtopic": "Addition of Numbers",
              "subtopic_key": "addition-of-numbers",
              "guideline_id": "guid-123",
              "score": 0.92,
              "session_count": 3,
              "latest_session_date": "2026-02-15T10:30:00Z",
              "concepts": {
                "single digit addition": 0.95,
                "carrying over": 0.88
              },
              "misconceptions": [
                {
                  "description": "Forgets to carry over",
                  "resolved": true
                }
              ]
            }
          ]
        }
      ],
      "trend": [
        {"date": "2026-01-10", "score": 0.45},
        {"date": "2026-01-18", "score": 0.58},
        {"date": "2026-02-01", "score": 0.72},
        {"date": "2026-02-15", "score": 0.75}
      ]
    }
  ],
  "strengths": [
    {"subtopic": "Comparing Fractions", "subject": "Mathematics", "score": 0.92},
    {"subtopic": "Addition of Numbers", "subject": "Mathematics", "score": 0.88}
  ],
  "needs_practice": [
    {"subtopic": "Long Division", "subject": "Mathematics", "score": 0.38},
    {"subtopic": "Word Problems", "subject": "Mathematics", "score": 0.42}
  ]
}
```

### 7.2 Backend Implementation

**New file:** `llm-backend/tutor/services/scorecard_service.py`

**Logic:**
1. Load all sessions for user: `SELECT * FROM sessions WHERE user_id = ? ORDER BY created_at`
2. For each session, parse `state_json` to extract:
   - `topic.subject`, `topic.topic_name` (split on " - " for topic vs subtopic)
   - `topic.topic_id` (guideline_id for linking to curriculum)
   - `mastery_estimates` (concept-level scores)
   - `misconceptions` (with resolved status)
   - `overall_mastery` (session-level score)
3. Group by subject → topic → subtopic
4. For each subtopic, keep only the latest session's data (by `created_at`)
5. Compute topic/subject averages
6. Build trend data: collect (date, mastery) pairs per subject across all sessions
7. Identify top 5 strengths (highest subtopic scores) and top 5 needs-practice (lowest)

**New file:** `llm-backend/shared/repositories/scorecard_repository.py` (or extend `session_repository.py`)

Adds a method to efficiently load all sessions for scorecard aggregation:
```python
def get_sessions_for_scorecard(self, user_id: str) -> list[dict]:
    """Load sessions with state_json for scorecard aggregation."""
    rows = (
        self.db.query(SessionModel.id, SessionModel.state_json,
                       SessionModel.subject, SessionModel.mastery,
                       SessionModel.created_at)
        .filter(SessionModel.user_id == user_id)
        .order_by(SessionModel.created_at.asc())
        .all()
    )
    return rows
```

**New route in:** `llm-backend/tutor/api/sessions.py`

```python
@router.get("/sessions/scorecard")
def get_scorecard(user_id: str = Depends(get_current_user), db = Depends(get_db)):
    service = ScorecardService(db)
    return service.get_scorecard(user_id)
```

### 7.3 Topic Grouping Strategy

The `topic.topic_name` field stores `"{topic} - {subtopic}"`. To reconstruct the hierarchy:

1. **Primary**: Use `topic.topic_id` (guideline_id) to JOIN with `teaching_guidelines` table and get `topic_title` + `subtopic_title` + `topic_key` + `subtopic_key`
2. **Fallback**: Split `topic_name` on ` - ` to get topic and subtopic (for sessions without guideline_id match)

This gives us clean grouping without depending on string parsing.

## 8. Frontend Implementation

### 8.1 New Files

```
llm-frontend/src/
├── pages/
│   └── ScorecardPage.tsx          # Main scorecard page (overview + drill-down)
├── components/
│   ├── scorecard/
│   │   ├── OverallScoreCard.tsx    # Circular progress + stats at top
│   │   ├── StrengthsList.tsx       # Top strengths section
│   │   ├── NeedsPracticeList.tsx   # Areas needing work
│   │   ├── SubjectCard.tsx         # Subject summary card (clickable)
│   │   ├── SubjectDetail.tsx       # Subject drill-down view
│   │   ├── TopicSection.tsx        # Topic accordion with subtopic rows
│   │   ├── SubtopicDetail.tsx      # Expandable concept-level detail
│   │   ├── MasteryBar.tsx          # Reusable colored progress bar
│   │   ├── MasteryBadge.tsx        # Label + color badge (Mastered, etc.)
│   │   ├── TrendChart.tsx          # Recharts line chart wrapper
│   │   └── MisconceptionsList.tsx  # Misconceptions with resolved status
│   └── ...
```

### 8.2 State Management

- Single API call on page load: `GET /sessions/scorecard`
- Local state in `ScorecardPage.tsx` using `useState` (no global state needed)
- Drill-down managed via URL params or local state: `view: "overview" | "subject"`
- Selected subject stored in state, not as a separate route (keeps navigation simple)

### 8.3 Chart Integration

Install Recharts:
```bash
npm install recharts
```

Use `<LineChart>` for trend visualization with responsive container. Render chart after initial data paint to keep perceived load time low.

### 8.4 Styling

Follow existing patterns — pure CSS in `App.css` with class names prefixed `scorecard-`. Use existing color variables and gradient patterns. Key additions:

- `.scorecard-page` — page container
- `.scorecard-overall` — hero card with circular progress
- `.scorecard-subject-card` — clickable subject card
- `.scorecard-topic-section` — expandable topic accordion
- `.mastery-bar` — colored progress bar (reusable)
- `.mastery-badge` — label pill (green/blue/orange/red)

## 9. Implementation Plan

### Phase 1: Backend API

1. Create `ScorecardService` with aggregation logic
2. Add `GET /sessions/scorecard` endpoint
3. Write unit tests for scoring and grouping logic

### Phase 2: Frontend — Overview Page

4. Create `ScorecardPage` with overall score, strengths, needs-practice
5. Create `SubjectCard` components
6. Add route `/scorecard` and navigation link
7. Style with pure CSS following existing patterns
8. Handle empty state

### Phase 3: Frontend — Drill-down + Charts

9. Implement `SubjectDetail` with topic sections
10. Implement `TopicSection` accordion with subtopic expansion
11. Add `SubtopicDetail` with concept scores and misconceptions
12. Install Recharts and implement `TrendChart`
13. Add "Practice Again" CTA that links to session creation for that subtopic

### Phase 4: Integration & Polish

14. Add scorecard link to session completion screen
15. Add nav link (bottom nav or header)
16. Mobile responsiveness testing
17. Loading skeleton states
18. Error handling for API failures

## 10. Performance Considerations

- **Scorecard computation**: Parsing `state_json` for all sessions is O(n) per user. For a student with ~50 sessions, this is fast (< 100ms). If scale requires it, a materialized `scorecard_cache` table can be added later — but premature for V1.
- **Frontend**: Single API call, no waterfall. Chart renders lazily after initial content paint.
- **Payload size**: The response JSON is lightweight (no conversation logs, no full state). Estimated < 5KB for a typical student.

## 11. Future Extensions (Out of Scope for V1)

- **Parent/teacher view**: Shared scorecard with different permissions
- **Time filtering**: "Last 30 days" / "This semester" / "All time"
- **Recommendations engine**: AI-generated "study next" suggestions based on scorecard data
- **Comparative benchmarks**: "You're ahead of 70% of students in your grade"
- **PDF export**: Downloadable report card
- **Push notifications**: "Your Math score improved 15% this week!"

## 12. Success Metrics

- **Adoption**: % of active students who visit the scorecard page at least once per week
- **Engagement**: Average time on scorecard page, drill-down depth
- **Re-engagement**: Do students who view their scorecard start more sessions on weak topics?
- **Retention**: Correlation between scorecard usage and 30-day retention

## 13. Resolved Questions

| # | Question | Decision |
|---|----------|----------|
| 1 | Show unstudied subtopics in scorecard? | **No.** Scorecard only shows what the student has covered. Instead, the **topic selection screen** gets color-coded indicators showing covered / in-progress / not-started topics (see Section 14). |
| 2 | Trend chart granularity? | **One data point per session.** Each session's end mastery score is a point on the chart. |
| 3 | "Practice Again" button behavior? | **TBD** — pending product decision. |

## 14. Topic Selection Screen — Coverage Indicators

As a companion to the scorecard, the existing **topic/subtopic selection screen** (curriculum picker) gets color-coded status indicators so students can see at a glance what they've covered, what's in progress, and what's new.

### 14.1 Status Definitions

| Status | Condition | Visual |
|--------|-----------|--------|
| **Mastered** | Latest session mastery >= 0.85 | Green dot / checkmark |
| **In Progress** | At least one session exists, mastery < 0.85 | Orange/blue dot |
| **Not Started** | No session exists for this subtopic | No indicator (default) |

### 14.2 Wireframe — Subtopic Selection with Indicators

```
┌──────────────────────────────────────────┐
│  Select a subtopic                       │
│  Mathematics > Fractions                 │
├──────────────────────────────────────────┤
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  ● Comparing Fractions    ✓ 92%   │  │  ← Green: Mastered
│  │    Compare fractions with like...  │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  ● Adding Fractions        68%    │  │  ← Blue: In Progress
│  │    Add fractions with like and...  │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │    Subtracting Fractions           │  │  ← No indicator: Not Started
│  │    Subtract fractions with...      │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │    Multiplying Fractions           │  │  ← No indicator: Not Started
│  │    Multiply simple fractions...    │  │
│  └────────────────────────────────────┘  │
│                                          │
└──────────────────────────────────────────┘
```

### 14.3 Data Requirement

The topic selection screen needs a lightweight lookup of "which guideline_ids has this user completed sessions for, and what was the latest mastery?" This can be served by a new endpoint or piggybacked onto the existing `/curriculum` response when a user is authenticated:

```json
// Additional field in curriculum response when authenticated
"user_progress": {
  "guid-123": {"score": 0.92, "session_count": 3, "status": "mastered"},
  "guid-456": {"score": 0.68, "session_count": 1, "status": "in_progress"}
}
```

### 14.4 Implementation

- Backend: Add a `get_user_subtopic_progress(user_id)` method that returns `{guideline_id → {score, session_count, status}}`
- Frontend: Overlay status indicators on existing subtopic selection cards
- This is a lightweight addition — no new page, just enriching the existing curriculum picker
