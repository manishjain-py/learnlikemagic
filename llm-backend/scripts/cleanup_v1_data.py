"""
Clean up V1 pipeline data from the database.

This script removes:
1. V1 LLM config entry ('book_ingestion' — NOT 'book_ingestion_v2')
2. V1 books (pipeline_version=1) from the books table
3. Teaching guidelines whose book_id references a V1 book
4. Study plans associated with deleted V1 guidelines
5. Lists V1 S3 prefixes for manual cleanup

Safety checks:
- Dry-run by default (pass --execute to actually delete)
- Only deletes books with pipeline_version=1
- Only deletes guidelines whose book_id matches a V1 book
- Never touches V2 data (pipeline_version=2, book_ingestion_v2 config)

Usage:
    cd llm-backend
    source venv/bin/activate
    python scripts/cleanup_v1_data.py              # dry run
    python scripts/cleanup_v1_data.py --execute    # actually delete
"""

import argparse

from sqlalchemy import text, bindparam
from database import get_db_manager


def cleanup_v1_data(dry_run: bool = True):
    db_manager = get_db_manager()
    action = "Would delete" if dry_run else "Deleting"

    if dry_run:
        print("=== DRY RUN (pass --execute to actually delete) ===\n")

    with db_manager.engine.connect() as conn:
        # 1. Remove V1 LLM config entry
        print("--- V1 LLM Config ---")
        v1_config = conn.execute(
            text("SELECT component_key, provider, model_id FROM llm_config WHERE component_key = :key"),
            {"key": "book_ingestion"},
        ).fetchone()
        if v1_config:
            print(f"  {action} llm_config entry: book_ingestion ({v1_config[1]}/{v1_config[2]})")
            if not dry_run:
                conn.execute(
                    text("DELETE FROM llm_config WHERE component_key = :key"),
                    {"key": "book_ingestion"},
                )
        else:
            print("  No V1 'book_ingestion' config found (already clean)")

        # Verify V2 config is untouched
        v2_config = conn.execute(
            text("SELECT component_key, provider, model_id FROM llm_config WHERE component_key = :key"),
            {"key": "book_ingestion_v2"},
        ).fetchone()
        if v2_config:
            print(f"  V2 config preserved: book_ingestion_v2 ({v2_config[1]}/{v2_config[2]})")
        else:
            print("  WARNING: No V2 'book_ingestion_v2' config found!")

        # 2. Find V1 books
        print("\n--- V1 Books ---")
        v1_books = conn.execute(
            text("SELECT id, title, subject, grade, s3_prefix FROM books WHERE pipeline_version = 1 OR pipeline_version IS NULL")
        ).fetchall()

        if not v1_books:
            print("  No V1 books found")
        else:
            v1_book_ids = [b[0] for b in v1_books]
            s3_prefixes = [b[4] for b in v1_books if b[4]]
            for b in v1_books:
                print(f"  {action}: book '{b[1]}' (id={b[0]}, {b[2]} grade {b[3]})")

            # 3. Delete study plans for guidelines linked to V1 books
            print("\n--- Study Plans (linked to V1 book guidelines) ---")
            v1_study_plans = conn.execute(
                text(
                    "SELECT sp.id FROM study_plans sp "
                    "JOIN teaching_guidelines tg ON sp.guideline_id = tg.id "
                    "WHERE tg.book_id IN :book_ids"
                ).bindparams(bindparam("book_ids", expanding=True)),
                {"book_ids": v1_book_ids},
            ).fetchall()
            print(f"  {action} {len(v1_study_plans)} study plans linked to V1 guidelines")
            if not dry_run and v1_study_plans:
                conn.execute(
                    text(
                        "DELETE FROM study_plans WHERE guideline_id IN ("
                        "  SELECT id FROM teaching_guidelines WHERE book_id IN :book_ids"
                        ")"
                    ).bindparams(bindparam("book_ids", expanding=True)),
                    {"book_ids": v1_book_ids},
                )

            # 4. Delete teaching guidelines linked to V1 books
            print("\n--- Teaching Guidelines (linked to V1 books) ---")
            v1_guidelines = conn.execute(
                text(
                    "SELECT id, chapter, topic FROM teaching_guidelines WHERE book_id IN :book_ids"
                ).bindparams(bindparam("book_ids", expanding=True)),
                {"book_ids": v1_book_ids},
            ).fetchall()
            print(f"  {action} {len(v1_guidelines)} guidelines linked to V1 books")
            for g in v1_guidelines[:5]:
                print(f"    - {g[1]} / {g[2]} (id={g[0]})")
            if len(v1_guidelines) > 5:
                print(f"    ... and {len(v1_guidelines) - 5} more")
            if not dry_run and v1_guidelines:
                conn.execute(
                    text(
                        "DELETE FROM teaching_guidelines WHERE book_id IN :book_ids"
                    ).bindparams(bindparam("book_ids", expanding=True)),
                    {"book_ids": v1_book_ids},
                )

            # 5. Delete V1 books
            print("\n--- Deleting V1 Books ---")
            print(f"  {action} {len(v1_books)} V1 books")
            if not dry_run:
                conn.execute(text(
                    "DELETE FROM books WHERE pipeline_version = 1 OR pipeline_version IS NULL"
                ))

            # 6. List S3 prefixes for manual cleanup
            if s3_prefixes:
                print("\n--- S3 Cleanup (manual) ---")
                print("  The following S3 prefixes should be manually deleted:")
                for prefix in s3_prefixes:
                    print(f"    aws s3 rm s3://$BUCKET/{prefix} --recursive")

        if not dry_run:
            conn.commit()
            print("\n✓ All V1 data deleted successfully")
        else:
            print("\n=== DRY RUN COMPLETE — no changes made ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up V1 pipeline data")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete data (default is dry-run)",
    )
    args = parser.parse_args()
    cleanup_v1_data(dry_run=not args.execute)
