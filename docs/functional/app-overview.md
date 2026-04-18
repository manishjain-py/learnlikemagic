# App Overview

LearnLikeMagic is an AI-powered adaptive tutoring platform for K-12 students. It provides personalized, one-on-one teaching through an AI tutor that adapts to each student's pace, style, and understanding.

---

## Purpose

Every student learns differently. LearnLikeMagic gives each student a personal tutor that explains concepts in ways they understand, asks the right questions, and adapts in real-time — just like a great human tutor would.

## Target Users

- **Students** (K-12, primarily grades 1-12) — The primary users. Everything is designed for them.
- **Parents** — Fill out an enrichment profile about their child to help personalize tutoring.
- **Admins** — Upload curriculum content, review teaching guidelines, run quality evaluations, configure AI models, and monitor tutor performance.

---

## Core Features

| Feature | What It Does |
|---------|-------------|
| **Learning Sessions** | Interactive tutoring conversations on any topic in the curriculum |
| **Learning Modes** | Three ways to learn: Teach Me (structured lesson), Clarify Doubts (Q&A), and Let's Practice (batch drill) |
| **Voice Input** | Students can speak their answers instead of typing |
| **Voice Output** | The tutor can read responses aloud (text-to-speech) in English, Hindi, or Hinglish |
| **Practice Results** | After a practice set, students see fractional scores and per-question rationale explaining why each pick was right or wrong |
| **Session Pause & Resume** | Pause a teaching session and pick up where you left off later |
| **Session History** | View past learning sessions with mastery scores and learning stats |
| **Report Card** | Progress report showing coverage percentage and latest practice scores per subject, chapter, and topic |
| **Enrichment Profile** | Parents describe their child's interests, learning style, strengths, challenges, and preferences to personalize tutoring |
| **Profile** | View and edit personal details like name, grade, board, and school |
| **Book & Guidelines** | Admin tool to upload textbooks, extract table of contents, process chapters, and sync topics to the curriculum |
| **Evaluation** | Admin tool to test tutor quality using simulated students |
| **LLM Configuration** | Admin tool to choose which AI model powers each part of the system |
| **Feature Flags** | Admin tool to toggle runtime features on or off (e.g., visuals in tutor flow). Changes take effect immediately for new sessions |
| **Pre-Computed Explanations** | During book ingestion, the system pre-generates multiple explanation variants for each topic (e.g., everyday analogies, visual/hands-on, story-based). During a Teach Me session, the tutor can present these as step-by-step explanation cards. If the student wants a different approach, they can request an alternative variant |
| **Interactive Questions** | During teaching and practice drills, questions are rendered in rich interactive formats — fill-in-the-blank, multiple choice, true/false, matching, sort-into-buckets, and sequencing — instead of plain text. Students tap or type answers directly in the structured format |
| **Check-In Activities** | Mid-explanation comprehension checks rendered as quick interactive activities (match-the-pairs, pick-one, true/false, fill-in-blank, sort-into-buckets, sequence) to verify understanding before moving on |
| **Get Ready Refresher** | A prerequisite "warm-up" topic appears at the top of each chapter. It revisits foundational knowledge needed before diving into the chapter's main topics |
| **Report Issue** | Students can report problems via text, voice recording, or screenshot attachments. Reports are tracked by status (open, in progress, closed) |
| **Visual Explanations (PoC)** | Admin tool to generate interactive diagrams and animations from text prompts using AI + Pixi.js |
| **Interactive Visuals (PoC)** | Admin tool to test interactive visual templates (drag-and-drop, sliders) with editable JSON parameters |
| **Issue Management** | Admin tool to view, triage, and update status of user-reported issues with screenshot viewing |
| **Test Scenarios** | Admin tool to view end-to-end test results and screenshots |
| **Docs Viewer** | Admin tool to browse project documentation inside the app |
| **Topics Admin** | Per-chapter admin tool to view, edit, delete, and reprocess extracted topics from a book chapter |
| **Guidelines Admin** | Per-chapter admin tool to view, edit, approve, reject, and sync teaching guidelines |
| **Explanations Admin** | Per-chapter admin tool to generate, view, and delete pre-computed explanation card variants per topic |
| **Visuals Admin** | Per-chapter admin tool to generate Pixi.js visuals for explanation cards and track visual coverage |
| **OCR Admin** | Per-chapter admin tool to view, retry, and bulk re-run OCR on chapter pages |

