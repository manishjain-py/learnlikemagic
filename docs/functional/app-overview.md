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
| **Learning Modes** | Three ways to learn: Teach Me, Clarify Doubts, and Exam |
| **Voice Input** | Students can speak their answers instead of typing |
| **Voice Output** | The tutor can read responses aloud (text-to-speech) in English, Hindi, or Hinglish |
| **Exam Review** | After finishing an exam, students see a detailed breakdown of each question with correct answers and explanations |
| **Session Pause & Resume** | Pause a teaching session and pick up where you left off later |
| **Session History** | View past learning sessions with mastery scores and learning stats |
| **Report Card** | Progress report showing coverage percentage and exam scores per subject, chapter, and topic |
| **Enrichment Profile** | Parents describe their child's interests, learning style, strengths, challenges, and preferences to personalize tutoring |
| **Profile** | View and edit personal details like name, grade, board, and school |
| **Book & Guidelines** | Admin tool to upload textbooks, extract table of contents, process chapters, and sync topics to the curriculum |
| **Evaluation** | Admin tool to test tutor quality using simulated students |
| **LLM Configuration** | Admin tool to choose which AI model powers each part of the system |
| **Visual Explanations (PoC)** | Admin tool to generate interactive diagrams and animations from text prompts using AI + Pixi.js |
| **Test Scenarios** | Admin tool to view end-to-end test results and screenshots |
| **Docs Viewer** | Admin tool to browse project documentation inside the app |

---

## Learning Modes

After choosing a subtopic, students pick how they want to learn:

| Mode | What It Does |
|------|-------------|
| **Teach Me** | The tutor teaches the topic step-by-step from scratch. Tracks progress and coverage. Can be paused and resumed later. |
| **Clarify Doubts** | The student asks their own questions about the topic. The tutor answers and tracks which concepts were discussed. |
| **Exam** | The tutor quizzes the student with questions and tracks correct answers. Can be ended early to see results. After finishing, shows a detailed exam review. |

If a student previously paused a Teach Me session on the same subtopic, a **Resume** option appears showing how much was already covered.

---

## User Journey

### Students

1. **Sign up** — Using phone, email, or Google
2. **Onboard** — Share your name, age, grade, and board
3. **Pick a subject** — Choose a subject from the curriculum
4. **Pick a chapter** — Choose a chapter within that subject
5. **Pick a topic** — Choose a specific topic to study
6. **Choose a mode** — Teach Me, Clarify Doubts, or Exam (or resume a paused session)
7. **Learn** — Interact with the tutor through text or voice; listen to responses read aloud; pause to come back later or end early to see results
8. **Review exam results** — After an exam, see a question-by-question breakdown with answers and explanations
9. **Check report card** — View coverage and exam scores across subjects, chapters, and topics
10. **View session history** — Browse past sessions with mastery scores and learning stats
11. **Manage profile** — Update your name, grade, board, school, and other details
12. **Practice again** — Jump back into topics that need more work

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
7. **Generate visual explanations** — Create interactive diagrams and animations from text descriptions (proof of concept)
8. **View test scenarios** — Review end-to-end test results and screenshots for each feature
9. **Browse documentation** — View project docs directly in the admin interface

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
