"""Unit tests for tutor/models/agent_logs.py

Tests AgentLogEntry, AgentLogStore (add/retrieve/filter/trim/clear/stats),
the get_agent_log_store singleton, and thread-safety.
"""

import threading
import pytest

from tutor.models.agent_logs import AgentLogEntry, AgentLogStore, get_agent_log_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(
    session_id: str = "sess_1",
    turn_id: str = "turn_1",
    agent_name: str = "planner",
    event_type: str = "invoke",
    **kwargs,
) -> AgentLogEntry:
    return AgentLogEntry(
        session_id=session_id,
        turn_id=turn_id,
        agent_name=agent_name,
        event_type=event_type,
        **kwargs,
    )


# ===========================================================================
# AgentLogEntry
# ===========================================================================

class TestAgentLogEntry:
    def test_required_fields(self):
        entry = _entry()
        assert entry.session_id == "sess_1"
        assert entry.turn_id == "turn_1"
        assert entry.agent_name == "planner"
        assert entry.event_type == "invoke"

    def test_optional_fields_defaults(self):
        entry = _entry()
        assert entry.input_summary is None
        assert entry.output is None
        assert entry.reasoning is None
        assert entry.duration_ms is None
        assert entry.prompt is None
        assert entry.model is None
        assert entry.metadata == {}

    def test_optional_fields_set(self):
        entry = _entry(
            input_summary="some input",
            output={"key": "value"},
            reasoning="because",
            duration_ms=150,
            prompt="test prompt",
            model="gpt-4",
            metadata={"extra": True},
        )
        assert entry.input_summary == "some input"
        assert entry.output == {"key": "value"}
        assert entry.reasoning == "because"
        assert entry.duration_ms == 150
        assert entry.prompt == "test prompt"
        assert entry.model == "gpt-4"
        assert entry.metadata == {"extra": True}

    def test_timestamp_auto_set(self):
        from datetime import datetime
        entry = _entry()
        assert isinstance(entry.timestamp, datetime)


# ===========================================================================
# AgentLogStore — add_log & get_logs
# ===========================================================================

class TestAgentLogStoreAddAndGet:
    def test_add_and_retrieve(self):
        store = AgentLogStore()
        e = _entry()
        store.add_log(e)
        logs = store.get_logs("sess_1")
        assert len(logs) == 1
        assert logs[0] is e

    def test_get_logs_empty_session(self):
        store = AgentLogStore()
        logs = store.get_logs("nonexistent")
        assert logs == []

    def test_add_multiple_sessions(self):
        store = AgentLogStore()
        store.add_log(_entry(session_id="s1"))
        store.add_log(_entry(session_id="s2"))
        store.add_log(_entry(session_id="s1"))
        assert len(store.get_logs("s1")) == 2
        assert len(store.get_logs("s2")) == 1


# ===========================================================================
# AgentLogStore — filtering
# ===========================================================================

class TestAgentLogStoreFiltering:
    def test_filter_by_turn_id(self):
        store = AgentLogStore()
        store.add_log(_entry(turn_id="t1"))
        store.add_log(_entry(turn_id="t2"))
        store.add_log(_entry(turn_id="t1"))
        logs = store.get_logs("sess_1", turn_id="t1")
        assert len(logs) == 2

    def test_filter_by_agent_name(self):
        store = AgentLogStore()
        store.add_log(_entry(agent_name="planner"))
        store.add_log(_entry(agent_name="evaluator"))
        store.add_log(_entry(agent_name="planner"))
        logs = store.get_logs("sess_1", agent_name="planner")
        assert len(logs) == 2

    def test_filter_by_turn_and_agent(self):
        store = AgentLogStore()
        store.add_log(_entry(turn_id="t1", agent_name="planner"))
        store.add_log(_entry(turn_id="t1", agent_name="evaluator"))
        store.add_log(_entry(turn_id="t2", agent_name="planner"))
        logs = store.get_logs("sess_1", turn_id="t1", agent_name="planner")
        assert len(logs) == 1

    def test_filter_no_matches(self):
        store = AgentLogStore()
        store.add_log(_entry(turn_id="t1", agent_name="planner"))
        logs = store.get_logs("sess_1", turn_id="t99")
        assert logs == []


# ===========================================================================
# AgentLogStore — max_logs trimming
# ===========================================================================

class TestAgentLogStoreTrimming:
    def test_trims_to_max_logs(self):
        store = AgentLogStore(max_logs_per_session=5)
        for i in range(10):
            store.add_log(_entry(event_type=f"event_{i}"))
        logs = store.get_logs("sess_1")
        assert len(logs) == 5

    def test_keeps_most_recent_after_trim(self):
        store = AgentLogStore(max_logs_per_session=3)
        for i in range(6):
            store.add_log(_entry(event_type=f"event_{i}"))
        logs = store.get_logs("sess_1")
        assert len(logs) == 3
        assert logs[0].event_type == "event_3"
        assert logs[1].event_type == "event_4"
        assert logs[2].event_type == "event_5"

    def test_no_trim_within_limit(self):
        store = AgentLogStore(max_logs_per_session=10)
        for i in range(5):
            store.add_log(_entry(event_type=f"event_{i}"))
        logs = store.get_logs("sess_1")
        assert len(logs) == 5

    def test_trim_per_session_independent(self):
        store = AgentLogStore(max_logs_per_session=3)
        for i in range(5):
            store.add_log(_entry(session_id="s1", event_type=f"e_{i}"))
        for i in range(2):
            store.add_log(_entry(session_id="s2", event_type=f"e_{i}"))
        assert len(store.get_logs("s1")) == 3
        assert len(store.get_logs("s2")) == 2


