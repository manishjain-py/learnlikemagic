# PRD: Baatcheet — Conversational Teach Me Mode

**Date:** 2026-04-25
**Status:** Draft
**Depends on:** Pre-Computed Explanations (variant A), Book Ingestion v2, Google Cloud TTS (Chirp 3 HD)

---

## 1. Problem

Today's Teach Me uses explanation cards — teacher-driven monologue, card after card. The flow is one-directional: information dumps onto the student, who taps "next" without engaging. Three problems:

- **No misconception surfacing.** A student about to think the wrong thing has no anchor for the correction. The teacher pre-empts misconceptions in monologue, but the correction lands flat without the felt experience of "I almost thought that too."
- **No curiosity gaps.** Questions create gaps the brain wants to close (driving retention). Monologue answers questions the student hasn't asked yet.
- **No metacognition modeling.** ESL Indian students often struggle to ask questions out loud. Monologue gives them no model of *how to be confused well*.

## 2. Solution

Add a parallel conversational mode under Teach Me: a pre-scripted dialogue between the tutor and a peer character (Meera) covering the same content as Explain mode. The student watches the conversation unfold card-by-card, occasionally answering when the tutor turns to address them directly.

Same content as Explain. Different teaching frame.

## 3. Mode Hierarchy

```
Teach Me
├── Baatcheet (NEW — default, recommended)
└── Explain (existing flow)
Let's Practice
Clarify Doubt
```

Working names; not final.

---

## 4. Functional Requirements

### 4.1 Mode Selection

- **FR-1:** Tapping "Teach Me" navigates to a chooser page with two stacked cards: Baatcheet on top (visually emphasized — "Recommended" badge or larger), Explain below (quieter secondary).
- **FR-2:** Both modes always presented. No memory of last choice. Student picks every entry.
- **FR-3:** Choosing a mode commits the student for that topic session. No mid-session switching. To switch, student exits to home and re-enters Teach Me.
- **FR-4:** Each mode tracks its own progress and completion state per (student, topic).

### 4.2 Peer Character — Meera

- **FR-5:** Meera is a single peer character used across all topics. Same name, same persona, same voice. Re-introduced in card 1 of every dialogue (no global "have we met?" memory).
- **FR-6:** Meera's age matches the student's (from profile). Personality: curious, warm, not-quite-there-yet. Confident enough to guess aloud — sometimes right, sometimes wrong. Never a know-it-all.
- **FR-7:** Within a single dialogue, Meera plays a mix of four roles. The dialogue generator (LLM, ingestion-time) decides the mix per dialogue:
  1. **Ask** what a curious beginner would ask
  2. **Answer correctly with reasoning** (modeling good thinking)
  3. **Answer incorrectly** (voicing a common misconception, then corrected)
  4. **React** ("hmm", "wait", "oh!")
- **FR-8:** Meera follows the same Easy-English principles as the rest of the app, slightly stricter than the tutor (peer voice = simpler vocabulary).

### 4.3 Dialogue Card Model

- **FR-9:** A dialogue is an ordered list of cards. One dialogue turn per card.
- **FR-10:** Card types:

  | Type | Purpose |
  |---|---|
  | `welcome` | Templated card 1 — introduces Meera, addresses real student |
  | `tutor_turn` | Tutor speaks |
  | `peer_turn` | Meera speaks |
  | `visual` | Visual card with brief tutor narration line |
  | `check_in` | Tutor turns to real student; reuses existing check-in activity |
  | `summary` | Final card — same shape as Explain mode summary |

- **FR-11:** Total card count target: ~25–30 per topic. Hard cap: 35 cards (validator rejects overflow).
- **FR-12:** Check-in cards appear every ~6–8 cards (matches Explain mode density).
- **FR-13:** First card is always `welcome`. Last card is always `summary`. Middle is LLM-generated.

### 4.4 Welcome Card (Templated)

- **FR-14:** Card 1 of every dialogue uses a single hand-authored template, parameterized at runtime:
  > "Hi {student_name}! I'm Mr. Verma. Today, Meera is joining us — she wants to learn about {topic_name} too. Let's start!"
- **FR-15:** Template literal. Same shape every topic. Easy to update once globally.
- **FR-16:** Always introduces Meera (no global "first-time" tracking).

### 4.5 Personalization (Student Name)

