# Chalkboard UI Redesign — Implementation Tracker

Single source of truth for the redesign. Update as work progresses.

**Branch:** `design/chalkboard-mockups` (one PR for everything)
**Design brief:** [design-brief.md](./design-brief.md)
**Mockups:** `llm-frontend/mockups/chalkboard/` — open `index.html` in a browser
**Direction chosen:** A — Chalkboard Classroom

---

## Status

- **Current step:** ✅ ALL 9 STEPS COMPLETE — ready for PR
- **Last commit:** step 9 — polish (nav fix, A11y, reduced-motion, mobile)
- **% complete:** 100% (awaiting final user QA before opening PR)

---

## Sequencing

| # | Step | Status | Scope | Est |
|---|---|---|---|---|
| 0 | Design brief + mockups | ✅ | 6 hero screens, direction picked | — |
| 1 | Tokens + font loads in `App.css` | ✅ | CSS vars + font links, zero visible change | done |
| 2 | Learning card re-skin | ✅ | `ChatSession.tsx` explanation slides (hero) | done |
| 3 | Check-in components | ✅ | 11 activities, shared `.checkin-*` batch | done |
| 4 | Selection screens | ✅ | Subject / chapter / topic / mode-select | done |
| 5 | Completion + scorecard + history | ✅ | Session complete, exam review, report card | done |
| 6 | Auth + onboarding | ✅ | Login/signup/OTP/onboarding wizard | done |
| 7 | Profile + enrichment + report-issue | ✅ | | done |
| 8 | Icon / logo SVG pass | ✅ | Chalk logo, nav icons, mode icons | done |
| 9 | Polish + QA | ✅ | Contrast, mobile, animation timing, A11y | done |

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
- **2026-04-15** — Step 1 complete. Chalkboard tokens added to `App.css` (board/wood/chalk/parchment palettes, font vars, spacing, radius, shadows). Font preconnect + stylesheet added to `index.html` (Inter 400-700, Caveat 500-700, JetBrains Mono 400-500). Legacy indigo/purple palette untouched. Build clean, 7 tests pass, zero visible change. CSS +1.7KB, HTML +0.5KB.
- **2026-04-15** — Step 2 complete. Added `chalkboard-active` class to `.app` when `sessionPhase === 'card_phase'` (single JSX change in `ChatSession.tsx:1459`). Added ~200 lines of CSS scoped under `.chalkboard-active` — chalkboard surface with vignette + SVG doodle overlays, chalk-white text, Caveat handwritten headings, parchment visual inset, wood-toned top nav + progress bar, wood bottom nav with chalk-tray strip and chalk pill Back/Next buttons. Interactive/exam phases untouched. Build clean, 7 tests pass, CSS +8.5KB. Awaiting visual QA.
- **2026-04-15** — Step 3 complete. CSS-only — no JSX changes since `.chalkboard-active` was already applied. ~200 lines covering all 11 check-in activities (PickOne, TrueFalse, FillBlank, SortBuckets, Sequence, SpotError, OddOneOut, PredictReveal, SwipeClassify, TapToEliminate, Match). Uniform patterns: chalk-white options with dashed borders, mint glow on correct, coral + shake on wrong, gold ring on selected, parchment popup for fill-blank input, chalk pill continue buttons. Existing `match-shake` animation untouched. Build clean, 7 tests pass.
- **2026-04-15** — Step 4 complete. `AppShell` now applies `chalkboard-active` to `.app` when `location.pathname.startsWith('/learn')` — scoping the theme to selection routes (subject/chapter/topic/mode) while leaving profile/history/report-card untouched until later steps. Added ~290 lines of CSS covering: selection-step chalkboard surface with vignette, hand-written chalk h2/h3, chalk-spine style on subject cards, chalk-ghost back button, gold/dim breadcrumb, dashed chalk-list rows for learning-path with mint/gold variants for completed/in-progress, parchment "Get Ready" button, mode-selection descriptions + resume cards with chalk shadow, past-exams list, session-error banner, parchment enrichment prompt, mobile tightening. Also cleaned up inline styles in `TopicSelect.tsx`, `ModeSelection.tsx`, `ModeSelectPage.tsx` — replaced `style={{ color: '#666' ... }}` etc. with semantic classes (`.mode-desc`, `.mode-card-sub`, `.mode-practiced-note`, `.chapter-landing-label`, `.chapter-landing-text`, `.get-ready-btn`, `.past-exams-toggle`, `.past-exam-row`, `.session-error-banner`). Note: resume-card gradients kept inline (they're the intent — vivid CTAs pop against chalkboard). ExamReviewPage also under `/learn` — inherits chalkboard bg + wood nav but inner content unstyled until step 5. Build clean, 7 tests pass, CSS 78.6KB.
- **2026-04-15** — Step 5 complete. Extended `AppShell` `chalkboard-active` scope to include `/history` and `/report-card` (exam review was already under `/learn`). Added ~450 lines of CSS for: (1) **session-complete-card** — standalone chalkboard island inside `ChatSession` with gold "Well done!" heading, mint chalk chips for concepts, parchment primary button + chalk-ghost secondary; (2) **SessionHistoryPage** — chalk stat cards, chalk-pill mode filter with gold-active state, dashed chalk session rows with hand-written topic titles + gold subject tags; (3) **ReportCardPage** — chalk-spine subject cards matching SubjectSelect pattern, dashed chapter sections, gold coverage bars, mint exam-score pills, parchment "Practice Again" button; (4) **ExamReviewPage** — chalk question cards, parchment-inset rationale, gold next-steps callout; (5) shared page-level chalkboard overrides for `page-title`, `page-empty-state`, `content-back-link`, `auth-btn`, `auth-link`, `auth-error`. Also cleaned 10+ inline `style={{...}}` blocks in `ChatSession.tsx` session-complete — replaced with semantic classes (`.session-complete-title`, `.session-complete-chips`, `.session-complete-btn--primary/ghost`). Inline exam-review score colors kept (they encode semantic pass/fail via red/amber/green). Build clean, 7 tests pass, CSS 92.1KB (+13.5KB).
- **2026-04-15** — Step 6 complete. Added `chalkboard-active` class to every `.auth-page` root across all 9 auth pages (LoginPage, EmailLogin, EmailSignup, EmailVerify, PhoneLogin, OTPVerify, ForgotPassword, OAuthCallback, OnboardingFlow) — 11 total JSX spots touched via sed. Added ~440 lines of CSS scoped under `.auth-page.chalkboard-active`: (1) wood-toned room bg; (2) `.auth-container` redrawn as wood-framed chalkboard via ::before pseudo-element (matches the real-app frame + vignette aesthetic); (3) chalk-white title + subtitle in handwritten Caveat, body text in Inter; (4) dashed chalk inputs with gold focus ring + placeholder dim chalk; (5) parchment primary pill, mint phone pill, gold email pill, chalk-ghost Google pill, chalk-outlined "auth-btn-outline" selected → gold; (6) OTP 6-digit squares with hand-written digits and gold focus glow; (7) onboarding progress dots — dim → gold (active, pulse scale) → mint (completed); (8) grade-grid (12 grades) with chalk-outlined squares, gold glow on select; (9) board-list using auth-btn-outline styling; (10) mobile tightening under 480px. Only inline style kept: `{ marginTop: '16px' }` on resend buttons (harmless). Build clean, 7 tests pass, CSS 104.5KB (+12.4KB).
- **2026-04-15** — Step 7 complete. Extended `AppShell` `chalkboard-active` to cover `/profile` and `/report-issue` — this completes the student-facing chalkboard skin (admin routes still excluded). Added ~500 lines of CSS. (1) **ProfilePage**: re-scoped `auth-form`, `auth-field`, `auth-btn`, `auth-success` under `.chalkboard-active` (step 6 scoped them under `.auth-page.chalkboard-active` which doesn't match AppShell mode); profile-section gets dashed chalk divider + handwritten h3; profile-info dim chalk; select dropdown option bg set to wood-dark for readable OS popup. (2) **EnrichmentPage**: gold parchment CTA card, gold→mint progress bar, parchment migration banner, expandable chalk sections with mint-dot filled indicator, chip system (dim chalk default, gold-filled selected), tag input with gold pill tags, parchment-inset personality card for AI summary, save-all strip with mint/coral status. (3) **ReportIssuePage**: fully refactored from inline styles to semantic classes (`.report-issue-*` — heading, subtitle, error, card, label, textarea, tools, tool-btn with recording variant, previews with remove buttons, submit-btn, done state with mint check). Build clean, 7 tests pass, CSS 120.4KB (+15.9KB).
- **2026-04-15** — Step 8 complete. SVG-only change — no CSS delta. (1) **Nav-logo** (`AppShell.tsx`): ditched the indigo `logoGrad` linearGradient; redrew as chalk-outlined open book (`stroke="currentColor"` → inherits `--chalk-white` on chalkboard routes, legacy indigo nav if any) with gold wand + star (`#F4C76C`) crossing over. (2) **Auth-logo** (`LoginPage.tsx`): same chalk book + gold wand treatment, 72px scale. (3) **Favicon**: created `/public/chalk-logo.svg` (chalk book + gold wand on green-board tile — looks right at 16/32 px tab sizes) and updated `index.html` `<link rel="icon">` to point at it (previous `/vite.svg` didn't exist in repo — was 404'ing). Nav/dropdown stroke icons were already `currentColor` and inheriting chalk color correctly from step 5 — no change needed. Build clean, 7 tests pass, CSS 120.4KB (unchanged).
- **2026-04-15** — Step 9 complete. Final polish pass. (1) **Nav-center gradient bug fix**: on chalkboard routes the "Learn Like Magic" title was rendering transparent because `.nav-center` used `-webkit-text-fill-color: transparent` with indigo gradient — step 2 set `color` but didn't clear the fill. Reset `background: none`, `text-fill-color: var(--chalk-white)`, and `background-clip: initial`. (2) **Contrast bumps**: `--chalk-white-soft` 0.85→0.88, `--chalk-white-dim` 0.55→0.68 (the dim value was failing AA for body text on board-green). (3) **Focus-visible ring**: 2px gold outline + soft 4px gold glow on all interactive elements (buttons/links/inputs) when keyboard-focused — mouse users see no extra ring. Inputs with their own internal focus glow get only the internal glow (no double ring). (4) **Reduced motion**: `@media (prefers-reduced-motion: reduce)` block disables animations/transitions globally and zeroes out hover-transform (translateY/scale) on chalk cards. (5) **Mobile ≤480px**: nav-logo 28→22px, nav buttons 36→32, stats-grid gap tighter, reportcard-subject-grid single-column, session-complete margin/padding tighter, exam score 2.8→2.2rem. (6) **Touch targets (pointer: coarse)**: small chalk buttons (mode-filter, past-exams-toggle, info-toggle, back-button) bumped to min 36px height. (7) **aria-live error banners**: `role="alert" aria-live="assertive"` added to all error banners (`.auth-error` × 10 files, `.report-issue-error`, `.session-error-banner`) via sed — screen readers now announce errors on render. Build clean, 7 tests pass, CSS 123.2KB (+2.8KB).

**Redesign complete — ready for PR review and merge to `main`.**

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
