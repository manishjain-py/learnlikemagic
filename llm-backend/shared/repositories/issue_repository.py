"""Repository for Issue data access."""
from typing import List, Optional
from sqlalchemy.orm import Session

from shared.models.entities import Issue


class IssueRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, issue: Issue) -> Issue:
        self.db.add(issue)
        self.db.commit()
        self.db.refresh(issue)
        return issue

    def get_by_id(self, issue_id: str) -> Optional[Issue]:
        return self.db.query(Issue).filter(Issue.id == issue_id).first()

    def get_all(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Issue]:
        query = self.db.query(Issue)
        if status:
            query = query.filter(Issue.status == status)
        return query.order_by(Issue.created_at.desc()).limit(limit).offset(offset).all()

    def count(self, status: Optional[str] = None) -> int:
        query = self.db.query(Issue)
        if status:
            query = query.filter(Issue.status == status)
        return query.count()

    def update_status(self, issue_id: str, status: str) -> Optional[Issue]:
        issue = self.get_by_id(issue_id)
        if not issue:
            return None
        issue.status = status
        self.db.commit()
        self.db.refresh(issue)
        return issue
