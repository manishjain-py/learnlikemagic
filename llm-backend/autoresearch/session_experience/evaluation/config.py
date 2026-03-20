"""
Session Experience Pipeline — Configuration

Extends the tutor_teaching_quality config with topic rotation support.
Reuses the same EvalConfig + personas infrastructure.
"""

import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

EVAL_DIR = Path(__file__).parent
# Runs dir is outside the llm-backend tree to avoid triggering uvicorn --reload
# (writing files in-tree causes server restart, wiping in-memory agent logs)
RUNS_DIR = Path("/tmp/session_experience_runs")

# Reuse personas from the tutor_teaching_quality pipeline
PERSONAS_DIR = PROJECT_ROOT / "autoresearch" / "tutor_teaching_quality" / "evaluation" / "personas"

# Topics with pre-computed explanations (Grade 3 Math, CBSE)
TOPIC_POOL = [
    {"id": "08ffca67-f71d-40b4-b60d-658bc688f74d", "name": "3-Digit Addition: Regrouping in One Column"},
    {"id": "eb64ad64-9ba6-4752-8b72-751baa0c74b5", "name": "3-Digit Addition: Regrouping in Two Columns"},
    {"id": "44fd6529-fb7f-4ff2-a2e7-cd598a8b3d4f", "name": "4-Digit Addition and Checking Your Answer"},
    {"id": "b8d0b705-7a49-4fe1-bd06-eff6fec0f8b6", "name": "Reviewing 3-Digit Place Value"},
    {"id": "4220931c-d879-4939-b092-bfbc0ed2f1e3", "name": "Revisiting Addition: Fact Families"},
    {"id": "206482af-8a3d-4872-a091-2436899b5125", "name": "Structured Problem Solving with Addition"},
]

DEFAULT_TOPICS_PER_ITERATION = 3


@dataclass
class SessionExperienceConfig:
    """Config for a session experience evaluation run."""

    # Server
    server_host: str = "localhost"
    server_port: int = 8000
    server_startup_timeout: int = 30
    health_check_interval: float = 1.0

    # Session
    topic_id: str = ""
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

    # LLM - Evaluator (naturalness judge)
    evaluator_model: str = "gpt-5.2"
    evaluator_reasoning_effort: str = "high"

    # LLM - Prompt Analyzer
    analyzer_model: str = "gpt-5.2"
    analyzer_reasoning_effort: str = "high"

    # Provider config
    eval_llm_provider: str = field(
        default_factory=lambda: os.environ.get("EVAL_LLM_PROVIDER", "openai")
    )
    evaluator_provider: str = ""
    simulator_provider: str = ""
    analyzer_provider: str = ""

    # Anthropic models
    anthropic_evaluator_model: str = "claude-opus-4-6"
    anthropic_simulator_model: str = "claude-opus-4-6"
    anthropic_analyzer_model: str = "claude-opus-4-6"
    anthropic_evaluator_thinking_budget: int = 20000

    # Tutor model (display only)
    tutor_llm_provider: str = field(
        default_factory=lambda: os.environ.get("TUTOR_LLM_PROVIDER", os.environ.get("APP_LLM_PROVIDER", "openai"))
    )

    # Topic rotation
    topics_per_iteration: int = DEFAULT_TOPICS_PER_ITERATION

    # API Keys
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))

    PROVIDER_LABELS = {
        "openai": "GPT-5.2",
        "anthropic": "Claude Opus 4.6",
        "anthropic-haiku": "Claude Haiku 4.5",
    }

    def __post_init__(self):
        if not self.evaluator_provider:
            self.evaluator_provider = self.eval_llm_provider
        if not self.simulator_provider:
            self.simulator_provider = self.eval_llm_provider
        if not self.analyzer_provider:
            self.analyzer_provider = self.eval_llm_provider

    @classmethod
    def from_db(cls, db_session, **kwargs) -> "SessionExperienceConfig":
        """Create config with evaluator/simulator models from DB llm_config table."""
        from shared.services.llm_config_service import LLMConfigService

        config_service = LLMConfigService(db_session)
        eval_cfg = config_service.get_config("eval_evaluator")
        sim_cfg = config_service.get_config("eval_simulator")

        kwargs["evaluator_provider"] = eval_cfg["provider"]
        if eval_cfg["provider"] == "anthropic":
            kwargs["anthropic_evaluator_model"] = eval_cfg["model_id"]
        elif eval_cfg["provider"] != "claude_code":
            kwargs["evaluator_model"] = eval_cfg["model_id"]

        kwargs["simulator_provider"] = sim_cfg["provider"]
        if sim_cfg["provider"] == "anthropic":
            kwargs["anthropic_simulator_model"] = sim_cfg["model_id"]
        elif sim_cfg["provider"] != "claude_code":
            kwargs["simulator_model"] = sim_cfg["model_id"]

        # Analyzer uses same provider as evaluator
        kwargs["analyzer_provider"] = eval_cfg["provider"]
        if eval_cfg["provider"] == "anthropic":
            kwargs["anthropic_analyzer_model"] = eval_cfg["model_id"]
        elif eval_cfg["provider"] != "claude_code":
            kwargs["analyzer_model"] = eval_cfg["model_id"]

        return cls(**kwargs)

    def create_llm_service(self, component: str):
        """Create an LLMService for evaluator, simulator, or analyzer."""
        from shared.services.llm_service import LLMService

        if component == "evaluator":
            provider = self.evaluator_provider
            model_id = (
                self.anthropic_evaluator_model if provider == "anthropic"
                else "claude-code" if provider == "claude_code"
                else self.evaluator_model
            )
        elif component == "simulator":
            provider = self.simulator_provider
            model_id = (
                self.anthropic_simulator_model if provider == "anthropic"
                else "claude-code" if provider == "claude_code"
                else self.simulator_model
            )
        elif component == "analyzer":
            provider = self.analyzer_provider
            model_id = (
                self.anthropic_analyzer_model if provider == "anthropic"
                else "claude-code" if provider == "claude_code"
                else self.analyzer_model
            )
        else:
            raise ValueError(f"Unknown component: {component}")

        return LLMService(
            api_key=self.openai_api_key,
            provider=provider,
            model_id=model_id,
            anthropic_api_key=self.anthropic_api_key or None,
        )

    @property
    def tutor_model_label(self) -> str:
        return self.PROVIDER_LABELS.get(self.tutor_llm_provider, self.tutor_llm_provider)

    @property
    def evaluator_model_label(self) -> str:
        if self.evaluator_provider == "anthropic":
            return self.anthropic_evaluator_model
        if self.evaluator_provider == "claude_code":
            return "claude-code"
        return self.evaluator_model

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
        persona_path = PERSONAS_DIR / self.persona_file
        with open(persona_path, "r") as f:
            return json.load(f)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = asdict(self)
        d.pop("openai_api_key", None)
        d.pop("anthropic_api_key", None)
        return d


def select_topics(n: int = DEFAULT_TOPICS_PER_ITERATION, seed: int | None = None) -> list[dict]:
    """Select n topics from the pool for this iteration."""
    rng = random.Random(seed)
    return rng.sample(TOPIC_POOL, min(n, len(TOPIC_POOL)))
