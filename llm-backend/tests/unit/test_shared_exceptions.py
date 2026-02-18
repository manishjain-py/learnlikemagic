"""Unit tests for shared/utils/exceptions.py — custom exception hierarchy."""
import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-fake")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from shared.utils.exceptions import (
    LearnLikeMagicException,
    SessionNotFoundException,
    GuidelineNotFoundException,
    LLMProviderException,
    DatabaseException,
)


# ---------------------------------------------------------------------------
# LearnLikeMagicException — base class
# ---------------------------------------------------------------------------

class TestLearnLikeMagicException:
    """Tests for the base LearnLikeMagicException."""

    def test_is_exception_subclass(self):
        """LearnLikeMagicException inherits from Exception."""
        assert issubclass(LearnLikeMagicException, Exception)

    def test_can_be_instantiated(self):
        """Can instantiate with a message."""
        exc = LearnLikeMagicException("something went wrong")
        assert str(exc) == "something went wrong"

    def test_can_be_raised_and_caught(self):
        """Can raise and catch by its type."""
        with pytest.raises(LearnLikeMagicException):
            raise LearnLikeMagicException("test")


# ---------------------------------------------------------------------------
# SessionNotFoundException
# ---------------------------------------------------------------------------

class TestSessionNotFoundException:
    """Tests for SessionNotFoundException."""

    def test_inherits_from_base(self):
        """SessionNotFoundException is a LearnLikeMagicException."""
        assert issubclass(SessionNotFoundException, LearnLikeMagicException)

    def test_stores_session_id(self):
        """The session_id attribute is stored correctly."""
        exc = SessionNotFoundException("sess-abc-123")
        assert exc.session_id == "sess-abc-123"

    def test_message_format(self):
        """The message includes the session ID."""
        exc = SessionNotFoundException("sess-abc-123")
        assert "sess-abc-123" in str(exc)
        assert "Session" in str(exc)
        assert "not found" in str(exc)

    def test_to_http_exception_status_404(self):
        """to_http_exception returns a 404 HTTPException."""
        exc = SessionNotFoundException("sess-abc-123")
        http_exc = exc.to_http_exception()
        assert http_exc.status_code == 404

    def test_to_http_exception_detail(self):
        """to_http_exception detail includes the session ID."""
        exc = SessionNotFoundException("sess-abc-123")
        http_exc = exc.to_http_exception()
        assert "sess-abc-123" in http_exc.detail

    def test_isinstance_checks(self):
        """Can be caught as both its own type and the base type."""
        exc = SessionNotFoundException("s1")
        assert isinstance(exc, SessionNotFoundException)
        assert isinstance(exc, LearnLikeMagicException)
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# GuidelineNotFoundException
# ---------------------------------------------------------------------------

class TestGuidelineNotFoundException:
    """Tests for GuidelineNotFoundException."""

    def test_inherits_from_base(self):
        """GuidelineNotFoundException is a LearnLikeMagicException."""
        assert issubclass(GuidelineNotFoundException, LearnLikeMagicException)

    def test_stores_guideline_id(self):
        """The guideline_id attribute is stored correctly."""
        exc = GuidelineNotFoundException("guide-xyz")
        assert exc.guideline_id == "guide-xyz"

    def test_message_format(self):
        """The message includes the guideline ID."""
        exc = GuidelineNotFoundException("guide-xyz")
        assert "guide-xyz" in str(exc)
        assert "Guideline" in str(exc)
        assert "not found" in str(exc)

    def test_to_http_exception_status_404(self):
        """to_http_exception returns a 404 HTTPException."""
        exc = GuidelineNotFoundException("guide-xyz")
        http_exc = exc.to_http_exception()
        assert http_exc.status_code == 404

    def test_to_http_exception_detail(self):
        """to_http_exception detail includes the guideline ID."""
        exc = GuidelineNotFoundException("guide-xyz")
        http_exc = exc.to_http_exception()
        assert "guide-xyz" in http_exc.detail

    def test_to_http_exception_detail_mentions_teaching_guideline(self):
        """to_http_exception detail mentions 'Teaching guideline'."""
        exc = GuidelineNotFoundException("guide-xyz")
        http_exc = exc.to_http_exception()
        assert "Teaching guideline" in http_exc.detail

    def test_isinstance_checks(self):
        """Can be caught as both its own type and the base type."""
        exc = GuidelineNotFoundException("g1")
        assert isinstance(exc, GuidelineNotFoundException)
        assert isinstance(exc, LearnLikeMagicException)
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# LLMProviderException
# ---------------------------------------------------------------------------

