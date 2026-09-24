# Customer Support Escalation

## Support Tiers

Tier 1 support handles account questions, billing questions, and known issues with documented
workarounds. Tier 2 support reproduces reported bugs, gathers logs and trace IDs, and files
engineering tickets. Only Tier 2 may escalate to engineering.

## Response Targets

Enterprise customers receive a first response within 1 hour for urgent tickets and within
4 business hours for normal tickets. Standard-plan customers receive a first response within
1 business day. These are response targets, not resolution targets.

## Escalating to Engineering

An escalation must include the customer's account ID, the `trace_id` from a failing request, the
steps to reproduce, and the business impact. Escalations missing a trace ID are returned to
support. Engineering acknowledges an escalation within 4 business hours.

If an escalation reveals an issue affecting many customers, the engineer declares an incident
rather than working it as a ticket.

## Customer Communication

Engineers do not contact customers directly. All updates go through the support agent who owns
the ticket, so the customer hears one consistent voice.
