# Design Doc — Relay: reliable outbound webhook delivery

> Template + worked example. Replace the `<>` bits, delete what doesn't apply.
> Target length: 2 pages. If it's longer, you haven't decided enough things.

| | |
|---|---|
| **Author** | <you> |
| **Status** | Draft → Review → Accepted |
| **Date** | 2026-11-01 |
| **Reviewers** | <a senior eng you trust> |

## 1. Problem

Any product that has third-party integrations eventually needs to *push* events to customer endpoints. Doing this naively (`POST` in the request path) fails in four predictable ways:

1. The customer's server is down / slow → your user-facing request fails or hangs.
2. Your process crashes between "wrote to DB" and "delivered" → silent event loss.
3. You retry → the customer receives duplicates and double-charges their own customers.
4. One customer's endpoint is slow → your worker pool starves and everyone's latency suffers.

**Goal:** a service that accepts events and delivers them to subscriber URLs with an explicit, documented delivery contract, and that a customer can *observe and repair* (logs, replay) without contacting support.

## 2. Goals / Non-goals

**Goals (v1)**
- G1: at-least-once delivery, HMAC-signed, per-subscription event filtering.
- G2: retries with exponential backoff + jitter; dead-letter queue; manual replay.
- G3: full attempt-level audit trail, queryable in a dashboard.
- G4: per-tenant fairness — a noisy tenant cannot starve others.
- G5: measurable: p99 delivery latency and queue depth under a documented load.

**Non-goals (explicitly out of scope for v1)**
- N1: exactly-once delivery (impossible over HTTP; see §6).
- N2: cross-region replication / active-active.
- N3: consumer-side SDKs (a 10-line verification snippet instead).
- N4: billing, OAuth, UI polish.
- N5: ordering across *different* destinations.

> Writing §2 is the single highest-signal thing in this document. Juniors list what they built; SDE2s list what they refused to build and why.

## 3. Constraints & assumptions

- Single region, single Postgres instance, ≤ a few thousand deliveries/minute (assumption — revisit at 10×).
- Subscribers are untrusted: may be slow, may 500, may be malicious.
- Events are immutable and small (< 64 KB body). Larger payloads → future "reference by ID" pattern.
- Budget: one small VM / free tier. Cost matters; state the monthly number.

## 4. Capacity math (do this even when it's rough)

| Input | Value |
|---|---|
| Events/day | 10,000 |
| Avg subscriptions matching an event | 3 |
| Deliveries/day | 30,000 (≈0.35/s avg, ≈3/s peak) |
| Bytes/delivery row | ~400 B |
| Storage/day | ~12 MB |
| Attempts/day incl. retries (5% fail) | ~32,000 |
| Retention: 30 days of attempts | ~400 MB |

Conclusion: **one Postgres box is 100× oversized for v1.** Do not introduce Kafka to solve a 3 req/s problem, and say so in the doc.

## 5. Design

```
            ┌────────────┐
 POST event │  Relay API │  (auth, validate, idempotency-key check)
            └─────┬──────┘
                  │ single transaction: events + deliveries(pending)
                  ▼
            ┌────────────┐
            │  Postgres  │◀──────────────┐
            └─────┬──────┘               │ attempt log
   claim batch    │                      │
 (FOR UPDATE      ▼                      │
  SKIP LOCKED) ┌────────────┐            │
               │  Worker(s) │─── HMAC ───┤
               └─────┬──────┘   POST     │
                     │                   │
            delivered│failed ─▶ backoff ──┘
                     │
                     └──▶ attempts ≥ max ──▶ DLQ ──▶ Replay (manual)
```

**Data model**

```sql
events(id uuid pk, tenant_id, type, payload jsonb, idempotency_key, created_at,
       unique(tenant_id, idempotency_key))

subscriptions(id, tenant_id, url, secret, event_types text[], active bool,
              max_attempts int default 8)

deliveries(id, event_id, subscription_id, status, attempt_count,
           next_attempt_at, last_error, created_at, updated_at,
           unique(event_id, subscription_id))
  status ∈ pending | in_flight | delivered | dead

attempts(id, delivery_id, attempt_no, request_headers jsonb,
         response_status int, response_body_snippet text,
         duration_ms int, created_at)
```

**Claiming work**

