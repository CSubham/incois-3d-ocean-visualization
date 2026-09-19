"""The adapter boundary: the service must not know what a source is made of."""

from typing import Any, Optional

import numpy as np
import pytest
import xarray as xr

from ingestion import adapters
from ingestion.domain.errors import SourceError
from ingestion.domain.selection import ImportSelection
from ingestion.ports import (
    DatasetMetadata, DatasetRef, FetchResult, SourceCapabilities,
    SourceDescription, SourcePort, StoragePort,
)
from ingestion.service import IngestionService
from ingestion.storage import RecordingSink


class InventedSource(SourcePort):
    """A source the application has never heard of."""

    def describe(self) -> SourceDescription:
        return SourceDescription(source_id="invented", name="Invented",
                                 kind="remote",
                                 capabilities=SourceCapabilities(
                                     variable_selection=True))

    def list_datasets(self, context: Optional[dict[str, Any]] = None):
        return (DatasetRef(dataset_id="only", name="Only dataset"),)

    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None):
        return DatasetMetadata(dataset_id=dataset_id, name="Only dataset")

    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        dataset = xr.Dataset(
            {"thing": (("lat", "lon"), np.ones((2, 2)), {"units": "m"})},
            coords={"lat": [1.0, 2.0], "lon": [3.0, 4.0],
                    "time": ("time", np.array(["2024-01-01"],
                                              dtype="datetime64[ns]"))})
        return FetchResult(dataset=dataset, location="invented://only")


def test_every_shipped_adapter_satisfies_the_port():
    for description in adapters.available_sources():
        adapter = adapters.resolve(description.source_id)
        assert isinstance(adapter, SourcePort)


def test_unknown_source_is_reported_not_guessed():
    with pytest.raises(SourceError, match="unknown source"):
        adapters.resolve("not_a_source")


def test_service_imports_a_source_it_has_no_knowledge_of(monkeypatch):
    """The whole point of the boundary: a new source needs no service change."""
    monkeypatch.setitem(adapters._BUILDERS, "invented", InventedSource)
    sink = RecordingSink()
    service = IngestionService(storage=sink)

    assert "invented" in [d.source_id for d in service.sources()]
    job = service.start_import(
        ImportSelection(source_id="invented", dataset_id="only"))

    assert job.state.value == "completed", job.message
    assert len(sink.packages) == 1
    assert sink.packages[0].source.source_name == "Invented"


def test_storage_port_receives_a_complete_package(monkeypatch):
    monkeypatch.setitem(adapters._BUILDERS, "invented", InventedSource)
    sink = RecordingSink()
    IngestionService(storage=sink).start_import(
        ImportSelection(source_id="invented", dataset_id="only"))

    package = sink.packages[0]
    assert package.import_id
    assert package.dataset is not None
    assert package.geometry is not None
    assert package.variables
    assert package.coordinates.identified()
    assert package.source.source_id == "invented"
    assert package.selection.dataset_id == "only"
    assert package.validation.passed
    assert package.metadata["dimensions"]


def test_recording_sink_is_a_storage_port():
    assert isinstance(RecordingSink(), StoragePort)
