"""The outcome of checking retrieved data against the required conventions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidationIssue:
    """One reason a dataset cannot be handed on as it stands."""

    check: str
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    """Which checks ran, and what they found.

    `passed` is derived, never set independently: a result with issues is not
    a passing result.
    """

    checks_run: tuple[str, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if self.passed:
            return f"{len(self.checks_run)} checks passed"
        return "; ".join(f"{issue.check}: {issue.detail}" for issue in self.issues)
