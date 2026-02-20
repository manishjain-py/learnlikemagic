"""Unit tests for evaluation/api.py — FastAPI router, endpoints, state management."""

import json
import threading
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from evaluation.api import (
    router,
    EvalStatus,
    _eval_state,
    _eval_lock,
    _update_eval_state,
)


# ---------------------------------------------------------------------------
# App + Client
# ---------------------------------------------------------------------------

_app = FastAPI()
_app.include_router(router)


@pytest.fixture()
def client():
    return TestClient(_app)


@pytest.fixture(autouse=True)
def reset_eval_state():
    """Reset module-level _eval_state before every test."""
    with _eval_lock:
        _eval_state.update({
            "status": EvalStatus.idle,
            "run_id": None,
            "detail": "",
            "turn": 0,
            "max_turns": 0,
            "error": None,
        })
    yield


# ---------------------------------------------------------------------------
# Tests — EvalStatus enum
# ---------------------------------------------------------------------------


class TestEvalStatus:
    def test_enum_values(self):
        assert EvalStatus.idle == "idle"
        assert EvalStatus.loading_persona == "loading_persona"
        assert EvalStatus.running_session == "running_session"
        assert EvalStatus.evaluating == "evaluating"
        assert EvalStatus.generating_reports == "generating_reports"
        assert EvalStatus.complete == "complete"
        assert EvalStatus.failed == "failed"

    def test_enum_count(self):
        assert len(EvalStatus) == 7

    def test_enum_is_str(self):
        for member in EvalStatus:
            assert isinstance(member, str)
            assert member.value == member


# ---------------------------------------------------------------------------
# Tests — _update_eval_state
# ---------------------------------------------------------------------------


class TestUpdateEvalState:
    def test_update_single_field(self):
        _update_eval_state(status=EvalStatus.running_session)
        assert _eval_state["status"] == EvalStatus.running_session

    def test_update_multiple_fields(self):
        _update_eval_state(
            status=EvalStatus.evaluating,
            detail="Running evaluation...",
            turn=3,
            max_turns=10,
        )
        assert _eval_state["status"] == EvalStatus.evaluating
        assert _eval_state["detail"] == "Running evaluation..."
        assert _eval_state["turn"] == 3
        assert _eval_state["max_turns"] == 10

    def test_update_error_field(self):
        _update_eval_state(error="something broke")
        assert _eval_state["error"] == "something broke"

    def test_update_run_id(self):
        _update_eval_state(run_id="run_20260218_120000")
        assert _eval_state["run_id"] == "run_20260218_120000"

    def test_thread_safety(self):
        """Multiple threads updating state should not corrupt it."""
        errors = []

        def updater(val):
            try:
                for _ in range(100):
                    _update_eval_state(turn=val)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert isinstance(_eval_state["turn"], int)


