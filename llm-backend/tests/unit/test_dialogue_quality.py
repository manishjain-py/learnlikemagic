"""Tests for the Baatcheet dialogue-quality work (Layers 1, 2, 3, 4).

Covers:
- Adapter `_resolve_cli_effort` and the call_sync / call_vision_sync surfaces
  expose all 5 Claude CLI levels distinctly with the right per-method fallback.
- Adapter fallback default for call_sync is `"max"` (not the old `"high"`).
- LLMService stores `reasoning_effort` from construction and honors it as
  the default when caller passes the sentinel `"none"`.
- Explicit `reasoning_effort=` on `.call()` overrides the construction default.
- `.call_stream()` mirrors the same fallback (live tutor streaming path).
- LLMConfigService returns `reasoning_effort` alongside provider/model.
- BaatcheetDialogueGeneratorService._extract_key_concepts pulls from all
  four teaching card_types (concept, example, visual, analogy).
- ChapterChunk constructs cleanly with the kwargs the orchestrator passes
  (regression test for the over-broad regex insertion that crashed Stage 3).
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
    BaatcheetDialogueGeneratorService,
)
from shared.services.llm_service import LLMService


# ─── Adapter — effort_map (Layer 1) ─────────────────────────────────────


def test_resolve_cli_effort_passes_all_five_levels_through():
    """The shared resolver maps each of low/medium/high/xhigh/max to itself."""
    from shared.services.claude_code_adapter import _resolve_cli_effort

    for level in ("low", "medium", "high", "xhigh", "max"):
        assert _resolve_cli_effort(level, fallback="max") == level


def test_resolve_cli_effort_max_does_not_silently_downgrade_to_low():
    """Pre-fix bug: vision adapter mapped xhigh→max but had no `max` key,
    so reasoning_effort='max' fell through to fallback (often 'low')."""
    from shared.services.claude_code_adapter import _resolve_cli_effort

    # Even when fallback is "low" (vision/OCR's choice), an explicit "max"
    # must NOT be downgraded.
    assert _resolve_cli_effort("max", fallback="low") == "max"


def test_resolve_cli_effort_uses_fallback_for_none_or_garbage():
    from shared.services.claude_code_adapter import _resolve_cli_effort

    assert _resolve_cli_effort("none", fallback="max") == "max"
    assert _resolve_cli_effort("", fallback="max") == "max"
    assert _resolve_cli_effort(None, fallback="max") == "max"
    assert _resolve_cli_effort("garbage-value", fallback="low") == "low"


def test_adapter_call_sync_passes_all_five_levels_to_cli(monkeypatch):
    """End-to-end: each of the 5 levels ends up as `--effort <level>` on the CLI."""
    from shared.services.claude_code_adapter import ClaudeCodeAdapter

    captured: list[str] = []

    def fake_run(cmd, **kwargs):
        idx = cmd.index("--effort")
        captured.append(cmd[idx + 1])
        return SimpleNamespace(returncode=0, stdout='{"result": "{}"}', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(ClaudeCodeAdapter, "_ensure_cli_available", lambda self: None)

    adapter = ClaudeCodeAdapter()
    for level in ("low", "medium", "high", "xhigh", "max"):
        captured.clear()
        adapter.call_sync(prompt="x", reasoning_effort=level, json_mode=False)
        assert captured == [level], f"effort {level!r} mapped to {captured!r}"


def test_adapter_call_sync_default_is_max(monkeypatch):
    """When caller passes 'none' or empty, call_sync fallback should be 'max'."""
    from shared.services.claude_code_adapter import ClaudeCodeAdapter

    captured: list[str] = []

    def fake_run(cmd, **kwargs):
        idx = cmd.index("--effort")
        captured.append(cmd[idx + 1])
        return SimpleNamespace(returncode=0, stdout='{"result": "{}"}', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(ClaudeCodeAdapter, "_ensure_cli_available", lambda self: None)

    adapter = ClaudeCodeAdapter()
    adapter.call_sync(prompt="x", reasoning_effort="none", json_mode=False)
    assert captured == ["max"]


def test_adapter_call_vision_sync_does_not_downgrade_max(monkeypatch):
    """Regression: pre-fix call_vision_sync had its own 4-key map and
    silently downgraded 'max' (and 'xhigh') to fallback 'low'."""
    from shared.services.claude_code_adapter import ClaudeCodeAdapter

    captured: list[str] = []

    def fake_run(cmd, **kwargs):
        idx = cmd.index("--effort")
        captured.append(cmd[idx + 1])
        return SimpleNamespace(returncode=0, stdout='{"result": "ocr text"}', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(ClaudeCodeAdapter, "_ensure_cli_available", lambda self: None)

    adapter = ClaudeCodeAdapter()

    # 'max' explicitly requested → must reach CLI as 'max', not fallback 'low'.
    adapter.call_vision_sync(prompt="extract", image_path="/tmp/x.png", reasoning_effort="max")
    assert captured == ["max"]

    # All other levels round-trip too.
    captured.clear()
    for level in ("low", "medium", "high", "xhigh"):
        captured.clear()
        adapter.call_vision_sync(prompt="extract", image_path="/tmp/x.png", reasoning_effort=level)
        assert captured == [level], f"vision effort {level!r} mapped to {captured!r}"


def test_adapter_call_vision_sync_default_fallback_is_low(monkeypatch):
    """Vision/OCR keeps its 'low' fallback (different from call_sync's 'max')."""
    from shared.services.claude_code_adapter import ClaudeCodeAdapter

    captured: list[str] = []

    def fake_run(cmd, **kwargs):
        idx = cmd.index("--effort")
        captured.append(cmd[idx + 1])
        return SimpleNamespace(returncode=0, stdout='{"result": "x"}', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(ClaudeCodeAdapter, "_ensure_cli_available", lambda self: None)

    adapter = ClaudeCodeAdapter()
    adapter.call_vision_sync(prompt="extract", image_path="/tmp/x.png", reasoning_effort="none")
    assert captured == ["low"]


# ─── LLMService — reasoning_effort plumbing (Layer 4) ───────────────────


def test_llm_service_stores_reasoning_effort_from_init():
    svc = LLMService(
        api_key="sk-fake",
        provider="claude_code",
        model_id="claude-opus-4-7",
        reasoning_effort="max",
    )
    assert svc.reasoning_effort == "max"


def test_llm_service_call_uses_init_default_when_caller_passes_none():
    """Caller's 'none' (the default) → service uses self.reasoning_effort."""
    svc = LLMService(
        api_key="sk-fake",
        provider="claude_code",
        model_id="claude-opus-4-7",
        reasoning_effort="max",
    )
    captured: dict = {}

    def fake_call_claude_code(prompt, effort, *args, **kwargs):
        captured["effort"] = effort
        return {"output_text": "{}", "reasoning": None}

    with patch.object(svc, "_call_claude_code", side_effect=fake_call_claude_code):
        svc.call(prompt="hi")  # no explicit reasoning_effort

    assert captured["effort"] == "max"


def test_llm_service_call_explicit_overrides_init_default():
    """Caller's explicit reasoning_effort overrides the construction-time default."""
    svc = LLMService(
        api_key="sk-fake",
        provider="claude_code",
        model_id="claude-opus-4-7",
        reasoning_effort="max",
    )
    captured: dict = {}

    def fake_call_claude_code(prompt, effort, *args, **kwargs):
        captured["effort"] = effort
        return {"output_text": "{}", "reasoning": None}

    with patch.object(svc, "_call_claude_code", side_effect=fake_call_claude_code):
        svc.call(prompt="hi", reasoning_effort="low")

    assert captured["effort"] == "low"


def test_llm_service_call_stream_uses_init_default_when_caller_passes_none():
    """Live tutor regression: pre-fix `call_stream` did NOT honor
    `self.reasoning_effort`, so the `tutor` row's admin setting never reached
    the OpenAI streaming Responses API. Post-fix, the same fallback as
    `.call()` applies — caller's "none" → uses construction-time default."""
    svc = LLMService(
        api_key="sk-fake",
        provider="openai",
        model_id="gpt-5.4-nano",  # Responses API model
        reasoning_effort="max",
    )
    captured: dict = {}

    def fake_stream_responses_api(prompt, model, effort, *args, **kwargs):
        captured["effort"] = effort
        yield "tok"

    with patch.object(svc, "_stream_responses_api", side_effect=fake_stream_responses_api):
        list(svc.call_stream(prompt="hi"))  # no explicit reasoning_effort

    assert captured["effort"] == "max"


def test_llm_service_call_stream_explicit_overrides_init_default():
    """Caller's explicit reasoning_effort on call_stream overrides the construction default."""
    svc = LLMService(
        api_key="sk-fake",
        provider="openai",
        model_id="gpt-5.4-nano",
        reasoning_effort="max",
    )
    captured: dict = {}

    def fake_stream_responses_api(prompt, model, effort, *args, **kwargs):
        captured["effort"] = effort
        yield "tok"

    with patch.object(svc, "_stream_responses_api", side_effect=fake_stream_responses_api):
        list(svc.call_stream(prompt="hi", reasoning_effort="low"))

    assert captured["effort"] == "low"


# ─── LLMConfigService — returns reasoning_effort (Layer 4) ──────────────


def test_llm_config_service_returns_reasoning_effort():
    """get_config and get_all_configs both expose reasoning_effort."""
    from shared.services.llm_config_service import LLMConfigService

    fake_row = SimpleNamespace(
        component_key="x",
        provider="claude_code",
        model_id="claude-opus-4-7",
        reasoning_effort="xhigh",
        description=None,
        updated_at=None,
        updated_by=None,
    )
    fake_repo = MagicMock()
    fake_repo.get_by_key.return_value = fake_row
    fake_repo.get_all.return_value = [fake_row]

    svc = LLMConfigService(db=MagicMock())
    svc.repo = fake_repo

    one = svc.get_config("x")
    assert one == {
        "provider": "claude_code",
        "model_id": "claude-opus-4-7",
        "reasoning_effort": "xhigh",
    }

    all_ = svc.get_all_configs()
    assert all_[0]["reasoning_effort"] == "xhigh"


def test_llm_config_service_falls_back_to_max_when_column_null():
    """If the row's reasoning_effort is None (legacy data), service yields 'max'."""
    from shared.services.llm_config_service import LLMConfigService

    fake_row = SimpleNamespace(
        component_key="x", provider="openai", model_id="gpt-5.2",
        reasoning_effort=None, description=None,
        updated_at=None, updated_by=None,
    )
    fake_repo = MagicMock()
    fake_repo.get_by_key.return_value = fake_row

    svc = LLMConfigService(db=MagicMock())
    svc.repo = fake_repo

    cfg = svc.get_config("x")
    assert cfg["reasoning_effort"] == "max"


# ─── Baatcheet — _extract_key_concepts (Layer 2) ─────────────────────────


def test_extract_key_concepts_includes_all_four_teaching_types():
    """Variant A's vocabulary is concept|example|visual|analogy|summary|welcome.
    All four teaching types must contribute to KEY CONCEPTS — pre-fix, analogy
    cards were silently dropped and the refine-round coverage check could pass
    with a real concept missing."""
    fake_va = SimpleNamespace(cards_json=[
        {"card_idx": 1, "card_type": "welcome", "title": "Welcome!"},
        {"card_idx": 2, "card_type": "concept", "title": "The ×10 Pattern"},
        {"card_idx": 3, "card_type": "analogy", "title": "Pizza-slice analogy"},
        {"card_idx": 4, "card_type": "visual", "title": "Place Value Chart"},
        {"card_idx": 5, "card_type": "example", "title": "Reading 47,352"},
        {"card_idx": 6, "card_type": "summary", "title": "All Done"},
    ])
    out = BaatcheetDialogueGeneratorService._extract_key_concepts(fake_va)
    assert out == (
        "- The ×10 Pattern\n- Pizza-slice analogy\n- Place Value Chart\n- Reading 47,352"
    )


def test_extract_key_concepts_dedupes_and_handles_empty():
    """Duplicate titles collapsed; empty input yields a fallback hint string."""
    fake_va = SimpleNamespace(cards_json=[
        {"card_idx": 1, "card_type": "concept", "title": "Periods"},
        {"card_idx": 2, "card_type": "concept", "title": "Periods"},   # dup
        {"card_idx": 3, "card_type": "concept", "title": "  "},          # whitespace-only
    ])
    out = BaatcheetDialogueGeneratorService._extract_key_concepts(fake_va)
    assert out == "- Periods"

    empty = SimpleNamespace(cards_json=[])
    out2 = BaatcheetDialogueGeneratorService._extract_key_concepts(empty)
    assert "(none extracted" in out2


# ─── ChapterChunk regression — Stage 3 (#1) ─────────────────────────────


def test_chapter_chunk_constructs_with_orchestrator_kwargs():
    """Regression for the over-broad regex insertion that crashed Stage 3.

    The reasoning_effort plumbing pass matched on `model_id=config["model_id"],`
    and inserted a `reasoning_effort=...` kwarg into ChapterChunk(...) calls
    in topic_extraction_orchestrator.py — but ChapterChunk has no such column,
    so every chunk processing run raised TypeError.

    This test instantiates ChapterChunk with the exact kwargs the
    orchestrator's success and failure branches use.
    """
    import uuid
    from book_ingestion_v2.models.database import ChapterChunk

    # Success branch (topic_extraction_orchestrator.py:380-397)
    success = ChapterChunk(
        id=str(uuid.uuid4()),
        chapter_id="c1",
        processing_job_id="j1",
        chunk_index=0,
        page_start=1,
        page_end=2,
        previous_page_text="",
        chapter_summary_before="",
        raw_llm_response="{}",
        topics_detected_json="[]",
        chapter_summary_after="",
        status="completed",
        model_provider="claude_code",
        model_id="claude-opus-4-7",
        prompt_hash="abc123",
    )
    assert success.status == "completed"
    assert success.model_id == "claude-opus-4-7"

    # Failure branch (topic_extraction_orchestrator.py:405-417)
    failure = ChapterChunk(
        id=str(uuid.uuid4()),
        chapter_id="c1",
        processing_job_id="j1",
        chunk_index=0,
        page_start=1,
        page_end=2,
        status="failed",
        error_message="boom",
        model_provider="claude_code",
        model_id="claude-opus-4-7",
    )
    assert failure.status == "failed"
