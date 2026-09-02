# Engineering Handbook

## Deployment Process

All services deploy via GitHub Actions on merge to `main`. A deployment first runs the test
suite, then builds a Docker image, then rolls out via a blue-green strategy with automatic
rollback if error rates exceed 2% in the first 5 minutes.

## On-Call Rotation

The on-call rotation is weekly, starting every Monday at 9:00 AM local time. The primary
on-call engineer is paged first; if there is no acknowledgment within 10 minutes, the
secondary on-call engineer is paged.

## Incident Severity Levels

- SEV-1: full outage or data loss, page immediately, war room required.
- SEV-2: partial degradation affecting a subset of users, page during business hours.
- SEV-3: minor issue with a workaround available, ticket only, no page.
