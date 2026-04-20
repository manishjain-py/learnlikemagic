"""Generate TTS audio for explanation card lines and check-in fields, upload to S3.

Runs offline as part of the explanation generation pipeline.
Each audio text is synthesized via Google Cloud TTS, uploaded to S3, and the
resulting public URL is stored on the corresponding dict.

Explanation lines use positional S3 keys `{card_idx}/{line_idx}.mp3`.
Check-in fields use card_id-based keys `{card_id}/check_in/{field}.mp3` so
re-insertion at a new card_idx doesn't serve stale audio.
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

# Check-in fields that get synthesized. (text_field, s3_key_suffix, url_field)
_CHECK_IN_FIELDS_ALWAYS = [
    ("audio_text", "audio_text", "audio_text_url"),
    ("hint", "hint", "hint_audio_url"),
    ("success_message", "success", "success_audio_url"),
]
# Only for predict_then_reveal activity type
_CHECK_IN_FIELD_REVEAL = ("reveal_text", "reveal", "reveal_audio_url")


def _check_in_fields_for(check_in: dict) -> list[tuple[str, str, str]]:
    """Return the list of (text_field, key_suffix, url_field) tuples that apply
    to this check-in based on its activity_type."""
    fields = list(_CHECK_IN_FIELDS_ALWAYS)
    if check_in.get("activity_type") == "predict_then_reveal":
        fields.append(_CHECK_IN_FIELD_REVEAL)
    return fields


class AudioGenerationService:
    """Generates TTS audio for explanation lines and check-in fields, stores them on S3."""

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

    def _synth_and_upload(self, text: str, s3_key: str) -> str:
        """Synthesize text → MP3 → upload to S3 → return public URL."""
        mp3_bytes = self._synthesize(text)
        self.s3.upload_bytes(mp3_bytes, s3_key, content_type="audio/mpeg")
        return self._s3_url(s3_key)

    def generate_for_cards(
        self,
        cards_json: list[dict],
        guideline_id: str,
        variant_key: str,
    ) -> list[dict]:
        """Generate TTS audio for every line and check-in field in every card.

        Mutates each dict in-place, adding the corresponding URL field. Items
        that already have a URL are skipped (idempotent). Items whose text is
        empty are skipped. Returns the same cards_json list (mutated).
        """
        total = 0
        generated = 0
        skipped = 0
        failed = 0

        for card in cards_json:
            card_idx = card.get("card_idx", 0)
            card_id = card.get("card_id")

            # ─── Explanation lines (positional key) ─────────────────────
            for line_idx, line in enumerate(card.get("lines") or []):
                total += 1
                if line.get("audio_url"):
                    skipped += 1
                    continue
                audio_text = (line.get("audio") or "").strip()
                if not audio_text:
                    skipped += 1
                    continue
                s3_key = f"audio/{guideline_id}/{variant_key}/{card_idx}/{line_idx}.mp3"
                try:
                    line["audio_url"] = self._synth_and_upload(audio_text, s3_key)
                    generated += 1
                except Exception as e:
                    logger.error(
                        f"TTS/upload failed for {guideline_id}/{variant_key}/"
                        f"card{card_idx}/line{line_idx}: {e}"
                    )
                    failed += 1

            # ─── Check-in fields (UUID key) ─────────────────────────────
            check_in = card.get("check_in")
            if not (check_in and card.get("card_type") == "check_in"):
                continue
            if not card_id:
                logger.warning(
                    f"Check-in card at idx {card_idx} in "
                    f"{guideline_id}/{variant_key} has no card_id — skipping audio gen"
                )
                continue

            for text_field, key_suffix, url_field in _check_in_fields_for(check_in):
                if check_in.get(url_field):
                    # Count toward total only if it's a real candidate (has text)
                    text = (check_in.get(text_field) or "").strip()
                    if text:
                        total += 1
                        skipped += 1
                    continue
                text = (check_in.get(text_field) or "").strip()
                if not text:
                    continue
                total += 1
                s3_key = (
                    f"audio/{guideline_id}/{variant_key}/{card_id}/check_in/{key_suffix}.mp3"
                )
                try:
                    check_in[url_field] = self._synth_and_upload(text, s3_key)
                    generated += 1
                except Exception as e:
                    logger.error(
                        f"TTS/upload failed for {guideline_id}/{variant_key}/"
                        f"check-in {card_id}/{key_suffix}: {e}"
                    )
                    failed += 1

        logger.info(
            f"Audio generation for {guideline_id}/{variant_key}: "
            f"{generated} generated, {skipped} skipped, {failed} failed "
            f"(total items={total})"
        )
        return cards_json

    @staticmethod
    def count_audio_items(cards: list[dict]) -> tuple[int, int]:
        """Count (total, with_url) across explanation lines and check-in fields.

        Matches the skip/count rules used by generate_for_cards: empty text is
        not counted as a candidate. Static so other services (e.g. pipeline
        status) can call without instantiating the TTS client.
        """
        total = 0
        existing = 0
        for card in cards or []:
            if not isinstance(card, dict):
                continue
            # Explanation lines
            for line in card.get("lines") or []:
                if not isinstance(line, dict):
                    continue
                if not (line.get("audio") or "").strip():
                    continue
                total += 1
                if line.get("audio_url"):
                    existing += 1
            # Check-in fields
            check_in = card.get("check_in")
            if check_in and card.get("card_type") == "check_in":
                for text_field, _, url_field in _check_in_fields_for(check_in):
                    if not (check_in.get(text_field) or "").strip():
                        continue
                    total += 1
                    if check_in.get(url_field):
                        existing += 1
        return total, existing

    # Backwards-compatible alias for existing internal callers.
    def _count_audio_items(self, cards: list[dict]) -> tuple[int, int]:
        return AudioGenerationService.count_audio_items(cards)

    def generate_for_topic_explanation(
        self,
        explanation,
        *,
        dry_run: bool = False,
    ) -> Optional[list[dict]]:
        """Generate audio for a TopicExplanation record.

        Args:
            explanation: TopicExplanation ORM object with cards_json
            dry_run: If True, count items but don't generate audio

        Returns:
            Updated cards_json if generated, None if dry_run or nothing to do
        """
        cards = explanation.cards_json
        if not cards:
            return None

        total, existing = self._count_audio_items(cards)

        if dry_run:
            logger.info(
                f"[DRY RUN] {explanation.guideline_id}/{explanation.variant_key}: "
                f"{total} items, {existing} already have audio"
            )
            return None

        if total > 0 and existing == total:
            logger.info(
                f"Skip {explanation.guideline_id}/{explanation.variant_key}: "
                f"all {total} items already have audio"
            )
            return cards

        return self.generate_for_cards(
            cards_json=cards,
            guideline_id=explanation.guideline_id,
            variant_key=explanation.variant_key,
        )
