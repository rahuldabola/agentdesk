# Deployment Pipeline

## Standard Path

All services deploy via GitHub Actions on merge to `main`. The pipeline runs the test suite,
builds a container image, pushes it to the registry, and rolls out using a blue-green strategy.
Automatic rollback triggers if the error rate exceeds 2% during the first 5 minutes after
cutover.

Deploys are expected to be boring. A team deploying several times a day is healthier than one
deploying once a sprint, because small changes are easier to reason about when something breaks.

## Freeze Windows

Deploys are frozen from 16:00 Friday until 09:00 Monday, and during the last three business days
of each quarter. Freezes exist because the people who understand a change are least available to
fix it at those times. Emergency fixes during a freeze require sign-off from the on-call
engineering manager and a note in the incident channel.

## Database Migrations

Migrations deploy separately from application code and must be backwards-compatible with the
currently running version. Adding a column is safe; dropping one requires two deploys — first
stop writing to it, then remove it in a later release. A migration that locks a table for more
than one second must run during a maintenance window.

## Feature Flags

Risky changes ship behind a flag, dark by default, and roll out by percentage. A flag fully
rolled out for 30 days is considered permanent and must be removed from the code. Stale flags
are audited quarterly.
