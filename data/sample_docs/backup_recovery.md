# Backup and Disaster Recovery

## Objectives

Tier 1 systems have a recovery point objective (RPO) of 5 minutes and a recovery time objective
(RTO) of 1 hour. Tier 2 systems have an RPO of 1 hour and an RTO of 4 hours. Tier 3 systems are
restored on a best-effort basis within 24 hours.

## Backups

Primary databases stream write-ahead logs continuously to object storage, which is what makes
the 5-minute RPO achievable. Full snapshots are taken nightly and retained for 35 days. Monthly
snapshots are retained for one year. Backups are copied to a second region and encrypted with a
key that is not stored in the primary region.

## Restore Drills

A backup that has never been restored is not a backup. Every Tier 1 database is restored into an
isolated environment once a quarter, and the drill records the time taken against the RTO. A
drill that misses its RTO is treated as a SEV3 and gets an action item.

## Regional Failover

The platform runs active-passive across two regions. Failover to the secondary region is a
manual decision made by the Incident Commander, because an automatic failover triggered by a
network partition can cause split-brain writes. The failover runbook is exercised twice a year
during a scheduled game day.
