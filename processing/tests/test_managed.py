"""Tests for the additive S3-to-S4 managed-field handoff."""

from __future__ import annotations

import numpy as np
import pytest

from ingestion.composition import build_model_field_query
from ingestion.query import ManagedModelField, ModelFieldQuery
from ingestion.query_memory import InMemoryModelFieldQuery
from ingestion.storage.query import CatalogueModelFieldQuery
from ingestion.tests.query_support import MODEL_VERSION_ID, in_memory_case
from processing import (
    DepthBounds, DepthSliceSelection, GeographicBounds, SamplingRequest,
    ScalarSelection, TimeSelectionError,
)
from processing.managed import (
    ManagedDepthSliceRequest, managed_depth_slice_builder,
    prepare_managed_scalar_point_field, scalar_grid_descriptor,
)


def _selection(time=None) -> ScalarSelection:
    return ScalarSelection(
        variable="water_temp",
        time=(np.datetime64("2026-09-28T00:00:00", "ns")
              if time is None else time),
        area=GeographicBounds(
            west=72.0, east=75.0, south=8.0, north=9.0),
        depth=DepthBounds(minimum=0.0, maximum=20.0),
    )


def test_handoff_maps_the_s3_descriptor_and_calls_existing_processing():
    case = in_memory_case()
    with case.query.open_model_field(
            MODEL_VERSION_ID, "water_temp") as managed:
        mapped = scalar_grid_descriptor(managed.descriptor)
    assert mapped.identity.dataset_id == "GLBy0.08_expt_93.0"
    assert mapped.identity.dataset_version_id == MODEL_VERSION_ID
    assert mapped.coordinates.depth == "depth"
    assert mapped.spatial_reference.crs == "EPSG:4326"
    assert mapped.spatial_reference.vertical_positive == "down"

    product = prepare_managed_scalar_point_field(
        case.query,
        MODEL_VERSION_ID,
        _selection(),
        SamplingRequest(maximum_points=7),
    )
    assert product.identity.dataset_version_id == MODEL_VERSION_ID
    assert product.identity.variable == "water_temp"
    assert product.variable_units == "degree_Celsius"
    assert product.points.values.size == 7
    assert product.provenance["source"]["id"] == "hycom_opendap"


def test_handoff_closes_the_managed_field_when_processing_fails():
    case = in_memory_case()
    closes = []

    class TrackingQuery(ModelFieldQuery):
        def list_model_versions(self):
            return case.query.list_model_versions()

        def describe_version(self, dataset_version_id):
            return case.query.describe_version(dataset_version_id)

        def open_model_field(self, dataset_version_id, variable):
            opened = case.query.open_model_field(dataset_version_id, variable)
            return ManagedModelField(
                opened.dataset,
                opened.descriptor,
                close=lambda: closes.append("closed"),
            )

    with pytest.raises(TimeSelectionError):
        prepare_managed_scalar_point_field(
            TrackingQuery(),
            MODEL_VERSION_ID,
            _selection(np.datetime64("2030-01-01", "ns")),
            SamplingRequest(maximum_points=5),
        )
    assert closes == ["closed"]


def test_composition_selects_the_backend_only_from_configuration(tmp_path):
    memory = build_model_field_query(
        environ={"S3_QUERY_BACKEND": "memory"},
    )
    catalogue = build_model_field_query(environ={
        "S3_QUERY_BACKEND": "catalogue",
        "INGESTION_CATALOGUE_DSN": "postgresql://example.invalid/catalogue",
        "INGESTION_OBJECT_STORE": str(tmp_path),
    })
    assert isinstance(memory, InMemoryModelFieldQuery)
    assert isinstance(catalogue, CatalogueModelFieldQuery)


def test_composition_rejects_an_unknown_backend():
    with pytest.raises(ValueError, match="catalogue.*memory"):
        build_model_field_query(environ={"S3_QUERY_BACKEND": "mystery"})


def _request(variable="water_temp", version=MODEL_VERSION_ID, points=10):
    from processing import ProductRequest
    return ProductRequest(
        dataset_version_id=version,
        selection=ScalarSelection(
            variable=variable, time=_selection().time,
            area=_selection().area, depth=_selection().depth),
        sampling=SamplingRequest(maximum_points=points))


def test_the_managed_builder_runs_behind_the_executor():
    from processing import JobState, LocalExecutor
    from processing.managed import managed_point_field_builder

    executor = LocalExecutor(managed_point_field_builder(in_memory_case().query),
                             maximum_points=100, maximum_cells=10_000)
    job = executor.submit(_request())

    assert job.state is JobState.SUCCEEDED, job.failure
    assert job.product.identity.dataset_version_id == MODEL_VERSION_ID


def test_the_managed_builder_honours_the_work_ceiling_before_reading():
    from processing import LocalExecutor
    from processing.managed import managed_point_field_builder

    job = LocalExecutor(managed_point_field_builder(in_memory_case().query),
                        maximum_points=100, maximum_cells=1).submit(_request())

    assert job.failure.code == "work_limit"


def test_managed_depth_slice_builder_uses_the_s3_field_boundary():
    builder = managed_depth_slice_builder(in_memory_case().query)

    product = builder(ManagedDepthSliceRequest(
        dataset_version_id=MODEL_VERSION_ID,
        selection=DepthSliceSelection(
            variable="water_temp",
            time=np.datetime64("2026-09-28T00:00:00", "ns"),
            area=GeographicBounds(
                west=72.0, east=75.0, south=8.0, north=9.0),
            depth=10.0,
        ),
        maximum_cells=100,
    ))

    assert product.identity.dataset_version_id == MODEL_VERSION_ID
    assert product.interpolation.source_depth_indices == (1,)
    assert product.data.values.shape == (2, 4)


@pytest.mark.parametrize("request_kwargs, code", [
    ({"version": "no-such-version"}, "data_unavailable"),
    ({"variable": "chlorophyll"}, "variable_unavailable"),
])
def test_s3_read_failures_become_actionable_codes(request_kwargs, code):
    from processing import LocalExecutor
    from processing.managed import managed_point_field_builder

    job = LocalExecutor(managed_point_field_builder(in_memory_case().query),
                        maximum_points=100, maximum_cells=10_000
                        ).submit(_request(**request_kwargs))

    assert job.failure.code == code
