"""The ingestion application service.

The whole S2 workflow lives here, and it contains no source-specific logic:
sources are resolved to a `SourcePort`, data is canonicalized and validated
the same way whatever it came from, and the result leaves through
`StoragePort`.

Adding a source touches the adapter table, not this module.
"""

from __future__ import annotations

from typing import Any, Optional

from ingestion import adapters, canonical, conventions
from ingestion.domain.errors import ConventionError, IngestionError
from ingestion.domain.job import ImportJob, ImportState
from ingestion.domain.package import CanonicalPackage, DatasetGeometry, SourceInfo
from ingestion.domain.selection import ImportSelection
from ingestion.jobs import JobStore
from ingestion.ports import (
    DatasetMetadata, DatasetRef, SourceDescription, StoragePort,
)


class IngestionService:
    """Drives one import from selection to storage handoff."""

    def __init__(self, storage: StoragePort,
                 jobs: Optional[JobStore] = None) -> None:
        self._storage = storage
        self.jobs = jobs or JobStore()

    # -- choosing what to import -------------------------------------------

    def sources(self) -> tuple[SourceDescription, ...]:
        return adapters.available_sources()

    def datasets(self, source_id: str,
                 context: Optional[dict[str, Any]] = None
                 ) -> tuple[DatasetRef, ...]:
        return adapters.resolve(source_id).list_datasets(context)

    def inspect(self, source_id: str, dataset_id: str,
                context: Optional[dict[str, Any]] = None) -> DatasetMetadata:
        return adapters.resolve(source_id).inspect_dataset(dataset_id, context)

    # -- running an import --------------------------------------------------

    def start_import(self, selection: ImportSelection,
                     context: Optional[dict[str, Any]] = None) -> ImportJob:
        """Register an import and run it.

        Execution is synchronous today. The job is registered before any work
        begins, so a caller already holds an id it can poll -- which is what
        allows the work to move off this thread later without changing the
        interface.
        """
        job = self.jobs.add(ImportJob(selection=selection))
        try:
            self._execute(job, context)
        except IngestionError as exc:
            job.fail(str(exc))
        except Exception as exc:  # unexpected, but a job must still resolve
            job.fail(f"the import stopped unexpectedly: {exc}")
        return job

    def _execute(self, job: ImportJob,
                 context: Optional[dict[str, Any]]) -> None:
        selection = job.selection
        source = adapters.resolve(selection.source_id)
        description = source.describe()

        job.advance(ImportState.IMPORTING)
        fetched = source.fetch(selection, context)

        job.advance(ImportState.VALIDATING)
        dataset = fetched.dataset
        coordinates = canonical.identify_coordinates(dataset)

        geometry: Optional[DatasetGeometry] = None
        geometry_problem: Optional[str] = None
        try:
            geometry = canonical.classify_geometry(dataset, coordinates)
        except ConventionError as exc:
            geometry_problem = str(exc)

        variables = canonical.describe_variables(dataset, coordinates)
        result = conventions.validate(dataset, coordinates, geometry,
                                      variables, geometry_problem)
        if not result.passed:
            job.result = {"validation": {
                "passed": False,
                "checks_run": list(result.checks_run),
                "problems": [{"check": i.check, "detail": i.detail}
                             for i in result.issues]}}
            job.fail(result.summary())
            return

        dataset_name = selection.dataset_id
        try:
            dataset_name = source.inspect_dataset(
                selection.dataset_id, context).name
        except IngestionError:
            pass  # a name is presentation, never a reason to fail an import

        package = CanonicalPackage(
            import_id=job.import_id,
            dataset=dataset,
            geometry=geometry,          # type: ignore[arg-type]
            variables=variables,
            coordinates=coordinates,
            source=SourceInfo(
                source_id=description.source_id,
                source_name=description.name,
                dataset_id=selection.dataset_id,
                dataset_name=dataset_name,
                kind=description.kind,
                location=fetched.location,
                details=fetched.details),
            selection=selection,
            validation=result,
            metadata=canonical.collect_metadata(dataset, coordinates),
        )

        job.advance(ImportState.HANDING_OFF)
        receipt = self._storage.hand_off(package)

        job.result = package.describe()
        job.result["validation"]["problems"] = []
        job.receipt = {"reference": receipt.reference,
                       "accepted_at": receipt.accepted_at,
                       "details": receipt.details}
        job.advance(ImportState.COMPLETED)

    # -- looking at imports -------------------------------------------------

    def job(self, import_id: str) -> Optional[ImportJob]:
        return self.jobs.get(import_id)

    def recent_jobs(self, count: int = 20) -> list[ImportJob]:
        return self.jobs.recent(count)
