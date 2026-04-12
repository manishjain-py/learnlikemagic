"""Generate TTS audio for explanation card lines and upload to S3.

Runs offline as part of the explanation generation pipeline.
Each line's audio text is synthesized via Google Cloud TTS, uploaded to S3,
and the resulting public URL is stored as audio_url on the line dict.
"""
import logging
from typing import Optional

from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions

from config import get_settings
from shared.utils.s3_client import S3Client

logger = logging.getLogger(__name__)

# Voice config — same as the real-time TTS endpoint
VOICE_MAP = {
    "en": ("en-US", "en-US-Chirp3-HD-Kore"),
    "hi": ("hi-IN", "hi-IN-Chirp3-HD-Kore"),
    "hinglish": ("hi-IN", "hi-IN-Chirp3-HD-Kore"),
}


class AudioGenerationService:
    """Generates TTS audio for explanation card lines and stores them on S3."""

    def __init__(self, language: str = "hinglish"):
        settings = get_settings()
        if not settings.google_cloud_tts_api_key:
            raise RuntimeError("Google Cloud TTS API key not configured")
        self.tts_client = texttospeech.TextToSpeechClient(
            client_options=ClientOptions(api_key=settings.google_cloud_tts_api_key),
        )
        self.s3 = S3Client()
        self.language = language
        lang_code, voice_name = VOICE_MAP.get(language, VOICE_MAP["en"])
        self.voice = texttospeech.VoiceSelectionParams(
            language_code=lang_code, name=voice_name,
        )
        self.audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )
        self.bucket = settings.aws_s3_bucket
        self.region = settings.aws_region

    def _synthesize(self, text: str) -> bytes:
        """Call Google Cloud TTS and return raw MP3 bytes."""
        response = self.tts_client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=self.voice,
            audio_config=self.audio_config,
        )
        return response.audio_content

    def _s3_url(self, key: str) -> str:
        """Construct the public HTTPS URL for an S3 object."""
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

    def generate_for_cards(
        self,
        cards_json: list[dict],
        guideline_id: str,
        variant_key: str,
    ) -> list[dict]:
        """Generate TTS audio for every line in every card.

        Modifies each line dict in-place, adding an 'audio_url' field.
        Lines that already have audio_url are skipped (idempotent).

        Returns the updated cards_json (same list, mutated).
        """
        total = sum(len(c.get("lines", [])) for c in cards_json)
        generated = 0
        skipped = 0
        failed = 0

        for card in cards_json:
            card_idx = card.get("card_idx", 0)
            for line_idx, line in enumerate(card.get("lines", [])):
                if line.get("audio_url"):
                    skipped += 1
                    continue
                audio_text = line.get("audio", "").strip()
                if not audio_text:
                    skipped += 1
                    continue
                try:
                    mp3_bytes = self._synthesize(audio_text)
                    s3_key = f"audio/{guideline_id}/{variant_key}/{card_idx}/{line_idx}.mp3"
                    self.s3.upload_bytes(mp3_bytes, s3_key, content_type="audio/mpeg")
                    line["audio_url"] = self._s3_url(s3_key)
                    generated += 1
                except Exception as e:
                    logger.error(f"TTS/upload failed for {guideline_id}/{variant_key}/card{card_idx}/line{line_idx}: {e}")
                    failed += 1

        logger.info(
            f"Audio generation for {guideline_id}/{variant_key}: "
            f"{generated} generated, {skipped} skipped, {failed} failed (total lines={total})"
        )
        return cards_json

    def generate_for_topic_explanation(
        self,
        explanation,
        *,
        dry_run: bool = False,
    ) -> Optional[list[dict]]:
        """Generate audio for a TopicExplanation record.

        Args:
            explanation: TopicExplanation ORM object with cards_json
            dry_run: If True, count lines but don't generate audio

        Returns:
            Updated cards_json if generated, None if dry_run
        """
        cards = explanation.cards_json
        if not cards:
            return None

        total = sum(len(c.get("lines", [])) for c in cards)
        existing = sum(
            1 for c in cards for line in c.get("lines", []) if line.get("audio_url")
        )

        if dry_run:
            logger.info(
                f"[DRY RUN] {explanation.guideline_id}/{explanation.variant_key}: "
                f"{total} lines, {existing} already have audio"
            )
            return None

        if existing == total:
            logger.info(
                f"Skip {explanation.guideline_id}/{explanation.variant_key}: "
                f"all {total} lines already have audio"
            )
            return cards

        return self.generate_for_cards(
            cards_json=cards,
            guideline_id=explanation.guideline_id,
            variant_key=explanation.variant_key,
        )
