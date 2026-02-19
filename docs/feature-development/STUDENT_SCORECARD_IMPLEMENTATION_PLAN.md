# Student Scorecard — Technical Implementation Plan

**Date:** 2026-02-19
**PRD:** `docs/feature-development/STUDENT_SCORECARD_PRD.md`
**Branch:** `claude/plan-student-scorecard-6ttw7`

---

## Table of Contents

1. [Key Findings from Codebase Analysis](#1-key-findings-from-codebase-analysis)
2. [Data Flow Architecture](#2-data-flow-architecture)
3. [Backend Implementation](#3-backend-implementation)
4. [Frontend Implementation](#4-frontend-implementation)
5. [Testing Strategy](#5-testing-strategy)
6. [File Change Summary](#6-file-change-summary)
7. [Implementation Phases](#7-implementation-phases)
8. [Risk & Edge Cases](#8-risk--edge-cases)

---

## 1. Key Findings from Codebase Analysis

### How Session Data Maps to Scorecard

Each session stores a `state_json` blob containing a serialized `SessionState` (defined in `tutor/models/session_state.py`). The relevant fields:

```python
# Inside state_json (SessionState model):
state.topic.topic_id       # = guideline_id (set in topic_adapter.py:70)
state.topic.topic_name     # = "{topic} - {subtopic}" (topic_adapter.py:71)
state.topic.subject        # = "Mathematics" (direct from guideline)
state.topic.grade_level    # = 3
state.mastery_estimates    # = {"concept_A": 0.85, "concept_B": 0.6}
state.misconceptions       # = [Misconception(concept, description, resolved)]
state.weak_areas           # = ["concept_B"]
state.session_summary.progress_trend  # = "improving" | "steady" | "struggling"
state.overall_mastery      # property: avg of mastery_estimates values

# Denormalized on sessions table:
sessions.mastery           # = overall_mastery (Float)
sessions.subject           # = "Mathematics" (String)
sessions.user_id           # = FK to users.id
sessions.created_at        # = timestamp
```

### Curriculum Hierarchy Source

The `teaching_guidelines` table provides the canonical hierarchy:
- `subject` -> `topic` (or `topic_title`) -> `subtopic` (or `subtopic_title`)
- `topic_key`, `subtopic_key` for stable grouping
- Each guideline has a unique `id` which is stored as `topic.topic_id` in SessionState

### Topic Name Format

`topic_adapter.py:71` constructs: `topic_name = f"{guideline.topic} - {guideline.subtopic}"`

This means we can reconstruct the hierarchy by:
1. **Primary:** Use `topic.topic_id` (= guideline_id) to JOIN with `teaching_guidelines` for canonical `topic` + `subtopic` names
2. **Fallback:** Split `topic_name` on ` - ` for sessions where the guideline_id lookup fails

### Existing Patterns to Follow

- **Repository:** `SessionRepository` (CRUD class, takes `db: DBSession` in constructor)
- **Service:** `SessionService` (business logic, creates repo internally)
- **API:** Router in `tutor/api/sessions.py`, uses `Depends(get_current_user)` for auth
- **Tests:** `tests/unit/test_session_repository.py` pattern - class-based, `db_session` fixture, in-memory SQLite
- **Frontend:** `SessionHistoryPage.tsx` pattern - `useState` + `useEffect`, direct `fetch()` with auth token, pure CSS in `App.css`

---

## 2. Data Flow Architecture

```
┌─────────────────┐     GET /sessions/scorecard     ┌──────────────────────┐
│   ScorecardPage │ ──────────────────────────────► │  sessions.py router  │
│   (React)       │ ◄────────────────────────────── │                      │
└─────────────────┘     ScorecardResponse JSON      └──────────┬───────────┘
                                                                │
                                                    ┌───────────▼───────────┐
                                                    │  ScorecardService     │
                                                    │                       │
                                                    │  1. Load sessions     │
                                                    │  2. Load guideline    │
                                                    │     hierarchy         │
                                                    │  3. Parse state_json  │
                                                    │  4. Group & aggregate │
                                                    │  5. Build response    │
                                                    └──┬──────────┬────────┘
                                                       │          │
                                              ┌────────▼──┐   ┌──▼───────────────┐
                                              │ SessionRepo│   │ GuidelineRepo    │
                                              │ (sessions) │   │ (hierarchy data) │
                                              └────────────┘   └──────────────────┘
```

---

## 3. Backend Implementation

### 3.1 New File: `llm-backend/tutor/services/scorecard_service.py`

This is the core aggregation logic. It follows the existing service pattern (see `session_service.py`).

```python
"""Scorecard aggregation service — builds student progress report from session data."""

import json
import logging
from collections import defaultdict
from typing import Optional
from sqlalchemy.orm import Session as DBSession

from shared.models.entities import Session as SessionModel, TeachingGuideline
from shared.repositories import SessionRepository

logger = logging.getLogger("tutor.scorecard_service")


class ScorecardService:
    """Aggregates session data into a hierarchical student scorecard."""

    def __init__(self, db: DBSession):
        self.db = db

    def get_scorecard(self, user_id: str) -> dict:
        """
        Build the complete scorecard for a student.

        Steps:
        1. Load all sessions for the user (lightweight: id, state_json, subject, mastery, created_at)
        2. Build a guideline_id → {topic, subtopic, topic_key, subtopic_key} lookup from teaching_guidelines
        3. Parse each session's state_json, extract topic hierarchy + mastery data
        4. Group by subject → topic → subtopic, keeping only latest session per subtopic
        5. Compute averages bottom-up (subtopic → topic → subject → overall)
        6. Build trend data (date + mastery per subject)
        7. Identify strengths and needs-practice subtopics
        """
        # Step 1: Load sessions
        sessions = self._load_user_sessions(user_id)
        if not sessions:
            return self._empty_scorecard()

        # Step 2: Build guideline hierarchy lookup
        guideline_lookup = self._build_guideline_lookup(sessions)

        # Step 3-4: Parse and group sessions
        grouped, trends_raw = self._group_sessions(sessions, guideline_lookup)

        # Step 5: Compute scores
        subjects_data = self._compute_scores(grouped)

        # Step 6: Build trend data
        self._attach_trends(subjects_data, trends_raw)

        # Step 7: Identify strengths and needs-practice
        all_subtopics = self._collect_all_subtopics(subjects_data)
        strengths = sorted(all_subtopics, key=lambda x: x["score"], reverse=True)[:5]
        needs_practice = sorted(
            [s for s in all_subtopics if s["score"] < 0.65],
            key=lambda x: x["score"]
        )[:5]

        # Overall score
        subject_scores = [s["score"] for s in subjects_data if s["score"] > 0]
        overall_score = sum(subject_scores) / len(subject_scores) if subject_scores else 0.0

        total_sessions = len(sessions)
        total_topics = sum(len(s["topics"]) for s in subjects_data)

        return {
            "overall_score": round(overall_score, 2),
            "total_sessions": total_sessions,
            "total_topics_studied": total_topics,
            "subjects": subjects_data,
            "strengths": [{"subtopic": s["subtopic"], "subject": s["subject"], "score": s["score"]}
                          for s in strengths],
            "needs_practice": [{"subtopic": s["subtopic"], "subject": s["subject"], "score": s["score"]}
                               for s in needs_practice],
        }
```

**Key methods (pseudocode):**

#### `_load_user_sessions(user_id)`
```python
def _load_user_sessions(self, user_id: str) -> list:
    """Load all sessions for the user, ordered by created_at ascending."""
    return (
        self.db.query(
            SessionModel.id,
            SessionModel.state_json,
            SessionModel.subject,
            SessionModel.mastery,
            SessionModel.created_at,
        )
        .filter(SessionModel.user_id == user_id)
        .order_by(SessionModel.created_at.asc())
        .all()
    )
```

#### `_build_guideline_lookup(sessions)`
```python
def _build_guideline_lookup(self, sessions) -> dict:
    """
    Build guideline_id → hierarchy info by collecting all topic_ids from sessions
    and batch-querying teaching_guidelines.
    """
    # Collect unique guideline_ids from parsed state_json
    guideline_ids = set()
    for s in sessions:
        state = json.loads(s.state_json)
        topic = state.get("topic", {})
        topic_id = topic.get("topic_id")
        if topic_id:
            guideline_ids.add(topic_id)

    if not guideline_ids:
        return {}

    # Batch query teaching_guidelines
    guidelines = (
        self.db.query(
            TeachingGuideline.id,
            TeachingGuideline.topic,
            TeachingGuideline.subtopic,
            TeachingGuideline.topic_key,
            TeachingGuideline.subtopic_key,
        )
        .filter(TeachingGuideline.id.in_(guideline_ids))
        .all()
    )

    return {
        g.id: {
            "topic": g.topic,
            "subtopic": g.subtopic,
            "topic_key": g.topic_key or g.topic.lower().replace(" ", "-"),
            "subtopic_key": g.subtopic_key or g.subtopic.lower().replace(" ", "-"),
        }
        for g in guidelines
    }
```

#### `_group_sessions(sessions, guideline_lookup)`
```python
def _group_sessions(self, sessions, guideline_lookup) -> tuple[dict, dict]:
    """
    Group sessions into subject → topic → subtopic hierarchy.
    For each subtopic, keep only the LATEST session's data.
    Also collect trend data points.

    Returns:
        (grouped, trends_raw)
        grouped: {subject: {topic_key: {subtopic_key: {latest session data}}}}
        trends_raw: {subject: [(date, mastery), ...]}
    """
    # Structure: grouped[subject][topic_key] = {
    #   "topic_name": str,
    #   "subtopics": {subtopic_key: {latest_data}}
    # }
    grouped = defaultdict(lambda: defaultdict(lambda: {"topic_name": "", "subtopics": {}}))
    trends_raw = defaultdict(list)

    for session_row in sessions:
        state = json.loads(session_row.state_json)
        topic_data = state.get("topic", {})
        if not topic_data:
            continue

        subject = topic_data.get("subject", session_row.subject or "Unknown")
        topic_id = topic_data.get("topic_id")
        topic_name_raw = topic_data.get("topic_name", "")

        # Resolve hierarchy
        if topic_id and topic_id in guideline_lookup:
            gl = guideline_lookup[topic_id]
            topic_name = gl["topic"]
            subtopic_name = gl["subtopic"]
            topic_key = gl["topic_key"]
            subtopic_key = gl["subtopic_key"]
        elif " - " in topic_name_raw:
            # Fallback: split topic_name
            parts = topic_name_raw.split(" - ", 1)
            topic_name = parts[0].strip()
            subtopic_name = parts[1].strip()
            topic_key = topic_name.lower().replace(" ", "-")
            subtopic_key = subtopic_name.lower().replace(" ", "-")
        else:
            topic_name = topic_name_raw or "Unknown"
            subtopic_name = topic_name_raw or "Unknown"
            topic_key = topic_name.lower().replace(" ", "-")
            subtopic_key = subtopic_name.lower().replace(" ", "-")

        # Extract mastery data
        mastery_estimates = state.get("mastery_estimates", {})
        overall_mastery = session_row.mastery or 0.0
        if mastery_estimates and not overall_mastery:
            overall_mastery = sum(mastery_estimates.values()) / len(mastery_estimates)

        misconceptions = state.get("misconceptions", [])
        session_date = session_row.created_at.isoformat() if session_row.created_at else None

        # Group (latest session wins — sessions are ordered by created_at ASC)
        grouped[subject][topic_key]["topic_name"] = topic_name
        grouped[subject][topic_key]["subtopics"][subtopic_key] = {
            "subtopic_name": subtopic_name,
            "guideline_id": topic_id,
            "score": round(overall_mastery, 2),
            "concepts": {k: round(v, 2) for k, v in mastery_estimates.items()},
            "misconceptions": [
                {"description": m.get("description", ""), "resolved": m.get("resolved", False)}
                for m in misconceptions
            ],
            "latest_session_date": session_date,
            "session_count": grouped[subject][topic_key]["subtopics"]
                .get(subtopic_key, {}).get("session_count", 0) + 1,
        }

        # Trend data
        trends_raw[subject].append({
            "date": session_date,
            "score": round(overall_mastery, 2),
        })

    return grouped, trends_raw
```

#### `_compute_scores(grouped)`
```python
def _compute_scores(self, grouped) -> list:
    """
    Compute topic and subject averages from bottom up.

    Returns list of subject dicts with nested topics and subtopics.
    """
    subjects_data = []
    for subject, topics in sorted(grouped.items()):
        topics_data = []
        for topic_key, topic_info in sorted(topics.items()):
            subtopics_data = []
            for subtopic_key, sub_info in sorted(topic_info["subtopics"].items()):
                subtopics_data.append({
                    "subtopic": sub_info["subtopic_name"],
                    "subtopic_key": subtopic_key,
                    "guideline_id": sub_info.get("guideline_id"),
                    "score": sub_info["score"],
                    "session_count": sub_info["session_count"],
                    "latest_session_date": sub_info["latest_session_date"],
                    "concepts": sub_info["concepts"],
                    "misconceptions": sub_info["misconceptions"],
                })

            subtopic_scores = [s["score"] for s in subtopics_data if s["score"] > 0]
            topic_score = sum(subtopic_scores) / len(subtopic_scores) if subtopic_scores else 0.0

            topics_data.append({
                "topic": topic_info["topic_name"],
                "topic_key": topic_key,
                "score": round(topic_score, 2),
                "subtopics": subtopics_data,
            })

        topic_scores = [t["score"] for t in topics_data if t["score"] > 0]
        subject_score = sum(topic_scores) / len(topic_scores) if topic_scores else 0.0

        session_count = sum(
            s["session_count"]
            for t in topics_data
            for s in t["subtopics"]
        )

        subjects_data.append({
            "subject": subject,
            "score": round(subject_score, 2),
            "session_count": session_count,
            "topics": topics_data,
            "trend": [],  # Populated by _attach_trends
        })

    return subjects_data
```

#### `_attach_trends(subjects_data, trends_raw)`
```python
def _attach_trends(self, subjects_data, trends_raw):
    """Attach trend data (date, score) to each subject."""
    for subject_entry in subjects_data:
        subject_name = subject_entry["subject"]
        if subject_name in trends_raw:
            subject_entry["trend"] = trends_raw[subject_name]
```

#### Helper methods
```python
def _collect_all_subtopics(self, subjects_data) -> list:
    """Flatten all subtopics for strengths/needs-practice ranking."""
    result = []
    for subject in subjects_data:
        for topic in subject["topics"]:
            for subtopic in topic["subtopics"]:
                result.append({
                    "subtopic": subtopic["subtopic"],
                    "subject": subject["subject"],
                    "score": subtopic["score"],
                })
    return result

def _empty_scorecard(self) -> dict:
    """Return empty scorecard for users with no sessions."""
    return {
        "overall_score": 0,
        "total_sessions": 0,
        "total_topics_studied": 0,
        "subjects": [],
        "strengths": [],
        "needs_practice": [],
    }
```

### 3.2 New Endpoint in `llm-backend/tutor/api/sessions.py`

Add to the existing router (before the `/{session_id}` catch-all routes):

```python
from tutor.services.scorecard_service import ScorecardService

@router.get("/scorecard")
def get_scorecard(
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get student scorecard with aggregated performance data."""
    service = ScorecardService(db)
    return service.get_scorecard(current_user.id)
```

**Placement:** This MUST be placed above the `/{session_id}` route in the file, because FastAPI matches routes in order and `/scorecard` would otherwise be captured by `/{session_id}` as a path parameter. Looking at the existing code, the `/history` and `/stats` endpoints are already above `/{session_id}`, so we follow the same pattern.

### 3.3 User Subtopic Progress for Topic Selection (Section 14 of PRD)

Add to `sessions.py`:

```python
@router.get("/subtopic-progress")
def get_subtopic_progress(
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Get lightweight subtopic progress: {guideline_id → {score, session_count, status}}.
    Used by topic selection screen to show coverage indicators.
    """
    service = ScorecardService(db)
    return service.get_subtopic_progress(current_user.id)
```

In `ScorecardService`:

```python
def get_subtopic_progress(self, user_id: str) -> dict:
    """
    Returns {guideline_id: {score, session_count, status}} for the
    curriculum picker coverage indicators.
    """
    sessions = self._load_user_sessions(user_id)
    progress = {}  # guideline_id → latest data

    for session_row in sessions:
        state = json.loads(session_row.state_json)
        topic_data = state.get("topic", {})
        topic_id = topic_data.get("topic_id")
        if not topic_id:
            continue

        mastery = session_row.mastery or 0.0
        existing = progress.get(topic_id)
        count = (existing["session_count"] + 1) if existing else 1

        # Latest session wins (sessions are ordered ASC, so last write = latest)
        progress[topic_id] = {
            "score": round(mastery, 2),
            "session_count": count,
            "status": "mastered" if mastery >= 0.85 else "in_progress",
        }

    return {"user_progress": progress}
```

### 3.4 Pydantic Response Models (optional, for documentation)

Add to `shared/models/schemas.py`:

```python
class ScorecardMisconception(BaseModel):
    description: str
    resolved: bool

class ScorecardSubtopic(BaseModel):
    subtopic: str
    subtopic_key: str
    guideline_id: Optional[str] = None
    score: float
    session_count: int
    latest_session_date: Optional[str] = None
    concepts: Dict[str, float]
    misconceptions: List[ScorecardMisconception]

class ScorecardTopic(BaseModel):
    topic: str
    topic_key: str
    score: float
    subtopics: List[ScorecardSubtopic]

class ScorecardTrendPoint(BaseModel):
    date: str
    score: float

class ScorecardSubject(BaseModel):
    subject: str
    score: float
    session_count: int
    topics: List[ScorecardTopic]
    trend: List[ScorecardTrendPoint]

class ScorecardHighlight(BaseModel):
    subtopic: str
    subject: str
    score: float

class ScorecardResponse(BaseModel):
    overall_score: float
    total_sessions: int
    total_topics_studied: int
    subjects: List[ScorecardSubject]
    strengths: List[ScorecardHighlight]
    needs_practice: List[ScorecardHighlight]

class SubtopicProgressEntry(BaseModel):
    score: float
    session_count: int
    status: str  # "mastered" | "in_progress"

class SubtopicProgressResponse(BaseModel):
    user_progress: Dict[str, SubtopicProgressEntry]
```

---

## 4. Frontend Implementation

### 4.1 New Route: `/scorecard`

**File:** `llm-frontend/src/App.tsx`

Add alongside the existing `/history` route:

```tsx
import ScorecardPage from './pages/ScorecardPage';

// Inside <Routes>:
<Route path="/scorecard" element={
  <ProtectedRoute>
    <ScorecardPage />
  </ProtectedRoute>
} />
```

### 4.2 API Client Addition

**File:** `llm-frontend/src/api.ts`

```typescript
// --- Scorecard types ---

export interface ScorecardMisconception {
  description: string;
  resolved: boolean;
}

export interface ScorecardSubtopic {
  subtopic: string;
  subtopic_key: string;
  guideline_id: string | null;
  score: number;
  session_count: number;
  latest_session_date: string | null;
  concepts: Record<string, number>;
  misconceptions: ScorecardMisconception[];
}

export interface ScorecardTopic {
  topic: string;
  topic_key: string;
  score: number;
  subtopics: ScorecardSubtopic[];
}

export interface ScorecardTrendPoint {
  date: string;
  score: number;
}

export interface ScorecardSubject {
  subject: string;
  score: number;
  session_count: number;
  topics: ScorecardTopic[];
  trend: ScorecardTrendPoint[];
}

export interface ScorecardHighlight {
  subtopic: string;
  subject: string;
  score: number;
}

export interface ScorecardResponse {
  overall_score: number;
  total_sessions: number;
  total_topics_studied: number;
  subjects: ScorecardSubject[];
  strengths: ScorecardHighlight[];
  needs_practice: ScorecardHighlight[];
}

export interface SubtopicProgress {
  score: number;
  session_count: number;
  status: 'mastered' | 'in_progress';
}

export async function getScorecard(): Promise<ScorecardResponse> {
  const response = await apiFetch('/sessions/scorecard');
  if (!response.ok) throw new Error(`Failed to fetch scorecard: ${response.statusText}`);
  return response.json();
}

export async function getSubtopicProgress(): Promise<Record<string, SubtopicProgress>> {
  const response = await apiFetch('/sessions/subtopic-progress');
  if (!response.ok) throw new Error(`Failed to fetch progress: ${response.statusText}`);
  const data = await response.json();
  return data.user_progress;
}
```

### 4.3 ScorecardPage Component

**New file:** `llm-frontend/src/pages/ScorecardPage.tsx`

Structure (follows `SessionHistoryPage.tsx` pattern):

```tsx
export default function ScorecardPage() {
  const navigate = useNavigate();
  const { token } = useAuth();
  const [data, setData] = useState<ScorecardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSubject, setSelectedSubject] = useState<ScorecardSubject | null>(null);
  const [expandedSubtopics, setExpandedSubtopics] = useState<Set<string>>(new Set());

  useEffect(() => { fetchScorecard(); }, []);

  // View modes: "overview" | "subject-detail"
  // When selectedSubject is null → overview, otherwise → subject detail

  // Render sections:
  // 1. Overall score hero card
  // 2. Strengths list
  // 3. Needs practice list
  // 4. Subject cards (clickable → drill-down)
  // 5. Trend chart (overview: all subjects; detail: single subject)

  // Subject detail view:
  // - Back button to overview
  // - Subject trend chart
  // - Topic sections (accordion)
  //   - Subtopic rows (expandable → concept scores + misconceptions)
  //   - "Practice Again" button (navigates to TutorApp with guideline_id)
}
```

### 4.4 Component Breakdown

All components go in `llm-frontend/src/pages/ScorecardPage.tsx` as a single file (following the existing pattern where `SessionHistoryPage.tsx` is self-contained). If it gets too large, extract into a `components/scorecard/` directory.

**Sections within `ScorecardPage.tsx`:**

| Section | Purpose | Notes |
|---------|---------|-------|
| `OverallHero` | Big circular score + stats | CSS-only circular progress (no library needed) |
| `StrengthsList` | Top 5 subtopics by score | Green-themed cards |
| `NeedsPracticeList` | Bottom 5 subtopics | Orange/red-themed cards |
| `SubjectCards` | Grid of subject cards | Clickable, shows score + topic count |
| `TrendChart` | Line chart of mastery over time | Recharts `<LineChart>` with `<ResponsiveContainer>` |
| `SubjectDetailView` | Topic sections + subtopic drill-down | Replaces overview when a subject is selected |
| `TopicSection` | Expandable topic card | Shows subtopics with progress bars |
| `SubtopicDetail` | Concept scores + misconceptions | Expandable within topic section |
| `MasteryBar` | Colored progress bar | Reusable, color based on score |
| `MasteryBadge` | Label pill ("Mastered", etc.) | Reusable, color based on score |
| `EmptyState` | No sessions yet | CTA to start learning |

### 4.5 Mastery Label Helper

```typescript
function getMasteryLabel(score: number): { label: string; color: string } {
  if (score >= 0.85) return { label: 'Mastered', color: '#38a169' };
  if (score >= 0.65) return { label: 'Getting Strong', color: '#667eea' };
  if (score >= 0.45) return { label: 'Getting There', color: '#ff9800' };
  return { label: 'Needs Practice', color: '#e53e3e' };
}
```

### 4.6 "Practice Again" Navigation

When user taps "Practice Again" on a subtopic, navigate to the home page with pre-selected topic:

```typescript
// Option A: Navigate with state
navigate('/', {
  state: {
    autoStart: true,
    guideline_id: subtopic.guideline_id,
    subject: currentSubject,
  }
});
```

This requires TutorApp to check `location.state` on mount and auto-create a session if `autoStart` is set. This is a lightweight addition to TutorApp.

### 4.7 Topic Selection Coverage Indicators

**File:** `llm-frontend/src/TutorApp.tsx`

After subtopics are fetched, also fetch subtopic progress:

```typescript
// In the subtopic fetch effect:
const [subtopicProgress, setSubtopicProgress] = useState<Record<string, SubtopicProgress>>({});

// After fetching subtopics:
getSubtopicProgress().then(setSubtopicProgress).catch(() => {});

// In subtopic rendering, overlay status indicator:
{subtopicProgress[st.guideline_id] && (
  <span className={`subtopic-status ${subtopicProgress[st.guideline_id].status}`}>
    {subtopicProgress[st.guideline_id].status === 'mastered' ? '✓' : '●'}
    {(subtopicProgress[st.guideline_id].score * 100).toFixed(0)}%
  </span>
)}
```

### 4.8 Navigation Links

Add scorecard link to these locations:

1. **TutorApp header** (user menu): Add "My Scorecard" alongside existing "My Sessions" and "Profile"
2. **SessionHistoryPage**: Add link/button to scorecard
3. **Session completion screen** (in TutorApp, when `isComplete`): Add "View Scorecard" CTA

### 4.9 Recharts Integration

```bash
cd llm-frontend && npm install recharts
```

Trend chart component:

```tsx
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

function TrendChart({ subjects }: { subjects: ScorecardSubject[] }) {
  // For overview: merge all subjects' trends
  // For subject detail: single subject's trend
  // X-axis: dates, Y-axis: score (0-100%)
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" tickFormatter={formatDate} />
        <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
        <Tooltip formatter={(v: number) => `${v}%`} />
        {subjects.map((subject, i) => (
          <Line
            key={subject.subject}
            dataKey={subject.subject}
            stroke={SUBJECT_COLORS[i % SUBJECT_COLORS.length]}
            dot={false}
            strokeWidth={2}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
```

### 4.10 CSS Additions

Add to `llm-frontend/src/App.css` (following existing patterns):

```css
/* === Scorecard === */
.scorecard-page { ... }
.scorecard-hero { ... }              /* Overall score card */
.scorecard-hero-score { ... }        /* Big circular progress */
.scorecard-section-title { ... }     /* Section headers */
.scorecard-strengths { ... }         /* Strengths list */
.scorecard-needs-practice { ... }    /* Needs practice list */
.scorecard-subject-grid { ... }      /* Subject cards grid */
.scorecard-subject-card { ... }      /* Individual subject card */
.scorecard-topic-section { ... }     /* Topic accordion */
.scorecard-subtopic-row { ... }      /* Subtopic within topic */
.scorecard-subtopic-detail { ... }   /* Expanded subtopic detail */
.scorecard-concept-row { ... }       /* Concept score row */
.scorecard-misconception { ... }     /* Misconception item */
.scorecard-chart { ... }             /* Chart container */
.mastery-bar { ... }                 /* Reusable progress bar */
.mastery-bar-fill { ... }            /* Progress bar fill */
.mastery-badge { ... }               /* Label pill */
.mastery-badge.mastered { ... }
.mastery-badge.getting-strong { ... }
.mastery-badge.getting-there { ... }
.mastery-badge.needs-practice { ... }
.subtopic-status { ... }             /* Topic selection indicators */
.subtopic-status.mastered { ... }
.subtopic-status.in_progress { ... }
.practice-again-btn { ... }          /* Practice Again CTA */
```

---

## 5. Testing Strategy

### 5.1 Backend Unit Tests

**New file:** `llm-backend/tests/unit/test_scorecard_service.py`

Tests follow the `test_session_repository.py` pattern: class-based with `db_session` fixture.

```python
class TestScorecardEmpty:
    """Test scorecard for users with no sessions."""
    def test_empty_scorecard_returns_zeros(self, db_session): ...

class TestScorecardSingleSession:
    """Test scorecard with one session."""
    def test_single_session_creates_one_subject(self, db_session): ...
    def test_single_session_mastery_propagates(self, db_session): ...
    def test_single_session_concepts_extracted(self, db_session): ...
    def test_single_session_misconceptions_extracted(self, db_session): ...

class TestScorecardMultipleSessions:
    """Test scorecard aggregation across sessions."""
    def test_latest_session_per_subtopic_wins(self, db_session): ...
    def test_topic_score_averages_subtopics(self, db_session): ...
    def test_subject_score_averages_topics(self, db_session): ...
    def test_overall_score_averages_subjects(self, db_session): ...
    def test_multiple_subjects_grouped_correctly(self, db_session): ...
    def test_trend_data_includes_all_sessions(self, db_session): ...

class TestScorecardStrengthsAndWeaknesses:
    """Test strengths/needs-practice identification."""
    def test_strengths_sorted_by_score_desc(self, db_session): ...
    def test_needs_practice_below_065_threshold(self, db_session): ...
    def test_max_five_strengths(self, db_session): ...
    def test_max_five_needs_practice(self, db_session): ...

class TestScorecardGuidelineLookup:
    """Test topic hierarchy resolution."""
    def test_hierarchy_from_guideline_table(self, db_session): ...
    def test_fallback_to_topic_name_split(self, db_session): ...

class TestSubtopicProgress:
    """Test the lightweight subtopic progress endpoint."""
    def test_empty_user_returns_empty(self, db_session): ...
    def test_mastered_status_above_085(self, db_session): ...
    def test_in_progress_status_below_085(self, db_session): ...
    def test_session_count_increments(self, db_session): ...
    def test_latest_session_score_wins(self, db_session): ...
```

**Test helper for creating sessions with state_json:**

```python
def _create_session_with_state(db, user_id, subject, topic, subtopic,
                                guideline_id, mastery_estimates, mastery,
                                misconceptions=None, created_at=None):
    """Create a session row with realistic state_json for scorecard testing."""
    from tutor.models.session_state import SessionState
    from tutor.models.study_plan import Topic, TopicGuidelines, StudyPlan, StudyPlanStep
    # ... build realistic state_json and insert into sessions table
```

### 5.2 Backend API Test

**New file:** `llm-backend/tests/unit/test_scorecard_api.py`

Test the endpoint integration (mock the service, test auth, test routing).

### 5.3 Frontend Testing

Manual testing via dev server:
1. Empty state (no sessions)
2. Single session
3. Multiple subjects with multiple topics
4. Drill-down navigation
5. Chart rendering
6. "Practice Again" flow
7. Topic selection coverage indicators
8. Mobile responsiveness (Chrome DevTools)

---

## 6. File Change Summary

### New Files

| File | Purpose |
|------|---------|
| `llm-backend/tutor/services/scorecard_service.py` | Core aggregation logic |
| `llm-backend/tests/unit/test_scorecard_service.py` | Unit tests for scorecard service |
| `llm-backend/tests/unit/test_scorecard_api.py` | API endpoint tests |
| `llm-frontend/src/pages/ScorecardPage.tsx` | Scorecard page component |

### Modified Files

| File | Change |
|------|--------|
| `llm-backend/tutor/api/sessions.py` | Add `GET /scorecard` and `GET /subtopic-progress` endpoints |
| `llm-backend/shared/models/schemas.py` | Add `ScorecardResponse` and related Pydantic models |
| `llm-frontend/src/App.tsx` | Add `/scorecard` route |
| `llm-frontend/src/api.ts` | Add scorecard types and API functions |
| `llm-frontend/src/TutorApp.tsx` | Add subtopic progress indicators, scorecard nav link, Practice Again support |
| `llm-frontend/src/App.css` | Add scorecard CSS classes |
| `llm-frontend/src/pages/SessionHistoryPage.tsx` | Add link to scorecard |
| `llm-frontend/package.json` | Add `recharts` dependency |

### No Database Migration Needed

All data already exists in the `sessions` table (`state_json`, `mastery`, `subject`, `user_id`, `created_at`) and `teaching_guidelines` table. No schema changes required.

---

## 7. Implementation Phases

### Phase 1: Backend API (scorecard service + endpoints)
1. Create `scorecard_service.py` with `get_scorecard()` and `get_subtopic_progress()`
2. Add `GET /sessions/scorecard` endpoint to `sessions.py`
3. Add `GET /sessions/subtopic-progress` endpoint to `sessions.py`
4. Add Pydantic response models to `schemas.py`
5. Write unit tests for scorecard service
6. Write API tests for new endpoints

### Phase 2: Frontend — Scorecard Overview Page
7. Add scorecard types + API functions to `api.ts`
8. Create `ScorecardPage.tsx` with:
   - Overall score hero card
   - Strengths list
   - Needs practice list
   - Subject cards (clickable)
   - Empty state
9. Add `/scorecard` route to `App.tsx`
10. Add CSS classes to `App.css`

### Phase 3: Frontend — Drill-down + Charts
11. Install `recharts` (`npm install recharts`)
12. Implement subject detail view in `ScorecardPage.tsx`:
    - Topic sections with subtopic rows
    - Subtopic expansion with concept scores + misconceptions
    - Trend chart (overview + subject detail)
13. Implement "Practice Again" button (navigates to TutorApp with `guideline_id`)
14. Handle `location.state.autoStart` in `TutorApp.tsx`

### Phase 4: Topic Selection Indicators + Navigation
15. Add `getSubtopicProgress()` call to `TutorApp.tsx`
16. Overlay status indicators on subtopic selection cards
17. Add scorecard link to TutorApp header user menu
18. Add scorecard link to SessionHistoryPage
19. Add "View Scorecard" CTA to session completion screen

### Phase 5: Polish
20. Loading skeleton states
21. Error handling for API failures
22. Mobile responsiveness testing
23. Run unit tests, fix any failures

---

## 8. Risk & Edge Cases

### Edge Cases to Handle

| Case | Handling |
|------|----------|
| User has 0 sessions | Return empty scorecard with CTA |
| Session has no `topic` in state_json | Skip that session in aggregation |
| Session's guideline_id not found in teaching_guidelines | Fallback to topic_name split |
| `topic_name` doesn't contain ` - ` separator | Use full name as both topic and subtopic |
| `mastery_estimates` is empty | Use `sessions.mastery` column as fallback |
| User has sessions in only one subject | Show single subject, no multi-subject chart |
| Very old sessions with different state_json schema | Graceful JSON parsing with defaults |
| Sessions without `user_id` (anonymous) | Excluded by `WHERE user_id = ?` filter |

### Performance

- **O(n) state_json parsing:** For a student with 50 sessions, parsing 50 JSON blobs is < 100ms. Acceptable for V1.
- **Guideline lookup:** Batch query with `IN` clause, not N+1. Single round-trip.
- **Response size:** < 5KB for typical student. No conversation logs or full state included.
- **Frontend:** Single API call, no waterfall. Chart renders after data paint.

### Not Doing (V1 scope control)

- No server-side caching/materialized views (premature optimization)
- No time filtering ("last 30 days")
- No parent/teacher views
- No PDF export
- No real-time updates via WebSocket
