"""
Session Runner

Manages the full lifecycle of a tutoring session for evaluation:
- Starts the backend server as a subprocess (or verifies health in-process)
- Creates a session via REST API
- Runs the conversation loop over WebSocket
- Captures all messages and metadata
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import websockets

from evaluation.config import EvalConfig, PROJECT_ROOT
from evaluation.student_simulator import StudentSimulator

logger = logging.getLogger("evaluation.session_runner")


class SessionRunner:
    """Runs a full tutoring session against the live server."""

    def __init__(
        self,
        config: EvalConfig,
        simulator: StudentSimulator,
        run_dir: Path,
        skip_server_management: bool = False,
        on_turn: callable = None,
    ):
        self.config = config
        self.simulator = simulator
        self.run_dir = run_dir
        self.skip_server_management = skip_server_management
        self.on_turn = on_turn
        self.server_process: subprocess.Popen | None = None
        self.conversation: list[dict] = []
        self.session_id: str | None = None
        self.session_metadata: dict | None = None
        self._log_file = open(run_dir / "run.log", "a")

    def _log(self, message: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}"
        self._log_file.write(line + "\n")
        self._log_file.flush()
        logger.info(message)

    def start_server(self):
        """Start the backend server or verify health if skip_server_management."""
        if self.skip_server_management:
            self._log("Skipping server start (in-process mode), verifying health...")
            try:
                with httpx.Client() as client:
                    resp = client.get(self.config.health_url, timeout=5.0)
                    if resp.status_code == 200:
                        self._log("Server is healthy")
                        return
            except (httpx.ConnectError, httpx.ReadTimeout):
                pass
            raise RuntimeError("Server is not reachable at " + self.config.health_url)

        self._log("Starting server...")
        self.server_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(self.config.server_port)],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._log(f"Server process started (PID {self.server_process.pid})")

        start = time.time()
        while time.time() - start < self.config.server_startup_timeout:
            try:
                with httpx.Client() as client:
                    resp = client.get(self.config.health_url, timeout=2.0)
                    if resp.status_code == 200:
                        self._log(f"Server healthy after {time.time() - start:.1f}s")
                        return
            except (httpx.ConnectError, httpx.ReadTimeout):
                pass
            time.sleep(self.config.health_check_interval)

        self.stop_server()
        raise RuntimeError(f"Server failed to start within {self.config.server_startup_timeout}s")

    def stop_server(self):
        if self.skip_server_management:
            self._log("Skipping server stop (in-process mode)")
            return
        if self.server_process:
            self._log("Stopping server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()
            self._log("Server stopped")
            self.server_process = None

    def _create_session(self) -> str:
        """Create a new tutoring session via REST API."""
        self._log(f"Creating session for topic '{self.config.topic_id}'")
        with httpx.Client() as client:
            resp = client.post(
                f"{self.config.base_url}/sessions",
                json={
                    "student": {
                        "id": "eval-student",
                        "grade": self.config.student_grade,
                    },
                    "goal": {
                        "topic": "Evaluation",
                        "syllabus": f"{self.config.student_board} Grade {self.config.student_grade}",
                        "learning_objectives": ["Evaluate tutoring quality"],
                        "guideline_id": self.config.topic_id,
                    },
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self.session_id = data["session_id"]
            self._log(f"Session created: {self.session_id}")
            return self.session_id

    async def _run_websocket_session(self):
        """Run the conversation loop over WebSocket."""
        ws_url = f"{self.config.ws_url}/sessions/ws/{self.session_id}"
        self._log(f"Connecting to WebSocket: {ws_url}")

        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=120) as ws:
            self._log("WebSocket connected")

            # Receive initial state_update
            raw = await asyncio.wait_for(ws.recv(), timeout=self.config.turn_timeout)
            msg = json.loads(raw)
            self._log(f"Received: {msg['type']}")

            # Receive welcome message
            raw = await asyncio.wait_for(ws.recv(), timeout=self.config.turn_timeout)
            msg = json.loads(raw)
            if msg["type"] == "assistant":
                welcome = msg["payload"]["message"]
                self.conversation.append({
                    "role": "tutor",
                    "content": welcome,
                    "turn": 0,
                    "timestamp": datetime.now().isoformat(),
                })
                self._log(f"[Turn 0] TUTOR: {welcome[:100]}...")

            # Conversation loop
            turn = 1
            session_complete = False
            while turn <= self.config.max_turns and not session_complete:
                self._log(f"[Turn {turn}] Generating student response...")
                t0 = time.time()
                student_msg = self.simulator.generate_response(self.conversation)
                gen_time = time.time() - t0
                self._log(f"[Turn {turn}] STUDENT ({gen_time:.1f}s): {student_msg[:100]}...")

                self.conversation.append({
                    "role": "student",
                    "content": student_msg,
                    "turn": turn,
                    "timestamp": datetime.now().isoformat(),
                })

                await ws.send(json.dumps({
                    "type": "chat",
                    "payload": {"message": student_msg},
                }))

                tutor_response = None
                t0 = time.time()
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self.config.turn_timeout)
                    msg = json.loads(raw)

                    if msg["type"] == "typing":
                        continue
                    elif msg["type"] == "state_update":
                        state = msg["payload"].get("state", {})
                        if state.get("is_complete", False):
                            self._log(f"[Turn {turn}] Session marked complete by tutor")
                            session_complete = True
                        continue
                    elif msg["type"] == "assistant":
                        tutor_response = msg["payload"]["message"]
                        resp_time = time.time() - t0
                        break
                    elif msg["type"] == "error":
                        self._log(f"[Turn {turn}] ERROR: {msg['payload'].get('error', 'unknown')}")
                        break

                if tutor_response:
                    self.conversation.append({
                        "role": "tutor",
                        "content": tutor_response,
                        "turn": turn,
                        "timestamp": datetime.now().isoformat(),
                    })
                    self._log(f"[Turn {turn}] TUTOR ({resp_time:.1f}s): {tutor_response[:100]}...")
                else:
                    self._log(f"[Turn {turn}] No tutor response received, ending session")
                    break

                if self.on_turn:
                    try:
                        self.on_turn(turn, self.config.max_turns)
                    except Exception:
                        pass

                turn += 1

            self._log(f"Session complete. Total turns: {turn - 1}, Messages: {len(self.conversation)}")

    def run_session(self) -> list[dict]:
        """Run the full session: create session, run conversation loop."""
        self._create_session()
        try:
            asyncio.run(self._run_websocket_session())
        except Exception as e:
            self._log(f"WebSocket session ended with error: {e}")
            if not self.conversation:
                raise

        # Fetch final state
        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{self.config.base_url}/sessions/{self.session_id}",
                    timeout=10.0,
                )
                resp.raise_for_status()
                self.session_metadata = resp.json()
            self._log("Fetched session state")
        except Exception as e:
            self._log(f"Failed to fetch session state: {e}")
            self.session_metadata = {}

        return self.conversation

    def cleanup(self):
        self.stop_server()
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
