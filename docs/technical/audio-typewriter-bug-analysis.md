# Bug Analysis: Audio + Typewriter Stops After 4-5 Cards

## Problem

During Teach Me card sessions, after 4-5 explanation cards play correctly (typewriter line reveal + TTS audio), both audio playback and line animation stop working. The remaining cards either flash through instantly with no audio, or the typewriter freezes entirely.

## How the Pipeline Works

The audio+typewriter system has three components working in a chain:

1. **TypewriterMarkdown** (`src/components/TypewriterMarkdown.tsx`) reveals words one at a time per block (line/paragraph). When a block finishes typing, it calls `onBlockTyped(audioText)` and waits for the returned Promise to resolve before advancing to the next block.

2. **playLineAudio** (`src/pages/ChatSession.tsx:985-1032`) fetches TTS audio via `prefetchAudio()`, sets it on a single global `HTMLAudioElement`, plays it, and returns a Promise that resolves when playback ends.

3. **prefetchAudio** (`src/pages/ChatSession.tsx:969-983`) caches TTS requests in a 30-entry Map. `onBlockStart` fires a prefetch for the next line while the current line is still playing.

The contract: TypewriterMarkdown waits for `playLineAudio`'s Promise. If that Promise resolves early (before audio finishes) or never resolves, the system breaks.

## Root Cause Analysis

### Bug 1: `onstalled` handler kills audio prematurely (PRIMARY)

**File:** `ChatSession.tsx:1021-1024`

```tsx
audio.onstalled = () => {
  console.warn('playLineAudio: audio stalled');
  done();  // resolves the Promise immediately
};
```

On mobile browsers, `stalled` fires when the audio element can't load media data fast enough. With blob URLs, this happens under memory pressure from previous blobs. **`stalled` does not mean playback failed** — the browser can recover. But our handler calls `done()` immediately, resolving the Promise.

This cascades: line resolves instantly -> typewriter advances -> next `playLineAudio` fires -> browser is under more pressure -> another `stalled` -> all remaining lines flash through with no audio.

### Bug 2: `onpause` fires spuriously on mobile

**File:** `ChatSession.tsx:1017-1019`

```tsx
audio.onpause = () => {
  if (audio.src === url) done();
};
```

Mobile browsers can pause audio for system reasons (incoming notification, memory pressure, audio session management). The guard `audio.src === url` helps but doesn't cover all cases. After rapid consecutive plays, spurious pause events can trigger premature resolution.

Additionally, there's a subtle interaction: every `playLineAudio` call starts with `audio.pause()` (line 988) to stop the previous play. If the previous play's `onpause` handler fires asynchronously after the new play has started, the timing can cause issues even with the guard.

### Bug 3: Catch block hides TTS failures

**File:** `ChatSession.tsx:1029-1031`

```tsx
} catch (err) {
  console.error('Line TTS failed:', err);
  // returns undefined from async function = resolved Promise
}
```

When `prefetchAudio` throws (network timeout, TTS server overloaded), the catch block logs but returns `undefined`. Since `playLineAudio` is `async`, this becomes a resolved `Promise<undefined>`. TypewriterMarkdown sees the Promise resolve and advances — lines flash through instantly with no audio.

### Contributing Factor: Concurrent prefetch pressure

`onBlockStart` fires a prefetch while the current line is still playing. After 4-5 cards (~10-20 TTS requests), the TTS server or browser network stack gets overwhelmed. Failed prefetches cascade into Bug 3, causing rapid silent advancement.

### Contributing Factor: Handler accumulation on shared audio element

The single global `HTMLAudioElement` gets new `onended`/`onerror`/`onpause`/`onstalled` handlers on every `playLineAudio` call. These are set to `null` inside the `done()` function (lines 1000-1003), but only if `done()` actually runs. In edge cases where `done()` doesn't fire (e.g., the Promise chain breaks), stale handlers from previous plays can fire on subsequent plays.

## Evidence of Known Fragility

The codebase already shows awareness of this problem:

- **30-second safety timeout** in `playLineAudio` (line 1010) — "Prevents animation freeze when mobile browser audio session degrades"
- **35-second safety timeout** in TypewriterMarkdown (line 305) — "if onBlockTyped never resolves (e.g. audio hangs), force-advance after 35s"
- **Comment on line 1016:** "Catch silent stalls: browser may pause/stall audio after many plays"
- **30-entry cache cap** (line 973) — attempt to manage memory on mobile

These are band-aids that acknowledge the fundamental fragility: audio failure modes block the typewriter.

## Proposed Fix

### Part 1 — Immediate (fixes the symptom)