```sql
UPDATE deliveries SET status='in_flight', attempt_count=attempt_count+1
WHERE id IN (
  SELECT id FROM deliveries
  WHERE status='pending' AND next_attempt_at <= now()
  ORDER BY next_attempt_at
  LIMIT 50
  FOR UPDATE SKIP LOCKED
) RETURNING *;
```

**Retry policy:** `delay = min(cap, base * 2^attempt) * random(0.5, 1.5)`, `base=2s`, `cap=6h`, `max_attempts=8`, retry only on network error / 5xx / 429 (honour `Retry-After`); never retry 4xx except 408/429.

**Signature contract:** `X-Relay-Signature: t=<unix>,v1=<hex hmac_sha256(secret, f"{t}.{raw_body}")>`, documented tolerance window (5 min) with a copy-pasteable verification snippet in 3 languages.

**Idempotency:** on `POST /v1/events`, a repeated `Idempotency-Key` returns the original `event_id` with `200` (not a new event). Uniqueness enforced by the DB constraint, not by a read-then-write race.

## 6. Failure modes (the section interviewers actually read)

| Failure | Detection | Handling | Residual risk |
|---|---|---|---|
| Worker dies mid-delivery | row stuck `in_flight` | reaper: `in_flight` older than `claim_timeout` → back to `pending` | duplicate send → covered by at-least-once contract |
| Subscriber slow | per-request timeout (10s) | abort, count as failure, back off | worker slot occupied ≤10s → cap concurrency |
| Subscriber returns 500 | status code | retry with backoff | none |
| Duplicate event from producer | idempotency key | unique constraint → return original | none |
| Noisy tenant floods queue | queue depth per tenant | token bucket per tenant + round-robin claim | fairness is approximate |
| DB down | health check / emit errors | API returns 503; producer retries | events in flight are safe (single transaction) |
| Poison payload (always 400) | `max_attempts` | DLQ + replay after fix | none |

**Why not exactly-once:** delivery is a network call to a system we don't control; the ack can be lost after the receiver processed the message. v1 guarantees **at-least-once + a documented dedupe key** (`X-Relay-Event-Id`) so subscribers can be idempotent. Exactly-once is only achievable by pushing dedupe to the receiver.

## 7. Alternatives considered

| Option | Why rejected |
|---|---|
| **Kafka/RabbitMQ as the queue** | adds a second source of truth → dual-write inconsistency between broker and delivery state; operational cost for a 3 req/s workload. Revisit above ~500 deliveries/s or when we need cross-region consumers. |
| **Redis Streams + consumer groups** | good fit, ~same complexity as Postgres here and loses transactional consistency with the delivery audit log. Kept as the documented next step. |
| **In-process `asyncio` background tasks** | loses everything on deploy/crash; no audit trail. Correctly rejected. |
| **Cron polling every minute** | delivery latency floor of 60s; no concurrency control. |
| **Fire-and-forget in the API request** | couples customer latency to subscriber availability. This is the bug we're fixing. |

## 8. Observability

- **Metrics:** `relay_delivery_attempts_total{outcome}`, `relay_delivery_duration_seconds` (histogram), `relay_queue_depth`, `relay_dlq_size`, `relay_tenant_queue_depth{tenant}`.
- **Logs:** one line per attempt with `trace_id`, `delivery_id`, `subscription_id`, `attempt_no`, `status`, `duration_ms`.
- **Alerts:** DLQ growth > 0 over 10 min; queue depth > 1,000 for 5 min; p99 delivery latency > 60s.
- **Runbook:** see `docs/runbook.md`.

## 9. Rollout

Feature-flagged per tenant → internal tenant first → 1 friendly external tenant → default on. Rollback = flip flag; no schema migration on the read path.

## 10. Open questions

1. Do we need per-destination ordering (single in-flight delivery per subscription)? Costs throughput; needs a lock column + `FOR UPDATE` on the subscription row.
2. Retention window for `attempts` — 7 days to start, then partition/drop.
3. Payload encryption at rest for PII-bearing events?

---

### Reviewer checklist (paste into the PR)

- [ ] Failure table has a row for every dependency
- [ ] At least one alternative rejected with a *number*, not an opinion
- [ ] Non-goals are explicit
- [ ] Capacity math exists
- [ ] Every alert has a runbook action
- [ ] A junior engineer could implement from this doc without asking more than 3 questions
