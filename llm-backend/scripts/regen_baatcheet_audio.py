"""Regenerate Baatcheet dialogue audio (Stage 10) for a list of guideline IDs.

Calls `AudioGenerationService.generate_for_topic_dialogue(force=True)` on each
dialogue so every line's MP3 is re-synthesized. S3 keys are deterministic per
(guideline, card_id, line_idx) so writes overwrite cleanly at the same URL —
the runtime player picks up the fresh audio on next play.

Usage:
    cd llm-backend && venv/bin/python scripts/regen_baatcheet_audio.py \\
        <guideline_id> [<guideline_id> ...]
"""
import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import attributes

from database import get_db_manager
from shared.models.entities import TopicDialogue, TeachingGuideline
from book_ingestion_v2.services.audio_generation_service import AudioGenerationService


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guideline_ids", nargs="+")
    args = ap.parse_args()

    db = get_db_manager()
    with db.session_scope() as session:
        svc = AudioGenerationService(db=session)
        print(f"Provider: {svc.provider}\n")

        for gid in args.guideline_ids:
            tg = session.query(TeachingGuideline).filter(
                TeachingGuideline.id == gid,
            ).first()
            if not tg:
                print(f"[{gid}] guideline not found — skipping")
                continue

            dialogue = session.query(TopicDialogue).filter(
                TopicDialogue.guideline_id == gid,
            ).first()
            if not dialogue:
                print(f"[{gid}] no dialogue row — skipping")
                continue

            label = tg.topic_title or tg.topic or "?"
            total, with_audio = AudioGenerationService.count_dialogue_audio_items(
                dialogue.cards_json,
            )
            print(f"[{gid}] {label!r}")
            print(f"  before: {with_audio}/{total} clips have audio_url")

            updated = svc.generate_for_topic_dialogue(dialogue, force=True)
            if updated is not None:
                dialogue.cards_json = updated
                attributes.flag_modified(dialogue, "cards_json")
                session.commit()

            total_after, with_audio_after = AudioGenerationService.count_dialogue_audio_items(
                dialogue.cards_json,
            )
            print(f"  after:  {with_audio_after}/{total_after} clips have audio_url\n")


if __name__ == "__main__":
    main()
