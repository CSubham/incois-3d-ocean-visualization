"""Versioned catalogue migrations: discovery, ledger, status and safety."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ingestion.storage.migrate import (
    MIGRATIONS, MigrationError, SchemaStatus, discover, expected_version,
    main, migrate, schema_status,
)

TEST_DATABASE = "incois_migrations_test"


def _write(directory: Path, **files: str) -> Path:
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def test_the_repository_migrations_are_numbered_without_gaps():
    migrations = discover()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "0001_catalogue_baseline"
    assert expected_version() == migrations[-1].version


@pytest.mark.parametrize("files, message", [
    ({"0001_a.sql": "", "0003_c.sql": ""}, "out of sequence"),
    ({"1_a.sql": ""}, "NNNN_description"),
    ({}, "no migrations"),
])
def test_bad_migration_sets_are_refused(tmp_path, files, message):
    with pytest.raises(MigrationError, match=message):
        discover(_write(tmp_path, **files))


def test_status_explains_every_state():
    assert SchemaStatus(2, 2, ()).ready
    assert "no migrations" in SchemaStatus(None, 2, ("0001_a", "0002_b")).reason
    assert "0002_b pending" in SchemaStatus(1, 2, ("0002_b",)).reason
    assert "newer than this code" in SchemaStatus(3, 2, ()).reason


def test_the_command_needs_a_catalogue(monkeypatch, capsys):
    monkeypatch.delenv("INGESTION_CATALOGUE_DSN", raising=False)
    assert main(["--check"]) == 2
    assert "INGESTION_CATALOGUE_DSN is not set" in capsys.readouterr().err


# -- live: a disposable database on the local test PostGIS -------------------

def _live_dsn() -> str:
    base = os.environ.get("INGESTION_CATALOGUE_DSN")
    if not base:
        pytest.skip("INGESTION_CATALOGUE_DSN is not set")
    parameters = conninfo_to_dict(base)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"} \
            or parameters.get("port") != "5433":
        pytest.skip("live migration tests run only against the local PostGIS on 5433")
    admin = make_conninfo(**{**parameters, "dbname": "postgres"})
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=3) as connection:
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DATABASE)))
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DATABASE)))
    except psycopg.OperationalError as exc:
        pytest.skip(f"local PostGIS is not reachable: {type(exc).__name__}")
    return make_conninfo(**{**parameters, "dbname": TEST_DATABASE})


@pytest.mark.live
def test_a_fresh_catalogue_is_migrated_once_and_reports_current():
    dsn = _live_dsn()
    assert schema_status(dsn).reason == "the catalogue has no migrations applied"

    assert migrate(dsn) == [m.name for m in discover()]
    assert migrate(dsn) == []
    status = schema_status(dsn)
    assert status.ready and status.current == expected_version()


@pytest.mark.live
def test_a_catalogue_built_before_migrations_existed_is_adopted_in_place():
    dsn = _live_dsn()
    baseline = (MIGRATIONS / "0001_catalogue_baseline.sql").read_text(encoding="utf-8")
    with psycopg.connect(dsn) as connection:
        connection.execute(baseline)   # how catalogues were set up by hand
        connection.execute(
            "INSERT INTO dataset_version (import_id, source_id, source_name, dataset_id, "
            "dataset_name, source_kind, geometry, object_ref) "
            "VALUES ('kept', 's', 'S', 'd', 'D', 'remote', 'grid', 'ref')")

    migrate(dsn)
    with psycopg.connect(dsn) as connection:
        kept = connection.execute("SELECT count(*) FROM dataset_version").fetchone()[0]
    assert kept == 1
    assert schema_status(dsn).ready


@pytest.mark.live
def test_an_edited_applied_migration_is_refused(tmp_path):
    dsn = _live_dsn()
    directory = _write(tmp_path, **{"0001_first.sql": "CREATE TABLE t (a int);"})
    migrate(dsn, directory=directory)
    _write(directory, **{"0001_first.sql": "CREATE TABLE t (a bigint);"})

    with pytest.raises(MigrationError, match="changed after it was applied"):
        migrate(dsn, directory=directory)
    with pytest.raises(MigrationError, match="changed after it was applied"):
        schema_status(dsn, directory=directory)


@pytest.mark.live
def test_a_failing_migration_leaves_the_catalogue_unchanged(tmp_path):
    dsn = _live_dsn()
    directory = _write(tmp_path, **{
        "0001_good.sql": "CREATE TABLE good (a int);",
        "0002_bad.sql": "CREATE TABLE bad (a nonexistent_type);",
    })
    with pytest.raises(psycopg.Error):
        migrate(dsn, directory=directory)
    with psycopg.connect(dsn) as connection:
        tables = {r[0] for r in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert "good" not in tables and "schema_migration" not in tables
