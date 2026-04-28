"""Repository for `topic_stage_runs` rows (Phase 2).

One row per `(guideline_id, stage_id)`. The hook in `run_in_background_v2`
calls `upsert_running` on stage entry and `upsert_terminal` on stage exit.
The status service uses `get` / `list_for_topic` for the lazy backfill read
path.

`mark_stale` is reserved for Phase 3 cascade orchestration.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import TopicStageRun


# Terminal states accepted by `upsert_terminal`. `pending` and `running`
# are non-terminal and must not be written through this method.
TERMINAL_STATES = ("done", "failed")


class TopicStageRunRepository:
    """CRUD for `topic_stage_runs`. Commits on every mutation — callers do
    not need to wrap calls in their own transaction."""

    def __init__(self, db: Session):
        self.db = db

    # ───── Reads ─────

    def get(self, guideline_id: str, stage_id: str) -> Optional[TopicStageRun]:
        return (
            self.db.query(TopicStageRun)
            .filter(
                TopicStageRun.guideline_id == guideline_id,
                TopicStageRun.stage_id == stage_id,
            )
            .first()
        )

    def list_for_topic(self, guideline_id: str) -> List[TopicStageRun]:
        return (
            self.db.query(TopicStageRun)
            .filter(TopicStageRun.guideline_id == guideline_id)
            .all()
        )

    # ───── Writes ─────

    def upsert_running(
        self,
        guideline_id: str,
        stage_id: str,
        *,
        job_id: Optional[str] = None,
        started_at: Optional[datetime] = None,
    ) -> TopicStageRun:
        """Mark a stage as running. Clears the previous run's terminal data
        so a stale view never shows mixed state."""
        started_at = started_at or datetime.utcnow()
        row = self.get(guideline_id, stage_id)
        if row is None:
            row = TopicStageRun(guideline_id=guideline_id, stage_id=stage_id)
            self.db.add(row)
        row.state = "running"
        row.started_at = started_at
        row.completed_at = None
        row.duration_ms = None
        row.summary_json = None
        if job_id is not None:
            row.last_job_id = job_id
        self.db.commit()
        self.db.refresh(row)
        return row

    def upsert_terminal(
        self,
        guideline_id: str,
        stage_id: str,
        *,
        state: str,
        completed_at: Optional[datetime] = None,
        duration_ms: Optional[int] = None,
        started_at: Optional[datetime] = None,
        summary: Optional[dict[str, Any]] = None,
        content_anchor: Optional[str] = None,
        last_job_id: Optional[str] = None,
    ) -> TopicStageRun:
        """Mark a stage as terminal (`done` or `failed`).

        On `done`, clears `is_stale` — the stage's output now reflects its
        inputs as of `started_at`. On `failed`, leaves `is_stale` alone.
        `started_at` is backfilled only if the row's value is missing — the
        normal flow sets it via `upsert_running`, but if that write was
        skipped (DB error, race) the terminal call provides it as a fallback.
        """
        if state not in TERMINAL_STATES:
            raise ValueError(
                f"upsert_terminal called with non-terminal state {state!r}; "
                f"expected one of {TERMINAL_STATES}"
            )
        completed_at = completed_at or datetime.utcnow()
        row = self.get(guideline_id, stage_id)
        if row is None:
            row = TopicStageRun(guideline_id=guideline_id, stage_id=stage_id)
            self.db.add(row)
        row.state = state
        row.completed_at = completed_at
        if duration_ms is not None:
            row.duration_ms = duration_ms
        if started_at is not None and row.started_at is None:
            row.started_at = started_at
        if summary is not None:
            row.summary_json = summary
        if content_anchor is not None:
            row.content_anchor = content_anchor
        if last_job_id is not None:
            row.last_job_id = last_job_id
        if state == "done":
            row.is_stale = False
        self.db.commit()
        self.db.refresh(row)
        return row

    def mark_stale(
        self,
        guideline_id: str,
        stage_id: str,
        *,
        is_stale: bool = True,
    ) -> Optional[TopicStageRun]:
        """Phase 3 — flip `is_stale`. Returns None if no row exists yet."""
        row = self.get(guideline_id, stage_id)
        if row is None:
            return None
        row.is_stale = is_stale
        self.db.commit()
        self.db.refresh(row)
        return row

    def upsert_backfill(
        self,
        guideline_id: str,
        stage_id: str,
        *,
        state: str,
        completed_at: Optional[datetime] = None,
        last_job_id: Optional[str] = None,
        summary: Optional[dict[str, Any]] = None,
    ) -> TopicStageRun:
        """Insert a derived row for a topic that ran before Phase 2 shipped.

        Called by `TopicPipelineStatusService` on first read when no row
        exists. Only `state` + `last_job_id` + `completed_at` are
        reconstructable; `started_at` and `duration_ms` stay NULL because
        we never measured them. Idempotent: a second backfill on the same
        key updates in place rather than inserting a duplicate.
        """
        row = self.get(guideline_id, stage_id)
        if row is None:
            row = TopicStageRun(guideline_id=guideline_id, stage_id=stage_id)
            self.db.add(row)
        row.state = state
        if completed_at is not None:
            row.completed_at = completed_at
        if last_job_id is not None:
            row.last_job_id = last_job_id
        if summary is not None:
            row.summary_json = summary
        self.db.commit()
        self.db.refresh(row)
        return row
