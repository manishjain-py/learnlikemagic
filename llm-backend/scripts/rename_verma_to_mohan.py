"""
Backfill rename: "Mr. Verma" → "Mohan Sir" in existing `topic_dialogues` rows.

Updates both `cards_json` (per-card text + speaker_name) and `plan_json`
(if non-null) via JSONB→text→JSONB replacement. Idempotent: rows with no
match are skipped. Reports counts so the operator can sanity-check.

Note: audio files baked into S3 still say "Mr. Verma" — only the
display/transcript text changes. Re-run Stage 10 (audio synthesis) to
refresh audio.

Usage:
    cd llm-backend && source venv/bin/activate
    python scripts/rename_verma_to_mohan.py            # dry run (prints counts)
    python scripts/rename_verma_to_mohan.py --commit   # actually write
"""

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from database import get_db_manager


OLD = "Mr. Verma"
NEW = "Mohan Sir"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="apply changes (default: dry run)")
    args = ap.parse_args()

    db = get_db_manager()
    with db.session_scope() as session:
        cards_hits = session.execute(
            text("SELECT COUNT(*) FROM topic_dialogues WHERE cards_json::text LIKE :p"),
            {"p": f"%{OLD}%"},
        ).scalar()
        plan_hits = session.execute(
            text(
                "SELECT COUNT(*) FROM topic_dialogues "
                "WHERE plan_json IS NOT NULL AND plan_json::text LIKE :p"
            ),
            {"p": f"%{OLD}%"},
        ).scalar()

        print(f"Rows with '{OLD}' in cards_json: {cards_hits}")
        print(f"Rows with '{OLD}' in plan_json:  {plan_hits}")

        if not args.commit:
            print("\nDry run — pass --commit to apply.")
            return

        if cards_hits:
            session.execute(
                text(
                    "UPDATE topic_dialogues "
                    "SET cards_json = REPLACE(cards_json::text, :old, :new)::jsonb, "
                    "    updated_at = NOW() "
                    "WHERE cards_json::text LIKE :p"
                ),
                {"old": OLD, "new": NEW, "p": f"%{OLD}%"},
            )
        if plan_hits:
            session.execute(
                text(
                    "UPDATE topic_dialogues "
                    "SET plan_json = REPLACE(plan_json::text, :old, :new)::jsonb, "
                    "    updated_at = NOW() "
                    "WHERE plan_json IS NOT NULL AND plan_json::text LIKE :p"
                ),
                {"old": OLD, "new": NEW, "p": f"%{OLD}%"},
            )

        post_cards = session.execute(
            text("SELECT COUNT(*) FROM topic_dialogues WHERE cards_json::text LIKE :p"),
            {"p": f"%{OLD}%"},
        ).scalar()
        post_plan = session.execute(
            text(
                "SELECT COUNT(*) FROM topic_dialogues "
                "WHERE plan_json IS NOT NULL AND plan_json::text LIKE :p"
            ),
            {"p": f"%{OLD}%"},
        ).scalar()

        print(f"\nAfter update: {post_cards} cards_json hits, {post_plan} plan_json hits remaining (expect 0).")

        if post_cards or post_plan:
            print("WARNING: residual matches — rolling back.", file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
