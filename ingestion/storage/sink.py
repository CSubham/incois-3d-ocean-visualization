"""Development implementations of `StoragePort`.

NOT STORAGE. The storage layer owns persistence, physical layout, chunking,
indexing and serving; none of that is implemented or simulated here. These
exist so the ingestion stage can be exercised and tested up to the boundary,
and so the shape of what crosses it is pinned down by real use.

Replace with the real adapter when the storage layer exists. Nothing in the
ingestion stage should need to change when that happens.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion.domain.package import CanonicalPackage
from ingestion.ports import StoragePort, StorageReceipt


class RecordingSink(StoragePort):
    """Records what it was handed, and nothing else.

    Used in tests to assert that a complete package reached the boundary.
    """

    def __init__(self) -> None:
        self.packages: list[CanonicalPackage] = []

    def hand_off(self, package: CanonicalPackage) -> StorageReceipt:
        self.packages.append(package)
        return StorageReceipt(
            import_id=package.import_id,
            reference=f"recorded:{package.import_id}",
            accepted_at=datetime.now(timezone.utc).isoformat(),
            details={"handed_off": len(self.packages)},
        )


class DevelopmentSink(StoragePort):
    """Writes the package description to disk so a run can be inspected.

    The dataset itself is written as NetCDF purely so a developer can open it.
    This is a convenience for local work, not a storage design: the real
    storage layer decides format, layout and lifetime.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def hand_off(self, package: CanonicalPackage) -> StorageReceipt:
        target = self.root / package.import_id
        target.mkdir(parents=True, exist_ok=True)

        description: dict[str, Any] = package.describe()
        description["metadata"] = package.metadata
        description["variables_detail"] = [
            {"name": v.name, "units": v.units,
             "standard_name": v.standard_name, "long_name": v.long_name,
             "dimensions": list(v.dimensions), "fill_value": v.fill_value}
            for v in package.variables]
        description["selection"] = {
            "source_id": package.selection.source_id,
            "dataset_id": package.selection.dataset_id,
            "variables": list(package.selection.variables),
            "time": vars(package.selection.time) if package.selection.time else None,
            "depth": vars(package.selection.depth) if package.selection.depth else None,
            "area": vars(package.selection.area) if package.selection.area else None,
        }
        (target / "package.json").write_text(
            json.dumps(description, indent=2, default=str))

        data_path = target / "dataset.nc"
        try:
            package.dataset.to_netcdf(data_path)
        except Exception as exc:  # inspection aid only; never fails the handoff
            (target / "dataset.error.txt").write_text(str(exc))
            data_path = None

        return StorageReceipt(
            import_id=package.import_id,
            reference=str(target),
            accepted_at=datetime.now(timezone.utc).isoformat(),
            details={"description": str(target / "package.json"),
                     "dataset": str(data_path) if data_path else None,
                     "note": "development sink; not durable storage"},
        )
