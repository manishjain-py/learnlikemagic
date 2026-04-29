# Baatcheet Spotlight Avatars — Implementation Plan

## Goal

Replace the 44px speaker chip in BaatcheetViewer with a "Spotlight" presenter strip — a 92px square portrait with name, role tag, and animated speaking indicator. Make Mr. Verma and Meera read as a real teacher and a real student, while keeping every existing dialogue feature working unchanged.

## Reference layout

Picked design: **Variant 2 — Spotlight** from the avatar mockups review.

- Mockup file: `reports/baatcheet-avatar-mockups/variant-2-spotlight.html`
- Open both phone frames (Frame A = Mr. Verma speaking, Frame B = Meera speaking) for the canonical visual spec.
- Shared CSS used in mockups: `reports/baatcheet-avatar-mockups/shared.css` (token names match production `App.css`).
- Meera redrawn 2026-04-30 — middle-parted hair, two thin front plaits with red ribbon bows, no bangs, no bindi, school bow at collar (use the V2 mockup as the spec).

## What changes (visual layer only)

The card head changes from "card-type badge + small chip" to "card-type badge above + spotlight strip below".

```
┌───────────────────────────────────────┐
│ • DIALOGUE                       ☆    │   ← card-type badge (existing)
├───────────────────────────────────────┤
│ ┌────────┐  Mr. Verma                 │
│ │ 92×92  │  Your tutor                │   ← NEW: spotlight strip
│ │portrait│  ▌▌▌▌  speaking            │      (replaces .baatcheet-speaker-chip)
│ └────────┘                            │
├───────────────────────────────────────┤
│       [ visual aid card ]             │   ← unchanged
│         ↻ REPLAY                      │   ← unchanged (replay button)
│       [ dialogue text — typewriter ]  │   ← unchanged
└───────────────────────────────────────┘
│  BACK     RESTART     NEXT            │   ← unchanged
└───────────────────────────────────────┘
```

Spotlight strip composition:
- 92×92 rounded-square portrait (border-radius 18px, gold inset ring, gold halo when speaking)
- Speaker name (18px Inter 700, gold for tutor, pink for peer)
- Role tag (`Your tutor` / `Classmate`, 11px caps)
- Speaking pill (4-bar animated equalizer + "speaking" label) — visible only when `speaking === true`
- Inactive state: same strip, no equalizer pill, no halo, no pulse

Mobile (≤600px): strip stays full-width, portrait shrinks to 80×80, name to 16px.

## What MUST keep working (no regressions)

Every behavior listed below exists today and must work identically after the change:

| Feature | Source of truth | Verify after change |
|---|---|---|
| Per-card typewriter reveal (`renderTypewriter()`) | `BaatcheetViewer.tsx` | Text reveals word-by-word in sync with audio on every dialogue card |
| Per-line MP3 + audio sync (`playDialogueLineAudio`) | `BaatcheetViewer.tsx` | Audio plays line-by-line; typewriter waits on `Audio('ended')` |
| Replay button | inside the card body, below visual | Re-triggers reveal+playback (`replayCurrent()` via ref); per-card replay epoch still bumps |
| Visual aid (PIXI/SVG) (`VisualExplanationComponent`) | `card.visual_explanation` + `visualPixiCode` | Visual still mounts above dialogue; `visualReady` gating still works |
| Check-in cards | `card.card_type === 'check_in'` | Spotlight strip still renders ABOVE the CheckInDispatcher; bottom nav still hides; check-in result still completes |
| Cross-fade on speaker change | `key={speaker}` on the avatar component | When the user navigates Next from a Verma card to a Meera card, portrait crossfades; identity is unambiguous through the transition |
| Speaking pulse animation | driven by `speaking` prop | Halo + equalizer animate while audio plays; settle when audio ends |
| Carousel navigation (Back / Restart / Next) | `.focus-track` translateX | Horizontal slide swap works; nav disabled while typewriter running (`activeCardAnimating`) |
| Card-type badge (`DIALOGUE` / `VISUAL` / `CHECK-IN` / `SUMMARY`) | `cardTypeBadge()` | Badge still renders on cards that have one |
| `card.speaker === null` (no-speaker cards) | currently hides chip | Spotlight strip is also hidden; layout falls back to body-only |
| Topic bar / Feedback / audio toggle / star bookmark | parent shell (ChatSession) | Untouched |
| Bottom nav (Back · Restart · Next) | `.explanation-nav` | Untouched |
| Keyboard nav, swipe gestures | `.focus-track` shared rule | Untouched |
| `prefers-reduced-motion` | existing `@media` rules | Pulse + equalizer + crossfade respect reduced-motion |

