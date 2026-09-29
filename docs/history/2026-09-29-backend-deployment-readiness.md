# Backend deployment readiness: migrations, configuration, probes, image, CI

Feature:
Prepares the pre-S7 backend for a real deployment. The catalogue schema is
applied as versioned, checked migrations. The app refuses to run without its
configuration. It reports liveness and readiness, logs structured JSON with
request ids, and builds as one container image. CI gates each change.

Requirements and IMAP refs:
The WEB-003 and WEB-004 evidence path starts here; neither requirement is
met yet (no deployment exists). IMAP:
- `x-deployment-scale` (blocked → in-progress; Azure confirmed by the owner)
- `x-operability`
- `x-composition`
- `s3-catalogue-profile-store`
- `s5-catalogue-response` (review M2)

Worker branch and commits:
`feature/c6-backend-hardening-c` (Agent C):
- `0b5e9e5` migrations
- `af65343` configuration
- `4a331e3` M2
- `f48d6af` probes and logs
- `7eff733` image and CI

Merge commit:
None; `main` fast-forwarded to `7eff733`.

What was implemented:
- `ingestion/storage/migrate.py` and `migrations/0001_catalogue_baseline.sql`
  (formerly `schema.sql`, unchanged):
  - numbered migrations, all applied in one transaction under an advisory
    lock, and recorded with checksums;
  - an edited applied migration is refused;
  - `--check` reports the schema state and exits 1 when it is not current.
- There are no default credentials anywhere in code.
  - Without `INGESTION_CATALOGUE_DSN`, the query backend raises
    `ConfigurationError`, and an import is refused before any array is
    written.
  - Every catalogue connection is bounded by
    `INGESTION_CATALOGUE_CONNECT_TIMEOUT`.
  - `.env.example` lists every setting.
- Review M2 (S3–S5 review): an observation-catalogue outage is now a coded
  partial failure (`observation_failure.code =
  observation_catalogue_unavailable`) beside the model listing.
  - The `Catalogue` protocol declares `list_observation_versions`, so there
    is no `getattr` discovery.
- `/health/live` and `/health/ready`:
  - readiness requires the catalogue at exactly this code's schema version
    and the object store;
  - it returns 503 with a reason per check, and the reasons carry no
    connection details.
- `serving/observability.py`:
  - a request id is kept from `X-Request-ID` if the caller's value is safe,
    otherwise generated;
  - it is echoed on the response and bound to log records;
  - each request writes one JSON access line.
- `Dockerfile`: one unprivileged backend image. It runs the API by default;
  migrations and S2 ingestion run by command.
- `.github/workflows/ci.yml` runs, in order:
  - ruff;
  - mypy, with the pre-existing errors recorded as a list in
    `pyproject.toml` that may only shrink;
  - the tests against a PostGIS service;
  - migrate and `--check`;
  - the image build and a liveness probe.
- The existing ruff findings were cleared.
- Tests that reach external providers are marked `network` and excluded from
  CI.
- `docs/deployment/README.md` maps the pieces onto Azure and lists the gaps.

Tests and results:
- 343 passed with the live catalogue, excluding `network` tests. The one
  `network` test failed here because HYCOM was unreachable from this
  sandbox; that failure is external to this change.
- ruff: clean. mypy: no issues outside the debt list.
- Smoke test of `create_default_app` against PostGIS:
  - ready (200) on a migrated catalogue;
  - 503 "the catalogue database could not be reached" on a missing database;
  - the request id was echoed.

Not verified:
- The image and the workflow have not run: this sandbox has no Docker, so
  CI is their first execution.
- Nothing has been pushed.

Review:
Agents A and B were out of limits, so Agent C reviewed this as moderator.
It is not an independent review. A non-author should read
`serving/observability.py` and `ingestion/storage/migrate.py` when next
available.

Follow-ups:
- Blob object-store adapter (Agent A). Until it exists, a Container Apps
  deployment needs an Azure Files mount.
- The web client should read `observation_failure`; this is done when the
  S6/S7 branch is merged.
- The mypy debt list.
- pytest is still in the runtime requirements.
