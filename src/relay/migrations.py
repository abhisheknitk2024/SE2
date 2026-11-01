"""Forward-only SQL migrations, with an integrity ledger.

Conventions
-----------
* Files live in ``migrations/`` and are named ``NNNN_snake_name.sql``.
* **Migrations are immutable once applied.** The ledger stores a checksum of the
  file; editing an applied migration raises instead of silently producing two
  databases that disagree. Roll forward with a new file; there are no downgrades
  (pre-v1, nobody has data worth rolling back).
* Each file is applied inside the caller's transaction, so a failing statement
  leaves neither a half-migrated schema nor a ledger row claiming success.
* An advisory transaction lock serializes concurrent runners -- two pods starting
  at once on deploy would otherwise race on the same ``CREATE TABLE``.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection
from psycopg.rows import dict_row

#: Schema version this build of the code expects. /readyz refuses traffic when the
#: database disagrees -- it catches the classic "deployed the app, forgot to run
#: migrations" failure at boot instead of at the first request.
EXPECTED_SCHEMA_VERSION = 1

# Arbitrary, stable, project-scoped constants. Advisory locks are global to the
# database, so the values must never collide with another feature's lock.
_LOCK_KEY = 7_204_331

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer     PRIMARY KEY,
    name       text        NOT NULL,
    checksum   text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""

_FILENAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str

    @property
    def label(self) -> str:
        return f"{self.version:04d}_{self.name}"


def migrations_dir() -> Path:
    override = os.environ.get("RELAY_MIGRATIONS_DIR")
    if override:
        return Path(override)
    # src/relay/migrations.py -> repository root / migrations
    return Path(__file__).resolve().parents[2] / "migrations"


def discover(directory: Path | None = None) -> list[Migration]:
    directory = directory or migrations_dir()
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")

    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if match is None:
            raise MigrationError(f"bad migration filename: {path.name} (want NNNN_name.sql)")
        body = path.read_bytes()
        found.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                path=path,
                sql=body.decode("utf-8"),
                checksum=hashlib.sha256(body).hexdigest(),
            )
        )

    versions = [m.version for m in found]
    duplicates = {v for v in versions if versions.count(v) > 1}
    if duplicates:
        raise MigrationError(f"duplicate migration versions: {sorted(duplicates)}")
    return found


def apply_all(conn: Connection, directory: Path | None = None) -> list[Migration]:
    """Apply every pending migration. Returns the ones applied by this call."""
    pending_candidates = discover(directory)  # validate all filenames before any DDL

    with conn.transaction():
        # Own cursor with its own row factory: the runner must behave identically
        # whether the caller hands us a plain psycopg connection (scripts/migrate.py)
        # or a pooled one configured with dict_row (the app).
        cur = conn.cursor(row_factory=dict_row)
        cur.execute(_LEDGER_DDL)
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))

        cur.execute("SELECT version, checksum FROM schema_migrations")
        applied = {row["version"]: row["checksum"] for row in cur.fetchall()}

        newly_applied: list[Migration] = []
        for migration in pending_candidates:
            recorded = applied.get(migration.version)
            if recorded is not None:
                if recorded != migration.checksum:
                    raise MigrationError(
                        f"{migration.path.name} changed after it was applied "
                        f"(recorded {recorded[:12]}, file {migration.checksum[:12]}). "
                        "Migrations are immutable: add a new file instead."
                    )
                continue

            cur.execute(migration.sql)
            cur.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                (migration.version, migration.name, migration.checksum),
            )
            newly_applied.append(migration)

    return newly_applied
