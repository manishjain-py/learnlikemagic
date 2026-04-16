# Chalkboard Mockups

Static HTML mockups for the kid-friendly UI redesign.

## View

Open `index.html` in any modern browser. No build step, no server required.

```bash
# macOS
open llm-frontend/mockups/chalkboard/index.html

# Or start a quick server if CORS/iframe issues appear
cd llm-frontend/mockups/chalkboard && python3 -m http.server 8080
# then open http://localhost:8080
```

## Files

| File | Screen |
|---|---|
| `index.html` | Mockup navigator (grid or single view) |
| `tokens.css` | Design tokens — chalkboard palette, fonts, spacing |
| `components.css` | Shared components — frame, board, tray, pills, chalk text |
| `login.html` | Auth entry (chalk logo, google/email/phone) |
| `subject-select.html` | Subject picker with color-coded spines |
| `learning-card.html` | Explanation card — matches the reference image |
| `check-in.html` | Pick-one check-in in correct-answer state |
| `session-complete.html` | End-of-session celebration |
| `profile.html` | Profile with parchment pinned notes |

## Scope

These are review artifacts — not production code. Do not import from `mockups/` into the real app.

## What to review

1. Does the **learning card** faithfully capture the reference chalkboard?
2. Does the **dark theme** feel readable, not oppressive?
3. Do the **subject colors** (green/navy/brick/ochre/plum) feel distinct without fighting each other?
4. Is the **typography mix** (Caveat for headings, Inter for body, JetBrains Mono for formulas) right?
5. Do the **chalk doodles** feel warm or cluttered?
6. Is the **chalk tray** a delight or a distraction?
