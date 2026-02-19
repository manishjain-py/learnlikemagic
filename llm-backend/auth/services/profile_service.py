"""Profile management service."""

from typing import Optional
from sqlalchemy.orm import Session as DBSession
from auth.repositories.user_repository import UserRepository


class ProfileService:
    """Business logic for profile operations."""

    def __init__(self, db: DBSession):
        self.db = db
        self.user_repo = UserRepository(db)

    def get_profile(self, user_id: str):
        return self.user_repo.get_by_id(user_id)

    def update_profile(self, user_id: str, name: Optional[str] = None,
                       age: Optional[int] = None, grade: Optional[int] = None,
                       board: Optional[str] = None, school_name: Optional[str] = None,
                       about_me: Optional[str] = None):
        fields = {}
        if name is not None:
            fields["name"] = name
        if age is not None:
            fields["age"] = age
        if grade is not None:
            fields["grade"] = grade
        if board is not None:
            fields["board"] = board
        if school_name is not None:
            fields["school_name"] = school_name
        if about_me is not None:
            fields["about_me"] = about_me

        user = self.user_repo.update_profile(user_id, **fields)

        # Check if onboarding is now complete (all required fields filled)
        if user and user.name and user.age and user.grade and user.board:
            if not user.onboarding_complete:
                self.user_repo.update_profile(user_id, onboarding_complete=True)
                user.onboarding_complete = True

        return user
