"""Unit tests for evaluation/session_runner.py — SessionRunner class."""

import asyncio
import json
import subprocess
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, mock_open

import httpx

from evaluation.config import EvalConfig
from evaluation.session_runner import SessionRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> EvalConfig:
    defaults = dict(
        openai_api_key="test-key-fake",
        anthropic_api_key="test-key-fake",
        topic_id="guideline-1",
        max_turns=3,
        eval_llm_provider="openai",
        server_startup_timeout=2,
        health_check_interval=0.1,
    )
    defaults.update(overrides)
    return EvalConfig(**defaults)


def _make_simulator() -> MagicMock:
    sim = MagicMock()
    sim.generate_response.return_value = "I think the answer is 5!"
    return sim


# ---------------------------------------------------------------------------
# Tests — __init__
# ---------------------------------------------------------------------------


class TestSessionRunnerInit:
    def test_init_defaults(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        assert runner.config is config
        assert runner.simulator is sim
        assert runner.run_dir == tmp_path
        assert runner.skip_server_management is False
        assert runner.on_turn is None
        assert runner.server_process is None
        assert runner.conversation == []
        assert runner.session_id is None
        assert runner.session_metadata is None
        assert not runner._log_file.closed

        runner.cleanup()

    def test_init_with_options(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        callback = MagicMock()
        runner = SessionRunner(
            config, sim, tmp_path,
            skip_server_management=True,
            on_turn=callback,
        )

        assert runner.skip_server_management is True
        assert runner.on_turn is callback

        runner.cleanup()

    def test_init_creates_log_file(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        assert (tmp_path / "run.log").exists()
        runner.cleanup()


# ---------------------------------------------------------------------------
# Tests — _log
# ---------------------------------------------------------------------------


class TestLog:
    def test_log_writes_to_file(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        runner._log("Hello world")
        runner._log("Second message")
        runner._log_file.flush()

        content = (tmp_path / "run.log").read_text()
        assert "Hello world" in content
        assert "Second message" in content
        runner.cleanup()

    def test_log_format_has_timestamp(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        runner._log("test msg")
        runner._log_file.flush()

        content = (tmp_path / "run.log").read_text()
        # Timestamp format: [YYYY-MM-DD HH:MM:SS.mmm]
        assert "[20" in content
        assert "]" in content
        runner.cleanup()


# ---------------------------------------------------------------------------
# Tests — start_server (skip_server_management=True)
# ---------------------------------------------------------------------------


class TestStartServerSkipped:
    @patch("evaluation.session_runner.httpx.Client")
    def test_start_server_skip_healthy(self, mock_httpx_cls, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get.return_value = mock_resp

        runner.start_server()  # should not raise
        runner.cleanup()

    @patch("evaluation.session_runner.httpx.Client")
    def test_start_server_skip_unhealthy(self, mock_httpx_cls, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with pytest.raises(RuntimeError, match="not reachable"):
            runner.start_server()
        runner.cleanup()

    @patch("evaluation.session_runner.httpx.Client")
    def test_start_server_skip_read_timeout(self, mock_httpx_cls, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ReadTimeout("timeout")

        with pytest.raises(RuntimeError, match="not reachable"):
            runner.start_server()
        runner.cleanup()


# ---------------------------------------------------------------------------
# Tests — start_server (subprocess mode)
# ---------------------------------------------------------------------------


class TestStartServerSubprocess:
    @patch("evaluation.session_runner.time.sleep")
    @patch("evaluation.session_runner.httpx.Client")
    @patch("evaluation.session_runner.subprocess.Popen")
    def test_start_server_subprocess_healthy(self, mock_popen, mock_httpx_cls, mock_sleep, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=False)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get.return_value = mock_resp

        runner.start_server()

        mock_popen.assert_called_once()
        assert runner.server_process is mock_proc
        runner.cleanup()

    @patch("evaluation.session_runner.time.sleep")
    @patch("evaluation.session_runner.httpx.Client")
    @patch("evaluation.session_runner.subprocess.Popen")
    def test_start_server_subprocess_timeout(self, mock_popen, mock_httpx_cls, mock_sleep, tmp_path):
        # Use a very short real timeout so test runs quickly without mocking time.time
        config = _make_config(server_startup_timeout=0, health_check_interval=0)
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=False)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with pytest.raises(RuntimeError, match="failed to start"):
            runner.start_server()

        # Server should have been stopped after timeout
        mock_proc.terminate.assert_called()
        runner.cleanup()


# ---------------------------------------------------------------------------
# Tests — stop_server
# ---------------------------------------------------------------------------


class TestStopServer:
    def test_stop_server_skip_mode(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        runner.stop_server()  # should not raise, no server_process
        runner.cleanup()

    def test_stop_server_no_process(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        runner.stop_server()  # should not raise
        runner.cleanup()

    def test_stop_server_terminates_process(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_proc = MagicMock()
        runner.server_process = mock_proc

        runner.stop_server()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=5)
        assert runner.server_process is None
        runner.cleanup()

    def test_stop_server_kills_on_timeout(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_proc = MagicMock()
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="uvicorn", timeout=5), None]
        runner.server_process = mock_proc

        runner.stop_server()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert runner.server_process is None
        runner.cleanup()


# ---------------------------------------------------------------------------
# Tests — _create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    @patch("evaluation.session_runner.httpx.Client")
    def test_create_session_success(self, mock_httpx_cls, tmp_path):
        config = _make_config(topic_id="fractions-basics")
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"session_id": "new-session-123"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        result = runner._create_session()

        assert result == "new-session-123"
        assert runner.session_id == "new-session-123"

        # Verify the POST payload
        call_args = mock_client.post.call_args
        body = call_args.kwargs["json"]
        assert body["student"]["id"] == "eval-student"
        assert body["goal"]["guideline_id"] == "fractions-basics"

        runner.cleanup()

    @patch("evaluation.session_runner.httpx.Client")
    def test_create_session_http_error(self, mock_httpx_cls, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock()
        )
        mock_client.post.return_value = mock_resp

        with pytest.raises(httpx.HTTPStatusError):
            runner._create_session()

        runner.cleanup()


# ---------------------------------------------------------------------------
# Tests — run_session
# ---------------------------------------------------------------------------


class TestRunSession:
    @patch("evaluation.session_runner.httpx.Client")
    @patch("evaluation.session_runner.asyncio.run")
    def test_run_session_success(self, mock_asyncio_run, mock_httpx_cls, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        # Mock _create_session via httpx
        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)

        # First call: create session POST
        create_resp = MagicMock()
        create_resp.json.return_value = {"session_id": "sess-run-1"}
        create_resp.raise_for_status = MagicMock()

        # Third call: fetch final state GET
        state_resp = MagicMock()
        state_resp.json.return_value = {"session_id": "sess-run-1", "state": "complete"}
        state_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = create_resp
        mock_client.get.return_value = state_resp

        # Mock asyncio.run to simulate conversation
        def fake_asyncio_run(coro):
            # Close the coroutine properly
            coro.close()
            runner.conversation = [
                {"role": "tutor", "content": "Hello!", "turn": 0},
                {"role": "student", "content": "Hi!", "turn": 1},
            ]

        mock_asyncio_run.side_effect = fake_asyncio_run

        result = runner.run_session()

        assert len(result) == 2
        assert result[0]["role"] == "tutor"
        assert runner.session_id == "sess-run-1"
        assert runner.session_metadata == {"session_id": "sess-run-1", "state": "complete"}

        runner.cleanup()

    @patch("evaluation.session_runner.httpx.Client")
    @patch("evaluation.session_runner.asyncio.run")
    def test_run_session_ws_error_with_conversation(self, mock_asyncio_run, mock_httpx_cls, tmp_path):
        """If WS errors but conversation has messages, should not raise."""
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)

        create_resp = MagicMock()
        create_resp.json.return_value = {"session_id": "sess-2"}
        create_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = create_resp

        state_resp = MagicMock()
        state_resp.json.return_value = {}
        state_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = state_resp

        def fake_asyncio_run(coro):
            coro.close()
            runner.conversation = [{"role": "tutor", "content": "Hi", "turn": 0}]
            raise ConnectionError("WebSocket closed unexpectedly")

        mock_asyncio_run.side_effect = fake_asyncio_run

        result = runner.run_session()
        assert len(result) == 1
        runner.cleanup()

    @patch("evaluation.session_runner.httpx.Client")
    @patch("evaluation.session_runner.asyncio.run")
    def test_run_session_ws_error_no_conversation_raises(self, mock_asyncio_run, mock_httpx_cls, tmp_path):
        """If WS errors and no conversation, should re-raise."""
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)

        create_resp = MagicMock()
        create_resp.json.return_value = {"session_id": "sess-3"}
        create_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = create_resp

        def fake_asyncio_run(coro):
            coro.close()
            raise ConnectionError("WebSocket refused")

        mock_asyncio_run.side_effect = fake_asyncio_run

        with pytest.raises(ConnectionError, match="WebSocket refused"):
            runner.run_session()

        runner.cleanup()

    @patch("evaluation.session_runner.httpx.Client")
    @patch("evaluation.session_runner.asyncio.run")
    def test_run_session_fetch_state_fails(self, mock_asyncio_run, mock_httpx_cls, tmp_path):
        """If fetching final state fails, session_metadata should be {}."""
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)

        create_resp = MagicMock()
        create_resp.json.return_value = {"session_id": "sess-4"}
        create_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = create_resp

        # GET for final state raises
        mock_client.get.side_effect = httpx.ConnectError("gone")

        def fake_asyncio_run(coro):
            coro.close()
            runner.conversation = [{"role": "tutor", "content": "Hello", "turn": 0}]

        mock_asyncio_run.side_effect = fake_asyncio_run

        result = runner.run_session()
        assert runner.session_metadata == {}
        runner.cleanup()


# ---------------------------------------------------------------------------
# Tests — cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_closes_log(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        assert not runner._log_file.closed
        runner.cleanup()
        assert runner._log_file.closed

    def test_cleanup_stops_server(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        mock_proc = MagicMock()
        runner.server_process = mock_proc

        runner.cleanup()

        mock_proc.terminate.assert_called_once()
        assert runner._log_file.closed

    def test_cleanup_idempotent(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path)

        runner.cleanup()
        # Second cleanup should not raise
        runner.cleanup()

    def test_cleanup_skip_server_management(self, tmp_path):
        config = _make_config()
        sim = _make_simulator()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        runner.cleanup()
        assert runner._log_file.closed
