"""Shared fixtures.

Test database strategy: one throwaway database per *test session*, created from
the same server the dev workflow uses and dropped afterwards. Real Postgres, real
constraints, real transaction semantics -- a fake or SQLite would let us "pass"
tests whose correctness claims do not hold (no unique-index blocking, no
SKIP LOCKED, no real isolation levels).

`RELAY_TEST_DATABASE_URL` overrides the server, which is how CI points at a
service container instead of the `pgserver` wheel.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from relay import migrations
from relay.app import create_app
from relay.config import Settings


def _base_dsn() -> str:
    env = os.environ.get("RELAY_TEST_DATABASE_URL")
    if env:
        return env

    import pgserver  # dev-only dependency

    return pgserver.get_server(
        os.environ.get("RELAY_PGDATA", "/tmp/relay-pgdata"), cleanup_mode=None
    ).get_uri()


@pytest.fixture(scope="session")
def base_dsn() -> str:
    return _base_dsn()


@pytest.fixture(scope="session")
def migrated_database(base_dsn: str) -> Iterator[str]:
    """A database with every migration applied, dropped at the end of the session."""
    name = f"relay_test_{uuid.uuid4().hex[:10]}"
    # CREATE/DROP DATABASE cannot run inside a transaction block -> autocommit.
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        url = psycopg.conninfo.make_conninfo(base_dsn, dbname=name)
        try:
            with psycopg.connect(url) as conn:
                migrations.apply_all(conn)
            yield url
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def empty_database(base_dsn: str) -> Iterator[str]:
    """A fresh database with no migrations applied -- for testing the runner itself."""
    name = f"relay_mig_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        url = psycopg.conninfo.make_conninfo(base_dsn, dbname=name)
        try:
            yield url
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def settings(migrated_database: str) -> Settings:
    return Settings(database_url=migrated_database, env="test", log_level="WARNING")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # `with` runs the lifespan: the pool is open for the duration of the test.
    with TestClient(app) as test_client:
        yield test_client