# ---------------------------------------------------------------------------
# Tests — GET /api/evaluation/status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_idle(self, client):
        resp = client.get("/api/evaluation/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["run_id"] is None
        assert data["detail"] == ""
        assert data["turn"] == 0
        assert data["max_turns"] == 0
        assert data["error"] is None

    def test_status_reflects_updates(self, client):
        _update_eval_state(
            status=EvalStatus.evaluating,
            run_id="run_123",
            detail="Evaluating...",
            turn=5,
            max_turns=20,
        )
        resp = client.get("/api/evaluation/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "evaluating"
        assert data["run_id"] == "run_123"
        assert data["turn"] == 5


# ---------------------------------------------------------------------------
# Tests — POST /api/evaluation/start
# ---------------------------------------------------------------------------


class TestStartEvaluation:
    @patch("evaluation.api.threading.Thread")
    def test_start_success(self, mock_thread_cls, client):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        resp = client.post(
            "/api/evaluation/start",
            json={"topic_id": "fractions", "persona_file": "curious.json", "max_turns": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["topic_id"] == "fractions"
        assert data["max_turns"] == 10

        mock_thread.start.assert_called_once()
        mock_thread_cls.assert_called_once()
        call_kwargs = mock_thread_cls.call_args
        assert call_kwargs.kwargs["target"].__name__ == "_run_evaluation_pipeline"
        assert call_kwargs.kwargs["args"] == ("fractions", "curious.json", 10)

    @patch("evaluation.api.threading.Thread")
    def test_start_defaults(self, mock_thread_cls, client):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        resp = client.post("/api/evaluation/start", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic_id"] == ""
        assert data["max_turns"] == 20

    @patch("evaluation.api.threading.Thread")
    def test_start_already_running(self, mock_thread_cls, client):
        _update_eval_state(status=EvalStatus.running_session)

        resp = client.post("/api/evaluation/start", json={"topic_id": "t1"})
        assert resp.status_code == 409
        assert "already running" in resp.json()["detail"]

    @patch("evaluation.api.threading.Thread")
    def test_start_after_complete(self, mock_thread_cls, client):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        _update_eval_state(status=EvalStatus.complete)

        resp = client.post("/api/evaluation/start", json={"topic_id": "t2"})
        assert resp.status_code == 200

    @patch("evaluation.api.threading.Thread")
    def test_start_after_failed(self, mock_thread_cls, client):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        _update_eval_state(status=EvalStatus.failed)

        resp = client.post("/api/evaluation/start", json={"topic_id": "t3"})
        assert resp.status_code == 200

    @patch("evaluation.api.threading.Thread")
    def test_start_updates_state(self, mock_thread_cls, client):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        client.post("/api/evaluation/start", json={"max_turns": 15})
        assert _eval_state["status"] == EvalStatus.loading_persona
        assert _eval_state["max_turns"] == 15
        assert _eval_state["error"] is None

    @patch("evaluation.api.threading.Thread")
    def test_start_no_body(self, mock_thread_cls, client):
        """POST with no JSON body should use defaults."""
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        resp = client.post("/api/evaluation/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic_id"] == ""
        assert data["max_turns"] == 20


# ---------------------------------------------------------------------------
# Tests — POST /api/evaluation/evaluate-session
# ---------------------------------------------------------------------------


class TestEvaluateSession:
    @patch("evaluation.api.threading.Thread")
    def test_evaluate_session_success(self, mock_thread_cls, client):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        resp = client.post(
            "/api/evaluation/evaluate-session",
            json={"session_id": "sess-abc-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["session_id"] == "sess-abc-123"

        mock_thread.start.assert_called_once()
        call_kwargs = mock_thread_cls.call_args
        assert call_kwargs.kwargs["target"].__name__ == "_run_session_evaluation"
        assert call_kwargs.kwargs["args"] == ("sess-abc-123",)

    @patch("evaluation.api.threading.Thread")
    def test_evaluate_session_missing_session_id(self, mock_thread_cls, client):
        resp = client.post("/api/evaluation/evaluate-session", json={})
        assert resp.status_code == 400
        assert "session_id is required" in resp.json()["detail"]

    @patch("evaluation.api.threading.Thread")
    def test_evaluate_session_none_body(self, mock_thread_cls, client):
        """POST with no JSON body should still fail with 400."""
        resp = client.post("/api/evaluation/evaluate-session")
        assert resp.status_code == 400

    @patch("evaluation.api.threading.Thread")
    def test_evaluate_session_already_running(self, mock_thread_cls, client):
        _update_eval_state(status=EvalStatus.evaluating)

        resp = client.post(
            "/api/evaluation/evaluate-session",
            json={"session_id": "sess-123"},
        )
        assert resp.status_code == 409
        assert "already running" in resp.json()["detail"]

    @patch("evaluation.api.threading.Thread")
    def test_evaluate_session_updates_state(self, mock_thread_cls, client):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        client.post(
            "/api/evaluation/evaluate-session",
            json={"session_id": "sess-xyz"},
        )
        assert _eval_state["status"] == EvalStatus.evaluating
        assert _eval_state["detail"] == "Loading session..."
        assert _eval_state["error"] is None


# ---------------------------------------------------------------------------
# Tests — GET /api/evaluation/runs
# ---------------------------------------------------------------------------


class TestListRuns:
    def test_runs_empty_no_dir(self, client, tmp_path):
        with patch("evaluation.api.RUNS_DIR", tmp_path / "nonexistent"):
            resp = client.get("/api/evaluation/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_runs_empty_dir(self, client, tmp_path):
        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_runs_ignores_non_run_dirs(self, client, tmp_path):
        (tmp_path / "not_a_run").mkdir()
        (tmp_path / "some_file.txt").write_text("hello")
        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_runs_ignores_run_without_config(self, client, tmp_path):
        (tmp_path / "run_20260218_120000").mkdir()
        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_runs_with_config_only(self, client, tmp_path):
        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({
            "topic_id": "fractions",
            "started_at": "2026-02-18T12:00:00",
        }))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs")

        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run_20260218_120000"
        assert runs[0]["topic_id"] == "fractions"
        assert runs[0]["message_count"] == 0
        assert runs[0]["avg_score"] is None

    def test_runs_with_full_data(self, client, tmp_path):
        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({
            "topic_id": "fractions",
            "started_at": "2026-02-18T12:00:00",
            "source": "existing_session",
            "source_session_id": "sess-123",
        }))
        (run_dir / "conversation.json").write_text(json.dumps({
            "message_count": 10,
            "messages": [],
        }))
        (run_dir / "evaluation.json").write_text(json.dumps({
            "avg_score": 7.5,
            "scores": {"responsiveness": 8, "pacing": 7},
        }))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs")

        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["message_count"] == 10
        assert runs[0]["avg_score"] == 7.5
        assert runs[0]["scores"]["responsiveness"] == 8
        assert runs[0]["source"] == "existing_session"
        assert runs[0]["source_session_id"] == "sess-123"

    def test_runs_sorted_reverse(self, client, tmp_path):
        for ts in ["20260218_100000", "20260218_120000", "20260218_110000"]:
            d = tmp_path / f"run_{ts}"
            d.mkdir()
            (d / "config.json").write_text(json.dumps({"topic_id": ts}))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs")

        runs = resp.json()
        assert len(runs) == 3
        assert runs[0]["run_id"] == "run_20260218_120000"
        assert runs[1]["run_id"] == "run_20260218_110000"
        assert runs[2]["run_id"] == "run_20260218_100000"

    def test_runs_skips_corrupt_config(self, client, tmp_path):
        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text("NOT VALID JSON")

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs")

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Tests — GET /api/evaluation/runs/{run_id}
# ---------------------------------------------------------------------------


class TestGetRun:
    def test_get_run_not_found(self, client, tmp_path):
        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs/run_nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_get_run_config_only(self, client, tmp_path):
        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({"topic_id": "fracs"}))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs/run_20260218_120000")

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "run_20260218_120000"
        assert data["config"]["topic_id"] == "fracs"
        assert "messages" not in data
        assert "evaluation" not in data

    def test_get_run_full_data(self, client, tmp_path):
        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({"topic_id": "fracs"}))
        (run_dir / "conversation.json").write_text(json.dumps({
            "messages": [{"role": "tutor", "content": "Hi"}],
            "message_count": 1,
        }))
        (run_dir / "evaluation.json").write_text(json.dumps({
            "scores": {"pacing": 9},
            "avg_score": 9.0,
        }))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs/run_20260218_120000")

        data = resp.json()
        assert data["messages"] == [{"role": "tutor", "content": "Hi"}]
        assert data["message_count"] == 1
        assert data["evaluation"]["avg_score"] == 9.0

    def test_get_run_file_not_dir(self, client, tmp_path):
        """A file named like a run_id should return 404."""
        (tmp_path / "run_20260218_120000").write_text("I am a file")
        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.get("/api/evaluation/runs/run_20260218_120000")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — POST /api/evaluation/runs/{run_id}/retry-evaluation
# ---------------------------------------------------------------------------


class TestRetryEvaluation:
    def test_retry_not_found(self, client, tmp_path):
        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.post("/api/evaluation/runs/run_missing/retry-evaluation")
        assert resp.status_code == 404

    def test_retry_no_conversation(self, client, tmp_path):
        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({"topic_id": "t"}))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.post("/api/evaluation/runs/run_20260218_120000/retry-evaluation")
        assert resp.status_code == 400
        assert "conversation.json" in resp.json()["detail"]

    def test_retry_no_config(self, client, tmp_path):
        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "conversation.json").write_text(json.dumps({"messages": []}))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.post("/api/evaluation/runs/run_20260218_120000/retry-evaluation")
        assert resp.status_code == 400
        assert "config.json" in resp.json()["detail"]

    @patch("evaluation.api.threading.Thread")
    def test_retry_success(self, mock_thread_cls, client, tmp_path):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({"topic_id": "t"}))
        (run_dir / "conversation.json").write_text(json.dumps({"messages": []}))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.post("/api/evaluation/runs/run_20260218_120000/retry-evaluation")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["run_id"] == "run_20260218_120000"

        mock_thread.start.assert_called_once()
        call_kwargs = mock_thread_cls.call_args
        assert call_kwargs.kwargs["target"].__name__ == "_retry_evaluation"

    @patch("evaluation.api.threading.Thread")
    def test_retry_already_running(self, mock_thread_cls, client, tmp_path):
        _update_eval_state(status=EvalStatus.running_session)

        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({"topic_id": "t"}))
        (run_dir / "conversation.json").write_text(json.dumps({"messages": []}))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            resp = client.post("/api/evaluation/runs/run_20260218_120000/retry-evaluation")
        assert resp.status_code == 409

    @patch("evaluation.api.threading.Thread")
    def test_retry_updates_state(self, mock_thread_cls, client, tmp_path):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        run_dir = tmp_path / "run_20260218_120000"
        run_dir.mkdir()
        (run_dir / "config.json").write_text(json.dumps({"topic_id": "t"}))
        (run_dir / "conversation.json").write_text(json.dumps({"messages": []}))

        with patch("evaluation.api.RUNS_DIR", tmp_path):
            client.post("/api/evaluation/runs/run_20260218_120000/retry-evaluation")

        assert _eval_state["status"] == EvalStatus.evaluating
        assert _eval_state["run_id"] == "run_20260218_120000"
        assert _eval_state["detail"] == "Re-running evaluation..."


