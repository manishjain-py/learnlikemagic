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

PIXI_SYSTEM_PROMPT = """You are an expert Pixi.js v8 developer. Generate ONLY valid JavaScript code that uses Pixi.js v8 to create the requested visual.

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
12. Use kid-friendly colors and large readable text for educational content.

OUTPUT_TYPE: {output_type}

If OUTPUT_TYPE is "animation", include smooth animations using app.ticker.
If OUTPUT_TYPE is "image", create a static diagram/illustration.

VISUAL DESCRIPTION:
{visual_prompt}"""


class PixiCodeGenerator:
    """Generates Pixi.js v8 code from natural language visual descriptions."""

    def __init__(self, llm_service: LLMService):
        self.llm = llm_service

    async def generate(self, visual_prompt: str, output_type: str = "image") -> str:
        """Generate Pixi.js code from a visual description.

        Returns the generated JavaScript code string, or empty string on failure.
        """
        prompt = PIXI_SYSTEM_PROMPT.format(
            output_type=output_type,
            visual_prompt=visual_prompt,
        )

        try:
            result = await asyncio.to_thread(
                self.llm.call,
                prompt=prompt,
                reasoning_effort="none",
                json_mode=False,
            )
            code = result["output_text"]
            return self._strip_markdown_fences(code)
        except LLMServiceError as e:
            logger.error(f"Pixi code generation failed: {e}")
            return ""
        except Exception as e:
            logger.error(f"Unexpected error in pixi code generation: {e}")
            return ""

    @staticmethod
    def _strip_markdown_fences(code: str) -> str:
        """Strip markdown code fences if present."""
        code = code.strip()
        if code.startswith("```"):
            first_newline = code.index("\n")
            code = code[first_newline + 1:]
        if code.endswith("```"):
            code = code[:-3].rstrip()
        return code
