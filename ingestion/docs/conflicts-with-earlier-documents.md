# Conflicts with earlier documents

Recorded during the S2 rebuild. The current instruction was followed in every
case below; nothing here was resolved by deferring to a document.

These are records, not proposals. The SRS, HLSA, LLD and the earlier
`S2_implementation_plan.md` have **not** been edited as part of this work.

---

**1. The feed registry is gone.**

`S2_implementation_plan.md` specified a `registry.yaml` naming one adapter per
registered feed, and stated that dispatch happens "by the adapter the registry
entry names, never the format."

A user choosing a file from disk has no registered feed, so that model cannot
describe local sources. Routing now happens at the adapter boundary
(`ingestion/adapters/__init__.py`), and the local-folder adapter detects format
internally to pick a delegate. The application service still performs no
dispatch of its own. `registry.yaml` and `registry.py` were deleted.

**2. One adapter per feed became one adapter per source kind.**

The plan had `hycom.py` and `incois_currents.py` as per-feed adapters. Both
were deleted. A NetCDF file is read by the NetCDF adapter whatever produced
it; nothing about HYCOM or the INCOIS value-added product needs its own
module, and the INCOIS currents file is now rejected by validation on the
evidence in the file rather than by anything that knows its name.

**3. The three-slot handoff became one canonical package.**

The plan defined the S2 output as `grid` / `profiles` / `manifest`, with the
first two optional. That split forced every dataset into one of two shapes.
The output is now a single `CanonicalPackage` carrying the dataset with its
geometry classified (`grid`, `profile`, `trajectory`, `trajectory_profile`,
`point`), so a glider track is not flattened into a set of profiles to fit a
slot.

**4. CLI removed.**

`cli.py` duplicated the workflow through a second entry point. The application
service is the one entry point; the HTTP layer and the UI sit on top of it.

**5. The LLD names a "Validation manifest and profiles" in the S2 output gate.**

Validation results and source details travel inside the canonical package
(`validation`, `source`, `metadata`) rather than as separate artifacts. The
information the LLD asked to cross the boundary does cross it; its shape
differs.

**6. `INCOIS_ALLOW_INSECURE` renamed and de-emphasised.**

The old escape hatch disabled TLS verification for all requests. The
underlying cause -- the INCOIS server omitting its intermediate certificate --
is now fixed properly by supplying that intermediate
(`ingestion/certs/`), so verification stays on. The override survives as
`INGESTION_ALLOW_INSECURE_TLS` for diagnosis only and is not needed in normal
operation.

**7. Local file sources archived.**

The scope that produced this stage required local NetCDF, delimited-text and
folder sources. They were built, worked against the repository's sample data,
and have since been set aside to concentrate on the remote adapter. The code
is in `archive/local-sources/` with restoration notes.

The cost is requirement coverage: ERDDAP griddap returns NetCDF, so the
project currently has no delimited-text route. ING-002 and the text half of
DIR-007 are uncovered until those adapters return or a tabledap adapter is
written.

**8. ERDDAP is the primary remote source; the investigation ranks it second.**

`docs/history/INCOIS_3D_Ocean_Visualization_Technical_Investigation.md` says
to "start with HTTPS file retrieval and OPeNDAP/THREDDS for INCOIS and model
products" and to "use ERDDAP only for datasets for which its query semantics
and provenance can be recorded." ERDDAP was built first because it is the
endpoint with a working, inspectable catalogue. No OPeNDAP/THREDDS adapter
exists yet.

**9. S2 is an interactive application, not a batch job.**

The LLD has S2 as "Azure: Container Apps Jobs" and the technical
investigation's H.1 lists it as an "`ingest` command or scheduled container".
Both describe a finite run with no interface.

It is built as a web application with a four-step import workflow, on the
stated grounds that choosing a source, dataset, variables and ranges is
something a person does, and doing it through a command or a schedule is
worse for the people who have to use it.

This is a decision, not drift. The documents describe how S2 is *invoked*;
they do not change what it produces, and the canonical package crossing
`StoragePort` is the same either way.

Worth knowing for later: the two forms are not exclusive. `IngestionService`
holds the whole workflow and takes an `ImportSelection`; the HTTP layer only
translates. A scheduled job would call the same service with a stored
selection and need nothing new from this stage. If the Azure profile later
wants a Container Apps Job as well, it is an entry point, not a rewrite.
