"""Phase 3 admin API for the topic-pipeline DAG.

These routes are additive — none of the per-stage admin pages or the
existing `/admin/v2/books/{book_id}/chapters/...` routes change. The new
endpoints are guideline-keyed (one DAG instance per topic), since the
cascade orchestrator's state map is keyed by `guideline_id`.

Endpoints:
- GET  /admin/v2/dag/definition                                  → DAG topology (stages, edges)
- GET  /admin/v2/topics/{guideline_id}/dag                       → per-stage state + cascade
- POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun   → cascade from stage
- POST /admin/v2/topics/{guideline_id}/dag/run-all               → cascade over not-done
- POST /admin/v2/topics/{guideline_id}/dag/cancel                → soft-cancel
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from book_ingestion_v2.dag.cascade import (
    CascadeAlreadyActiveError,
    CascadeNotReadyError,
    get_cascade_orchestrator,
)
from book_ingestion_v2.dag.topic_pipeline_dag import DAG
from book_ingestion_v2.models.database import BookChapter
from book_ingestion_v2.models.schemas import (
    CascadeCancelResponse,
    CascadeInfo,
    CascadeKickoffResponse,
    DAGDefinitionResponse,
    DAGStageDefinition,
    RunAllCascadeRequest,
    StartCascadeRequest,
    TopicDAGResponse,
    TopicDAGStageRow,
)
from book_ingestion_v2.repositories.topic_stage_run_repository import (
    TopicStageRunRepository,
)
from book_ingestion_v2.services.chapter_job_service import ChapterJobLockError
from book_ingestion_v2.services.topic_pipeline_status_service import (
    TopicPipelineStatusService,
)
from shared.models.entities import TeachingGuideline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v2", tags=["Book Ingestion V2 - Topic DAG"])


# ───── Helpers ─────


def _resolve_topic_keys(db: Session, guideline_id: str) -> tuple[str, str, str]:
    """Return `(book_id, chapter_id, topic_key)` for a guideline.

    Raises 404 if the guideline is missing or its chapter row can't be
    found. Most cascade callers only have a `guideline_id`; the launcher
    contracts and the status service still want all three.
    """
    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == guideline_id
    ).first()
    if not guideline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guideline {guideline_id} not found",
        )

    chapter_key = guideline.chapter_key  # "chapter-N"
    try:
        chapter_number = int(chapter_key.split("-", 1)[1])
    except (IndexError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Guideline {guideline_id} has malformed chapter_key {chapter_key!r}",
        )

    chapter = db.query(BookChapter).filter(
        BookChapter.book_id == guideline.book_id,
        BookChapter.chapter_number == chapter_number,
    ).first()
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Chapter {chapter_number} not found for book "
                f"{guideline.book_id} (guideline {guideline_id})"
            ),
        )

    topic_key = guideline.topic_key or guideline.topic
    return guideline.book_id, chapter.id, topic_key


def _cascade_info(guideline_id: str) -> Optional[CascadeInfo]:
    cascade = get_cascade_orchestrator().get_cascade(guideline_id)
    if cascade is None:
        return None
    return CascadeInfo(
        cascade_id=cascade.cascade_id,
        running=cascade.running,
        halted_at=cascade.halted_at,
        cancelled=cascade.cancelled,
        pending=sorted(cascade.pending),
        started_at=cascade.started_at,
        stage_results=dict(cascade.stage_results),
    )


def _build_dag_view(db: Session, guideline_id: str) -> TopicDAGResponse:
    """Pull the per-stage rows + DAG topology into one response.

    Lazy backfill happens implicitly on the dashboard read flow via
    `TopicPipelineStatusService.get_pipeline_status`; this endpoint is
    state-only and skips the artifact reconstruction. If a stage has no
    row yet, it shows up as `pending`.
    """
    repo = TopicStageRunRepository(db)
    rows_by_stage = {r.stage_id: r for r in repo.list_for_topic(guideline_id)}

    stages: list[TopicDAGStageRow] = []
    for stage in DAG.stages:
        row = rows_by_stage.get(stage.id)
        if row is None:
            stages.append(
                TopicDAGStageRow(
                    stage_id=stage.id,
                    label=stage.label,
                    depends_on=list(stage.depends_on),
                    state="pending",
                )
            )
        else:
            stages.append(
                TopicDAGStageRow(
                    stage_id=stage.id,
                    label=stage.label,
                    depends_on=list(stage.depends_on),
                    state=row.state,
                    is_stale=bool(row.is_stale),
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                    duration_ms=row.duration_ms,
                    last_job_id=row.last_job_id,
                    summary=row.summary_json,
                )
            )

    return TopicDAGResponse(
        guideline_id=guideline_id,
        stages=stages,
        cascade=_cascade_info(guideline_id),
    )


# ───── Read endpoints ─────


@router.get("/dag/definition", response_model=DAGDefinitionResponse)
def get_dag_definition():
    """Topology of the topic DAG. Static across topics — pinned by the
    code, not the database."""
    return DAGDefinitionResponse(
        stages=[
            DAGStageDefinition(
                id=s.id,
                scope=s.scope.value,
                label=s.label,
                depends_on=list(s.depends_on),
            )
            for s in DAG.stages
        ]
    )


@router.get("/topics/{guideline_id}/dag", response_model=TopicDAGResponse)
def get_topic_dag(guideline_id: str, db: Session = Depends(get_db)):
    """Per-stage state for one topic, plus active cascade summary.

    Triggers lazy backfill of `topic_stage_runs` so the response
    reflects current artifact reality even for topics that pre-date
    Phase 2.
    """
    book_id, chapter_id, topic_key = _resolve_topic_keys(db, guideline_id)

    # Drive backfill via the existing status service (Phase 2 entry
    # point). Reads the artifact tables and inserts missing rows; we
    # don't use its response shape, but the side effect is what makes
    # the dag-view accurate for legacy topics.
    try:
        TopicPipelineStatusService(db).get_pipeline_status(
            book_id, chapter_id, topic_key
        )
    except LookupError:
        # Should not happen — `_resolve_topic_keys` already verified
        # the guideline exists. Treat as 404 for symmetry.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guideline {guideline_id} not found",
        )

    return _build_dag_view(db, guideline_id)


# ───── Cascade endpoints ─────


@router.post(
    "/topics/{guideline_id}/stages/{stage_id}/rerun",
    response_model=CascadeKickoffResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def rerun_stage(
    guideline_id: str,
    stage_id: str,
    body: StartCascadeRequest = StartCascadeRequest(),
    db: Session = Depends(get_db),
):
    """Re-run one stage; the cascade engine handles descendants.

    Returns 409 if a cascade is already active OR if the per-topic
    chapter-job lock is held by another in-flight stage.
    """
    if not DAG.has(stage_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown stage {stage_id!r}",
        )
    book_id, chapter_id, _ = _resolve_topic_keys(db, guideline_id)
    try:
        cascade = get_cascade_orchestrator().start_cascade(
            db,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            from_stage_id=stage_id,
            force=body.force,
            quality_level=body.quality_level,
        )
    except CascadeAlreadyActiveError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "cascade_active", "message": str(e)},
        )
    except CascadeNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "upstream_not_done", "message": str(e)},
        )
    except ChapterJobLockError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "stage_running", "message": str(e)},
        )
    return CascadeKickoffResponse(
        cascade_id=cascade.cascade_id,
        pending=sorted(cascade.pending),
        running=cascade.running,
    )


@router.post(
    "/topics/{guideline_id}/dag/run-all",
    response_model=CascadeKickoffResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_all_stages(
    guideline_id: str,
    body: RunAllCascadeRequest = RunAllCascadeRequest(),
    db: Session = Depends(get_db),
):
    """Cascade over every stage that isn't already `done`.

    Use this for "fill in what's missing"; for a forced rebuild start a
    rerun on the upstream-most stage instead.
    """
    book_id, chapter_id, _ = _resolve_topic_keys(db, guideline_id)
    try:
        cascade = get_cascade_orchestrator().start_cascade(
            db,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            from_stage_id=None,
            force=False,
            quality_level=body.quality_level,
        )
    except CascadeAlreadyActiveError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "cascade_active", "message": str(e)},
        )
    except ChapterJobLockError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "stage_running", "message": str(e)},
        )
    if not cascade.pending and cascade.running is None:
        return CascadeKickoffResponse(
            cascade_id=cascade.cascade_id,
            pending=[],
            running=None,
            message="All stages already done.",
        )
    return CascadeKickoffResponse(
        cascade_id=cascade.cascade_id,
        pending=sorted(cascade.pending),
        running=cascade.running,
    )


@router.post(
    "/topics/{guideline_id}/dag/cancel",
    response_model=CascadeCancelResponse,
)
def cancel_cascade(guideline_id: str, db: Session = Depends(get_db)):
    """Soft-cancel any active cascade. The currently running stage
    finishes; nothing else launches.

    Validates `guideline_id` so a typo'd id 404s rather than silently
    returning `cancelled=False` (which is indistinguishable from "no
    cascade was active").
    """
    _resolve_topic_keys(db, guideline_id)
    cancelled = get_cascade_orchestrator().cancel(guideline_id)
    return CascadeCancelResponse(cancelled=cancelled)
