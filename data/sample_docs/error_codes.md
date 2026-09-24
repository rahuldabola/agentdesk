# API Error Code Reference

Every error response carries a machine-readable `code` alongside the HTTP status. Clients should
branch on the code, never on the human-readable message, which may change without notice.

## Authentication Errors

- `AUTH-1001` — the bearer token is missing from the request. Returned with HTTP 401.
- `AUTH-1002` — the token has expired. Refresh it with the refresh token; do not re-prompt the user.
- `AUTH-1003` — the token was revoked, usually because the user signed out everywhere or an
  administrator disabled the account. Clients must discard both tokens.
- `AUTH-1007` — the API key lacks the scope required by the endpoint. The response lists the
  missing scope in `details.required_scope`.

## Request Errors

- `REQ-2001` — the body is not valid JSON.
- `REQ-2004` — a required field is absent; `details.field` names it.
- `REQ-2009` — the idempotency key was reused with a different request body. The original
  response is not replayed; the client must generate a new key.

## Throttling

- `RATE-4290` — the per-key request quota was exceeded. Honour the `Retry-After` header.
- `RATE-4291` — the account-wide concurrency cap of 50 in-flight requests was exceeded. This is
  separate from the per-minute quota and clears as soon as requests complete.

## Payment Errors

- `PAY-4012` — the card was declined by the issuer. Safe to retry with a different card only.
- `PAY-4015` — the payment requires 3-D Secure authentication; redirect the customer to the
  returned `challenge_url`.
- `PAY-5030` — the payment processor is unavailable. Retry with exponential backoff; the request
  is idempotent if an idempotency key was supplied.

## Server Errors

- `SYS-5000` — an unexpected internal error. Includes a `trace_id` that support can use to find
  the request in the tracing system.
- `SYS-5031` — the service is in read-only maintenance mode. Writes are rejected, reads succeed.