**Changes in `playLineAudio` (`ChatSession.tsx:985-1032`):**

1. **Remove `onstalled` as a termination handler.** Stalled means "loading slowly," not "failed." The browser can recover. Let it try.

2. **Remove `onpause` as a termination handler.** Too many false positives on mobile. The only legitimate termination events are `onended` (audio finished) and `onerror` (audio failed).

3. **Null out all handlers BEFORE calling `audio.pause()`** at the start of `playLineAudio`. Currently, `audio.pause()` fires the previous play's `onpause` handler. By nulling handlers first, we prevent stale handler interference.

4. **Reduce safety timeout from 30s to 10s.** A typical TTS line is 3-8 seconds. 30s means the student waits half a minute if something goes wrong. 10s is generous enough for slow networks but short enough to not feel broken.

5. **Fix the catch block** to explicitly resolve (return) so the behavior is clear:
   ```tsx
   } catch (err) {
     console.error('Line TTS failed:', err);
     return; // async function — returns resolved Promise<void>
   }
   ```

### Part 2 — Structural (prevents the class of bugs)

**Pre-fetch all audio lines for a card before starting the typewriter.**

Currently, audio is fetched one line ahead via `onBlockStart`. Under pressure, this single-line prefetch fails and cascades into the bugs above.

The fix: when a card becomes active (slide changes), immediately prefetch ALL audio lines for that card into the cache. By the time the typewriter starts revealing lines, all audio is already in memory. This eliminates:
- Concurrent fetch+play pressure
- Network failures mid-card causing cascading audio loss
- The need for `onBlockStart` prefetching entirely

Implementation:
```tsx
// When slide changes, prefetch all audio for the new card
useEffect(() => {
  const slide = carouselSlides[currentSlideIdx];
  if (slide?.audioLines) {
    slide.audioLines.forEach(line => {
      if (line.audio?.trim()) prefetchAudio(line.audio);
    });
  }
}, [currentSlideIdx]);
```

This is a small change but eliminates the root cause of network pressure after 4-5 cards.

## Confidence Assessment

| Fix | Confidence | Impact |
|-----|-----------|--------|
| Remove `onstalled` handler | 90% | Fixes the primary cascade |
| Remove `onpause` handler | 85% | Eliminates spurious termination |
| Null handlers before pause | 90% | Prevents stale handler interference |
| Reduce safety timeout to 10s | 95% | Faster recovery from edge cases |
| Fix catch block | 95% | Clean error handling |
| Pre-fetch all card audio upfront | 85% | Eliminates fetch pressure root cause |
| **All combined** | **90-95%** | **Should resolve for vast majority of sessions** |

The remaining 5-10% are edge cases like phone calls interrupting audio session, tab backgrounding, or OS-level audio session conflicts — which the safety timeout handles gracefully.

## Files Affected

| File | Lines | What changes |
|------|-------|-------------|
| `llm-frontend/src/pages/ChatSession.tsx` | 985-1032 | `playLineAudio` handler cleanup |
| `llm-frontend/src/pages/ChatSession.tsx` | ~330 (new) | Card-level audio prefetch effect |
| `llm-frontend/src/components/TypewriterMarkdown.tsx` | 304-310 | Reduce safety timeout to match |

## Test Plan

1. Open a Teach Me session for a topic with 8+ explanation cards
2. Let all cards play through with typewriter + audio
3. Verify audio plays on every line through the last card
4. Test on mobile Safari (iPhone) and mobile Chrome (Android) — these are where the bug manifests
5. Test with poor network (throttle to 3G) to verify prefetch resilience
6. Test interrupting mid-card (lock screen, notification) and returning — verify recovery

---

## Post-Mortem: Real Root Cause (2026-04-12)

**The analysis above was wrong about the primary cause.** Adding debug logging and monitoring a live session revealed:

- TTS API requests take **10-22 seconds** per line (Google Cloud TTS under concurrent load)
- Many requests hit the 15s `AbortController` timeout and fail entirely
- The `onstalled`/`onpause` handlers were a secondary issue at best — the real problem was that audio simply wasn't arriving in time

**Resolution:** Pre-computed audio stored on S3 (`docs/feature-development/pre-computed-audio/PRD.md`). Audio is generated offline during the explanation pipeline, uploaded to S3, and served via direct HTTPS download (~300-900ms) instead of real-time TTS API calls (10-22s). Lines without pre-computed audio fall back to real-time TTS.

The `onstalled`/`onpause` handler fixes and safety timeout changes from the original analysis are still in the code as defense-in-depth for the TTS fallback path, but they are no longer the primary fix.
