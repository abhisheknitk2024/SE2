# Developer quickstart

## First run

```bash
make setup     # venv + dependencies (Python 3.11+)
make db        # start the local Postgres 16, print its DSN
make migrate   # apply migrations
make dev       # http://0.0.0.0:8000
```

`make test` runs the suite against a throwaway database (created and dropped per run).

```bash
curl -s localhost:8000/healthz      # {"status":"ok"}            always, no DB
curl -s localhost:8000/readyz       # {"status":"ok","db":"ok","schema_version":1}
```

There is no Docker in this sandbox; Postgres comes from the `pgserver` wheel and lives in
`/tmp/relay-pgdata` (disposable — `rm -rf` it and re-run `make db && make migrate`).
Override with `RELAY_PGDATA`, or point `RELAY_DATABASE_URL` at any real server.

## Layout

```
src/relay/
  app.py          app factory: middleware, error handlers, lifespan, routers
  api/health.py   /healthz (liveness) and /readyz (readiness + schema gate)
  config.py       env-var settings (RELAY_* prefix)
  db.py           connection pool + transaction helper
  migrations.py   migration discovery, checksums, advisory lock
  log.py          JSON formatter
migrations/       NNNN_snake_name.sql — immutable once applied
scripts/          dev_db.py (local cluster), migrate.py (deploy step)
tests/            pytest, real Postgres, one throwaway DB per session
docs/decisions/   one record per chunk: context, decision, alternatives, consequences
```

## Adding a migration

1. Add `migrations/0002_something.sql`. Never edit `0001_init.sql` (the ledger checksum
   will refuse to run it).
2. Bump `EXPECTED_SCHEMA_VERSION` in `src/relay/migrations.py`.
3. `make migrate`. `/readyz` turns 503 until this is done — that is the point.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `RELAY_ENV` | `dev` | `dev` / `test` / `prod` |
| `RELAY_DATABASE_URL` | local socket DSN | the only thing that changes between environments |
| `RELAY_LOG_LEVEL` | `INFO` | |
| `RELAY_DB_POOL_MIN_SIZE` / `MAX_SIZE` | `1` / `10` | cap the pool explicitly |
| `RELAY_PGDATA` | `/tmp/relay-pgdata` | local cluster location only |
| `RELAY_TEST_DATABASE_URL` | — | point tests at a real/CI server instead of `pgserver` |

## Troubleshooting

- **`/readyz` → 503, `db: unavailable`** — the cluster is not running: `make db`.
- **`/readyz` → 503, `schema_out_of_date`** — `make migrate`, or your code expects a
  version the database does not have yet.
- **`MigrationError: ... changed after it was applied`** — you edited an applied file.
  Revert it and add a new migration; on a dev box, `rm -rf /tmp/relay-pgdata` is fine,
  never on a shared environment.
- **port 8000 busy** — `make dev PORT=8010`.
