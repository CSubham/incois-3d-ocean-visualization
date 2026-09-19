"""Where running and finished imports are held.

In-process today. The service treats it as a store, so moving imports onto a
worker with a shared backing store does not change the service or its callers.
"""

from __future__ import annotations

import threading
from typing import Optional

from ingestion.domain.job import ImportJob


class JobStore:
    """A thread-safe registry of imports, newest first."""

    def __init__(self, limit: int = 200) -> None:
        self._jobs: dict[str, ImportJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._limit = limit

    def add(self, job: ImportJob) -> ImportJob:
        with self._lock:
            self._jobs[job.import_id] = job
            self._order.insert(0, job.import_id)
            while len(self._order) > self._limit:
                self._jobs.pop(self._order.pop(), None)
        return job

    def get(self, import_id: str) -> Optional[ImportJob]:
        with self._lock:
            return self._jobs.get(import_id)

    def recent(self, count: int = 20) -> list[ImportJob]:
        with self._lock:
            return [self._jobs[i] for i in self._order[:count]
                    if i in self._jobs]
