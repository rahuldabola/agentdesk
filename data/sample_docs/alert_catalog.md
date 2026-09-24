# Alert Catalog

Each alert below links to the first steps a responder should take. Alert names match the
alerting rules exactly, so they can be searched from a page.

## HighConsumerLag

Fires when a queue consumer group is more than 10,000 messages behind for 10 minutes. Check
whether consumers are crash-looping before scaling them out; adding replicas to a consumer that is
failing on a poison message only multiplies the failures. Poison messages are moved to the
dead-letter queue with `queue-admin dlq move`.

## DiskPressureCritical

Fires when a node's root volume passes 90% utilisation. The usual cause is container logs not
being rotated. Cordon the node, then drain it; do not delete files by hand on a production node.

## CertificateExpiringSoon

Fires 14 days before a certificate expires, which means automatic renewal at 30 days has already
failed. Follow the manual renewal procedure in the platform runbook.

## ReplicationLagHigh

Fires when a database read replica is more than 30 seconds behind the primary. Reads that need
fresh data must be routed to the primary until lag recovers. Persistent lag usually indicates a
long-running transaction on the primary.

## ErrorBudgetBurnFast

Fires when a service is burning its error budget 14 times faster than sustainable over one hour,
which would exhaust a 28-day budget in about 2 days. Treat it as at least a SEV2.
