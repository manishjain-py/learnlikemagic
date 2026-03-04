# Auth & Onboarding

How students sign up, log in, and set up their profile.

---

## Login Options

Students can sign in using any of these methods:

- **Email** — Tap "Continue with Email", enter your email and password
- **Google** — Tap "Continue with Google" to sign in with your Google account
- **Phone** — Listed on the login screen as "coming soon" (not yet active)

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
Phone-based signup and login are not yet available. The button on the login screen is currently disabled.

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
2. **What should we call you?** — Enter your preferred name (how the tutor will greet you). Pre-filled with the first word of your full name.
3. **How old are you?** — Enter your age (5-18)
4. **What grade are you in?** — Tap your grade from a grid of 1-12
5. **What's your school board?** — Tap your board (CBSE, ICSE, State Board, or Other)
6. **Tell us about yourself** — Optional free-text about interests and learning style. If you enter text, the button says "Save & Continue"; if left empty, it says "Continue". You can also skip entirely with "Skip for now"
7. **You're all set!** — Personalized confirmation screen ("You're all set, {preferred name}!") with a "Start Learning" button

Progress dots at the top show which step you're on (6 dots for the 6 input steps). Each step saves automatically — even if you leave mid-flow, your progress is kept. Onboarding is marked complete once your name, age, grade, and board are all filled in.

---

## Profile & Settings

After onboarding, you can view and update your profile from the Profile & Settings page (accessible from the user menu in the top-right corner):

- **View mode** — Shows all your profile fields in read-only format, plus your sign-in method (email, phone, or Google) and account details
- **Edit mode** — Tap "Edit Profile" to make changes, then "Save Changes" to confirm or "Cancel" to discard. A success message appears after saving.

Editable fields:
- Name
- Preferred name (how the tutor addresses you)
- Age
- Grade (dropdown selector)
- Board (dropdown selector)
- School name (optional)

### Learning Preferences

These settings control your tutoring experience:

- **Focus Mode** — A toggle that shows tutor responses in full-screen with audio, designed for younger students
- **Text language** — Choose between English, Hindi, or Hinglish (Hindi + English) for written responses
- **Audio language** — Choose between English, Hindi, or Hinglish for spoken responses

### Enrichment Profile

Below the profile fields, there is a link to the enrichment page ("Help us know {name} better"). This is a separate page where parents can provide additional information about their child to personalize the tutoring experience. See the Enrichment Profile section below.

### Account Info

The profile page shows which sign-in method you used (email, phone, or Google) along with your email or phone number.

---

## Enrichment Profile

The enrichment page helps parents provide detailed information about their child so the tutor can adapt its approach. It is accessed from the Profile & Settings page.

### What You Fill In

Four optional sections, each with pre-set options to tap:

1. **What does {name} enjoy doing?** — Interests and hobbies (cricket, drawing, gaming, coding, etc.). You can also add custom interests.
2. **How {name} learns best** — Learning styles (visual, step-by-step, exploratory, real-life examples, stories, hands-on)
3. **What motivates {name}** — Motivations (challenges, praise, real-life relevance, creativity, achievements, helping others)
4. **Challenges** — Growth areas (staying focused, showing work, word problems, memorizing, etc.). You can also add custom entries.

A progress bar shows how many of the 4 sections you have filled.

### Additional Details

- **Anything else we should know?** — A free-text box (up to 1000 characters) for any extra notes about the child's learning style, personality, or preferences
- **Session Preferences** — Attention span (short, medium, or long) and pace preference (slow, balanced, or fast)

### About Me Migration

If you previously entered text in the "about me" field during onboarding, the enrichment page offers to copy that text into the open-ended notes box as a starting point.

### Personality Profile

After saving enrichment data, the system automatically generates a personality profile for the child. This appears as a card at the bottom of the page showing:

- How the tutor will teach
- Example themes the tutor will use
- What motivates the child
- What the tutor will focus on

The personality profile regenerates automatically when you update enrichment data or certain profile fields (name, preferred name, age, grade, board).

---

## Navigation & User Menu

Once logged in, the app shows a navigation bar at the top with:

- **Home button** — Returns to the subject selection page
- **App name** — "Learn Like Magic" in the center
- **User menu** (top-right icon) — Opens a dropdown with: Profile, My Sessions, My Report Card, and Log Out

---

## Key Details

- Both active auth methods (email, Google) lead to the same app experience. Phone login is listed but not yet active.
- The login screen includes a "By continuing, you agree to our Terms of Service" notice at the bottom
- The onboarding wizard only appears once — after completing it, you go straight to the learning pages on future logins
- Profile data (grade, board) is used to personalize the tutoring experience and show relevant curriculum
- The preferred name is used by the tutor to greet the student
- OTP and email verification codes use a 6-digit input with auto-submit — no need to tap a button after entering all digits
- Resend buttons have a 30-second cooldown to prevent spamming
- Language and focus mode preferences affect how the tutor delivers content
- The enrichment profile is entirely optional and designed for parents to fill in
