# Plan: Unify Card Design — Remove Chat View, Make Everything Cards

> **Note:** This plan replaces the previous PixiJS visual explanation plan. The PixiJS work
> (LLM-generated Pixi.js visuals) has already been implemented and merged in earlier PRs.
> This plan focuses solely on unifying the frontend tutoring UI.

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

### Step 1: Define a unified `Slide` data model

**File: `ChatSession.tsx`**

Before touching any UI, create a single `Slide` interface that represents both explanation cards and interactive messages:

```typescript
interface Slide {
  id: string;                          // Stable ID for audio tracking (e.g., "card-0", "msg-2")
  type: 'explanation' | 'message';     // Source type
  content: string;                     // Markdown content (card content or tutor message)
  title?: string;                      // Explanation card title (null for messages)
  cardType?: string;                   // 'concept' | 'example' | 'visual' | 'analogy' | 'summary'
  visual?: string | null;              // ASCII visual from explanation card
  visualExplanation?: VisualExplanationType | null;  // PixiJS visual
  studentResponse?: string | null;     // Student reply (for message slides)
  audioText?: string | null;           // TTS-optimized text
}
```

Create a unified `carouselSlides` memo:
- In `card_phase`: maps `explanationCards[]` → Slide[] with `type: 'explanation'`, stable IDs like `"card-0"`, `"card-1"`
- In `interactive`: maps tutor messages → Slide[] with `type: 'message'`, stable IDs like `"msg-0"`, `"msg-2"` (using message array index)
- This replaces the current `focusCards` memo

**Audio tracking migration**: Replace `playingMsgIdx: number | null` with `playingSlideId: string | null`. Audio play/stop functions reference slide IDs instead of message array indices, so merging explanation cards and messages into one carousel doesn't break TTS state.

### Step 2: Convert focus carousel from overlay to inline view

**File: `ChatSession.tsx`**
- Remove the overlay rendering condition (`focusCardIdx !== null && ...`)
- Always render the carousel as a direct child of `.chat-container` for non-exam modes
- Remove the close/exit button and `focusDismissedRef` logic
- Remove `handleTeacherDoubleTap` (no longer needed to "open" carousel)

**File: `App.css`**
- `.focus-carousel`: change from fixed overlay to `flex: 1; display: flex; flex-direction: column; overflow: hidden`
- Remove `z-index: 100`, `position: fixed`, `top/left/right/bottom: 0`

