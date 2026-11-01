# 0001 — Walking skeleton

- **Status:** accepted
- **Date:** 2026-11-01
- **Chunk:** 0 (`ROADMAP.md`)
- **Supersedes:** none

## Context

The design doc (`README.md`) describes a webhook delivery service but there is no code
and no infrastructure. Before any product decision can be made we need a process that
boots, a database that is real, a migration path that is safe to run on every deploy,
and a test harness that exercises all three. Anything else is a feature built on sand.

Constraint discovered while building this: **the sandbox has no Docker, no system
Postgres, and no Go toolchain.**

## Decisions

### D1 — Python 3.11 + FastAPI + psycopg 3, raw SQL, no ORM

Chosen because the substance of chunks 2–4 *is* SQL: `INSERT ... ON CONFLICT`, a
`unique` index used as a lock, `FOR UPDATE SKIP LOCKED`, isolation levels. An ORM
generates exactly those statements and hides the part we are trying to learn.

Rejected: **SQLAlchemy** — would have blurred the single-transaction fan-out in chunk 1
and the claim statement in chunk 3. Rejected: **Go** — not installable here, so no test
could ever run; a design we cannot execute is a design we cannot validate. Rejected:
**TypeScript/Fastify** — equally good engineering, but the author's stronger interview
language is Python, and this project doubles as interview material.

### D2 — Real Postgres 16 in development, never SQLite

SQLite would let us "finish" chunks whose correctness claims are untestable: it has no
`SKIP LOCKED`, no real concurrent unique-index blocking, and different isolation
semantics. Every claim in `README.md` §6 depends on those.

Dev/test Postgres comes from the `pgserver` wheel (Postgres 16.2 binaries over a unix
socket, ~1 s to start). CI and production use `RELAY_DATABASE_URL` instead, so the code
path is identical; only the DSN differs.

### D3 — Forward-only SQL migrations + a ledger table, no Alembic

`migrations/NNNN_name.sql`, applied in order, recorded in `schema_migrations`.

- No downgrades pre-v1: rolling back a schema with no users is a fiction, and
  auto-generated downgrade code is where migration bugs hide.
- Alembic rejected: it brings offline-mode/autogenerate machinery and an ORM-shaped
  mental model, for a project with ~6 tables and no ORM.

### D4 — Ledger checksums + advisory lock

`apply_all` stores `sha256` of each file. Editing an applied migration raises
`MigrationError` instead of silently producing two databases that disagree — the failure
is caught at deploy time, not three weeks later in production.

`pg_advisory_xact_lock` serializes concurrent runners: two pods starting simultaneously
would otherwise both try `CREATE TABLE` and one would crash-loop.

Each migration runs inside **one transaction** with its ledger row, so a half-applied
migration cannot exist (`test_failed_migration_leaves_no_partial_state`).

### D5 — Two probes, and readiness gates on schema version

`/healthz` is liveness only: it must not touch the database. If it did, a 30-second
database blip would make the orchestrator kill every API pod at once — turning a slow
dependency into a total outage. `/readyz` checks the database and that the applied
schema equals `EXPECTED_SCHEMA_VERSION`, so "deployed the app, forgot to migrate"
manifests as *not ready* rather than as 500s from the first real request.

Rejected: one `/health` that pings the DB (the classic cascading-restart bug).
Cost accepted: two endpoints and one extra constant to keep in sync — enforced by
`test_expected_schema_version_matches_the_newest_file`.

### D6 — One error envelope, stable codes, opaque 500s

`{"error": {"code", "message", "request_id"}}` with codes like `not_found`,
`validation_error`. Clients branch on `code`; `message` is for humans and may change.

Rejected: FastAPI's default `{"detail": ...}` — its *shape* varies (a string for
`HTTPException`, a list of objects for validation errors), which forces every client to
special-case it. Unhandled exceptions return `internal_error` with no detail: driver
errors and connection strings are a data-leak vector (`test_unhandled_exception_is_opaque_and_enveloped`
asserts a fake DSN password never reaches the response body).

**Known gap:** validation (422) bodies are not enveloped yet — there are no validated
endpoints until chunk 1, and shipping an untested handler for an endpoint that does not
exist is speculation.

### D7 — Request correlation id, validated on the way in

`X-Request-Id` is accepted from the caller, else generated. Accepted only if ≤ 64 chars,
ASCII and printable: echoing arbitrary client input into logs and headers is log
injection and header splitting. Every log line carries it, so an API request and (later)
a worker attempt can be joined by grep.

### D8 — One JSON log line per request; uvicorn's access log disabled

Structured, machine-parseable, single line. uvicorn's own access log duplicates it
without the `request_id`, so it is turned off rather than left to interleave.

### D9 — Pool of 1–10 connections, `connect_timeout=3`, `open(wait=False)`

Booting is not the same question as "can I serve": the process starts even when the
database is down, and `/readyz` answers the second question with a 1-second timeout so a
probe can never hang.

## Consequences

- Cold checkout is two commands (`make setup`, `make db && make migrate`); `.venv` and the
  dev cluster live outside git and outside snapshots, so assume nothing survives a session.
- A schema change now requires bumping `EXPECTED_SCHEMA_VERSION` **and** adding a file;
  the test suite refuses to let those drift.
- No CI yet. `make check` is exactly what CI will run; wiring GitHub Actions is a
  ten-minute task whenever we want it.
- Two packages (`psycopg`, `fastapi`) pinned by exact version: reproducibility over
  novelty, with a dev-only dependency (`pgserver`) that never ships to production.

## What I'd say in an interview

> We split liveness from readiness because a health check that pings the database makes
> an orchestrator restart every pod during a database blip — the health check turns a
> dependency slowdown into a cascading outage. Readiness also compares the applied schema
> version to the version the build expects, so a deploy that skips migrations shows up as
> "not ready" instead of as 500s.
>
> Migrations are forward-only SQL files with a checksummed ledger run under an advisory
> lock. The checksum catches edited-after-applied migrations; the lock makes concurrent
> pod starts safe; one transaction per migration means no half-applied schema.
>
> I develop against real Postgres rather than SQLite because the design depends on
> behaviour SQLite does not have — `SKIP LOCKED` and concurrent unique-index blocking.
