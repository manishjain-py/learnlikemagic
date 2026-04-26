# Baatcheet ↔ Explain — UX Consistency Audit

**Status:** audit + plan, not yet implemented.
**Scope:** student-facing card-deck UI for Teach Me. Compares Baatcheet (`BaatcheetViewer.tsx`) against Explain (the inline ExplanationViewer in `ChatSession.tsx`).
**Pairs with:** `docs/principles/ux-design.md`, `docs/principles/typography.md`, `docs/principles/baatcheet-dialogue-craft.md`.

---

## TL;DR

Baatcheet ships the same content type as Explain (swipeable teach-cards on a chalkboard) but was built as a self-contained component with its own CSS island. On screen they look like two different products. Cause: Baatcheet didn't inherit Explain's chrome. Fix: Baatcheet becomes a **content variant** of Explain — same room, same nav, same motion, same escape hatches; only the per-card body differs (speaker chip + dialogue turns).

---

## What's already aligned

- Type tokens — Inter (UI) + Lexend Deca (prose), weights {400/600/700}, `--type-*` scale.
- Color tokens — `--board-green`, `--chalk-white`, `--chalk-gold`.
- `prefers-reduced-motion` honored in both.
- Shared `ConfirmDialog` for restart.
- Shared `CheckInDispatcher` for activities.

Foundation isn't broken. Chrome on top of it is.

---

## Where they diverge

### 1. Outer frame (the room)

| | Explain | Baatcheet |
|---|---|---|
| Wall | `.app.chalkboard-active` → `--wood-dark` #6B4220 | `.baatcheet-active` → `--wall-cream` #E8DFCE |
| Layout | Full-bleed carousel | `max-width: 720px` card centered |
| Texture | Wood vignette + chalk-smudge SVGs | Plain cream |

Two different rooms in the same app. Loudest inconsistency; lands the moment the screen mounts.

### 2. Top app chrome (orientation)

| | Explain | Baatcheet |
|---|---|---|
| Home button | ✅ `.nav-home-btn` | ❌ |
| Breadcrumb | ✅ subject › chapter › topic | ❌ |
| Audio replay | ✅ `.focus-audio-btn`, gold-when-playing | ❌ autoplay-only |
| Counter | "3/8" tabular-nums, top-right | "Card 3 / 8" UPPERCASE inside the card |

Baatcheet student loses orientation: no app frame, no manual replay, no quick exit.

### 3. Card surface

| | Explain | Baatcheet |
|---|---|---|
| Card-type badge | ✅ CONCEPT/EXAMPLE/VISUAL/ANALOGY/SUMMARY + gold dot | ❌ no badge |
| Title | h2 card title | h3 only on visual/check-in; dialogue cards have none |
| Body container | Prose flows on board | Wrapped in `1px dashed rgba(244,244,239,0.18)` bubble, padding 16px |
| Prose line-height | **1.65** (per typography §D4) | **1.55** (violates rule) |
| Parchment insets | ✅ for examples/formulas | ❌ |

Dashed bubble is the most consequential difference. typography §5.1 calls explanation prose "the primary reading surface — biggest single win" → 18px / 1.65 / max-width 520px. Baatcheet pulls focus from reading and tightens the line-height.

### 4. Speaker (Baatcheet's net-new element)

96px avatar (76px on mobile), centered, above its own bubble. Becomes the dominant visual element on every dialogue card — bigger than the actual teaching prose. Speaker label 14px Inter +0.04em — fine in isolation, doesn't match anything else's hierarchy.

Not wrong to show a speaker — Baatcheet *is* a dialogue. But pixel real estate is out of scale.

### 5. Bottom navigation

| | Explain | Baatcheet |
|---|---|---|
| Position | Fixed-feel bottom rail + safe-area | Inside the card, scrolls with content |
| Primary CTA | Indigo vertical gradient `#6C7DE8 → #5B6FE0` (via `--cb-action-primary`), pill shadow + `translateY(1px)` on press (App.css:4404-4414) | Cream parchment `var(--parchment) → #EDE1BF` |
| Secondary | Grey pill `#F0F0F0` | Translucent on-board, **1.5px dashed** border |
| Restart | Same row, ghost variant | Flex 0 0 auto, narrower, 14px, 0.85 opacity |
| Escape hatch | ✅ "I didn't understand" | ❌ none — student gets stuck |
| End-of-deck | "I didn't understand" + "Start practice" + "Try a different approach" + "Restart" | "Done" only |

Two brand systems for the same primary action. Indigo = "the way forward" contract is broken.

**Missing escape hatch is the most pedagogically harmful** of these. Per `interactive-teaching.md` and `how-to-explain.md`, students must always be able to say "I didn't understand."

### 6. Motion & reading rhythm

| | Explain | Baatcheet |
|---|---|---|
| Card transition | `translateX` 300ms ease-out | None — instant rerender |
| Text reveal | Typewriter word-by-word (400ms/word, 600ms sentence pause, 900ms spotlight); audio synced via `onBlockTyped` | Instant — full text dropped, audio plays over it |
| Speaking indicator | Audio button turns gold | Avatar pulse 1.6s infinite |

