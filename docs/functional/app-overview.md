# App Overview

LearnLikeMagic is an AI-powered adaptive tutoring platform for K-12 students. It provides personalized, one-on-one teaching through an AI tutor that adapts to each student's pace, style, and understanding.

---

## Purpose

Every student learns differently. LearnLikeMagic gives each student a personal tutor that explains concepts in ways they understand, asks the right questions, and adapts in real-time — just like a great human tutor would.

## Target Users

- **Students** (K-12, primarily grades 1-12) — The primary users. Everything is designed for them.
- **Admins** — Upload curriculum content, review teaching guidelines, run quality evaluations, configure AI models, and monitor tutor performance.

---

## Core Features

| Feature | What It Does |
|---------|-------------|
| **Learning Sessions** | Interactive tutoring conversations on any topic in the curriculum |
| **Learning Modes** | Three ways to learn: Teach Me, Clarify Doubts, and Exam |
| **Voice Input** | Students can speak their answers instead of typing |
| **Session Pause & Resume** | Pause a teaching session and pick up where you left off later |
| **Session History** | View past learning sessions with mastery scores and learning stats |
| **Scorecard** | Progress report showing mastery across subjects, topics, and subtopics |
| **Profile** | View and edit personal details like name, grade, board, and school |
| **Book & Guidelines** | Admin tool to upload textbooks and extract teaching guidelines |
| **Evaluation** | Admin tool to test tutor quality using simulated students |
| **LLM Configuration** | Admin tool to choose which AI model powers each part of the system |
| **Test Scenarios** | Admin tool to view end-to-end test results and screenshots |
| **Docs Viewer** | Admin tool to browse project documentation inside the app |

---

## Learning Modes

After choosing a subtopic, students pick how they want to learn:

| Mode | What It Does |
|------|-------------|
| **Teach Me** | The tutor teaches the topic step-by-step from scratch. Tracks progress and coverage. Can be paused and resumed later. |
| **Clarify Doubts** | The student asks their own questions about the topic. The tutor answers and tracks which concepts were discussed. |
| **Exam** | The tutor quizzes the student with questions and tracks correct answers. Can be ended early to see results. |

If a student previously paused a Teach Me session on the same subtopic, a **Resume** option appears showing how much was already covered.

---

## User Journey

### Students

1. **Sign up** — Using phone, email, or Google
2. **Onboard** — Share your name, age, grade, and board
3. **Pick a subject** — Choose a subject from the curriculum
4. **Pick a topic** — Choose a topic within that subject
5. **Pick a subtopic** — Choose a specific subtopic to study
6. **Choose a mode** — Teach Me, Clarify Doubts, or Exam (or resume a paused session)
7. **Learn** — Interact with the tutor through text or voice; pause to come back later or end early to see results
8. **Review progress** — Check your scorecard to see strengths and areas to practice
9. **View session history** — Browse past sessions with mastery scores and learning stats
10. **Manage profile** — Update your name, grade, board, school, and other details
11. **Practice again** — Jump back into topics that need more work

### Admins

1. **Upload books** — Add textbook pages to the system
2. **Generate guidelines** — AI extracts teaching guidelines from book pages
3. **Review & approve** — Check guidelines for accuracy and approve them
4. **Generate study plans** — AI creates step-by-step teaching plans from guidelines
5. **Run evaluations** — Test the tutor with simulated students and review quality scores
6. **Configure AI models** — Choose which AI provider and model powers each component
7. **View test scenarios** — Review end-to-end test results and screenshots for each feature
8. **Browse documentation** — View project docs directly in the admin interface

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
