"""Unit tests for AudioGenerationService.generate_for_cards / _count_audio_items.

Focuses on the walk logic for explanation lines + check-in fields. The TTS
client and S3 client are fully mocked — no network calls.
"""
from unittest.mock import MagicMock

import pytest

from book_ingestion_v2.services.audio_generation_service import (
    AudioGenerationService,
    _check_in_fields_for,
)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_service() -> AudioGenerationService:
    """Build an AudioGenerationService without running __init__ (avoids loading
    real Google creds). Internal helpers are stubbed to record calls."""
    svc = AudioGenerationService.__new__(AudioGenerationService)
    svc.provider = "google_tts"
    svc.tts_client = MagicMock()
    svc.s3 = MagicMock()
    svc.bucket = "test-bucket"
    svc.region = "us-east-1"
    svc.voice = MagicMock()
    svc.audio_config = MagicMock()
    svc.language = "en"
    svc.elevenlabs_api_key = None
    # Deterministic stub: synth_and_upload returns a URL derived from the key.
    # Accepts kwargs (speaker / emotion) since callers thread them through
    # in the dialogue path.
    svc._synth_and_upload = MagicMock(
        side_effect=lambda text, s3_key, **_: f"https://s3/{s3_key}"
    )
    return svc


def _line(audio: str, audio_url: str | None = None) -> dict:
    line = {"audio": audio, "display": audio}
    if audio_url is not None:
        line["audio_url"] = audio_url
    return line


def _explanation_card(card_idx: int, lines: list[dict], card_id: str | None = None) -> dict:
    card = {
        "card_idx": card_idx,
        "card_type": "concept",
        "title": f"Card {card_idx}",
        "lines": lines,
    }
    if card_id:
        card["card_id"] = card_id
    return card


def _check_in_card(
    *,
    card_idx: int = 5,
    card_id: str | None = "ci-uuid",
    activity_type: str = "pick_one",
    audio_text: str = "Pick the one that makes ten.",
    hint: str = "Think pairs.",
    success_message: str = "Nice work!",
    reveal_text: str = "",
    audio_text_url: str | None = None,
    hint_audio_url: str | None = None,
    success_audio_url: str | None = None,
    reveal_audio_url: str | None = None,
) -> dict:
    check_in: dict = {
        "activity_type": activity_type,
        "audio_text": audio_text,
        "hint": hint,
        "success_message": success_message,
    }
    if reveal_text:
        check_in["reveal_text"] = reveal_text
    if audio_text_url is not None:
        check_in["audio_text_url"] = audio_text_url
    if hint_audio_url is not None:
        check_in["hint_audio_url"] = hint_audio_url
    if success_audio_url is not None:
        check_in["success_audio_url"] = success_audio_url
    if reveal_audio_url is not None:
        check_in["reveal_audio_url"] = reveal_audio_url

    card: dict = {
        "card_idx": card_idx,
        "card_type": "check_in",
        "title": "Quick check",
        "audio_text": audio_text,
        "check_in": check_in,
    }
    if card_id:
        card["card_id"] = card_id
    return card


# ─── _check_in_fields_for ─────────────────────────────────────────────────


class TestCheckInFieldsFor:
    def test_default_three_fields(self):
        fields = _check_in_fields_for({"activity_type": "pick_one"})
        assert [f[0] for f in fields] == ["audio_text", "hint", "success_message"]

    def test_predict_then_reveal_gets_fourth_field(self):
        fields = _check_in_fields_for({"activity_type": "predict_then_reveal"})
        assert [f[0] for f in fields] == [
            "audio_text", "hint", "success_message", "reveal_text",
        ]

    def test_other_types_do_not_get_reveal(self):
        for at in ("true_false", "match_pairs", "fill_blank", "spot_the_error"):
            fields = _check_in_fields_for({"activity_type": at})
            assert "reveal_text" not in [f[0] for f in fields]


# ─── generate_for_cards — explanation lines ───────────────────────────────


