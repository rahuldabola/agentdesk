# Access Control

## Principle

Access is granted on the principle of least privilege and is time-bounded by default. Standing
production access is limited to the platform team; everyone else requests elevated access through
the access broker, which grants it for a maximum of 8 hours and logs every session.

## Authentication

All employees authenticate through the company identity provider with hardware-backed
multi-factor authentication. SMS-based second factors were retired and are no longer accepted
anywhere. Service accounts authenticate with short-lived tokens issued by the workload identity
system; long-lived static credentials are prohibited in every environment, development included.

## Reviews

Access is reviewed quarterly. Managers attest to the entitlements held by their reports, and any
entitlement unused for 90 days is revoked automatically. Revocation is reversible — the point is
to keep the standing surface small, not to make people fill in forms.

## Offboarding

Access is revoked within 1 hour of a departure being recorded in the HR system. This is automated
and does not wait for a ticket. Shared credentials the departing employee could have known are
rotated within 24 hours.

## Production Data

Production customer data may not be copied into development or staging environments under any
circumstances. Engineers needing realistic data use the synthetic data generator, which produces
statistically similar records containing no real customer information.
