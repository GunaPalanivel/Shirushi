# PR3: new company coverage from attributable external sources

Goal: close the cross-family recall gap toward the official 80+ target. The unit
of progress is a newly covered legal-company/information-family pair, followed
by independently supported facts. Candidates and registry activity do not count.

## Repairs and why

| Repair | Why | Evidence gate |
| --- | --- | --- |
| Eight primary sampling cells, separately balanced splits | Five-way allocation rounded away most employers | 500 selected: 72 employers, 54 website hints, seven large employers; development 15 employers/11 hints, validation 14/11 |
| Anonymous AnySearch or access-receipted Brave discovery | BRREG website hints leave most companies unreachable | Two bounded queries; name plus exact spaced org number; snippets never support claims; quota failure is shared and reported |
| Legal/contact traversal before rejection | Homepage-only proof misses legal seller terms | Exact legal name and labelled org number in operator/seller context; directories, customers and other legal parents abstain |
| Seller-scoped catalogue extraction | Literal product cards omit full legal names | Exact offer text and link under verified seller locale/path; ten offers per page, bounded page count |
| One shared NAV feed window | Jobs can be retrieved without finding an owned site | Public experimental token, two pages over seven days, at most three distinct employer-matched details per company |
| Official employer-subunit bridge | NAV employer org numbers may identify a subunit | Exact subunit `overordnetEnhet` equals supplied legal company; no name-only publication |
| Current job support and refresh | Old ACTIVE payloads cannot establish a current vacancy | ACTIVE detail, posted/expiry dates and UUID; unverified old jobs/NAV descriptions leave current coverage and remain audit history |
| Independent source audit and bounded parsing cache | Maker acceptance cannot validate itself; repeated parsing wasted time | Separate parser/field interpretation, retained source hashes and attack tests; four-entry parse cache |

No contacts or full job descriptions become published claims. Employer
`description` supports a bounded sentence that explicitly names the target and its operations; group boilerplate, negation and job duties do not. Source bodies
remain private ignored run artifacts. Summaries retain URLs, hashes, dispositions
and costs. Public display does not expose old NAV job records after withdrawal.
The public token is documented for experiments and may rotate. A stable NAV
consumer credential, if chosen for scheduled deployment, is a separate access
step; none is created or assumed here.

## Predeclared comparison

Control is PR3 head `665e53292b207fd0c36c282fdd00e329f7fcb7e8` before repairs.
Challenger adds the repaired website funnel and NAV adapter. Both have identical
company membership, 1,000 requests, 1,200 seconds, six page attempts per company,
eight I/O workers and zero paid budget. Comparisons report actual resource use.
Each acquires fresh source responses; acquisition times can differ and are
retained, rather than asserting a common immutable live-web cutoff.

The v1 200-company zero-external result stays under `benchmarks/external-coverage/v1`.
V2 development and validation each contain 100 eligible companies from the
hash-bound organizer universe. They measure representative execution/support;
unknown opportunities never become labelled negatives.

A separately frozen NAV-positive source-opportunity pool is labelled directly
from public detail responses and exact BRREG bridges before the paired runs. Source examples were inspected during development; these are disjoint production smoke splits, not an untouched held-out gold test.
Its development/validation companies are disjoint. This targeted pool tests
whether the added mechanism recovers real opportunities; it is deliberately not
an estimate of population recall. The independent checker audits every available
publication against its retained source. Positive company gains and losses are
reported for business/products and jobs/dated activity separately, with exact
McNemar and Holm adjustment across those two outcomes. Promotion requires gains
in both families, zero unsupported publications and complete live outputs.

The positive feed window is intentionally bounded, and a truncated window does
not prove that other companies have no jobs. Corp-group identity beyond known
registered host groups is not independently resolved; disclose that limitation
instead of treating every legal entity as an independent corporate group.

## Validation and release

158 adversarial/contract tests pass locally. Configuration validation, compilation
and 100/300/1,500-company synthetic state stress pass. Actual retained Fristads
Norwegian seller and catalogue pages pass both interpretations: one website plus
13 offer facts across two pages, within the per-page extraction cap. Its audit
runs in under one second after removing repeated parsing. This replay is distinct
from the production live tests.

The final head must pass Linux/Windows contracts, financial regression audits,
V2 live source audits and both equal-budget positive-opportunity comparisons.
Exact live outcomes, costs and head-bound CI links are recorded in PR #3 and
its validation artifacts before merge; local tests do not substitute for them.

Soham's 8 October reply confirms 100-company shards, 45 minutes, 8 vCPU,
16 GB RAM, 10 GB temporary disk, 2,000 outbound requests and $10 external API
spend per shard. Search/model calls count. No personal credentials or general
Brave key are supplied. Revisions close before the end of 18 October UTC.
The public starter supplies a minimal output example and submission command;
the next boundary integration must map its semantics and consume the supplied
frozen registry. See [updated release plan](official-80plus-release-plan.md)
and the hash-bound [limit receipt](organizer-run-limits.json).

The final-head workflow additionally runs the combined six-source pipeline on
100 frozen companies using `configs/shard-validation.json`. This is local
validation within confirmed limits; it does not substitute for the official
frozen-registry integration or assign competition points.

Exclude PDF finance, full financial history, general research agents and a
learned planner from this PR. The existing empirical scheduler remains a route
policy, not a measured implementation of MIDAS's full source-slice algorithm.

Primary contracts:
- https://builderr.ai/docs/signalpost-evaluation-harness.md
- https://builderr.ai/starter-briefs/signalpost-sources.md
- https://navikt.github.io/pam-stilling-feed/
- https://arbeidsplassen.nav.no/vilkar-api
- https://anysearch.com/docs/auth
