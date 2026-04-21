"""
Chapter job service — job lock + progress tracking per chapter and per topic.

Adapts V1 JobLockService pattern. Two lock scopes:

- **Chapter-level jobs** (`guideline_id IS NULL`) — OCR, topic extraction,
  refinalization, refresher generation. One active job per chapter.
- **Topic-level jobs** (`guideline_id IS NOT NULL`) — post-sync stages
  (explanations, visuals, check-ins, practice bank, audio review, audio
  synthesis). One active job per `(chapter_id, guideline_id)`.

Reader-writer semantics: a chapter-level job and any topic-level job in the
same chapter are mutually exclusive. Two topic-level jobs in the same chapter
with different `guideline_id`s can run concurrently.

State machine: pending → running → completed|completed_with_errors|failed
Stale detection: running jobs with expired heartbeat are auto-marked failed.
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from book_ingestion_v2.constants import HEARTBEAT_STALE_THRESHOLD, PENDING_STALE_THRESHOLD, V2JobType
from book_ingestion_v2.models.database import ChapterProcessingJob
from book_ingestion_v2.models.schemas import ProcessingJobResponse

logger = logging.getLogger(__name__)

_HEARTBEAT_THRESHOLD = timedelta(seconds=HEARTBEAT_STALE_THRESHOLD)
_PENDING_THRESHOLD = timedelta(seconds=PENDING_STALE_THRESHOLD)

# Post-sync job types REQUIRE a guideline_id.
POST_SYNC_JOB_TYPES: frozenset[str] = frozenset(
    {
        V2JobType.EXPLANATION_GENERATION.value,
        V2JobType.VISUAL_ENRICHMENT.value,
        V2JobType.CHECK_IN_ENRICHMENT.value,
        V2JobType.PRACTICE_BANK_GENERATION.value,
        V2JobType.AUDIO_TEXT_REVIEW.value,
        V2JobType.AUDIO_GENERATION.value,
    }
)


class ChapterJobLockError(Exception):
    """Raised when a job lock cannot be acquired."""
    pass


class ChapterJobService:
    """
    Service to manage job locks for chapter or topic operations.

    Enforces the job state machine:
      pending → running → completed|completed_with_errors|failed
    """

    def __init__(self, db: Session):
        self.db = db

    def acquire_lock(
        self,
        book_id: str,
        chapter_id: str,
        job_type: str,
        total_items: int | None = None,
        guideline_id: str | None = None,
    ) -> str:
        """
        Create a new job in 'pending' state. Returns job_id.

        Post-sync job types REQUIRE `guideline_id`; chapter-level job types
        must NOT pass one (the index enforces NULL for chapter-level).

        Enforces reader-writer semantics across chapter- and topic-scope:
        a chapter-level job blocks all topic-level starts in the same chapter
        and vice versa.

        Raises ChapterJobLockError if a conflicting active job exists.
        """
        is_post_sync = job_type in POST_SYNC_JOB_TYPES
        if is_post_sync and not guideline_id:
            raise ChapterJobLockError(
                f"Post-sync job {job_type} requires guideline_id"
            )
        if not is_post_sync:
            # Chapter-level job: guideline_id must be NULL.
            guideline_id = None

        # Cross-scope check — chapter-level vs topic-level mutual exclusion.
        if is_post_sync:
            conflicting = self.db.query(ChapterProcessingJob).filter(
                ChapterProcessingJob.chapter_id == chapter_id,
                ChapterProcessingJob.guideline_id.is_(None),
                ChapterProcessingJob.status.in_(["pending", "running"]),
            ).first()
            if conflicting and not self._stale_or_abandoned(conflicting):
                raise ChapterJobLockError(
                    f"Chapter-level {conflicting.job_type} is active for chapter "
                    f"{chapter_id}; cannot start {job_type} for guideline "
                    f"{guideline_id}"
                )
        else:
            conflicting_topic_jobs = self.db.query(ChapterProcessingJob).filter(
                ChapterProcessingJob.chapter_id == chapter_id,
                ChapterProcessingJob.guideline_id.isnot(None),
                ChapterProcessingJob.status.in_(["pending", "running"]),
            ).all()
            live = [j for j in conflicting_topic_jobs if not self._stale_or_abandoned(j)]
            if live:
                raise ChapterJobLockError(
                    f"{len(live)} post-sync job(s) active in chapter {chapter_id}; "
                    f"cannot start chapter-level {job_type}"
                )

        # Same-scope duplicate check.
        existing_query = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.status.in_(["pending", "running"]),
        )
        if is_post_sync:
            existing_query = existing_query.filter(
                ChapterProcessingJob.guideline_id == guideline_id
            )
        else:
            existing_query = existing_query.filter(
                ChapterProcessingJob.guideline_id.is_(None)
            )
        existing = existing_query.first()

        if existing:
            if existing.status == "running" and self._is_stale(existing):
                self._mark_stale(existing)
            elif existing.status == "pending" and self._is_pending_stale(existing):
                self._mark_pending_abandoned(existing)
            else:
                scope = (
                    f"chapter={chapter_id}"
                    if not is_post_sync
                    else f"chapter={chapter_id} guideline={guideline_id}"
                )
                raise ChapterJobLockError(
                    f"Job already {existing.status} for {scope}: "
                    f"{existing.job_type} (started {existing.started_at})"
                )

        job = ChapterProcessingJob(
            id=str(uuid.uuid4()),
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            job_type=job_type,
            status="pending",
            total_items=total_items,
        )

        try:
            self.db.add(job)
            self.db.commit()
            logger.info(
                f"Job {job.id} created: chapter={chapter_id} "
                f"guideline={guideline_id} type={job_type} total_items={total_items}"
            )
            return job.id
        except IntegrityError:
            self.db.rollback()
            raise ChapterJobLockError(
                f"Another job was just created for chapter={chapter_id} "
                f"guideline={guideline_id}"
            )

    def start_job(self, job_id: str):
        """Transition pending → running. Uses row lock to prevent race."""
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).with_for_update().first()

        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.status != "pending":
            raise ValueError(f"Cannot start job in '{job.status}' state")

        job.status = "running"
        job.heartbeat_at = datetime.utcnow()
        self.db.commit()
        logger.info(f"Job {job_id} transitioned pending → running")

    def update_progress(
        self,
        job_id: str,
        current_item: Optional[str] = None,
        completed: int = 0,
        failed: int = 0,
        last_completed_item: Optional[str] = None,
        detail: Optional[str] = None,
    ):
        """Update job progress + heartbeat. Uses absolute values for idempotency.

        Preserves `pipeline_run_id` across detail overwrites — callers
        (stage `_run_*` tasks) write their own payload into `detail`; without
        this merge the orchestrator's observability tag would be clobbered at
        stage completion.
        """
        import json
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).first()
        if not job or job.status != "running":
            return

        job.current_item = current_item
        job.completed_items = completed
        job.failed_items = failed
        job.heartbeat_at = datetime.utcnow()

        if last_completed_item is not None:
            job.last_completed_item = last_completed_item
        if detail is not None:
            pipeline_run_id = None
            if job.progress_detail:
                try:
                    prev = json.loads(job.progress_detail)
                    if isinstance(prev, dict):
                        pipeline_run_id = prev.get("pipeline_run_id")
                except (json.JSONDecodeError, TypeError):
                    pass
            if pipeline_run_id:
                try:
                    new_detail = json.loads(detail)
                    if isinstance(new_detail, dict) and "pipeline_run_id" not in new_detail:
                        new_detail["pipeline_run_id"] = pipeline_run_id
                        detail = json.dumps(new_detail)
                except (json.JSONDecodeError, TypeError):
                    pass
            job.progress_detail = detail

        self.db.commit()

    def record_pipeline_run_id(self, job_id: str, pipeline_run_id: str):
        """Tag the job's progress_detail with {pipeline_run_id} for observability.

        Called by the orchestrator right after `acquire_lock` + launcher,
        before the job transitions to running. Unlike `update_progress`,
        this method ignores job status and merges (not overwrites) into
        whatever `progress_detail` already holds.
        """
        import json
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).first()
        if not job:
            return
        try:
            existing = json.loads(job.progress_detail) if job.progress_detail else {}
            if not isinstance(existing, dict):
                existing = {"raw": existing}
        except (json.JSONDecodeError, TypeError):
            existing = {}
        existing["pipeline_run_id"] = pipeline_run_id
        job.progress_detail = json.dumps(existing)
        self.db.commit()

    def release_lock(
        self, job_id: str, status: str = "completed", error: str = None
    ):
        """Transition running → completed/failed. Terminal state."""
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).with_for_update().first()

        if not job:
            logger.warning(f"Cannot release lock: job {job_id} not found")
            return
        if job.status not in ("running", "pending"):
            logger.warning(f"Cannot release job {job_id} in '{job.status}' state")
            return

        old_status = job.status
        job.status = status
        job.completed_at = datetime.utcnow()
        job.error_message = error
        self.db.commit()
        logger.info(f"Job {job_id} transitioned {old_status} → {status}")

    def get_job(self, job_id: str) -> Optional[ProcessingJobResponse]:
        """Get job by ID as response schema."""
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).first()
        if not job:
            return None
        return self._to_response(job)

    def reap_stale_post_sync_jobs(
        self, chapter_id: str, guideline_id: Optional[str] = None
    ) -> int:
        # Stale-detection side effects inside `acquire_lock` and `get_latest_job`
        # only fire for whichever job the caller happens to query. Callers that
        # read pipeline status via `TopicPipelineStatusService` (read-only, no
        # side effects) see a stale orphaned job as `running` — so a
        # force=true pipeline kickoff excludes that stage from `stages_to_run`.
        # Reaping across all post-sync job types up-front makes the status
        # snapshot reflect reality before stage selection.
        query = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.status.in_(["pending", "running"]),
            ChapterProcessingJob.job_type.in_(POST_SYNC_JOB_TYPES),
        )
        if guideline_id is not None:
            query = query.filter(ChapterProcessingJob.guideline_id == guideline_id)
        reaped = 0
        for job in query.all():
            if job.status == "running" and self._is_stale(job):
                self._mark_stale(job)
                reaped += 1
            elif job.status == "pending" and self._is_pending_stale(job):
                self._mark_pending_abandoned(job)
                reaped += 1
        return reaped

    def is_job_heartbeat_stale(self, job_id: str) -> bool:
        """True if the job's heartbeat is older than `HEARTBEAT_STALE_THRESHOLD`.

        Used by the orchestrator's poll loop to detect dead backing threads
        without relying on wall-time-since-orchestrator-start — the latter
        false-fails healthy long runs whose backing thread is still making
        steady progress. Cross-session visibility is enforced by expiring
        the ORM cache before reading.
        """
        self.db.expire_all()
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id
        ).first()
        if not job:
            return False
        if job.status not in ("pending", "running"):
            return False
        if job.status == "pending":
            return self._is_pending_stale(job)
        return self._is_stale(job)

    def get_latest_job(
        self,
        chapter_id: str,
        job_type: Optional[str] = None,
        guideline_id: Optional[str] = None,
    ) -> Optional[ProcessingJobResponse]:
        """Get most recent job for a chapter (optionally scoped to topic).

        When `guideline_id` is passed, the query filters by it (topic-scope).
        When not passed, the query returns the most recent row matching the
        other filters — which, for callers that still use the old
        `lock_chapter_id = guideline_id or chapter_id` pattern, continues to
        surface historical overloaded rows correctly.

        Detects stale jobs as a side effect of reading the latest.
        """
        query = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id
        )
        if job_type:
            query = query.filter(ChapterProcessingJob.job_type == job_type)
        if guideline_id is not None:
            query = query.filter(ChapterProcessingJob.guideline_id == guideline_id)
        job = query.order_by(ChapterProcessingJob.created_at.desc()).first()

        if not job:
            return None

        # Server-side stale detection
        if job.status == "running" and self._is_stale(job):
            self._mark_stale(job)
        elif job.status == "pending" and self._is_pending_stale(job):
            self._mark_pending_abandoned(job)

        return self._to_response(job)

    def _stale_or_abandoned(self, job: ChapterProcessingJob) -> bool:
        """True if the job is stale (running, no heartbeat) or abandoned (pending too long)."""
        if job.status == "running":
            return self._is_stale(job)
        if job.status == "pending":
            return self._is_pending_stale(job)
        return False

    def _is_stale(self, job: ChapterProcessingJob) -> bool:
        if not job.heartbeat_at:
            if not job.started_at:
                return True
            return (datetime.utcnow() - job.started_at) > _HEARTBEAT_THRESHOLD
        return (datetime.utcnow() - job.heartbeat_at) > _HEARTBEAT_THRESHOLD

    def _is_pending_stale(self, job: ChapterProcessingJob) -> bool:
        if not job.started_at:
            return True
        return (datetime.utcnow() - job.started_at) > _PENDING_THRESHOLD

    def _mark_stale(self, job: ChapterProcessingJob):
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job.id
        ).with_for_update().first()

        if job.status != "running":
            return
        if not self._is_stale(job):
            return

        job.status = "failed"
        job.completed_at = datetime.utcnow()
        job.error_message = (
            f"Job interrupted (no heartbeat since "
            f"{job.heartbeat_at.isoformat() if job.heartbeat_at else 'never'}). "
            f"Resume from chunk {job.last_completed_item or 'start'}."
        )
        self.db.commit()
        logger.warning(f"Job {job.id} marked stale → failed")

    def _mark_pending_abandoned(self, job: ChapterProcessingJob):
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job.id
        ).with_for_update().first()

        if job.status != "pending":
            return

        job.status = "failed"
        job.completed_at = datetime.utcnow()
        job.error_message = (
            f"Job abandoned (stuck in pending since {job.started_at.isoformat() if job.started_at else 'never'})."
        )
        self.db.commit()
        logger.warning(f"Job {job.id} marked abandoned → failed")

    def append_stage_snapshots(self, job_id: str, snapshots: list[dict]):
        """Append stage snapshots to job's stage_snapshots_json."""
        import json
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id,
        ).first()
        if not job:
            return
        existing = json.loads(job.stage_snapshots_json) if job.stage_snapshots_json else []
        existing.extend(snapshots)
        job.stage_snapshots_json = json.dumps(existing, default=str)
        job.heartbeat_at = datetime.utcnow()
        self.db.commit()

    def get_stage_snapshots(self, job_id: str, guideline_id: str | None = None) -> list[dict]:
        """Get stage snapshots for a job, optionally filtered by guideline_id."""
        import json
        job = self.db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.id == job_id,
        ).first()
        if not job or not job.stage_snapshots_json:
            return []
        snapshots = json.loads(job.stage_snapshots_json)
        if guideline_id:
            snapshots = [s for s in snapshots if s.get("guideline_id") == guideline_id]
        return snapshots

    def _to_response(self, job: ChapterProcessingJob) -> ProcessingJobResponse:
        import json
        progress = None
        if job.progress_detail:
            try:
                progress = json.loads(job.progress_detail)
            except (json.JSONDecodeError, TypeError):
                progress = {"raw": job.progress_detail}

        return ProcessingJobResponse(
            job_id=job.id,
            chapter_id=job.chapter_id,
            job_type=job.job_type,
            status=job.status,
            total_items=job.total_items,
            completed_items=job.completed_items or 0,
            failed_items=job.failed_items or 0,
            current_item=job.current_item,
            last_completed_item=job.last_completed_item,
            progress_detail=progress,
            model_provider=job.model_provider,
            model_id=job.model_id,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
        )
