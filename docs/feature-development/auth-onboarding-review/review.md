# Auth, Onboarding, Profile & Preferences — Review

**Date:** 2026-04-23
**Scope:** Sign up, sign in, onboarding wizard, profile page, enrichment/preferences.
**Goal:** Identify improvements for ease of onboarding, data minimization, visual polish, and flow.

> **Revision log:** Updated with verified corrections and three new P0 accelerators (OAuth pre-fill, Skip buttons, optimistic UI) that address the "smooth onboarding" goal more directly than data-cutting alone.

Surfaces covered: `LoginPage`, `EmailSignupPage`, `EmailVerifyPage`, `EmailLoginPage`, `ForgotPasswordPage`, `OAuthCallbackPage`, `OnboardingFlow`, `ProfilePage`, `EnrichmentPage`, their CSS in `App.css`, and the backend `profile_service.py` / `auth/schemas.py`. The chalkboard theme is well-applied everywhere. The real issues are **flow length, avoidable network round-trips, data we don't need, and a few UX legacies**. Recommendations are ordered by impact-to-effort.

---

## P0 — Quick wins (ship first, biggest ROI)

### 1. Cut the signup form by half

**File:** `llm-frontend/src/pages/EmailSignupPage.tsx`

- **Remove "Confirm password"** — modern pattern is a single password with show/hide toggle (add an eye icon). Confirm-password was a defense against typos before mobile keyboards had show-password; it's dead weight now.
- **Drop the 4-rule checklist** for length + number only (NIST SP 800-63B explicitly moved away from composition rules — they push users toward `Password1` patterns). Replace with a simple "12+ characters" hint and a strength meter.
- **Add "Show password"** toggle — kids mistype constantly on phones.

### 2. Fix the login screen — the broken button is the most prominent CTA

**File:** `llm-frontend/src/pages/LoginPage.tsx:37-59`

The disabled "Continue with Phone (coming soon)" button is rendered **first** — it's literally the most prominent call-to-action on a brand-new user's first screen, and it does nothing. That's the strongest version of the argument.

- **Remove the disabled phone button entirely.** If/when phone lands, add it back at the bottom.
- **Put "Continue with Google" first** — it's one tap, the easiest path for a parent setting up on a phone. Email should be secondary.

### 3. Collapse onboarding from 6 steps → 3

**File:** `llm-frontend/src/pages/OnboardingFlow.tsx`

Current: `name → preferred_name → age → grade → board → about → done` (6 input screens)
Recommended: **`preferred_name → grade → board → done` (3 input screens)**

