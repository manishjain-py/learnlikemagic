# Principles: Evaluation & Quality Measurement

How we measure tutor quality. The evaluation pipeline is read-only — we measure, never optimize the measurement itself.

## Core Dimensions (Interactive Teaching)

1. **Responsiveness** — Does tutor adapt to student signals? Picks up subtle cues (boredom, confusion, confidence) and adjusts immediately vs follows own script
2. **Explanation Quality** — Clear, varied explanations with concrete examples? Tries different approaches when one fails vs repeats similar explanation?
3. **Emotional Attunement** — Matches student emotional state? Celebrates breakthroughs, patient with struggle, doesn't over-praise easy wins
4. **Pacing** — Right speed for THIS student? Speeds up with quick learners, slows with strugglers, skips mastered content, lingers on hard content
5. **Authenticity** — Feels like real teacher or chatbot? Natural language, appropriate informality, varied structure vs template-like and predictable

## Card-Phase Dimensions (when pre-computed explanations precede session)

6. **Card-to-Session Coherence** — Interactive session references and builds on card analogies/examples? Feels like one continuous experience, not two separate lessons
7. **Transition Quality** — Smooth bridge from card reading to interactive teaching? Checks what student remembers, identifies gaps, launches from right point

## Persona-Aware Scoring

Same tutor behavior gets different scores for different students. Moving fast = brilliant for ace student, harmful for struggling student. Evaluation must account for who the student is.

## Problem-First Analysis

Beyond dimension scores, identify top problems with:
- Specific turn numbers
- Root cause category (missed_student_signal, wrong_pacing, repetitive_approach, emotional_mismatch, missed_misconception, over_scaffolding, card_content_ignored, abrupt_transition, etc.)
- Severity (critical / major / minor)

Problems are more actionable than scores. A score of 6 doesn't tell you what to fix. A problem at turn 7 with root cause "missed_misconception" does.
