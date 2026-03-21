"""
Simplicity Quality Pipeline — Configuration

Reuses SessionExperienceConfig from session_experience pipeline.
Same topic pool, personas, and session runner infrastructure.
"""

from autoresearch.session_experience.evaluation.config import (
    SessionExperienceConfig as SimplicityConfig,
    RUNS_DIR as _SE_RUNS_DIR,
    TOPIC_POOL,
    PERSONAS_DIR,
    select_topics,
)
from pathlib import Path

# Separate runs dir to avoid mixing with session_experience artifacts
RUNS_DIR = Path("/tmp/simplicity_quality_runs")
