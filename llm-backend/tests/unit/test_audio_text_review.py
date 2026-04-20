"""Unit tests for AudioTextReviewService.

Mocks the LLMService.call boundary only. Tests cover validation, drift guard,
check-in vs line revision paths, error handling, audio_url invalidation, and
stage_snapshots capture.
"""
import json
from unittest.mock import MagicMock

import pytest

from book_ingestion_v2.services.audio_text_review_service import (
    AudioLineRevision,
    AudioTextReviewService,
    CardReviewOutput,
)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_service(llm_response: dict | None = None, raises: Exception | None = None):
    """Build an AudioTextReviewService with a mocked LLMService."""
    llm = MagicMock()
    llm.provider = "openai"
    if raises is not None:
        llm.call.side_effect = raises
    else:
        llm.call.return_value = {"output_text": json.dumps(llm_response or {})}
    llm.parse_json_response = lambda s: json.loads(s)

    db = MagicMock()
    service = AudioTextReviewService(db, llm, language="en")
    return service, llm


def _line(audio: str, display: str = "", audio_url: str | None = None) -> dict:
    line = {"audio": audio, "display": display or audio}
    if audio_url:
        line["audio_url"] = audio_url
    return line


def _explanation_card(card_idx: int = 1, lines: list[dict] | None = None) -> dict:
    return {
        "card_idx": card_idx,
        "card_type": "concept",
        "title": f"Card {card_idx}",
        "lines": lines or [],
    }


def _check_in_card(
    card_idx: int = 5,
    audio_text: str = "",
    instruction: str = "",
    *,
    check_in: dict | None = None,
) -> dict:
    card = {
        "card_idx": card_idx,
        "card_type": "check_in",
        "title": "Quick check",
        "instruction": instruction or "Pick the right one",
        "audio_text": audio_text,
    }
    if check_in is not None:
        card["check_in"] = check_in
    return card


def _guideline():
    g = MagicMock()
    g.topic_title = "Fractions"
    g.topic = "Fractions"
    g.grade = 3
    g.id = "guideline-1"
    return g


# ─── Tests ────────────────────────────────────────────────────────────────


class TestReviewCard:
    """_review_card — the single-card LLM call."""

    def test_returns_empty_revisions_for_clean_card(self):
        service, _ = _make_service(
            llm_response={"card_idx": 1, "revisions": [], "notes": "all clean"}
        )
        card = _explanation_card(lines=[_line("five plus three equals eight")])
        output = service._review_card(card, _guideline())
        assert output is not None
        assert output.revisions == []

    def test_returns_parsed_revisions_for_defective_card(self):
        service, _ = _make_service(
            llm_response={
                "card_idx": 1,
                "revisions": [
                    {
                        "card_idx": 1, "line_idx": 0, "kind": "line",
                        "original_audio": "5+3=8",
                        "revised_audio": "five plus three equals eight",
                        "reason": "symbol leak",
                    }
                ],
                "notes": "",
            }
        )
        card = _explanation_card(lines=[_line("5+3=8")])
        output = service._review_card(card, _guideline())
        assert output is not None
        assert len(output.revisions) == 1
        assert output.revisions[0].revised_audio == "five plus three equals eight"

    def test_returns_none_on_llm_error(self):
        service, _ = _make_service(raises=RuntimeError("LLM down"))
        card = _explanation_card(lines=[_line("hello")])
        output = service._review_card(card, _guideline())
        assert output is None

    def test_strips_audio_url_before_sending_to_llm(self):
        service, llm = _make_service(
            llm_response={"card_idx": 1, "revisions": [], "notes": ""}
        )
        card = _explanation_card(lines=[
            _line("hello", audio_url="https://s3/audio-1.mp3"),
        ])
        service._review_card(card, _guideline())
        # Prompt should not contain the URL
        sent_prompt = llm.call.call_args.kwargs["prompt"]
        assert "audio-1.mp3" not in sent_prompt


