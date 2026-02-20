"""Audio transcription endpoint using OpenAI Whisper."""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from openai import OpenAI
from pydantic import BaseModel

from auth.middleware.auth_middleware import get_optional_user
from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcribe", tags=["transcription"])

ALLOWED_CONTENT_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
}

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB (Whisper API limit)


class TranscriptionResponse(BaseModel):
    text: str


@router.post("", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user=Depends(get_optional_user),
):
    """Transcribe an audio file to text using OpenAI Whisper."""
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {file.content_type}",
        )

    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 25 MB)")

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file")

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    # Map content types to file extensions Whisper expects
    ext_map = {
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/mp4": "mp4",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/flac": "flac",
    }
    ext = ext_map.get(file.content_type or "", "webm")
    filename = f"recording.{ext}"

    try:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, contents),
        )
        return TranscriptionResponse(text=transcript.text)
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed")
