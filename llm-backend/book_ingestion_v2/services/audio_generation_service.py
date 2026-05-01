"""Generate TTS audio for explanation card lines and check-in fields, upload to S3.

Runs offline as part of the explanation generation pipeline. Each audio text
is synthesized via the configured TTS provider (Google Cloud TTS or
ElevenLabs v3), uploaded to S3, and the resulting public URL is stored on
the corresponding dict.

Provider routing is inline (no factory): `__init__` reads the resolved
provider once at construction; `_synthesize` dispatches per call. ElevenLabs
is the future default; Google remains the env-level fallback (admin DB
override resolves first via shared.services.tts_config_service).

Explanation lines use positional S3 keys `{card_idx}/{line_idx}.mp3`.
Check-in fields use card_id-based keys `{card_id}/check_in/{field}.mp3` so
re-insertion at a new card_idx doesn't serve stale audio.
"""
import json
import logging
import re
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions

from config import get_settings
from shared.services.tts_config_service import resolve_tts_provider
from shared.types.emotion import Emotion, canonicalize_emotion
from shared.utils.s3_client import S3Client

# Pre-synthesis text fixes for Chirp 3 HD pronunciation quirks. Empty under
# the current en-IN voice pair — those voices handle "us" / "U.S." cleanly.
# Earlier hi-IN voices misread bare "us" as "U.S.", and the various phonetic
# rewrites we tried ("uss", "uhs", etc.) triggered initialism detection
# instead. Audition results landed on en-IN voices as the right fix; this
# hook is kept so future regressions can be patched in one place without
# replumbing call sites. ElevenLabs v3 doesn't share the quirk but reuses
# the same hook so any future provider-agnostic fixes (e.g. lakh/crore
# pronunciation overrides) live in one place.
_TTS_PRONUNCIATION_FIXES: list[tuple[re.Pattern[str], str]] = []


def normalize_tts_text(text: str) -> str:
    """Apply pre-synthesis fixes for known pronunciation quirks (provider-agnostic)."""
    for pattern, replacement in _TTS_PRONUNCIATION_FIXES:
        text = pattern.sub(replacement, text)
    return text

logger = logging.getLogger(__name__)

# ─── Google voices ────────────────────────────────────────────────────────
# Voice config — same as the real-time TTS endpoint. We standardised on
# en-IN voices after auditioning the en-IN catalog: hi-IN voices misread bare
# English tokens like "us" as "U.S.", and the phonetic-rewrite workaround
# regressed each iteration. en-IN-Chirp3-HD-Orus is the adult-male tutor
# voice (Mr. Verma); en-IN-Chirp3-HD-Leda is the youthful-feminine peer
# voice (Meera) — closest "girl" timbre Chirp 3 HD ships, since the catalog
# has no literal child voices.
TUTOR_VOICE = ("en-IN", "en-IN-Chirp3-HD-Orus")
PEER_VOICE = ("en-IN", "en-IN-Chirp3-HD-Leda")

# Tutor voice keyed by content-language. All map to the same en-IN tutor
# voice now — the language key is preserved so future per-locale routing
# (e.g. dedicated Devanagari pronunciation) can plug back in.
VOICE_MAP = {
    "en": TUTOR_VOICE,
    "hi": TUTOR_VOICE,
    "hinglish": TUTOR_VOICE,
}

# ─── ElevenLabs voices ────────────────────────────────────────────────────
# Locked by audition (PR #137 plan). Both Indian-English shared library
# voices. ElevenLabs prohibits actual child voices industry-wide; Meera is
# an adult voice performing a youthful character.
EL_TUTOR_VOICE_ID = "81uXfTrZ08xcmV31Rvrb"  # Sekhar — Warm & Energetic
EL_PEER_VOICE_ID = "IEBxKtmsE9KTrXUwNazR"   # Amara  — Calm & Intellectual Narrator
EL_MODEL_ID = "eleven_v3"

