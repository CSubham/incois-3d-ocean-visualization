"""ERDDAP selection logic, exercised without touching the network."""

import pytest

from ingestion.adapters.erddap import (
    ErddapAdapter, _clamp, _points,
)
from ingestion.config import INCOIS_ERDDAP
from ingestion.domain.errors import SelectionError
from ingestion.domain.selection import (
    Area, DepthRange, ImportSelection, TimeRange,
)
from ingestion.ports import RangeInfo

DEPTH = RangeInfo(dimension="ZAX", role="vertical", minimum=5.0,
                  maximum=2000.0, units="METERS", count=24)
TIME = RangeInfo(dimension="time", role="time",
                 minimum="2004-01-10T00:00:00Z", maximum="2026-07-30T00:00:00Z",
                 units="UTC", count=813)


def _selection(**kwargs) -> ImportSelection:
    return ImportSelection(source_id="incois_erddap",
                           dataset_id="incois_argo_10d_VAM", **kwargs)


def test_an_unconstrained_axis_uses_its_whole_extent():
    assert _clamp(DEPTH, _selection()) == ("5.0", "2000.0")


def test_a_request_is_clamped_to_what_the_axis_covers():
    selection = _selection(depth=DepthRange(0, 500))
    low, high = _clamp(DEPTH, selection)
    assert float(low) == 5.0      # clamped up to the shallowest level
    assert float(high) == 500.0


def test_an_inverted_range_is_refused():
    with pytest.raises(SelectionError, match="must not exceed"):
        _clamp(DEPTH, _selection(depth=DepthRange(500, 10)))


def test_a_range_outside_the_data_is_refused():
    with pytest.raises(SelectionError, match="must fall within"):
        _clamp(DEPTH, _selection(depth=DepthRange(5000, 6000)))


def test_dates_are_bounded_by_the_available_period():
    selection = _selection(
        time=TimeRange("2024-09-01T00:00:00Z", "2024-09-20T00:00:00Z"))
    low, high = _clamp(TIME, selection)
    assert low == "2024-09-01T00:00:00Z"
    assert high == "2024-09-20T00:00:00Z"


def test_a_period_the_dataset_does_not_cover_is_refused_clearly():
    """Silently clamping would build a start later than its own end."""
    with pytest.raises(SelectionError, match="only covers"):
        _clamp(TIME, _selection(
            time=TimeRange("1990-01-01", "1990-06-01")))


def test_dates_are_compared_as_instants_not_as_text():
    """'2004-01-10' and '2004-01-10T00:00:00Z' are the same moment.

    Compared as text the first looks earlier, which would make the axis
    appear to start before its own beginning.
    """
    from ingestion.adapters.erddap import _seconds

    low, high = _clamp(TIME, _selection(
        time=TimeRange("2004-01-10", "2004-02-01")))
    assert _seconds(low) == _seconds(TIME.minimum)   # accepted, not refused
    assert high == "2004-02-01"

    # A date genuinely before the axis is pulled up to its first instant.
    earlier, _ = _clamp(TIME, _selection(
        time=TimeRange("2003-01-01", "2004-02-01")))
    assert earlier == TIME.minimum


def test_a_backwards_date_range_is_refused():
    with pytest.raises(SelectionError, match="start date"):
        _clamp(TIME, _selection(
            time=TimeRange("2024-09-20T00:00:00Z", "2024-09-01T00:00:00Z")))


def test_a_narrower_range_estimates_fewer_points():
    whole = _points(DEPTH, "5.0", "2000.0")
    part = _points(DEPTH, "5.0", "200.0")
    assert part < whole == DEPTH.count


def test_a_short_date_range_is_not_costed_as_the_whole_archive():
    """A fortnight out of twenty years must not be priced as twenty years."""
    whole = _points(TIME, "2004-01-10T00:00:00Z", "2026-07-30T00:00:00Z")
    fortnight = _points(TIME, "2024-09-01T00:00:00Z", "2024-09-20T00:00:00Z")
    assert whole == TIME.count
    assert fortnight < 10


def test_a_selection_within_the_limit_is_accepted():
    """The guard must not reject a modest request from a long archive."""
    selection = _selection(
        variables=("TEMP", "SAL"),
        time=TimeRange("2024-09-01T00:00:00Z", "2024-09-20T00:00:00Z"),
        depth=DepthRange(5, 200))
    latitude = RangeInfo(dimension="latitude", role="latitude", minimum=-29.5,
                         maximum=29.5, units="degrees_north", count=60)
    longitude = RangeInfo(dimension="longitude", role="longitude",
                          minimum=30.5, maximum=119.5,
                          units="degrees_east", count=90)
    total = 2
    for info in (TIME, DEPTH, latitude, longitude):
        low, high = _clamp(info, selection)
        total *= _points(info, low, high)
    assert total < INCOIS_ERDDAP.max_values_per_request


def test_dimension_metadata_is_read_rather_than_downloaded():
    rows = [
        ["dimension", "ZAX", "", "double",
         "nValues=24, evenlySpaced=false, averageSpacing=86.7"],
        ["attribute", "ZAX", "actual_range", "double", "5.0, 2000.0"],
        ["attribute", "ZAX", "units", "String", "METERS"],
    ]
    described = ErddapAdapter._dimension_rows(rows)
    assert described["ZAX"]["count"] == 24
    assert described["ZAX"]["actual_range"] == "5.0, 2000.0"


def test_cf_times_are_rendered_as_readable_instants():
    rendered = ErddapAdapter._epoch_to_iso(
        1.0736928e9, "seconds since 1970-01-01T00:00:00Z")
    assert rendered.startswith("2004-01-10")


def test_the_catalogue_is_read_from_what_the_server_publishes():
    """Datasets are discovered, not recited from configuration."""
    adapter = ErddapAdapter(INCOIS_ERDDAP)
    adapter._catalogue_cache = [
        {"dataset_id": "grid_one", "title": "Zulu", "summary": "s",
         "institution": "i"},
        {"dataset_id": "grid_two", "title": "Alpha", "summary": "s",
         "institution": "i"},
    ]
    found = adapter.list_datasets()
    assert [ref.dataset_id for ref in found] == ["grid_two", "grid_one"]
    assert found[0].name == "Alpha"          # sorted by title, not by id


def test_an_allow_list_narrows_what_is_offered():
    """Configuration restricts the catalogue; it does not replace it."""
    from dataclasses import replace
    adapter = ErddapAdapter(replace(INCOIS_ERDDAP, datasets=("grid_two",)))
    adapter._catalogue_cache = [
        {"dataset_id": "grid_one", "title": "Zulu", "summary": "",
         "institution": ""},
        {"dataset_id": "grid_two", "title": "Alpha", "summary": "",
         "institution": ""},
    ]
    assert [ref.dataset_id for ref in adapter.list_datasets()] == ["grid_two"]


def test_no_allow_list_means_everything_the_server_offers():
    assert INCOIS_ERDDAP.datasets == ()


def test_the_adapter_declares_what_it_can_narrow():
    capabilities = ErddapAdapter(INCOIS_ERDDAP).describe().capabilities
    assert capabilities.variable_selection
    assert capabilities.spatial_subsetting
    assert capabilities.time_subsetting
    assert capabilities.depth_subsetting
