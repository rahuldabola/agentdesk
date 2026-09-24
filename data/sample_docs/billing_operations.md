# Billing Operations

## Invoicing

Invoices are generated on the customer's billing anniversary at 00:00 UTC. Usage-based charges
are computed from the ledger at that moment, so usage recorded after midnight lands on the next
invoice. Invoices are immutable once issued; corrections are made with a credit note.

## Failed Payments and Dunning

When an automatic payment fails, the dunning process retries the card on days 1, 3, 5 and 7 after
the failure, emailing the customer before each retry. If every retry fails, the subscription moves
to past-due and paid features are suspended on day 14. The account is not deleted; data is kept
until the normal retention policy applies.

## Refunds

Support may issue refunds up to $500 without approval. Refunds above $500 need approval from a
billing operations lead, and refunds above $5,000 need finance approval. Refunds are always issued
to the original payment method.

## Currency

Prices are stored in minor units (cents) as integers. Floating-point types are never used for
money anywhere in the codebase.
