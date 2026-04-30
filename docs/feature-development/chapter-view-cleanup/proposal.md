---
status: proposal
owner: manish
date: 2026-04-30
---

# Chapter View Cleanup — Proposal

## Problem

The admin chapter card in `BookV2Detail.tsx` predates the topic pipeline DAG. It still
exposes a per-topic fan-out for every stage as a chapter-level button:

```
Sync to DB | OCR | Topics | Guidelines | Explanations | Refresher |
Visuals | Check-ins  rounds:[1] | Practice | Generate  rounds:[1] |
Review audio | Audio
```

Now that every topic has its own DAG view (`/admin/books-v2/<book>/pipeline/<topic>`)
and the chapter has a single "▶ Run all topics" orchestrator, the per-topic stage
buttons are duplicate surface area. They also confuse the mental model — it is no
longer obvious which buttons act on the chapter and which silently fan out to
every topic.

Beyond the duplication, the row itself is hard to read:

- Stages, view-links, and generators are mixed together with no visual grouping.
- The order on the chapter row (Refresher → Visuals → Check-ins → Practice → Audio)
  does not match the actual DAG order (Explanations → {Visuals, Check-ins, Practice,
  Audio Review} → Audio Synthesis), so the row misrepresents the pipeline.
- "Generate" and "rounds" controls are wedged inline next to unrelated buttons.
- There is no indication of *what each stage produces* — so the row reads as a
  pile of verbs rather than a pipeline.

## Proposal

### Part A — Remove per-topic fan-out buttons

Drop the chapter-level buttons whose only job was to loop over every topic and
call the per-topic stage. Users do this either via "Run all topics" (chapter
fan-out) or via the topic DAG (single topic).

| Button         | File:line in `BookV2Detail.tsx` | Reason                                              |
| -------------- | ------------------------------- | --------------------------------------------------- |
| Visuals        | 1140                            | Per-topic; viewer link, but topic DAG covers it     |
| Check-ins      | 1141 + rounds 1142–1163         | Per-topic generator; rounds belong on the DAG node  |
| Practice       | 1169                            | Per-topic; viewer link covered by topic DAG         |
| Generate       | 1170 + rounds 1171–1192         | Per-topic generator; rounds belong on the DAG node  |
| Review audio   | 1198                            | Per-topic generator                                 |
| Audio          | 1204                            | Per-topic generator                                 |

Dead state/handlers to remove with them:
- `handleGenerateCheckIns`, `handleGeneratePracticeBanks`,
  `handleGenerateAudioReview`, `handleGenerateAudio`
- `checkInReviewRounds`, `practiceBankReviewRounds`,
  `checkInJobs`, `practiceBankJobs`, `audioReviewJobs`, `audioJobs`
- The corresponding progress banners further down the JSX

### Part B — Keep the genuinely chapter-scoped controls

These act once per chapter and have no per-topic equivalent in the DAG:

| Button         | What it does                                              |
| -------------- | --------------------------------------------------------- |
| Sync to DB     | Sync chapter + topics to the runtime DB                   |
| OCR            | Open the chapter OCR review page                          |
| Topics         | Open topic extraction / review (must run before any topic exists) |
| Guidelines     | Open chapter-level teaching guidelines                    |
| Explanations   | Open chapter-level explanations viewer                    |
| Refresher      | Generate the chapter "get-ready" topic                    |
| Run all topics | Orchestrate the DAG across every topic in the chapter     |

### Part C — Restructure the chapter row for clarity

Replace the flat button row with three labelled groups so the user sees at a
glance: *what stages exist, in what order, and what each one produces*.

```
┌─ Chapter pipeline (shared inputs for all topics) ───────────────────┐
│  1. OCR  →  2. Topics  →  3. Guidelines  →  4. Explanations         │
│  [view OCR]  [view topics]  [view guidelines]  [view explanations]  │
│                                                                     │
│  Optional:  [+ Refresher topic]                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─ Per-topic pipeline ────────────────────────────────────────────────┐
│  Each topic runs its own DAG:                                       │
│    Explanations → { Baatcheet, Visuals, Check-ins, Practice,        │
│                     Audio Review } → Audio Synthesis                │
│                                                                     │
│  [▶ Run all topics]  [Open topic list ▼]                            │
└─────────────────────────────────────────────────────────────────────┘

┌─ Sync ──────────────────────────────────────────────────────────────┐
│  [Sync chapter to DB]   last synced: 2 hours ago                    │
└─────────────────────────────────────────────────────────────────────┘
```

Specifics:

- **Stage chips already exist** (the green/violet/grey "✓ OCR → Topics → Sync → …"
  row at line 1083). Today they show *every* stage including per-topic ones,
  which is also misleading. After Part A, narrow them to chapter-scoped stages
  only — the per-topic stages are the DAG's job.
- **Each stage chip becomes the click target** for "view / manage" — the chip
  already conveys done/active/pending; a separate "view" button next to it is
  redundant. One click on the chip opens the corresponding viewer.
- **"Run all topics" gets promoted** out of the header strip into the
  per-topic-pipeline group, where its meaning is unambiguous.
- **One-line output hint under each chip** (e.g. "Topics — 6 extracted",
  "Guidelines — 1 doc"). Cheap to add from data we already fetch
  (`pipelineSummaries`, `explanationStatus`, etc.).

## Out of scope (for this PR)

- Backend changes to the per-chapter fan-out endpoints. They keep working;
  "Run all topics" already calls the orchestrated path.
- The topic DAG itself.
- Any change to topic-detail rows under the chapter.

## Rollout

Single PR, behind no flag — admin-only surface.

1. Delete buttons + dead handlers/state (Part A).
2. Restructure the row into the three groups (Part C).
3. Update stage chips to chapter-scoped stages only.
4. Update `docs/technical/architecture-overview.md` admin-UI section if it
   names any of the removed buttons (probably does not).

## Open questions

- "Refresher" today regenerates whenever clicked. Should it become a chip with
  a "regenerate" action, or stay a button? Leaning button — it is genuinely
  optional and not part of the linear pipeline.
- Do we want a "rounds" control surfaced anywhere chapter-level, or is that
  now strictly a per-topic-DAG concern? Leaning fully per-topic.
