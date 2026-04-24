"""Domain exceptions for the book ingestion pipeline.

These are raised by service-layer code and translated to HTTP responses at
the API layer. They inherit from ``LearnLikeMagicException`` so callers can
translate them via the established ``to_http_exception()`` contract.
"""
from fastapi import HTTPException, status

from shared.utils.exceptions import LearnLikeMagicException


class StageGateRejected(LearnLikeMagicException):
    """Chapter is not in a valid state for the requested stage (409)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=self.message,
        )
