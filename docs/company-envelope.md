# Company envelope

The [local machine-readable contract](../contracts/company-envelope.v1.json)
validates typed claims and evidence. The [evaluator adapter](evaluator-command.md)
uses the published `run/claims/evidence` example and `official_website` alias;
it is not an organizer-confirmed private schema.

Input identities are exact nine-digit ASCII organisation numbers. Produce one
terminal record per supplied identity in order. Names, brands, parents and
subunits cannot replace the legal subject.

Records contain `organisation_number`, `run`, `claims`, `evidence`, `changes`,
`errors` and `operations`. Run state is `completed` or `failed`. Claim availability
is separately `available`, `not_available`, `blocked`, `not_applicable`,
`ambiguous` or `failed`; completion does not imply complete information.

Available claims require a typed non-null value and resolving evidence IDs.
Other states require a null value and reason. Evidence retains source URL,
acquisition time, content SHA-256, support span, locator and extraction method.
Financial and dated claims preserve periods, units and entity scope. Missing
values never become zero. Duplicate JSON keys, nonfinite numbers and ambiguous
timestamps are rejected.

Refresh rechecks retained evidence before carrying a claim forward. A failed
source does not establish removal; identical supported values create no change.
Contract validation checks structure. Source auditing separately checks retained
bytes, legal attribution and claim support; neither establishes official recall.