# Voice settings auto-keyed by emotion presence:
# - Expressive (locked from bake-off) — used when a line carries an emotion
#   tag. Higher style + mid stability lets v3 modulate prosody around the
#   tag.
# - Steady — used for emotion=None (explanation cards, check-in fields,
#   neutral baatcheet lines). High stability + low style keeps the voice
#   consistent across long stretches of monologue.
EL_VOICE_SETTINGS_EXPRESSIVE = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.4,
    "use_speaker_boost": True,
}
EL_VOICE_SETTINGS_STEADY = {
    "stability": 0.7,
    "similarity_boost": 0.75,
    "style": 0.2,
    "use_speaker_boost": True,
}

_EL_RETRY_ATTEMPTS = 3
_EL_RETRY_BASE_SECONDS = 5.0
_EL_TIMEOUT_SECONDS = 120.0


def _voice_for_speaker(speaker: Optional[str], language: str) -> tuple[str, str]:
    """Return (language_code, voice_name) for a given speaker (Google).

    `speaker == "peer"` → Meera's voice.
    Anything else (including None / "tutor" / unknown) → the language-mapped
    tutor voice. This preserves variant A behavior for cards that don't carry
    a speaker field.
    """
    if speaker == "peer":
        return PEER_VOICE
    return VOICE_MAP.get(language, VOICE_MAP["en"])


def _el_voice_id_for_speaker(speaker: Optional[str]) -> str:
    """Return the ElevenLabs voice_id for a given speaker."""
    if speaker == "peer":
        return EL_PEER_VOICE_ID
    return EL_TUTOR_VOICE_ID


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


class TTSProviderError(RuntimeError):
    """Raised when the configured TTS provider fails persistently.

    Stage callers translate this into a job failure (no per-line fallback
    to a different provider — the plan prohibits mixed-provider audio).
    """


