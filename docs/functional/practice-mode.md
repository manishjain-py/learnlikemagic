# Let's Practice

Let's Practice is a low-stakes, repeatable batch-drill mode. Students answer 10 questions on a topic without hints or scaffolding, submit once, and come back to a per-question review with fractional scoring. Replaces the old Exam mode entirely.

---

## Starting Practice

Practice is offered on all non-refresher topics. On the topic's mode selection screen, students see a **Let's Practice** tile alongside Teach Me and Clarify Doubts.

- If the topic has a question bank ready, the tile is active.
- If not, the tile is greyed out with "No practice bank for this topic yet".
- Refresher ("Get Ready") topics hide the tile entirely.

Tapping the tile opens the practice landing screen.

---

## The Landing Screen

The landing screen is the hub for a topic's practice history. It shows:

- **Start practice** — begins a fresh 10-question set.
- **Resume** — reappears only if an in-progress set exists (auto-saved from a previous abandoned attempt).
- **Past attempts** — a list of every submitted attempt, newest first, with date and score. Tap any row to open its review.

---

## During the Set

Each set is exactly 10 questions with a **3 easy / 5 medium / 2 hard** difficulty mix. All the topic's free-form text questions are included in every set; the remaining slots are filled with structured questions to hit the mix and at least 4 different formats.

The runner shows one question per screen with a progress indicator ("5 of 10"):

- **No hints, no correctness signals** — no green/red, no scoring, no tutor interjection.
- **No timer** — session duration is untracked.
- **No audio and no visuals on question cards** — visuals return on eval cards after submit.
- **Prev / Next** — students can navigate backwards and change any answer before submit.
- **Auto-save** — every answer is saved to the server on change. Closing the tab and returning later resumes the same questions in the same order, with answers preserved.

After the last question, a **Review my picks** screen lists all 10 answers with current selections. Students can edit any answer, then tap **Submit** — one tap, no confirmation dialog.

Blank answers are allowed. They count as wrong at grading.

---

## After Submit

Submit is immediate. The student is routed to a results page and grading runs in the background — typically under a few seconds for a 10-question set.

While grading, the results page shows a "Grading your answers..." state. When grading completes, the score and per-question breakdown appear.

If the student leaves the results page before grading finishes, a **banner** appears at the top of the app when the results are ready. The banner persists across Teach Me, Clarify Doubts, and all other in-app screens. Tapping the banner jumps to the results.

If grading fails (e.g., an LLM transient error after retries), the banner is amber and exposes an inline **Retry** button. If the student stays on the results page and grading hasn't finished after ~5 minutes, the page shows a "Grading is taking longer than expected" state with the same Retry option.

---

## The Results Screen

The results screen leads with the **fractional score** — e.g., "7.5 / 10" — and three primary actions:

- **Reteach this topic** — routes to Teach Me for the whole topic (hidden when the results screen was opened from the banner, since the topic path isn't in state there).
- **Practice again** — one-tap retake on the same topic, fresh set.
- **Back to topic** — returns to the topic's mode selection.

Below the actions is the **card-by-card review**. Each question card shows:

- The original question.
- The student's answer (or "not answered" for blanks).
- The correct answer (on wrong picks).
- For wrong/blank picks and all free-form answers: a 2-3 sentence rationale (≤60 words) — confirms or states the correct idea, names the specific misconception THIS pick reveals, and gives one concrete anchor to remember next time.

The review uses the same interactive components as the runner, but in a disabled/read-only mode with correctness styling applied.

---

## History

Every submitted attempt is stored forever. The landing screen's past-attempts list shows every submission with status chip, date, and score. Graded and grading-failed rows are tappable; in-progress and grading rows are read-only placeholders. Tapping a graded row opens that attempt's full card-by-card review — the exact same UI as a fresh submit.

Because each attempt snapshots its 10 questions at creation time, regenerating a topic's question bank doesn't affect historical reviews.

---

## Scorecard

The scorecard shows, per topic where practice has been attempted:

- Latest score (e.g., "7.5 / 10").
- Attempt count (e.g., "3 attempts").

Only graded attempts count; in-progress and grading-failed attempts are excluded from the scorecard.

---

## Key Details

- **Max one in-progress attempt per topic** — if a student taps Start practice while an in-progress set exists, they resume the existing set.
- **Parallel grading** — submitting attempts on two different topics grades both independently.
- **No admin interruptions** — question banks are regenerated from the admin dashboard only when explicitly triggered; students never see regeneration.
- **Mobile-first** — tap targets minimum 44px; match-pairs columns stack on narrow viewports.
