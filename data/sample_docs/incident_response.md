# Incident Response

## Severity Levels

**SEV1** — Complete outage of a customer-facing service, confirmed data loss, or an active
security breach. Page the on-call primary immediately, open a bridge within 5 minutes, and
notify the executive on duty. Customer communication goes out within 30 minutes of declaration.

**SEV2** — Major degradation affecting more than 20% of requests, or a complete outage of an
internal service that blocks engineering work. Page during business hours; open a bridge within
15 minutes. The status page is updated within 1 hour.

**SEV3** — Partial degradation affecting a subset of users, elevated error rates below 5%, or a
single-tenant issue with a viable workaround. File a ticket; no page. Handled in the next
business day triage.

**SEV4** — Cosmetic defects, documentation errors, and issues with no customer impact. Tracked
in the normal backlog.

## Declaring an Incident

Anyone may declare an incident. Over-declaring is explicitly preferred to under-declaring, and
there is no penalty for a severity that is later downgraded. The declarer becomes Incident
Commander until they formally hand off. The Incident Commander does not debug — the job is
coordination, communication, and deciding when to page for more help.

## Roles

- **Incident Commander** — owns the incident, runs the bridge, and decides between mitigation
  and root-cause investigation. Mitigation always wins during an active incident.
- **Communications Lead** — owns the status page and customer-facing updates. Assigned for all
  SEV1 and SEV2 incidents.
- **Scribe** — maintains the timeline in the incident channel. Every state change, hypothesis,
  and action gets a timestamped entry.

## Postmortems

Every SEV1 and SEV2 requires a written postmortem within 5 business days. Postmortems are
blameless: they describe what the system allowed to happen, not who typed the command. Each
postmortem must produce at least one concrete action item with a named owner and a due date.
Action items are tracked to completion and reviewed monthly.

A SEV3 gets a postmortem only if the same failure mode has occurred twice in a quarter.
