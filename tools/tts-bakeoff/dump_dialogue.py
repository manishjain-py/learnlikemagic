"""Dump the one baatcheet dialogue + plan to a JSON file we can read offline."""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg2
import psycopg2.extras

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / "llm-backend" / ".env"
OUT = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "dialogue.json"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> None:
    env = load_env(ENV_PATH)
    conn = psycopg2.connect(env["DATABASE_URL"])
    conn.set_session(readonly=True)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT
          td.id, td.guideline_id, td.cards_json, td.plan_json, td.generator_model,
          tg.topic_title, tg.chapter_title, tg.subject, tg.grade
        FROM topic_dialogues td
        LEFT JOIN teaching_guidelines tg ON tg.id = td.guideline_id
        ORDER BY td.created_at DESC
        LIMIT 1;
    """)
    row = dict(cur.fetchone())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(row, indent=2, default=str))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"topic: {row['topic_title']}")
    print(f"cards: {len(row['cards_json'])}")
    print(f"plan keys: {list(row['plan_json'].keys()) if row['plan_json'] else 'none'}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
