# Deployment: backend through S6

What the repository gives a deployment today, and what an Azure deployment
still needs. No Azure resource has been created; the owner creates them.

## One image, several processes

`Dockerfile` builds one backend image (ingestion, processing and serving
code; no tests, data or credentials; runs as uid 10001). The command picks
the process:

| Process | Command | Azure target |
|---|---|---|
| S5 API (default) | `uvicorn serving.compose:create_default_app --factory …` | Container Apps app, ingress on 8000 |
| Catalogue migrations | `python -m ingestion.storage.migrate` | Container Apps Job, run before each API revision |
| S2 ingestion | `uvicorn ingestion.web:app --host 0.0.0.0 --port 8000` | Container Apps app, internal ingress |

The browser app is not in this image. It is built separately (S6/S7) for
Static Web Apps; a Static Web Apps linked backend proxies `/api` to the API
so the browser stays same-origin, which the API assumes (it opens no CORS).

## Configuration

Environment only; `.env.example` lists every setting. Required:

- `INGESTION_CATALOGUE_DSN`: no default. On Azure, include `sslmode=require`,
  and keep the value in a Container Apps secret or Key Vault reference.
- `INGESTION_OBJECT_STORE`: a directory. See the gaps below.

Optional: `INGESTION_CATALOGUE_CONNECT_TIMEOUT` (default 5 s),
`SERVING_MAX_POINTS`, `SERVING_MAX_CELLS`, `SERVING_MAX_MARKERS`,
`SERVING_RETAINED_JOBS`, `LOG_LEVEL`, and `LOG_FORMAT` (`json` or `text`).

## Probes and logs

- Liveness is `GET /health/live`. It only proves the process answers.
- Readiness is `GET /health/ready`. It returns 503 with a reason for each
  check until two things hold:
  - the catalogue is reachable at exactly this code's schema version;
  - the object store is present.
  A new revision therefore takes no traffic until its migration job has run.
- Logs are one JSON object per line on stdout.
- Each request writes one access line. The line carries its `request_id`,
  which is also echoed as `X-Request-ID`.

## Catalogue

PostgreSQL Flexible Server 16 with PostGIS. Before the first migration,
allow-list the extension (server parameter `azure.extensions` = `POSTGIS`).
Migration 0001 then creates it. `--check` reports without applying anything,
and exits 1 when the schema is not current.

## CI

`.github/workflows/ci.yml` runs on every push to main and on pull requests:

- ruff, then mypy (modules listed as debt in `pyproject.toml` are exempt;
  the list may only shrink);
- the test suite against a PostGIS service container, excluding tests
  marked `network`;
- migrate and `--check`;
- building the image and probing `/health/live` in a running container;
- the web app's tests, type-check and production build. The build is kept
  as the `web-dist` artifact, which is what Static Web Apps serves.

Nothing is pushed to a registry yet. That needs ACR and credentials from the
owner.

## Gaps before a real deployment

- **Object store:** only `LocalObjectStore` exists. On Container Apps, use
  either an Azure Files mount or the Blob adapter (agent A's lane). The
  adapter is the intended route.
- **Unverified here:** the image was not built in this environment (no
  Docker in the agent sandbox). CI is its first build.
- **Runtime requirements:** they still include pytest.
