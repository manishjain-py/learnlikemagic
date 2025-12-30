
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.models import Base, TeachingGuideline
from book_ingestion.services.db_sync_service import DBSyncService
from book_ingestion.models.guideline_models import SubtopicShard

# Setup in-memory DB
engine = create_engine('sqlite:///:memory:')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

def test_full_workflow(db_session):
    # 1. Setup Mock Data
    book_id = "test_book"
    shard = SubtopicShard(
        topic_key="topic-1",
        topic_title="Topic 1",
        subtopic_key="subtopic-1",
        subtopic_title="Subtopic 1",
        source_page_start=1,
        source_page_end=5,
        status="final",
        guidelines="Test guidelines",
        version=1
    )
    
    # Mock S3 Client
    mock_s3 = MagicMock()
    mock_s3.download_json.return_value = shard.model_dump()
    
    # Mock Index
    mock_index = {
        "book_id": book_id,
        "topics": [{
            "topic_key": "topic-1",
            "topic_title": "Topic 1",
            "subtopics": [{
                "subtopic_key": "subtopic-1",
                "subtopic_title": "Subtopic 1",
                "status": "final"
            }]
        }]
    }
    
    def side_effect(key):
        if "index.json" in key:
            return mock_index
        return shard.model_dump()
        
    mock_s3.download_json.side_effect = side_effect

    # 2. Sync to DB (First Time)
    sync_service = DBSyncService(db_session)
    book_metadata = {"grade": 3, "subject": "Math", "board": "CBSE"}
    
    print("\n--- Sync 1 ---")
    sync_service.sync_book_guidelines(book_id, mock_s3, book_metadata)
    
    # Verify DB State
    guideline = db_session.query(TeachingGuideline).filter_by(book_id=book_id).first()
    assert guideline is not None
    assert guideline.review_status == "TO_BE_REVIEWED"
    print(f"Guideline created with status: {guideline.review_status}")

    # 3. Approve Guideline
    print("\n--- Approval ---")
    guideline.review_status = "APPROVED"
    db_session.commit()
    
    guideline = db_session.query(TeachingGuideline).filter_by(book_id=book_id).first()
    assert guideline.review_status == "APPROVED"
    print(f"Guideline status updated to: {guideline.review_status}")

    # 4. Re-sync (Simulate regeneration/update)
    print("\n--- Sync 2 (Re-sync) ---")
    sync_service.sync_book_guidelines(book_id, mock_s3, book_metadata)
    
    # Verify DB State (Should be reset)
    guideline = db_session.query(TeachingGuideline).filter_by(book_id=book_id).first()
    assert guideline.review_status == "TO_BE_REVIEWED"
    print(f"Guideline status reset to: {guideline.review_status}")

    # 5. Test Job Locking
    print("\n--- Job Locking Test ---")
    from book_ingestion.services.job_lock_service import JobLockService, JobLockError
    from book_ingestion.models.database import BookJob
    
    # Create Book table if not exists (for foreign key)
    from book_ingestion.models.database import Book
    if not engine.dialect.has_table(engine.connect(), "books"):
        Book.__table__.create(engine)
        # Create dummy book
        book = Book(id=book_id, title="Test", country="IN", board="CBSE", grade=3, subject="Math", status="draft", s3_prefix="x")
        db_session.add(book)
        db_session.commit()

    job_service = JobLockService(db_session)
    job_id = job_service.acquire_lock(book_id, "extraction")
    print(f"Acquired lock: {job_id}")
    
    try:
        job_service.acquire_lock(book_id, "finalization")
        assert False, "Should have raised JobLockError"
    except JobLockError:
        print("✅ Correctly prevented concurrent job")
        
    job_service.release_lock(job_id)
    print("Released lock")
    
    # Verify lock released
    job_id_2 = job_service.acquire_lock(book_id, "finalization")
    print(f"Acquired new lock: {job_id_2}")
    job_service.release_lock(job_id_2)
    
    print("\n✅ Verification Successful!")

if __name__ == "__main__":
    # Manual run wrapper
    session = Session()
    try:
        test_full_workflow(session)
    finally:
        session.close()
