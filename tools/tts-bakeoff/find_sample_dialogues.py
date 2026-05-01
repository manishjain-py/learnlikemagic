"""Pick 3 baatcheet dialogues from prod DB for the TTS bake-off.

Selection criteria:
1. Math-heavy with crisp pedagogical structure (e.g. fractions, place value)
2. Reframe / emotional moment somewhere ("spinning", "tired", "tricky")
3. Clean trap-set → fall → articulate cycle (look for `move` in plan_json)

Read-only. Hits prod DB but only SELECT.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / "llm-backend" / ".env"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


ENV = load_env(ENV_PATH)
DB_URL = ENV.get("DATABASE_URL") or os.environ["DATABASE_URL"]


def main() -> None:
    conn = psycopg2.connect(DB_URL)
    conn.set_session(readonly=True)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Sample: get the most recent N dialogues with their guideline title + plan presence
    cur.execute("""
        SELECT
          td.id,
          td.guideline_id,
          tg.topic_title,
          tg.chapter_title,
          tg.subject,
          tg.grade,
          (td.plan_json IS NOT NULL) AS has_plan,
          jsonb_array_length(td.cards_json) AS card_count,
          td.created_at,
          td.generator_model
        FROM topic_dialogues td
        LEFT JOIN teaching_guidelines tg ON tg.id = td.guideline_id
        ORDER BY td.created_at DESC
        LIMIT 30;
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} recent dialogues:\n")
    for r in rows:
        title = (r["topic_title"] or "?")[:42]
        chap = (r["chapter_title"] or "?")[:25]
        subj = (r["subject"] or "?")[:8]
        grade = r["grade"] or "?"
        print(f"  {r['guideline_id'][:8]} | g={grade:>4} | {subj:8s} | cards={r['card_count']:2} | plan={'Y' if r['has_plan'] else 'N'} | {chap:25s} | {title}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
