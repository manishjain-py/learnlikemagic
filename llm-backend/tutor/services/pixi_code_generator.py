"""
Pixi.js Code Generator Service

Translates natural language visual descriptions into executable Pixi.js v8 code
using an LLM (GPT Codex). Used by the orchestrator to generate visuals for
the tutor's visual_explanation prompts.
"""

import asyncio
import logging

from shared.services.llm_service import LLMService, LLMServiceError

logger = logging.getLogger(__name__)

_PIXI_SYSTEM_PROMPT_HEADER = """You are an expert Pixi.js v8 developer. Generate ONLY valid JavaScript code that uses Pixi.js v8 to create the requested visual.

CRITICAL RULES:
1. The code will be executed via new Function() with a single parameter `app` which is an initialized PIXI.Application instance already added to the DOM.
2. PIXI is available as a global variable. Use `PIXI.Graphics`, `PIXI.Text`, `PIXI.Container`, etc.
3. The canvas size is 500x350. Use `app.screen.width` and `app.screen.height`.
4. Do NOT call `new PIXI.Application()` or `app.init()` — the app is already initialized.
5. Do NOT use import/export statements. PIXI is a global.
6. For animations, use `app.ticker.add(callback)`.
7. Return ONLY the JavaScript code, no markdown fences, no explanation.
8. Use modern Pixi.js v8 API:
   - Graphics: `const g = new PIXI.Graphics(); g.rect(x,y,w,h); g.fill(color);` (chaining fill/stroke after shape calls)
   - Text: `new PIXI.Text({ text: '...', style: { fontSize: 24, fill: 0xffffff } })`
   - Container: `new PIXI.Container()`
9. Always add created display objects to `app.stage` via `app.stage.addChild(...)`.
10. For colors use hex numbers like 0xff0000, not strings.
11. Keep code concise but visually clear and educational.
12. Use kid-friendly colors and large readable text for educational content."""


class PixiCodeGenerator:
    """Generates Pixi.js v8 code from natural language visual descriptions."""

    def __init__(self, llm_service: LLMService):
        self.llm = llm_service

    async def generate(self, visual_prompt: str, output_type: str = "image") -> str:
        """Generate Pixi.js code from a visual description.

        Returns the generated JavaScript code string, or empty string on failure.
        """
        import time
        start = time.time()
        try:
            # Build prompt via concatenation — NOT str.format() — because
            # visual_prompt may contain curly braces (e.g. "the set {1,2,3}")
            # which would crash .format() with KeyError/ValueError.
            prompt = (
                _PIXI_SYSTEM_PROMPT_HEADER
                + f"\n\nOUTPUT_TYPE: {output_type}"
                + "\n\nIf OUTPUT_TYPE is \"animation\", include smooth animations using app.ticker."
                + "\nIf OUTPUT_TYPE is \"image\", create a static diagram/illustration."
                + f"\n\nVISUAL DESCRIPTION:\n{visual_prompt}"
            )
            result = await asyncio.to_thread(
                self.llm.call,
                prompt=prompt,
                reasoning_effort="none",
                json_mode=False,
            )
            code = result["output_text"]
            stripped = self._strip_markdown_fences(code)
            duration_ms = int((time.time() - start) * 1000)
            if stripped:
                logger.info(f"Pixi code generated ({duration_ms}ms, {len(stripped)} chars)")
            else:
                logger.warning(
                    f"Pixi code generation returned empty after stripping ({duration_ms}ms, "
                    f"raw length={len(code)})"
                )
            return stripped
        except LLMServiceError as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"Pixi code generation failed ({duration_ms}ms): {e}")
            return ""
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"Unexpected error in pixi code generation ({duration_ms}ms, {type(e).__name__}): {e}")
            return ""

    @staticmethod
    def _strip_markdown_fences(code: str) -> str:
        """Strip markdown code fences if present."""
        code = code.strip()
        if code.startswith("```"):
            newline_idx = code.find("\n")
            if newline_idx == -1:
                # Edge case: input is just "```" or "```js" with no newline
                return ""
            code = code[newline_idx + 1:]
        if code.endswith("```"):
            code = code[:-3].rstrip()
        return code
