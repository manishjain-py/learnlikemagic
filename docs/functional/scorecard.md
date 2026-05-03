# Report Card

The report card is a student's progress overview. It shows what they have studied, how much of each topic they have covered, and their latest practice scores.

---

## What the Report Card Shows

### Overview

- **Total sessions and chapters studied** — Quick stats at the top
- **Subject cards** — One card per subject showing how many chapters it contains; tap a card to see details

### Subject Detail

Tap any subject card to see a detailed breakdown:

- **Chapters** — Each chapter lists its topics
- **Topics** — Each topic shows:
  - A coverage percentage and progress bar showing how much of the study plan has been worked through
  - Latest practice score (if the student has submitted at least one graded practice attempt on this topic)
  - The date the student last studied this topic
  - A "Practice Again" button to start a new session

"Get Ready" refresher topics (prerequisite warm-ups attached to a chapter) are hidden from the report card listing — only the actual chapter topics appear.

---

## Coverage

Coverage measures what fraction of a topic's study plan the student has worked through. It accumulates across multiple Teach Me sessions — if a student covers some concepts in one session and different concepts in the next, coverage reflects the total.

Only Teach Me sessions contribute to coverage. Clarify Doubts sessions and practice attempts do not change the coverage percentage.

The denominator (total concepts in the plan) comes from the most recent session's study plan, not a union of all sessions. This means if the plan is updated, coverage recalculates against the current plan.

---

## Progress Badges

When browsing chapters and topics to start a new session, each chapter and topic shows a progress badge based on the student's past Teach Me sessions. Three statuses:

- **Completed** (checkmark) — topic coverage ≥ 80%; for chapters, average coverage across all topics ≥ 80%
- **In Progress** (highlighted) — coverage > 0% but below 80%
- **Not Started** (default) — no Teach Me sessions yet

Topics also show a coverage percentage ("42% covered") when progress exists.

---

## Practice Scores

When a student completes a practice attempt on a topic, the report card shows the latest attempt's score alongside the attempt count — for example, **7.5 / 10 · 3 attempts**.

- Only **graded** attempts count. In-progress attempts and attempts that failed grading do not appear.
- If a student has multiple graded attempts on the same topic, the latest is displayed.
- Scores are fractional with half-point granularity (e.g., `8` displays as `8`, `7.5` displays as `7.5`).
- A topic with practice attempts but no Teach Me sessions still appears in the report card data — the practice chip creates the row — provided the student has at least one session of any kind (otherwise the empty state takes over).

---

## Practice Again

From any topic in the report card, students can tap "Practice Again" to start a new Teach Me session on that topic. This creates a new session and takes the student directly into the learning experience.

The button is only available for topics that are linked to a teaching guideline.

---

## Resuming Sessions

On the mode selection screen, if the student has an incomplete Teach Me lesson with coverage above 0%, the app shows a **Continue Lesson** option with the coverage so far and lets them pick up where they left off. A "Start Fresh" button is also available to begin a new lesson instead.

For "Get Ready" refresher topics, only the Teach Me option is shown — Clarify Doubts and Let's Practice are not offered.

---

## Empty State

When a student has zero learning sessions, the report card shows an encouraging message and a "Start Learning" button that takes them to the topic selection screen. (The empty-state check is based on session count, so a student with only graded practice attempts and no Teach Me / Clarify Doubts sessions also sees the empty state.)

---

## Key Details

- The report card updates automatically after each completed Teach Me session and each graded practice attempt.
- Coverage only counts Teach Me sessions; Clarify Doubts sessions and practice attempts do not contribute to coverage.
- Practice scores display the latest attempt, not a rolling average — students see where they are now, not a smoothed trend.
- The report card is accessible from the user menu ("My Report Card") and the session history page.
