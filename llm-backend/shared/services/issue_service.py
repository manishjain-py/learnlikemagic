"""Service for issue reporting — CRUD + screenshot upload."""
import logging
from uuid import uuid4
from typing import Optional, List

from sqlalchemy.orm import Session as DBSession

from shared.models.entities import Issue, User
from shared.repositories.issue_repository import IssueRepository
from shared.utils.s3_client import get_s3_client

logger = logging.getLogger(__name__)


class IssueService:
    def __init__(self, db: DBSession):
        self.db = db
        self.repo = IssueRepository(db)

    def upload_screenshot(self, issue_id: str, file_bytes: bytes, filename: str, content_type: str) -> str:
        """Upload a screenshot to S3. Returns the S3 key."""
        s3 = get_s3_client()
        s3_key = f"issues/{issue_id}/{filename}"
        s3.upload_bytes(file_bytes, s3_key, content_type=content_type)
        return s3_key

    def create_issue(
        self,
        title: str,
        description: str,
        original_input: str,
        screenshot_s3_keys: Optional[List[str]],
        user_id: Optional[str] = None,
    ) -> Issue:
        """Create an issue in the database."""
        reporter_name = None
        if user_id:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user:
                reporter_name = user.preferred_name or user.name

        issue = Issue(
            id=str(uuid4()),
            user_id=user_id,
            reporter_name=reporter_name,
            title=title,
            description=description,
            original_input=original_input,
            screenshot_s3_keys=screenshot_s3_keys or [],
            status="open",
        )
        return self.repo.create(issue)

    def list_issues(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> dict:
        """List issues with optional status filter."""
        issues = self.repo.get_all(status=status, limit=limit, offset=offset)
        total = self.repo.count(status=status)
        return {"issues": issues, "total": total}

    def get_issue(self, issue_id: str) -> Optional[Issue]:
        return self.repo.get_by_id(issue_id)

    def update_status(self, issue_id: str, status: str) -> Optional[Issue]:
        if status not in ("open", "in_progress", "closed"):
            raise ValueError(f"Invalid status: {status}")
        return self.repo.update_status(issue_id, status)

    def get_screenshot_url(self, s3_key: str) -> str:
        """Get a presigned URL for a screenshot."""
        s3 = get_s3_client()
        return s3.get_presigned_url(s3_key)