Most-felt difference once reading starts. Explain teaches with paced reveal — words arrive at the speed of comprehension, in sync with TTS. Baatcheet drops the whole turn and lets audio catch up. For Grade 3-8 ESL readers, Explain's rhythm is the principled one.

### 7. Loading & error

| | Explain | Baatcheet |
|---|---|---|
| Initial | "Loading session…" header | Renders nothing |
| Generation skeleton | `.simplification-skeleton` shimmer 1.5s | None |
| Empty | "Loading session…" | Tiny "No dialogue to display." |

### 8. Chooser priming

`TeachMeSubChooser` hands Baatcheet the chalkboard-green gradient + gold "Recommended" badge + heavier shadow. Student is primed for board-aesthetic, taps it, gets a small board on a cream wall. Explain's chooser card is quieter but launches into the bigger chalkboard universe. Expectation and experience are inverted.

---

## Strategy

**Option 1 — Baatcheet inherits Explain's chrome (recommended).**
Explain is older, more battle-tested. Typography role map (§4) was written with explanation cards as the canonical surface. `baatcheet-dialogue-craft.md` is entirely about content authoring and intentionally says nothing about chrome. Baatcheet should be a content variant of Explain — only the per-card body changes (speaker chip + dialogue turns).

**Option 2 — Refactor both to a shared `TeachDeck` primitive.**
Cleanest architecturally; biggest scope. Worth it only if more deck-like surfaces are coming. Currently they aren't.

**Recommendation: Option 1.** One PR-sized push, no Explain regression risk, matches existing principle docs.

The one Baatcheet-specific element worth preserving — and shrinking — is the speaker cue. 96px focal-point avatar overshadows prose; replace with ~40-48px inline chip + name on one line, before the prose.

---

## Prioritized fix list

### P0 — Same room

1. Wrap BaatcheetViewer in `.app.chalkboard-active` → wood wall, vignette, chalk-smudge overlays.
2. Replace centered max-w-720 card with `.focus-carousel` → `.focus-track` → `.focus-slide` skeleton; each dialogue card = one full slide.
3. Drop `.baatcheet-viewer__line` dashed bubble. Prose lives on board at `--type-body-reading` 18px Lexend Deca **line-height 1.65** (currently 1.55).

### P0 — Same nav

4. Adopt Explain top nav: home + breadcrumb + audio-replay (`.focus-audio-btn`) + tabular-nums counter `1/8`. Drop in-card "Card 3 / 8".
5. Adopt Explain bottom nav: same `.explanation-nav-btn` for Back/Restart/Next. Primary uses the chalkboard indigo via `--cb-action-primary` (`#5B6FE0`, gradient start `#6C7DE8`), pill shadow + `translateY(1px)` press — **reach for the token, not raw hex**. Note: `--color-primary` (`#667eea`) and `--color-accent` (`#764ba2`) are the legacy brand gradient still used on welcome/summary surfaces; the chalkboard nav is its own indigo. Pick one across the chalkboard surface — keep `--cb-action-primary`. (Separate cleanup: align summary card CTA to the same token so end-of-deck doesn't pop into the brand gradient.)
6. Add **"I didn't understand"** to Baatcheet — wires to tutor-agent simplification, same UX as Explain.

### P1 — Same motion

7. 300ms `translateX` carousel between Baatcheet cards.
8. Typewriter reveal on dialogue lines, synced to TTS via `onBlockTyped` — reuse `TypewriterMarkdown`. Solves "audio races ahead of text."
9. Keep avatar pulse for speaking; **shrink avatar to 40-48px**, place inline with speaker name as a chip above the prose. Not centered focal element.

### P1 — Same card grammar

10. Card-type badge for Baatcheet: `DIALOGUE` / `VISUAL` / `CHECK-IN` / `SUMMARY`, same `.explanation-card-type` styling (gold dot + uppercase 12px Inter).
11. Same end-of-deck summary card: "Nice work!" + concept chips + "Let's Practice" + "I'm done for now" ghost. Replaces lone "Done".

### P2 — Cleanup

12. Delete orphaned CSS in `.baatcheet-viewer__*` (bubble, in-card progress, in-card nav, separate button system). Keep speaker-chip styles.
13. Audit `--wall-cream` — if Baatcheet was the only consumer, remove the token.
14. Cross-reference in `baatcheet-dialogue-craft.md`: "visual chrome inherits from Explain — see typography §4 + ux-design. This doc covers content only."

---

## One-line summary

Baatcheet is a **content** variant of Explain that was built as a **visual** variant by accident. Converging it onto Explain's chrome — same room, same nav, same motion, same escape hatches; downsized inline speaker chip the only Baatcheet-specific element — restores "one app, one teaching surface" without touching dialogue authoring or the audio pipeline.
