"""
Session Runner

Manages the full lifecycle of a tutoring session for evaluation:
- Starts the backend server as a subprocess (or verifies health in-process)
- Creates a session via REST API
- Handles card phase if pre-computed explanations exist (reads cards, calls /card-action)
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

from autoresearch.tutor_teaching_quality.evaluation.config import EvalConfig, PROJECT_ROOT
from autoresearch.tutor_teaching_quality.evaluation.student_simulator import StudentSimulator

logger = logging.getLogger("autoresearch.tutor_teaching_quality.evaluation.session_runner")


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
        self.card_phase_data: dict | None = None  # Stores card phase info for evaluator
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
                        "chapter": "Evaluation",
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

            # Detect card phase
            first_turn = data.get("first_turn", {})
            if first_turn.get("session_phase") == "card_phase":
                self._handle_card_phase(first_turn)
            else:
                # No card phase — record the welcome message from the REST response
                welcome = first_turn.get("message", "")
                if welcome:
                    self.conversation.append({
                        "role": "tutor",
                        "content": welcome,
                        "turn": 0,
                        "timestamp": datetime.now().isoformat(),
                        "phase": "welcome",
                    })
                    self._log(f"[Turn 0] TUTOR (welcome): {welcome[:100]}...")

            return self.session_id

    def _handle_card_phase(self, first_turn: dict):
        """Handle the card phase: read cards, add to transcript, call /card-action."""
        cards = first_turn.get("explanation_cards", [])
        card_phase_state = first_turn.get("card_phase_state", {})
        welcome = first_turn.get("message", "")

        self._log(
            f"Card phase detected: {len(cards)} cards, "
            f"variant={card_phase_state.get('current_variant_key', '?')}, "
            f"available_variants={card_phase_state.get('available_variants', '?')}"
        )

        # Store card phase data for evaluator context
        self.card_phase_data = {
            "cards": cards,
            "variant_key": card_phase_state.get("current_variant_key"),
            "total_variants": card_phase_state.get("available_variants", 1),
        }

        # Add welcome message to conversation
        if welcome:
            self.conversation.append({
                "role": "tutor",
                "content": welcome,
                "turn": 0,
                "timestamp": datetime.now().isoformat(),
                "phase": "card_phase_welcome",
            })

        # Add each card as a conversation entry so evaluator sees the full experience
        for card in cards:
            card_content = self._format_card_for_transcript(card)
            self.conversation.append({
                "role": "explanation_card",
                "content": card_content,
                "turn": 0,
                "timestamp": datetime.now().isoformat(),
                "phase": "card_phase",
                "card_data": card,
            })

        self._log(f"Added {len(cards)} explanation cards to transcript")

        # Complete card phase by calling /card-action with "clear"
        self._complete_card_phase()

    def _format_card_for_transcript(self, card: dict) -> str:
        """Format an explanation card for readable transcript output."""
        parts = []
        card_idx = card.get("card_idx", "?")
        card_type = card.get("card_type", "")
        title = card.get("title", "")
        content = card.get("content", "")
        visual = card.get("visual")

        parts.append(f"**Card {card_idx}** ({card_type}): {title}")
        parts.append(content)
        if visual:
            parts.append(f"\n{visual}")

        return "\n".join(parts)

    def _complete_card_phase(self):
        """Call /card-action to transition from card phase to interactive teaching."""
        self._log("Completing card phase (action=clear)...")
        with httpx.Client() as client:
            resp = client.post(
                f"{self.config.base_url}/sessions/{self.session_id}/card-action",
                json={"action": "clear"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        action = data.get("action", "")
        transition_msg = data.get("message", "")

        self._log(f"Card phase completed: action={action}")

        # Add the transition message to conversation
        if transition_msg:
            self.conversation.append({
                "role": "tutor",
                "content": transition_msg,
                "turn": 0,
                "timestamp": datetime.now().isoformat(),
                "phase": "card_to_interactive_transition",
            })
            self._log(f"[Transition] TUTOR: {transition_msg[:100]}...")

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

            # Receive welcome/transition message from WebSocket
            # If we went through card phase, this is the post-card-phase state;
            # if no card phase, the welcome was already captured in _create_session
            raw = await asyncio.wait_for(ws.recv(), timeout=self.config.turn_timeout)
            msg = json.loads(raw)
            if msg["type"] == "assistant":
                ws_welcome = msg["payload"]["message"]
                # Only add if we didn't already capture this from REST
                if not self.card_phase_data and not any(
                    m.get("phase") == "welcome" for m in self.conversation
                ):
                    self.conversation.append({
                        "role": "tutor",
                        "content": ws_welcome,
                        "turn": 0,
                        "timestamp": datetime.now().isoformat(),
                    })
                    self._log(f"[Turn 0] TUTOR: {ws_welcome[:100]}...")
                else:
                    self._log(f"[Turn 0] TUTOR (WS echo, skipped): {ws_welcome[:80]}...")

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

                    if msg["type"] in ("typing", "token", "visual_update"):
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
