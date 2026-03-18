"""
Pixi.js PoC API — Generates Pixi.js code from natural language prompts.

Uses GPT Codex 5.3 to translate user descriptions into executable Pixi.js v8 code.
"""

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_settings
from shared.services.llm_service import LLMService, LLMServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/pixi-poc", tags=["pixi-poc"])

SYSTEM_PROMPT_TEMPLATE = """You are an expert Pixi.js v8 developer. Generate ONLY valid JavaScript code that uses Pixi.js v8 to create the requested visual.

CRITICAL RULES:
1. The code will be executed via new Function() with a single parameter `app` which is an initialized PIXI.Application instance already added to the DOM.
2. PIXI is available as a global variable. Use `PIXI.Graphics`, `PIXI.Text`, `PIXI.Container`, etc.
3. The canvas size is available as `app.screen.width` and `app.screen.height` (default 800x600).
4. Do NOT call `new PIXI.Application()` or `app.init()` — the app is already initialized.
5. Do NOT use import/export statements. PIXI is a global.
6. For animations, use `app.ticker.add(callback)`.
7. Return ONLY the JavaScript code, no markdown fences, no explanation.
8. Use modern Pixi.js v8 API:
   - Graphics: `const g = new PIXI.Graphics(); g.rect(x,y,w,h); g.fill(color);` (chaining fill/stroke after shape calls)
   - Text: `new PIXI.Text({{ text: '...', style: {{ fontSize: 24, fill: 0xffffff }} }})`
   - Container: `new PIXI.Container()`
   - Sprite from graphics: render to texture if needed
9. Always add created display objects to `app.stage` via `app.stage.addChild(...)`.
10. For colors use hex numbers like 0xff0000, not strings.
11. Keep code concise but visually impressive.

OUTPUT_TYPE: {output_type}

If OUTPUT_TYPE is "animation", include smooth animations using app.ticker.
If OUTPUT_TYPE is "image", create a static diagram/illustration.

USER REQUEST:
{user_prompt}
"""


class PixiGenerateRequest(BaseModel):
    prompt: str
    output_type: Literal["image", "animation"] = "image"


class PixiGenerateResponse(BaseModel):
    code: str
    output_type: str


@router.post("/generate", response_model=PixiGenerateResponse)
async def generate_pixi_code(request: PixiGenerateRequest):
    """Generate Pixi.js code from a natural language prompt."""
    from database import get_db
    from shared.services.llm_config_service import LLMConfigService

    settings = get_settings()

    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    # Load model config from DB
    db = next(get_db())
    try:
        pixi_config = LLMConfigService(db).get_config("pixi_code_generator")
    finally:
        db.close()

    llm = LLMService(
        api_key=settings.openai_api_key,
        provider=pixi_config["provider"],
        model_id=pixi_config["model_id"],
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        timeout=120,
    )

    full_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        output_type=request.output_type,
        user_prompt=request.prompt,
    )

    try:
        # Run sync LLM call in thread pool to avoid blocking the event loop
        result = await asyncio.to_thread(
            llm.call,
            prompt=full_prompt,
            reasoning_effort="none",
            json_mode=False,
        )
        code = result["output_text"]

        # Strip markdown fences if the LLM wraps them anyway
        code = code.strip()
        if code.startswith("```"):
            # Remove opening fence
            first_newline = code.index("\n")
            code = code[first_newline + 1:]
        if code.endswith("```"):
            code = code[:-3].rstrip()

        return PixiGenerateResponse(code=code, output_type=request.output_type)

    except LLMServiceError as e:
        logger.error(f"Pixi PoC LLM error: {e}")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {str(e)}")
