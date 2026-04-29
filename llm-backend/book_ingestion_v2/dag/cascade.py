"""Phase 3 — cascade orchestrator for the topic pipeline.

Event-driven, not polling. The trigger is the terminal-write hook in
`run_in_background_v2`: when a topic stage finishes, the hook calls
`on_stage_complete`, which (if a cascade is active for that topic) marks
direct descendants stale and launches the next ready stage.

Why event-driven instead of polling: keeps the cascade decoupled from any
caller's lifetime. The API endpoint that kicks off a cascade returns 202
immediately — the cascade runs entirely off the background-thread chain
that already exists for stage execution.

State lives in-memory only. A server restart drops active cascades; the
admin can re-trigger from whichever stage is no longer `done`. This
matches the existing `TopicPipelineOrchestrator`, which also holds state
in a daemon thread and dies on restart.

Concurrency: a single `RLock` guards the cascades dict and per-cascade
mutations. Stage launches happen INSIDE the lock — they only do a quick
DB insert (`acquire_lock`) plus a daemon-thread spawn before returning.
The actual stage work runs on that other thread and re-enters via
`on_stage_complete`.

Why one stage at a time per topic: the partial unique index
`idx_chapter_active_topic_job` on `chapter_processing_jobs` enforces at
most one active job per `(chapter_id, guideline_id)`. Even sibling
stages with no DAG edge between them would race on that index.
`TopicPipelineOrchestrator` learned this the hard way; cascade follows
the same serial-within-topic discipline.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from book_ingestion_v2.dag.launcher_map import LAUNCHER_BY_STAGE
from book_ingestion_v2.dag.topic_pipeline_dag import DAG
from book_ingestion_v2.repositories.topic_stage_run_repository import (
    TopicStageRunRepository,
)
from book_ingestion_v2.services.chapter_job_service import ChapterJobLockError

logger = logging.getLogger(__name__)


class CascadeAlreadyActiveError(Exception):
    """`start_cascade` called while a cascade is already active for the topic."""


class CascadeNotReadyError(Exception):
    """`start_cascade(from_stage_id=X)` called when X has unmet upstream deps.

    Without this guard the cascade registers, finds no ready stage to
    launch, and gets stuck with `running=None` — blocking future
    kickoffs until someone hits the cancel endpoint.
    """


@dataclass
class CascadeState:
    cascade_id: str
    book_id: str
    chapter_id: str
    guideline_id: str
    quality_level: str
    force_first: bool
    pending: set[str]
    running: Optional[str] = None
    halted_at: Optional[str] = None
    cancelled: bool = False
    started_at: datetime = field(default_factory=datetime.utcnow)
    stage_results: dict[str, str] = field(default_factory=dict)
    # Descendants this cascade flagged stale at kickoff. On halt-on-failure
    # we clear ONLY these — rows that were already stale before the cascade
    # represent legitimate signals from a prior cascade or operator, and a
    # failed rerun shouldn't erase them.
    stale_marked: set[str] = field(default_factory=set)


def build_launcher_kwargs(
    stage_id: str,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    quality_level: str = "balanced",
    force: bool = False,
) -> dict:
    """Stage-specific kwargs for `Stage.launch`.

    Mirrors `TopicPipelineOrchestrator._launcher_kwargs` so cascade and
    the synchronous orchestrator stay in sync. Both should eventually
    move onto `Stage` itself (see Phase 1 follow-up notes), but doing it
    here in Phase 3 would balloon the diff.
    """
    from book_ingestion_v2.services.topic_pipeline_orchestrator import (
        QUALITY_ROUNDS,
    )

    rounds = QUALITY_ROUNDS.get(quality_level, QUALITY_ROUNDS["balanced"])
    kwargs: dict = {
        "book_id": book_id,
        "chapter_id": chapter_id,
        "guideline_id": guideline_id,
    }
    if stage_id in ("explanations", "visuals", "check_ins", "practice_bank"):
        kwargs["review_rounds"] = rounds.get(stage_id, 1)
        kwargs["force"] = force
        if stage_id == "explanations":
            kwargs["mode"] = "generate"
    elif stage_id == "baatcheet_dialogue":
        kwargs["force"] = force
        kwargs["review_rounds"] = rounds.get("baatcheet_dialogue", 1)
    elif stage_id == "baatcheet_visuals":
        kwargs["force"] = force
    elif stage_id == "audio_review":
        kwargs["language"] = None
        kwargs["force"] = force
    elif stage_id == "audio_synthesis":
        kwargs["force"] = force
    elif stage_id == "baatcheet_audio_review":
        kwargs["language"] = None
        kwargs["force"] = force
    elif stage_id == "baatcheet_audio_synthesis":
        kwargs["force"] = force
    return kwargs


class CascadeOrchestrator:
    """Headless cascade engine. One instance per process; the terminal
    hook in `run_in_background_v2` reaches it via
    `get_cascade_orchestrator()`."""

    def __init__(self, *, session_factory: Optional[Callable] = None):
        self._lock = threading.RLock()
        self._cascades: dict[str, CascadeState] = {}
        self._session_factory = session_factory

    # ───── Public API ─────

    def start_cascade(
        self,
        db,
        *,
        book_id: str,
        chapter_id: str,
        guideline_id: str,
        from_stage_id: Optional[str] = None,
        force: bool = True,
        quality_level: str = "balanced",
    ) -> CascadeState:
        """Begin a cascade for a topic.

        - `from_stage_id` set → that stage + every transitive descendant
          becomes the pending set; descendants are marked stale; the
          stage is launched with `force=force`.
        - `from_stage_id` is None (run-all) → every stage that isn't
          `done` becomes the pending set; `force` applies to whichever
          stage launches first.

        Raises `CascadeAlreadyActiveError` if a cascade is already
        active for this topic, `CascadeNotReadyError` if `from_stage_id`
        has unmet upstream deps, and `ChapterJobLockError` if the first
        launch hits the per-topic lock (caller maps to 409).
        """
        with self._lock:
            if guideline_id in self._cascades:
                existing = self._cascades[guideline_id]
                raise CascadeAlreadyActiveError(
                    f"Cascade {existing.cascade_id} already active for "
                    f"guideline {guideline_id} (running={existing.running})"
                )

            state_map = self._build_state_map(db, guideline_id)
            stale_set = self._build_stale_set(db, guideline_id)
            pending = self._compute_pending(
                state_map, stale_set, from_stage_id,
            )

            # Reject upfront if `from_stage_id` has any dep that isn't
            # `done AND not stale` — otherwise the cascade registers but
            # `_launch_next` finds nothing ready, leaving an orphan
            # entry that blocks future kickoffs.
            if from_stage_id is not None:
                stage = DAG.get(from_stage_id)
                missing_deps = [
                    dep for dep in stage.depends_on
                    if state_map.get(dep) != "done" or dep in stale_set
                ]
                if missing_deps:
                    raise CascadeNotReadyError(
                        f"Cannot rerun {from_stage_id!r} — upstream "
                        f"dep(s) not done or stale: {missing_deps}"
                    )

            cascade = CascadeState(
                cascade_id=str(uuid.uuid4()),
                book_id=book_id,
                chapter_id=chapter_id,
                guideline_id=guideline_id,
                quality_level=quality_level,
                force_first=force,
                pending=pending,
            )

            if not pending:
                # Nothing to do. Don't register the cascade; let the
                # caller decide what to communicate.
                return cascade

            self._cascades[guideline_id] = cascade

            # Launch BEFORE marking descendants stale — otherwise a
            # `ChapterJobLockError` on the first launch would commit
            # `is_stale=True` writes against a cascade that never ran.
            try:
                self._launch_next(cascade, db=db)
            except Exception:
                self._cascades.pop(guideline_id, None)
                raise

            # Mark stale on every pending stage that already has a
            # `done` row AND isn't already stale. Track which rows we
            # flipped on `cascade.stale_marked` so halt-on-failure only
            # clears those — pre-existing stale signals from a prior
            # cancelled cascade or operator action stay intact.
            #
            # The `from_stage_id` itself is in `running` now; its
            # terminal write will clear its own stale flag if it had one.
            repo = TopicStageRunRepository(db)
            for sid in pending:
                if sid == from_stage_id:
                    continue
                row = repo.get(guideline_id, sid)
                if row and row.state == "done" and not row.is_stale:
                    repo.mark_stale(guideline_id, sid, is_stale=True)
                    cascade.stale_marked.add(sid)

            return cascade

    def on_stage_complete(
        self,
        *,
        guideline_id: str,
        stage_id: str,
        terminal_state: str,
    ) -> None:
        """Terminal-write hook callback. No-op when no cascade is active.

        Halt-on-failure: a `failed` terminal sets `halted_at = stage_id`
        and clears the pending queue. Descendants that we flagged
        stale on cascade kickoff get their `is_stale` cleared on halt
        — the failed rerun didn't actually change upstream artifacts,
        so downstream isn't truly stale.
        """
        if terminal_state not in ("done", "failed"):
            return

        with self._lock:
            cascade = self._cascades.get(guideline_id)
            if cascade is None:
                return
            if cascade.running != stage_id:
                # Some other code path (manual single-stage rerun, race
                # with a long-running orphan) finished a stage we
                # weren't tracking. Ignore.
                return

            cascade.stage_results[stage_id] = terminal_state
            cascade.running = None
            cascade.pending.discard(stage_id)

            if terminal_state == "failed":
                cascade.halted_at = stage_id
                # Clear stale on descendants we flagged at kickoff —
                # the failed rerun left upstream unchanged, so
                # descendants are no more stale than before. Best-
                # effort; a DB error here doesn't break halt semantics.
                self._clear_stale_on_pending_descendants(cascade)
                cascade.pending.clear()
                logger.warning(
                    f"Cascade {cascade.cascade_id} halted at {stage_id} (failed)"
                )
                self._maybe_cleanup(cascade)
                return

            if cascade.cancelled:
                logger.info(
                    f"Cascade {cascade.cascade_id} cancelled — not scheduling "
                    f"further stages"
                )
                self._maybe_cleanup(cascade)
                return

            try:
                self._launch_next(cascade, db=None)
            except ChapterJobLockError as e:
                logger.warning(
                    f"Cascade {cascade.cascade_id} hit lock collision on next "
                    f"stage launch: {e}"
                )
                cascade.halted_at = "lock_collision"
                self._maybe_cleanup(cascade)
            except Exception as e:
                logger.error(
                    f"Cascade {cascade.cascade_id} _launch_next crashed: {e}",
                    exc_info=True,
                )
                cascade.halted_at = "internal_error"
                self._maybe_cleanup(cascade)

    def cancel(self, guideline_id: str) -> bool:
        """Soft-cancel. Running stage finishes; no further launches.

        Returns True if there was a cascade to cancel.
        """
        with self._lock:
            cascade = self._cascades.get(guideline_id)
            if cascade is None:
                return False
            cascade.cancelled = True
            logger.info(
                f"Cascade {cascade.cascade_id} cancelled for guideline "
                f"{guideline_id} (running={cascade.running})"
            )
            if cascade.running is None:
                # No stage in flight — drop now so a fresh cascade can
                # start without waiting for a hook that won't come.
                self._maybe_cleanup(cascade)
            return True

    def get_cascade(self, guideline_id: str) -> Optional[CascadeState]:
        with self._lock:
            return self._cascades.get(guideline_id)

    def list_active(self) -> list[CascadeState]:
        with self._lock:
            return list(self._cascades.values())

    # ───── Internals ─────

    def _compute_pending(
        self,
        state_map: dict[str, str],
        stale_set: set[str],
        from_stage_id: Optional[str],
    ) -> set[str]:
        """Stages this cascade plans to run.

        Run-all (`from_stage_id is None`) follows plan §2 decision 16:
        "stale and failed are not-done." A stage is pending if its row
        state isn't `done` OR the row is flagged `is_stale=True`. Stages
        with no row at all fall through to "not done" and are pending.
        """
        if from_stage_id is not None:
            if not DAG.has(from_stage_id):
                raise ValueError(f"Unknown stage: {from_stage_id!r}")
            return {from_stage_id} | DAG.descendants(from_stage_id)
        pending: set[str] = set()
        for s in DAG.stages:
            if state_map.get(s.id) != "done":
                pending.add(s.id)
            elif s.id in stale_set:
                pending.add(s.id)
        return pending

    def _build_state_map(self, db, guideline_id: str) -> dict[str, str]:
        repo = TopicStageRunRepository(db)
        return {r.stage_id: r.state for r in repo.list_for_topic(guideline_id)}

    def _build_stale_set(self, db, guideline_id: str) -> set[str]:
        repo = TopicStageRunRepository(db)
        return {
            r.stage_id for r in repo.list_for_topic(guideline_id)
            if r.is_stale
        }

    def _launch_next(self, cascade: CascadeState, *, db) -> None:
        """Pick one ready stage from `pending` and launch it.

        `db` is None when called from `on_stage_complete` — the caller's
        session is closing. We open our own from `_session_factory` then.
        """
        if cascade.cancelled or cascade.halted_at is not None:
            self._maybe_cleanup(cascade)
            return

        owns_session = False
        if db is None:
            db = self._resolve_session_factory()()
            owns_session = True

        try:
            state_map = self._build_state_map(db, cascade.guideline_id)
            ready = self._ready_in_pending(cascade, state_map)
            if not ready:
                # Defense-in-depth: the upfront check in `start_cascade`
                # rejects from-stages with unmet deps, so we should never
                # reach here with non-empty pending and no in-flight
                # stage. If we do (e.g., a future regression in pending
                # computation), halt loudly instead of orphaning the
                # cascade with `running=None` and pending stuck in the
                # dict, which would block future kickoffs.
                if cascade.pending and cascade.running is None:
                    cascade.halted_at = "no_ready_stages"
                    logger.warning(
                        f"Cascade {cascade.cascade_id} has pending "
                        f"{cascade.pending} but no ready stages; halting"
                    )
                self._maybe_cleanup(cascade)
                return

            topo_order = [s.id for s in DAG.topo_sort()]
            ready.sort(key=lambda sid: topo_order.index(sid))
            next_stage_id = ready[0]

            # Cascade contract on `force`:
            # - First stage: honour the caller's `force` (e.g., "rerun
            #   forcefully from explanations").
            # - Descendants whose previous run was `done` or `failed`:
            #   force=True. Several downstream services (visual
            #   enrichment, audio synthesis) short-circuit when artifacts
            #   already exist; without force, they declare success
            #   without recomputing on the new upstream content, then
            #   `upsert_terminal "done"` clears `is_stale` and we ship
            #   stale artifacts as fresh.
            # - Descendants with no prior row: force=False — first-time
            #   stages don't need it.
            is_first = not cascade.stage_results
            if is_first:
                stage_force = cascade.force_first
            else:
                prior_state = state_map.get(next_stage_id)
                stage_force = prior_state in ("done", "failed")
            kwargs = build_launcher_kwargs(
                next_stage_id,
                book_id=cascade.book_id,
                chapter_id=cascade.chapter_id,
                guideline_id=cascade.guideline_id,
                quality_level=cascade.quality_level,
                force=stage_force,
            )
            # Resolve the launcher via the module-level dict on every call
            # (don't capture at import) so monkeypatched test launchers
            # take effect — the dict is the seam tests use.
            launcher = LAUNCHER_BY_STAGE[next_stage_id]
            launcher(db, **kwargs)
            cascade.running = next_stage_id
            logger.info(
                f"Cascade {cascade.cascade_id} launched stage {next_stage_id} "
                f"(force={kwargs.get('force', False)})"
            )
        finally:
            if owns_session:
                db.close()

    def _ready_in_pending(
        self, cascade: CascadeState, state_map: dict[str, str]
    ) -> list[str]:
        """Stages in `pending` whose deps are `done` AND not still
        themselves pending in this cascade.

        We check `dep in cascade.pending` because a `done` row from a
        previous successful run is no longer accurate once cascade
        marked the stage stale + queued it for re-run; treating it as
        satisfied would launch a downstream stage on stale inputs.
        """
        ready: list[str] = []
        for sid in cascade.pending:
            stage = DAG.get(sid)
            ok = True
            for dep in stage.depends_on:
                if dep in cascade.pending:
                    ok = False
                    break
                if state_map.get(dep) != "done":
                    ok = False
                    break
            if ok:
                ready.append(sid)
        return ready

    def _clear_stale_on_pending_descendants(self, cascade: CascadeState) -> None:
        """Clear `is_stale` on stages this cascade flagged at kickoff
        and that are still pending at halt time.

        Scope is `cascade.stale_marked & cascade.pending`. We don't
        touch rows that were stale before this cascade started — those
        signals come from a prior cancelled cascade or operator action
        and a failed rerun shouldn't erase them. We also don't clear
        rows for stages this cascade already advanced past (not in
        pending) — their fresh terminal write owns the stale flag.

        Best-effort — opens its own session; swallows DB errors so a
        cleanup glitch can't mask the underlying halt.
        """
        to_clear = cascade.stale_marked & cascade.pending
        if not to_clear:
            return
        try:
            db = self._resolve_session_factory()()
            try:
                repo = TopicStageRunRepository(db)
                for sid in to_clear:
                    repo.mark_stale(cascade.guideline_id, sid, is_stale=False)
            finally:
                db.close()
        except Exception as e:
            logger.warning(
                f"Cascade {cascade.cascade_id} stale cleanup failed on halt: {e}",
                exc_info=True,
            )

    def _maybe_cleanup(self, cascade: CascadeState) -> None:
        """Drop the cascade entry once nothing is in flight and there's
        nothing left to do."""
        if cascade.running is not None:
            return
        if cascade.pending and not cascade.halted_at and not cascade.cancelled:
            return
        self._cascades.pop(cascade.guideline_id, None)

    def _resolve_session_factory(self) -> Callable:
        if self._session_factory is not None:
            return self._session_factory
        from database import get_db_manager

        return get_db_manager().session_factory


# ───── Module-level access ─────

_default_orchestrator = CascadeOrchestrator()


def get_cascade_orchestrator() -> CascadeOrchestrator:
    return _default_orchestrator


def reset_cascade_orchestrator() -> None:
    """Test helper — drops the singleton's in-memory state."""
    global _default_orchestrator
    _default_orchestrator = CascadeOrchestrator()
