# Auth, Onboarding, Profile & Preferences — Review

**Date:** 2026-04-23
**Scope:** Sign up, sign in, onboarding wizard, profile page, enrichment/preferences.
**Goal:** Identify improvements for ease of onboarding, data minimization, visual polish, and flow.

Surfaces covered: `LoginPage`, `EmailSignupPage`, `EmailVerifyPage`, `EmailLoginPage`, `ForgotPasswordPage`, `OAuthCallbackPage`, `OnboardingFlow`, `ProfilePage`, `EnrichmentPage`, their CSS in `App.css`, and the backend `profile_service.py` / `auth/schemas.py`. The chalkboard theme is well-applied everywhere. The real issues are **flow length, data we don't need, and a few UX legacies**. Recommendations below are ordered by impact-to-effort.

---

## P0 — Quick wins (ship first, biggest ROI)

### 1. Cut the signup form by half

**File:** `llm-frontend/src/pages/EmailSignupPage.tsx`

- **Remove "Confirm password"** — modern pattern is a single password with show/hide toggle (add an eye icon). Confirm-password was a defense against typos before mobile keyboards had show-password; it's dead weight now.
- **Drop the 4-rule checklist** for length + number only (NIST SP 800-63B explicitly moved away from composition rules — they push users toward `Password1` patterns). Replace with a simple "12+ characters" hint and a strength meter.
- **Add "Show password"** toggle — kids mistype constantly on phones.

### 2. Fix the login screen order

**File:** `llm-frontend/src/pages/LoginPage.tsx:37-59`

- **Remove the disabled "Continue with Phone (coming soon)" button** — it's visual noise and a broken promise. If/when phone lands, bring it back.
- **Put "Continue with Google" first** — it's one tap, the easiest path for a parent setting up on a phone. Email should be secondary.

### 3. Collapse onboarding from 6 steps → 3

**File:** `llm-frontend/src/pages/OnboardingFlow.tsx`

Current: `name → preferred_name → age → grade → board → about → done` (6 input screens)
Recommended: **`preferred_name → grade → board → done` (3 input screens)**

| Step | Why keep/cut |
|------|---|
| `name` (full) | **Cut.** We only use `preferred_name` at runtime (`useStudentProfile.ts`). Full name adds nothing. |
| `preferred_name` | **Keep.** Rename the question to just: "What should we call you?" |
| `age` | **Cut.** Fully redundant with grade in the Indian school system (Grade N ≈ age N+5). Derive age server-side if it's needed for anything. |
| `grade` | **Keep**, but restrict the grid to supported grades (the typography principles doc scopes to Grade 3–8). Offering Grades 1–2 and 9–12 when the tutor isn't tuned for them is a false promise. |
| `board` | **Keep**, but default-select CBSE (most common in India) so users can one-tap through. Or move to profile as an optional refinement. |
| `about_me` | **Cut.** Violates the "minimal typing" principle. Data gets migrated into Enrichment anyway (see the migration banner in `EnrichmentPage.tsx:258-265` — the fact that this banner exists is a tell that the field was in the wrong place). |

That's **2 screens + 1 confirmation screen** for first-time setup, down from 6 + 1.

### 4. Trim the Profile page

**File:** `llm-frontend/src/pages/ProfilePage.tsx`

- **Remove "School name"** — it's optional, unused anywhere in learn/tutor flow, and just another field.
- **Replace "Edit Profile / Save Changes" toggle** with inline-on-focus editing (field becomes editable when tapped, auto-saves on blur with a small "saved" toast).
- **Collapse text + audio language** into one "Language" selector, with a single "Use a different language for audio" disclosure link that reveals the second field. 90% of users will want them the same.

### 5. Small code / dead-surface cleanup

