#!/usr/bin/env python3
"""Apply pending migrations. Forward-only; safe to run on every deploy."""

from __future__ import annotations

import sys

import psycopg

from relay import migrations
from relay.config import get_settings


def main() -> int:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        applied = migrations.apply_all(conn)

    if not applied:
        print(f"schema up to date (version {migrations.EXPECTED_SCHEMA_VERSION})")
        return 0

    for migration in applied:
        print(f"applied {migration.label}")
    if applied[-1].version != migrations.EXPECTED_SCHEMA_VERSION:
        print(
            f"WARNING: migrated to {applied[-1].version} but this build expects "
            f"{migrations.EXPECTED_SCHEMA_VERSION}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
