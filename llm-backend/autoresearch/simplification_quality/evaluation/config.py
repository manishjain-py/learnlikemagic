"""
Simplification Quality Pipeline — Configuration

Defines topic pool, reason types, and config for evaluating
re-explanation quality at different simplification depths.
"""

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
RUNS_DIR = Path("/tmp/simplification_quality_runs")

REASONS = ["example", "simpler_words", "elaborate", "different_approach"]

# Place Value chapter topics (Grade 1 CBSE Math - test_auth_mathematics_1_2026)
TOPIC_POOL = [
    {"id": "5d308551-cdbd-40d4-8001-c82902b47ca4", "name": "Understanding Place Value"},
    {"id": "69428296-cfea-42a0-8d0f-3d1bff665f16", "name": "Forming Numbers"},
    {"id": "a477516c-6b80-406b-9b39-279d3e755998", "name": "Comparing and Ordering Numbers"},
    {"id": "8ebae695-f1cf-42af-9d7d-05f5eb2eef47", "name": "Place Value and Expansion"},
]


@dataclass
class SimplificationConfig:
    """Config for a simplification quality evaluation run."""

    # Server
    server_host: str = "localhost"
    server_port: int = 8000

    # Session
    student_grade: int = 1

    # Sampling
    cards_per_run: int = 2
    depths_to_test: int = 2  # test depth 1 and depth 2

    # Provider config
    eval_llm_provider: str = field(
        default_factory=lambda: os.environ.get("EVAL_LLM_PROVIDER", "openai")
    )
    evaluator_provider: str = ""
    evaluator_model_id: str = "gpt-5.2"
    anthropic_evaluator_model: str = "claude-opus-4-6"

    # API Keys
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))

    def __post_init__(self):
        if not self.evaluator_provider:
            self.evaluator_provider = self.eval_llm_provider

    @classmethod
    def from_db(cls, db_session, **kwargs) -> "SimplificationConfig":
        """Create config with evaluator model from DB llm_config table."""
        from shared.services.llm_config_service import LLMConfigService

        config_service = LLMConfigService(db_session)
        eval_cfg = config_service.get_config("eval_evaluator")

        kwargs["evaluator_provider"] = eval_cfg["provider"]
        if eval_cfg["provider"] == "anthropic":
            kwargs["anthropic_evaluator_model"] = eval_cfg["model_id"]
        elif eval_cfg["provider"] != "claude_code":
            kwargs["evaluator_model_id"] = eval_cfg["model_id"]

        return cls(**kwargs)

    def create_llm_service(self, component: str):
        """Create an LLMService for the evaluator."""
        from shared.services.llm_service import LLMService

        if component == "evaluator":
            provider = self.evaluator_provider
            model_id = (
                self.anthropic_evaluator_model if provider == "anthropic"
                else "claude-code" if provider == "claude_code"
                else self.evaluator_model_id
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
    def base_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"

    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = asdict(self)
        d.pop("openai_api_key", None)
        d.pop("anthropic_api_key", None)
        return d


def select_topics(n: int, seed: int | None = None) -> list[dict]:
    """Select n topics from the pool for this iteration."""
    rng = random.Random(seed)
    return rng.sample(TOPIC_POOL, min(n, len(TOPIC_POOL)))


def select_cards(cards: list, n: int, seed: int | None = None) -> list[int]:
    """Sample n card indices from a cards list."""
    rng = random.Random(seed)
    indices = list(range(len(cards)))
    return rng.sample(indices, min(n, len(indices)))