class TestValidateRevision:
    """_validate_revision — banned pattern + empty guards."""

    def _rev(self, revised_audio: str) -> AudioLineRevision:
        return AudioLineRevision(
            card_idx=1, line_idx=0, kind="line",
            original_audio="x", revised_audio=revised_audio, reason="test",
        )

    def test_drops_markdown_bold(self):
        service, _ = _make_service()
        assert service._validate_revision(self._rev("this is **bold**")) is False

    def test_drops_standalone_equals(self):
        service, _ = _make_service()
        assert service._validate_revision(self._rev("x = 5")) is False

    def test_drops_emoji(self):
        service, _ = _make_service()
        assert service._validate_revision(self._rev("great job \U0001F600")) is False

    def test_drops_empty_string(self):
        service, _ = _make_service()
        assert service._validate_revision(self._rev("   ")) is False

    def test_accepts_plain_words(self):
        service, _ = _make_service()
        rev = self._rev("five plus three equals eight")
        assert service._validate_revision(rev) is True


class TestApplyRevisions:
    """_apply_revisions — drift guard + audio_url invalidation."""

    def test_applies_line_revision_and_clears_audio_url(self):
        service, _ = _make_service()
        card = _explanation_card(lines=[
            _line("5+3=8", audio_url="https://s3/a.mp3"),
            _line("next line", audio_url="https://s3/b.mp3"),
        ])
        rev = AudioLineRevision(
            card_idx=1, line_idx=0, kind="line",
            original_audio="5+3=8", revised_audio="five plus three equals eight",
            reason="symbol leak",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 1
        assert card["lines"][0]["audio"] == "five plus three equals eight"
        assert card["lines"][0]["audio_url"] is None
        # Other line untouched
        assert card["lines"][1]["audio"] == "next line"
        assert card["lines"][1]["audio_url"] == "https://s3/b.mp3"

    def test_drops_line_revision_on_drift(self):
        service, _ = _make_service()
        card = _explanation_card(lines=[_line("actually different text")])
        rev = AudioLineRevision(
            card_idx=1, line_idx=0, kind="line",
            original_audio="old text",  # drift: doesn't match current
            revised_audio="new text", reason="test",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 0
        assert card["lines"][0]["audio"] == "actually different text"

    def test_drops_line_revision_on_out_of_range_index(self):
        service, _ = _make_service()
        card = _explanation_card(lines=[_line("only line")])
        rev = AudioLineRevision(
            card_idx=1, line_idx=5, kind="line",  # out of range
            original_audio="only line", revised_audio="new", reason="test",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 0

    def test_applies_check_in_revision_to_audio_text_field(self):
        service, _ = _make_service()
        card = _check_in_card(audio_text="Pick 5+3=8")
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_text",
            original_audio="Pick 5+3=8",
            revised_audio="Pick five plus three equals eight",
            reason="symbol leak",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 1
        assert card["audio_text"] == "Pick five plus three equals eight"

    def test_drops_check_in_revision_on_wrong_card_type(self):
        service, _ = _make_service()
        card = _explanation_card()  # card_type == "concept", not "check_in"
        rev = AudioLineRevision(
            card_idx=1, line_idx=None, kind="check_in_text",
            original_audio="x", revised_audio="y", reason="test",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 0

    def test_drops_check_in_revision_on_drift(self):
        service, _ = _make_service()
        card = _check_in_card(audio_text="current text")
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_text",
            original_audio="stale text",  # drift
            revised_audio="new text", reason="test",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 0
        assert card["audio_text"] == "current text"

    def test_check_in_text_also_mirrors_onto_nested_and_clears_url(self):
        """Applying check_in_text mirrors the edit onto check_in.audio_text and
        clears the nested URL so the next synth re-generates."""
        service, _ = _make_service()
        card = _check_in_card(
            audio_text="Pick 5+3=8",
            check_in={
                "activity_type": "pick_one",
                "audio_text": "Pick 5+3=8",
                "audio_text_url": "https://s3/old.mp3",
                "hint": "h", "success_message": "s",
            },
        )
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_text",
            original_audio="Pick 5+3=8",
            revised_audio="Pick five plus three equals eight",
            reason="symbol leak",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 1
        assert card["audio_text"] == "Pick five plus three equals eight"
        assert card["check_in"]["audio_text"] == "Pick five plus three equals eight"
        assert card["check_in"]["audio_text_url"] is None

    def test_applies_check_in_hint_and_clears_hint_url(self):
        service, _ = _make_service()
        card = _check_in_card(
            check_in={
                "activity_type": "pick_one",
                "hint": "2+3=5 so pair with 7",
                "hint_audio_url": "https://s3/old-hint.mp3",
                "success_message": "s",
                "audio_text": "at",
            },
        )
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_hint",
            original_audio="2+3=5 so pair with 7",
            revised_audio="two plus three equals five, so pair it with seven",
            reason="symbol leak",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 1
        ci = card["check_in"]
        assert ci["hint"] == "two plus three equals five, so pair it with seven"
        assert ci["hint_audio_url"] is None
        # success untouched
        assert ci["success_message"] == "s"

    def test_applies_check_in_success_and_clears_url(self):
        service, _ = _make_service()
        card = _check_in_card(
            check_in={
                "activity_type": "true_false",
                "hint": "h",
                "success_message": "Right! 5*2=10.",
                "success_audio_url": "https://s3/old.mp3",
                "audio_text": "at",
            },
        )
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_success",
            original_audio="Right! 5*2=10.",
            revised_audio="Right! five times two equals ten.",
            reason="symbol leak",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 1
        assert card["check_in"]["success_message"] == "Right! five times two equals ten."
        assert card["check_in"]["success_audio_url"] is None

    def test_applies_check_in_reveal_only_for_predict_then_reveal(self):
        service, _ = _make_service()
        card = _check_in_card(
            check_in={
                "activity_type": "predict_then_reveal",
                "hint": "h", "success_message": "s", "audio_text": "at",
                "reveal_text": "Actually, 3*4=12.",
                "reveal_audio_url": "https://s3/old.mp3",
            },
        )
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_reveal",
            original_audio="Actually, 3*4=12.",
            revised_audio="Actually, three times four equals twelve.",
            reason="symbol leak",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 1
        assert card["check_in"]["reveal_text"] == "Actually, three times four equals twelve."
        assert card["check_in"]["reveal_audio_url"] is None

    def test_drops_check_in_reveal_on_non_predict_activity(self):
        service, _ = _make_service()
        card = _check_in_card(
            check_in={
                "activity_type": "pick_one",  # not predict_then_reveal
                "hint": "h", "success_message": "s", "audio_text": "at",
                "reveal_text": "x",
            },
        )
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_reveal",
            original_audio="x", revised_audio="y", reason="test",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 0
        # Original value preserved
        assert card["check_in"]["reveal_text"] == "x"

    def test_drops_check_in_hint_on_drift(self):
        service, _ = _make_service()
        card = _check_in_card(
            check_in={
                "activity_type": "pick_one",
                "hint": "current hint", "success_message": "s", "audio_text": "at",
            },
        )
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_hint",
            original_audio="stale hint",  # drift
            revised_audio="new hint", reason="test",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 0
        assert card["check_in"]["hint"] == "current hint"

    def test_drops_check_in_kind_on_wrong_card_type(self):
        service, _ = _make_service()
        card = _explanation_card()
        for kind in ("check_in_hint", "check_in_success", "check_in_reveal"):
            rev = AudioLineRevision(
                card_idx=1, line_idx=None, kind=kind,
                original_audio="x", revised_audio="y", reason="test",
            )
            applied = service._apply_revisions(card, [rev])
            assert applied == 0, f"Should drop {kind} on non-check-in card"

    def test_drops_check_in_kind_when_check_in_dict_missing(self):
        service, _ = _make_service()
        # Card marked check_in but no nested dict
        card = _check_in_card(audio_text="at")  # No check_in= kwarg
        assert "check_in" not in card
        rev = AudioLineRevision(
            card_idx=5, line_idx=None, kind="check_in_hint",
            original_audio="x", revised_audio="y", reason="test",
        )
        applied = service._apply_revisions(card, [rev])
        assert applied == 0


class TestStripAudioUrls:
    """_strip_audio_urls — pre-LLM sanitizer."""

    def test_strips_line_audio_urls(self):
        service, _ = _make_service()
        card = _explanation_card(lines=[
            _line("a", audio_url="https://s3/a.mp3"),
            _line("b", audio_url="https://s3/b.mp3"),
        ])
        out = service._strip_audio_urls(card)
        assert all("audio_url" not in l for l in out["lines"])
        # Original card untouched (deep-copy)
        assert card["lines"][0]["audio_url"] == "https://s3/a.mp3"

    def test_strips_check_in_nested_audio_urls(self):
        service, _ = _make_service()
        card = _check_in_card(
            audio_text="at",
            check_in={
                "activity_type": "predict_then_reveal",
                "audio_text": "at",
                "hint": "h", "success_message": "s", "reveal_text": "r",
                "audio_text_url": "https://s3/1.mp3",
                "hint_audio_url": "https://s3/2.mp3",
                "success_audio_url": "https://s3/3.mp3",
                "reveal_audio_url": "https://s3/4.mp3",
            },
        )
        out = service._strip_audio_urls(card)
        ci = out["check_in"]
        for url_field in (
            "audio_text_url", "hint_audio_url",
            "success_audio_url", "reveal_audio_url",
        ):
            assert url_field not in ci, f"{url_field} should be stripped"
        # Text content preserved
        assert ci["hint"] == "h"
        # Original card untouched
        assert card["check_in"]["audio_text_url"] == "https://s3/1.mp3"


class TestCollectSnapshot:
    """_collect_snapshot — stage_snapshots capture shape."""

    def test_captures_revisions_proposed_and_applied(self):
        service, _ = _make_service()
        g = _guideline()
        expl = MagicMock(variant_key="variant-1")
        card = _explanation_card(lines=[_line("hello")])
        rev = AudioLineRevision(
            card_idx=1, line_idx=0, kind="line",
            original_audio="hello", revised_audio="hi there", reason="test",
        )
        collector: list = []
        service._collect_snapshot(
            collector, g, expl, card,
            revisions=[rev], applied_count=1,
        )
        assert len(collector) == 1
        entry = collector[0]
        assert entry["stage"] == "audio_text_review"
        assert entry["card_idx"] == 1
        assert entry["card_type"] == "concept"
        assert entry["variant_key"] == "variant-1"
        assert entry["revisions_applied"] == 1
        assert len(entry["revisions_proposed"]) == 1
        assert entry["revisions_proposed"][0]["revised_audio"] == "hi there"

    def test_captures_error_marker_on_llm_failure(self):
        service, _ = _make_service()
        g = _guideline()
        expl = MagicMock(variant_key="variant-1")
        card = _explanation_card()
        collector: list = []
        service._collect_snapshot(
            collector, g, expl, card,
            revisions=[], applied_count=0, error="llm_error",
        )
        assert collector[0]["error"] == "llm_error"


class TestReviewVariantIntegration:
    """_review_variant — end-to-end through the service with a mocked LLM."""

    def test_continues_after_single_card_llm_failure(self):
        """When LLM fails on card 1, other cards still get reviewed."""
        service, llm = _make_service()
        # First call raises, second succeeds
        llm.call.side_effect = [
            RuntimeError("transient"),
            {"output_text": json.dumps({"card_idx": 2, "revisions": [], "notes": ""})},
        ]
        expl = MagicMock(variant_key="v1")
        expl.cards_json = [
            _explanation_card(card_idx=1, lines=[_line("first")]),
            _explanation_card(card_idx=2, lines=[_line("second")]),
        ]
        g = _guideline()
        collector: list = []
        result = service._review_variant(expl, g, stage_collector=collector)
        assert result["cards_reviewed"] == 2
        # First card's snapshot should carry an error marker
        assert collector[0].get("error") == "llm_error"
