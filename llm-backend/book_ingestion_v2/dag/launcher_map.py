"""Derived `stage_id → launch_fn` map.

Lives here (not in `stage_launchers.py`) to break the natural cycle:
    topic_pipeline_dag → stages → stage_launchers → DAG.

Importing this module triggers the full DAG load. Adding a new stage
requires no edit here — the dict is regenerated from `DAG.stages` on
import.
"""
from __future__ import annotations

from typing import Callable

from book_ingestion_v2.dag.topic_pipeline_dag import DAG


LAUNCHER_BY_STAGE: dict[str, Callable[..., str]] = {
    s.id: s.launch for s in DAG.stages
}
