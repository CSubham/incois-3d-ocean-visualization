"""The contracts themselves: what may and may not be constructed."""

import pytest
import xarray as xr

from ingestion.domain.errors import SelectionError
from ingestion.domain.package import (
    CanonicalPackage, CoordinateSet, DatasetGeometry, SourceInfo, VariableSpec,
)
from ingestion.domain.job import ImportJob, ImportState
from ingestion.domain.selection import (
    Area, DepthRange, ImportSelection, TimeRange,
)
from ingestion.domain.validation import ValidationIssue, ValidationResult


def _selection() -> ImportSelection:
    return ImportSelection(source_id="s", dataset_id="d")


def _package(**overrides) -> CanonicalPackage:
    defaults = dict(
        import_id="abc",
        dataset=xr.Dataset(),
        geometry=DatasetGeometry.GRID,
        variables=(VariableSpec(name="t", original_name="t", units="degC"),),
        coordinates=CoordinateSet(latitude="lat", longitude="lon"),
        source=SourceInfo(source_id="s", source_name="S", dataset_id="d",
                          dataset_name="D", kind="local"),
        selection=_selection(),
        validation=ValidationResult(checks_run=("a",)),
    )
    defaults.update(overrides)
    return CanonicalPackage(**defaults)


def test_selection_requires_a_source_and_dataset():
    with pytest.raises(SelectionError):
        ImportSelection(source_id="", dataset_id="d")
    with pytest.raises(SelectionError):
        ImportSelection(source_id="s", dataset_id="")


def test_selection_reports_which_ranges_were_asked_for():
    selection = ImportSelection(
        source_id="s", dataset_id="d", variables=("a",),
        time=TimeRange("2024-01-01", "2024-01-02"),
        depth=DepthRange(0, 10), area=Area(1, 2, 3, 4))
    assert all(selection.requested_ranges().values())
    assert not any(_selection().requested_ranges().values())


def test_validation_result_passes_only_without_issues():
    assert ValidationResult(checks_run=("a",)).passed
    failed = ValidationResult(checks_run=("a",),
                              issues=(ValidationIssue("a", "no units"),))
    assert not failed.passed
    assert "no units" in failed.summary()


def test_package_cannot_be_built_without_variables():
    with pytest.raises(ValueError, match="no variables"):
        _package(variables=())


def test_package_cannot_be_built_from_failed_validation():
    failed = ValidationResult(checks_run=("a",),
                              issues=(ValidationIssue("a", "bad"),))
    with pytest.raises(ValueError, match="failed validation"):
        _package(validation=failed)


def test_package_describes_itself_without_the_dataset():
    described = _package().describe()
    assert described["geometry"] == "grid"
    assert described["validation"]["passed"] is True
    assert "dataset" not in described


def test_job_reports_terminal_states_and_messages():
    job = ImportJob(selection=_selection())
    assert not job.describe()["done"]
    job.advance(ImportState.IMPORTING)
    assert job.message == "Retrieving data."
    job.fail("source unreachable")
    assert job.describe()["done"] and not job.describe()["ok"]
    assert job.message == "source unreachable"
