"""
Book Ingestion Evaluation Configuration

Settings for evaluating the topic extraction pipeline.
"""

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

EVAL_DIR = Path(__file__).parent
RUNS_DIR = EVAL_DIR / "runs"
RESULTS_FILE = EVAL_DIR / "results.tsv"


@dataclass
class IngestionEvalConfig:
    """Settings for a single book ingestion evaluation run."""

    # Target chapter
    chapter_id: str = ""
    book_id: str = ""
    chapter_number: int = 0

    # LLM - Judge
    evaluator_provider: str = field(
        default_factory=lambda: os.environ.get("EVAL_LLM_PROVIDER", "openai")
    )
    evaluator_model: str = "gpt-5.2"
    evaluator_reasoning_effort: str = "high"
    anthropic_evaluator_model: str = "claude-opus-4-6"
    anthropic_evaluator_thinking_budget: int = 20000

    # API Keys
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )

    @classmethod
    def from_db(cls, db_session, **kwargs) -> "IngestionEvalConfig":
        """Create config with evaluator model read from the DB llm_config table."""
        from shared.services.llm_config_service import LLMConfigService

        config_service = LLMConfigService(db_session)
        eval_cfg = config_service.get_config("eval_evaluator")

        kwargs["evaluator_provider"] = eval_cfg["provider"]
        if eval_cfg["provider"] == "anthropic":
            kwargs["anthropic_evaluator_model"] = eval_cfg["model_id"]
        elif eval_cfg["provider"] != "claude_code":
            kwargs["evaluator_model"] = eval_cfg["model_id"]

        return cls(**kwargs)

    @property
    def evaluator_model_label(self) -> str:
        if self.evaluator_provider == "anthropic":
            return self.anthropic_evaluator_model
        if self.evaluator_provider == "claude_code":
            return "claude-code"
        return self.evaluator_model

    def create_llm_service(self):
        """Create an LLMService for the evaluator component."""
        from shared.services.llm_service import LLMService

        provider = self.evaluator_provider
        model_id = (
            self.anthropic_evaluator_model if provider == "anthropic"
            else "claude-code" if provider == "claude_code"
            else self.evaluator_model
        )
        return LLMService(
            api_key=self.openai_api_key,
            provider=provider,
            model_id=model_id,
            anthropic_api_key=self.anthropic_api_key or None,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("openai_api_key", None)
        d.pop("anthropic_api_key", None)
        return d