**Container-relative sizing fix** (addresses reviewer finding #1):
- Replace `window.innerWidth` in swipe transform calculations (lines 867, 887, 1563) with `containerRef.current.clientWidth`
- Add a `containerRef = useRef<HTMLDivElement>(null)` on the `.focus-carousel` div
- In CSS: change `.focus-slide` from `flex: 0 0 100vw; width: 100vw` to `flex: 0 0 100%; width: 100%`
- This ensures slides match the container width, not the viewport, on desktop/tablet layouts

### Step 3: Add streaming slide support

**File: `ChatSession.tsx`** (addresses reviewer finding #2)

The current streaming text renderer lives inside the `.messages` block we're deleting. Add streaming support to the carousel:

- When `streamingText` is non-empty, append a **provisional streaming slide** to `carouselSlides`:
  ```typescript
  // In carouselSlides memo:
  if (streamingText) {
    slides.push({
      id: 'streaming',
      type: 'message',
      content: streamingText,
      // no studentResponse, no audioText yet
    });
  }
  ```
- The carousel auto-advances to this streaming slide (same as current auto-advance logic)
- When streaming completes and the real message arrives, the provisional slide is replaced by the final message slide
- Typing indicator: when `loading && !streamingText`, show a typing indicator inside the last slide instead of as a separate chat bubble

### Step 4: Render card_phase explanation cards as carousel slides

**File: `ChatSession.tsx`**
- The `carouselSlides` memo (from Step 1) already maps explanation cards to slides
- Each slide renders using the same `.focus-slide` / `.focus-tutor-msg` styling
- For `type: 'explanation'` slides, additionally render:
  - Card type badge at top (concept/example/visual/analogy/summary) using `.explanation-card-type` styles
  - Title using `.explanation-card-title` styles
  - ASCII visual using `.explanation-card-visual` styles (if present)
- Progress counter in nav: "1/5" works for both phases (just uses `carouselSlides.length`)

### Step 5: Unify the input/action area at bottom

**File: `ChatSession.tsx`**
- Single bottom area that changes based on phase:
  - **card_phase, not last card**: Back / Next buttons
  - **card_phase, last card**: "I understand!" / "Explain differently" buttons
  - **interactive**: text input + mic + send (current `.focus-input-area`)
  - **loading**: typing indicator
  - **complete**: nothing (summary takes over)
- Extract one `<BottomActionArea>` inline section to replace the current 4 duplicated input forms

### Step 6: Move audio button + counter into main nav

**File: `ChatSession.tsx`**
- The focus carousel header had its own audio button — move this to the main `<nav>` actions area
- Add card counter ("1/5") to the nav as well
- Audio button uses `playingSlideId` (from Step 1) instead of `playingMsgIdx`
- Remove the separate `.focus-header` entirely since the main nav already has breadcrumb

### Step 7: Remove old view modes

**File: `ChatSession.tsx`**
- Remove `ExplanationViewer` import and its rendering block
- Remove virtual teacher view block (the `virtualTeacherOn` conditional)
- Remove the `.messages` chat bubble rendering block
- Remove `virtualTeacherOn` state + toggle button from nav
- Remove `focusDismissedRef`, `lastTapRef`, `handleTeacherDoubleTap`
- Remove conditions gating focus carousel display

### Step 8: Handle card_phase → interactive transition

**File: `ChatSession.tsx`**
- When user clicks "I understand!" (card action 'clear'):
  - `sessionPhase` transitions from 'card_phase' to 'interactive'
  - `carouselSlides` memo automatically switches from explanation slides to message slides
  - First message slide contains the transition message from backend
  - Reset `currentSlideIdx` to 0
- When "Explain differently" is clicked:
  - Swap explanation cards in the carousel (same logic as current `handleCardAction('explain_differently')`)
  - Reset carousel to first slide

### Step 9: Port localStorage resume logic

**File: `ChatSession.tsx`** (addresses reviewer finding #4)

The current `ExplanationViewer` persists card position via `localStorage.setItem('card-pos-${sessionId}', ...)`. Port this to the unified carousel:

- On slide navigation: `localStorage.setItem('slide-pos-${sessionId}', String(currentSlideIdx))`
- On session init: restore `currentSlideIdx` from localStorage
- On card_phase → interactive transition: clear the stored position
- On session complete: clear the stored position

### Step 10: Clean up focus_mode user preference

**File: `ChatSession.tsx`, `ProfilePage.tsx`** (addresses reviewer finding #3)

Since the card view is now always-on, the `focus_mode` user preference is no longer meaningful:

- `ChatSession.tsx`: Remove all `user?.focus_mode !== false` checks (3 locations)
- `ProfilePage.tsx`: Remove the focus mode toggle from the settings UI
- `AuthContext.tsx`: Keep the `focus_mode` field on the user type (no DB migration needed, just unused)
- Backend: No changes — the field stays in the DB, just ignored

### Step 11: Auto-play TTS on new slides

**File: `ChatSession.tsx`**
- In card_phase: auto-play TTS when navigating to a new explanation card (read `slide.content` or `slide.audioText`)
- In interactive: auto-play TTS when new tutor message arrives (existing logic, adapted to use `playingSlideId`)
- Single audio play/pause button in nav works for both phases

### Step 12: Clean up CSS

**File: `App.css`**
- Remove: `.messages`, `.message.teacher`, `.message.student`, `.virtual-teacher-view`, `.vt-typing-indicator`, `.vt-input-area`
- Keep: `.focus-carousel` (adapted), `.focus-slide`, `.focus-tutor-msg`, `.focus-input-area`, `.focus-track`
- Keep: `.explanation-card-type`, `.explanation-card-title` styles (reused in card_phase slides)
- Adapt `.explanation-nav-btn` styles for the unified bottom action area

### Step 13: Clean up dead code

- Delete `ExplanationViewer.tsx` component file
- Remove unused state variables: `virtualTeacherOn`, `focusDismissedRef`, `lastTapRef`, `playingMsgIdx`
- Remove unused CSS classes

## What Stays Unchanged

- Exam mode (its own card-like Q&A UI)
- Session completion/summary view
- Feedback modal
- DevTools drawer
- WebSocket communication
- Backend API (no backend changes needed)
- Visual explanations (PixiJS) — just rendered inside card slides

## Key Design Decisions

1. **Unified `Slide` data model** — A single interface abstracts over explanation cards and messages. This is the foundation that makes audio tracking, resume, and transitions work correctly. Treat this as a state-model refactor, not just a UI cleanup.
2. **Focus carousel becomes the primary view** — it already has the right UX (swipe, one-card-at-a-time, large text). We promote it rather than building something new.
3. **Container-relative sizing** — Use `containerRef.clientWidth` instead of `window.innerWidth` so the carousel works correctly as an inline element on desktop/tablet.
4. **Streaming slide** — A provisional slide appended to the carousel during streaming, replaced by the final message when complete. Ensures streaming text isn't lost when chat bubbles are removed.
5. **Stable slide IDs for audio** — Replace message-index-based audio tracking with string IDs (`"card-0"`, `"msg-2"`) that survive the explanation→interactive transition.
6. **No user preference needed** — Everyone gets the card view. Removes complexity of VT toggle and focus_mode pref. The `focus_mode` DB field is left in place (no migration) but ignored.
7. **Exam mode untouched** — It has its own distinct UX that works well as-is.

## Files Modified

| File | Change |
|------|--------|
| `llm-frontend/src/pages/ChatSession.tsx` | Major refactor — unified Slide model + card view |
| `llm-frontend/src/App.css` | Remove old styles, adapt focus carousel to inline + container-relative |
| `llm-frontend/src/pages/ProfilePage.tsx` | Remove focus_mode toggle |
| `llm-frontend/src/components/ExplanationViewer.tsx` | **DELETE** |
