"""Convention checks run before anything is handed to storage.

Every check reports rather than repairs. A dataset that cannot be understood
is returned as a clear problem, never guessed into shape -- downstream layers
must be able to trust that an accepted package means what it says.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import xarray as xr

from ingestion.domain.package import (
    CoordinateSet, DatasetGeometry, VariableSpec,
)
from ingestion.domain.validation import ValidationIssue, ValidationResult

#: Geometries that carry a vertical axis by definition.
_NEEDS_VERTICAL = (DatasetGeometry.PROFILE, DatasetGeometry.TRAJECTORY_PROFILE)


def validate(dataset: xr.Dataset,
             coordinates: CoordinateSet,
             geometry: Optional[DatasetGeometry],
             variables: tuple[VariableSpec, ...],
             geometry_problem: Optional[str] = None) -> ValidationResult:
    """Check a retrieved dataset against the conventions required downstream."""

    checks: list[str] = []
    issues: list[ValidationIssue] = []

    def failed(check: str, detail: str) -> None:
        issues.append(ValidationIssue(check=check, detail=detail))

    # -- the data is there at all ------------------------------------------
    checks.append("variables_present")
    if not variables:
        failed("variables_present", "the dataset contains no data variables")

    checks.append("dimensions_valid")
    empty_dims = [str(name) for name, size in dataset.sizes.items() if size < 1]
    if empty_dims:
        failed("dimensions_valid",
               "dimension(s) have no extent: " + ", ".join(sorted(empty_dims)))
    undimensioned = [spec.name for spec in variables if not spec.dimensions]
    if undimensioned:
        failed("dimensions_valid",
               "variable(s) have no dimensions: "
               + ", ".join(sorted(undimensioned)))

    # -- scientific coordinates can be identified --------------------------
    checks.append("horizontal_coordinates")
    for role in ("latitude", "longitude"):
        if not getattr(coordinates, role):
            failed("horizontal_coordinates",
                   f"no {role} coordinate could be identified")

    checks.append("time_coordinate")
    if not coordinates.time:
        failed("time_coordinate", "no time coordinate could be identified")

    checks.append("vertical_coordinate")
    if geometry in _NEEDS_VERTICAL and not coordinates.vertical:
        failed("vertical_coordinate",
               f"{geometry.label} data requires a depth or pressure "
               "coordinate, and none could be identified")

    # -- metadata survived the source --------------------------------------
    checks.append("units_declared")
    unitless = sorted(spec.name for spec in variables if not spec.units)
    if unitless:
        failed("units_declared",
               "variable(s) declare no units, so their values cannot be "
               "interpreted: " + ", ".join(unitless))

    checks.append("missing_values_handled")
    scientific = {spec.name for spec in variables}
    undecoded = sorted(
        str(name) for name, variable in dataset.data_vars.items()
        if str(name) in scientific
        and ("_FillValue" in variable.attrs
             or "missing_value" in variable.attrs))
    if undecoded:
        failed("missing_values_handled",
               "fill values were not applied while reading: "
               + ", ".join(undecoded))

    checks.append("values_present")
    empty = sorted(str(name) for name, variable in dataset.data_vars.items()
                   if str(name) in scientific and _entirely_missing(variable))
    if empty:
        failed("values_present",
               "variable(s) contain no usable values: " + ", ".join(empty))

    # -- the shape is known ------------------------------------------------
    checks.append("geometry_classified")
    if geometry is None:
        failed("geometry_classified",
               geometry_problem or "the shape of the dataset could not be "
                                   "determined")

    return ValidationResult(checks_run=tuple(checks), issues=tuple(issues))


def _entirely_missing(variable: xr.DataArray) -> bool:
    try:
        if variable.size == 0:
            return True
        if variable.dtype.kind not in "fc":
            return False
        return bool(np.isnan(variable.values).all())
    except Exception:
        return False
