"""
Explanation Quality Evaluation Configuration

Centralizes settings for the explanation quality evaluation pipeline.
Simpler than the tutor config — no session/persona/simulator needed.
"""

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from dotenv import load_dotenv

# Load .env from llm-backend root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Path constants
EVAL_DIR = Path(__file__).parent
RUNS_DIR = EVAL_DIR / "runs"


@dataclass
class ExplanationEvalConfig:
    """All settings for an explanation quality evaluation run."""

    # Topic
    topic_id: str = ""
    topic_title: str = ""
    grade: int = 1
    subject: str = "Mathematics"

    # LLM - Evaluator (judges explanation quality)
    evaluator_provider: str = ""
    evaluator_model: str = ""
    evaluator_reasoning_effort: str = "high"
    anthropic_evaluator_model: str = ""
    anthropic_evaluator_thinking_budget: int = 20000

    # LLM - Generator (generates explanations — same as production)
    generator_provider: str = ""
    generator_model: str = ""

    # API Keys (not serialized)
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )

    @classmethod
    def from_db(cls, db_session, **kwargs) -> "ExplanationEvalConfig":
        """Create config with models read from the DB llm_config table."""
        from shared.services.llm_config_service import LLMConfigService

        config_service = LLMConfigService(db_session)

        # Evaluator — uses eval_evaluator config
        eval_cfg = config_service.get_config("eval_evaluator")
        kwargs["evaluator_provider"] = eval_cfg["provider"]
        if eval_cfg["provider"] == "anthropic":
            kwargs["anthropic_evaluator_model"] = eval_cfg["model_id"]
        elif eval_cfg["provider"] != "claude_code":
            kwargs["evaluator_model"] = eval_cfg["model_id"]

        # Generator — uses explanation_generator config (same model as production)
        gen_cfg = config_service.get_config("explanation_generator")
        kwargs["generator_provider"] = gen_cfg["provider"]
        if gen_cfg["provider"] != "claude_code":
            kwargs["generator_model"] = gen_cfg["model_id"]

        return cls(**kwargs)

    def create_llm_service(self, component: str):
        """Create an LLMService for the given component ('evaluator' or 'generator')."""
        from shared.services.llm_service import LLMService

        if component == "evaluator":
            provider = self.evaluator_provider
            model_id = (
                self.anthropic_evaluator_model if provider == "anthropic"
                else "claude-code" if provider == "claude_code"
                else self.evaluator_model
            )
        elif component == "generator":
            provider = self.generator_provider
            model_id = (
                "claude-code" if provider == "claude_code"
                else self.generator_model
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
    def evaluator_model_label(self) -> str:
        if self.evaluator_provider == "anthropic":
            return self.anthropic_evaluator_model
        if self.evaluator_provider == "claude_code":
            return "claude-code"
        return self.evaluator_model

    @property
    def generator_model_label(self) -> str:
        if self.generator_provider == "claude_code":
            return "claude-code"
        return self.generator_model

    def to_dict(self) -> dict:
        """Serialize config for saving, excluding API keys."""
        d = asdict(self)
        d.pop("openai_api_key", None)
        d.pop("anthropic_api_key", None)
        return d
