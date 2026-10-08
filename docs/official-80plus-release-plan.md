# Signalpost release plan: 82-point target

Updated 8 October 2026 after reading Soham's reply, the current evaluation
contract, source policy and downloaded starter. This supersedes earlier statements
that numeric limits or the public output example are unavailable. Limits and
source hashes are retained in `organizer-run-limits.json`.

## Outcome and score budget

| Component | Internal target | Required behavior |
| --- | ---: | --- |
| Recall / coverage | 34/50 | Recover first supported company coverage across missing external families, then additional distinct facts |
| Precision / evidence | 28/30 | Exact legal subject, inspectable source spans, periods and current support |
| Synthesis | 12/12 | Explain supported business, material changes and unknowns with direct evidence links |
| UX | 8/8 | Find, compare and verify 100 profiles at `/signalpost` on desktop and mobile |
| Total | 82/100 | Two-point margin above 80; these are acceptance targets, not awarded points |

Each official family uses `0.7 * company recall + 0.3 * fact recall`.
For example, 80% company recall and 40% fact recall produce 68% coverage in
one family. The official weighted aggregate must reach 68% for 34 recall points.
Family weights/equivalences are not specified in the public contract, so our
six-family macro average cannot be called an official score. Scheduled-batch
mean determines ranking; one favorable test does not determine first place.

## Confirmed execution envelope

| Limit per shard | Organizer value | Release decision |
| --- | --- | --- |
| Companies | 100 | Read supplied membership; never replace it with our positive cohort |
| Time | 45 minutes / 2,700 seconds | Proposed acquisition stop at 2,430 seconds, retaining 270 seconds for audit/output |
| CPU / RAM / disk | 8 vCPU / 16 GB / 10 GB | Test in a constrained clean environment; bound snapshots and product artifacts |
| Outbound requests | 2,000 | One atomic ledger includes search, model, robots, redirects and retries |
| External API spend | $10 | Default remains $0; proposed paid-use ceiling $8 with $2 reserve once access/pricing is confirmed |
| Credentials | No personal service credentials | Bounded legal-name domain hypotheses without a provider; optional anonymous search; provisioned provider and environment variable confirmed before freeze |
| Revisions | Initial plus four revisions | Use revisions for measured gains or official feedback |
| Final revision | Before end of 18 October UTC | Internal freeze on 17 October; submit before the deadline |

The shared official collection can span many shards. The 1,500-company synthetic
state test remains a stress test, while the operational acceptance unit is a
100-company shard. No undocumented shard orchestration is inferred.

Proposed initial request allocation for the combined pipeline, including all
attempts rather than only successful source fetches:

| Work | Ceiling | Why |
| --- | ---: | --- |
| Registry identity, roles, accounts, workplaces | 400 | Preserve cheap deterministic foundations; frozen identity input can save calls |
| Search | 200 | At most two queries per missing company |
| Company pages, robots and redirects | 900 | Spread verified content across companies before deep crawling |
| NAV feed, details and employer bridges | 200 | Share feed work; prioritize first matched posting and reuse exact bridges |
| Additional high-yield source attempts | 100 | Only after measured incremental gains |
| Retry / finalization reserve | 200 | Avoid exhaustion before every input terminates |
| Total | 2,000 | Allocation is a proposed controller policy, not current route enforcement |

Unused allocations may move to another route while preserving the global cap.
Current PR3 comparisons use 1,000 requests and 1,200 seconds; they exercise
only an external subset. A combined six-family shard is a separate release test.

## PR3 failure, repair and merge gate

At head `364d6d0c`, run `37789477682` failed only the live legal-seller website
regression. Fristads discovery supplied a Swiss contact page, a group newsroom
and a reseller. Five acquired pages did not prove the Norwegian legal operator.
The exact-entity gate correctly rejected them. Retained Norwegian pages already
pass extraction, isolating this observed failure to candidate discovery.

The host-scoped second query at `1369489a` did not recover a usable legal
candidate in the fresh hosted run; its predeclared prediction failed. A direct
provider probe returned Norwegian terms, demonstrating that result availability
can vary. The acquired Swiss page explicitly links `/nb-no/` via `data-language`,
but our page selector omitted locale links and spent its identity budget on
Swiss terms. Follow one observed same-host Norwegian alternate, then check its
legal/contact links. Never synthesize a locale URL or treat a language marker as
ownership. The locale traversal reached more pages at `c51a0486` but still found no exact
operator proof: the Norwegian legal-notice page does not link the available
seller terms. Direct fresh API probes for both the legal name plus exact number
and the host plus exact number returned the Norwegian seller terms. Prefer the
exact-identifier query first, use broad-name search only as fallback, and retain
per-query request IDs/result URLs to identify hosted provider differences.
Search snippets and result content remain excluded from retained evidence. Host-name resemblance is only a retrieval lead. Retain legal ownership,
seller locale scope, two-query limits and source access checks. Also encode
international URL paths/queries at the HTTP boundary and skip non-HTML candidates
without aborting the remaining website route. Tests must reproduce the wrong
locale and preserve customer/parent/foreign-locale rejection.

Predeclared prediction: fresh production fetching recovers both a legally verified
Norwegian Fristads website and at least one audited catalogue offer within the
existing 50-request/180-second diagnostic budget. Reject the repair if only
candidate counts improve. No domain or organisation number is hard-coded into
the submitted discovery implementation; the known company remains a regression
input, not a held-out recall estimate.