class TestGenerateForCardsLines:
    def test_generates_line_audio_with_positional_key(self):
        svc = _make_service()
        cards = [_explanation_card(card_idx=1, lines=[_line("hello")])]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        svc._synth_and_upload.assert_called_once_with(
            "hello", "audio/g1/v1/1/0.mp3"
        )
        assert cards[0]["lines"][0]["audio_url"] == "https://s3/audio/g1/v1/1/0.mp3"

    def test_skips_line_with_existing_url(self):
        svc = _make_service()
        cards = [_explanation_card(
            card_idx=1,
            lines=[_line("hello", audio_url="https://s3/old.mp3")],
        )]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        svc._synth_and_upload.assert_not_called()
        assert cards[0]["lines"][0]["audio_url"] == "https://s3/old.mp3"

    def test_skips_empty_audio_text(self):
        svc = _make_service()
        cards = [_explanation_card(card_idx=1, lines=[_line("   ")])]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        svc._synth_and_upload.assert_not_called()

    def test_continues_after_per_line_failure(self):
        svc = _make_service()

        def flaky(text, key):
            if "fail" in text:
                raise RuntimeError("TTS blew up")
            return f"https://s3/{key}"

        svc._synth_and_upload.side_effect = flaky
        cards = [_explanation_card(
            card_idx=1,
            lines=[_line("fail me"), _line("I'm fine")],
        )]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        assert "audio_url" not in cards[0]["lines"][0] or cards[0]["lines"][0].get("audio_url") is None
        assert cards[0]["lines"][1]["audio_url"] == "https://s3/audio/g1/v1/1/1.mp3"


# ─── generate_for_cards — check-in fields ─────────────────────────────────


class TestGenerateForCardsCheckIns:
    def test_generates_three_check_in_audios_by_default(self):
        svc = _make_service()
        cards = [_check_in_card(card_idx=5, card_id="ci-1")]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")

        calls = {c.args[1] for c in svc._synth_and_upload.call_args_list}
        assert calls == {
            "audio/g1/v1/ci-1/check_in/audio_text.mp3",
            "audio/g1/v1/ci-1/check_in/hint.mp3",
            "audio/g1/v1/ci-1/check_in/success.mp3",
        }
        ci = cards[0]["check_in"]
        assert ci["audio_text_url"] == "https://s3/audio/g1/v1/ci-1/check_in/audio_text.mp3"
        assert ci["hint_audio_url"] == "https://s3/audio/g1/v1/ci-1/check_in/hint.mp3"
        assert ci["success_audio_url"] == "https://s3/audio/g1/v1/ci-1/check_in/success.mp3"

    def test_generates_reveal_audio_for_predict_then_reveal(self):
        svc = _make_service()
        cards = [_check_in_card(
            card_idx=5, card_id="ci-2",
            activity_type="predict_then_reveal",
            reveal_text="Actually, the answer is 12 because...",
        )]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        calls = {c.args[1] for c in svc._synth_and_upload.call_args_list}
        assert "audio/g1/v1/ci-2/check_in/reveal.mp3" in calls
        ci = cards[0]["check_in"]
        assert ci["reveal_audio_url"] == "https://s3/audio/g1/v1/ci-2/check_in/reveal.mp3"

    def test_skips_reveal_for_non_predict_types(self):
        svc = _make_service()
        cards = [_check_in_card(card_idx=5, card_id="ci-3", activity_type="pick_one",
                                reveal_text="should be ignored")]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        calls = [c.args[1] for c in svc._synth_and_upload.call_args_list]
        assert not any("reveal.mp3" in k for k in calls)
        assert "reveal_audio_url" not in cards[0]["check_in"]

    def test_idempotent_skips_fields_with_existing_url(self):
        svc = _make_service()
        cards = [_check_in_card(
            card_idx=5, card_id="ci-4",
            hint_audio_url="https://s3/old-hint.mp3",
        )]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        calls = {c.args[1] for c in svc._synth_and_upload.call_args_list}
        # hint already present, should be skipped
        assert "audio/g1/v1/ci-4/check_in/hint.mp3" not in calls
        # Other two should still be generated
        assert "audio/g1/v1/ci-4/check_in/audio_text.mp3" in calls
        assert "audio/g1/v1/ci-4/check_in/success.mp3" in calls
        # Old URL preserved
        assert cards[0]["check_in"]["hint_audio_url"] == "https://s3/old-hint.mp3"

    def test_skips_empty_field_text(self):
        svc = _make_service()
        cards = [_check_in_card(card_idx=5, card_id="ci-5", hint="   ")]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        calls = {c.args[1] for c in svc._synth_and_upload.call_args_list}
        # hint text is whitespace → skipped entirely
        assert "audio/g1/v1/ci-5/check_in/hint.mp3" not in calls
        assert "hint_audio_url" not in cards[0]["check_in"]

    def test_skips_check_in_without_card_id(self):
        svc = _make_service()
        cards = [_check_in_card(card_idx=5, card_id=None)]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        calls = {c.args[1] for c in svc._synth_and_upload.call_args_list}
        # No card_id → no check-in calls at all
        assert not any("check_in" in k for k in calls)

    def test_non_check_in_card_with_check_in_field_is_ignored(self):
        """Defense in depth: only card_type == 'check_in' triggers check-in walk."""
        svc = _make_service()
        cards = [{
            "card_idx": 1,
            "card_type": "concept",
            "card_id": "c-1",
            "lines": [],
            "check_in": {"activity_type": "pick_one", "hint": "x"},
        }]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        svc._synth_and_upload.assert_not_called()

    def test_per_field_failure_does_not_block_others(self):
        svc = _make_service()

        def flaky(text, key):
            if "hint" in key:
                raise RuntimeError("TTS blew up")
            return f"https://s3/{key}"

        svc._synth_and_upload.side_effect = flaky
        cards = [_check_in_card(card_idx=5, card_id="ci-6")]
        svc.generate_for_cards(cards, guideline_id="g1", variant_key="v1")
        ci = cards[0]["check_in"]
        assert ci.get("audio_text_url")
        assert ci.get("success_audio_url")
        assert "hint_audio_url" not in ci


