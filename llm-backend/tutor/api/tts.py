"""Text-to-speech endpoint — runtime synthesis for `{student_name}` cards.

Provider routing mirrors `book_ingestion_v2.services.audio_generation_service`:
inline branch on `settings.tts_provider` (admin DB override resolved upstream
when a DB session is available). Google path uses Chirp 3 HD; ElevenLabs
path uses v3 with the steady voice preset (no per-line emotion at runtime —
this endpoint exists only for student-name personalization on opener
cards, where the steady preset matches the explanation-card baseline).

Latency caveat (plan §runtime TTS): EL from us-east-1 → India is ~500ms vs
Google's ~200ms. Personalized cards can't be prefetched (need student name
at session start). Accepted: ~5% of cards have `{student_name}`, the
pedagogical tone of personalized openers benefits from the warm voice.
"""

import asyncio
import io
import json
import logging
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from auth.middleware.auth_middleware import get_optional_user
from book_ingestion_v2.services.audio_generation_service import (
    EL_MODEL_ID,
    EL_PEER_VOICE_ID,
    EL_TUTOR_VOICE_ID,
    EL_VOICE_SETTINGS_STEADY,
    PEER_VOICE,
    TUTOR_VOICE,
    normalize_tts_text,
)
from config import get_settings
from database import get_db
from shared.services.tts_config_service import resolve_tts_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text-to-speech", tags=["tts"])

MAX_TEXT_LENGTH = 5000  # Google Cloud TTS limit (EL accepts more, but cap matches)

# Reuse the gRPC client across requests — creating a new client per request
# adds significant connection setup overhead under burst TTS load.
_tts_client: texttospeech.TextToSpeechClient | None = None
_tts_api_key: str | None = None

_EL_RETRY_ATTEMPTS = 3
_EL_RETRY_BASE_SECONDS = 2.0
_EL_TIMEOUT_SECONDS = 60.0


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
    # Allowlisted role; never accept arbitrary voice IDs from the frontend.
    # Baatcheet uses "peer" for Meera's lines; everything else falls through
    # to the tutor voice.
    voice_role: Literal["tutor", "peer"] = "tutor"


def _synth_google(text: str, voice_role: str) -> bytes:
    client = _get_tts_client()
    if voice_role == "peer":
        lang_code, voice_name = PEER_VOICE
    else:
        # Tutor voice — en-IN-Chirp3-HD-Orus across all languages.
        # See `audio_generation_service.VOICE_MAP` for the rationale.
        lang_code, voice_name = TUTOR_VOICE
    voice = texttospeech.VoiceSelectionParams(
        language_code=lang_code, name=voice_name,
    )
    # Chirp 3 HD does not support pitch/rate adjustment
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content


def _synth_elevenlabs(text: str, voice_role: str) -> bytes:
    """ElevenLabs v3 single-voice synth with the steady preset.

    No per-line emotion at runtime — the runtime endpoint serves
    `{student_name}` openers, which match explanation-card pacing rather
    than baatcheet emotion-tagged dialogue. Retries on rate limit / 5xx.
    """
    settings = get_settings()
    api_key = settings.elevenlabs_api_key
    if not api_key:
        raise HTTPException(
            status_code=500, detail="ElevenLabs API key not configured",
        )
    voice_id = EL_PEER_VOICE_ID if voice_role == "peer" else EL_TUTOR_VOICE_ID
    body = {
        "text": text,
        "model_id": EL_MODEL_ID,
        "voice_settings": EL_VOICE_SETTINGS_STEADY,
    }
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    last_err: Exception | None = None
    for attempt in range(1, _EL_RETRY_ATTEMPTS + 1):
        try:
            req = Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                method="POST",
            )
            with urlopen(req, timeout=_EL_TIMEOUT_SECONDS) as resp:
                return resp.read()
        except HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code == 429 or 500 <= e.code < 600:
                last_err = RuntimeError(
                    f"ElevenLabs HTTP {e.code} (attempt {attempt}/"
                    f"{_EL_RETRY_ATTEMPTS}): {detail}"
                )
                logger.warning(str(last_err))
            else:
                # 4xx (auth, bad request, quota) — fail fast
                raise HTTPException(
                    status_code=502,
                    detail=f"ElevenLabs HTTP {e.code}: {detail}",
                ) from e
        except (URLError, TimeoutError) as e:
            # `urlopen(timeout=...)` raises `TimeoutError` on socket read
            # timeout — NOT a `URLError` subclass, so catch explicitly.
            last_err = RuntimeError(
                f"ElevenLabs network error (attempt {attempt}/"
                f"{_EL_RETRY_ATTEMPTS}): {e}"
            )
            logger.warning(str(last_err))
        if attempt < _EL_RETRY_ATTEMPTS:
            time.sleep(_EL_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    raise HTTPException(
        status_code=502,
        detail=f"ElevenLabs synthesis failed: {last_err}",
    )


@router.post("")
async def text_to_speech(
    request: TTSRequest,
    current_user=Depends(get_optional_user),
    db: DBSession = Depends(get_db),
):
    """Convert text to speech via the configured TTS provider.

    Provider resolves admin DB row → env → default on every call so the
    admin toggle takes effect for the next request without a redeploy.
    The DB lookup is one indexed primary-key read, negligible vs the
    synthesis call itself.
    """
    provider = resolve_tts_provider(db)
    text = normalize_tts_text(request.text)

    try:
        if provider == "elevenlabs":
            audio_bytes = await asyncio.to_thread(
                _synth_elevenlabs, text, request.voice_role,
            )
        elif provider == "google_tts":
            audio_bytes = await asyncio.to_thread(
                _synth_google, text, request.voice_role,
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Unknown tts_provider {provider!r}",
            )

        audio_stream = io.BytesIO(audio_bytes)
        return StreamingResponse(
            audio_stream,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("TTS generation failed")
        raise HTTPException(status_code=500, detail="Text-to-speech generation failed")
