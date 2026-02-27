"""
Background task runner using Python threads.

Uses independent DB sessions for background work to avoid
session lifecycle issues with the request-scoped session.

Usage:
    from book_ingestion.services.background_task_runner import run_in_background

    # target_fn signature: (db_session, job_id, *args, **kwargs)
    thread = run_in_background(my_background_fn, job_id, arg1, arg2)
"""
import time
import logging
import threading
from database import get_db_manager

logger = logging.getLogger(__name__)


def run_in_background(target_fn, job_id: str, *args, **kwargs):
    """
    Run a function in a background thread with its own DB session.

    The runner handles the pending → running transition via start_job()
    before calling the target function. If the target raises, the job
    is marked failed via release_lock().

    Args:
        target_fn: Function to run. Signature: (db_session, job_id, *args, **kwargs)
        job_id: The BookJob ID to manage lifecycle for
        *args, **kwargs: Additional arguments passed to target_fn

    Returns:
        threading.Thread instance
    """
    def wrapper():
        db_manager = get_db_manager()
        session = db_manager.session_factory()
        try:
            from book_ingestion.services.job_lock_service import JobLockService
            job_lock = JobLockService(session)

            # Transition pending → running (sets initial heartbeat).
            # If this fails (InvalidStateTransition), the except block
            # calls release_lock(failed) which works because release_lock
            # accepts jobs in 'pending' state.
            job_lock.start_job(job_id)

            # Run the actual task
            target_fn(session, job_id, *args, **kwargs)

        except Exception as e:
            logger.error(
                f"Background task {target_fn.__name__} failed: {e}",
                exc_info=True,
                extra={"job_id": job_id},
            )
            # Ensure job is marked failed — retry once on DB error
            for attempt in range(2):
                try:
                    from book_ingestion.services.job_lock_service import JobLockService
                    job_lock = JobLockService(session)
                    job_lock.release_lock(job_id, status='failed', error=str(e))
                    break
                except Exception:
                    if attempt == 0:
                        logger.warning("First release_lock attempt failed, retrying...")
                        time.sleep(1)
                    else:
                        logger.error(
                            f"Could not mark job {job_id} as failed — "
                            "will be caught by stale detection"
                        )
        finally:
            session.close()

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    logger.info(f"Launched background task: {target_fn.__name__} (job_id={job_id})")
    return thread
