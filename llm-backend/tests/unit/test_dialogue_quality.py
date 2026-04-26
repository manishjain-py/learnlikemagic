"""Tests for the Baatcheet dialogue-quality work (Layers 1, 2, 3, 4).

Covers:
- Adapter `effort_map` exposes all 5 Claude CLI levels distinctly.
- Adapter fallback default is `"max"` (not the old `"high"`).
- LLMService stores `reasoning_effort` from construction and honors it as
  the default when caller passes the sentinel `"none"`.
- Explicit `reasoning_effort=` on `.call()` overrides the construction default.
- LLMConfigService returns `reasoning_effort` alongside provider/model.
- BaatcheetDialogueGeneratorService._extract_key_concepts produces a flat
  bulleted list from variant A's teaching-type cards (skipping welcome,
  check_in, summary).
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
    BaatcheetDialogueGeneratorService,
)
from shared.services.llm_service import LLMService


# ─── Adapter — effort_map (Layer 1) ─────────────────────────────────────


def test_adapter_effort_map_has_five_distinct_levels(monkeypatch):
    """Each of low/medium/high/xhigh/max should map to a DISTINCT CLI value.

    Pre-fix the adapter conflated xhigh→max. Post-fix all five round-trip.
    """
    from shared.services.claude_code_adapter import ClaudeCodeAdapter

    captured: list[str] = []

    def fake_run(cmd, **kwargs):
        # Capture the value passed to --effort
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


def test_adapter_effort_default_is_max(monkeypatch):
    """When caller passes 'none' or empty, fallback should be 'max', not 'high'."""
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


def test_extract_key_concepts_skips_non_teaching_cards():
    """Welcome, check_in, summary cards are excluded; concept/visual/example included."""
    fake_va = SimpleNamespace(cards_json=[
        {"card_idx": 1, "card_type": "welcome", "title": "Welcome!"},
        {"card_idx": 2, "card_type": "concept", "title": "The ×10 Pattern"},
        {"card_idx": 3, "card_type": "visual", "title": "Place Value Chart"},
        {"card_idx": 4, "card_type": "check_in", "title": "Quick check!"},
        {"card_idx": 5, "card_type": "example", "title": "Reading 47,352"},
        {"card_idx": 6, "card_type": "summary", "title": "All Done"},
    ])
    out = BaatcheetDialogueGeneratorService._extract_key_concepts(fake_va)
    assert out == (
        "- The ×10 Pattern\n- Place Value Chart\n- Reading 47,352"
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
