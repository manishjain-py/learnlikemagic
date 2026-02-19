"""User data access layer."""

from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlalchemy.orm import Session as DBSession
from shared.models.entities import User


class UserRepository:
    """CRUD operations for the users table."""

    def __init__(self, db: DBSession):
        self.db = db

    def get_by_id(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_cognito_sub(self, cognito_sub: str) -> Optional[User]:
        return self.db.query(User).filter(User.cognito_sub == cognito_sub).first()

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def create(self, cognito_sub: str, email: Optional[str], phone: Optional[str],
               auth_provider: str, name: Optional[str] = None) -> User:
        user = User(
            id=str(uuid4()),
            cognito_sub=cognito_sub,
            email=email,
            phone=phone,
            auth_provider=auth_provider,
            name=name,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_login_at=datetime.utcnow(),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_profile(self, user_id: str, **fields) -> Optional[User]:
        user = self.get_by_id(user_id)
        if not user:
            return None
        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_last_login(self, user_id: str) -> None:
        user = self.get_by_id(user_id)
        if user:
            user.last_login_at = datetime.utcnow()
            self.db.commit()
