"""The whole workflow, offline.

Source -> dataset -> variables -> range -> import -> parse -> validate ->
canonical package -> storage handoff, driven through a stand-in provider so
no network is involved.
"""

import pytest

from ingestion import adapters
from ingestion.domain.selection import Area, DepthRange, ImportSelection
from ingestion.service import IngestionService
from ingestion.storage import RecordingSink
from ingestion.tests.fakes import GRID, PROFILES, UNREADABLE, FakeSource


@pytest.fixture()
def running(monkeypatch):
    source = FakeSource()
    monkeypatch.setitem(adapters._BUILDERS, source.source_id, lambda: source)
    sink = RecordingSink()
    return IngestionService(storage=sink), sink, source


def _select(dataset_id, **kwargs) -> ImportSelection:
    return ImportSelection(source_id=FakeSource.source_id,
                           dataset_id=dataset_id, **kwargs)


def test_a_new_source_needs_no_change_to_the_service(running):
    service, _, _ = running
    assert FakeSource.source_id in [d.source_id for d in service.sources()]
    assert len(service.datasets(FakeSource.source_id)) == 3


def test_inspecting_reports_variables_and_ranges(running):
    metadata = running[0].inspect(FakeSource.source_id, GRID)
    assert {v.name for v in metadata.variables} == {"temperature", "salinity"}
    assert {r.role for r in metadata.ranges} == {"vertical", "latitude"}


def test_gridded_data_reaches_storage_with_its_shape_intact(running):
    service, sink, _ = running
    job = service.start_import(_select(
        GRID, variables=("temperature",), depth=DepthRange(0, 50)))

    assert job.state.value == "completed", job.message
    package = sink.packages[0]
    assert package.geometry.value == "grid"
    assert [v.name for v in package.variables] == ["temperature"]
    assert package.dataset.sizes["depth"] == 3        # the range was applied
    assert package.variables[0].units == "degC"
    assert package.coordinates.identified() == {
        "time": "time", "vertical": "depth",
        "latitude": "lat", "longitude": "lon"}


def test_observations_are_not_flattened_into_a_grid(running):
    service, sink, _ = running
    job = service.start_import(_select(PROFILES))
    assert job.state.value == "completed", job.message
    assert sink.packages[0].geometry.value == "profile"
    assert "observation" in sink.packages[0].dataset.sizes


def test_the_selection_is_what_the_adapter_receives(running):
    service, _, source = running
    service.start_import(_select(
        GRID, variables=("salinity",), depth=DepthRange(0, 10),
        area=Area(west=70, east=80, south=0, north=10)))

    received = source.fetches[0]
    assert received.variables == ("salinity",)
    assert received.depth.maximum == 10
    assert received.area.north == 10


def test_data_that_cannot_be_interpreted_never_reaches_storage(running):
    service, sink, _ = running
    job = service.start_import(_select(UNREADABLE))

    assert job.state.value == "failed"
    assert "units" in job.message
    assert sink.packages == []
    assert job.result["validation"]["problems"]


def test_asking_for_a_variable_that_is_not_there_is_reported(running):
    service, sink, _ = running
    job = service.start_import(_select(GRID, variables=("nonsense",)))
    assert job.state.value == "failed"
    assert "nonsense" in job.message
    assert sink.packages == []


def test_an_unknown_dataset_fails_without_raising(running):
    job = running[0].start_import(_select("no_such_dataset"))
    assert job.state.value == "failed"


def test_a_finished_job_can_be_looked_up_again(running):
    service, _, _ = running
    job = service.start_import(_select(GRID))
    assert service.job(job.import_id) is job
    assert service.recent_jobs()[0].import_id == job.import_id


def test_the_package_carries_everything_storage_needs(running):
    service, sink, _ = running
    service.start_import(_select(GRID, variables=("temperature",)))
    package = sink.packages[0]

    assert package.import_id
    assert package.dataset is not None
    assert package.geometry is not None
    assert package.variables
    assert package.coordinates.identified()
    assert package.source.source_id == FakeSource.source_id
    assert package.source.location.startswith("fake://")
    assert package.selection.dataset_id == GRID
    assert package.validation.passed
    assert package.metadata["dimensions"]
