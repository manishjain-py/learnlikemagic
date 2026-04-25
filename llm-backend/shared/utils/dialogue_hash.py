"""Semantic content hash for staleness detection on Baatcheet dialogues.

Hashes only the fields that affect *what* a variant A explanation says — not
fields that mutate when only enrichment refreshes (audio_url, pixi_code,
visual_explanation). Stage 5b stores the hash on the dialogue row at
generation time; the pipeline status service reports the dialogue as stale
when the current variant A hash differs from the stored hash.
"""
import hashlib
import json
from typing import Optional


_SEMANTIC_LINE_FIELDS = ("display", "audio")
_SEMANTIC_CARD_FIELDS = ("card_type", "title", "content", "audio_text")
_SEMANTIC_SUMMARY_FIELDS = ("key_analogies", "key_examples", "teaching_notes")


def compute_explanation_content_hash(
    cards_json: Optional[list[dict]],
    summary_json: Optional[dict],
) -> str:
    """Stable SHA-256 hash of variant A's semantic content.

    Excludes audio_url, pixi_code, visual_explanation — those mutate during
    enrichment without changing what the variant says. Hash is stable across
    process restarts (no random salt) and across Python versions (sort_keys).
    """
    canonical_cards: list[dict] = []
    for card in cards_json or []:
        if not isinstance(card, dict):
            continue
        c = {k: card.get(k) for k in _SEMANTIC_CARD_FIELDS}
        c["lines"] = [
            {k: line.get(k) for k in _SEMANTIC_LINE_FIELDS}
            for line in (card.get("lines") or [])
            if isinstance(line, dict)
        ]
        canonical_cards.append(c)

    canonical_summary = (
        {k: (summary_json or {}).get(k) for k in _SEMANTIC_SUMMARY_FIELDS}
        if summary_json
        else None
    )
    payload = json.dumps(
        {"cards": canonical_cards, "summary": canonical_summary},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
