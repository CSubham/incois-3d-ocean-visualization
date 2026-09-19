"""Failure modes of the ingestion stage.

Ingestion distinguishes three kinds of failure, because callers react to them
differently: the request was wrong, the source could not be reached or
understood, or the data did not meet the conventions.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for every failure raised inside the ingestion stage."""


class SelectionError(IngestionError):
    """The requested import is not something the source can satisfy."""


class SourceError(IngestionError):
    """A source could not be listed, inspected or retrieved."""


class ConventionError(IngestionError):
    """Retrieved data does not satisfy the conventions required downstream.

    Raised rather than guessed at: an ambiguous dataset is a reportable
    outcome, never something the stage resolves on the data's behalf.
    """
