"""Phase 6 — cross-DAG warning helpers.

`explanation_generator_service` consumes three logical inputs from the
topic's `teaching_guidelines` row:
  - guideline text:  `guideline.guideline OR guideline.description OR ""`
  - topic title:     `guideline.topic_title OR guideline.topic`
  - prior context:   `guideline.prior_topics_context`

We hash those at the end of every successful `explanations` run and
persist the digest in `topic_content_hashes`. When upstream stages
(`topic_sync`, `refresher_generation`, in-place admin edits) leave the
current values diverging from the captured hash, the cross-DAG warning
endpoint surfaces a `chapter_resynced` banner.

**Why a side table, not a column on `teaching_guidelines`.** `topic_sync`
deletes-and-recreates guideline rows on every chapter resync — anything
keyed on `guideline_id` dies with them. The hash row is keyed on the
stable curriculum tuple `(book_id, chapter_key, topic_key)` so it
survives a resync intact, which is the whole signal the banner needs.

The banner clears automatically the next time `explanations` runs
successfully — that run writes the new hash, so the live hash matches
again.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from book_ingestion_v2.models.database import TopicContentHash
from shared.models.entities import TeachingGuideline

logger = logging.getLogger(__name__)


def _effective_guideline_text(guideline: TeachingGuideline) -> str:
    """Mirror `explanation_generator_service`'s fallback chain so the hash
    reflects the actual LLM input, not just the primary field."""
    return guideline.guideline or guideline.description or ""


def _effective_topic_title(guideline: TeachingGuideline) -> str:
    return guideline.topic_title or guideline.topic or ""


def compute_input_hash(
    guideline_text: Optional[str],
    prior_topics_context: Optional[str],
    topic_title: Optional[str],
) -> str:
    """Return SHA-256 hex of the three explanations input fields.

    Treats NULL the same as empty string so a guideline that never had
    a `prior_topics_context` doesn't flip to "changed" the moment we set
    it to ''. Uses a `\\x1f` (ASCII unit separator) between fields so a
    field containing the delimiter can't collide with the next one.
    """
    parts = (
        guideline_text or "",
        prior_topics_context or "",
        topic_title or "",
    )
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_input_hash_for_guideline(guideline: TeachingGuideline) -> str:
    """Compute the live hash from a TeachingGuideline ORM instance.

    Uses the same fallback chains the explanation generator uses so the
    hash actually fingerprints the LLM input.
    """
    return compute_input_hash(
        guideline_text=_effective_guideline_text(guideline),
        prior_topics_context=guideline.prior_topics_context,
        topic_title=_effective_topic_title(guideline),
    )


def stable_key_for_guideline(
    guideline: TeachingGuideline,
) -> Optional[Tuple[str, str, str]]:
    """Return `(book_id, chapter_key, topic_key)` or None if any
    component is missing.

    Older guideline rows can have NULL `chapter_key`/`topic_key`; for
    those we can't capture (or look up) a hash and the banner is silent
    by design — the operator dashboard for those topics still works,
    just without the cross-DAG signal.
    """
    if not guideline.book_id or not guideline.chapter_key or not guideline.topic_key:
        return None
    return (guideline.book_id, guideline.chapter_key, guideline.topic_key)


def capture_explanations_input_hash(
    db: Session,
    guideline_id: str,
    *,
    completed_at: Optional[datetime] = None,
) -> Optional[str]:
    """Compute the live hash and upsert it into `topic_content_hashes`.

    Keyed on the stable `(book_id, chapter_key, topic_key)` tuple so the
    captured hash survives `topic_sync`'s delete-recreate pattern.

    Returns the captured hash, or None if the guideline is missing or
    lacks the curriculum tuple needed to key the row. Caller is
    responsible for committing — this function only stages the
    UPDATE/INSERT so it can compose with the existing terminal-write
    transaction.
    """
    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == guideline_id
    ).first()
    if not guideline:
        logger.warning(
            "capture_explanations_input_hash: guideline %s not found",
            guideline_id,
        )
        return None

    key = stable_key_for_guideline(guideline)
    if key is None:
        logger.warning(
            "capture_explanations_input_hash: guideline %s missing "
            "book_id/chapter_key/topic_key — skipping capture",
            guideline_id,
        )
        return None

    hash_hex = compute_input_hash_for_guideline(guideline)
    completed = completed_at or datetime.utcnow()

    book_id, chapter_key, topic_key = key
    row = db.query(TopicContentHash).filter(
        TopicContentHash.book_id == book_id,
        TopicContentHash.chapter_key == chapter_key,
        TopicContentHash.topic_key == topic_key,
    ).first()
    if row is None:
        row = TopicContentHash(
            book_id=book_id,
            chapter_key=chapter_key,
            topic_key=topic_key,
            explanations_input_hash=hash_hex,
            last_explanations_at=completed,
        )
        db.add(row)
    else:
        row.explanations_input_hash = hash_hex
        row.last_explanations_at = completed

    return hash_hex


def get_stored_hash(
    db: Session,
    book_id: str,
    chapter_key: str,
    topic_key: str,
) -> Optional[TopicContentHash]:
    """Fetch the stored hash row for a stable key. Returns None when no
    successful `explanations` run has captured one yet."""
    return db.query(TopicContentHash).filter(
        TopicContentHash.book_id == book_id,
        TopicContentHash.chapter_key == chapter_key,
        TopicContentHash.topic_key == topic_key,
    ).first()
