"""Implementations of the storage port.

The real storage layer (S3) does not exist yet. What lives here is enough to
prove the handoff happens and to let the stage run end to end -- nothing here
is, or pretends to be, durable scientific storage.
"""

from ingestion.storage.sink import DevelopmentSink, RecordingSink

__all__ = ["DevelopmentSink", "RecordingSink"]