At `9762b559`, the identical exact-number query returned zero results in one
hosted job and nine in another; website verification and 18 catalogue facts
passed in only one run. Query order alone is insufficient. The site's observed
robots sitemap index and Norwegian sitemap explicitly list the unlinked seller
terms. Test a fallback bounded to two metadata fetches plus the existing six
HTML attempts, same-host/locale scope and unchanged exact seller checks. A
recorded-source replay now recovers ownership from the foreign candidate.
Two company-gain jobs also failed with an incomplete-batch diagnostic; retain
the worker reason in the next summary and resolve it before merge.

At `4f92fbb8`, one full workflow passed all nine checks, while the other failed
its first search call with HTTP 402. Test a credential-free path that derives at
most two untrusted domain hypotheses from the verified legal name, applies the
same ownership/sitemap checks, and suppresses repeated quota calls. Validate a
separate hosted website run with search disabled. Validate response shapes so
malformed success JSON cannot terminate the worker. The prior incomplete-batch
reason was not retained, so this independently reproduced crash must not be
presented as the proven cause of that old failure.

Both full `c51a0486` workflows finished with eight jobs passing and the website
regression failing. The combined six-source shard produced every output in
716/718 seconds, with 852/857 requests and no unsupported publications. Both
representative external cohorts still have zero supported external-family
coverage. The current NAV-positive pairs gained 7/6 business-covered companies
and 20/19 job-covered companies, with no lost coverage. These inspected positive
groups prove route behavior, not population recall. See
`pr3-ci-root-cause.md` for the complete results and the same-code candidate
intervention reproduction. A new untouched reference pool must measure broader
coverage separately.

Merge PR3 only when its exact final head passes every existing check plus the
live website regression. Keep failed-run receipts. Do not remove the check,
insert a known URL into production, weaken legal ownership or count registry
activity as external business coverage to obtain a green result.

## Ordered work after PR3

| Order / intended window | Work | Why | Acceptance |
| --- | --- | --- | --- |
| PR4, 9-10 October | Integrate public output example and supplied frozen registry; shard budget config and clean evaluator command | Correct research must be scorable and reproducible | Read starter field semantics including `official_website` versus internal `verified_website`; exact input membership; cold 100-company run under confirmed limits; forced source outage and refresh pass |
| PR4, alongside boundary | Review existing static synthesis and `/signalpost` showcase | Existing UI is a foundation, but the 20 product points require behavior validation | Direct evidence links for summary conclusions, useful changes/unknowns, desktop/mobile search/compare/source checks, no implementation/status copy in user flows |
| PR5, 10-13 October | Close measured per-family losses with source-specific adapters | Website and NAV gains alone do not cover broad companies | Freeze independent opportunity labels before tuning; equal-budget new-company gains in missing families with zero material wrong-company publications |
| First complete release, 13-14 October target | Submit frozen complete version and obtain official breakdown | Private union and weights cannot be reproduced from smoke cohorts | Clean install, 100-profile artifact, source/model/license/cost declarations, executable command and exact commit; no personal credentials |
| 14-16 October | Repair the largest official score loss; expand only the winning mechanism | Real official feedback determines the next revision | Component delta, identity/refresh checks, per-family gain and budget receipts; retain prior version as rollback |
| 17 October | Freeze final revision and rerun clean shard | Ranking penalizes repeat failures | Repeatable cold run and source failures produce every terminal output; resource ceilings and evidence checks pass |

Family repair order is selected by observed missing opportunities, not by adding
every possible adapter:

| Family | Next small experiment | Disconfirming result |
| --- | --- | --- |
| Website / owned profiles | Generalize legal-host discovery; inspect permitted verified-site outbound links | More candidates but no new exact-company facts, quota collapse, wrong locale or inaccessible source |
| Business / products | Bounded about/service/catalogue sections on verified sites, preserving explicit subject or verified seller scope | Parent promotional text or generic legal-name sentences counted as business |
| Jobs / activity | Measure NAV's truncated seven-day/two-page window; test bounded wider or targeted routes and dated company news | Window scans cost more but recover no newly covered companies; name-only employer match |
| People | Existing official roles, then verified leadership/team pages | Group staff mistaken for the legal entity or duplicates of registered roles |
| Locations | Existing BRREG workplaces, then verified contact/location evidence | Registered office counted as an unsupported operating location |
| Finance / history | Preserve structured accounts; test permitted missing-period data or PDFs only on measured opportunities | No additional checked periods, fabricated values, company/group or currency/unit confusion |

Start with deterministic extraction. Conditional LLM extraction may propose
facts from retained permitted content once a reproducible model key is confirmed;
the source checker retains publication authority. Do not add a general research
agent or learned scheduler to compensate for missing sources. Compare simple
missing-family scheduling with fixed routing only after adapters have measured
positive yield.

## Evidence required for each promotion

Record the prediction, fixed inputs/code/labels, actual company and fact gain,
losses, source-stage failures, unsupported/wrong-company publications, request
count, bytes, paid spend, p50/p95 time and output completeness. Labels come from
source review independently of accepted maker outputs. Unknown opportunities
remain unknown. Hold the validation cohort untouched until the experiment freezes.
Current separate source-audit implementations share some acceptance patterns;
use blind source review to detect shared blind spots rather than describing
agreement between code paths as independent human verification.

Keep source bodies in access-controlled ignored artifacts; tracked receipts
contain hashes, source identifiers, costs and failure reasons. Respect NAV's
current-status/update terms and withdraw unverified vacancies from public output.

Primary authorities:
- https://builderr.ai/challenges/signalpost
- https://builderr.ai/docs/signalpost-evaluation-harness.md
- https://builderr.ai/starter-briefs/signalpost-sources.md
- https://builderr.ai/signalpost-starter-kit.tar.gz
- Soham's 8 October reply, summarized in `organizer-run-limits.json`
