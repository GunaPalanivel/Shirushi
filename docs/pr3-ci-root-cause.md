# PR3 CI failure investigation, 8 October 2026

## Complete results before the next repair

Both workflows on `c51a0486e178567e69b4b1fb7f55e0d49af4d43f` finished.
[Push run 37817706228](https://github.com/GunaPalanivel/Shirushi/actions/runs/37817706228)
and [PR run 37817712663](https://github.com/GunaPalanivel/Shirushi/actions/runs/37817712663)
each passed eight jobs and failed the live legal-seller website regression.

| Check | Result | Meaning |
| --- | --- | --- |
| Linux and Windows contracts | PASS | 162 tests, configuration and ordered-output checks |
| External support, development and validation | PASS | All 100 outputs, no unsupported publications; zero external family coverage in both cohorts |
| NAV-positive paired groups | PASS | Additional business-covered companies 7/6; job-covered companies 20/19; no lost coverage |
| Two fresh financial cohorts | PASS | Additional financial-covered companies 15/17 versus revenue-only projection; no unsupported publications |
| Combined six-source development shard | PASS | 100 outputs, zero failed companies, zero unsupported publications |
| Live legal-seller website | FAIL | Five registry facts only; no verified website or catalogue offer |

The combined runs used 852/857 requests, 718/716 seconds and $0 paid spend.
They respect the confirmed request/time/spend ceilings. Hosted runner CPU/RAM
are not a substitute for a final constrained 8-vCPU/16-GB/10-GB acceptance run.
Their green checks demonstrate execution and support, not official recall.
Zero website/business/job coverage is a release gap, not an 80-point result.

## Reproduction and causal boundary

Use exactly the `c51a0486` code, the no-hint Fristads organisation number
`915463568`, legal name `FRISTADS AS`, and a six-page acquisition limit.
Keep the company, code and fetched public page bodies constant; vary only the
candidate supplied to `acquire_website`.

| Candidate intervention | Result |
| --- | --- |
| Actual CI lead, `/fr-ch/contactez-nous` | Foreign contact, linked Norwegian home, legal notice and careers page acquired; zero accepted pages; no exact legal operator proof |
| Norwegian seller terms, `/nb-no/generelle-vilkar`, returned by a fresh exact-number search | Six accepted Norwegian pages, including ownership terms and catalogue pages; zero identity rejections |

This diagnostic used ordinary HTTPS acquisition rather than the production
pinned-DNS fetcher. It reproduces the acquisition/ownership boundary; it is not
a production live-run result or an official score. No claim from it is published.
Ignored local receipts retain timestamps, URLs and SHA-256 hashes for every
fetched body, under `out/ci-root-cause-reproduction/reproduction.json`.

The Swiss page explicitly links the Norwegian locale. Following that link
corrected one traversal omission, but the Norwegian legal notice does not link
the seller terms carrying the exact legal proof. Locale traversal therefore
cannot fix this observed input alone. Supplying those terms makes the unchanged
ownership gate succeed. Search must discover the useful identity page.

The hosted run does not retain each query's returned URLs, so the precise cause
of its difference from direct provider probes remains unmeasured. Provider
variation is a hypothesis, not an established backend defect. Do not infer a
cache problem, wrong API schema or missing credentials from these logs.

## Next bounded experiment

Search the verified legal name plus exact spaced organisation number first.
Keep a second host-scoped exact-number query when a likely first-party host is
observed, otherwise use the broad name query as fallback. Keep the existing
two-query and three-host limits. Retain request IDs and result URLs, without
search snippets or response bodies, so another hosted miss is diagnosable.

The query-order regression fails on the old code before repair. Acceptance
requires the fresh production CI job to publish an audited verified website and
at least one catalogue offer within its 50-request/180-second limit, then all
jobs on that same final head to pass. Candidate counts or passing mocked tests
alone do not establish success. Preserve customer, parent-company and foreign
seller rejection. Do not hard-code the diagnostic URL into production.

## Follow-up results on `9762b559`

Both full workflows finished before the next code change. PR run
[37819782100](https://github.com/GunaPalanivel/Shirushi/actions/runs/37819782100)
failed website and validation company-gain checks; push run
[37819776077](https://github.com/GunaPalanivel/Shirushi/actions/runs/37819776077)
passed website but failed development company gains. Both combined shards
passed, with 854/855 requests and 691/649 seconds, all 100 outputs, $0 spend and
no unsupported publications. Representative external coverage remains zero.

The same exact-number query returned zero results in the failed website job
(`dc058799-a7a3-49a7-a3c5-95596503ae52`) and nine in the passing job
(`b1115790-3e08-472c-bc66-9e4c49478309`). The passing job acquired the Norwegian
terms, verified the website and audited 18 catalogue facts in 10 requests and
70 seconds. The failing job fell back to the same foreign contact lead. Hosted
search variability is now directly observed; its upstream cause remains unknown.
Query order alone is an insufficient repair.

The company's observed robots response advertises `/sitemap-index.xml`; that
index links `/nb-no/sitemap-0.xml`, which explicitly lists the seller terms.
A recorded-source replay using only the foreign CI candidate now succeeds with
two metadata reads and six bounded HTML attempts, without supplying the terms
URL directly. XML leads are filtered to the observed host and locale, reject
DTD/entities and retain exact seller ownership checking. The corresponding
worker/source-audit regression fails on the old code and passes after repair.
Fresh production CI is still required. No production URL is synthesized.

The company-gain failures retained their gains but expose only the validator's
generic `Incomplete or failed live batch`. The next diagnostic summary retains
the existing run errors, failed-company count and worker completion/reason.
That failure is unresolved; do not claim it repaired or erase it with a rerun.

## Quota and malformed-response validation

Both full `4f92fbb8` workflows finished. PR run
[37821934250](https://github.com/GunaPalanivel/Shirushi/actions/runs/37821934250)
passed all nine checks. Push run
[37821927955](https://github.com/GunaPalanivel/Shirushi/actions/runs/37821927955)
failed only website discovery: HTTP 402 occurred on its first search call, so
there was no candidate domain for sitemap traversal. A favorable anonymous-IP
quota outcome is not sufficient production acceptance.

The next repair classifies 402 as blocked and suppresses subsequent calls in
that worker. It uses at most two untrusted `.com`/`.no` domain hypotheses derived
from the verified legal name when search is unavailable or supplies no usable
candidate. This path also works when no discovery receipt/provider is configured.
Neither a generated hostname nor a sitemap is identity evidence. Publication
still requires the exact legal operator, observed locale scope and source audit.
No company-specific hostname is embedded in the algorithm.

A recorded-page replay starts with a derived root domain, follows the observed
Norwegian alternate and the advertised sitemap, and verifies the seller terms
with six HTML attempts and two metadata reads. This is a replay, not a production
run. The next hosted website job checks both anonymous discovery and a separate
run with search explicitly disabled, each under 50 requests and 180 seconds.

Independently, success-shaped search JSON with `data: null`, `data: []` or a
non-object body reproduced an uncaught `AttributeError` in the old adapter.
The worker does not catch that exception in its source acquisition boundary.
The repair validates these shapes and raises a source failure, preserving batch
completion; full worker/source-audit tests cover malformed responses, 402 and
no provider. These tests do not identify the earlier lost incomplete-batch reason
as this defect. Updated diagnostics preserve the reason if it recurs.

## Organizer email and release decision

Soham confirms 100-company shards, 45 minutes, 8 vCPU, 16 GB RAM, 10 GB temporary
disk, 2,000 outbound requests and $10 external API spend. Search and model calls
count. Keep the credential-free path unless Builderr confirms the provider and
environment variable before freeze. Submit before the end of 18 October UTC.

PR3 remains unmerged while the website gate fails. The subsequent official
adapter, broader coverage and product acceptance work is ordered in
[official-80plus-release-plan.md](official-80plus-release-plan.md).
