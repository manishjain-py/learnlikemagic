"""Custom exception hierarchy for better error handling."""
from fastapi import HTTPException, status


class LearnLikeMagicException(Exception):
    """Base exception for all application errors."""
    pass


class SessionNotFoundException(LearnLikeMagicException):
    """Raised when a session is not found."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session {session_id} not found")

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {self.session_id} not found"
        )


class GuidelineNotFoundException(LearnLikeMagicException):
    """Raised when a teaching guideline is not found."""

    def __init__(self, guideline_id: str):
        self.guideline_id = guideline_id
        super().__init__(f"Guideline {guideline_id} not found")

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teaching guideline {self.guideline_id} not found"
        )


class LLMProviderException(LearnLikeMagicException):
    """Raised when LLM provider fails."""

    def __init__(self, original_error: Exception):
        self.original_error = original_error
        super().__init__(f"LLM provider error: {str(original_error)}")

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service temporarily unavailable"
        )


class DatabaseException(LearnLikeMagicException):
    """Raised when database operations fail."""

    def __init__(self, operation: str, original_error: Exception):
        self.operation = operation
        self.original_error = original_error
        super().__init__(f"Database {operation} failed: {str(original_error)}")

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed"
        )


class StaleStateError(LearnLikeMagicException):
    """Raised when an optimistic locking conflict is detected during session update."""

    def __init__(self, message: str):
        super().__init__(message)

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(self)
        )
