"""Typed failures raised by the pure S4 scalar-field path."""

from __future__ import annotations


class ProcessingError(Exception):
    """Base class for failures within the processing stage."""


class InvalidRequestError(ProcessingError):
    """A processing request is incomplete or internally inconsistent."""


class VariableSelectionError(ProcessingError):
    """The requested scalar variable is missing or unsupported."""


class TimeSelectionError(ProcessingError):
    """The requested time does not identify exactly one source time."""


class GridValidationError(ProcessingError):
    """The supplied data is not an unambiguous rectilinear scalar grid."""


class EmptySubsetError(ProcessingError):
    """Valid bounds selected no source coordinate cells."""


class AllMissingSubsetError(ProcessingError):
    """The selected cells exist but none holds a valid value."""


class PointBudgetError(InvalidRequestError):
    """The requested point budget cannot be applied."""


class WorkLimitError(ProcessingError):
    """The request is valid but selects more cells than this server builds."""


class ManagedDataUnavailableError(ProcessingError):
    """The managed dataset version or variable could not be read.

    Raised by the product builder bound at composition when the configured
    storage read path cannot supply the input; the detail stays inside S3.
    """


class UnknownRequestError(ProcessingError):
    """No request with this identity is known to the executor."""
