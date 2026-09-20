"""Reading delimited observation text."""

import numpy as np
import pytest

from ingestion.domain.errors import SourceError
from ingestion.tools.delimited import (
    OBSERVATION_DIM, is_ancillary, read, role_of, split_units_row,
)

ERDDAP_CSV = """time,latitude,longitude,depth,temperature,salinity
UTC,degrees_north,degrees_east,m,Celsius,1
2018-09-01T07:58:55Z,4.8521,81.5743,3.13,27.7116,34.802784
2018-09-01T07:58:55Z,4.8521,81.5743,13.69,27.4267,34.802498
"""

NO_UNITS_ROW = """time,latitude,longitude,depth,temperature
2018-09-01T07:58:55Z,4.8521,81.5743,3.13,27.7116
2018-09-01T07:58:55Z,4.8521,81.5743,13.69,27.4267
"""


def test_a_dimensionless_unit_does_not_look_like_data():
    """Practical salinity is `1` in CF. Judging the row alone reads that as
    a measurement and loses every unit in the file."""
    units, first_row = split_units_row(
        [line.split(",") for line in ERDDAP_CSV.strip().splitlines()])
    assert first_row == 2
    assert units["salinity"] == "1"
    assert units["temperature"] == "Celsius"


def test_a_file_without_a_units_row_is_read_as_data_from_line_two():
    units, first_row = split_units_row(
        [line.split(",") for line in NO_UNITS_ROW.strip().splitlines()])
    assert units == {}
    assert first_row == 1


def test_units_carry_onto_the_variables():
    dataset = read(ERDDAP_CSV)
    assert dataset["temperature"].attrs["units"] == "Celsius"
    assert dataset["salinity"].attrs["units"] == "1"


def test_declared_units_beat_what_the_file_says_about_itself():
    """A catalogue entry is more reliable than sniffing a row."""
    dataset = read(ERDDAP_CSV, units={"temperature": "degree_Celsius"})
    assert dataset["temperature"].attrs["units"] == "degree_Celsius"


def test_rows_stay_rows():
    dataset = read(ERDDAP_CSV)
    assert dataset.sizes[OBSERVATION_DIM] == 2
    assert dataset["temperature"].dims == (OBSERVATION_DIM,)


def test_position_time_and_depth_become_coordinates_not_variables():
    dataset = read(ERDDAP_CSV)
    assert set(dataset.data_vars) == {"temperature", "salinity"}
    for name in ("time", "latitude", "longitude", "depth"):
        assert name in dataset.coords


def test_flags_and_identifiers_are_kept_but_not_offered_as_measurements():
    text = ("time,latitude,longitude,PRES,TEMP,TEMP_QC,PLATFORM_NUMBER\n"
            "UTC,degrees_north,degrees_east,decibar,degree_Celsius,,\n"
            "2002-11-11T09:20:28Z,-9.857,55.953,5.5,27.388,1,2900123\n"
            "2002-11-11T09:20:28Z,-9.857,55.953,9.4,27.375,1,2900123\n")
    dataset = read(text)
    assert set(dataset.data_vars) == {"TEMP"}
    assert "TEMP_QC" in dataset.coords
    assert "PLATFORM_NUMBER" in dataset.coords


def test_a_table_of_only_flags_is_refused():
    text = ("time,latitude,longitude,PLATFORM_NUMBER\n"
            "UTC,degrees_north,degrees_east,\n"
            "2002-11-11T09:20:28Z,-9.857,55.953,2900123\n"
            "2002-11-12T09:20:28Z,-9.858,55.954,2900123\n")
    with pytest.raises(SourceError, match="no measured values"):
        read(text)


def test_an_empty_response_is_refused():
    with pytest.raises(SourceError, match="no data"):
        read("")


@pytest.mark.parametrize("column,role", [
    ("time", "time"), ("latitude", "latitude"), ("lon", "longitude"),
    ("PRES", "vertical"), ("depth", "vertical"), ("TEMP", None),
])
def test_column_roles(column, role):
    assert role_of(column) == role


@pytest.mark.parametrize("column", [
    "TEMP_QC", "PSAL_ADJUSTED_QC", "PLATFORM_NUMBER", "CYCLE_NUMBER",
    "profile_id", "trajectory",
])
def test_ancillary_columns(column):
    assert is_ancillary(column)
