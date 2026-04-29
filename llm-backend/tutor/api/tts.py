"""Text-to-speech endpoint using Google Cloud TTS API (Chirp 3 HD)."""

import asyncio
import io
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions
from pydantic import BaseModel, Field

from auth.middleware.auth_middleware import get_optional_user
from book_ingestion_v2.services.audio_generation_service import (
    PEER_VOICE,
    TUTOR_VOICE,
    normalize_tts_text,
)
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text-to-speech", tags=["tts"])

MAX_TEXT_LENGTH = 5000  # Google Cloud TTS limit

# Reuse the gRPC client across requests — creating a new client per request
# adds significant connection setup overhead under burst TTS load.
_tts_client: texttospeech.TextToSpeechClient | None = None
_tts_api_key: str | None = None


def _get_tts_client() -> texttospeech.TextToSpeechClient:
    global _tts_client, _tts_api_key
    settings = get_settings()
    api_key = settings.google_cloud_tts_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="Google Cloud TTS API key not configured")
    # Recreate client if API key changed (e.g. config reload)
    if _tts_client is None or _tts_api_key != api_key:
        _tts_client = texttospeech.TextToSpeechClient(
            client_options=ClientOptions(api_key=api_key),
        )
        _tts_api_key = api_key
    return _tts_client


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    language: str = Field(default='hinglish', pattern=r'^(en|hi|hinglish)$')
    # Allowlisted role; never accept arbitrary Google voice IDs from the
    # frontend. Baatcheet uses "peer" for Meera's lines; everything else
    # falls through to the language-mapped tutor voice.
    voice_role: Literal["tutor", "peer"] = "tutor"


@router.post("")
async def text_to_speech(
    request: TTSRequest,
    current_user=Depends(get_optional_user),
):
    """Convert text to speech using Google Cloud TTS API (Chirp 3 HD Kore)."""
    try:
        client = _get_tts_client()

        synthesis_input = texttospeech.SynthesisInput(text=normalize_tts_text(request.text))

        if request.voice_role == "peer":
            lang_code, voice_name = PEER_VOICE
        else:
            # Tutor voice — en-IN-Chirp3-HD-Orus across all languages.
            # See `audio_generation_service.VOICE_MAP` for the rationale.
            lang_code, voice_name = TUTOR_VOICE

        voice = texttospeech.VoiceSelectionParams(
            language_code=lang_code,
            name=voice_name,
        )

        # Chirp 3 HD does not support pitch/rate adjustment
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )

        response = await asyncio.to_thread(
            client.synthesize_speech,
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
    except Exception:
        logger.exception("TTS generation failed")
        raise HTTPException(status_code=500, detail="Text-to-speech generation failed")
