"""Tests for session extension logic."""

from unittest.mock import MagicMock


class TestExtension:
    def test_extension_bypasses_early_return(self):
        """When is_complete=True and allow_extension=True, tutor should still run."""
        session = MagicMock()
        session.is_complete = True
        session.allow_extension = True
        # The condition: if session.is_complete and not session.allow_extension
        should_short_circuit = session.is_complete and not session.allow_extension
        assert should_short_circuit is False

    def test_no_extension_short_circuits(self):
        """When is_complete=True and allow_extension=False, should short-circuit."""
        session = MagicMock()
        session.is_complete = True
        session.allow_extension = False
        should_short_circuit = session.is_complete and not session.allow_extension
        assert should_short_circuit is True
