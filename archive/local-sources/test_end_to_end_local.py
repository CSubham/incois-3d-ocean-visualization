"""The whole workflow, against the repository's real sample data.

Source -> dataset -> variables -> range -> import -> parse -> validate ->
canonical package -> storage handoff.
"""

import pytest

from ingestion import local_paths
from ingestion.domain.errors import SourceError
from ingestion.domain.selection import Area, DepthRange, ImportSelection
from ingestion.service import IngestionService
from ingestion.storage import RecordingSink

HYCOM = "data:model/hycom_glby008_expt930/indian_ocean_ts_sample.nc"
ARGO = "data:obs/incois_argo_floats/indian_ocean_sample.csv"
GLIDER = "data:obs/ioos_glider_ru29/bay_of_bengal_sample.csv"
BROKEN = "data:model/incois_valueadded_currents/indian_ocean_sample.nc"


@pytest.fixture()
def service() -> tuple[IngestionService, RecordingSink]:
    sink = RecordingSink()
    return IngestionService(storage=sink), sink


def test_sources_are_offered_remote_first(service):
    described = service[0].sources()
    assert described[0].kind == "remote"
    assert {d.source_id for d in described} >= {
        "incois_erddap", "local_netcdf", "local_delimited", "local_folder"}


def test_a_folder_lists_only_what_can_be_imported(service):
    found = service[0].datasets(
        "local_netcdf",
        {"root_id": "data", "path": "model/hycom_glby008_expt930"})
    assert {ref.name for ref in found} == {
        "indian_ocean_ts_sample.nc", "indian_ocean_uv_sample.nc"}


def test_inspecting_a_file_lists_variables_and_ranges(service):
    metadata = service[0].inspect("local_netcdf", HYCOM)
    assert {v.name for v in metadata.variables} == {"water_temp", "salinity"}
    assert {r.role for r in metadata.ranges} == {
        "time", "vertical", "latitude", "longitude"}


def test_gridded_import_reaches_storage_with_its_structure_intact(service):
    ingestion, sink = service
    job = ingestion.start_import(ImportSelection(
        source_id="local_netcdf", dataset_id=HYCOM,
        variables=("water_temp",), depth=DepthRange(0, 100),
        area=Area(west=70, east=80, south=6, north=15)))

    assert job.state.value == "completed", job.message
    package = sink.packages[0]
    assert package.geometry.value == "grid"
    assert [v.name for v in package.variables] == ["water_temp"]
    assert package.dataset.sizes["depth"] < 20     # the range was applied
    assert package.dataset.sizes["lat"] < 88
    assert package.variables[0].units == "degC"
    assert package.variables[0].standard_name == "sea_water_temperature"


def test_observation_import_keeps_its_own_shape(service):
    ingestion, sink = service
    job = ingestion.start_import(ImportSelection(
        source_id="local_delimited", dataset_id=ARGO,
        variables=("TEMP", "PSAL"), depth=DepthRange(0, 500)))

    assert job.state.value == "completed", job.message
    package = sink.packages[0]
    assert package.geometry.value == "profile"
    assert "observation" in package.dataset.sizes
    assert package.variables[0].units == "degree_Celsius"


def test_a_moving_platform_is_not_flattened_into_a_profile(service):
    ingestion, sink = service
    job = ingestion.start_import(ImportSelection(
        source_id="local_delimited", dataset_id=GLIDER))
    assert job.state.value == "completed", job.message
    assert sink.packages[0].geometry.value == "trajectory_profile"


def test_the_folder_source_routes_a_file_to_the_right_reader(service):
    ingestion, sink = service
    for dataset_id in (HYCOM, ARGO):
        job = ingestion.start_import(ImportSelection(
            source_id="local_folder", dataset_id=dataset_id))
        assert job.state.value == "completed", job.message
    assert {p.geometry.value for p in sink.packages} == {"grid", "profile"}


def test_data_that_cannot_be_interpreted_never_reaches_storage(service):
    ingestion, sink = service
    job = ingestion.start_import(ImportSelection(
        source_id="local_netcdf", dataset_id=BROKEN))

    assert job.state.value == "failed"
    assert "units" in job.message
    assert sink.packages == []
    problems = job.result["validation"]["problems"]
    assert any("GEO_U" in problem["detail"] for problem in problems)


def test_an_unreadable_selection_fails_without_raising(service):
    job = service[0].start_import(ImportSelection(
        source_id="local_netcdf", dataset_id="data:does/not/exist.nc"))
    assert job.state.value == "failed"
    assert service[1].packages == []


def test_selection_outside_an_allowed_location_is_refused():
    with pytest.raises(SourceError, match="outside the allowed location"):
        local_paths.resolve("data", "../../../etc/passwd")


def test_asking_for_a_variable_that_is_not_there_is_reported(service):
    job = service[0].start_import(ImportSelection(
        source_id="local_netcdf", dataset_id=HYCOM, variables=("nonsense",)))
    assert job.state.value == "failed"
    assert "nonsense" in job.message
