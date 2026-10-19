"""Result cache keyed by PDF hash plus generation options."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any


def hash_file(data: bytes) -> str:
    """Return a SHA-256 hex digest for cache keys."""
    return hashlib.sha256(data).hexdigest()


def cache_key(file_hash: str, *, max_depth: int, max_branches: int, language: str | None) -> str:
    """Build a cache key.

    The file hash identifies the document; options are included because they
    change the generated tree.
    """
    options = json.dumps(
        {"depth": max_depth, "branches": max_branches, "language": language},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{file_hash}:{options}"


class ResultCache(ABC):
    """Cache interface for completed results."""

    @abstractmethod
    def get(self, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def put(self, key: str, result: dict[str, Any]) -> None: ...


class InMemoryResultCache(ResultCache):
    """Small LRU cache. Lost on restart (documented limitation)."""

    def __init__(self, max_entries: int = 64) -> None:
        self.max_entries = max(1, max_entries)
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        """Return a cached result and refresh its LRU position."""
        value = self._items.get(key)
        if value is None:
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: str, result: dict[str, Any]) -> None:
        """Store a result, evicting the least-recently-used entry if needed."""
        self._items[key] = result
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def clear(self) -> None:
        """Remove all cached results."""
        self._items.clear()
