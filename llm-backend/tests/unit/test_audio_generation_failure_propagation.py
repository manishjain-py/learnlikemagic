"""Regression tests: TTSProviderError must propagate out of the per-line
catches in generate_for_cards / generate_for_topic_dialogue, so a
sustained EL outage aborts the topic stage instead of powering through
every line for hours and committing partial cards_json.

These tests use the same service-stub trick as test_audio_generation.py:
build the service via __new__ so we don't load real Google creds, and
stub `_synth_and_upload` to control which exception each call raises.
"""
from unittest.mock import MagicMock

import pytest

from book_ingestion_v2.services.audio_generation_service import (
    AudioGenerationService,
    TTSProviderError,
)


def _make_service() -> AudioGenerationService:
    svc = AudioGenerationService.__new__(AudioGenerationService)
    svc.provider = "elevenlabs"
    svc.tts_client = None
    svc.s3 = MagicMock()
    svc.bucket = "test-bucket"
    svc.region = "us-east-1"
    svc.audio_config = None
    svc.language = "en"
    svc.elevenlabs_api_key = "test-key"
    return svc


class TestExplanationLinesPropagateProviderError:
    def test_provider_error_aborts_loop(self):
        svc = _make_service()
        calls = {"n": 0}

        def synth(text, s3_key, **_kwargs):
            calls["n"] += 1
            raise TTSProviderError("EL down")

        svc._synth_and_upload = MagicMock(side_effect=synth)

        cards = [
            {
                "card_idx": 1, "card_type": "concept", "title": "C1",
                "lines": [
                    {"audio": "line one", "display": "line one"},
                    {"audio": "line two", "display": "line two"},
                    {"audio": "line three", "display": "line three"},
                ],
            },
        ]
        with pytest.raises(TTSProviderError):
            svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        # Should bail on the first attempt — not power through the next two.
        assert calls["n"] == 1

    def test_non_provider_error_still_tolerated(self):
        """Confirms the narrowing didn't accidentally catch everything —
        a generic exception (e.g. S3 503, encoding bug) is still
        per-line tolerated."""
        svc = _make_service()

        def synth(text, s3_key, **_kwargs):
            raise RuntimeError("S3 hiccup")

        svc._synth_and_upload = MagicMock(side_effect=synth)

        cards = [
            {
                "card_idx": 1, "card_type": "concept", "title": "C1",
                "lines": [
                    {"audio": "line one", "display": "line one"},
                    {"audio": "line two", "display": "line two"},
                ],
            },
        ]
        # Should NOT raise — generic failures are logged and counted.
        result = svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        assert result is cards
        assert svc._synth_and_upload.call_count == 2


class TestCheckInPropagateProviderError:
    def test_provider_error_in_check_in_aborts_loop(self):
        svc = _make_service()

        # Synth succeeds for line audio (fast path), then raises on the
        # first check-in field.
        results = iter(["https://s3/line.mp3"])

        def synth(text, s3_key, **_kwargs):
            try:
                return next(results)
            except StopIteration:
                raise TTSProviderError("EL down")

        svc._synth_and_upload = MagicMock(side_effect=synth)

        cards = [
            {
                "card_idx": 1, "card_type": "check_in",
                "card_id": "ci-1", "title": "Quick check",
                "lines": [{"audio": "instruction", "display": "instruction"}],
                "check_in": {
                    "activity_type": "pick_one",
                    "instruction": "Pick one.",
                    "audio_text": "Pick one.",
                    "hint": "Hint!",
                    "success_message": "Yay!",
                },
            },
        ]
        with pytest.raises(TTSProviderError):
            svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")


class TestDialoguePropagateProviderError:
    def _dialogue_card(self, idx, lines, *, card_id):
        return {
            "card_idx": idx,
            "card_type": "tutor_turn",
            "speaker": "tutor",
            "speaker_name": "Mr. Verma",
            "card_id": card_id,
            "lines": lines,
            "includes_student_name": False,
        }

    def test_provider_error_aborts_dialogue_synthesis(self):
        svc = _make_service()
        calls = {"n": 0}

        def synth(text, s3_key, **_kwargs):
            calls["n"] += 1
            raise TTSProviderError("EL down")

        svc._synth_and_upload = MagicMock(side_effect=synth)

        cards = [
            self._dialogue_card(2, [
                {"audio": "warm hook", "display": "warm hook", "emotion": "warm"},
                {"audio": "second line", "display": "second line", "emotion": None},
            ], card_id="c-2"),
            self._dialogue_card(3, [
                {"audio": "next card", "display": "next card", "emotion": "curious"},
            ], card_id="c-3"),
        ]
        dialogue = MagicMock(guideline_id="g1", cards_json=cards)

        with pytest.raises(TTSProviderError):
            svc.generate_for_topic_dialogue(dialogue)
        # Bailed on first line; subsequent lines/cards never attempted.
        assert calls["n"] == 1

    def test_provider_error_in_dialogue_check_in_aborts(self):
        svc = _make_service()

        # First two synth calls succeed (line audio); third (check-in) raises.
        results = iter(["https://s3/a.mp3", "https://s3/b.mp3"])

        def synth(text, s3_key, **_kwargs):
            try:
                return next(results)
            except StopIteration:
                raise TTSProviderError("EL down")

        svc._synth_and_upload = MagicMock(side_effect=synth)

        cards = [
            {
                "card_idx": 2, "card_type": "check_in",
                "speaker": "tutor", "speaker_name": "Mr. Verma",
                "card_id": "ci-2", "includes_student_name": False,
                "lines": [
                    {"audio": "instruction line one", "display": "i1"},
                    {"audio": "instruction line two", "display": "i2"},
                ],
                "check_in": {
                    "activity_type": "pick_one",
                    "instruction": "Pick one.",
                    "audio_text": "Pick one.",
                    "hint": "Hint!",
                    "success_message": "Yay!",
                },
            },
        ]
        dialogue = MagicMock(guideline_id="g1", cards_json=cards)

        with pytest.raises(TTSProviderError):
            svc.generate_for_topic_dialogue(dialogue)
