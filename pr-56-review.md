# PR #56 Review: PixiJS Diagram Integration

## Summary

This PR replaces the hardcoded SVG-based visual explanation system (5 scene types: addition, subtraction, fraction, multiplication, counting) with a flexible LLM-driven approach: the master tutor writes a natural-language `visual_prompt`, a new `PixiCodeGenerator` service translates it to Pixi.js v8 code via a second LLM call, and the frontend executes that code in a canvas.

---

## Critical Issues

### 1. XSS / Arbitrary Code Execution on the Client (Security — HIGH)

**File:** `llm-frontend/src/components/VisualExplanation.tsx:71`

The component executes LLM-generated JavaScript directly in the browser:

```js
const fn = new Function('app', 'PIXI', code);
fn(app, PIXI);
```

This runs arbitrary code in the page's origin with full access to `document`, `window`, `localStorage`, cookies, etc. An adversarial or hallucinated LLM response could:

- Exfiltrate session tokens / auth credentials
- Modify the DOM to phish the student
- Make network requests to external servers

**Recommendation:** Sandbox the generated code in an `<iframe sandbox="allow-scripts">` with a `null` origin, or use a Web Worker. At minimum, wrap execution in a restrictive CSP or use a code-analysis allowlist before eval.

### 2. Pixi Code Generation Adds Latency to Every Visual Turn (Performance — HIGH)

**Files:** `llm-backend/tutor/orchestration/orchestrator.py:281,451,782`

`_generate_pixi_code()` is called inline — it makes a full synchronous LLM call (wrapped in `asyncio.to_thread`) before the `TurnResult` is returned to the student. This means:

- Every turn with a visual now requires **two sequential LLM calls** (tutor + pixi codegen) before the student sees anything
- The pixi generation cannot be parallelized because it depends on the tutor output
- For the **streaming path** (`process_turn_stream`, line 451), the visual is still generated non-streaming, so the student sees the text stream but then waits for the pixi code before the turn completes

**Recommendation:** Consider generating pixi code asynchronously / in the background and pushing it to the frontend via WebSocket once ready, so the text response isn't blocked.

### 3. Silent Failure Returns Empty `pixi_code` — Frontend Still Renders Container (Functional — MEDIUM)

**Files:** `llm-backend/tutor/services/pixi_code_generator.py:50-53`, `llm-frontend/src/components/VisualExplanation.tsx:98-100`

If the LLM call fails, `generate()` returns `""`. The orchestrator still constructs a `visual_dict` with `pixi_code: ""`. On the frontend, `if (!visual.pixi_code) return null` catches this, BUT the "Visualise" start button was already shown because `visual_explanation` is non-null in the turn data. The user clicks "Visualise", `executePixiCode("")` is called, hits the `if (!code) return` guard, and nothing happens — no error, no feedback.

**Recommendation:** Either (a) don't include `visual_explanation` in the turn result when pixi_code is empty, or (b) show an explicit "Visual unavailable" message when code is empty.

### 4. `_strip_markdown_fences` Crashes on Malformed Input (Bug — MEDIUM)

**File:** `llm-backend/tutor/services/pixi_code_generator.py:60-61`

```python
if code.startswith("```"):
    first_newline = code.index("\n")
```

If the LLM returns just `` ``` `` with no newline, `code.index("\n")` raises `ValueError`. The exception is caught by the generic `except Exception` at line 252, which logs a misleading "Unexpected error in pixi code generation" and silently returns `""`.

**Recommendation:** Use `code.find("\n")` with a bounds check, or handle `ValueError` explicitly.

---

## Moderate Issues

### 5. `visual_prompt` Leaks to the Frontend (Data — LOW)

The `visual_dict` returned by `_generate_pixi_code()` includes `visual_prompt` (the natural-language description). The frontend type marks it as `visual_prompt?: string // Original prompt (for debugging)`. In production this exposes the internal prompt to anyone inspecting the WebSocket payload. If the prompt contains internal instructions or teacher context, this could be undesirable.

### 6. Dark Theme Hardcoded Without Theme Awareness (UX — LOW)

The CSS changes hardcode a dark background (`#0f0f23`) and light text. The Pixi canvas also uses `backgroundColor: 0x1a1a2e`. If the app supports or later adds a light theme, visuals will look broken. The old SVG approach used light colors that matched the existing app theme.

### 7. No Pixi.js Cleanup on `visual` Prop Change (Bug — LOW)

