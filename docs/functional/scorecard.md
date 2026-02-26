# Report Card

The report card is a student's progress overview. It shows what they have studied, how much of each subtopic they have covered, and their latest exam results.

---

## What the Report Card Shows

### Overview

- **Total sessions and topics studied** — Quick stats at the top
- **Subject cards** — One card per subject showing how many topics it contains; tap a card to see details

### Subject Detail

Tap any subject card to see a detailed breakdown:

- **Topics** — Each topic lists its subtopics
- **Subtopics** — Each subtopic shows:
  - A coverage percentage and progress bar showing how much of the study plan has been worked through
  - Latest exam score (if the student has taken an exam on this subtopic)
  - The date the student last studied this subtopic
  - A "Practice Again" button to start a new session

---

## Coverage

Coverage measures what fraction of a subtopic's study plan the student has worked through. It accumulates across multiple Teach Me sessions — if a student covers some concepts in one session and different concepts in the next, coverage reflects the total.

Only Teach Me sessions contribute to coverage. Clarify Doubts and Exam sessions do not change the coverage percentage.

The denominator (total concepts in the plan) comes from the most recent session's study plan, not a union of all sessions. This means if the plan is updated, coverage recalculates against the current plan.

---

## Exam Scores

When a student completes an exam on a subtopic, the report card shows the score from the most recent exam (for example, "7/10"). Only completed exams are counted — if a student starts an exam but does not finish, it does not appear.

If a student takes multiple exams on the same subtopic, only the latest result is displayed.

---

## Practice Again

From any subtopic in the report card, students can tap "Practice Again" to start a new Teach Me session on that subtopic. This creates a new session and takes the student directly into the learning experience.

The button is only available for subtopics that are linked to a teaching guideline.

---

## Empty State

When a student has no completed sessions, the report card shows an encouraging message and a "Start Learning" button that takes them to the topic selection screen.

---

## Key Details

- The report card updates automatically after each completed session
- Coverage only counts Teach Me sessions; exams and Clarify Doubts sessions do not contribute
- The report card is accessible from the user menu ("My Scorecard") and from the session history page
- Both the `/scorecard` and `/report-card` URLs show the same report card page