# ===========================================================================
# AgentLogStore — get_recent_logs
# ===========================================================================

class TestAgentLogStoreRecentLogs:
    def test_recent_logs_returns_last_n(self):
        store = AgentLogStore()
        for i in range(10):
            store.add_log(_entry(event_type=f"event_{i}"))
        recent = store.get_recent_logs("sess_1", limit=3)
        assert len(recent) == 3
        assert recent[0].event_type == "event_7"
        assert recent[2].event_type == "event_9"

    def test_recent_logs_returns_all_if_fewer(self):
        store = AgentLogStore()
        store.add_log(_entry())
        store.add_log(_entry())
        recent = store.get_recent_logs("sess_1", limit=50)
        assert len(recent) == 2

    def test_recent_logs_empty_session(self):
        store = AgentLogStore()
        recent = store.get_recent_logs("nonexistent", limit=10)
        assert recent == []


# ===========================================================================
# AgentLogStore — clear_session
# ===========================================================================

class TestAgentLogStoreClearSession:
    def test_clear_removes_all_logs(self):
        store = AgentLogStore()
        for _ in range(5):
            store.add_log(_entry(session_id="s1"))
        store.clear_session("s1")
        assert store.get_logs("s1") == []

    def test_clear_does_not_affect_other_sessions(self):
        store = AgentLogStore()
        store.add_log(_entry(session_id="s1"))
        store.add_log(_entry(session_id="s2"))
        store.clear_session("s1")
        assert len(store.get_logs("s2")) == 1

    def test_clear_nonexistent_session_is_safe(self):
        store = AgentLogStore()
        store.clear_session("no_such_session")  # Should not raise


# ===========================================================================
# AgentLogStore — get_stats
# ===========================================================================

class TestAgentLogStoreStats:
    def test_stats_empty(self):
        store = AgentLogStore(max_logs_per_session=200)
        stats = store.get_stats()
        assert stats["session_count"] == 0
        assert stats["total_logs"] == 0
        assert stats["max_logs_per_session"] == 200

    def test_stats_with_data(self):
        store = AgentLogStore(max_logs_per_session=100)
        store.add_log(_entry(session_id="s1"))
        store.add_log(_entry(session_id="s1"))
        store.add_log(_entry(session_id="s2"))
        stats = store.get_stats()
        assert stats["session_count"] == 2
        assert stats["total_logs"] == 3
        assert stats["max_logs_per_session"] == 100

    def test_stats_after_clear(self):
        store = AgentLogStore()
        store.add_log(_entry(session_id="s1"))
        store.add_log(_entry(session_id="s2"))
        store.clear_session("s1")
        stats = store.get_stats()
        assert stats["session_count"] == 1
        assert stats["total_logs"] == 1


# ===========================================================================
# AgentLogStore — thread safety
# ===========================================================================

class TestAgentLogStoreThreadSafety:
    def test_concurrent_adds(self):
        """Add entries from multiple threads; all should be recorded."""
        store = AgentLogStore(max_logs_per_session=5000)
        num_threads = 10
        entries_per_thread = 100
        errors = []

        def _add_entries(thread_idx: int):
            try:
                for i in range(entries_per_thread):
                    store.add_log(
                        _entry(
                            session_id="shared",
                            turn_id=f"t_{thread_idx}",
                            event_type=f"evt_{thread_idx}_{i}",
                        )
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_add_entries, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        total = len(store.get_logs("shared"))
        assert total == num_threads * entries_per_thread

    def test_concurrent_add_and_read(self):
        """Reads should not fail while writes happen concurrently."""
        store = AgentLogStore()
        errors = []

        def _writer():
            try:
                for i in range(100):
                    store.add_log(_entry(session_id="s", event_type=f"w_{i}"))
            except Exception as exc:
                errors.append(exc)

        def _reader():
            try:
                for _ in range(100):
                    store.get_logs("s")
                    store.get_recent_logs("s", limit=5)
                    store.get_stats()
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_writer),
            threading.Thread(target=_reader),
            threading.Thread(target=_reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"


# ===========================================================================
# get_agent_log_store singleton
# ===========================================================================

class TestGetAgentLogStore:
    def test_returns_agent_log_store_instance(self):
        store = get_agent_log_store()
        assert isinstance(store, AgentLogStore)

    def test_singleton_returns_same_instance(self):
        s1 = get_agent_log_store()
        s2 = get_agent_log_store()
        assert s1 is s2