**File:** `llm-frontend/src/components/VisualExplanation.tsx`

The `useEffect` cleanup only runs on unmount (`[]` deps). If the parent re-renders with a *different* `visual` prop (e.g., navigating between turns), the old Pixi app isn't destroyed and the new one isn't created. The `started` state also persists. This could cause stale canvases or memory leaks.

### 8. `(window as any).PIXI = PIXI` Global Pollution (Code Quality — LOW)

**File:** `llm-frontend/src/components/VisualExplanation.tsx:69`

Sets `PIXI` on the global `window` object. This persists across the app lifecycle and could conflict with other libraries or multiple simultaneous visuals. The code already passes `PIXI` as a function parameter (line 71-72), so the global assignment appears unnecessary — unless the generated code references `PIXI` directly rather than using the parameter.

---

## Regression Risk Assessment

| Area | Risk | Notes |
|------|------|-------|
| **Existing sessions with old visual data** | **HIGH** | Old sessions stored in DB have `scene_type`, `group1_count`, etc. The new frontend expects `pixi_code`. Loading historical turns will render a "Visualise" button that does nothing (empty pixi_code), or the component returns null. The old SVG renderers are completely deleted. |
| **Tutor output schema change** | **MEDIUM** | `VisualExplanation` model fields completely changed. If any other code references old fields (`scene_type`, `animation_steps`, etc.), it will break. |
| **LLM cost increase** | **MEDIUM** | Every visual turn now requires a second LLM call. Depending on the model used, this could significantly increase per-turn cost and token usage. |
| **pixi.js bundle size** | **LOW** | `pixi.js` is a ~500KB+ dependency added to the frontend bundle. Worth confirming tree-shaking or lazy loading is set up. |

---

## Verdict

The architectural direction is sound — moving from rigid scene types to flexible LLM-generated visuals is a good long-term play. However, the PR has a **critical security issue** (executing untrusted LLM-generated JS in the page context) that should be addressed before merge, along with the latency concern in the hot path and backward compatibility with existing stored sessions.

---
---

# Second Round Review (post-fix commit `c291f81`)

## Issues Addressed

All 8 original issues were addressed. Here's an assessment of each fix:

### 1. XSS / Arbitrary Code Execution — RESOLVED

The fix moves code execution into an `<iframe sandbox="allow-scripts">` with `srcdoc`. This is a solid mitigation:

