# Relay — build roadmap

The design doc (`README.md`) says *what* and *why*. This file says *in what order*, one
small session per chunk. Each chunk is a vertical slice: code + tests + a one-page
decision record in `docs/decisions/NNNN-<slug>.md`.

Rule for every chunk: **it must be demonstrable** (`make demo` or a named pytest) before
we move on. No chunk depends on a chunk we haven't finished.

## Principles

1. **Walking skeleton first.** A server that boots, talks to real Postgres, and passes one
   test — before any feature. Prevents 3 sessions of yak-shaving at once.
2. **Risk-first ordering after that.** The riskiest correctness property (no duplicate
   events) is proven in chunk 2, not chunk 7.
3. **Real infrastructure.** Postgres 16 locally, real HTTP against a real (fake) subscriber.
   SQLite is banned: it has no `SKIP LOCKED` and no unique-index blocking semantics, i.e.
   it cannot express the two things this project is actually about.
4. **Every decision gets a reason and a rejected alternative.** That is the interview
   material, and it is also what stops us from re-litigating in week 3.
5. **Delete nothing that is written down.** Superseded decisions stay, marked superseded.

## Chunks

| # | Chunk | Deliverable you can see | Decisions locked | Interview concept |
|---|---|---|---|---|
| 0 | **Walking skeleton** | `make dev` boots API; `make test` green; `GET /healthz` → `{db: ok}` | stack, layout, config/secrets, migration tool, test DB strategy, error envelope | layering, 12-factor config, test pyramid |
| 1 | **Schema + event ingestion** | `POST /v1/events` → 1 event + N `pending` deliveries in one transaction | tenancy model, API-key auth, fan-out rule, payload size limit, status codes for validation | transactional fan-out, why one transaction, idempotent *writes* vs reads |
| 2 | **Idempotency key** | 50 concurrent requests with one key → exactly 1 event; replay returns original `event_id` | required vs optional key, fingerprint, replay semantics, 409/422/400, TTL + prune, fail-open vs closed | idempotency, distributed retry safety, check-then-act races |
| 3 | **Claim + deliver** | worker sends HMAC-signed POST to a fake subscriber, logged in `attempts` | claim SQL, concurrency = N workers, timeout budget, signature contract, success/failure state machine | queue semantics without a queue, `SKIP LOCKED`, at-least-once |
| 4 | **Retry, backoff, DLQ, reaper** | flaky subscriber → retries with backoff → `dead` after max attempts | backoff formula, retryable status codes, `Retry-After`, claim timeout, poison handling | failure classification, exponential backoff + jitter, dead-letter queues |
| 5 | **Replay + audit API** | `GET /v1/deliveries?status=dead`, `POST /v1/deliveries/{id}/replay` | replay semantics vs duplicate sends, audit retention, pagination | operator-facing APIs, replayability, retention |
| 6 | **Per-tenant fairness** | noisy tenant cannot starve a quiet one (test with 2 tenants) | token bucket vs round-robin claim, limits per plan, backpressure | noisy-neighbour, admission control, fairness |
| 7 | **Observability + load test** | metrics endpoint, structured logs with `trace_id`, p99 under k6 load | metric names/labels, redaction, SLO targets | golden signals, cardinality, SLO/SLI |
| 8 | **Contract docs + runbook** | `docs/contract.md` + verification snippet in 3 languages + `docs/runbook.md` | tolerance window, header names, versioning | API contracts, backwards compatibility, on-call |

Chunks 3–8 are the queue/delivery half; 0–2 are the correctness half. We stop and re-read
`README.md` §6 before every chunk: if a chunk makes a failure-table row worse, it is wrong.

## Environment (this sandbox)

- Python 3.11, Node 22. **No Docker, no system Postgres, no Go.**
- Postgres 16.2 is available as a Python wheel (`pgserver`), started on demand over a unix
  socket. Bootstrap is scripted (`scripts/bootstrap.sh`) because `.venv/` is not persisted
  between sessions — assume a cold checkout at the start of every session.
- CI (GitHub Actions) gets a service container instead, same migrations, same tests.

## Definition of done, per chunk

1. Code merged on the session branch, tests green.
2. `docs/decisions/NNNN-*.md`: context, decision, alternatives rejected *with a number*,
   consequences.
3. README/ROADMAP updated if the chunk changed a contract.
4. New failure modes appended to the doc's §6 table.
5. 5-line "what I'd say in an interview" summary at the end of the decision record.

## Open decisions (parked on purpose)

- Per-destination ordering: needs one in-flight delivery per subscription → costs throughput.
  Defer until chunk 3 measurements exist. (README §10.1)
- Retention of `attempts`: 7 days, partitioned. Decide in chunk 5. (README §10.2)
- Payload encryption at rest. Out of scope until there is a real PII event type. (README §10.3)
- Dashboard: not a chunk. API + curl/tests only; a UI is not what we are learning here.

## Progress

| # | Chunk | Status | Artifact |
|---|---|---|---|
| 0 | Walking skeleton | **done** — 14 tests, `make check` green | `docs/decisions/0001-walking-skeleton.md` |
| 1 | Schema + event ingestion | next | — |
| 2 | Idempotency key | pending | — |

Two bugs found by the chunk-0 tests, worth remembering: stdlib `logging` rejects
`logger.info(msg, key=value)` (that is structlog syntax — it needs `extra={...}`), and a
helper that reads rows must not inherit the caller's row factory. Both were invisible
until a test exercised the code path.
