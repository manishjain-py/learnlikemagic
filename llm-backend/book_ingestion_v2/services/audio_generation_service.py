"""Generate TTS audio for explanation card lines and check-in fields, upload to S3.

Runs offline as part of the explanation generation pipeline.
Each audio text is synthesized via Google Cloud TTS, uploaded to S3, and the
resulting public URL is stored on the corresponding dict.

Explanation lines use positional S3 keys `{card_idx}/{line_idx}.mp3`.
Check-in fields use card_id-based keys `{card_id}/check_in/{field}.mp3` so
re-insertion at a new card_idx doesn't serve stale audio.
"""
import logging
import re
from typing import Optional

from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions

from config import get_settings
from shared.utils.s3_client import S3Client

# Chirp 3 HD's text normalizer reads the bare English word "us" as the
# country abbreviation "U.S.", especially under the hi-IN voices we use for
# Hinglish/Hindi. Chirp 3 HD doesn't support <sub>/<say-as> SSML, so we
# rewrite the token to a homophone-ish spelling the normalizer parses as a
# regular word. Case-sensitive — leaves the acronym "US" alone.
_TTS_PRONUNCIATION_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bus\b"), "uss"),
]


def normalize_tts_text(text: str) -> str:
    """Apply pre-synthesis fixes for known Chirp 3 HD pronunciation quirks."""
    for pattern, replacement in _TTS_PRONUNCIATION_FIXES:
        text = pattern.sub(replacement, text)
    return text

logger = logging.getLogger(__name__)

# Voice config — same as the real-time TTS endpoint
VOICE_MAP = {
    "en": ("en-US", "en-US-Chirp3-HD-Kore"),
    "hi": ("hi-IN", "hi-IN-Chirp3-HD-Kore"),
    "hinglish": ("hi-IN", "hi-IN-Chirp3-HD-Kore"),
}

# Baatcheet voices — tutor reuses the existing Kore voice (smooth, neutral);
# peer (Meera) gets a distinct hi-IN-Chirp3-HD-* voice. Per Google's published
# Chirp 3 HD voice catalog, `Leda` is documented as a youthful feminine voice,
# which fits Meera's persona (peer-aged, warm, curious) and contrasts most
# audibly with Kore. Pilot the pick during the first dialogue listen-test;
# revisit if it sounds too similar in production audio.
TUTOR_VOICE = ("hi-IN", "hi-IN-Chirp3-HD-Kore")
PEER_VOICE = ("hi-IN", "hi-IN-Chirp3-HD-Leda")


