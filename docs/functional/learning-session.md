# Learning Session

A learning session is a one-on-one experience between a student and the AI tutor on a specific subtopic. The platform offers two session modes: **Teach Me** (lesson) and **Clarify Doubts** (student-led Q&A). A separate batch-drill mode called **Let's Practice** provides low-stakes self-assessment — see `docs/functional/practice-mode.md`.

---

## Starting a Session

1. **Pick a subject** — e.g., Mathematics, English.
2. **Pick a chapter, then a topic** — within the subject.
3. **Pick a subtopic** — subtopics show progress badges if you've studied them before (check mark for mastered, dot for in progress, plus a coverage percentage). Some subtopics are flagged as **warm-up / refresher** topics — these are restricted to Teach Me and use the card-based explanation only (no follow-up interactive lesson, no Clarify Doubts, no Let's Practice).
4. **Pick a mode**:
   - **Teach Me** — lesson on the topic.
   - **Clarify Doubts** — ask questions and get direct answers.
   - **Let's Practice** — 10-question batch drill (see `docs/functional/practice-mode.md`).
5. **Pick a Teach Me submode** (after Teach Me) — two cards:
   - **Baatcheet (recommended)** — listen in on a friendly chat between Mr. Verma (tutor) and Meera (peer) explaining the topic. Available only when a Baatcheet dialogue has been pre-built for that subtopic.
   - **Explain** — read structured explanation cards at your own pace.
   Each card shows availability and a "Continue" CTA with progress when you have an in-progress session for that submode.
6. **Resume (if available)** — if you have an in-progress Teach Me session for that subtopic, the submode card shows "Continue — N / M". Tap to pick up where you left off.

You can also start a session from the report card by tapping "Practice Again" on any subtopic.

The lesson is personalized to your learning profile (interests, attention span, preferred examples) when a personality profile and enrichment data are on file.

---

## Learning Modes

### Teach Me — Baatcheet (Conversational)

