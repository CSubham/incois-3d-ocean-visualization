"""Live S2→S3→S4 proof against local PostGIS and bounded real sources."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import psycopg
import pytest
from psycopg.rows import dict_row

from ingestion.composition import build_model_field_query
from ingestion.domain.job import ImportState
from ingestion.domain.selection import (
    Area, DepthRange, ImportSelection, TimeRange,
)
from ingestion.query_memory import InMemoryDatasetVersion
from ingestion.service import IngestionService
from ingestion.storage.objects import LocalObjectStore
from ingestion.storage.postgres import PostgresStorage
from ingestion.tests.query_support import (
    live_dsn_status, rebuild_live_catalogue,
)
from processing import (
    DepthBounds, GeographicBounds, SamplingRequest, ScalarSelection,
)
from processing.managed import prepare_managed_scalar_point_field


LIVE_DSN, LIVE_SKIP_REASON = live_dsn_status()
pytestmark = [
    pytest.mark.live,
    pytest.mark.network,
    pytest.mark.skipif(
        LIVE_SKIP_REASON is not None,
        reason=LIVE_SKIP_REASON or "local PostGIS is unavailable",
    ),
]


@dataclass(frozen=True)
class LiveProof:
    dsn: str
    object_root: str
    objects: LocalObjectStore
    model_version_id: str
    profile_version_id: str
    model_reference: str
    profile_reference: str
    schema_evidence: dict


@pytest.fixture(scope="module")
def live_proof(tmp_path_factory) -> LiveProof:
    assert LIVE_DSN is not None
    schema_evidence = dict(rebuild_live_catalogue(LIVE_DSN))
    object_root = tmp_path_factory.mktemp("live-query-objects")
    objects = LocalObjectStore(object_root)
    service = IngestionService(PostgresStorage(LIVE_DSN, objects))

    model_job = service.start_import(ImportSelection(
        source_id="hycom_opendap",
        dataset_id="GLBy0.08_expt_93.0",
        variables=("water_temp",),
        time=TimeRange(
            "2024-09-05T09:00:00Z", "2024-09-05T09:00:00Z"),
        depth=DepthRange(0.0, 10.0),
        area=Area(west=79.8, east=80.0, south=9.0, north=9.2),
    ))
    assert model_job.state is ImportState.COMPLETED, model_job.message

    profile_job = service.start_import(ImportSelection(
        source_id="incois_erddap",
        dataset_id="Indian_ARGO_Floats",
        variables=("TEMP",),
        time=TimeRange(
            "2025-04-23T13:28:00Z", "2025-04-23T13:28:00Z"),
        depth=DepthRange(0.0, 10.0),
    ))
    assert profile_job.state is ImportState.COMPLETED, profile_job.message

    assert model_job.receipt is not None
    assert profile_job.receipt is not None
    return LiveProof(
        dsn=LIVE_DSN,
        object_root=str(object_root),
        objects=objects,
        model_version_id=model_job.import_id,
        profile_version_id=profile_job.import_id,
        model_reference=str(model_job.receipt["reference"]),
        profile_reference=str(profile_job.receipt["reference"]),
        schema_evidence=schema_evidence,
    )


def test_live_real_sources_persist_query_spatially_and_feed_s4(live_proof):
    environ = {
        "S3_QUERY_BACKEND": "catalogue",
        "INGESTION_CATALOGUE_DSN": live_proof.dsn,
        "INGESTION_OBJECT_STORE": live_proof.object_root,
    }
    catalogue_query = build_model_field_query(environ=environ)

    with live_proof.objects.open(live_proof.model_reference) as stored:
        expected = stored.load().copy(deep=True)
    expected_field = expected["water_temp"]
    expected_mask = np.isnan(expected_field.values)
    assert expected_mask.any()
    assert (~expected_mask).any()

    first = catalogue_query.open_model_field(
        live_proof.model_version_id, "water_temp")
    with first as managed:
        assert managed.dataset["water_temp"].variable._in_memory is False
        first_values = managed.dataset["water_temp"].values.copy()
        first_mask = np.isnan(first_values)
        np.testing.assert_allclose(
            first_values, expected_field.values, equal_nan=True)
        np.testing.assert_array_equal(first_mask, expected_mask)
        for name in ("time", "depth", "lat", "lon"):
            np.testing.assert_array_equal(
                managed.dataset[name].values, expected[name].values)
        descriptor = managed.descriptor
        assert descriptor.dataset_version_id == live_proof.model_version_id
        assert descriptor.dataset_id == "GLBy0.08_expt_93.0"
        assert descriptor.variable == "water_temp"
        assert descriptor.units == "degC"
        assert descriptor.time_coordinate == "time"
        assert descriptor.depth_coordinate == "depth"
        assert descriptor.latitude_coordinate == "lat"
        assert descriptor.longitude_coordinate == "lon"
        assert descriptor.crs == "EPSG:4326"
        assert descriptor.vertical_positive == "down"
        public_text = repr((managed.dataset, descriptor))
        assert live_proof.dsn not in public_text
        assert live_proof.model_reference not in public_text
        assert live_proof.object_root not in public_text
    assert first.closed

    with catalogue_query.open_model_field(
            live_proof.model_version_id, "water_temp") as second:
        np.testing.assert_allclose(
            second.dataset["water_temp"].values,
            first_values,
            equal_nan=True,
        )

    with live_proof.objects.open(live_proof.profile_reference) as profile:
        assert profile.sizes["observation"] == 8
        assert set(profile["PLATFORM_NUMBER"].values.astype(str)) == {
            "7902250"
        }
        assert set(profile["CYCLE_NUMBER"].values.astype(str)) == {"12"}
        profile_longitude = float(profile["longitude"].values[0])
        profile_latitude = float(profile["latitude"].values[0])
        assert -180.0 <= profile_longitude <= 180.0
        np.testing.assert_allclose(
            profile["PRES"].values,
            [2.5, 3.5, 4.5, 5.5, 6.5, 7.6, 8.5, 9.4],
        )
        assert profile["TEMP"].attrs["units"] == "degree_Celsius"

    with psycopg.connect(
            live_proof.dsn, row_factory=dict_row) as connection:
        versions = connection.execute(
            "SELECT import_id, geometry, object_ref FROM dataset_version "
            "ORDER BY import_id"
        ).fetchall()
        variables = connection.execute(
            "SELECT import_id, name, units FROM dataset_variable "
            "ORDER BY import_id, name"
        ).fetchall()
        profiles = connection.execute(
            """
            SELECT import_id, platform_id, cycle, measurements,
                   representative_source_index,
                   ST_X(position::geometry) AS longitude,
                   ST_Y(position::geometry) AS latitude
            FROM observation_profile
            WHERE ST_Intersects(
                position,
                ST_MakeEnvelope(85.0, -2.0, 86.0, -1.0, 4326)::geography
            )
            """
        ).fetchall()
    assert {row["import_id"] for row in versions} == {
        live_proof.model_version_id, live_proof.profile_version_id,
    }
    assert {row["name"] for row in variables
            if row["import_id"] == live_proof.model_version_id} == {
        "water_temp"
    }
    assert len(profiles) == 1
    assert profiles[0]["import_id"] == live_proof.profile_version_id
    assert profiles[0]["platform_id"] == "7902250"
    assert profiles[0]["cycle"] == "12"
    assert profiles[0]["measurements"] == 8
    assert profiles[0]["representative_source_index"] == 0
    assert profiles[0]["longitude"] == pytest.approx(profile_longitude)
    assert profiles[0]["latitude"] == pytest.approx(profile_latitude)

    scalar_selection = ScalarSelection(
        variable="water_temp",
        time=expected["time"].values[0],
        area=GeographicBounds(
            west=float(expected["lon"].values.min()),
            east=float(expected["lon"].values.max()),
            south=float(expected["lat"].values.min()),
            north=float(expected["lat"].values.max()),
        ),
        depth=DepthBounds(
            minimum=float(expected["depth"].values.min()),
            maximum=float(expected["depth"].values.max()),
        ),
    )
    sampling = SamplingRequest(maximum_points=17)
    catalogue_product = prepare_managed_scalar_point_field(
        catalogue_query,
        live_proof.model_version_id,
        scalar_selection,
        sampling,
    )
    assert catalogue_product.points.values.size == 17
    assert catalogue_product.identity.dataset_version_id == (
        live_proof.model_version_id)

    summary = catalogue_query.describe_version(live_proof.model_version_id)
    with catalogue_query.open_model_field(
            live_proof.model_version_id, "water_temp") as opened:
        memory_version = InMemoryDatasetVersion(
            summary=summary,
            dataset=opened.dataset.load().copy(deep=True),
            descriptors={"water_temp": opened.descriptor},
        )
    memory_query = build_model_field_query(
        environ={"S3_QUERY_BACKEND": "memory"},
        memory_versions=(memory_version,),
    )
    memory_product = prepare_managed_scalar_point_field(
        memory_query,
        live_proof.model_version_id,
        scalar_selection,
        sampling,
    )
    np.testing.assert_allclose(
        memory_product.points.values,
        catalogue_product.points.values,
        equal_nan=True,
    )
    np.testing.assert_array_equal(
        memory_product.points.missing_value_mask,
        catalogue_product.points.missing_value_mask,
    )
    np.testing.assert_array_equal(
        memory_product.points.longitude,
        catalogue_product.points.longitude,
    )
    assert memory_product.identity == catalogue_product.identity
    assert live_proof.schema_evidence["postgis"]
