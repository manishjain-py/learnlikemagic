"""Short-lived in-memory store mapping random ids to pixi code.

Used by the Visual Rendering Review pipeline:
 1. Harness calls POST /admin/v2/visual-preview/prepare with the code -> gets an id
 2. Harness navigates Playwright to /admin/visual-render-preview/{id}
 3. The admin page fetches GET /admin/v2/visual-preview/{id} to load the code
 4. Entry expires after TTL_SECONDS or on LRU eviction at MAX_ENTRIES

No DB — lost on process restart, which is fine because these are per-job
ephemerals. Closes the reflected-XSS vector of carrying executable pixi
code in a URL query param.
"""
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Optional


TTL_SECONDS = 120        # Enough for Playwright launch + navigation + render
MAX_ENTRIES = 256        # Cap memory; LRU eviction if exceeded


@dataclass
class PreviewEntry:
    code: str
    output_type: str
    created_at: float


class VisualPreviewStore:
    """Thread-safe singleton. One instance per process."""

    def __init__(self) -> None:
        self._entries: dict[str, PreviewEntry] = {}
        self._lock = Lock()

    def put(self, code: str, output_type: str) -> str:
        """Store code under a random 32-char id. Returns the id."""
        with self._lock:
            self._expire_locked()
            if len(self._entries) >= MAX_ENTRIES:
                # Evict oldest entry
                oldest_id = min(self._entries, key=lambda k: self._entries[k].created_at)
                self._entries.pop(oldest_id, None)
            preview_id = secrets.token_urlsafe(24)
            self._entries[preview_id] = PreviewEntry(
                code=code, output_type=output_type, created_at=time.time(),
            )
            return preview_id

    def get(self, preview_id: str) -> Optional[PreviewEntry]:
        """Returns None if id is unknown or entry has expired."""
        with self._lock:
            self._expire_locked()
            return self._entries.get(preview_id)

    def size(self) -> int:
        """Current (non-expired) entry count. For tests + diagnostics."""
        with self._lock:
            self._expire_locked()
            return len(self._entries)

    def clear(self) -> None:
        """Reset the store. Test-only."""
        with self._lock:
            self._entries.clear()

    def _expire_locked(self) -> None:
        cutoff = time.time() - TTL_SECONDS
        stale = [k for k, v in self._entries.items() if v.created_at < cutoff]
        for k in stale:
            self._entries.pop(k, None)


_singleton: Optional[VisualPreviewStore] = None


def get_preview_store() -> VisualPreviewStore:
    """Return the process-wide singleton, creating it lazily."""
    global _singleton
    if _singleton is None:
        _singleton = VisualPreviewStore()
    return _singleton
