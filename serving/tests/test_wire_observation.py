"""Observation products use an exact, aligned, self-describing wire layout."""

from __future__ import annotations

import json

import numpy as np
import pytest

from ingestion.query import ProfileIdentity
from ingestion.tests.query_support import PROFILE_VERSION_ID, in_memory_case
from processing import (
    DatasetIdentity, ObservationProfileIdentity, ObservationProfileSelection,
    ObservationRecordDescriptor, SpatialReference,
    build_observation_markers, build_observation_profile,
)
from processing.managed import (
    ManagedObservationProfileRequest, managed_observation_profile_builder,
)
from processing.tests import observation_fixtures as fixtures
from serving import wire_observation
from serving.wire import WireFormatError


def _markers():
    return build_observation_markers(
        fixtures.argo(), fixtures.argo_descriptor())


def _profile(dataset=None):
    return build_observation_profile(
        dataset if dataset is not None else fixtures.argo(),
        fixtures.argo_descriptor(), fixtures.argo_selection())


def test_marker_arrays_identities_times_and_source_rows_round_trip():
    product = _markers()
    layout, buffer = wire_observation.encode(product)
    arrays = wire_observation.decode(layout, buffer)

    np.testing.assert_array_equal(arrays["longitude"],
                                  [marker.longitude for marker in product.markers])
    np.testing.assert_array_equal(arrays["vertical_minimum"], [
        marker.vertical_range.minimum for marker in product.markers])
    assert wire_observation.decode_text(layout, buffer, "platform_id") == \
        ("5901", "5902")
    assert wire_observation.decode_text(layout, buffer, "cycle") == ("7", "8")
    assert wire_observation.decode_text(layout, buffer, "time") == (
        "2026-01-01", "2026-01-02T00:01",
    )
    assert arrays["marker_source_index_offsets"].tolist() == [0, 4, 7]
    assert arrays["marker_source_index"].tolist() == list(range(7))


def test_integral_float_cycle_identity_round_trips_without_decimal_suffix():
    dataset = fixtures.glider().assign_coords(
        profile_id=("row", np.ones(4, dtype=np.float64)))
    selection = ObservationProfileSelection(
        ObservationProfileIdentity("ru29", "1"), ("temperature",))
    profile = build_observation_profile(
        dataset, fixtures.glider_descriptor(), selection)
    markers = build_observation_markers(dataset, fixtures.glider_descriptor())

    layout, buffer = wire_observation.encode(markers)

    assert profile.profile_identity.cycle == "1"
    assert markers.markers[0].identity.cycle == "1"
    assert wire_observation.decode_text(layout, buffer, "cycle") == ("1",)


def test_profile_values_masks_qc_timestamps_and_indices_round_trip():
    product = _profile()
    layout, buffer = wire_observation.encode(product)
    arrays = wire_observation.decode(layout, buffer)

    np.testing.assert_array_equal(arrays["vertical"], product.vertical_values)
    np.testing.assert_array_equal(arrays["variable_0_values"],
                                  product.variables[0].values)
    assert arrays["variable_0_values"].dtype == np.dtype("<f4")
    assert arrays["variable_0_missing_value_mask"].tolist() == [0, 1, 0, 0]
    assert arrays["timestamp_missing_value_mask"].tolist() == [0, 0, 1, 0]
    assert arrays["source_index"].tolist() == [0, 1, 2, 3]
    assert wire_observation.decode_text(
        layout, buffer, "variable_0_qc") == ("1", "4", "", "2")
    assert wire_observation.decode_text(layout, buffer, "timestamp")[2] == ""


def test_every_observation_array_starts_on_an_eight_byte_boundary():
    layout, buffer = wire_observation.encode(_profile())

    assert all(entry["byte_offset"] % 8 == 0 for entry in layout)
    last = layout[-1]
    assert last["byte_offset"] + last["byte_length"] == len(buffer)


def test_big_endian_measurements_are_little_endian_without_value_changes():
    dataset = fixtures.argo()
    dataset["TEMP"] = dataset["TEMP"].astype(">f4")
    product = _profile(dataset)

    layout, buffer = wire_observation.encode(product)
    delivered = wire_observation.decode(layout, buffer)["variable_0_values"]

    assert delivered.dtype == np.dtype("<f4")
    np.testing.assert_array_equal(delivered, product.variables[0].values)


def test_an_unviewable_measurement_dtype_is_refused_not_quantized():
    dataset = fixtures.argo()
    dataset["TEMP"] = (("observation",), np.arange(7, dtype=np.int64),
                       {"units": "degree_Celsius"})
    product = _profile(dataset)

    with pytest.raises(WireFormatError, match="int64"):
        wire_observation.encode(product)


