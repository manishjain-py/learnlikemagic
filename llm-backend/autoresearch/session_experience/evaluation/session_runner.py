"""
Session Runner with Prompt Capture

Extends the tutor_teaching_quality SessionRunner to capture master tutor
prompts via the agent-logs API after each turn, before the server can
be reloaded (uvicorn --reload watches for file changes).

The key insight: agent logs are stored in-memory on the server. With
uvicorn --reload, the server process can restart at any time (triggered
by .pyc or .json file writes), wiping the in-memory store. So we must
fetch logs during the active WebSocket session, not after it ends.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
import websockets

from autoresearch.session_experience.evaluation.config import SessionExperienceConfig
from autoresearch.tutor_teaching_quality.evaluation.config import EvalConfig
from autoresearch.tutor_teaching_quality.evaluation.student_simulator import StudentSimulator

logger = logging.getLogger("autoresearch.session_experience.session_runner")


def _to_eval_config(config: SessionExperienceConfig) -> EvalConfig:
    """Convert SessionExperienceConfig to EvalConfig for server management."""
    return EvalConfig(
        server_host=config.server_host,
        server_port=config.server_port,
        server_startup_timeout=config.server_startup_timeout,
        health_check_interval=config.health_check_interval,
        topic_id=config.topic_id,
        student_grade=config.student_grade,
        student_board=config.student_board,
        language_level=config.language_level,
        persona_file=config.persona_file,
        max_turns=config.max_turns,
        turn_timeout=config.turn_timeout,
        simulator_model=config.simulator_model,
        simulator_temperature=config.simulator_temperature,
        simulator_max_tokens=config.simulator_max_tokens,
        evaluator_model=config.evaluator_model,
        evaluator_reasoning_effort=config.evaluator_reasoning_effort,
        evaluator_provider=config.evaluator_provider,
        simulator_provider=config.simulator_provider,
        anthropic_evaluator_model=config.anthropic_evaluator_model,
        anthropic_simulator_model=config.anthropic_simulator_model,
        anthropic_evaluator_thinking_budget=config.anthropic_evaluator_thinking_budget,
        openai_api_key=config.openai_api_key,
        anthropic_api_key=config.anthropic_api_key,
    )


def _fetch_latest_prompt(base_url: str, session_id: str, known_count: int) -> dict | None:
    """Fetch the latest master_tutor prompt from agent logs.

    Only returns a new prompt if the log count exceeds known_count.
    """
    try:
        resp = httpx.get(
            f"{base_url}/sessions/{session_id}/agent-logs",
            params={"agent_name": "master_tutor", "limit": 200},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return None
        logs = resp.json().get("logs", [])
        # Find completed events with prompts
        prompt_logs = [
            l for l in logs
            if l.get("event_type") == "completed" and l.get("prompt")
        ]
        if len(prompt_logs) > known_count:
            latest = prompt_logs[-1]
            return {
                "turn": latest.get("turn_id", "?"),
                "agent_name": latest.get("agent_name", "master_tutor"),
                "prompt": latest["prompt"],
                "reasoning": latest.get("reasoning", ""),
                "duration_ms": latest.get("duration_ms"),
                "timestamp": latest.get("timestamp", ""),
            }
    except Exception:
        pass
    return None


class SessionRunnerWithPrompts:
    """Runs a session and captures master tutor prompts after each turn."""

    def __init__(
        self,
        config: SessionExperienceConfig,
        simulator: StudentSimulator,
        run_dir: Path,
        skip_server: bool = False,
        restart_server: bool = False,
    ):
        self.config = config
        self.eval_config = _to_eval_config(config)
        self.simulator = simulator
        self.run_dir = run_dir
        self.skip_server = skip_server
        self.restart_server_flag = restart_server

        self.conversation: list[dict] = []
        self.prompts: list[dict] = []
        self.session_id: str | None = None
        self.session_metadata: dict | None = None
        self.card_phase_data: dict | None = None
        self.server_process = None
        self._log_file = open(run_dir / "run.log", "a")

    def _log(self, message: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}"
        self._log_file.write(line + "\n")
        self._log_file.flush()

    def _start_server(self):
        """Start or verify the backend server."""
        # Reuse the base SessionRunner's server management
        from autoresearch.tutor_teaching_quality.evaluation.session_runner import SessionRunner
        temp_runner = SessionRunner(
            self.eval_config, self.simulator, self.run_dir,
            skip_server_management=self.skip_server,
            restart_server=self.restart_server_flag,
        )
        temp_runner.start_server()
        self.server_process = temp_runner.server_process

    def _stop_server(self):
        if self.skip_server and not self.restart_server_flag:
            return
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except Exception:
                self.server_process.kill()
                self.server_process.wait()
            self.server_process = None

    def _create_session(self):
        """Create session via REST, handle card phase."""
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

            first_turn = data.get("first_turn", {})
            if first_turn.get("session_phase") == "card_phase":
                self._handle_card_phase(first_turn)
            else:
                welcome = first_turn.get("message", "")
                if welcome:
                    self.conversation.append({
                        "role": "tutor", "content": welcome,
                        "turn": 0, "timestamp": datetime.now().isoformat(),
                        "phase": "welcome",
                    })
                    self._log(f"[Turn 0] TUTOR (welcome): {welcome[:100]}...")

    def _handle_card_phase(self, first_turn: dict):
        cards = first_turn.get("explanation_cards", [])
        card_phase_state = first_turn.get("card_phase_state", {})
        welcome = first_turn.get("message", "")

        self._log(f"Card phase: {len(cards)} cards, variant={card_phase_state.get('current_variant_key', '?')}")

        self.card_phase_data = {
            "cards": cards,
            "variant_key": card_phase_state.get("current_variant_key"),
            "total_variants": card_phase_state.get("available_variants", 1),
        }

        if welcome:
            self.conversation.append({
                "role": "tutor", "content": welcome,
                "turn": 0, "timestamp": datetime.now().isoformat(),
                "phase": "card_phase_welcome",
            })

        for card in cards:
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

            self.conversation.append({
                "role": "explanation_card",
                "content": "\n".join(parts),
                "turn": 0, "timestamp": datetime.now().isoformat(),
                "phase": "card_phase", "card_data": card,
            })

        # Complete card phase
        with httpx.Client() as client:
            resp = client.post(
                f"{self.config.base_url}/sessions/{self.session_id}/card-action",
                json={"action": "clear"}, timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        transition_msg = data.get("message", "")
        if transition_msg:
            self.conversation.append({
                "role": "tutor", "content": transition_msg,
                "turn": 0, "timestamp": datetime.now().isoformat(),
                "phase": "card_to_interactive_transition",
            })
            self._log(f"[Transition] TUTOR: {transition_msg[:100]}...")

    async def _run_websocket_session(self):
        """Run conversation loop, fetching agent logs after each turn."""
        ws_url = f"{self.config.ws_url}/sessions/ws/{self.session_id}"
        self._log(f"Connecting to WebSocket: {ws_url}")

        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=120) as ws:
            self._log("WebSocket connected")

            # Initial state_update
            raw = await asyncio.wait_for(ws.recv(), timeout=self.config.turn_timeout)
            msg = json.loads(raw)
            self._log(f"Received: {msg['type']}")

            # Possible welcome (only for non-card-phase sessions)
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw)
                if msg["type"] == "assistant" and not self.card_phase_data:
                    ws_welcome = msg["payload"]["message"]
                    if not any(m.get("phase") == "welcome" for m in self.conversation):
                        self.conversation.append({
                            "role": "tutor", "content": ws_welcome,
                            "turn": 0, "timestamp": datetime.now().isoformat(),
                            "phase": "welcome",
                        })
                        self._log(f"[Turn 0] TUTOR (WS welcome): {ws_welcome[:100]}...")
            except asyncio.TimeoutError:
                self._log("No WS welcome (card phase or already captured)")

            # Conversation loop
            turn = 1
            session_complete = False
            prompt_count = 0

            while turn <= self.config.max_turns and not session_complete:
                self._log(f"[Turn {turn}] Generating student response...")
                t0 = time.time()
                student_msg = self.simulator.generate_response(self.conversation)
                gen_time = time.time() - t0
                self._log(f"[Turn {turn}] STUDENT ({gen_time:.1f}s): {student_msg[:100]}...")

                self.conversation.append({
                    "role": "student", "content": student_msg,
                    "turn": turn, "timestamp": datetime.now().isoformat(),
                })

                await ws.send(json.dumps({
                    "type": "chat",
                    "payload": {"message": student_msg},
                }))

                # Collect tutor response
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
                            self._log(f"[Turn {turn}] Session complete")
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
                        "role": "tutor", "content": tutor_response,
                        "turn": turn, "timestamp": datetime.now().isoformat(),
                    })
                    self._log(f"[Turn {turn}] TUTOR ({resp_time:.1f}s): {tutor_response[:100]}...")

                    # Fetch prompt for this turn immediately (before server can reload)
                    new_prompt = _fetch_latest_prompt(
                        self.config.base_url, self.session_id, prompt_count
                    )
                    if new_prompt:
                        self.prompts.append(new_prompt)
                        prompt_count += 1
                        self._log(f"[Turn {turn}] Captured master tutor prompt")
                else:
                    self._log(f"[Turn {turn}] No response, ending")
                    break

                turn += 1

            self._log(f"Session complete. Turns: {turn - 1}, Messages: {len(self.conversation)}, Prompts: {len(self.prompts)}")

    def run(self) -> dict:
        """Run the full session and return conversation + prompts."""
        self._start_server()
        try:
            self._create_session()
            try:
                asyncio.run(self._run_websocket_session())
            except Exception as e:
                self._log(f"WebSocket session error: {e}")
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
            except Exception as e:
                self._log(f"Failed to fetch session state: {e}")
                self.session_metadata = {}

            return {
                "conversation": self.conversation,
                "prompts": self.prompts,
                "session_metadata": self.session_metadata or {},
                "card_phase_data": self.card_phase_data,
                "session_id": self.session_id,
            }
        finally:
            self._stop_server()
            if self._log_file and not self._log_file.closed:
                self._log_file.close()


def run_session_with_prompts(
    config: SessionExperienceConfig,
    persona: dict,
    run_dir: Path,
    skip_server: bool = False,
    restart_server: bool = False,
    on_turn: callable = None,
) -> dict:
    """Run a full session and capture both conversation + master tutor prompts."""
    eval_config = _to_eval_config(config)
    simulator = StudentSimulator(eval_config, persona)

    runner = SessionRunnerWithPrompts(
        config, simulator, run_dir,
        skip_server=skip_server,
        restart_server=restart_server,
    )
    return runner.run()
