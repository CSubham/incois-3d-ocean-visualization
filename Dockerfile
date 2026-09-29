# syntax=docker/dockerfile:1
#
# The backend image: one image, several processes, chosen by command.
#
#   API (S5, default)   uvicorn serving.compose:create_default_app --factory ...
#   Migrations (job)    python -m ingestion.storage.migrate
#   Ingestion (S2)      uvicorn ingestion.web:app --host 0.0.0.0 --port 8000
#
# Configuration arrives only by environment (see .env.example); the image
# carries no credentials and no data. Runs as an unprivileged user.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SERVING_WEB_ROOT=""

WORKDIR /app

COPY ingestion/requirements.txt ingestion/requirements.txt
RUN pip install -r ingestion/requirements.txt

COPY ingestion ingestion
COPY processing processing
COPY serving serving

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001

EXPOSE 8000

# The app writes its own JSON access line per request, so uvicorn's is off.
# TLS ends at the platform ingress, which sets the forwarded headers.
CMD ["uvicorn", "serving.compose:create_default_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--no-access-log", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
