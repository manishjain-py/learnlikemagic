"""Unit tests for VisualPreviewStore — TTL, cap, id isolation."""
import time

import pytest

from book_ingestion_v2.services import visual_preview_store
from book_ingestion_v2.services.visual_preview_store import (
    MAX_ENTRIES,
    VisualPreviewStore,
    get_preview_store,
)


@pytest.fixture(autouse=True)
def fresh_store():
    # Reset singleton + any direct instances per-test.
    visual_preview_store._singleton = None
    yield
    visual_preview_store._singleton = None


class TestPutAndGet:
    def test_put_returns_different_ids_for_different_payloads(self):
        store = VisualPreviewStore()
        id1 = store.put("code A", "static_visual")
        id2 = store.put("code B", "animated_visual")
        assert id1 != id2

    def test_get_returns_original_payload(self):
        store = VisualPreviewStore()
        pid = store.put("my pixi code", "static_visual")
        entry = store.get(pid)
        assert entry is not None
        assert entry.code == "my pixi code"
        assert entry.output_type == "static_visual"

    def test_get_unknown_id_returns_none(self):
        store = VisualPreviewStore()
        assert store.get("not-a-real-id") is None

    def test_ids_are_url_safe(self):
        store = VisualPreviewStore()
        pid = store.put("x", "static_visual")
        # token_urlsafe output is [A-Za-z0-9_-]
        for ch in pid:
            assert ch.isalnum() or ch in "-_"


class TestTTL:
    def test_entry_expires_after_ttl(self, monkeypatch):
        store = VisualPreviewStore()
        # Use a tiny TTL for the test
        monkeypatch.setattr(visual_preview_store, "TTL_SECONDS", 0.05)
        pid = store.put("x", "static_visual")
        assert store.get(pid) is not None
        time.sleep(0.1)
        assert store.get(pid) is None

    def test_fresh_entry_survives(self):
        store = VisualPreviewStore()
        pid = store.put("x", "static_visual")
        # No wait — should still be there on the next call.
        assert store.get(pid) is not None


class TestCapacity:
    def test_max_entries_enforced_via_lru_eviction(self, monkeypatch):
        # Shrink cap for tractable tests
        monkeypatch.setattr(visual_preview_store, "MAX_ENTRIES", 3)
        store = VisualPreviewStore()
        # Put 4 entries at distinct times; oldest must be evicted.
        ids = []
        base = time.time()
        for i in range(3):
            # Spoof created_at so eviction is deterministic
            pid = store.put(f"code-{i}", "static_visual")
            store._entries[pid].created_at = base + i
            ids.append(pid)
        # Current size == 3
        assert store.size() == 3
        # Add a 4th — oldest (ids[0]) should evict
        new_pid = store.put("code-new", "static_visual")
        assert store.size() == 3
        assert store.get(ids[0]) is None      # evicted
        assert store.get(ids[1]) is not None  # survivors
        assert store.get(ids[2]) is not None
        assert store.get(new_pid) is not None


class TestSingleton:
    def test_get_preview_store_returns_same_instance(self):
        a = get_preview_store()
        b = get_preview_store()
        assert a is b

    def test_singleton_survives_across_calls(self):
        a = get_preview_store()
        pid = a.put("code", "static_visual")
        b = get_preview_store()
        assert b.get(pid) is not None