# ─── _count_audio_items ───────────────────────────────────────────────────


class TestCountAudioItems:
    def test_counts_lines_with_non_empty_text(self):
        svc = _make_service()
        cards = [_explanation_card(
            card_idx=1,
            lines=[
                _line("one", audio_url="https://s3/a.mp3"),
                _line("two"),
                _line("   "),  # empty — not counted
            ],
        )]
        total, existing = svc._count_audio_items(cards)
        assert total == 2
        assert existing == 1

    def test_counts_check_in_fields(self):
        svc = _make_service()
        cards = [_check_in_card(
            card_idx=5, card_id="ci-7",
            audio_text_url="https://s3/audio_text.mp3",
        )]
        total, existing = svc._count_audio_items(cards)
        # 3 always-fields (audio_text, hint, success) all non-empty
        assert total == 3
        # Only audio_text has URL
        assert existing == 1

    def test_counts_reveal_for_predict_then_reveal(self):
        svc = _make_service()
        cards = [_check_in_card(
            card_idx=5, card_id="ci-8",
            activity_type="predict_then_reveal",
            reveal_text="Reveal explanation",
        )]
        total, _ = svc._count_audio_items(cards)
        assert total == 4

    def test_mixed_cards(self):
        svc = _make_service()
        cards = [
            _explanation_card(card_idx=1, lines=[_line("a", audio_url="https://s3/1.mp3")]),
            _check_in_card(card_idx=2, card_id="ci-9",
                           audio_text_url="https://s3/at.mp3",
                           hint_audio_url="https://s3/h.mp3"),
        ]
        total, existing = svc._count_audio_items(cards)
        # 1 line + 3 check-in fields
        assert total == 4
        # line + audio_text + hint
        assert existing == 3


# ─── generate_for_topic_explanation — short-circuit correctness ───────────


class TestGenerateForTopicExplanation:
    def test_skips_when_all_items_have_audio_including_check_ins(self):
        svc = _make_service()
        expl = MagicMock(
            guideline_id="g1", variant_key="v1",
            cards_json=[
                _explanation_card(card_idx=1,
                                  lines=[_line("a", audio_url="https://s3/1.mp3")]),
                _check_in_card(card_idx=2, card_id="ci-10",
                               audio_text_url="https://s3/at.mp3",
                               hint_audio_url="https://s3/h.mp3",
                               success_audio_url="https://s3/s.mp3"),
            ],
        )
        result = svc.generate_for_topic_explanation(expl)
        assert result is not None
        svc._synth_and_upload.assert_not_called()

    def test_does_not_skip_when_check_in_audio_missing(self):
        """Regression — previous code counted only lines, would skip prematurely."""
        svc = _make_service()
        expl = MagicMock(
            guideline_id="g1", variant_key="v1",
            cards_json=[
                _explanation_card(card_idx=1,
                                  lines=[_line("a", audio_url="https://s3/1.mp3")]),
                _check_in_card(card_idx=2, card_id="ci-11"),  # no URLs
            ],
        )
        result = svc.generate_for_topic_explanation(expl)
        assert result is not None
        # Should have been called for the 3 check-in fields
        assert svc._synth_and_upload.call_count == 3

    def test_dry_run_returns_none(self):
        svc = _make_service()
        expl = MagicMock(
            guideline_id="g1", variant_key="v1",
            cards_json=[_explanation_card(card_idx=1, lines=[_line("a")])],
        )
        result = svc.generate_for_topic_explanation(expl, dry_run=True)
        assert result is None
        svc._synth_and_upload.assert_not_called()
