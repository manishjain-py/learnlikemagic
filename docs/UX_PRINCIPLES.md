# UX Principles — LearnLikeMagic

The primary users are **students (kids)**. Every screen, every interaction must be effortless. These principles apply to **all features** across the app.

---

## Core Principles

| # | Principle | What It Means In Practice |
|---|-----------|--------------------------|
| 1 | **One thing per screen** | Each screen has one clear purpose. Don't cram multiple actions into one view. Big, clear buttons. Focused flows. |
| 2 | **Minimal typing** | Prefill what you can. Use pickers, dropdowns, and selectors over free-text where possible. Auto-advance inputs (e.g., OTP fields). Reduce keystrokes at every step. |
| 3 | **Friendly language** | No jargon, no technical terms. Say "What's your name?" not "Enter display name". Say "How old are you?" not "Date of birth". Write like you're talking to the student. |
| 4 | **Forgiving inputs** | Accept messy input gracefully. Phone numbers with or without spaces/dashes should all work. Show inline validation as they type, not error popups after submit. Never make the student feel like they did something wrong. |
| 5 | **Fast** | No interaction should feel slow. Loading spinners should not exceed 2 seconds. If something takes longer, show progress or a friendly message. Aim for perceived instant response. |
| 6 | **Skippable where possible** | If a field or step is optional, make "Skip for now" a clear, prominent button — not a tiny link. Never block the student from their goal longer than necessary. |
| 7 | **Mobile-first** | Design for phone screens first. Big tap targets (min 44px), no tiny links, no hover-dependent interactions. Test on small screens before large ones. |
| 8 | **Warm and encouraging** | The app should feel like a friendly tutor, not software. "You're all set! Let's start learning." not "Account created successfully." Celebrate progress. Be kind on errors ("Hmm, that didn't work. Let's try again."). |
| 9 | **Consistent** | Same patterns everywhere. If "back" is top-left on one screen, it's top-left on all screens. If buttons are blue, they're always blue. Predictability builds trust. |
| 10 | **Accessible** | Sufficient color contrast, readable font sizes (min 16px body text), screen-reader friendly labels. Don't rely on color alone to convey meaning. |

---

## Applying These Principles

When building any new feature, use this as a checklist:

- [ ] Can a student figure out what to do within 3 seconds of seeing the screen?
- [ ] Is there only one primary action per screen?
- [ ] Is the language something a 10-year-old would understand?
- [ ] Does it work well on a phone?
- [ ] Are error states helpful and kind, not scary?
- [ ] Can optional steps be skipped without hunting for a tiny link?
- [ ] Does the feedback feel warm (not robotic)?