---

## Learning Modes

After choosing a subtopic, students pick how they want to learn:

| Mode | What It Does |
|------|-------------|
| **Teach Me** | The tutor teaches the topic step-by-step from scratch. Tracks progress and coverage. Can be paused and resumed later. |
| **Clarify Doubts** | The student asks their own questions about the topic. The tutor answers and tracks which concepts were discussed. |
| **Let's Practice** | A 10-question batch drill with no hints or tutor-in-the-loop. Students submit once and see per-question results with a rationale. Available on topics that have a question bank ready. See `docs/functional/practice-mode.md`. |

If a student previously paused a Teach Me session on the same subtopic, a **Resume** option appears showing how much was already covered. Let's Practice sessions auto-save progress mid-drill and can be resumed from the practice landing screen.

---

## User Journey

### Students

1. **Sign up** — Using phone, email, or Google
2. **Onboard** — Share your name, age, grade, and board
3. **Pick a subject** — Choose a subject from the curriculum
4. **Pick a chapter** — Choose a chapter within that subject
5. **Pick a topic** — Choose a specific topic to study
6. **Choose a mode** — Teach Me, Clarify Doubts, or Let's Practice (or resume a paused session)
7. **Learn** — Interact with the tutor through text or voice; listen to responses read aloud; pause to come back later or end early to see results
8. **Review practice results** — After a practice set, see a question-by-question breakdown with your answer, the correct answer, and a rationale for wrong picks
9. **Check report card** — View coverage and latest practice scores across subjects, chapters, and topics
10. **View session history** — Browse past sessions with mastery scores and learning stats
11. **Manage profile** — Update your name, grade, board, school, and other details
12. **Report an issue** — Describe a problem via text, voice, or screenshots; the team tracks it
13. **Practice again** — Jump back into topics that need more work

### Parents

1. **Open enrichment profile** — Navigate to the enrichment page from the student's profile
2. **Describe your child** — Fill in interests, hobbies, learning style, strengths, challenges, and session preferences
3. **View personality summary** — The system generates a personality snapshot based on the enrichment data to personalize tutoring

### Admins

1. **Upload books** — Add textbook pages to the system
2. **Extract table of contents** — AI identifies chapters from book pages
3. **Process chapters** — AI extracts topics, guidelines, and study plans from chapter pages
4. **Sync to curriculum** — Push processed topics into the live curriculum
5. **Run evaluations** — Test the tutor with simulated students and review quality scores
6. **Configure AI models** — Choose which AI provider and model powers each component
7. **Manage feature flags** — Toggle runtime features on or off from the admin dashboard
8. **Edit topics, guidelines, explanations, visuals, OCR** — Per-chapter admin tools to inspect and refine each artifact produced by the ingestion pipeline
9. **Generate visual explanations** — Create interactive diagrams and animations from text descriptions (proof of concept)
10. **Test interactive visuals** — Try drag-and-drop and other interactive templates with editable parameters (proof of concept)
11. **Manage reported issues** — View user-reported issues, update status (open / in progress / closed), view attached screenshots
12. **View test scenarios** — Review end-to-end test results and screenshots for each feature
13. **Browse documentation** — View project docs directly in the admin interface

---

## UX Philosophy

The app is designed for kids. Every screen, every interaction is built to be effortless:

- **One thing per screen** — Each screen has one clear purpose with big, clear buttons
- **Minimal typing** — Pickers and selectors over free-text wherever possible; voice input available
- **Friendly language** — No jargon. "What's your name?" not "Enter display name"
- **Mobile-first** — Designed for phone screens first with large tap targets
- **Warm and encouraging** — "You're all set! Let's start learning" not "Account created successfully"
- **Forgiving** — Messy input is handled gracefully. Errors are kind, not scary
- **Fast** — Nothing should feel slow. If it takes time, show progress
- **Skippable** — Optional steps have a clear "Skip for now" button
