# Chalkboard UI Redesign — Implementation Tracker

Single source of truth for the redesign. Update as work progresses.

**Branch:** `design/chalkboard-mockups` (one PR for everything)
**Design brief:** [design-brief.md](./design-brief.md)
**Mockups:** `llm-frontend/mockups/chalkboard/` — open `index.html` in a browser
**Direction chosen:** A — Chalkboard Classroom

---

## Status

- **Current step:** 1 — tokens + font loads (not started)
- **Last commit:** `326d087 design: chalkboard UI redesign brief + 6 hero screen mockups`
- **% complete:** ~10% (design phase done, 0% implementation)

---

## Sequencing

| # | Step | Status | Scope | Est |
|---|---|---|---|---|
| 0 | Design brief + mockups | ✅ | 6 hero screens, direction picked | — |
| 1 | Tokens + font loads in `App.css` | ⬜ NEXT | CSS vars + font links, zero visible change | ~30 min |
| 2 | Learning card re-skin | ⬜ | `ChatSession.tsx` explanation slides (hero) | ~3–5 hrs |
| 3 | Check-in components | ⬜ | 11 activities, shared `.checkin-*` batch | ~1 day |
| 4 | Selection screens | ⬜ | Subject / chapter / topic / mode-select | ~½ day |
| 5 | Completion + scorecard + history | ⬜ | Session complete, exam review, report card | ~½ day |
| 6 | Auth + onboarding | ⬜ | Login/signup/OTP/onboarding wizard | ~½ day |
| 7 | Profile + enrichment + report-issue | ⬜ | | ~½ day |
| 8 | Icon / logo SVG pass | ⬜ | Chalk logo, nav icons, mode icons | ~½ day |
| 9 | Polish + QA | ⬜ | Contrast, mobile, animation timing, A11y | ~½ day |

**Total estimate:** 3–4 weeks focused work. Each numbered step ends in a commit, and I pause for review before the next step.

Legend: ✅ done · 🟡 in progress · ⬜ not started · ❌ blocked

---

## Step 1 — Tokens + font loads (NEXT UP)

**Goal:** Drop chalkboard design tokens into the real app without changing any visible pixels. Later steps pull from these tokens instead of hardcoding.

**Files to touch:**
- `llm-frontend/src/App.css` — add new CSS variables in the `:root` block alongside existing ones (do not replace old ones yet — migration is incremental)
- `llm-frontend/index.html` — add Google Fonts link for Caveat + JetBrains Mono (Inter already loaded)

**What NOT to touch:**
- Any JSX/TSX components
- Existing CSS variables (old indigo/purple palette stays as fallback during migration)
- Any screen-specific classes

**Verification:**
- `cd llm-frontend && npx vite build` must pass clean
- `npm run dev` and open `localhost:3000` — should look identical to today

**Exit criteria:** new variables + fonts loaded, build green, one commit.

---

## Progress log

- **2026-04-15** — Design brief written. Direction A (Chalkboard) picked. Mockups built and approved by user. Ready to implement.

_(append a bullet per session or step completion)_

---

## Open questions (revisit during the step indicated)

| Question | When | Default |
|---|---|---|
| Self-host fonts for prod perf/privacy vs Google Fonts CDN? | Step 9 | CDN for now, self-host before launch |
| "Day mode" (cream bg) toggle — build now or later? | After step 2 | Defer until baseline shipped |
| Per-check-in-type feedback colors — keep varied or unify? | Step 3 | Keep varied (mint/coral/etc.) |
| Redraw logo ourselves or hire illustrator? | Step 8 | Use SVG we drew in mockup as starting point |
| Keep existing typewriter word-by-word reveal or switch to chalk-write animation? | Step 2 | Keep existing for now, revisit in step 9 |

---

## Risks to manage

- **Mobile frame overhead:** wood frame eats real estate on 375px phones. Make frame thin (6–8px) on `<768px`, full on tablets+.
- **Contrast:** white chalk on dark green is fine. Pastel chalk colors in body copy are NOT — pastel is for accents only. Enforce during step 2 review.
- **Font-loading flash:** handwritten heading briefly shows in Inter before Caveat loads. Use `font-display: swap` and preload Caveat.
- **Typewriter coupling:** `TypewriterMarkdown` drives line-by-line reveal and TTS audio sync. Re-skinning must not break reveal timing or audio triggers.
- **Scope creep:** ONLY student-facing code. Admin UI (`llm-frontend/src/features/admin/`) is out of scope.
- **Dark theme strain over 20+ min sessions:** watch user feedback after step 2; if it's a problem, accelerate day-mode toggle.

---

## Scope boundary (what's in / out)

**IN scope:**
- All routes/pages listed in design-brief.md §2
- 11 check-in components
- `AppShell` nav chrome
- `ChatSession.tsx` carousel and related CSS
- `TypewriterMarkdown` styling (not logic)
- Inline SVG icons/logo

**OUT of scope:**
- Admin dashboard (`src/features/admin/**`)
- Backend API changes (this is pure frontend)
- Analytics/telemetry rewiring
- Any behavioral/UX logic change (only visual restyle)

---

## How to resume (for future sessions / context clears)

1. `git checkout design/chalkboard-mockups && git pull`
2. Read the **Status** and **Sequencing** tables above — shows where we are
3. Read the "Current step" / "Step N" section for detailed context
4. Open `llm-frontend/mockups/chalkboard/index.html` for visual reference
5. Read `docs/feature-development/kid-friendly-ui-redesign/design-brief.md` only if vision needs refresher
6. Continue from the next unchecked step

---

## Rollback plan

If a step breaks the app or the user wants to back out:
1. `git log --oneline` to find the last-good commit (step N-1)
2. `git revert <bad-commit>` — preserve history
3. Update this tracker with the revert, note what went wrong
4. Replan the failed step before retrying
