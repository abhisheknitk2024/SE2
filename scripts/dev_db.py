#!/usr/bin/env python3
"""Start (or reuse) the local development Postgres and print its DSN.

This sandbox has no Docker and no system Postgres, so dev/test use the Postgres 16
binaries shipped by the `pgserver` wheel. The cluster is disposable: `rm -rf` the
data directory and `make migrate` rebuilds it. Production points RELAY_DATABASE_URL
at a real server and never uses this script.

Usage:
    python scripts/dev_db.py            # start, print DSN, exit (postmaster keeps running)
    RELAY_PGDATA=/tmp/other python scripts/dev_db.py
"""

from __future__ import annotations

import os
import sys

import pgserver

DEFAULT_PGDATA = "/tmp/relay-pgdata"


def start(data_dir: str = DEFAULT_PGDATA) -> str:
    """Return the DSN of a running cluster, starting one if necessary."""
    server = pgserver.get_server(data_dir, cleanup_mode=None)
    return server.get_uri()


def main() -> int:
    data_dir = os.environ.get("RELAY_PGDATA", DEFAULT_PGDATA)
    dsn = start(data_dir)
    print(f"RELAY_PGDATA={data_dir}")
    print(f"RELAY_DATABASE_URL={dsn}")
    print("(export RELAY_DATABASE_URL, or set RELAY_PGDATA to change the default)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
