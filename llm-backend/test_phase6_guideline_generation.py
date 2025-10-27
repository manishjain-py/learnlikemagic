"""
Test script for Phase 6 guideline generation pipeline.

This script runs the guideline extraction orchestrator on the test book
and captures detailed statistics and timing information.
"""
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from features.book_ingestion.services.guideline_extraction_orchestrator import GuidelineExtractionOrchestrator
from features.book_ingestion.utils.s3_client import S3Client
from database import get_db

# Load environment variables
load_dotenv()

def main():
    book_id = "ncert_mathematics_3_2024"
    start_page = 1
    end_page = 8

    print("=" * 80)
    print("PHASE 6 GUIDELINE GENERATION TEST")
    print("=" * 80)
    print(f"Book ID: {book_id}")
    print(f"Pages: {start_page}-{end_page}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    # Initialize dependencies
    s3_client = S3Client()
    openai_client = OpenAI()
    db = next(get_db())

    # Get book metadata
    from features.book_ingestion.models.database import Book
    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        print(f"❌ Book not found: {book_id}")
        return

    book_metadata = {
        "grade": book.grade,
        "subject": book.subject,
        "board": book.board,
        "country": book.country,
        "total_pages": 8
    }

    # Create orchestrator
    orchestrator = GuidelineExtractionOrchestrator(
        s3_client=s3_client,
        openai_client=openai_client,
        db_session=db
    )

    # Run extraction with timing
    print("🚀 Starting guideline extraction...")
    print()

    start_time = time.time()

    try:
        stats = orchestrator.extract_guidelines_for_book(
            book_id=book_id,
            book_metadata=book_metadata,
            start_page=start_page,
            end_page=end_page,
            auto_sync_to_db=True
        )

        end_time = time.time()
        elapsed = end_time - start_time

        print()
        print("=" * 80)
        print("✅ EXTRACTION COMPLETE!")
        print("=" * 80)
        print(f"Total time: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
        print(f"Time per page: {elapsed/8:.2f} seconds")
        print()
        print("📊 Statistics:")
        print(f"  Pages processed: {stats['pages_processed']}")
        print(f"  Subtopics created: {stats['subtopics_created']}")
        print(f"  Subtopics finalized: {stats['subtopics_finalized']}")
        print(f"  Errors: {len(stats['errors'])}")
        print()

        if stats['errors']:
            print("❌ Errors encountered:")
            for error in stats['errors']:
                print(f"  - {error}")
            print()

        # Check S3 structure
        print("📁 Checking S3 structure...")
        prefix = f"books/{book_id}/guidelines/"
        response = s3_client.s3_client.list_objects_v2(
            Bucket=s3_client.bucket_name,
            Prefix=prefix
        )

        if 'Contents' in response:
            files = [obj['Key'] for obj in response['Contents']]
            print(f"  Files created: {len(files)}")

            # Categorize files
            page_files = [f for f in files if '/pages/' in f]
            index_files = [f for f in files if f.endswith('index.json')]
            shard_files = [f for f in files if f.endswith('.latest.json')]

            print(f"  - Page guidelines: {len(page_files)}")
            print(f"  - Index files: {len(index_files)}")
            print(f"  - Subtopic shards: {len(shard_files)}")
            print()

            # Show shard files
            if shard_files:
                print("  Subtopic shards created:")
                for sf in shard_files:
                    parts = sf.split('/')
                    topic = parts[-3]
                    subtopic = parts[-1].replace('.latest.json', '')
                    print(f"    - {topic}/{subtopic}")
                print()

        # Check database sync
        from models.database import TeachingGuideline
        guidelines = db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id
        ).all()

        print(f"💾 Database sync:")
        print(f"  Teaching guidelines synced: {len(guidelines)}")
        if guidelines:
            print(f"  Topics:")
            for g in guidelines:
                print(f"    - {g.topic} > {g.subtopic}")
        print()

        print("=" * 80)
        print("TEST COMPLETE!")
        print("=" * 80)

    except Exception as e:
        end_time = time.time()
        elapsed = end_time - start_time

        print()
        print("=" * 80)
        print("❌ EXTRACTION FAILED!")
        print("=" * 80)
        print(f"Error: {e}")
        print(f"Time before failure: {elapsed:.2f} seconds")
        print()

        import traceback
        print("Full traceback:")
        traceback.print_exc()

        raise

if __name__ == "__main__":
    main()
