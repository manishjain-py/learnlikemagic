"""Auth service — handles user sync from Cognito."""

import logging
import boto3
from sqlalchemy.orm import Session as DBSession
from config import get_settings
from auth.repositories.user_repository import UserRepository

logger = logging.getLogger("auth.service")


class AuthService:
    """Syncs Cognito users to local DB on first login."""

    def __init__(self, db: DBSession):
        self.db = db
        self.user_repo = UserRepository(db)

    @staticmethod
    def _derive_auth_provider(claims: dict) -> str:
        """
        Derive auth_provider from Cognito token claims (server-side).

        This is NOT taken from the client request body to prevent spoofing.

        Cognito claim inspection:
        - Google federated users have an `identities` claim with providerName="Google"
        - Phone users have `phone_number_verified=true` and cognito:username starts with "+"
        - Email users have `email_verified=true` as default fallback
        """
        # Check for federated identity (Google OAuth)
        identities = claims.get("identities", [])
        if identities:
            provider = identities[0].get("providerName", "")
            if provider == "Google":
                return "google"

        # Check for phone-based signup
        if claims.get("phone_number_verified"):
            return "phone"
        username = claims.get("cognito:username", "")
        if username.startswith("+"):
            return "phone"

        # Default: email
        return "email"

    def sync_user(self, claims: dict):
        """
        Create or update user record after Cognito authentication.
        Called from /auth/sync endpoint with the full decoded ID token claims.
        """
        cognito_sub = claims["sub"]
        email = claims.get("email")
        phone = claims.get("phone_number")
        name = claims.get("name")
        auth_provider = self._derive_auth_provider(claims)

        existing = self.user_repo.get_by_cognito_sub(cognito_sub)

        if existing:
            # Update last login, merge any new data
            self.user_repo.update_last_login(existing.id)
            if email and not existing.email:
                self.user_repo.update_profile(existing.id, email=email)
            if phone and not existing.phone:
                self.user_repo.update_profile(existing.id, phone=phone)
            return existing
        else:
            # First login — create user row
            return self.user_repo.create(
                cognito_sub=cognito_sub,
                email=email,
                phone=phone,
                auth_provider=auth_provider,
                name=name,
            )

    @staticmethod
    def provision_phone_user(phone: str) -> None:
        """
        Ensure a Cognito user exists for this phone number.
        Uses admin API to bypass required email/name schema constraints.
        Idempotent — silently ignores if user already exists.
        """
        import secrets
        settings = get_settings()
        cognito = boto3.client("cognito-idp", region_name=settings.cognito_region)

        try:
            cognito.admin_get_user(
                UserPoolId=settings.cognito_user_pool_id,
                Username=phone,
            )
            return  # User already exists
        except cognito.exceptions.UserNotFoundException:
            pass

        # Create user with placeholder email (required by schema) and phone
        phone_digits = phone.replace("+", "")
        cognito.admin_create_user(
            UserPoolId=settings.cognito_user_pool_id,
            Username=phone,
            UserAttributes=[
                {"Name": "phone_number", "Value": phone},
                {"Name": "phone_number_verified", "Value": "true"},
                {"Name": "email", "Value": f"phone_{phone_digits}@placeholder.local"},
                {"Name": "name", "Value": phone},
            ],
            MessageAction="SUPPRESS",
        )

        # Set password to move from FORCE_CHANGE_PASSWORD to CONFIRMED
        temp_password = f"P{secrets.token_urlsafe(16)}!1a"
        cognito.admin_set_user_password(
            UserPoolId=settings.cognito_user_pool_id,
            Username=phone,
            Password=temp_password,
            Permanent=True,
        )
        logger.info(f"Provisioned phone user {phone}")

    def delete_user(self, cognito_sub: str) -> bool:
        """
        Delete a user from both the local DB and Cognito.
        Returns True if user was found and deleted.
        """
        settings = get_settings()
        user = self.user_repo.get_by_cognito_sub(cognito_sub)
        if not user:
            return False

        # Delete from Cognito
        cognito = boto3.client(
            "cognito-idp", region_name=settings.cognito_region
        )
        try:
            cognito.admin_delete_user(
                UserPoolId=settings.cognito_user_pool_id,
                Username=cognito_sub,
            )
        except cognito.exceptions.UserNotFoundException:
            logger.warning(f"User {cognito_sub} not found in Cognito, deleting DB row only")

        # Delete from DB
        self.user_repo.delete(user.id)
        logger.info(f"Deleted user {user.id} (sub={cognito_sub})")
        return True
