"""
Database management layer for PostgreSQL.

Provides abstraction for database connections, sessions, and health checks.
"""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, text, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from config import get_settings
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages PostgreSQL database connections and sessions.

    Provides:
    - Engine creation with connection pooling
    - Session factory
    - Health checks
    - Context managers for transactions
    """

    def __init__(self):
        """Initialize the database manager with settings from config."""
        self.settings = get_settings()
        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    @property
    def engine(self) -> Engine:
        """
        Get or create the SQLAlchemy engine.

        Returns:
            Engine: SQLAlchemy engine instance
        """
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """
        Get or create the session factory.

        Returns:
            sessionmaker: Session factory
        """
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False
            )
        return self._session_factory

    def _create_engine(self) -> Engine:
        """
        Create SQLAlchemy engine with PostgreSQL-specific settings.

        Returns:
            Engine: Configured SQLAlchemy engine
        """
        logger.info(f"Creating database engine for: {self._mask_password(str(self.settings.database_url))}")

        engine = create_engine(
            str(self.settings.database_url),
            poolclass=QueuePool,
            pool_size=self.settings.db_pool_size,
            max_overflow=self.settings.db_max_overflow,
            pool_timeout=self.settings.db_pool_timeout,
            pool_pre_ping=True,  # Verify connections before using
            echo=self.settings.log_level == "DEBUG",  # SQL logging
        )

        logger.info("Database engine created successfully")
        return engine

    def get_session(self) -> Session:
        """
        Create a new database session.

        Returns:
            Session: SQLAlchemy session
        """
        return self.session_factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Provide a transactional scope for database operations.

        Usage:
            with db_manager.session_scope() as session:
                session.query(Model).all()

        Yields:
            Session: Database session

        Raises:
            Exception: Re-raises any exception after rolling back
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database transaction failed: {e}")
            raise
        finally:
            session.close()

    def health_check(self) -> bool:
        """
        Check database connectivity.

        Returns:
            bool: True if database is accessible, False otherwise
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database health check passed")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def close(self):
        """Close the database engine and dispose of connections."""
        if self._engine:
            self._engine.dispose()
            logger.info("Database engine closed")

    @staticmethod
    def _mask_password(url: str) -> str:
        """
        Mask the password in a database URL for logging.

        Args:
            url: Database URL

        Returns:
            str: URL with password masked
        """
        if "@" in url and ":" in url:
            parts = url.split("@")
            if len(parts) == 2:
                credentials = parts[0]
                if ":" in credentials:
                    user_pass = credentials.split(":")
                    if len(user_pass) >= 2:
                        # Keep protocol and user, mask password
                        return f"{':'.join(user_pass[:-1])}:****@{parts[1]}"
        return url


# Global database manager instance
_db_manager: DatabaseManager | None = None


def get_db_manager() -> DatabaseManager:
    """
    Get or create the global database manager instance.

    Returns:
        DatabaseManager: Database manager
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_db() -> Generator[Session, None, None]:
    """
    Dependency injection for FastAPI endpoints.

    Usage:
        @app.get("/")
        def endpoint(db: Session = Depends(get_db)):
            return db.query(Model).all()

    Yields:
        Session: Database session
    """
    db_manager = get_db_manager()
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()


def reset_db_manager():
    """Reset the global database manager (useful for testing)."""
    global _db_manager
    if _db_manager:
        _db_manager.close()
    _db_manager = None
