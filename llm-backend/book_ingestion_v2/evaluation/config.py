"""
Book Ingestion Evaluation Configuration

Settings for evaluating the topic extraction pipeline.
"""

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
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

    @property
    def evaluator_model_label(self) -> str:
        if self.evaluator_provider == "anthropic":
            return self.anthropic_evaluator_model
        return self.evaluator_model

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("openai_api_key", None)
        d.pop("anthropic_api_key", None)
        return d