# ---------------------------------------------------------------------------
# Tests — _run_evaluation_pipeline (background thread target)
# ---------------------------------------------------------------------------


class TestRunEvaluationPipeline:
    def _mock_db_for_eval(self, provider="openai", eval_model="gpt-5.2", sim_model="gpt-4o"):
        """Helper: patch get_db_manager so from_db() returns a config with the given provider."""
        mock_db = MagicMock()
        mock_config_service = MagicMock()
        mock_config_service.get_config.side_effect = lambda key: {
            "eval_evaluator": {"provider": provider, "model_id": eval_model},
            "eval_simulator": {"provider": provider, "model_id": sim_model},
        }[key]
        return patch("database.get_db_manager", return_value=MagicMock(session_factory=MagicMock(return_value=mock_db))), \
               patch("shared.services.llm_config_service.LLMConfigService", return_value=mock_config_service)

    def test_pipeline_fails_on_missing_openai_key(self):
        """When OPENAI_API_KEY is empty, pipeline should set status=failed."""
        import evaluation.api as api_mod

        db_patch, svc_patch = self._mock_db_for_eval(provider="openai")
        with db_patch, svc_patch, patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            api_mod._run_evaluation_pipeline("topic-1", "average_student.json", 5)

        with _eval_lock:
            assert _eval_state["status"] == EvalStatus.failed
            assert "OPENAI_API_KEY" in (_eval_state["error"] or "")

    def test_pipeline_fails_on_missing_anthropic_key(self):
        """When ANTHROPIC_API_KEY is missing for anthropic provider."""
        import evaluation.api as api_mod

        db_patch, svc_patch = self._mock_db_for_eval(provider="anthropic", eval_model="claude-opus-4-6", sim_model="claude-opus-4-6")
        with db_patch, svc_patch, patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            api_mod._run_evaluation_pipeline("topic-1", "average_student.json", 5)

        with _eval_lock:
            assert _eval_state["status"] == EvalStatus.failed
            assert "ANTHROPIC_API_KEY" in (_eval_state["error"] or "")