## Scroll behavior

Today: `.focus-slide` has `overflow-y: auto`, so each card scrolls vertically when its content exceeds viewport height. Topic bar (top) and bottom nav are siblings of the carousel — they stay fixed; only the slide content scrolls.

Decision for spotlight: **scroll together with content** (do NOT make the spotlight sticky inside the slide).

Rationale:
- Most cards fit without scrolling — spotlight + visual aid + ~3 lines of text fits in <600px on a typical phone (390 wide × 750 tall, minus header/nav).
- Sticky spotlight would compete with the visual aid card and visually pin two large elements at the top, leaving even less room for text.
- The chalkboard topic bar (which carries audio + step counter) is already always visible at the top of the screen.
- When a card does overflow (long check-in prompt, multi-line summary), it should scroll naturally as a single unit; users keep gesture muscle memory from existing cards.

Sticky behavior is **out of scope** for V1. Revisit only if user testing shows people lose track of who's speaking on long cards.

## Files to modify

| Path | Change |
|---|---|
| `llm-frontend/src/components/baatcheet/SpeakerAvatar.tsx` | Rewrite as `<SpeakerSpotlight>` (or rename file). New props: `speaker`, `speaking`. Renders portrait + name + role tag + speaking pill. Same `key={speaker}` crossfade pattern. |
| `llm-frontend/src/components/teach/BaatcheetViewer.tsx` | In `.baatcheet-card-head` (lines ~511–526), replace the `<div class="baatcheet-speaker-chip">` block with `<SpeakerSpotlight>`. Keep card-type badge as a sibling. |
| `llm-frontend/src/App.css` | Replace `.speaker-avatar*` block (lines ~8738–8793) with `.speaker-spotlight*`. Update `.baatcheet-card-head` to be a column (badge above, spotlight below) instead of a row. Add `@media (max-width: 600px)` overrides. |
| `llm-frontend/public/avatars/tutor.svg` | Replace existing 22-line geometric SVG with the V2 portrait art (semi-realistic 3/4 turn, salt-and-pepper hair, glasses, mustache, mid-speech mouth). Source: `reports/baatcheet-avatar-mockups/variant-2-spotlight.html` (Frame A's inline SVG). |
| `llm-frontend/public/avatars/peer.svg` | Replace with the redrawn Meera (middle parting, two thin plaits, ribbon bows, no bindi, school bow at collar). Source: `reports/baatcheet-avatar-mockups/variant-2-spotlight.html` (Frame B's inline SVG, post-2026-04-30 edit). |

## Files to add

None. The new SVGs replace existing files in-place; the spotlight component replaces the avatar component in-place.

## State coverage

| State | Visual |
|---|---|
| `speaker === null` | Spotlight hidden entirely; body content centers as today |
| `speaker === 'tutor'`, `speaking === false` | Verma portrait, gold name, role tag, no equalizer, no halo |
| `speaker === 'tutor'`, `speaking === true` | Verma portrait, gold halo + 3px outer glow, equalizer pill animating |
| `speaker === 'peer'`, `speaking === false` | Meera portrait, pink name, role tag, no equalizer |
| `speaker === 'peer'`, `speaking === true` | Meera portrait, gold halo, equalizer animating |
| Speaker change between cards | 320ms opacity crossfade (existing `key={speaker}` pattern) |
| `prefers-reduced-motion: reduce` | Halo static at 40% opacity, no pulse, no equalizer animation, no crossfade |

## Edge cases

- **Check-in card** — Spotlight should still render at the top (identifies who is asking the question). CheckInDispatcher renders below it; bottom nav hides as today.
- **Visual card with no `pixi_code`** — Spotlight renders, then visual_intent paragraph, then nothing else. No regression.
- **Card with no title** — Spotlight renders, then directly into visual or typewriter body. No regression.
- **Long dialogue text overflows** — Slide scrolls as one unit; spotlight scrolls out of view (acceptable per decision above).
- **Audio fails to load** — `speaking` stays `false`; spotlight stays in idle state; typewriter advances silently. No regression.
- **Personalized vs pre-rendered audio path** — Both call into the same `speaking` boolean lifecycle; spotlight doesn't care which path was used.
- **Replay mid-card** — Resets typewriter via per-card replay epoch; spotlight halo/equalizer should re-trigger when audio restarts.
- **Restart from card 0** — Global restart epoch already remounts subtrees; spotlight remounts cleanly with new `key={speaker}`.

## Acceptance criteria

Implementation is done when:

- [ ] Visual matches `variant-2-spotlight.html` Frame A and Frame B at iPhone-sized viewport
- [ ] Mr. Verma and Meera SVGs in `public/avatars/` updated to the new portraits
- [ ] All seven existing capabilities in the "What MUST keep working" table verified by hand on at least one dialogue topic end-to-end (ingest → Baatcheet → completion)
- [ ] All seven state-coverage rows in the "State coverage" table verified visually
- [ ] No new TypeScript errors; no new lint warnings
- [ ] `prefers-reduced-motion: reduce` verified in DevTools rendering panel
- [ ] At least one dialogue card with overflowing text confirmed to scroll cleanly
- [ ] Check-in card still completes (CheckInDispatcher → onCheckInComplete → next card)

## Out of scope

- Polaroid / Stage Duo / Chat Bubble / Classroom Scene / Chalk variants (V1, V3–V6) — kept as alternatives, not shipping.
- Animated facial expressions (mouth open/closed sync with audio) — V2 mockup uses a static "mid-speech" mouth; expression sync is a future enhancement.
- "Sticky spotlight" while content scrolls — deferred unless testing demands it.
- Photographic-realism portraits — current SVG art is illustrated; commissioning real character portraits is a separate brand exercise.
- Updating the chalkboard topic bar, bottom nav, or any non-Baatcheet viewer.

## Resolved decisions (locked 2026-04-30)

1. **Role tag copy** — `Your tutor` for Verma, `Classmate` for Meera. Warm, instantly legible.
2. **Crossfade duration** — 220ms (was 320ms). Fade only fires on actual speaker change; 220ms reads as a soft swap without lag.
3. **Speaking-pill copy** — lowercase `speaking`, no ellipsis. The animated equalizer carries the in-progress signal. Pill is also hidden when the global audio toggle is off — pill reflects actual playback, not just speaker identity.
4. **Card-type badge** — hidden on `dialogue` cards (the spotlight already names the speaker). Kept on `visual` / `check_in` / `summary` cards because those signal a shift in interaction shape.
5. **Mobile portrait size** — start at 80px at ≤600px width. Revisit at step 6 (device check) before final lock.

## Implementation order (suggested)

1. Add the new SVG art to `public/avatars/` (lowest-risk first — no behavioral change yet).
2. Replace `SpeakerAvatar.tsx` with `SpeakerSpotlight.tsx`, keep the same import path so callers don't change.
3. Replace CSS block in `App.css`. Verify cross-fade + speaking pulse on a single card.
4. Walk the entire dialogue (one full topic) end-to-end on mobile + desktop.
5. Verify check-in cards, visual-only cards, and summary cards.
6. Tighten mobile breakpoint sizes after device check.
