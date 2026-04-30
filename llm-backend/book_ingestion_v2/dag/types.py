"""DAG primitives for the topic-pipeline orchestration.

A `Stage` bundles everything the orchestrator and the status service need to
know about one pipeline step: how to launch it, how to read its current
artefact state, and (eventually) how to detect staleness.

The single source of truth for the topic pipeline is
`dag/topic_pipeline_dag.py`, which composes a `TopicPipelineDAG` from the
per-stage `STAGE` exports under `book_ingestion_v2/stages/`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

from book_ingestion_v2.models.schemas import StageId, StageStatus

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session
    from shared.models.entities import TopicExplanation


class StageScope(str, Enum):
    """Scope of orchestration a stage belongs to."""

    TOPIC = "topic"
    CHAPTER = "chapter"


# Phase 1 keeps the existing rich `StageStatus` shape (state ∈
# done|warning|running|ready|blocked|failed). Phase 2+ may introduce a
# narrower shape carrying just the artefact signal + per-stage hash; until
# then this alias keeps callers honest about what `status_check` returns.
StageStatusOutput = StageStatus


@dataclass(frozen=True)
class StatusContext:
    """Bundle of pre-loaded inputs shared across every stage's status check.

    The status service loads `explanations` once per topic and reuses the
    result for all eight stages — the existing service preloads the same
    inputs and we preserve that behaviour.
    """

    db: "Session"
    guideline_id: str
    chapter_id: str
    explanations: list["TopicExplanation"]
    content_anchor: Optional[datetime]


# A stage launcher acquires its job lock and kicks the background task —
# returns the new `chapter_processing_jobs.id`. Kwargs vary per stage; the
# orchestrator passes whatever the launcher needs (book_id/chapter_id always,
# force/review_rounds/language conditionally).
LaunchFn = Callable[..., str]
StatusCheckFn = Callable[[StatusContext], StageStatusOutput]
StalenessCheckFn = Callable[..., bool]


@dataclass
class Stage:
    """One node in a pipeline DAG.

    `launch` returns a `chapter_processing_jobs.id` once the lock is acquired
    and the background worker is queued.

    `status_check` reads the current artefact state and overlays the latest
    job's status, returning a `StageStatusOutput` (== `StageStatus` in v1).

    `staleness_check` is unused in Phase 1 — Phase 3 cascade orchestration
    will wire it in for hash-based invalidation of downstream stages.
    """

    id: str
    scope: StageScope
    label: str
    depends_on: tuple[str, ...]
    launch: LaunchFn
    status_check: StatusCheckFn
    staleness_check: Optional[StalenessCheckFn] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = None
    review_rounds: Optional[int] = None

    def __post_init__(self) -> None:
        # Coerce to tuple so a list silently passed by a future contributor
        # doesn't make the dataclass field mutable.
        self.depends_on = tuple(self.depends_on)
        if not self.id:
            raise ValueError("Stage requires non-empty id")
        if not self.label:
            raise ValueError(f"Stage {self.id} requires non-empty label")
        if not callable(self.launch):
            raise TypeError(f"Stage {self.id}.launch must be callable")
        if not callable(self.status_check):
            raise TypeError(f"Stage {self.id}.status_check must be callable")


class TopicPipelineDAG:
    """Holds the topic-scope pipeline DAG and offers traversal helpers.

    All structure is derived from `Stage.depends_on`. Construction validates
    that every dep references a known stage and that no stage id is reused.
    `validate_acyclic()` enforces no cycles.
    """

    def __init__(self, stages: list[Stage]):
        self.stages: list[Stage] = list(stages)
        self._by_id: dict[str, Stage] = {}
        for s in self.stages:
            if s.id in self._by_id:
                raise ValueError(f"Duplicate stage id: {s.id}")
            self._by_id[s.id] = s
        for s in self.stages:
            for dep in s.depends_on:
                if dep not in self._by_id:
                    raise ValueError(
                        f"Stage {s.id} depends on unknown stage {dep!r}"
                    )

    # ───── Lookup ─────

    def get(self, stage_id: str) -> Stage:
        return self._by_id[stage_id]

    def has(self, stage_id: str) -> bool:
        return stage_id in self._by_id

    @property
    def stage_ids(self) -> list[str]:
        return [s.id for s in self.stages]

    # ───── Traversal ─────

    def validate_acyclic(self) -> None:
        """Raise `ValueError` if the DAG contains a cycle.

        Implemented by running `topo_sort()` for the side effect — it raises
        when stages can no longer be placed.
        """
        self.topo_sort()

    def topo_sort(self) -> list[Stage]:
        """Stages in topological order, ties broken by declaration order.

        For Phase 1 this matches the old `PIPELINE_LAYERS` sequence exactly
        when stages are declared in the corresponding order, so the
        super-button runs every stage in the same order it always did.
        """
        placed: set[str] = set()
        result: list[Stage] = []
        remaining: list[Stage] = list(self.stages)
        while remaining:
            for s in remaining:
                if all(dep in placed for dep in s.depends_on):
                    result.append(s)
                    placed.add(s.id)
                    remaining.remove(s)
                    break
            else:
                raise ValueError(
                    "DAG cycle detected. Unplaced stages: "
                    f"{[s.id for s in remaining]}"
                )
        return result

    def descendants(self, stage_id: str) -> set[str]:
        """All stages that transitively depend on `stage_id`."""
        if stage_id not in self._by_id:
            raise KeyError(stage_id)
        children: dict[str, list[str]] = {s.id: [] for s in self.stages}
        for s in self.stages:
            for dep in s.depends_on:
                children[dep].append(s.id)
        result: set[str] = set()
        queue: list[str] = list(children[stage_id])
        while queue:
            sid = queue.pop()
            if sid in result:
                continue
            result.add(sid)
            queue.extend(children[sid])
        return result

    def ready_nodes(self, state_map: dict[str, str]) -> list[Stage]:
        """Stages whose every dep is `done` and which are not themselves
        `done` or `running`. Used by Phase 3 cascade orchestration."""
        ready: list[Stage] = []
        for s in self.stages:
            current = state_map.get(s.id)
            if current in ("done", "running"):
                continue
            if all(state_map.get(dep) == "done" for dep in s.depends_on):
                ready.append(s)
        return ready

    # ───── Serialisation ─────

    def to_json(self) -> dict[str, Any]:
        """Topology-only representation for the React Flow UI (Phase 5)."""
        return {
            "stages": [
                {
                    "id": s.id,
                    "scope": s.scope.value,
                    "label": s.label,
                    "depends_on": list(s.depends_on),
                    "description": s.description,
                    "review_rounds": s.review_rounds,
                }
                for s in self.stages
            ],
        }
