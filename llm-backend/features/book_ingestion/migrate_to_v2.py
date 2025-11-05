"""
Migration script for Guidelines V2

This script:
1. Deletes all V1 teaching guidelines from the database
2. Optionally drops V1-specific columns (requires schema migration)
3. Clears S3 shard storage for a fresh V2 start

BREAKING CHANGE: All V1 data will be lost.

Usage:
    python -m features.book_ingestion.migrate_to_v2 --confirm

Options:
    --confirm           Required flag to confirm data deletion
    --db-only          Only clear database, keep S3 shards
    --s3-only          Only clear S3 shards, keep database
    --book-id <id>     Migrate only specific book (for testing)
"""

import argparse
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import boto3
from typing import Optional
import os
from datetime import datetime

from models.database import Base, TeachingGuideline
from core.config import settings


class V2Migrator:
    """Handles migration from V1 to V2 architecture"""

    def __init__(self, db_url: str, s3_bucket: str):
        self.db_url = db_url
        self.s3_bucket = s3_bucket
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        self.s3_client = boto3.client('s3')

    def clear_database_guidelines(self, book_id: Optional[str] = None):
        """
        Delete all V1 teaching guidelines from database.

        Args:
            book_id: If provided, only delete guidelines for this book
        """
        session = self.Session()
        try:
            if book_id:
                count = session.query(TeachingGuideline).filter(
                    TeachingGuideline.book_id == book_id
                ).delete()
                print(f"✓ Deleted {count} guidelines for book_id={book_id}")
            else:
                count = session.query(TeachingGuideline).delete()
                print(f"✓ Deleted {count} guidelines from database")

            session.commit()
        except Exception as e:
            session.rollback()
            print(f"✗ Database deletion failed: {e}")
            raise
        finally:
            session.close()

    def clear_s3_shards(self, book_id: Optional[str] = None):
        """
        Delete all V1 shards from S3.

        Args:
            book_id: If provided, only delete shards for this book
        """
        try:
            prefix = f"guidelines/v1/"
            if book_id:
                prefix = f"guidelines/v1/{book_id}/"

            # List all objects with prefix
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix)

            deleted_count = 0
            for page in pages:
                if 'Contents' not in page:
                    continue

                # Delete in batches
                objects = [{'Key': obj['Key']} for obj in page['Contents']]
                if objects:
                    self.s3_client.delete_objects(
                        Bucket=self.s3_bucket,
                        Delete={'Objects': objects}
                    )
                    deleted_count += len(objects)

            print(f"✓ Deleted {deleted_count} S3 objects from {prefix}")
        except Exception as e:
            print(f"✗ S3 deletion failed: {e}")
            raise

    def verify_clean_slate(self, book_id: Optional[str] = None):
        """
        Verify that V1 data has been cleared.

        Args:
            book_id: If provided, only verify for this book
        """
        session = self.Session()
        try:
            # Check database
            if book_id:
                db_count = session.query(TeachingGuideline).filter(
                    TeachingGuideline.book_id == book_id
                ).count()
            else:
                db_count = session.query(TeachingGuideline).count()

            if db_count > 0:
                print(f"⚠ Warning: {db_count} guidelines still in database")
                return False

            # Check S3
            prefix = f"guidelines/v1/"
            if book_id:
                prefix = f"guidelines/v1/{book_id}/"

            response = self.s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=prefix,
                MaxKeys=1
            )

            if 'Contents' in response:
                print(f"⚠ Warning: S3 objects still exist at {prefix}")
                return False

            print("✓ Verification passed: Clean slate confirmed")
            return True

        finally:
            session.close()

    def create_migration_log(self, book_id: Optional[str], details: dict):
        """
        Log migration event to S3 for audit trail.

        Args:
            book_id: Book ID if specific book, None for full migration
            details: Migration details dict
        """
        timestamp = datetime.utcnow().isoformat()
        log_key = f"migrations/v2/{timestamp}_{book_id or 'full'}.json"

        import json
        log_data = {
            "migration_version": "v1_to_v2",
            "timestamp": timestamp,
            "book_id": book_id,
            "details": details
        }

        try:
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=log_key,
                Body=json.dumps(log_data, indent=2),
                ContentType='application/json'
            )
            print(f"✓ Migration log saved: {log_key}")
        except Exception as e:
            print(f"⚠ Warning: Failed to save migration log: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate from Guidelines V1 to V2 (DESTRUCTIVE)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required flag to confirm data deletion"
    )
    parser.add_argument(
        "--db-only",
        action="store_true",
        help="Only clear database, keep S3 shards"
    )
    parser.add_argument(
        "--s3-only",
        action="store_true",
        help="Only clear S3 shards, keep database"
    )
    parser.add_argument(
        "--book-id",
        type=str,
        help="Migrate only specific book (for testing)"
    )

    args = parser.parse_args()

    # Safety check
    if not args.confirm:
        print("ERROR: Must specify --confirm flag to proceed with migration")
        print("This operation will DELETE all V1 guideline data!")
        sys.exit(1)

    # Get configuration
    db_url = os.getenv("DATABASE_URL")
    s3_bucket = os.getenv("S3_BUCKET", "learnlikemagic-data")

    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    print("=" * 60)
    print("GUIDELINES V2 MIGRATION")
    print("=" * 60)
    print()
    print("⚠️  WARNING: This will DELETE all V1 guideline data!")
    print()

    if args.book_id:
        print(f"Target: Book {args.book_id} only")
    else:
        print("Target: ALL books")

    if args.db_only:
        print("Mode: Database only")
    elif args.s3_only:
        print("Mode: S3 only")
    else:
        print("Mode: Full migration (database + S3)")

    print()
    confirm = input("Type 'DELETE' to proceed: ")
    if confirm != "DELETE":
        print("Migration cancelled")
        sys.exit(0)

    print()
    print("Starting migration...")
    print()

    migrator = V2Migrator(db_url=db_url, s3_bucket=s3_bucket)

    try:
        # Clear database
        if not args.s3_only:
            print("Step 1: Clearing database...")
            migrator.clear_database_guidelines(book_id=args.book_id)

        # Clear S3
        if not args.db_only:
            print("Step 2: Clearing S3 shards...")
            migrator.clear_s3_shards(book_id=args.book_id)

        # Verify
        print("Step 3: Verifying clean slate...")
        success = migrator.verify_clean_slate(book_id=args.book_id)

        # Log migration
        if success:
            migrator.create_migration_log(
                book_id=args.book_id,
                details={
                    "db_cleared": not args.s3_only,
                    "s3_cleared": not args.db_only,
                }
            )

        print()
        print("=" * 60)
        if success:
            print("✓ MIGRATION COMPLETE")
            print("Ready for V2 guideline extraction")
        else:
            print("⚠ MIGRATION COMPLETED WITH WARNINGS")
            print("Please check the warnings above")
        print("=" * 60)

    except Exception as e:
        print()
        print("=" * 60)
        print(f"✗ MIGRATION FAILED: {e}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
