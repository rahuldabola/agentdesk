# Code Review Guidelines

## Requirements

Every change to a production repository goes through a pull request. Changes to Tier 1 services
need two approvals, at least one from a code owner; everything else needs one. Authors may not
approve their own changes, and approvals are dismissed automatically when new commits are pushed.

## Size

Pull requests should be small enough to review in one sitting — as a guideline, under 400 changed
lines excluding generated files. Large refactors are split into a sequence of mechanical changes
that each keep the build green.

## Turnaround

Reviewers respond within one business day. A response can be a review, a question, or a note
that someone else is better placed to review, but silence is not acceptable. Blocking a change
requires an explanation of what would unblock it.

## What Reviewers Check

Correctness first, then whether the change is tested, then clarity. Style issues that a linter
could catch belong in the linter configuration, not in review comments. Comments prefixed with
`nit:` are optional and never block a merge.

## Merging

Branches are squash-merged so that the main branch history has one commit per change. The CI
pipeline must be green; overriding a failed check requires a written justification in the pull
request.