- `PhoneLoginPage.tsx` and `OTPVerifyPage.tsx` are orphaned (login screen can't reach them). Either delete or add a `TODO:remove-when-phone-ships` comment. Same for the `/auth/phone/provision` backend endpoint — currently unreachable.
- `EmailSignupPage.tsx:39` passes `password` through React Router state to the verify page. If the user refreshes the verify page, the auto-login after `confirmSignUp` fails silently. Either persist briefly in `sessionStorage`, or don't promise auto-login and just drop them on `/login/email` with a "Verified! Log in now" state.

---

## P1 — Medium effort, high polish

### 6. Add Change Password UI

Backend exists (`PUT /profile/password` per `docs/technical/auth-and-onboarding.md:81-84`) but there's no UI. Add a "Change password" button in the Account section of `ProfilePage.tsx` (email users only).

### 7. Add "Delete my account" / data export

Required for Indian DPDP compliance (enforced Sep 2025) and increasingly expected. Currently there's no user-facing path — only the admin endpoint `DELETE /auth/admin/user`.

### 8. Expose `focus_mode` toggle

Backend supports it, frontend has no control. Add it under a new "Session preferences" area on Profile (moved from enrichment) since it's a student-facing option, not parent-facing.

### 9. Replace the arbitrary 500ms delay in OAuth callback

**File:** `llm-frontend/src/pages/OAuthCallbackPage.tsx:31` — `setTimeout(complete, 500)` is a race-condition workaround. Drive it off a proper `useEffect` that awaits `userPool.getCurrentUser()` resolution, or remove the delay and retry on failure. Magic timeouts rot.

### 10. Preferred-name field = Lexend per typography principles

`docs/principles/typography.md:144` says *"Input value (what kid types) = Lexend Deca weight 600."* Current chalkboard input (`App.css:5841-5850`, `6237-6248`) uses `--font-body` (Inter). Flip the input font to Lexend on onboarding/profile to match the principle.

---

## P2 — Strategic / longer-term

### 11. Rethink the Enrichment page from "form" to "conversation"

Current Enrichment (`EnrichmentPage.tsx`): 4 chip sections + parent notes + 2 session prefs = a lot of parent time. It's visually polished (chalkboard theme with gold accents), but the density is high.

Specific cuts:

- **Learning styles** (visual/structured/exploratory/contextual/narrative/kinesthetic) — the "learning styles" construct is **empirically debunked** (Pashler et al. 2008; Kirschner 2017). Parents guess; the tutor prompt gets low-signal input. Replace with a single free-text "Anything we should know about how [kid] learns best?" or drop entirely.
- **Attention span + pace preference** — parents will guess. These are better derived from actual session telemetry (track completion rate per session length, idle time, skip rate). Ship as adaptive rather than declarative.
- **Keep:** interests (good LLM fuel for relatable examples), growth areas (tutor calibration), parent notes (highest-signal per unit of parent effort).

### 12. Unify onboarding with first session

Why ask grade/board on a separate screen before the kid sees anything interesting? Let them **pick a subject first** (which implies grade for most content), then collect board inline when it actually matters ("Which textbook — CBSE or ICSE?"). Onboarding becomes 1 screen: "What should we call you?" and everything else is just-in-time.

### 13. Adaptive vs declarative preferences

Session preferences, pace, attention span, even preferred explanation style — all of these can be **learned from actual usage** better than asked upfront. Ship a thin telemetry loop that updates the `kid_personalities` inputs continuously from behavioral signals.

### 14. Add Apple Sign In (iOS trajectory)

Given the chalkboard redesign and mobile-first principle, Apple Sign In will matter for iOS users (and Apple requires it in-store if you offer Google). Preparation now is cheap.

---

## Summary: proposed data footprint

| Field | Today | Proposed |
|---|---|---|
| `name` (full) | collected | **drop** |
| `preferred_name` | collected | keep |
| `age` | collected | **drop (derive)** |
| `grade` | collected | keep |
| `board` | collected upfront | keep (default CBSE, editable) |
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

**Net result:** first-time user goes from "sign up form with 3 fields + 4-rule checklist → verify code → 6 onboarding steps" to "sign up form with 2 fields → verify code → 3 onboarding steps." Estimated **~40% less time to first learning moment**, and the app stops collecting fields it doesn't use.

---

## Suggested sequencing

1. **Week 1 (P0):** Items 1–5. All contained, no schema changes, ~1–2 days each.
2. **Week 2 (P1):** Items 6–10. Touch backend-exposed features and typography.
3. **Backlog (P2):** Items 11–14. Require design + data work.

Start with **#3 (collapse onboarding)** — biggest user impact, well-contained in one file, no backend schema change needed (dropped fields just go unused; server-side `onboarding_complete` auto-flag still works after adjusting the "required" set).
