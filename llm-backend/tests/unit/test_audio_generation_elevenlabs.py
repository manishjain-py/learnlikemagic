"""Unit tests for the ElevenLabs synthesis path on AudioGenerationService.

Covers:
- Provider dispatch in `_synthesize`
- Voice settings auto-keyed by emotion presence (steady vs expressive)
- `[emotion]` audio tag prepended on the EL request
- Voice ID routed by speaker (tutor vs peer)

The HTTP layer is mocked at `urlopen`; no network calls.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from book_ingestion_v2.services.audio_generation_service import (
    EL_PEER_VOICE_ID,
    EL_TUTOR_VOICE_ID,
    EL_VOICE_SETTINGS_EXPRESSIVE,
    EL_VOICE_SETTINGS_STEADY,
    AudioGenerationService,
    TTSProviderError,
)
from shared.types.emotion import Emotion


def _make_el_service() -> AudioGenerationService:
    """Construct an EL-mode service without running __init__'s S3/Settings code."""
    svc = AudioGenerationService.__new__(AudioGenerationService)
    svc.provider = "elevenlabs"
    svc.elevenlabs_api_key = "test-key"
    svc.tts_client = None
    svc.audio_config = None
    svc.s3 = MagicMock()
    svc.bucket = "test-bucket"
    svc.region = "us-east-1"
    svc.language = "hinglish"
    return svc


def _captured_request(payload_capture: dict, audio_bytes: bytes = b"\x00\xffMP3"):
    """Returns a urlopen replacement that captures the request body + URL.

    Stores `body`, `headers`, `url` on the dict passed in. Returns a
    context-manager-like object whose `read()` yields `audio_bytes`.
    """

    def fake_urlopen(req, timeout=None):
        payload_capture["url"] = req.full_url
        payload_capture["headers"] = dict(req.header_items())
        import json
        payload_capture["body"] = json.loads(req.data.decode("utf-8"))

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner):
                return audio_bytes

        return _Resp()

    return fake_urlopen


class TestProviderDispatch:
    def test_synthesize_routes_to_elevenlabs(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            audio = svc._synthesize("hello", speaker="tutor", emotion=None)
        assert audio == b"\x00\xffMP3"
        assert "text-to-speech" in captured["url"]


class TestVoiceRouting:
    def test_tutor_speaker_uses_tutor_voice_id(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("hi", speaker="tutor")
        assert EL_TUTOR_VOICE_ID in captured["url"]

    def test_peer_speaker_uses_peer_voice_id(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("hi", speaker="peer")
        assert EL_PEER_VOICE_ID in captured["url"]

    def test_unknown_speaker_falls_through_to_tutor(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("hi", speaker=None)
        assert EL_TUTOR_VOICE_ID in captured["url"]


class TestVoiceSettingsAutoKey:
    def test_emotion_set_uses_expressive_preset(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("praise", speaker="tutor", emotion=Emotion.WARM)
        assert captured["body"]["voice_settings"] == EL_VOICE_SETTINGS_EXPRESSIVE

    def test_no_emotion_uses_steady_preset(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("instructional line", speaker="tutor", emotion=None)
        assert captured["body"]["voice_settings"] == EL_VOICE_SETTINGS_STEADY


class TestEmotionTagPrepend:
    def test_emotion_prepends_bracket_tag(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("Spot on!", speaker="tutor", emotion=Emotion.PROUD)
        assert captured["body"]["text"] == "[proud] Spot on!"

    def test_no_emotion_sends_plain_text(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("Plain.", speaker="tutor", emotion=None)
        assert captured["body"]["text"] == "Plain."

    def test_synonym_string_canonicalized_into_tag(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            # Pass a synonym string; service should canonicalize -> "warm".
            svc._synthesize("hello", speaker="tutor", emotion="warmly")
        assert captured["body"]["text"] == "[warm] hello"

    def test_invalid_emotion_dropped_to_steady(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("hello", speaker="tutor", emotion="evil")
        assert captured["body"]["text"] == "hello"
        assert captured["body"]["voice_settings"] == EL_VOICE_SETTINGS_STEADY


class TestPersistentFailure:
    def test_raises_on_persistent_5xx(self):
        from urllib.error import HTTPError

        svc = _make_el_service()

        def fail(req, timeout=None):
            raise HTTPError(
                req.full_url, 503, "service unavailable", {},
                io.BytesIO(b"upstream is down"),
            )

        # Tight retry loop for the test
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=fail,
        ), patch(
            "book_ingestion_v2.services.audio_generation_service.time.sleep",
            return_value=None,
        ):
            with pytest.raises(TTSProviderError):
                svc._synthesize("hello", speaker="tutor")

    def test_4xx_does_not_retry(self):
        from urllib.error import HTTPError

        svc = _make_el_service()
        calls = {"n": 0}

        def fail(req, timeout=None):
            calls["n"] += 1
            raise HTTPError(
                req.full_url, 401, "unauthorized", {},
                io.BytesIO(b"bad key"),
            )

        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=fail,
        ):
            with pytest.raises(TTSProviderError):
                svc._synthesize("hello", speaker="tutor")
        assert calls["n"] == 1

    def test_socket_timeout_triggers_retry(self):
        """A bare TimeoutError from urlopen must trigger retries — it's
        NOT a URLError subclass, so a missing catch would skip the retry
        loop and let the timeout bubble up as a single-attempt failure.
        Regression test for review feedback."""
        svc = _make_el_service()
        calls = {"n": 0}

        def fail(req, timeout=None):
            calls["n"] += 1
            raise TimeoutError("read timeout")

        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=fail,
        ), patch(
            "book_ingestion_v2.services.audio_generation_service.time.sleep",
            return_value=None,
        ):
            with pytest.raises(TTSProviderError):
                svc._synthesize("hello", speaker="tutor")
        # All 3 attempts should have run, not just one.
        assert calls["n"] == 3


class TestHeaders:
    def test_xi_api_key_sent(self):
        svc = _make_el_service()
        captured: dict = {}
        with patch(
            "book_ingestion_v2.services.audio_generation_service.urlopen",
            side_effect=_captured_request(captured),
        ):
            svc._synthesize("hi", speaker="tutor")
        # Header keys are case-preserved by Request, but lookups normalize.
        keys = {k.lower(): v for k, v in captured["headers"].items()}
        assert keys.get("xi-api-key") == "test-key"
        assert keys.get("content-type") == "application/json"
