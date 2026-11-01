"""The migration runner is infrastructure: it earns tests like any other code.

These tests exist because a broken runner corrupts every environment at once, and
because "run migrations twice" is the most common thing a deploy pipeline does.
"""

from __future__ import annotations

import psycopg
import pytest

from relay import migrations


def test_applies_pending_migrations_once(empty_database: str) -> None:
    with psycopg.connect(empty_database) as conn:
        first = migrations.apply_all(conn)
        second = migrations.apply_all(conn)

        assert [m.version for m in first] == [1]
        assert second == []
        count = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        assert count == 1


def test_failed_migration_leaves_no_partial_state(tmp_path, empty_database: str) -> None:
    """A migration is one transaction: the ledger row and the DDL live or die together."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_init.sql").write_text("CREATE TABLE t1 (a int);")

    with psycopg.connect(empty_database) as conn:
        migrations.apply_all(conn, directory)
        (directory / "0002_broken.sql").write_text(
            "CREATE TABLE t2 (a int); SELECT this_function_does_not_exist();"
        )

        with pytest.raises(psycopg.errors.UndefinedFunction):
            migrations.apply_all(conn, directory)

        applied = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
        assert applied == [1]
        assert conn.execute("SELECT to_regclass('t2')").fetchone()[0] is None


def test_editing_an_applied_migration_is_refused(tmp_path, empty_database: str) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    path = directory / "0001_init.sql"
    path.write_text("CREATE TABLE t1 (a int);")

    with psycopg.connect(empty_database) as conn:
        migrations.apply_all(conn, directory)
        path.write_text("CREATE TABLE t1 (a int, b int);")  # rewritten history

        with pytest.raises(migrations.MigrationError, match="changed after it was applied"):
            migrations.apply_all(conn, directory)


def test_expected_schema_version_matches_the_newest_file() -> None:
    """Guards the readiness gate: code and migrations must agree, or every pod is unready."""
    on_disk = max(m.version for m in migrations.discover())
    assert on_disk == migrations.EXPECTED_SCHEMA_VERSION


def test_bad_filename_is_rejected(tmp_path) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "init.sql").write_text("SELECT 1;")

    with pytest.raises(migrations.MigrationError, match="bad migration filename"):
        migrations.discover(directory)
