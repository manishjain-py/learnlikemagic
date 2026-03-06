# Auth & Onboarding

How students sign up, log in, and set up their profile.

---

## Login Options

Students can sign in using any of these methods:

- **Email** — Tap "Continue with Email", enter your email and password
- **Google** — Tap "Continue with Google" to sign in with your Google account
- **Phone** — Currently disabled (shown as "coming soon" on the login screen)

The login screen shows one button per method. Tap to choose.

---

## Signup Flow

### Email Signup
1. Tap "Continue with Email", then "Don't have an account? Sign up"
2. Enter your email and create a password
3. Password requirements are shown as you type — at least 8 characters, one lowercase letter, one uppercase letter, one number
4. Confirm your password by typing it again
5. Check your email for a 6-digit verification code
6. Enter the code (one digit per box — it submits automatically when all 6 are filled)
7. You're signed in automatically after verification

### Google Signup
1. Tap "Continue with Google"
2. You'll be redirected to Google to sign in
3. After signing in, you're redirected back and signed in automatically

### Phone Signup
Phone signup is not currently available. The button appears on the login screen but is disabled.

---

## Email Verification

New email accounts need to verify their email address:
1. After signing up, you'll see a verification screen showing which email the code was sent to
2. Enter the 6-digit code, one digit per box — it submits automatically when all digits are filled
3. If the code doesn't arrive, wait for the cooldown timer (30 seconds) and tap "Resend code"
4. After verification, you're logged in automatically

---

## Forgot Password

1. Tap "Forgot password?" on the email login screen
2. Enter your email address and tap "Send Reset Code"
3. Check your email for a reset code
4. Enter the code and your new password (at least 8 characters) in the form that appears
5. After resetting, tap "Go to Login" to sign in with your new password

---

## Onboarding Wizard

First-time users go through a short onboarding flow before they can start learning:

1. **What's your name?** — Enter your full name
2. **What should we call you?** — Enter your preferred name (pre-filled with the first word of your name). This is how the tutor will greet you.
3. **How old are you?** — Enter your age (5-18)
4. **What grade are you in?** — Tap your grade from a grid of 1-12
5. **What's your school board?** — Tap your board (CBSE, ICSE, State Board, or Other)
6. **Tell us about yourself** — Optional free-text about interests and learning style. If you enter text, the button says "Save & Continue"; if left empty, it says "Continue". You can also skip entirely with "Skip for now"
7. **You're all set!** — Personalized confirmation screen ("You're all set, {preferred name}!") with a "Start Learning" button

Progress dots at the top show which step you're on (six dots for the six input steps). Each step saves automatically — even if you leave mid-flow, your progress is kept. Onboarding is marked complete once your name, age, grade, and board are all filled in.

---

## Profile Management

After onboarding, you can view and update your profile from the profile page (accessible via the user menu in the top navigation bar).

- **View mode** — Shows all your profile fields in read-only format, plus your sign-in method (email, phone, or Google) and account details
- **Edit mode** — Tap "Edit Profile" to make changes, then "Save Changes" to confirm or "Cancel" to discard. A success message appears after saving.

Editable fields:
- Name
- Preferred name (what the tutor calls you)
- Age
- Grade (dropdown selector)
- Board (dropdown selector)
- School name (optional)

Settings:
- **Focus Mode** — Toggle on/off. Shows tutor responses in full-screen with audio, designed for younger students. On by default.
- **Text language** — Choose English, Hindi, or Hinglish (Hindi + English)
- **Audio language** — Choose English, Hindi, or Hinglish (Hindi + English)

The profile page also links to the enrichment profile (see below).

---

## Enrichment Profile

The enrichment profile is a parent-facing form accessible from the profile page ("Help us know {name} better"). It collects additional information to personalize the tutoring experience. All sections are optional.

### Sections

1. **Interests** — What does the child enjoy doing? Choose from a list of activities (cricket, drawing, gaming, etc.) or add custom entries
2. **Learning styles** — How the child learns best (visual, structured, exploratory, contextual, narrative, hands-on)
3. **Motivations** — What motivates the child (challenges, praise, relevance, creativity, achievements, helping others)
4. **Challenges** — What the child finds difficult (focus, showing work, word problems, memorizing, etc.) with custom entries
5. **Open-ended notes** — Free-text field for any additional tips from the parent (up to 1000 characters)
6. **Session preferences** — Attention span and pace preference settings

A progress bar shows how many of the four main sections (interests, learning styles, motivations, challenges) have been filled.

If the student previously entered an "about me" during onboarding, a banner offers to copy that text into the open-ended notes as a starting point.

### Personality Card

After saving enrichment data, the system automatically generates a personalized learning profile. This appears as a card at the bottom of the enrichment page showing:
- How the tutor will teach
- What types of examples the tutor will use
- What motivates the student
- What the tutor will focus on

The card updates when enrichment data changes. If generation fails, a retry button is available.

---

## Navigation & User Menu

The top navigation bar (visible on all learning screens) includes a user menu with:
- **Profile** — Go to profile and settings
- **My Sessions** — View session history
- **My Report Card** — View progress reports
- **Log Out** — Sign out of your account

---

## Key Details

- Email and Google auth methods lead to the same app experience
- The login screen includes a "By continuing, you agree to our Terms of Service" notice at the bottom
- The onboarding wizard only appears once — after completing it, you go straight to the learning screens on future logins
- Profile data (grade, board) is used to personalize the tutoring experience and show relevant curriculum
- Email verification codes use a 6-digit input with auto-submit — no need to tap a button after entering all digits
- Resend buttons have a 30-second cooldown to prevent spamming
- All pages except onboarding require onboarding to be completed before access
