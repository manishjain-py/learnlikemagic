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
