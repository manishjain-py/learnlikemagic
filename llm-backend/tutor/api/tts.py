"""Text-to-speech endpoint using OpenAI TTS API."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel, Field

from auth.middleware.auth_middleware import get_optional_user
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text-to-speech", tags=["tts"])

MAX_TEXT_LENGTH = 4096  # OpenAI TTS input limit


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)


@router.post("")
async def text_to_speech(
    request: TTSRequest,
    current_user=Depends(get_optional_user),
):
    """Convert text to speech using OpenAI TTS API."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=request.text,
        )

        return StreamingResponse(
            response.iter_bytes(),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail="Text-to-speech generation failed")
