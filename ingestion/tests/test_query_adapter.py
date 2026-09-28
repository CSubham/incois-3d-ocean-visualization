"""Network-free tests for catalogue descriptor resolution and privacy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestion.config import ModelSourceReference
from ingestion.query import (
    ModelFieldQueryError, UndeclaredReference, VariableUnavailable,
)
from ingestion.storage.query import CatalogueModelFieldQuery
from ingestion.tests.query_support import MODEL_VERSION_ID, model_dataset


OBJECT_REFERENCE = "private/model-version-1.nc"
SECRET_DSN = "postgresql://private-secret"


def _version(**changes):
    value = {
        "import_id": MODEL_VERSION_ID,
        "source_id": "hycom_opendap",
        "source_name": "HYCOM",
        "dataset_id": "GLBy0.08_expt_93.0",
        "dataset_name": "HYCOM GLBy0.08 global analysis",
        "source_kind": "remote",
        "geometry": "grid",
        "object_ref": OBJECT_REFERENCE,
        "sizes": {"time": 1, "depth": 3, "lat": 2, "lon": 4},
        "selection": {"variables": ["water_temp"]},
        "validation": {"passed": True},
        "metadata": {
            "coordinate_names": {
                "time": "time", "vertical": "depth",
                "latitude": "lat", "longitude": "lon",
            },
            "global_attributes": {
                "title": "model",
                "cache_path": "/private/cache/model.nc",
            },
        },
        "source_details": {
            "provider": "fixture",
            "provider_code": "NOAA/NCEI",
            "request_url": "https://example.invalid/model",
            "download_path": "/private/download/model.nc",
            "catalogue": "postgresql://private-secret/catalogue",
        },
        "time_values": ["2026-09-28T00:00:00.000000000"],
        "depth_values": [0.0, 10.0, 20.0],
        "time_start": datetime(2026, 9, 28, tzinfo=timezone.utc),
        "time_end": datetime(2026, 9, 28, tzinfo=timezone.utc),
        "depth_min": 0.0,
        "depth_max": 20.0,
        "west": 72.0,
        "east": 75.0,
        "south": 8.0,
        "north": 9.0,
        "created_at": datetime(2026, 9, 28, tzinfo=timezone.utc),
    }
    value.update(changes)
    return value


def _variables():
    return [
        {
            "import_id": MODEL_VERSION_ID,
            "name": "water_temp",
            "units": "degree_Celsius",
            "standard_name": "sea_water_temperature",
        },
        {
            "import_id": MODEL_VERSION_ID,
            "name": "salinity",
            "units": "1e-3",
            "standard_name": "sea_water_salinity",
        },
    ]


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, statement, parameters):
        sql = str(statement)
        self.connection.calls.append((sql, parameters))
        if "FROM dataset_version" in sql:
            if "WHERE import_id = %s" in sql:
                self.result = [
                    row for row in self.connection.versions
                    if row["import_id"] == parameters[0]
                ]
            else:
                self.result = list(self.connection.versions)
        elif "FROM dataset_variable" in sql:
            requested = set(parameters[0])
            self.result = [
                row for row in self.connection.variables
                if row["import_id"] in requested
            ]
        else:
            raise AssertionError(f"unexpected SQL: {sql}")
        return self

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class FakeConnection:
    def __init__(self, version=None, variables=None, versions=None):
        self.version = _version() if version is None else version
        self.versions = ([self.version] if versions is None
                         else list(versions))
        self.variables = _variables() if variables is None else variables
        self.calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True

    def cursor(self):
        return FakeCursor(self)


class FakeObjects:
    def __init__(self, dataset=None, failure=None):
        self.source = model_dataset() if dataset is None else dataset
        self.failure = failure
        self.opened = []
        self.close_calls = 0

    def open(self, reference):
        self.opened.append(reference)
        if self.failure is not None:
            raise self.failure
        dataset = self.source.copy(deep=False)
        dataset.set_close(self._closed)
        return dataset

    def _closed(self):
        self.close_calls += 1


DECLARATION = ModelSourceReference(
    crs="EPSG:4326",
    vertical_positive="down",
    basis="source-backed fixture declaration",
)


def _query(*, version=None, versions=None, variables=None, dataset=None,
           declarations=None, object_failure=None):
    connection = FakeConnection(
        version=version, versions=versions, variables=variables)
    objects = FakeObjects(dataset=dataset, failure=object_failure)
    query = CatalogueModelFieldQuery(
        SECRET_DSN,
        objects,
        ({"hycom_opendap": DECLARATION}
         if declarations is None else declarations),
        connect=lambda dsn: connection,
    )
    return query, connection, objects


def test_descriptor_maps_catalogue_coordinates_and_source_declarations():
    dataset = model_dataset()
    dataset["water_temp"].encoding["source"] = "/private/store/object.nc"
    dataset["depth"].encoding["source"] = "/private/store/object.nc"
    query, connection, objects = _query(dataset=dataset)

    with query.open_model_field(MODEL_VERSION_ID, "water_temp") as managed:
        descriptor = managed.descriptor
        assert descriptor.time_coordinate == "time"
        assert descriptor.depth_coordinate == "depth"
        assert descriptor.latitude_coordinate == "lat"
        assert descriptor.longitude_coordinate == "lon"
        assert descriptor.crs == "EPSG:4326"
        assert descriptor.vertical_positive == "down"
        assert descriptor.provenance["reference_basis"]["crs"] == (
            "source-backed fixture declaration")
        assert descriptor.provenance["source"]["details"] == {
            "_withheld": True,
            "provider": "fixture",
            "provider_code": "NOAA/NCEI",
            "request_url": "https://example.invalid/model",
        }
        assert descriptor.provenance["global_attributes"] == {
            "_withheld": True,
            "title": "model",
        }
        assert "source" not in managed.dataset.encoding
        assert all("source" not in item.encoding
                   for item in managed.dataset.variables.values())

    assert connection.closed
    assert objects.close_calls == 1
    assert all(call[0].lstrip().startswith("SELECT")
               for call in connection.calls)
    assert all(MODEL_VERSION_ID not in call[0]
               for call in connection.calls)
    assert connection.calls[0][1] == (MODEL_VERSION_ID,)


def test_summary_reads_exact_catalogue_coordinates_without_opening_object():
    dataset = model_dataset()
    query, _, objects = _query(dataset=dataset)

    summary = query.describe_version(MODEL_VERSION_ID)

    assert summary.depth_levels == 3
    assert summary.depth_values == (0.0, 10.0, 20.0)
    assert summary.time_steps == 1
    assert summary.time_values[0].startswith("2026-09-28T00:00:00")
    assert objects.opened == []
    assert objects.close_calls == 0


def test_legacy_summary_without_catalogue_coordinates_opens_object():
    query, _, objects = _query(version=_version(
        time_values=None, depth_values=None))

    summary = query.describe_version(MODEL_VERSION_ID)

    assert summary.depth_values == (0.0, 10.0, 20.0)
    assert summary.time_values[0].startswith("2026-09-28T00:00:00")
    assert objects.opened == [OBJECT_REFERENCE]
    assert objects.close_calls == 1


def test_listing_skips_and_reports_an_unreadable_managed_version():
    query, _, _ = _query(
        version=_version(time_values=None, depth_values=None),
        object_failure=RuntimeError(OBJECT_REFERENCE),
    )

    listing = query.list_model_versions()

    assert listing.versions == ()
    assert len(listing.unavailable) == 1
    assert listing.unavailable[0].id == MODEL_VERSION_ID
    assert "could not be opened" in listing.unavailable[0].reason
    assert OBJECT_REFERENCE not in repr(listing)
    assert SECRET_DSN not in repr(listing)


def test_listing_keeps_readable_versions_when_another_object_is_unreadable():
    broken_id = "broken-version"
    broken_reference = "/private/broken.nc"
    versions = (
        _version(),
        _version(
            import_id=broken_id,
            object_ref=broken_reference,
            time_values=None,
            depth_values=None,
        ),
    )

    class MixedObjects(FakeObjects):
        def open(self, reference):
            if reference == broken_reference:
                raise RuntimeError(reference)
            return super().open(reference)

    connection = FakeConnection(versions=versions)
    query = CatalogueModelFieldQuery(
        SECRET_DSN,
        MixedObjects(),
        {"hycom_opendap": DECLARATION},
        connect=lambda dsn: connection,
    )

    listing = query.list_model_versions()

    assert [summary.id for summary in listing] == [MODEL_VERSION_ID]
    assert [(item.id, item.reason) for item in listing.unavailable] == [
        (broken_id, f"dataset version {broken_id!r} could not be opened"),
    ]
    assert broken_reference not in repr(listing)


def test_cf_grid_mapping_and_vertical_direction_take_precedence():
    dataset = model_dataset()
    dataset["mapping"] = 0
    dataset["mapping"].attrs["epsg_code"] = 3857
    dataset["water_temp"].attrs["grid_mapping"] = "mapping"
    query, _, _ = _query(
        dataset=dataset,
        declarations={"hycom_opendap": ModelSourceReference(
            crs="EPSG:9999", vertical_positive="up", basis="fallback")},
    )

    with query.open_model_field(MODEL_VERSION_ID, "water_temp") as managed:
        assert managed.descriptor.crs == "EPSG:3857"
        assert managed.descriptor.vertical_positive == "down"
        assert "mapping" in managed.dataset
        assert managed.descriptor.provenance["reference_basis"]["crs"] == (
            "CF grid_mapping mapping.epsg_code")


def test_vertical_direction_uses_an_explicit_source_fallback_when_cf_omits_it():
    dataset = model_dataset()
    dataset["depth"].attrs.pop("positive")
    declaration = ModelSourceReference(
        crs="EPSG:4326", vertical_positive="up",
        basis="source documentation declares height positive up",
    )
    query, _, _ = _query(
        dataset=dataset, declarations={"hycom_opendap": declaration})

    with query.open_model_field(MODEL_VERSION_ID, "water_temp") as managed:
        assert managed.descriptor.vertical_positive == "up"
        assert managed.descriptor.provenance["reference_basis"][
            "vertical_positive"
        ] == declaration.basis


@pytest.mark.parametrize("missing_role", [
    "time", "vertical", "latitude", "longitude",
])
def test_missing_catalogue_coordinate_names_are_refused(missing_role):
    version = _version()
    del version["metadata"]["coordinate_names"][missing_role]
    query, _, objects = _query(version=version)

    with pytest.raises(UndeclaredReference, match="coordinate name"):
        query.open_model_field(MODEL_VERSION_ID, "water_temp")
    assert objects.close_calls == 1


def test_missing_crs_is_refused_without_a_silent_default():
    query, _, objects = _query(declarations={})
    with pytest.raises(UndeclaredReference, match="reference system"):
        query.open_model_field(MODEL_VERSION_ID, "water_temp")
    assert objects.close_calls == 1


def test_missing_vertical_direction_is_refused_without_a_silent_default():
    dataset = model_dataset()
    dataset["depth"].attrs.pop("positive")
    dataset["mapping"] = 0
    dataset["mapping"].attrs["spatial_ref"] = "EPSG:4326"
    dataset["water_temp"].attrs["grid_mapping"] = "mapping"
    query, _, objects = _query(dataset=dataset, declarations={})

    with pytest.raises(UndeclaredReference, match="vertical positive"):
        query.open_model_field(MODEL_VERSION_ID, "water_temp")
    assert objects.close_calls == 1


def test_declared_catalogue_variable_missing_from_object_is_typed():
    dataset = model_dataset().drop_vars("water_temp")
    query, _, objects = _query(dataset=dataset)
    with pytest.raises(VariableUnavailable):
        query.open_model_field(MODEL_VERSION_ID, "water_temp")
    assert objects.close_calls == 1


def test_backend_failures_hide_dsn_and_object_reference():
    query, _, _ = _query(object_failure=RuntimeError(OBJECT_REFERENCE))
    with pytest.raises(ModelFieldQueryError) as failure:
        query.open_model_field(MODEL_VERSION_ID, "water_temp")
    message = str(failure.value)
    assert SECRET_DSN not in message
    assert OBJECT_REFERENCE not in message
    assert failure.value.__cause__ is None


def test_catalogue_failure_hides_connection_details():
    def fail(_dsn):
        raise RuntimeError(SECRET_DSN)

    query = CatalogueModelFieldQuery(
        SECRET_DSN, FakeObjects(), {}, connect=fail)
    with pytest.raises(ModelFieldQueryError) as failure:
        query.list_model_versions()
    assert SECRET_DSN not in str(failure.value)
    assert failure.value.__cause__ is None