- **FR-17:** Cards that address the real student by name carry an `includes_student_name: true` flag. Their `lines` text contains a `{student_name}` placeholder.
- **FR-18:** At session start, the frontend fetches Google TTS audio at runtime for all `includes_student_name: true` cards in parallel. Substitutes `{student_name}` from the student profile.
- **FR-19:** Cards without the flag use pre-rendered S3 audio (synthesized at ingestion time, identical for all students).
- **FR-20:** If the student profile has no name, the placeholder resolves to a generic phrase ("Okay, your turn" instead of "Okay Arjun, your turn"). Audio for nameless students may be pre-rendered.

### 4.6 Visuals (Baatcheet-Specific)

- **FR-21:** Baatcheet has its own visual cards generated as a separate ingestion stage (Stage 5c, see §6). Baatcheet does **not** inherit or reference variant A's visuals.
- **FR-22:** Visual generator works purely from the dialogue text (no input from variant A's visuals).
- **FR-23:** A visual card holds: PixiJS visual (or interactive_visual template), title, brief narration line spoken by the tutor, audio_url.
- **FR-24:** Existing PixiJS code generator (`tutor/services/pixi_code_generator.py`) is reused.

### 4.7 Check-In Cards

- **FR-25:** Reuses the existing 11 check-in activity types verbatim and the existing `CheckInDispatcher` component.
- **FR-26:** Reactions are generic per check-in (one `success_message`, one `hint`). No answer-specific reactions in V1.
- **FR-27:** Meera does not react to the real student's check-in answer in V1. Only the tutor's reaction plays.

### 4.8 Audio & Voice

- **FR-28:** Two distinct voices are used:
  - **Tutor:** existing `hi-IN-Chirp3-HD-Kore` (no change to existing app behavior).
  - **Meera:** a different `hi-IN-Chirp3-HD-*` voice (specific voice selected during impl after audition).
- **FR-29:** Pre-rendered audio (Stage 10) generates one MP3 per card, stored in S3.
- **FR-30:** Personalized cards (`includes_student_name: true`) skip pre-rendering. Audio is synthesized at session start via the existing runtime `/text-to-speech` endpoint.

### 4.9 Navigation, Pacing, Continuity

- **FR-31:** Same carousel as Explain mode. Tap-to-advance forward; tap-to-go-back. New cards auto-play TTS. Revisited cards show final state with no auto-replay.
- **FR-32:** Replay button is **deferred to V2** (applies to both Baatcheet and Explain).
- **FR-33:** Resume-from-last-card on session re-entry. **Applies to both Baatcheet and Explain mode** — Explain-mode resume is a scope expansion shipped with this PR.
- **FR-34:** A topic counts as **complete** when the student sees the final summary card. Independent of check-in correctness. Replays of completed topics are unlimited.

### 4.10 End-of-Dialogue

- **FR-35:** Final card is identical in shape and behavior to Explain mode's summary card: brief recap text + "Let's Practice" CTA. No dialogue-flavored sign-off in V1.

### 4.11 Visual Layout

- **FR-36:** Single-speaker focus: only the currently speaking character's avatar is visible at a time. Cross-fade between tutor and Meera turns.
- **FR-37:** New compact avatars used (small footprint — text dominates the screen). Avatars are Baatcheet-specific. Existing Virtual Teacher avatar unchanged.
- **FR-38:** V1 avatars are **stylized placeholders** (one per character + simple speaking indicator e.g., glow ring or pulse). Properly illustrated/animated avatars deferred to V2.
- **FR-39:** Speech bubble or text container appears below avatar; line text shown in full on card entry (typewriter-sync to TTS deferred to V2).

---

## 5. Non-Goals (V1)

- Branching dialogue based on check-in answers (right/wrong reactions only, then rejoin).
- Multiple dialogue variants per topic (one dialogue per topic).
- User-selectable peer (Meera is the only peer character).
- Mid-session mode switching (Baatcheet ↔ Explain on the same topic).
- Scripted Meera reactions to check-in answers.
- Answer-specific check-in reactions.
- Properly commissioned avatars (stylized placeholders only).
- Typewriter/word-by-word reveal synced to TTS (whole-line reveal in V1).
- Replay button in dialogue (deferred for both modes).
- Mode preference memory.

---

## 6. Ingestion Pipeline Changes

```
Existing                                   Baatcheet additions
───────                                    ───────────────────
Stage 5: Variant A/B/C explanations        Stage 5b: Dialogue Generation
                                             Input:  Variant A cards + Teaching Guideline
                                             Output: TopicDialogue.cards_json (text + visual slots)
Stage 6 (parallel branch for variant A):   Stage 5c: Baatcheet Visual Enrichment
  - Visual enrichment                        Input:  Stage 5b output
  - Check-in enrichment                      Output: PixiJS visuals filling Stage 5b's visual slots
  - Practice bank
Stage 10: Audio synthesis                  Stage 10: Same — extended to handle two voices
                                             (tutor vs. peer based on card.speaker)
```

- **FR-40:** Stage 5b runs sequentially after Stage 5 finishes for variant A specifically. Doesn't wait for variants B and C.
- **FR-41:** Stage 5c runs sequentially after Stage 5b. Stages 5b → 5c form a parallel branch alongside the existing variant A enrichment branch.
- **FR-42:** Stage 10 (audio synthesis) is extended to select voice by `card.speaker` (`tutor` vs. `peer`). Existing variant A audio synthesis is unchanged.
- **FR-43:** Each new stage has its own admin trigger button: "Generate Baatcheet dialogue" (5b), "Generate Baatcheet visuals" (5c). Independently regenerable.
- **FR-44:** Stage 5b uses review-refine rounds (matches Stage 5 pattern — 1 initial pass + N rounds, configurable per environment).

### Stage 5b — Dialogue Generation Prompt Inputs

- Teaching guideline text (full)
- Variant A explanation cards (full)
- Student persona placeholder hints (e.g., `{student_name}`, `{topic_name}`)
- Constraints: card count 25–35, check-in spacing 6–8, Meera's role mix, Easy-English rules
- `common_misconceptions` from the guideline (used as soft material — see §8)

### Stage 5b — Output Validation

- Card count between 13 and 35.
- First card is `welcome`; last card is `summary`.
- Check-in cards spaced ≥4 cards apart (no back-to-back check-ins).
- Each `peer_turn` and `tutor_turn` has at least one line.
- All visual slots have a non-empty title and intent description.
- Failed validation → review-refine round.

---

## 7. Regeneration Behavior

- **FR-45:** Variant A regeneration does **not** cascade to Baatcheet. Dialogue stays as-is until the editor clicks "Regenerate Baatcheet dialogue."
- **FR-46:** Admin UI shows a **stale dialogue warning** when variant A's `updated_at` is newer than `TopicDialogue.updated_at`.
- **FR-47:** A bulk "Regenerate all stale dialogues" button is provided for end-of-edit-session cleanup.
- **FR-48:** Stage 5c (visuals) regeneration is decoupled from Stage 5b (text). Editors can regenerate text without re-doing visuals, and vice versa.

---

## 8. Misconception Coverage (Soft)

- **FR-49:** The dialogue generation prompt includes `common_misconceptions` from the `TeachingGuideline` as material the generator MAY voice via Meera. Soft requirement — generator decides which (and how many) to surface.
- **FR-50:** No validator gate on misconception count in V1. Quality drift is caught via review-refine rounds.

---

## 9. Storage

- **FR-51:** New table `topic_dialogues`:

  | Field | Type | Description |
  |---|---|---|
  | `id` | UUID | PK |
  | `guideline_id` | UUID | FK to `teaching_guidelines` (cascade delete) |
  | `cards_json` | JSONB | Ordered list of dialogue cards |
  | `generator_model` | VARCHAR | LLM model used |
  | `source_variant_key` | VARCHAR | "A" (always, in V1) |
  | `created_at` / `updated_at` | TIMESTAMP | |

- **FR-52:** Each card in `cards_json` has the shape:

  ```json
  {
    "card_idx": 1,
    "card_type": "welcome|tutor_turn|peer_turn|visual|check_in|summary",
    "speaker": "tutor|peer|null",
    "lines": [{"display": "...", "audio": "..."}],
    "audio_url": "https://...",
    "includes_student_name": false,
    "visual": null | {...},
    "check_in": null | {...},
    "title": "optional"
  }
  ```

- **FR-53:** No S3 backup. Cards are small structured JSON — DB JSONB is sufficient.
- **FR-54:** Cascade delete on `guideline_id`: re-syncing a guideline clears its dialogue, just like variant A explanations. Stage 5b regenerates on next ingestion run.

---

## 10. Frontend Changes

- **FR-55:** New `BaatcheetViewer` component, sibling to `ExplanationViewer`. Reuses the carousel/navigation/check-in dispatcher from Explain mode.
- **FR-56:** New `sessionPhase: 'dialogue_phase'` in `ChatSession.tsx`, alongside `card_phase`.
- **FR-57:** Mode chooser screen (Teach Me → Baatcheet/Explain) added as a new sub-step in the existing mode selection flow.
- **FR-58:** Resume support added to both `ExplanationViewer` and `BaatcheetViewer` (shared progress-tracking infra).
- **FR-59:** New compact avatar assets bundled in `llm-frontend/public/` for Baatcheet (placeholder versions for V1).
- **FR-60:** Frontend pre-fetches runtime-synthesized audio for all `includes_student_name: true` cards at session start, in parallel.
- **FR-61:** Single-speaker layout: avatar fades in/out as speakers change. No persistent two-character layout.

---

## 11. Impact on Existing Features

| Feature | Impact | Details |
|---|---|---|
| Explain mode (Teach Me) | Minor | Resume-from-last-card behavior added (consistent with Baatcheet). Otherwise unchanged. |
| Mode selection | Minor | Teach Me now leads to a sub-chooser instead of starting directly. |
| Virtual Teacher | None | Existing avatar and TTS endpoint unchanged. |
| Check-in dispatcher | None | Reused verbatim. |
| Practice mode | None | Practice CTA at end of Baatcheet identical to Explain. |
| Audio synthesis (Stage 10) | Minor | Voice selection now branches on `speaker`. Backward compatible. |
| Variant A explanations | None | Source of truth, untouched. |
| Existing card carousel | None | Reused; same component drives both modes. |

---

## 12. Edge Cases

| Scenario | Behavior |
|---|---|
| Topic has no Baatcheet generated yet | Mode chooser disables the Baatcheet card, shows "coming soon" hint. (Backfill handled by admin team outside V1 ship.) |
| Student profile missing `name` | Personalized cards fall back to generic phrasing. |
| Runtime TTS fetch fails for personalized card | Show display text only, skip audio for that card. |
| Check-in answered incorrectly | Tutor's `hint` plays, student retries (existing CheckInDispatcher behavior). |
| Student exits mid-dialogue | Resume to last viewed card on next entry. |
| Variant A regenerated mid-edit | Baatcheet stays as-is. Admin sees stale-warning until they explicitly regenerate. |
| Two students of significantly different ages | Same dialogue served. Meera's age cue softened in the prompt to avoid hard age contradictions. |
| Student picks Baatcheet on topic without dialogue | Mode chooser prevents this — Baatcheet card disabled (see first row). |

---

## 13. Open Items / Defer to Implementation

1. **Specific Meera voice selection.** Audition `hi-IN-Chirp3-HD-*` voices during impl.
2. **Avatar placeholder design.** Choose colors / silhouettes / speaking indicator style during impl.
3. **Review-refine round count** for Stage 5b dialogue generation. Default: match Stage 5 pattern; tune based on quality.
4. **Validator threshold details** (max card count, check-in spacing rules, role-mix rules, length per card).
5. **Admin UI surface** for the stale-dialogue warning and bulk regenerate.

---

## 14. Success Criteria

1. **Engagement.** Students complete a Baatcheet dialogue end-to-end at ≥ rate of Explain mode (no regression).
2. **Retention.** Students who chose Baatcheet for a topic score equal-or-higher on Practice / Scorecard than students who chose Explain (long-tail measurement).
3. **Quality.** A curriculum reviewer rates Baatcheet dialogues as pedagogically sound (misconceptions surfaced, no factual errors, conversational tone, age-appropriate, within length cap).
4. **Operational.** Stage 5b + 5c add < 30s wall-clock per topic to the ingestion pipeline (parallel with existing variant A enrichment).
5. **Zero regression.** Existing Explain mode, Virtual Teacher, Practice, and Clarify Doubt flows unchanged behaviorally except for the resume feature added to Explain mode.

---

## 15. V2 Roadmap (deferred from V1)

- Properly commissioned animated avatars (replace V1 placeholders)
- Replay button in both Baatcheet and Explain
- Typewriter / word-by-word reveal synced to TTS
- Branching on check-in answers (richer recovery from wrong answers)
- Multiple dialogue variants per topic
- Scripted Meera reactions to real-student check-in answers
- Answer-specific check-in reactions (tailored to the wrong option picked)
- Mode preference memory (remember last chosen Teach Me sub-mode)
