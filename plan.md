# Plan: Unify Card Design — Remove Chat View, Make Everything Cards

## Summary

Promote the focus carousel from an overlay to THE primary view for all non-exam tutoring sessions. Explanation cards (card_phase) and interactive messages all render through the same card-based UI. Remove the chat bubble view and virtual teacher toggle entirely.

## Current State

Three separate view modes in `ChatSession.tsx`:
1. **ExplanationViewer** — card_phase pre-computed explanation cards (separate component)
2. **Virtual Teacher** — single focused message with markdown, TTS
3. **Chat bubbles** + **Focus Carousel overlay** — message list with optional full-screen carousel

## Target State

One unified card view for all non-exam modes:
- **Card phase**: Explanation cards render as carousel slides (same visual style as focus cards)
- **Interactive phase**: Each tutor message is a card slide, student replies shown inline
- No chat bubbles, no VT toggle, no overlay — the carousel IS the view
- Exam mode unchanged

## Implementation Steps

### Step 1: Convert focus carousel from overlay to inline view

**File: `ChatSession.tsx`**
- Remove `position: fixed` and `z-index: 100` from focus carousel — make it a normal flex child of `.chat-container`
- Remove the close/exit button and `focusDismissedRef` logic
- Always render the carousel for non-exam modes (no more conditional on `focusCardIdx !== null`)
- Remove `handleTeacherDoubleTap` (no longer needed to "open" carousel)

**File: `App.css`**
- `.focus-carousel`: change from fixed overlay to `flex: 1; display: flex; flex-direction: column; overflow: hidden`
- Remove `z-index: 100`, `position: fixed`, `top/left/right/bottom: 0`

### Step 2: Render card_phase explanation cards as carousel slides

**File: `ChatSession.tsx`**
- When `sessionPhase === 'card_phase'`, the carousel renders explanation cards as slides instead of message-based focus cards
- Create a unified `carouselSlides` memo that:
  - In card_phase: maps `explanationCards[]` → slides with type badge, title, content, visual
  - In interactive: maps tutor messages → slides (current `focusCards` logic)
- Each explanation card slide uses the same `.focus-slide` / `.focus-tutor-msg` styling
- Card type badge (concept/example/visual/analogy/summary) shown at top of slide
- Progress counter in header: "1/5" for both phases

### Step 3: Unify the input/action area at bottom

**File: `ChatSession.tsx`**
- Single bottom area that changes based on phase:
  - **card_phase, not last card**: Back / Next buttons
  - **card_phase, last card**: "I understand!" / "Explain differently" buttons
  - **interactive**: text input + mic + send (current `.focus-input-area`)
  - **loading**: typing indicator
  - **complete**: nothing (summary takes over)
- Extract one `<InputArea>` section to avoid the current 4 duplicated input forms

### Step 4: Move audio button into main nav

**File: `ChatSession.tsx`**
- The focus carousel header had its own audio button — move this to the main `<nav>` actions area
- Add card counter ("1/5") to the nav as well
- Remove the separate `.focus-header` entirely since the main nav already has breadcrumb

### Step 5: Remove old view modes

**File: `ChatSession.tsx`**
- Remove `ExplanationViewer` import and its rendering block
- Remove virtual teacher view block (the `virtualTeacherOn` conditional)
- Remove the `.messages` chat bubble rendering block
- Remove `virtualTeacherOn` state + toggle button from nav
- Remove `focusDismissedRef`, `lastTapRef`, `handleTeacherDoubleTap`
- Remove conditions gating focus carousel display

### Step 6: Handle card_phase → interactive transition

**File: `ChatSession.tsx`**
- When user clicks "I understand!" (card action 'clear'):
  - `sessionPhase` transitions from 'card_phase' to 'interactive'
  - Carousel seamlessly switches from explanation card slides to message slides
  - First message slide contains the transition message from backend
- When "Explain differently" is clicked:
  - Swap explanation cards in the carousel (same logic as current `handleCardAction('explain_differently')`)
  - Reset carousel to first slide

### Step 7: Auto-play TTS on new slides

**File: `ChatSession.tsx`**
- In card_phase: auto-play TTS when navigating to a new explanation card (read card content)
- In interactive: auto-play TTS when new tutor message arrives (existing logic)
- Single audio play/pause button in nav works for both phases

### Step 8: Clean up CSS

**File: `App.css`**
- Remove/comment out: `.messages`, `.message.teacher`, `.message.student`, `.virtual-teacher-view`, `.vt-typing-indicator`, `.vt-input-area`
- Keep: `.focus-carousel` (adapted), `.focus-slide`, `.focus-tutor-msg`, `.focus-input-area`, `.focus-track`
- Keep: `.explanation-card-type`, `.explanation-card-title` styles (reused in card_phase slides)
- Adapt `.explanation-nav-btn` styles for the unified bottom action area

### Step 9: Clean up dead code

- Delete `ExplanationViewer.tsx` component file
- Remove unused state variables: `virtualTeacherOn`, `focusDismissedRef`, `lastTapRef`
- Remove unused CSS classes

## What Stays Unchanged

- Exam mode (its own card-like Q&A UI)
- Session completion/summary view
- Feedback modal
- DevTools drawer
- TTS/audio playback logic
- Streaming text display
- WebSocket communication
- Backend API (no backend changes needed)
- Visual explanations (PixiJS) — just rendered inside card slides

## Key Design Decisions

1. **Focus carousel becomes the primary view** — it already has the right UX (swipe, one-card-at-a-time, large text). We promote it rather than building something new.
2. **Unified slide model** — a memo (`carouselSlides`) abstracts over both explanation cards and message-based cards, so the carousel renderer doesn't care about the source.
3. **No user preference needed** — everyone gets the card view. Removes complexity of VT toggle and focus_mode pref.
4. **Exam mode untouched** — it has its own distinct UX that works well as-is.

## Files Modified

| File | Change |
|------|--------|
| `llm-frontend/src/pages/ChatSession.tsx` | Major refactor — unified card view |
| `llm-frontend/src/App.css` | Remove old styles, adapt focus carousel |
| `llm-frontend/src/components/ExplanationViewer.tsx` | **DELETE** |
