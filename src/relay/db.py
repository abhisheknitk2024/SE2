"""Postgres access: one connection pool, one explicit transaction helper.

Deliberate choices (see docs/decisions/0002-db-access.md once chunk 1 lands):

* A pool, not a connection per request. Connecting to Postgres costs a round trip
  and a backend process on the server; at 3 req/s that is still 3 forks/second
  that we do not need to pay.
* ``autocommit=False``. Every statement is inside a transaction whether or not we
  ask for one, so a forgotten commit fails loudly instead of silently discarding
  writes.
* ``connect_timeout`` set explicitly. Without it, a black-holed database turns a
  readiness probe into a hung thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Database:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self._pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            timeout=5.0,
            kwargs={"row_factory": dict_row, "connect_timeout": 3},
        )

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        """Open the pool without waiting for a connection.

        ``wait=False`` on purpose: the API process must be able to start while the
        database is down. Booting is not the same question as "can I serve" --
        that is what /readyz answers.
        """
        self._pool.open(wait=False)

    def close(self) -> None:
        self._pool.close()

    # -- usage -------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Run a unit of work atomically: commit on success, roll back on error.

        ``conn.transaction()`` (rather than relying on the pool's implicit commit)
        makes the boundary visible at the call site and releases the savepoint /
        transaction before the connection goes back to the pool.
        """
        with self._pool.connection() as conn, conn.transaction():
            yield conn

    def ping(self, *, timeout: float = 1.0) -> None:
        with self._pool.connection(timeout=timeout) as conn:
            conn.execute("SELECT 1")

    def schema_version(self, *, timeout: float = 1.0) -> int:
        """Highest applied migration, or 0 if the schema was never initialized."""
        with self._pool.connection(timeout=timeout) as conn:
            initialized = conn.execute(
                "SELECT to_regclass('public.schema_migrations') AS oid"
            ).fetchone()
            if initialized is None or initialized["oid"] is None:
                return 0
            row = conn.execute(
                "SELECT coalesce(max(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            return int(row["version"]) if row else 0
