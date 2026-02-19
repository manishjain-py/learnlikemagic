"""Auth service — handles user sync from Cognito."""

import logging
from sqlalchemy.orm import Session as DBSession
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

        Handles re-registration: if a user deleted their Cognito account and
        re-signed up, the email/phone stays in the DB with an old cognito_sub.
        We update the sub to link the existing row to the new Cognito identity.
        """
        cognito_sub = claims["sub"]
        email = claims.get("email")
        phone = claims.get("phone_number")
        name = claims.get("name")
        auth_provider = self._derive_auth_provider(claims)

        # 1. Try matching by cognito_sub (normal case)
        existing = self.user_repo.get_by_cognito_sub(cognito_sub)

        if existing:
            self.user_repo.update_last_login(existing.id)
            if email and not existing.email:
                self.user_repo.update_profile(existing.id, email=email)
            if phone and not existing.phone:
                self.user_repo.update_profile(existing.id, phone=phone)
            return existing

        # 2. Try matching by email or phone (re-registration with new cognito_sub)
        existing = None
        if email:
            existing = self.user_repo.get_by_email(email)
        if not existing and phone:
            existing = self.user_repo.get_by_phone(phone)

        if existing:
            logger.info(f"Re-linking user {existing.id} to new cognito_sub {cognito_sub}")
            self.user_repo.update_profile(existing.id, cognito_sub=cognito_sub)
            self.user_repo.update_last_login(existing.id)
            return existing

        # 3. Brand new user
        return self.user_repo.create(
            cognito_sub=cognito_sub,
            email=email,
            phone=phone,
            auth_provider=auth_provider,
            name=name,
        )