def test_descriptor_is_json_ready_and_excludes_bulk_arrays():
    product = _profile()
    described = wire_observation.describe(product, data_url="/observations/data")
    decoded = json.loads(json.dumps(described, allow_nan=False))

    assert decoded["wire_format"] == wire_observation.WIRE_FORMAT
    assert decoded["observation_count"] == 4
    assert decoded["product"]["dataset_identity"][
        "dataset_version_id"] == fixtures.ARGO_VERSION
    assert decoded["product"]["profile_identity"] == {
        "platform_id": "5901", "cycle": "7"}
    assert decoded["product"]["coordinates"]["vertical_kind"] == "pressure"
    assert decoded["product"]["variables"][0]["qc_variable"] == "TEMP_QC"
    assert decoded["product"]["variables"][0]["qc_flag_values"] == [
        "1", "2", "3", "4"]
    assert decoded["product"]["variables"][0]["qc_flag_meanings"] == (
        "good_data probably_good_data probably_bad_data bad_data")
    assert decoded["product"]["variables"][0]["qc_conventions"] == \
        "Argo reference table 2"
    assert decoded["product"]["variables"][1]["qc_flag_values"] is None
    assert decoded["product"]["variables"][1]["qc_flag_meanings"] is None
    assert decoded["product"]["variables"][1]["qc_conventions"] is None
    assert "values" not in decoded["product"]["variables"][0]
    assert decoded["data"]["byte_order"] == "little"


def test_glider_qc_vocabulary_is_declared_in_the_wire_descriptor():
    product = build_observation_profile(
        fixtures.glider(), fixtures.glider_descriptor(),
        fixtures.glider_selection())

    variable = wire_observation.describe(product, data_url=None)[
        "product"]["variables"][0]

    assert variable["qc_flag_values"] == ["GOOD", "SUSPECT"]
    assert variable["qc_flag_meanings"] == "good_data suspect_data"
    assert variable["qc_conventions"] == "IOOS QARTOD"


def test_s3_record_profile_uses_the_same_wire_format_with_absent_dtypes():
    descriptor = ObservationRecordDescriptor(
        identity=DatasetIdentity("Indian_ARGO_Floats", PROFILE_VERSION_ID),
        spatial_reference=SpatialReference(
            crs="EPSG:4326", vertical_positive="down"),
        vertical_kind="depth",
        vertical_coordinate="PRES",
        vertical_units="decibar",
        provenance={"import_id": PROFILE_VERSION_ID},
    )
    product = managed_observation_profile_builder(
        in_memory_case().query, {PROFILE_VERSION_ID: descriptor})(
            ManagedObservationProfileRequest(
                identity=ProfileIdentity(
                    PROFILE_VERSION_ID, "7902250", "12"),
                variables=("TEMP",),
            ))

    layout, buffer = wire_observation.encode(product)
    arrays = wire_observation.decode(layout, buffer)
    described = wire_observation.describe(product, data_url=None)

    np.testing.assert_array_equal(arrays["variable_0_values"], [28.0, 27.5])
    assert wire_observation.decode_text(
        layout, buffer, "variable_0_qc") == ("1", "2")
    variable = described["product"]["variables"][0]
    assert variable["source_dtype"] is None
    assert variable["qc_source_dtype"] is None
    assert variable["qc_flag_values"] == [1, 2]
    assert variable["qc_flag_meanings"] == "good_data bad_data"
    assert variable["qc_conventions"] == "fixture QC table 1"


def test_the_browser_marker_fixture_matches_the_encoder():
    """The browser marker decoder is tested against these files; regenerate
    with WIRE_GOLDEN_UPDATE=1 only when the wire format changes on purpose."""
    import json
    import os
    from pathlib import Path

    from ingestion.query import ProfileSearch
    from ingestion.tests.query_support import PROFILE_VERSION_ID, in_memory_case
    from processing.managed import (
        ManagedObservationMarkerRequest, managed_observation_marker_builder,
    )

    golden = Path(__file__).resolve().parents[2] / "web" / "test-fixtures"
    product = managed_observation_marker_builder(in_memory_case().query)(
        ManagedObservationMarkerRequest(PROFILE_VERSION_ID, ProfileSearch(
            west=70, east=80, south=5, north=12,
            time_start="2026-09-27T00:00:00Z", time_end="2026-09-29T00:00:00Z")))
    descriptor = json.dumps(wire_observation.describe(product, data_url="/data"),
                            indent=2, sort_keys=True) + "\n"
    _, buffer = wire_observation.encode(product)
    if os.environ.get("WIRE_GOLDEN_UPDATE") == "1":
        (golden / "observation-markers.json").write_text(descriptor)
        (golden / "observation-markers.bin").write_bytes(buffer)

    assert (golden / "observation-markers.json").read_text() == descriptor
    assert (golden / "observation-markers.bin").read_bytes() == buffer


def test_the_browser_float32_marker_fixture_matches_the_encoder():
    """Source-dtype-preserving markers: Argo positions stay float32 on the
    wire, and the browser decoder must accept them as declared."""
    import json
    import os
    from pathlib import Path

    from processing.observation import build_observation_markers
    from processing.tests.observation_fixtures import argo, argo_descriptor

    golden = Path(__file__).resolve().parents[2] / "web" / "test-fixtures"
    product = build_observation_markers(argo(), argo_descriptor())
    described = wire_observation.describe(product, data_url="/data")
    dtypes = {a["name"]: a["dtype"] for a in described["data"]["arrays"]}
    assert dtypes["longitude"] == dtypes["latitude"] == "<f4"
    descriptor = json.dumps(described, indent=2, sort_keys=True) + "\n"
    _, buffer = wire_observation.encode(product)
    if os.environ.get("WIRE_GOLDEN_UPDATE") == "1":
        (golden / "observation-markers-f4.json").write_text(descriptor)
        (golden / "observation-markers-f4.bin").write_bytes(buffer)

    assert (golden / "observation-markers-f4.json").read_text() == descriptor
    assert (golden / "observation-markers-f4.bin").read_bytes() == buffer
