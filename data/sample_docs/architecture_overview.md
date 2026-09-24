# Architecture Overview

## Request Path

Public traffic enters through the CDN, which terminates TLS and forwards to the API gateway. The
gateway authenticates the request, enforces per-key rate limits, and routes to backend services.
Services communicate synchronously over gRPC with a default deadline of 2 seconds, and
asynchronously through the event bus.

## Core Services

- `identity-svc` — users, sessions, API keys, and token issuance.
- `ledger-svc` — the double-entry ledger that records every balance change. It is the source of
  truth for money; no other service stores balances.
- `billing-svc` — invoices, subscriptions, and dunning. It reads from the ledger but never writes
  balance changes directly.
- `notify-svc` — email, SMS, and push notifications, with per-user preference checks.
- `search-svc` — full-text search over customer records, rebuilt from the event bus.

## Event Bus

Events are published to Kafka topics named `<domain>.<entity>.<event>`, for example
`billing.invoice.paid`. Topics retain events for 7 days. Consumers must be idempotent, since
events can be redelivered after a consumer restart.

## Datastores

Transactional data lives in PostgreSQL. Caching uses Redis with a default TTL of 5 minutes;
nothing may treat the cache as a source of truth.
