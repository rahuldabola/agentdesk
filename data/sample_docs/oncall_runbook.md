# On-call Runbook

## Rotation

On-call is a weekly rotation running Monday 09:00 UTC to the following Monday 09:00 UTC. Each
service has a primary and a secondary. The primary acknowledges pages within 5 minutes; an
unacknowledged page escalates to the secondary after 10 minutes, then to the engineering manager
after a further 10 minutes.

Nobody is on-call more than one week in any four-week period. Engineers paged outside business
hours take compensatory time off in the following week, and this is expected rather than optional.

## Handover

Handover happens Monday morning before the rotation flips. The outgoing primary writes a summary
covering incidents during the week, alerts that fired without warranting action, deploys still
being watched, and any known-fragile areas. The incoming primary confirms receipt in writing.

## Common Procedures

**Elevated 5xx from the API gateway.** Check the deploy log first — most elevated error rates
follow a deploy within the previous 30 minutes. If a recent deploy correlates, roll back before
investigating. Rollback takes about 90 seconds and is always reversible.

**Database connection pool exhaustion.** Symptoms are rising latency with flat CPU. Check for a
long-running migration or a query without an index. Increasing pool size is a temporary
mitigation, not a fix, and requires a follow-up ticket.

**Certificate expiry.** Certificates auto-renew 30 days before expiry. A renewal failure pages
at 14 days. Manual renewal is documented in the platform runbook and takes about 10 minutes.

## What Not To Do

Do not make an untested change to production during an incident in the hope that it helps.
Mitigate with a known-good action — roll back, fail over, shed load — and investigate afterwards.