class TestLLMProviderException:
    """Tests for LLMProviderException."""

    def test_inherits_from_base(self):
        """LLMProviderException is a LearnLikeMagicException."""
        assert issubclass(LLMProviderException, LearnLikeMagicException)

    def test_stores_original_error(self):
        """The original_error attribute is stored correctly."""
        orig = ValueError("API timeout")
        exc = LLMProviderException(orig)
        assert exc.original_error is orig

    def test_message_includes_original_error(self):
        """The message includes the string representation of the original error."""
        orig = RuntimeError("rate limit exceeded")
        exc = LLMProviderException(orig)
        assert "rate limit exceeded" in str(exc)
        assert "LLM provider error" in str(exc)

    def test_to_http_exception_status_503(self):
        """to_http_exception returns a 503 HTTPException."""
        exc = LLMProviderException(RuntimeError("fail"))
        http_exc = exc.to_http_exception()
        assert http_exc.status_code == 503

    def test_to_http_exception_detail_is_generic(self):
        """to_http_exception detail does not leak internal error details."""
        exc = LLMProviderException(RuntimeError("secret internal detail"))
        http_exc = exc.to_http_exception()
        assert "secret internal detail" not in http_exc.detail
        assert "unavailable" in http_exc.detail.lower()

    def test_isinstance_checks(self):
        """Can be caught as both its own type and the base type."""
        exc = LLMProviderException(Exception("x"))
        assert isinstance(exc, LLMProviderException)
        assert isinstance(exc, LearnLikeMagicException)
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# DatabaseException
# ---------------------------------------------------------------------------

class TestDatabaseException:
    """Tests for DatabaseException."""

    def test_inherits_from_base(self):
        """DatabaseException is a LearnLikeMagicException."""
        assert issubclass(DatabaseException, LearnLikeMagicException)

    def test_stores_operation(self):
        """The operation attribute is stored correctly."""
        exc = DatabaseException("INSERT", RuntimeError("connection refused"))
        assert exc.operation == "INSERT"

    def test_stores_original_error(self):
        """The original_error attribute is stored correctly."""
        orig = RuntimeError("connection refused")
        exc = DatabaseException("INSERT", orig)
        assert exc.original_error is orig

    def test_message_format(self):
        """The message includes both operation and original error."""
        exc = DatabaseException("UPDATE", ValueError("constraint violation"))
        msg = str(exc)
        assert "UPDATE" in msg
        assert "constraint violation" in msg
        assert "Database" in msg

    def test_to_http_exception_status_500(self):
        """to_http_exception returns a 500 HTTPException."""
        exc = DatabaseException("DELETE", RuntimeError("fail"))
        http_exc = exc.to_http_exception()
        assert http_exc.status_code == 500

    def test_to_http_exception_detail_is_generic(self):
        """to_http_exception detail does not leak internal error details."""
        exc = DatabaseException("SELECT", RuntimeError("password=secret123"))
        http_exc = exc.to_http_exception()
        assert "secret123" not in http_exc.detail
        assert "Database operation failed" in http_exc.detail

    def test_isinstance_checks(self):
        """Can be caught as both its own type and the base type."""
        exc = DatabaseException("op", Exception("x"))
        assert isinstance(exc, DatabaseException)
        assert isinstance(exc, LearnLikeMagicException)
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# Cross-cutting: hierarchy and catch patterns
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    """Tests that verify the exception hierarchy works for polymorphic catch."""

    def test_catch_session_not_found_as_base(self):
        """SessionNotFoundException can be caught as LearnLikeMagicException."""
        with pytest.raises(LearnLikeMagicException):
            raise SessionNotFoundException("s1")

    def test_catch_guideline_not_found_as_base(self):
        """GuidelineNotFoundException can be caught as LearnLikeMagicException."""
        with pytest.raises(LearnLikeMagicException):
            raise GuidelineNotFoundException("g1")

    def test_catch_llm_provider_as_base(self):
        """LLMProviderException can be caught as LearnLikeMagicException."""
        with pytest.raises(LearnLikeMagicException):
            raise LLMProviderException(RuntimeError("err"))

    def test_catch_database_as_base(self):
        """DatabaseException can be caught as LearnLikeMagicException."""
        with pytest.raises(LearnLikeMagicException):
            raise DatabaseException("op", RuntimeError("err"))

    def test_all_exceptions_are_not_interchangeable(self):
        """SessionNotFoundException is not a DatabaseException, etc."""
        exc = SessionNotFoundException("s1")
        assert not isinstance(exc, DatabaseException)
        assert not isinstance(exc, LLMProviderException)
        assert not isinstance(exc, GuidelineNotFoundException)

    def test_http_exception_types_are_fastapi(self):
        """All to_http_exception() return FastAPI HTTPException instances."""
        from fastapi import HTTPException as FastAPIHTTPException

        exceptions = [
            SessionNotFoundException("s1"),
            GuidelineNotFoundException("g1"),
            LLMProviderException(RuntimeError("err")),
            DatabaseException("op", RuntimeError("err")),
        ]
        for exc in exceptions:
            http_exc = exc.to_http_exception()
            assert isinstance(http_exc, FastAPIHTTPException)
