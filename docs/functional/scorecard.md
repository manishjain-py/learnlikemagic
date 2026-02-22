# Scorecard

The scorecard is a student's progress report. It shows how well they're doing across all subjects, topics, and subtopics they've studied.

---

## What the Scorecard Shows

### Overview

- **Overall mastery score** — A single percentage showing overall progress, displayed as a circular progress ring
- **Total sessions and topics studied** — Quick stats at the top
- **Strengths** — Up to 5 subtopics where the student is doing well (score 65% or above)
- **Needs Practice** — Up to 5 subtopics that need more work (score below 65%)
- **Subject cards** — One card per subject showing the subject score, a progress bar, and topic/session counts
- **Trend chart** — A line chart showing mastery over time across subjects (appears when there are 2+ data points)

### Subject Detail

Tap any subject card to see a detailed breakdown:

- **Subject trend** — Mastery over time for this subject
- **Topics** — Each topic shows its score and a list of subtopics
- **Subtopics** — Each subtopic is expandable and shows:
  - Mastery score with a color-coded badge
  - Individual concept scores
  - Misconceptions (marked as resolved or still active)
  - Number of sessions and last session date
  - A "Practice Again" button
- **Misconceptions summary** — All misconceptions from every subtopic in the subject, collected in one list at the bottom, each showing which topic it came from and whether it has been resolved

---

## How Scores Are Calculated

Scores flow from the bottom up:

1. **Concept scores** come from the tutor's mastery tracking during sessions
2. **Subtopic score** = the mastery from the student's most recent session on that subtopic
3. **Topic score** = average of all subtopic scores within that topic
4. **Subject score** = average of all topic scores within that subject
5. **Overall score** = average of all subject scores

Only the latest session per subtopic counts — earlier sessions are replaced as the student progresses.

---

## Mastery Labels

| Score | Label | Color |
|-------|-------|-------|
| 85%+ | Mastered | Green |
| 65-84% | Getting Strong | Purple |
| 45-64% | Getting There | Orange |
| Below 45% | Needs Practice | Red |

---

## Strengths & Needs Practice

The scorecard highlights the student's top-5 strengths and top-5 areas needing practice:

- **Strengths** are subtopics with scores of 65% or above, sorted highest first
- **Needs Practice** are subtopics with scores below 65%, sorted lowest first

Each entry shows the subtopic name, subject, and score.

---

## Trends Over Time

The trend chart shows how mastery changes across sessions. Each data point represents a session, plotted by date and mastery score. Multiple subjects are shown as separate lines with a color-coded legend.

Trends only appear when there are at least 2 data points to plot.

When sessions span more than one calendar year, dates include the year. Otherwise, only the month and day are shown.

---

## Practice Again

From any subtopic in the scorecard, students can tap "Practice Again" to start a new tutoring session on that subtopic. This creates a new session and jumps directly into the chat — skipping the subject/topic/subtopic selection flow.

---

## Coverage & Revision Nudges

The system tracks which concepts the student has covered across all sessions on a subtopic. This coverage percentage reflects how much of the subtopic's study plan the student has worked through, even across multiple sessions.

Based on coverage and how long it has been since the student last studied a subtopic, the system may suggest revisiting it:

- After 30+ days: a nudge to take an exam and check retention
- After 14+ days: a gentle reminder to consider revising
- After 7+ days (if coverage is 60%+): a suggestion that a quick exam can help

These nudges help students revisit material before it fades from memory.

---

## Session Type Tracking

Each subtopic tracks how many sessions the student has done in each learning mode:

- **Teach Me sessions** — guided tutoring sessions
- **Clarify Doubts sessions** — sessions where the student asked questions
- **Exam sessions** — completed practice exams

This gives a picture of how the student has been engaging with each subtopic.

---

## Exam History

When a student completes exams on a subtopic, each attempt is recorded with the score and date. The scorecard tracks:

- How many exams were taken on each subtopic
- The score and total for each attempt
- Feedback from the most recent exam (strengths, weak areas, patterns, and next steps)

---

## Key Details

- The scorecard updates automatically after each completed session
- Subtopics with zero scores (attempted but no mastery gained) are included in averages
- An empty state is shown with a "Start Learning" prompt when no sessions have been completed yet
- Misconceptions from all sessions are aggregated and displayed at the subtopic level
- The scorecard is also available as a "report card" view that includes the same data with additional coverage and exam details