class AudioGenerationService:
    """Generates TTS audio for explanation lines and check-in fields, stores them on S3.

    Provider is chosen at construction:
      provider = "google_tts" → Google Cloud TTS (Chirp 3 HD, no emotion control)
      provider = "elevenlabs" → ElevenLabs v3 (emotion via [tag] prefix)

    Constructor args override settings; pass `None` (default) to read from
    Settings.
    """

    def __init__(
        self,
        language: str = "hinglish",
        *,
        provider: Optional[str] = None,
        elevenlabs_api_key: Optional[str] = None,
        db=None,
    ):
        """Construct the service for the active TTS provider.

        Resolution order for `provider`:
          1. Explicit `provider=` arg.
          2. `db` session → admin override row in `llm_config` (component_key='tts').
          3. `Settings.tts_provider` env var.
          4. Hard default `'google_tts'`.

        Pass `db` from FastAPI route handlers / pipeline workers so
        admin toggles take effect on the next service construction.
        """
        settings = get_settings()
        self.language = language
        self.s3 = S3Client()
        self.bucket = settings.aws_s3_bucket
        self.region = settings.aws_region
        if provider is not None:
            self.provider = provider.strip().lower()
        else:
            self.provider = resolve_tts_provider(db)

        if self.provider == "google_tts":
            if not settings.google_cloud_tts_api_key:
                raise RuntimeError("Google Cloud TTS API key not configured")
            self.tts_client = texttospeech.TextToSpeechClient(
                client_options=ClientOptions(api_key=settings.google_cloud_tts_api_key),
            )
            lang_code, voice_name = VOICE_MAP.get(language, VOICE_MAP["en"])
            self.voice = texttospeech.VoiceSelectionParams(
                language_code=lang_code, name=voice_name,
            )
            self.audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
            )
            self.elevenlabs_api_key = None
        elif self.provider == "elevenlabs":
            api_key = elevenlabs_api_key or settings.elevenlabs_api_key
            if not api_key:
                raise RuntimeError("ElevenLabs API key not configured")
            self.elevenlabs_api_key = api_key
            self.tts_client = None
            self.voice = None
            self.audio_config = None
        else:
            raise RuntimeError(
                f"Unknown tts_provider {self.provider!r}; "
                f"expected 'google_tts' or 'elevenlabs'"
            )

    # ─── Provider dispatch ────────────────────────────────────────────────

    def _synthesize(
        self,
        text: str,
        *,
        speaker: Optional[str] = None,
        emotion: Optional[Emotion] = None,
    ) -> bytes:
        """Synthesize text → MP3 bytes via the configured provider.

        `speaker == "peer"` → Meera's voice. Anything else → tutor.
        `emotion` is honored only on the ElevenLabs path; Google ignores it
        (Chirp 3 HD has no SSML / emotion control). Both providers go through
        the same `normalize_tts_text` hook.
        """
        normalized = normalize_tts_text(text)
        if self.provider == "google_tts":
            return self._synthesize_google(normalized, speaker=speaker)
        return self._synthesize_elevenlabs(normalized, speaker=speaker, emotion=emotion)

    def _synthesize_google(
        self,
        text: str,
        *,
        speaker: Optional[str] = None,
    ) -> bytes:
        lang_code, voice_name = _voice_for_speaker(speaker, self.language)
        voice = texttospeech.VoiceSelectionParams(
            language_code=lang_code, name=voice_name,
        )
        response = self.tts_client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=voice,
            audio_config=self.audio_config,
        )
        return response.audio_content

    def _synthesize_elevenlabs(
        self,
        text: str,
        *,
        speaker: Optional[str] = None,
        emotion: Optional[Emotion] = None,
    ) -> bytes:
        """Call ElevenLabs v3 single-voice TTS; return raw MP3 bytes.

        Voice settings are auto-keyed: emotion present → expressive preset
        (the bake-off values); emotion None → steady preset (high stability,
        low style) for clean monologue. Retries 3× with exponential backoff
        on rate limits / 5xx, then raises TTSProviderError. No fallback to
        Google — mixed-provider audio is not allowed (plan §risks).
        """
        emotion = canonicalize_emotion(emotion)
        voice_id = _el_voice_id_for_speaker(speaker)
        if emotion is not None:
            payload_text = f"[{emotion.value}] {text}"
            voice_settings = EL_VOICE_SETTINGS_EXPRESSIVE
        else:
            payload_text = text
            voice_settings = EL_VOICE_SETTINGS_STEADY
        body = {
            "text": payload_text,
            "model_id": EL_MODEL_ID,
            "voice_settings": voice_settings,
        }
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        last_err: Optional[Exception] = None
        for attempt in range(1, _EL_RETRY_ATTEMPTS + 1):
            try:
                req = Request(
                    url,
                    data=json.dumps(body).encode("utf-8"),
                    headers={
                        "xi-api-key": self.elevenlabs_api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    method="POST",
                )
                with urlopen(req, timeout=_EL_TIMEOUT_SECONDS) as resp:
                    return resp.read()
            except HTTPError as e:
                # Retry on rate limit + 5xx; surface 4xx (auth, bad request,
                # quota exhausted) immediately so the stage fails fast.
                detail = e.read().decode("utf-8", "replace")[:400]
                if e.code == 429 or 500 <= e.code < 600:
                    last_err = TTSProviderError(
                        f"ElevenLabs HTTP {e.code} (attempt {attempt}/"
                        f"{_EL_RETRY_ATTEMPTS}): {detail}"
                    )
                    logger.warning(str(last_err))
                else:
                    raise TTSProviderError(
                        f"ElevenLabs HTTP {e.code}: {detail}"
                    ) from e
            except URLError as e:
                last_err = TTSProviderError(
                    f"ElevenLabs network error (attempt {attempt}/"
                    f"{_EL_RETRY_ATTEMPTS}): {e}"
                )
                logger.warning(str(last_err))
            if attempt < _EL_RETRY_ATTEMPTS:
                time.sleep(_EL_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
        raise last_err or TTSProviderError("ElevenLabs synthesis failed")

    def _s3_url(self, key: str) -> str:
        """Construct the public HTTPS URL for an S3 object."""
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

    def _synth_and_upload(
        self,
        text: str,
        s3_key: str,
        *,
        speaker: Optional[str] = None,
        emotion: Optional[Emotion] = None,
    ) -> str:
        """Synthesize text → MP3 → upload to S3 → return public URL."""
        mp3_bytes = self._synthesize(text, speaker=speaker, emotion=emotion)
        self.s3.upload_bytes(mp3_bytes, s3_key, content_type="audio/mpeg")
        return self._s3_url(s3_key)

    def generate_for_cards(
        self,
        cards_json: list[dict],
        guideline_id: str,
        variant_key: str,
        *,
        force: bool = False,
    ) -> list[dict]:
        """Generate TTS audio for every line and check-in field in every card.

        Mutates each dict in-place, adding the corresponding URL field. Items
        that already have a URL are skipped (idempotent) unless `force=True`,
        in which case the existing URL is overwritten with a freshly
        synthesized clip. S3 keys are deterministic per
        (guideline, variant, card, line/field), so overwrites land at the
        same URL — no orphan cleanup needed. Items whose text is empty are
        always skipped regardless of force. Returns the same cards_json
        list (mutated).

        Variant A explanation cards: speaker resolves to the language-mapped
        tutor voice (no per-card speaker field), and `emotion=None` so the
        ElevenLabs path uses the steady preset.
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
                if line.get("audio_url") and not force:
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
                if check_in.get(url_field) and not force:
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
            f"Audio generation for {guideline_id}/{variant_key} "
            f"(provider={self.provider}, force={force}): "
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
        force: bool = False,
    ) -> Optional[list[dict]]:
        """Generate audio for a TopicExplanation record.

        Args:
            explanation: TopicExplanation ORM object with cards_json
            dry_run: If True, count items but don't generate audio
            force: If True, re-synthesize every line and check-in field
                even when an `audio_url` is already populated. S3 keys are
                deterministic so the new clip overwrites the old at the
                same URL.

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

        if total > 0 and existing == total and not force:
            logger.info(
                f"Skip {explanation.guideline_id}/{explanation.variant_key}: "
                f"all {total} items already have audio"
            )
            return cards

        return self.generate_for_cards(
            cards_json=cards,
            guideline_id=explanation.guideline_id,
            variant_key=explanation.variant_key,
            force=force,
        )

    # ─── Baatcheet ────────────────────────────────────────────────────────

    def generate_for_topic_dialogue(
        self, dialogue, *, dry_run: bool = False, force: bool = False,
    ) -> Optional[list[dict]]:
        """Generate audio for a TopicDialogue record.

        - Skips lines on cards flagged `includes_student_name=True` (the
          frontend handles these via runtime TTS at session start so the
          student's actual name can be substituted into the audio).
        - Routes voice per `card.speaker` ("peer" → Meera; otherwise tutor).
        - Routes emotion per `line.emotion` on the ElevenLabs path
          (canonicalized via shared.types.emotion); Google ignores it.
        - S3 keys live in a parallel namespace
          `audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3`. Variant A
          keys are unchanged.
        - `card_id` is mandatory — dialogue regen rotates content, so
          positional keys would race. Cards without `card_id` are skipped
          with a warning.
        - `force=True` overwrites lines that already have an `audio_url`.
          S3 keys are deterministic per (guideline, dialogue, card_id,
          line/field) so writes overwrite cleanly at the same URL.
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
            card_id = card.get("card_id")
            if not card_id:
                logger.warning(
                    f"Dialogue card at idx {card.get('card_idx')} on "
                    f"{guideline_id} has no card_id — skipping audio gen"
                )
                continue

            for line_idx, line in enumerate(card.get("lines") or []):
                total += 1
                if line.get("audio_url") and not force:
                    skipped += 1
                    continue
                text = (line.get("audio") or "").strip()
                if not text or "{student_name}" in text:
                    skipped += 1
                    continue
                emotion = canonicalize_emotion(line.get("emotion"))
                s3_key = f"audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3"
                try:
                    line["audio_url"] = self._synth_and_upload(
                        text, s3_key, speaker=speaker, emotion=emotion,
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
                # subtree. Emotion is intentionally None — these are
                # static, instructional prompts, so the steady preset is
                # right.
                for text_field, key_suffix, url_field in _check_in_fields_for(check_in):
                    if check_in.get(url_field) and not force:
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
                            text, s3_key, speaker="tutor",
                        )
                        generated += 1
                    except Exception as e:
                        logger.error(
                            f"Dialogue check-in TTS failed for "
                            f"{guideline_id}/{card_id}/{key_suffix}: {e}"
                        )
                        failed += 1

        logger.info(
            f"Dialogue audio for {guideline_id} "
            f"(provider={self.provider}, force={force}): "
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
