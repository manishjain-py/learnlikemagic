"""Tests: LLMConfigService hides + refuses to write the 'tts' row so the
TTS toggle row doesn't pollute the LLM Config admin page.

The `tts` row shares the `llm_config` table but uses the TTS provider
vocabulary (google_tts | elevenlabs), which doesn't match the LLM page's
provider dropdowns — surfacing it there would let an admin overwrite it
with `openai`, silently breaking TTS resolution.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from shared.services.llm_config_service import (
    LLMConfigNotFoundError,
    LLMConfigService,
)


def _row(component_key: str, *, provider="openai", model_id="gpt-5.4"):
    row = MagicMock()
    row.component_key = component_key
    row.provider = provider
    row.model_id = model_id
    row.reasoning_effort = "max"
    row.description = None
    row.updated_at = datetime(2026, 5, 1)
    row.updated_by = "admin"
    return row


def _service(rows):
    svc = LLMConfigService.__new__(LLMConfigService)
    svc.repo = MagicMock()
    svc.repo.get_all.return_value = rows
    svc.repo.get_by_key.side_effect = lambda key: next(
        (r for r in rows if r.component_key == key), None
    )
    svc.repo.upsert = MagicMock()
    return svc


class TestGetAllConfigs:
    def test_excludes_tts_row(self):
        rows = [
            _row("tutor"),
            _row("tts", provider="elevenlabs", model_id="eleven_v3"),
            _row("book_ingestion_v2"),
        ]
        result = _service(rows).get_all_configs()
        keys = {r["component_key"] for r in result}
        assert "tts" not in keys
        assert {"tutor", "book_ingestion_v2"}.issubset(keys)

    def test_no_tts_row_passes_through_normally(self):
        rows = [_row("tutor"), _row("eval_evaluator")]
        result = _service(rows).get_all_configs()
        assert {r["component_key"] for r in result} == {"tutor", "eval_evaluator"}


class TestGetConfig:
    def test_get_tts_raises(self):
        svc = _service([_row("tts", provider="elevenlabs", model_id="eleven_v3")])
        with pytest.raises(LLMConfigNotFoundError):
            svc.get_config("tts")

    def test_get_other_component_works(self):
        svc = _service([_row("tutor")])
        result = svc.get_config("tutor")
        assert result["provider"] == "openai"


class TestUpdateConfig:
    def test_update_tts_refused(self):
        svc = _service([])
        with pytest.raises(LLMConfigNotFoundError):
            svc.update_config(
                component_key="tts", provider="openai", model_id="gpt-5.4",
            )
        # Should never have hit the repo — refusal is at the service layer.
        svc.repo.upsert.assert_not_called()

    def test_update_other_component_passes_through(self):
        svc = _service([])
        svc.repo.upsert.return_value = _row("tutor")
        svc.update_config(
            component_key="tutor", provider="openai", model_id="gpt-5.4",
        )
        svc.repo.upsert.assert_called_once()
