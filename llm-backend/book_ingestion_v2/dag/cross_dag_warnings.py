"""Phase 6 — cross-DAG warning helpers.

The `explanations` stage's output is a function of three fields on the
`teaching_guidelines` row: `guideline`, `prior_topics_context`, and
`topic_title`. When upstream stages (`topic_sync`, `refresher_generation`)
mutate any of those after a cached `explanations` run, the cached
artefacts may no longer reflect the chapter's current content.

We capture a SHA-256 hex of those three fields at the end of every
successful `explanations` run and store it on the guideline row
(`explanations_input_hash`). The DAG view's banner endpoint compares the
stored hash to a live one and surfaces a warning when they differ.

The banner clears automatically the next time `explanations` runs
successfully — that run writes the new hash, so the live hash matches
again.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from sqlalchemy.orm import Session

from shared.models.entities import TeachingGuideline

logger = logging.getLogger(__name__)


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
    """Compute the live hash from a TeachingGuideline ORM instance."""
    return compute_input_hash(
        guideline_text=guideline.guideline,
        prior_topics_context=guideline.prior_topics_context,
        topic_title=guideline.topic_title,
    )


def capture_explanations_input_hash(db: Session, guideline_id: str) -> Optional[str]:
    """Read the live hash and write it to `teaching_guidelines.explanations_input_hash`.

    Returns the captured hash (or None if the guideline row is missing).
    Caller is responsible for committing — this function only stages the
    UPDATE so it can compose with the existing terminal-write transaction.
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
    hash_hex = compute_input_hash_for_guideline(guideline)
    guideline.explanations_input_hash = hash_hex
    return hash_hex
