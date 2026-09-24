# Logging, Metrics and Tracing

## Logging

Services log structured JSON to stdout; the log shipper handles collection. Every line carries
`service`, `env`, `trace_id`, and `level`. Application logs are retained for 30 days in hot
storage and 13 months in cold storage. Audit logs are a separate stream, are immutable, and are
retained for 7 years.

Logging personal data is prohibited. Email addresses, phone numbers, and payment details must be
masked before they reach a log line; the shared logging library does this for known field names.

## Metrics

Metrics are exported in Prometheus format and scraped every 15 seconds. High-cardinality labels
such as user IDs or request IDs must never be used as metric labels, because each distinct value
creates a new time series and can take down the metrics cluster.

## Tracing

Distributed tracing uses OpenTelemetry. Head-based sampling keeps 10% of traces in production,
and every trace that contains an error is kept regardless of sampling. Traces are retained for
14 days.

## Dashboards

Each service owns a golden-signals dashboard showing latency, traffic, errors, and saturation.
