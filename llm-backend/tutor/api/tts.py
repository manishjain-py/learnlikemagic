"""Text-to-speech endpoint using Google Cloud TTS API (Chirp 3 HD)."""

import io
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions
from pydantic import BaseModel, Field

from auth.middleware.auth_middleware import get_optional_user
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text-to-speech", tags=["tts"])

MAX_TEXT_LENGTH = 5000  # Google Cloud TTS limit


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    language: str = Field(default='hinglish', pattern=r'^(en|hi|hinglish)$')


@router.post("")
async def text_to_speech(
    request: TTSRequest,
    current_user=Depends(get_optional_user),
):
    """Convert text to speech using Google Cloud TTS API (Chirp 3 HD Kore)."""
    settings = get_settings()

    if not settings.google_cloud_tts_api_key:
        raise HTTPException(status_code=500, detail="Google Cloud TTS API key not configured")

    try:
        # Use API key auth (simpler than service account for single API)
        client = texttospeech.TextToSpeechClient(
            client_options=ClientOptions(api_key=settings.google_cloud_tts_api_key),
        )

        synthesis_input = texttospeech.SynthesisInput(text=request.text)

        # Chirp 3 HD Kore — natural human-like voice for all languages
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-IN",
            name="en-IN-Chirp3-HD-Kore",
        )

        # Chirp 3 HD does not support pitch/rate adjustment
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )

        audio_stream = io.BytesIO(response.audio_content)

        return StreamingResponse(
            audio_stream,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail="Text-to-speech generation failed")
