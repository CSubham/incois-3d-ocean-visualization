"""Import lifecycle.

An import is a job with states, not a single blocking call. The current
execution is synchronous and in-process, but the model is what allows a
long-running import to be moved onto a worker without changing callers: the UI
already polls a job rather than waiting on a response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from ingestion.domain.selection import ImportSelection


class ImportState(str, Enum):
    CREATED = "created"
    INSPECTING = "inspecting"
    READY = "ready"
    IMPORTING = "importing"
    VALIDATING = "validating"
    HANDING_OFF = "handing_off"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in (ImportState.COMPLETED, ImportState.FAILED)


#: What the user is told while a job is in each state. Kept here so the UI
#: never has to translate internal state names itself.
STATE_MESSAGES: dict[ImportState, str] = {
    ImportState.CREATED: "Import requested.",
    ImportState.INSPECTING: "Checking the source.",
    ImportState.READY: "Ready to import.",
    ImportState.IMPORTING: "Retrieving data.",
    ImportState.VALIDATING: "Checking the data.",
    ImportState.HANDING_OFF: "Saving.",
    ImportState.COMPLETED: "Imported successfully.",
    ImportState.FAILED: "Import failed.",
}


@dataclass
class ImportJob:
    """One import, tracked from request to outcome."""

    selection: ImportSelection
    import_id: str = field(default_factory=lambda: uuid4().hex[:12])
    state: ImportState = ImportState.CREATED
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    receipt: Optional[dict[str, Any]] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))

    def advance(self, state: ImportState) -> None:
        self.state = state
        self.updated_at = datetime.now(timezone.utc)

    def fail(self, reason: str) -> None:
        self.error = reason
        self.advance(ImportState.FAILED)

    @property
    def message(self) -> str:
        if self.state is ImportState.FAILED and self.error:
            return self.error
        return STATE_MESSAGES[self.state]

    def describe(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "state": self.state.value,
            "message": self.message,
            "done": self.state.terminal,
            "ok": self.state is ImportState.COMPLETED,
            "result": self.result,
            "receipt": self.receipt,
            "updated_at": self.updated_at.isoformat(),
        }
