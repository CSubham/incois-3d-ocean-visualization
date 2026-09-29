"""Request correlation and structured logs for the serving process.

Every request carries an id: the caller's ``X-Request-ID`` when it is a
safe token, otherwise a fresh one. The id is echoed on the response, bound
to every log record made while handling the request, and written on one
access line per request. ``configure_logging`` makes those records one JSON
object per line, which is what a log collector reads from stdout.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

access_log = logging.getLogger("serving.access")
_HANDLER = "serving.stdout"

#: LogRecord attributes that are not caller-supplied extras.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def current_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per record; extras passed with ``extra=`` included."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
                    + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = current_request_id()
        if request_id is not None:
            entry["request_id"] = request_id
        entry.update({key: value for key, value in vars(record).items()
                      if key not in _STANDARD and not key.startswith("_")})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


JsonFormatter.converter = time.gmtime


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Route the root logger to stdout, as JSON unless ``fmt`` is 'text'.

    Idempotent: replaces only the handler it installed before, so handlers
    a host added (a test harness, a platform agent) stay in place.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER)
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if h.get_name() != _HANDLER]
    root.addHandler(handler)
    root.setLevel(level.upper())


class RequestContext:
    """ASGI middleware: assign the request id and write the access line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(HEADER.lower().encode(), b"")
        text = supplied.decode("latin-1")
        request_id = text if _SAFE_ID.match(text) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (HEADER.lower().encode(), request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            access_log.info("request", extra={
                "method": scope["method"], "path": scope["path"],
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
            _request_id.reset(token)
