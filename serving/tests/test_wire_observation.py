"""Observation products use an exact, aligned, self-describing wire layout."""

from __future__ import annotations

import json

import numpy as np
import pytest

from processing import build_observation_markers, build_observation_profile
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
    assert "values" not in decoded["product"]["variables"][0]
    assert decoded["data"]["byte_order"] == "little"
