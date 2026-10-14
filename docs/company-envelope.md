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

## Kit-compatible blocks

The evaluator adapter adds the starter runner's envelope keys beside the public
ones. They are a view of the claims: nothing appears in them that is not an
available claim with evidence, and the independent validator in
`shirushi_eval/wire.py` rejects any value without a matching claim.

- `run_id`, `started_at` and `completed_at` copy `run`. `state` is `complete`
  for a completed run and `submission_error` for a failed one.
- `modules` lists only the modules whose claims exist: `registry`,
  `registry_live`, `financials`, `roles`, `locations`, `website`. Each has
  `state` (`complete`, `not_found`, `not_applicable`, `blocked_policy`,
  `blocked_robots`, `source_error` or `budget_exhausted`), `retry_count` (0,
  retries are not tracked) and `final_timestamp` (latest cited evidence time,
  else the run completion time).
- `profile` carries `organisation_number`, `kit_compat` and, only from available
  claims, `name`, `legal_form`, `employees` (zero is kept; a missing count has
  no key), `municipality` and the registry-declared `website`. Its `evidence`
  holds `registry_live` (the same identity values) and `website`.
- `profile.evidence.website` is `available` only for a published
  `official_website` claim, with that claim's evidence and the `social_profile`
  claims as sorted `social_links`. Otherwise it is an absence record with the
  kit `status`, our `availability` and the claim `reason`, and a null value.
  A registry-declared address that is not a published website never appears here.
- Each claim gains `confidence`, a fixed table by evidence class (1.0 registry
  and official API, 0.99 legal-operator website, 0.9 company page facts, 0.8 date
  only news) and 0.0 where no value is supported. It is not a probability.

Output order is the order the run produced; the kit blocks are sorted and hold
no volatile value except the allowed time fields.