| Step | Why keep/cut |
|------|---|
| `name` (full) | **Cut.** We only use `preferred_name` at runtime (`useStudentProfile.ts`). Full name adds nothing. |
| `preferred_name` | **Keep.** Rename the question to just: "What should we call you?" |
| `age` | **Cut.** Fully redundant with grade in the Indian school system (Grade N ≈ age N+5). Derive age server-side if anything needs it. |
| `grade` | **Keep**, but restrict the grid to supported grades (the typography principles doc scopes to Grade 3–8). Offering Grades 1–2 and 9–12 when the tutor isn't tuned for them is a false promise. |
| `board` | **Keep**, but default-select CBSE (most common in India) so users can one-tap through. Or move to profile as an optional refinement. |
| `about_me` | **Cut.** Violates the "minimal typing" principle. Data gets migrated into Enrichment anyway (see the migration banner in `EnrichmentPage.tsx:258-265` — the banner's existence is a tell that the field was in the wrong place). |

That's **2 screens + 1 confirmation screen** for first-time setup, down from 6 + 1.

### 4. Pre-fill from OAuth identity tokens

**Files:** `llm-frontend/src/contexts/AuthContext.tsx`, `llm-backend/auth/services/auth_service.py`

Google's ID token already contains `given_name`, `family_name`, `email`, and `picture` — but after Google sign-in we still put users through the `name → preferred_name` steps. Both are already known.

- **On the backend `/auth/sync`,** extract `given_name` from the ID token on first login and set it as both `name` and `preferred_name`.
- **On the frontend,** if `preferred_name` is already populated when `OnboardingFlow` mounts, **skip** the name screen entirely. Show a single "Hi Aanya, does that sound right?" confirmation with an edit affordance.

For the Google happy path, this collapses onboarding to **2 screens** (name confirmation + grade), which is the strongest smoothness lever available.

### 5. Add Skip buttons to optional steps

**File:** `llm-frontend/src/pages/OnboardingFlow.tsx`

`docs/principles/ux-design.md:25-27` already mandates "Skip for now" on optional steps, but onboarding has zero Skip buttons except on `about_me`. `board` has a sensible default (CBSE, ~70% of Indian students), so it should be skippable with that default applied.

- Add "Skip for now" on `board` (defaults to CBSE, editable later on Profile).
- If `about_me` survives the Item-3 cut, ensure its Skip button actually advances without penalty (it does today).

One-line UI change, disproportionate impact, doesn't require schema changes.

### 6. Optimistic UI in OnboardingFlow

**File:** `llm-frontend/src/pages/OnboardingFlow.tsx:31-52`

`updateProfile()` does an `await fetch()` between every screen and **blocks** the next screen on the response. On 4G that's ~6 × 200–500ms = 1–3 seconds of avoidable wait across the full flow.

Two options:

1. **Optimistic:** advance immediately, queue the `PUT /profile` in the background, surface errors as a non-blocking toast.
2. **Batched:** collect all fields in component state, send a single `PUT /profile` at the `done` step.

Option 2 is simpler and loses the "resumability" claim, but resumability on a 30-second flow is overkill — if a user abandons mid-flow they'll re-enter 3 fields, not 30. Prefer the batched approach.

### 7. Fix the silent auto-login failure after email verification

**Files:** `llm-frontend/src/pages/EmailSignupPage.tsx:39`, `llm-frontend/src/pages/EmailVerifyPage.tsx`

`EmailSignupPage` passes `password` through React Router state to the verify page, which calls `loginWithEmail` automatically after `confirmSignUp`. **If the user refreshes the verify page, the state is gone and auto-login fails silently** — they're left on a screen that says "Verifying…" forever, or bumped back to signup.

For a brand-new user, that first-minute experience becomes "wait, did I just lose my password?" — a smoothness issue, not just a cleanup nit.

- Persist briefly in `sessionStorage` (cleared after successful verify), **or**
- Don't promise auto-login — after `confirmSignUp`, route to `/login/email` with a "Verified! Log in now" state.

### 8. Trim the Profile page

**File:** `llm-frontend/src/pages/ProfilePage.tsx`

- **Remove "School name"** — it's optional, unused anywhere in learn/tutor flow, and just another field.
- **Replace "Edit Profile / Save Changes" toggle** with inline-on-focus editing (field becomes editable when tapped, auto-saves on blur with a small "saved" toast).
- **Collapse text + audio language** into one "Language" selector, with a single "Use a different language for audio" disclosure link that reveals the second field. 90% of users will want them the same.

### 9. Dead-surface cleanup

- **`PhoneLoginPage.tsx` and `OTPVerifyPage.tsx` are not orphaned — they're URL-reachable.** Both are routed in `llm-frontend/src/App.tsx:86-87` at `/login/phone` and `/login/phone/verify`, and `/auth/phone/provision` is called from `AuthContext.tsx:226`. Anyone with the URL can land on them; they just aren't reachable from the login screen. **Remove the routes, components, `AuthContext.sendOTP`/`verifyOTP` methods, and the backend endpoint together.** When phone ships, re-add deliberately.

---

## P1 — Medium effort, high polish

### 10. Subject-first onboarding

**Files:** `llm-frontend/src/pages/OnboardingFlow.tsx`, routing in `App.tsx`, `OnboardingGuard.tsx`

Rather than gate first-time users behind a wizard, let them **pick a subject first** (which implies grade for most content), then collect `board` inline only when it actually matters ("Which textbook — CBSE or ICSE?"). Onboarding becomes ~1 required screen ("What should we call you?") and everything else is just-in-time.

This is a **layout reshuffle, not a re-architecture** — the existing `SubjectSelect → ChapterSelect → TopicSelect` flow already exists. The change is relaxing `OnboardingGuard` for a single subject-pick screen and deferring `board` until it matters.

### 11. Add Change Password UI

Backend exists (`PUT /profile/password` per `docs/technical/auth-and-onboarding.md:81-84`) but there's no UI. Add a "Change password" button in the Account section of `ProfilePage.tsx` (email users only).

### 12. Add "Delete my account" / data export

Required for Indian DPDP compliance (enforced Sep 2025) and increasingly expected. Currently there's no user-facing path — only the admin endpoint `DELETE /auth/admin/user`.

### 13. Expose `focus_mode` toggle

Backend supports it, frontend has no control. Add it under a new "Session preferences" area on Profile (moved from enrichment) since it's a student-facing option, not parent-facing.

### 14. Replace the arbitrary 500ms delay in OAuth callback

**File:** `llm-frontend/src/pages/OAuthCallbackPage.tsx:31` — `setTimeout(complete, 500)` is a race-condition workaround. Drive it off a proper `useEffect` that awaits `userPool.getCurrentUser()` resolution, or remove the delay and retry on failure. Magic timeouts rot.

### 15. Preferred-name field = Lexend per typography principles

`docs/principles/typography.md:144` says *"Input value (what kid types) = Lexend Deca weight 600."* Current chalkboard input (`App.css:5841-5850`, `6237-6248`) uses `--font-body` (Inter). Flip the input font to Lexend on onboarding/profile to match the principle.

### 16. Loading / transition affordances in OnboardingFlow

`ux-design.md:21-23` ("Fast, Never Slow") mandates never leaving the student staring at a blank screen. `OnboardingFlow.tsx:46` shows a generic error string but no per-step skeleton / transition affordance. Add explicit transition states — even a simple cross-fade between steps signals "the app heard you."

---

## P2 — Strategic / longer-term

### 17. Rethink the Enrichment page from "form" to "conversation"

Current Enrichment (`EnrichmentPage.tsx`): 4 chip sections + parent notes + 2 session prefs = a lot of parent time. It's visually polished (chalkboard theme with gold accents), but the density is high.

Specific cuts:

- **Learning styles** (visual/structured/exploratory/contextual/narrative/kinesthetic) — the "learning styles" construct is **empirically debunked** (Pashler et al. 2008; Kirschner 2017). Parents guess; the tutor prompt gets low-signal input. Replace with a single free-text "Anything we should know about how [kid] learns best?" or drop entirely.
- **Attention span + pace preference** — parents will guess. These are better derived from actual session telemetry (completion rate per session length, idle time, skip rate). Ship as adaptive rather than declarative.
- **Keep:** interests (good LLM fuel for relatable examples), growth areas (tutor calibration), parent notes (highest-signal per unit of parent effort).

### 18. Adaptive vs declarative preferences

Session preferences, pace, attention span, even preferred explanation style — all of these can be **learned from actual usage** better than asked upfront. Ship a thin telemetry loop that updates the `kid_personalities` inputs continuously from behavioral signals.

### 19. Magic link or paste-detected verify code

A 6-digit code is still a typing step. Two options worth evaluating:

- **Magic link** (one-tap email link that completes verification) — supported by Cognito via the `CUSTOM_AUTH` flow.
- **Paste-detected auto-fill** — if `navigator.clipboard` contains a 6-digit number when `EmailVerifyPage` mounts, offer a "Paste code" button that fills all six boxes at once.

### 20. Add Apple Sign In (iOS trajectory)

Given the chalkboard redesign and mobile-first principle, Apple Sign In will matter for iOS users (and Apple requires it in-store if you offer Google). Preparation now is cheap.

---

## Summary: proposed data footprint

| Field | Today | Proposed |
|---|---|---|
| `name` (full) | collected | **drop** |
| `preferred_name` | collected | keep (pre-fill from OAuth `given_name`) |
| `age` | collected | **drop (derive)** |
| `grade` | collected | keep |
| `board` | collected upfront | keep (default CBSE, skippable) |
| `school_name` | collected (optional) | **drop** |
| `about_me` | collected (optional) | **drop (redundant with enrichment parent_notes)** |
| `learning_styles` | collected | **drop (debunked)** |
| `attention_span` / `pace_preference` | collected | **drop (derive from telemetry)** |
| `interests` / `growth_areas` | collected | keep |
| `parent_notes` | collected | keep |
| confirm password | required | **drop** |
| `focus_mode` | backend-only | expose |
| change password | backend-only | expose |
| delete account | missing | add |

---

## Time-to-first-value estimate

Rough back-of-envelope (not measured):

- **Today:** 6 onboarding screens × ~5s each + 4 signup fields × ~3s each ≈ **42s** of required interaction before first learning moment, plus network-block time of ~1–3s.
- **After P0 (email path):** 3 onboarding screens × ~5s + 2 signup fields × ~3s ≈ **21s**, no network-block time (batched save).
- **After P0 (Google path, with OAuth pre-fill):** 2 onboarding screens × ~5s ≈ **10s**, with **zero typed characters**.

So the Google happy path becomes roughly: **Tap Google → confirm name → pick grade → start.** ~4 taps, 0 typed characters.

The real win is on the Google path — anyone arriving via email will still see a meaningful drop but not a dramatic one.

---

## Suggested sequencing

1. **Week 1 (P0 basics):** Items 1–3, 8, 9. Form-trimming + route cleanup. No schema changes.
2. **Week 2 (P0 smoothness):** Items 4–7. OAuth pre-fill, Skip buttons, optimistic UI, verify-page fix. Bigger behavioral wins.
3. **Week 3 (P1):** Items 10–16. Subject-first flow + expose backend-only features (change password, delete account, focus_mode).
4. **Backlog (P2):** Items 17–20. Require design + data work.

If sequencing has to pick one thing to ship first, **#4 (OAuth pre-fill)** is the single highest-leverage change — it converts the Google happy path from "sign up, verify, onboard" into "sign up, confirm, go."
