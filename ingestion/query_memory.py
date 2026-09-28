"""Public in-memory implementation of the S3 model-field read contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import xarray as xr

from ingestion.query import (
    DatasetVersionSummary, ManagedModelField, ModelFieldDescriptor,
    ModelFieldQuery, NotAModelField, UndeclaredReference,
    VariableUnavailable, VersionNotFound,
)


@dataclass(frozen=True)
class InMemoryDatasetVersion:
    """One immutable registration for tests and local composition."""

    summary: DatasetVersionSummary
    dataset: xr.Dataset
    descriptors: Mapping[str, ModelFieldDescriptor]
    undeclared_references: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "descriptors", MappingProxyType(dict(self.descriptors)))
        object.__setattr__(
            self, "undeclared_references",
            MappingProxyType(dict(self.undeclared_references)),
        )


class InMemoryModelFieldQuery(ModelFieldQuery):
    """A replaceable query fake with the same semantics as the catalogue."""

    def __init__(self,
                 versions: Iterable[InMemoryDatasetVersion] = ()) -> None:
        supplied = tuple(versions)
        registered = {item.summary.id: item for item in supplied}
        if len(registered) != len(supplied):
            raise ValueError("dataset version ids must be unique")
        self._versions = MappingProxyType(registered)

    def list_model_versions(self) -> tuple[DatasetVersionSummary, ...]:
        summaries = [
            item.summary for item in self._versions.values()
            if item.summary.geometry == "grid"
        ]
        return tuple(sorted(
            summaries, key=lambda item: (item.created_at, item.id),
            reverse=True,
        ))

    def describe_version(
            self, dataset_version_id: str) -> DatasetVersionSummary:
        version = self._version(dataset_version_id)
        self._require_grid(version.summary)
        return version.summary

    def open_model_field(
            self, dataset_version_id: str,
            variable: str) -> ManagedModelField:
        version = self._version(dataset_version_id)
        self._require_grid(version.summary)
        if variable in version.undeclared_references:
            raise UndeclaredReference(
                dataset_version_id,
                version.undeclared_references[variable],
            )
        descriptor = version.descriptors.get(variable)
        declared = {item.name for item in version.summary.variables}
        if (descriptor is None or variable not in declared
                or variable not in version.dataset.data_vars):
            raise VariableUnavailable(dataset_version_id, variable)
        dataset = version.dataset[[variable]].copy(deep=False)
        return ManagedModelField(dataset, descriptor)

    def _version(self, dataset_version_id: str) -> InMemoryDatasetVersion:
        try:
            return self._versions[dataset_version_id]
        except KeyError:
            raise VersionNotFound(dataset_version_id) from None

    @staticmethod
    def _require_grid(summary: DatasetVersionSummary) -> None:
        if summary.geometry != "grid":
            raise NotAModelField(summary.id, summary.geometry)


__all__ = ["InMemoryDatasetVersion", "InMemoryModelFieldQuery"]
