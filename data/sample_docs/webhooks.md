# Webhooks

## Delivery

Webhook events are delivered as HTTP POST requests with a JSON body. An endpoint must respond
with a 2xx status within 10 seconds, or the delivery is treated as failed. Events are delivered
at least once, so receivers must deduplicate using the `event_id` field.

## Retries

Failed deliveries are retried with exponential backoff over 72 hours: after 1 minute, 5 minutes,
30 minutes, 2 hours, and then every 6 hours until the window closes. After the final failure the
event is moved to the dead-letter view in the developer dashboard, where it can be replayed
manually for up to 30 days.

An endpoint that fails every delivery for 5 consecutive days is disabled automatically and the
account owner is emailed.

## Signatures

Every request carries an `X-Signature-256` header: an HMAC-SHA256 of the raw request body, keyed
with the endpoint's signing secret. Receivers must verify the signature against the raw bytes
before parsing JSON. Requests also carry `X-Webhook-Timestamp`; reject any request whose
timestamp is more than 5 minutes old to prevent replay attacks.

## Throughput

Each endpoint receives at most 25 concurrent deliveries. Events for a single object are
delivered in order; events across different objects are not ordered relative to each other.
