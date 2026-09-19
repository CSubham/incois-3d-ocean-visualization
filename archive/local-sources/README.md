# Archived: local file sources

Set aside while the project focuses on the remote adapter. Nothing here is
imported by the running application.

## What this was

Three `SourcePort` implementations plus the path handling they shared:

| File | Was |
|---|---|
| `local_base.py` | Shared base: `root:relative` identifiers, safe resolution, listing |
| `local_netcdf.py` | NetCDF files the user chose |
| `local_delimited.py` | CSV and other delimited observation files |
| `local_folder.py` | Folder discovery, delegating to the two above by format |
| `local_paths.py` | Root-confined path resolution and directory listing |
| `test_end_to_end_local.py` | End-to-end tests covering all three |

## Why it was archived

Scope decision: concentrate on the remote source path. Not a defect -- all of
it worked, against the repository's real sample data.

## What it took with it

**Requirement coverage.** ERDDAP griddap returns NetCDF, so with these gone
the project has no delimited-text route. ING-002 (automated parsing of
delimited text) and the text half of DIR-007 are uncovered until either these
return or a tabledap adapter is written.

**Offline testing.** These were the only tests that exercised the full
workflow without a network. `ingestion/tests/test_workflow.py` now covers the
same ground using an in-repo fake source.

## Restoring it

1. Move the five modules back to `ingestion/` (`local_paths.py` at the top
   level, the rest under `ingestion/adapters/`).
2. Restore `browse_roots`, `NETCDF_SUFFIXES`, `DELIMITED_SUFFIXES` and
   `SUPPORTED_SUFFIXES` in `ingestion/config.py` -- see this directory's
   `config-fragment.py`.
3. Re-register the three adapters in `ingestion/adapters/__init__.py`.
4. Restore the `/api/locations` and `/api/browse` endpoints in
   `ingestion/web.py`, and the file-browsing branch in `static/app.js`.
5. Move `test_end_to_end_local.py` back to `ingestion/tests/`.

Nothing in the ports, contracts, canonicalization, validation or storage
boundary changed, so the adapters should fit as they are.
