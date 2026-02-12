"""
Evaluation Pipeline Configuration

Centralizes all settings for the evaluation pipeline:
server connection, session parameters, LLM models, and simulation controls.
"""

import os
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from dotenv import load_dotenv

# Load .env from llm-backend root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Path constants
EVAL_DIR = Path(__file__).parent
RUNS_DIR = EVAL_DIR / "runs"
PERSONAS_DIR = EVAL_DIR / "personas"


@dataclass
class EvalConfig:
    """All settings for a single evaluation run."""

    # Server
    server_host: str = "localhost"
    server_port: int = 8000
    server_startup_timeout: int = 30
    health_check_interval: float = 1.0

    # Session — these map to the learnlikemagic CreateSessionRequest
    topic_id: str = ""  # guideline_id for learnlikemagic
    student_grade: int = 5
    student_board: str = "CBSE"
    language_level: str = "simple"

    # Simulation
    persona_file: str = "average_student.json"
    max_turns: int = 20
    turn_timeout: int = 90

    # LLM - Student Simulator
    simulator_model: str = "gpt-4o"
    simulator_temperature: float = 0.8
    simulator_max_tokens: int = 150

    # LLM - Evaluator
    evaluator_model: str = "gpt-5.2"
    evaluator_reasoning_effort: str = "high"

    # Provider switch for evaluation pipeline
    eval_llm_provider: str = field(
        default_factory=lambda: os.environ.get("EVAL_LLM_PROVIDER", "openai")
    )

    # Anthropic models (used when eval_llm_provider == "anthropic")
    anthropic_evaluator_model: str = "claude-opus-4-6"
    anthropic_simulator_model: str = "claude-opus-4-6"
    anthropic_evaluator_thinking_budget: int = 20000

    # API Keys (not serialized)
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )

    @property
    def base_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.server_host}:{self.server_port}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/health/db"

    def load_persona(self) -> dict:
        """Load persona JSON from the personas directory."""
        persona_path = PERSONAS_DIR / self.persona_file
        with open(persona_path, "r") as f:
            return json.load(f)

    def to_dict(self) -> dict:
        """Serialize config for saving, excluding API keys."""
        d = asdict(self)
        d.pop("openai_api_key", None)
        d.pop("anthropic_api_key", None)
        return d
