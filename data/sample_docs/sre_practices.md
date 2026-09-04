# SRE Practices

## Service Level Objectives

Every user-facing service defines an SLO covering availability and latency. Availability is
measured as the ratio of successful requests to total requests over a rolling 28-day window.
Latency SLOs are expressed at the 99th percentile, never the mean, because the mean hides the
tail that users actually notice.

Current targets:

- Tier 1 services (auth, API gateway, billing): 99.95% availability, p99 under 300ms
- Tier 2 services (search, notifications): 99.9% availability, p99 under 800ms
- Tier 3 internal services: 99.5% availability, no latency SLO

## Error Budgets

An SLO implies an error budget: 99.95% over 28 days permits roughly 20 minutes of downtime.
While a service is within budget, the team ships freely. When a service exhausts its budget,
feature work stops and reliability work takes priority until the budget recovers. This is
automatic and does not require a manager approval.

Error budget policy exists to make the reliability-versus-velocity tradeoff explicit, rather
than leaving it to whoever argues most persuasively in a planning meeting.

## Toil

Toil is manual, repetitive work that scales linearly with service growth and produces no lasting
value. Teams cap toil at 50% of engineering time. Anything above that threshold triggers an
automation project in the following quarter.

## Monitoring Philosophy

Alert on symptoms, not causes. A page should mean a user is being harmed right now, and it
should be actionable — if the responder can only wait, it should not have been a page. Every
alert links to a runbook. An alert without a runbook is a defect, and is either documented or
deleted within two weeks.

Dashboards are for investigation; alerts are for interruption. The two are designed separately.