def _voice_for_speaker(speaker: Optional[str], language: str) -> tuple[str, str]:
    """Return (language_code, voice_name) for a given speaker.

    `speaker == "peer"` → Meera's voice.
    Anything else (including None / "tutor" / unknown) → the language-mapped
    tutor voice. This preserves variant A behavior for cards that don't carry
    a speaker field.
    """
    if speaker == "peer":
        return PEER_VOICE
    return VOICE_MAP.get(language, VOICE_MAP["en"])

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

    def _synthesize(
        self,
        text: str,
        voice: Optional["texttospeech.VoiceSelectionParams"] = None,
    ) -> bytes:
        """Call Google Cloud TTS and return raw MP3 bytes.

        `voice` defaults to the instance's language-mapped voice (existing
        variant A behavior). Pass an explicit voice to route per-speaker.
        """
        response = self.tts_client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=normalize_tts_text(text)),
            voice=voice or self.voice,
            audio_config=self.audio_config,
        )
        return response.audio_content

    def _s3_url(self, key: str) -> str:
        """Construct the public HTTPS URL for an S3 object."""
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

    def _synth_and_upload(
        self,
        text: str,
        s3_key: str,
        voice: Optional["texttospeech.VoiceSelectionParams"] = None,
    ) -> str:
        """Synthesize text → MP3 → upload to S3 → return public URL."""
        mp3_bytes = self._synthesize(text, voice=voice)
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

    # ─── Baatcheet ────────────────────────────────────────────────────────

    def generate_for_topic_dialogue(
        self, dialogue, *, dry_run: bool = False,
    ) -> Optional[list[dict]]:
        """Generate audio for a TopicDialogue record.

        - Skips lines on cards flagged `includes_student_name=True` (the
          frontend handles these via runtime TTS at session start so the
          student's actual name can be substituted into the audio).
        - Routes voice per `card.speaker` ("peer" → Meera; otherwise tutor).
        - S3 keys live in a parallel namespace
          `audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3`. Variant A
          keys are unchanged.
        - `card_id` is mandatory — dialogue regen rotates content, so
          positional keys would race. Cards without `card_id` are skipped
          with a warning.
        """
        cards = dialogue.cards_json
        if not cards:
            return None

        guideline_id = dialogue.guideline_id
        total = generated = skipped = failed = 0

        for card in cards:
            if card.get("includes_student_name"):
                continue  # runtime TTS — never pre-render

            speaker = card.get("speaker")
            lang_code, voice_name = _voice_for_speaker(speaker, self.language)
            voice = texttospeech.VoiceSelectionParams(
                language_code=lang_code, name=voice_name,
            )
            card_id = card.get("card_id")
            if not card_id:
                logger.warning(
                    f"Dialogue card at idx {card.get('card_idx')} on "
                    f"{guideline_id} has no card_id — skipping audio gen"
                )
                continue

            for line_idx, line in enumerate(card.get("lines") or []):
                total += 1
                if line.get("audio_url"):
                    skipped += 1
                    continue
                text = (line.get("audio") or "").strip()
                if not text or "{student_name}" in text:
                    skipped += 1
                    continue
                s3_key = f"audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3"
                try:
                    line["audio_url"] = self._synth_and_upload(
                        text, s3_key, voice=voice,
                    )
                    generated += 1
                except Exception as e:
                    logger.error(
                        f"Dialogue TTS failed for {guideline_id}/{card_id}/"
                        f"line{line_idx}: {e}"
                    )
                    failed += 1

            check_in = card.get("check_in")
            if check_in and card.get("card_type") == "check_in":
                # Tutor voice for all check-in fields — PRD §FR-27 (no Meera
                # reactions to real student in V1). Match the existing
                # check-in S3 key shape for variant A but in the dialogue
                # subtree.
                tutor_voice = texttospeech.VoiceSelectionParams(
                    language_code=TUTOR_VOICE[0], name=TUTOR_VOICE[1],
                )
                for text_field, key_suffix, url_field in _check_in_fields_for(check_in):
                    if check_in.get(url_field):
                        if (check_in.get(text_field) or "").strip():
                            total += 1
                            skipped += 1
                        continue
                    text = (check_in.get(text_field) or "").strip()
                    if not text or "{student_name}" in text:
                        continue
                    total += 1
                    s3_key = (
                        f"audio/{guideline_id}/dialogue/{card_id}"
                        f"/check_in/{key_suffix}.mp3"
                    )
                    try:
                        check_in[url_field] = self._synth_and_upload(
                            text, s3_key, voice=tutor_voice,
                        )
                        generated += 1
                    except Exception as e:
                        logger.error(
                            f"Dialogue check-in TTS failed for "
                            f"{guideline_id}/{card_id}/{key_suffix}: {e}"
                        )
                        failed += 1

        logger.info(
            f"Dialogue audio for {guideline_id}: "
            f"{generated} generated, {skipped} skipped, {failed} failed "
            f"(total items={total})"
        )
        return cards

    @staticmethod
    def count_dialogue_audio_items(cards: list[dict]) -> tuple[int, int]:
        """Count (total, with_url) for a dialogue card list — same skip rules
        used by generate_for_topic_dialogue. Used by the pipeline status
        service to surface progress on the audio_synthesis tile when the
        topic has both variant A and a dialogue.
        """
        total = existing = 0
        for card in cards or []:
            if not isinstance(card, dict):
                continue
            if card.get("includes_student_name"):
                continue
            for line in card.get("lines") or []:
                if not isinstance(line, dict):
                    continue
                text = (line.get("audio") or "").strip()
                if not text or "{student_name}" in text:
                    continue
                total += 1
                if line.get("audio_url"):
                    existing += 1
            check_in = card.get("check_in")
            if check_in and card.get("card_type") == "check_in":
                for text_field, _, url_field in _check_in_fields_for(check_in):
                    text = (check_in.get(text_field) or "").strip()
                    if not text or "{student_name}" in text:
                        continue
                    total += 1
                    if check_in.get(url_field):
                        existing += 1
        return total, existing