- `sandbox="allow-scripts"` without `allow-same-origin` gives the iframe a `null` origin — no access to parent page cookies, localStorage, or DOM
- Pixi.js is loaded from CDN inside the iframe, eliminating the `(window as any).PIXI` global pollution (issue #8 also resolved)
- The `new Function()` call now runs inside the sandboxed iframe, not the parent page

**Status: Well implemented.**

### 2. Latency (Sequential LLM Calls) — RESOLVED

The streaming path (`process_turn_stream`) now:
1. Yields `("result", TurnResult)` immediately with `visual_explanation=None`
2. Then generates pixi code and yields `("visual", visual_dict)` as a separate message
3. The WebSocket handler sends a `visual_update` message after the main response
4. Frontend's `onVisualUpdate` callback attaches the visual to the last teacher message

**Status: Well designed. Text response is no longer blocked by pixi generation.**

### 3. Silent Failure / Broken "Visualise" Button — RESOLVED

`_generate_pixi_code()` now returns `None` when pixi code is empty, and the orchestrator only yields the visual message when the dict is non-None. The frontend never receives a visual with empty `pixi_code`.

**Status: Clean fix.**

### 4. `_strip_markdown_fences` Crash — RESOLVED

Changed `code.index("\n")` to `code.find("\n")` with a `-1` bounds check that returns `""`.

**Status: Correct.**

### 5. `visual_prompt` Leak — RESOLVED

`visual_dict.pop("visual_prompt", None)` strips the internal prompt before sending to client.

**Status: Clean fix.**

### 7. No Cleanup on Prop Change — RESOLVED

The iframe approach inherently solves this — when `pixiCode` changes, `useEffect` resets `started` to false, and React unmounts/remounts the iframe naturally. No manual Pixi app cleanup needed.

**Status: Resolved by architecture change.**

### 8. Global `window.PIXI` Pollution — RESOLVED

Pixi.js is now loaded inside the sandboxed iframe via CDN `<script>` tag. No global pollution on the parent page.

**Status: Resolved by architecture change.**

---

## Remaining Issues (New or Unchanged)

### R1. Non-streaming `process_turn` path still blocks on pixi generation (Performance — MEDIUM)

**File:** `llm-backend/tutor/orchestration/orchestrator.py:293`

The fix only addressed the streaming path. The non-streaming `process_turn()` (line 293) and `_process_clarify_turn()` (line 802) still `await self._generate_pixi_code()` inline before returning the `TurnResult`. These paths block the full response on the second LLM call.

This may be acceptable if non-streaming is only used for exam/clarify modes where visuals are rare, but worth noting for consistency.

### R2. `postMessage` listener has no origin check (Security — LOW)

**File:** `llm-frontend/src/components/VisualExplanation.tsx:59`

```js
const handler = (event: MessageEvent) => {
  if (event.data?.type === 'pixi-error') { ... }
};
window.addEventListener('message', handler);
```

The handler listens for messages from **any** origin. While the check is only for `pixi-error` type messages (low impact — it just shows an error string), any other page/iframe could trigger false error states. Additionally, if multiple `VisualExplanation` components are mounted simultaneously, an error from one iframe would trigger error state in all of them.

**Recommendation:** Check `event.source` against the specific iframe's `contentWindow`, or use a unique nonce per iframe instance in the message payload.

### R3. Pixi.js loaded from external CDN inside iframe (Reliability — LOW)

**File:** `llm-frontend/src/components/VisualExplanation.tsx:37`

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/pixi.js/8.6.6/pixi.min.js">
```

The iframe loads Pixi.js from cdnjs on every render. If the CDN is slow or down, the visual silently fails (the `PIXI` global won't exist, causing a ReferenceError caught by the try/catch which sends `pixi-error`). This also means:
- No SRI hash — a CDN compromise could inject malicious code inside the sandbox
- Additional network request per visual render
- Version `8.6.6` is pinned in a string literal — easy to forget during upgrades

Consider bundling Pixi.js as a static asset and using a blob URL or data URI in the srcdoc instead.

### R4. `onVisualUpdate` race condition with message state (Functional — LOW)

**File:** `llm-frontend/src/pages/ChatSession.tsx:371-381`

```js
onVisualUpdate: (visualExplanation) => {
  setMessages((prev) => {
    const updated = [...prev];
    for (let i = updated.length - 1; i >= 0; i--) {
      if (updated[i].role === 'teacher') {
        updated[i] = { ...updated[i], visualExplanation };
        break;
      }
    }
    return updated;
  });
},
```

This finds the **last** teacher message and attaches the visual. If a fast follow-up turn completes before the visual from the previous turn arrives (unlikely but possible), the visual would attach to the wrong message. Consider including a `turn_id` in the `visual_update` payload to match precisely.

### R5. Dark theme hardcoded (UX — LOW, unchanged)

Issue #6 from the first review was not addressed. The dark background (`#1a1a2e`) is hardcoded in both the iframe srcdoc CSS and the Pixi canvas `backgroundColor`. This is cosmetic and low priority.

### R6. Bundle size impact from pixi.js (unchanged, but mitigated)

The iframe approach partially mitigates this — pixi.js is no longer in the main app bundle since it's loaded from CDN inside the iframe. However, `pixi.js` may still be in `package.json` as an unused dependency if it wasn't removed. Worth checking and cleaning up.

---

## Regression Risk (Updated)

| Area | Risk | Status |
|------|------|--------|
| **Existing sessions with old visual data** | **LOW** | Fixed — frontend checks for `scene_type` and returns null for legacy data |
| **Tutor output schema change** | **LOW** | `VisualExplanation` type now includes optional `scene_type` for backward compat |
| **LLM cost increase** | **MEDIUM** | Unchanged — still a second LLM call per visual turn |
| **pixi.js bundle size** | **RESOLVED** | Pixi.js loaded from CDN inside iframe, not bundled in main app |

---

## Verdict

The fix commit addresses all critical and medium issues from the first review effectively. The iframe sandbox is a clean solution that simultaneously resolves the XSS concern, global pollution, and cleanup-on-prop-change issues. The async visual delivery via WebSocket is well-designed and unblocks the streaming text response.

The remaining issues (R1-R6) are all LOW-MEDIUM severity and none are merge-blockers. **This PR is ready to merge.** The remaining items can be addressed in follow-up PRs if desired.
