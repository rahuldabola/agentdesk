# Data Classification

All data is labelled with one of four classes. When a dataset mixes classes, the whole dataset
takes the most sensitive class present.

## Classes

**Public** — information intended for release, such as marketing pages and published
documentation. No handling restrictions.

**Internal** — ordinary business information: design docs, meeting notes, most source code.
May be shared with any employee, but not outside the company without approval.

**Confidential** — customer personal data, contracts, financial results before announcement,
and security findings. Encrypted at rest and in transit, accessible on a need-to-know basis,
and never stored on personal devices.

**Restricted** — payment card data, government identifiers, authentication secrets, and
encryption keys. Stored only in systems approved for the class, with access logged per record.
Restricted data must never be pasted into chat tools, tickets, or AI assistants.

## Encryption

Data at rest is encrypted with AES-256. Data in transit uses TLS 1.2 or higher; TLS 1.0 and 1.1
are disabled on every endpoint. Encryption keys for Confidential and Restricted data are managed
by the key management service and rotated annually.

## Labelling

Storage buckets, database schemas, and document folders carry a classification tag. Untagged
storage is treated as Restricted until an owner classifies it.