# ---------------------------------------------------------------------------
# Tests — _retry_evaluation (background thread target)
# ---------------------------------------------------------------------------


class TestRetryEvaluationThread:
    def test_retry_fails_on_missing_files(self, tmp_path):
        """Should set status=failed when config/conversation files are missing."""
        import evaluation.api as api_mod
        run_dir = tmp_path / "run_retry_test"
        run_dir.mkdir()
        # No config.json or conversation.json

        api_mod._retry_evaluation(run_dir)

        with _eval_lock:
            assert _eval_state["status"] == EvalStatus.failed

    def test_retry_writes_error_file(self, tmp_path):
        """Should write error.txt on failure."""
        import evaluation.api as api_mod
        run_dir = tmp_path / "run_retry_err"
        run_dir.mkdir()

        api_mod._retry_evaluation(run_dir)

        error_path = run_dir / "error.txt"
        assert error_path.exists()
        content = error_path.read_text()
        assert len(content) > 0


# ############################################################################
# SessionRunner Tests
# ############################################################################


class TestSessionRunner:
    """Tests for evaluation/session_runner.py."""

    def _make_config(self):
        from evaluation.config import EvalConfig
        return EvalConfig(
            openai_api_key="test-key-fake",
            anthropic_api_key="test-key-fake",
            topic_id="topic-1",
            max_turns=3,
            server_port=9999,
            server_startup_timeout=2,
            health_check_interval=0.1,
            turn_timeout=5,
        )

    def _make_runner(self, tmp_path, config=None, skip_server=True):
        from evaluation.session_runner import SessionRunner
        config = config or self._make_config()
        simulator = MagicMock()
        runner = SessionRunner(
            config=config,
            simulator=simulator,
            run_dir=tmp_path,
            skip_server_management=skip_server,
        )
        return runner

    def test_init(self, tmp_path):
        runner = self._make_runner(tmp_path)
        assert runner.config.topic_id == "topic-1"
        assert runner.skip_server_management is True
        assert runner.conversation == []
        assert runner.session_id is None
        assert runner.server_process is None
        runner.cleanup()

    def test_log_writes_to_file(self, tmp_path):
        runner = self._make_runner(tmp_path)
        runner._log("hello world")
        runner._log_file.flush()
        log_content = (tmp_path / "run.log").read_text()
        assert "hello world" in log_content
        runner.cleanup()

    def test_start_server_skip_mode_healthy(self, tmp_path):
        runner = self._make_runner(tmp_path, skip_server=True)
        with patch("evaluation.session_runner.httpx.Client") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client_inst = MagicMock()
            mock_client_inst.get.return_value = mock_resp
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_client_inst)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx
            runner.start_server()  # Should not raise
        runner.cleanup()

    def test_start_server_skip_mode_unhealthy(self, tmp_path):
        runner = self._make_runner(tmp_path, skip_server=True)
        import httpx
        with patch("evaluation.session_runner.httpx.Client") as MockClient:
            mock_client_inst = MagicMock()
            mock_client_inst.get.side_effect = httpx.ConnectError("refused")
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_client_inst)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx
            with pytest.raises(RuntimeError, match="not reachable"):
                runner.start_server()
        runner.cleanup()

    def test_stop_server_skip_mode_noop(self, tmp_path):
        runner = self._make_runner(tmp_path, skip_server=True)
        runner.stop_server()
        assert runner.server_process is None
        runner.cleanup()

    def test_stop_server_terminates_process(self, tmp_path):
        runner = self._make_runner(tmp_path, skip_server=False)
        mock_proc = MagicMock()
        runner.server_process = mock_proc
        runner.stop_server()
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called()
        assert runner.server_process is None
        runner.cleanup()

    def test_stop_server_kills_on_timeout(self, tmp_path):
        import subprocess
        runner = self._make_runner(tmp_path, skip_server=False)
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="test", timeout=5), None]
        runner.server_process = mock_proc
        runner.stop_server()
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        runner.cleanup()

    def test_create_session(self, tmp_path):
        runner = self._make_runner(tmp_path)
        with patch("evaluation.session_runner.httpx.Client") as MockClient:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"session_id": "sess-abc"}
            mock_resp.raise_for_status = MagicMock()
            mock_client_inst = MagicMock()
            mock_client_inst.post.return_value = mock_resp
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_client_inst)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            sid = runner._create_session()
            assert sid == "sess-abc"
            assert runner.session_id == "sess-abc"
        runner.cleanup()

    def test_cleanup_closes_log_file(self, tmp_path):
        runner = self._make_runner(tmp_path)
        assert not runner._log_file.closed
        runner.cleanup()
        assert runner._log_file.closed

    def test_cleanup_twice_raises_on_log_write(self, tmp_path):
        """Cleanup closes log file; a second cleanup tries to write to closed file."""
        runner = self._make_runner(tmp_path)
        runner.cleanup()
        # Second call fails because _log writes to closed file
        with pytest.raises(ValueError, match="closed file"):
            runner.cleanup()
