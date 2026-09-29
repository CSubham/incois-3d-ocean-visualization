"""Versioned migrations for the S3 catalogue.

Each schema change is one numbered SQL file under ``migrations/``, applied
once, in order, and recorded with its checksum in ``schema_migration``. All
pending migrations apply in one transaction, so a failure part-way leaves
the catalogue exactly as it was. A recorded migration whose file has since
changed is refused rather than silently diverging. A transaction-scoped advisory lock serialises runners, so
several containers starting at once cannot migrate concurrently.

Code declares the schema version it needs (``expected_version``); readiness
compares it with the database, so a service never answers from a catalogue
older than its code. Run with ``python -m ingestion.storage.migrate``
(``--check`` only reports).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from ingestion.domain.errors import IngestionError

MIGRATIONS = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
#: Arbitrary constant naming this runner's advisory lock.
_LOCK_KEY = 6_067_000_001

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     integer PRIMARY KEY,
    name        text NOT NULL,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(IngestionError):
    """Migrations could not be discovered or applied safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SchemaStatus:
    current: int | None
    expected: int
    pending: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.current == self.expected and not self.pending

    @property
    def reason(self) -> str | None:
        if self.ready:
            return None
        if self.current is None:
            return "the catalogue has no migrations applied"
        if self.current > self.expected:
            return (f"the catalogue is at schema {self.current}, newer than "
                    f"this code's {self.expected}")
        return (f"the catalogue is at schema {self.current}; this code needs "
                f"{self.expected} ({', '.join(self.pending)} pending)")


def discover(directory: Path = MIGRATIONS) -> tuple[Migration, ...]:
    """Every migration, in order; numbering must run 1, 2, 3 without gaps."""
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            raise MigrationError(f"{path.name} is not named NNNN_description.sql")
        migrations.append(Migration(int(match.group(1)), path.stem,
                                    path.read_text(encoding="utf-8")))
    for position, migration in enumerate(migrations, start=1):
        if migration.version != position:
            raise MigrationError(
                f"migration {migration.name} is out of sequence; expected "
                f"version {position}")
    if not migrations:
        raise MigrationError("no migrations were found")
    return tuple(migrations)


def expected_version(directory: Path = MIGRATIONS) -> int:
    return discover(directory)[-1].version


def _applied(connection: Any) -> dict[int, str]:
    exists = connection.execute(
        "SELECT to_regclass('public.schema_migration') IS NOT NULL").fetchone()[0]
    if not exists:
        return {}
    return {version: checksum for version, checksum in connection.execute(
        "SELECT version, checksum FROM schema_migration ORDER BY version")}


def _verify(applied: dict[int, str], migrations: tuple[Migration, ...]) -> None:
    known = {m.version: m for m in migrations}
    for version, checksum in applied.items():
        migration = known.get(version)
        if migration is None:
            raise MigrationError(
                f"the catalogue records migration {version}, which this code "
                "does not have; it is newer than this code")
        if migration.checksum != checksum:
            raise MigrationError(
                f"migration {migration.name} was changed after it was applied; "
                "add a new migration instead of editing an applied one")


def migrate(dsn: str, *, directory: Path = MIGRATIONS,
            connect: Callable[..., Any] = psycopg.connect) -> list[str]:
    """Apply pending migrations in order; returns the names applied."""
    migrations = discover(directory)
    applied_now: list[str] = []
    with connect(dsn) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            connection.execute(_LEDGER)
            applied = _applied(connection)
            _verify(applied, migrations)
            for migration in migrations:
                if migration.version in applied:
                    continue
                connection.execute(migration.sql)
                connection.execute(
                    "INSERT INTO schema_migration (version, name, checksum) "
                    "VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum))
                applied_now.append(migration.name)
    return applied_now


def schema_status(dsn: str, *, directory: Path = MIGRATIONS,
                  connect: Callable[..., Any] = psycopg.connect,
                  connect_timeout: int = 5) -> SchemaStatus:
    """Where the catalogue stands against this code; read-only."""
    migrations = discover(directory)
    with connect(dsn, connect_timeout=connect_timeout) as connection:
        applied = _applied(connection)
    _verify(applied, migrations)
    pending = tuple(m.name for m in migrations if m.version not in applied)
    return SchemaStatus(current=max(applied) if applied else None,
                        expected=migrations[-1].version, pending=pending)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingestion.storage.migrate",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report the catalogue's schema state; apply nothing")
    arguments = parser.parse_args(argv)
    dsn = os.environ.get("INGESTION_CATALOGUE_DSN")
    if not dsn:
        print("INGESTION_CATALOGUE_DSN is not set", file=sys.stderr)
        return 2
    try:
        if arguments.check:
            status = schema_status(dsn)
            print(f"schema {status.current} of {status.expected}"
                  + (f"; {status.reason}" if status.reason else "; current"))
            return 0 if status.ready else 1
        applied = migrate(dsn)
    except (MigrationError, psycopg.Error) as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    print("applied: " + ", ".join(applied) if applied else "already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
