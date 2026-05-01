"""Unit tests for TTSConfigService resolution + update."""
from unittest.mock import MagicMock

import pytest

from shared.services.tts_config_service import (
    TTS_COMPONENT_KEY,
    TTSConfigService,
    resolve_tts_provider,
)


def _row(provider: str | None = "elevenlabs"):
    row = MagicMock()
    row.provider = provider
    return row


def _service_with_row(row):
    db = MagicMock()
    svc = TTSConfigService.__new__(TTSConfigService)
    svc.db = db
    svc.repo = MagicMock()
    svc.repo.get_by_key.return_value = row
    return svc


class TestGetProvider:
    def test_returns_admin_row_when_valid(self):
        svc = _service_with_row(_row("elevenlabs"))
        assert svc.get_provider() == "elevenlabs"
        svc.repo.get_by_key.assert_called_once_with(TTS_COMPONENT_KEY)

    def test_admin_row_lowercased_and_trimmed(self):
        svc = _service_with_row(_row("  ElevenLabs  "))
        assert svc.get_provider() == "elevenlabs"

    def test_unknown_admin_value_falls_through_to_env(self, monkeypatch):
        from config import reset_settings
        monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
        reset_settings()
        try:
            svc = _service_with_row(_row("garbage"))
            assert svc.get_provider() == "elevenlabs"
        finally:
            monkeypatch.delenv("TTS_PROVIDER", raising=False)
            reset_settings()

    def test_no_admin_row_uses_env(self, monkeypatch):
        from config import reset_settings
        monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
        reset_settings()
        try:
            svc = _service_with_row(None)
            assert svc.get_provider() == "elevenlabs"
        finally:
            monkeypatch.delenv("TTS_PROVIDER", raising=False)
            reset_settings()

    def test_no_admin_no_env_defaults_to_elevenlabs(self, monkeypatch):
        # Post-PR-#7 cutover: with no admin row and no env override, the
        # Pydantic field default in Settings.tts_provider supplies
        # "elevenlabs". (Pre-cutover this was "google_tts".)
        from config import reset_settings
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        reset_settings()
        try:
            svc = _service_with_row(None)
            assert svc.get_provider() == "elevenlabs"
        finally:
            reset_settings()


class TestUpdateProvider:
    def test_persists_valid_provider(self):
        svc = _service_with_row(None)
        svc.repo.upsert.return_value = MagicMock(
            provider="elevenlabs", model_id="eleven_v3",
            updated_at=None, updated_by="admin",
        )
        result = svc.update_provider("elevenlabs", updated_by="admin")
        assert result["provider"] == "elevenlabs"
        svc.repo.upsert.assert_called_once()
        kwargs = svc.repo.upsert.call_args.kwargs
        assert kwargs["component_key"] == TTS_COMPONENT_KEY
        assert kwargs["provider"] == "elevenlabs"
        assert kwargs["model_id"] == "eleven_v3"
        svc.db.commit.assert_called_once()

    def test_rejects_unknown_provider(self):
        svc = _service_with_row(None)
        with pytest.raises(ValueError):
            svc.update_provider("aws_polly")

    def test_lowercases_input(self):
        svc = _service_with_row(None)
        svc.repo.upsert.return_value = MagicMock(
            provider="google_tts", model_id="chirp_3_hd",
            updated_at=None, updated_by=None,
        )
        svc.update_provider("GOOGLE_TTS")
        kwargs = svc.repo.upsert.call_args.kwargs
        assert kwargs["provider"] == "google_tts"


class TestResolveTTSProviderHelper:
    def test_with_db_uses_service(self, monkeypatch):
        from config import reset_settings
        monkeypatch.setenv("TTS_PROVIDER", "google_tts")
        reset_settings()
        try:
            db = MagicMock()
            # Build a real service bound to the mock DB so resolve_tts_provider's
            # call into TTSConfigService(db) wires the upsert/get path.
            from shared.services import tts_config_service as tts_mod
            from unittest.mock import patch

            row = _row("elevenlabs")
            with patch.object(tts_mod.LLMConfigRepository, "get_by_key", return_value=row):
                assert resolve_tts_provider(db) == "elevenlabs"
        finally:
            monkeypatch.delenv("TTS_PROVIDER", raising=False)
            reset_settings()

    def test_without_db_uses_env_only(self, monkeypatch):
        from config import reset_settings
        monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
        reset_settings()
        try:
            assert resolve_tts_provider(None) == "elevenlabs"
        finally:
            monkeypatch.delenv("TTS_PROVIDER", raising=False)
            reset_settings()