A pre-scripted dialogue between Mr. Verma (tutor) and Meera (a student peer who asks the questions you'd ask). You watch + listen. Each card is one beat of the conversation.

- Cards include tutor turns, peer turns, visuals, embedded check-ins, and a final summary.
- Each line plays per-line audio synced with a typewriter reveal — the tutor's voice and Meera's voice are different.
- You navigate forward / back at your own pace; the current card position is saved automatically.
- A short check-in activity may appear mid-deck (match pairs, pick one, fill blank, etc.) — answer it before continuing.
- The session completes when you reach the summary card. You then see a completion screen with a "Let's Practice" CTA.

Baatcheet doesn't have an "I didn't understand" simplify button — the dialogue itself is the explanation.

### Teach Me — Explain (Card-Based)

You read a deck of pre-prepared explanation cards. Each card covers one idea (concept, example, visual, analogy, or summary).

- You read at your own pace — typewriter reveals each line.
- A card may include a visual illustration (rendered live) and/or an interactive check-in activity.
- If a card is unclear, tap **"I didn't understand"** to get a simplified version of that specific card. The tutor breaks the idea into smaller pieces using simpler words. You can tap again on the same card for a deeper simplification.
- When you finish the deck, you choose:
  - **"I understand"** — the session ends. You see a coverage summary + a prominent "Let's Practice" CTA.
  - **"Explain differently"** — the tutor switches to a different variant (different analogy or angle) for the same topic. If all variants have been shown, the session ends with a gentle nudge to practice.

Refresher topics use the same card flow but always end as soon as you finish the cards — there's no "Explain differently" branch and no per-card simplify button.

### Clarify Doubts

A student-led Q&A. You ask questions, the tutor answers them directly. No structured plan — you drive.

- The tutor answers directly without Socratic scaffolding.
- After answering, the tutor asks if your doubt is cleared. It does not start teaching new material or quizzing.
- The concepts you discuss are tracked and shown as tags in the session header.
- End the session via the "End Session" button or by saying "I'm done", "no more doubts", "that's all" — the tutor wraps up warmly.
- Past discussions for the same subtopic (up to 5 most recent) are shown so you can see what you've already asked about.

### Let's Practice

A 10-question batch drill. Full details in `docs/functional/practice-mode.md`.

---

## How the Tutor Teaches

Teach Me mode (Baatcheet and Explain alike) is built on these principles. They guide the dialogue script for Baatcheet and the per-card simplification for Explain.

### Teaching Philosophy

0. **Radical simplicity** — every sentence under 15 words, one idea per sentence, only words a child uses daily, no idioms or phrasal verbs. Indian everyday context is the baseline (rupees, cricket, chapati, lakh/crore). Self-check before every line: could a 5-year-old follow?

1. **Cards do the teaching** — the deck (Baatcheet dialogue or Explain cards) is the lesson. The tutor never re-explains over chat after cards. Re-explanation only happens via per-card simplification or by switching to a different Explain variant.

2. **Calibrated to the student** — when a personality profile and attention span are on file, the dialogue script + card framing adapt to who you are.

3. **Indian ESL voice** — written for students who think in Hindi and read English second. No idioms, no phrasal verbs, no academic vocabulary. The audio version is in your chosen language (English, Hindi, or Hinglish).

### Pausing and Resuming

A Teach Me session is auto-saved on every navigation step. There's no explicit "Pause" button — closing the page or navigating away just leaves the session in progress. Returning to the same subtopic shows a "Continue" CTA on the submode card with progress.

### Coverage Tracking

When you complete the cards, every concept covered by the cards is added to your subtopic coverage. This is the percentage shown next to subtopics on the topic picker and report card.

---

## Ending a Session

### Teach Me

A Teach Me session ends when:
- You reach the summary card (Baatcheet) or tap "I understand" on the final card (Explain).
- You exhaust all Explain variants by repeatedly choosing "Explain differently".

After the session, the completion screen shows:
- A short congratulations message.
- The list of concepts covered.
- A prominent **"Let's Practice"** CTA that starts a Practice session on the same subtopic.

### Clarify Doubts

A Clarify Doubts session ends when:
- You tap "End Session".
- You tell the tutor you're done.

After the session, you see the list of concepts you discussed.

### After Any Session

You can start a new session, jump to Practice, or view your report card. Returning to a completed session URL replays the full conversation / card deck.

---

## Mid-Session Feedback

During a Clarify Doubts session, you (or a parent) can submit feedback to adjust how the tutor is explaining things. The tutor regenerates its approach based on the feedback. Feedback is limited to 3 submissions per session.

For Teach Me, the cards are pre-built — you change the experience by tapping "I didn't understand" (Explain) or "Explain differently" (Explain).

---

## Voice Input and Audio

In Clarify Doubts, you can speak your question into the microphone instead of typing. Your speech is transcribed to text, which you can edit before sending.

In Teach Me, every card / dialogue line plays its own pre-recorded audio when revealed — Mr. Verma and Meera have distinct voices in Baatcheet, and the Explain cards play a single tutor voice. The audio language matches your language preference.

You can write or speak in Hindi or Hinglish (Hindi-English mix) — the tutor understands and translates it automatically.

---

## Language Support

The tutor supports three language modes for both text and audio, configured in your profile:

- **English** — all responses in English.
- **Hindi** — Devanagari script for text, Roman transliteration for audio.
- **Hinglish** — natural Hindi-English mix common in Indian schools.

Text and audio language can be set independently — for example, read in English but listen in Hinglish.

---

## Visual Illustrations

Many cards include a built-in visual — a small interactive diagram or animation rendered live. Tap "See it" on a card to expand the visual; it plays alongside the card's narration. Visuals are pre-built into Baatcheet and Explain cards during ingestion (not generated mid-session).

In Clarify Doubts, the tutor may generate a fresh visual on the fly when a picture would help the answer. Visuals are skipped on test questions where they would reveal the answer.

---

## Interactive Check-Ins

Cards can embed short interactive activities. The card pauses until you complete the activity:

- **Pick one** — single-select from 3-4 options.
- **True/false** — judge a statement.
- **Fill in the blank** — type a short answer.
- **Match pairs** — connect related items.
- **Sort buckets / swipe classify** — drop items into categories.
- **Sequence** — order items in the correct sequence.
- **Spot the error** — find the wrong step.
- **Odd one out** — pick the item that doesn't fit.
- **Predict then reveal** — guess, then see the answer.
- **Tap to eliminate** — remove items until only the correct one(s) remain.

Wrong attempts and confused pairs are tracked silently. After enough wrong tries, the activity auto-reveals so you can keep moving.

---

## Key Details

- Sessions are saved automatically — review past sessions in your history.
- Each session focuses on one subtopic for depth over breadth.
- The tutor formats responses for readability: bold key terms, bullet points, short paragraphs, blank lines between ideas.
- The tutor uses colored emoji (🔴🟠🟡🟢🔵) to illustrate color-based examples (sorting, grouping, mixing).
- Refresher / warm-up topics deliver pre-computed cards as a quick review and end as soon as you finish — no follow-up.
