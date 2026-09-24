# Secrets Management

## Where Secrets Live

All secrets are stored in the central vault. Applications read them at startup through the
workload identity integration; secrets are never baked into container images, committed to
repositories, or passed as build arguments.

## Rotation

Database passwords rotate every 30 days automatically. Third-party API keys rotate every 90 days,
and the owning team is notified 14 days before a key expires. TLS private keys rotate with their
certificates. Any secret that may have been exposed is rotated immediately, regardless of schedule.

## Leaked Secrets

Repositories are scanned for secrets on every push, and a push containing a recognised secret
pattern is blocked. If a secret reaches a repository anyway, treat it as compromised: rotate it
first, then clean the history. Cleaning history alone is not remediation, since clones and caches
may already hold it.

## Local Development

Developers use per-developer credentials scoped to development resources. Copying a production
secret to a laptop is a policy violation.
