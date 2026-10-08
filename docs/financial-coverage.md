# Financial coverage challenger

The live foundation at `7bf4d4443eb20e01a46c0e12ca352661cdcced5a` collected 215 supported revenue facts on 85 of 100 public AS companies, using 100 accounts requests within 400 total agent requests. The same responses contain additional explicit results and balance-sheet totals. Extracting only revenue loses recoverable facts and can miss companies with no revenue field.

## Winning metric and scope of this phase

[Builderr's official scoring rules](https://builderr.ai/challenges/signalpost) assign 70% to company coverage and 30% to fact coverage within each information type. Expanding eight fields on an already-covered company improves financial depth. It does not improve that company's coverage contribution. Therefore `additional_covered_companies` is the primary strategic metric and `additional_facts` is secondary. A positive fact-only result can ship as financial completeness, but cannot establish the major external-recall gain required for 80+.

This evaluator tests only the nine explicitly mapped fields in successfully acquired BRREG responses. It neither establishes official fact equivalence/recognition nor measures facts outside those responses. Its source-subset denominator is not Builderr's cumulative checked collection. Company/fact gains must be inspected on both cohorts before merging and reported without an official-score conversion.

## Input, output and interpretation

The registry website claim remains a retained discovery lead; it does not mark verified owned-page coverage as covered. Registered activity remains a sourced registry fact; it does not mark verified business/product/service coverage as covered. The same rule controls published opportunities and planner gain/selection feedback. Profile summaries label it Registered activity. Historical claim metadata remains compatible.

The existing exact-organisation accounts endpoint and retained receipts feed proposals in `shirushi/api_sources.py`, its source checker, canonical claims, refresh and the existing profile renderer. No new network route, dependency, model, licence or setting is introduced. Missing and null amounts remain unknown. Explicit zero and negative results survive. No sums, ratios, foreign-exchange conversions or inferred balances are published.

| Published field | Official source path below the account record | Interpretation |
|---|---|---|
| `annual_revenue` | `resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter` | Total operating income; existing revenue convention |
| `annual_operating_profit` | `resultatregnskapResultat.driftsresultat.driftsresultat` | Operating result |
| `annual_profit_before_tax` | `resultatregnskapResultat.ordinaertResultatFoerSkattekostnad` | Ordinary result before tax |
| `annual_net_profit` | `resultatregnskapResultat.aarsresultat` | Result for the reporting period |
| `total_assets` | `eiendeler.sumEiendeler` | Explicit total assets |
| `total_equity` | `egenkapitalGjeld.egenkapital.sumEgenkapital` | Explicit total equity |
| `total_liabilities` | `egenkapitalGjeld.gjeldOversikt.sumGjeld` | Explicit total debt/liabilities |
| `current_liabilities` | `egenkapitalGjeld.gjeldOversikt.kortsiktigGjeld.sumKortsiktigGjeld` | Explicit current debt/liabilities |
| `long_term_liabilities` | `egenkapitalGjeld.gjeldOversikt.langsiktigGjeld.sumLangsiktigGjeld` | Explicit long-term debt/liabilities |

Every amount retains source currency and reporting period. `SELSKAP` and `KONSERN` remain distinct entity/group scopes. Results concern the reporting interval; balance-sheet totals concern its end. Names do not force a calendar-year assumption. The [current official OpenAPI](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs/regnskapsregisteret), reviewed 8 October, documents key figures from the three most recent accounts including consolidated accounts. This route does not establish all-history or PDF coverage.

## Trace before scale

1. An exact-company filing has no revenue but directly supports assets `0` and equity `-5`: publish those supported values, gain financial company coverage, retain unknown revenue.
2. An amount belongs to another org number, is boolean/string/nonfinite, or has an invalid date/currency: reject it. Excessive integers must reject without crashing the worker.
3. Three periods and two scopes with nine fields create 54 distinct slots. Identical replay creates zero changes; revising one 2025 group-equity value creates one change and preserves old evidence.
4. Two different currencies or amounts in one slot remain ambiguous. No duplicate count breaks the tie.
5. An earlier revenue-only profile expands with new fields without false changes. Forged prior claim identity/family/period fails before refresh. Boolean money in a candidate or prior state is rejected even when Python would compare `True == 1`.

A fresh exact HTTP-body replay for Equinor (`923609016`, acquired 8 October) ran both the actual main adapter and challenger against the same retained bytes: 6 versus 54 supported facts, zero replay changes, zero automated support errors. It used a separate proxy research request because workspace direct DNS is unavailable. Production safe acquisition requires hosted live results. Real bodies and receipts stay ignored.

## Source-subset experiment and acceptance

`shirushi_eval/live_support.py` maintains its own field interpretation; `financial_coverage.py` independently enumerates retained-source labels and detects extraction misses. Neither imports maker extraction or acceptance. This separation is automated auditing, not independent human adjudication or independently searched gold.

```bash
python -X dev -W error tools/validate_live_run.py --count 100 --output-dir out/live-smoke
python -X dev -W error tools/validate_live_run.py --count 100 --page 1 --output-dir out/live-validation
python -X dev -W error tools/validate_live_cohorts.py out/live-smoke out/live-validation
```

| Metric/gate | Why |
|---|---|
| Same-response revenue-only control versus all nine fields | Isolates extraction gain; acquisition requests are unchanged |
| Company and fact counts separately, per field | Additional depth is not automatically broader company coverage |
| Unknown inaccessible sources and invalid/conflicting references reported | Missing denominators do not become zero labels or fabricated positives |
| Zero missed unambiguous in-scope source facts and unsupported publications | Catch maker loss and unsupported output without trusting maker acceptance |
| Positive absolute fact gain on both distinct cohorts | Confirm the mechanism beyond one hand-inspected company |
| Same maker code, distinct input manifests, input/config/output/code hashes | Prevent overlapping cohorts or stale summaries from posing as validation |
| Existing tests, failure accounting, output completeness and refresh checks | Financial expansion must preserve operational validity |

CI preserves summary/config/input-manifest artifacts for 14 days using a pinned upload action. Real source bytes and personal claims are not included in that summary artifact. Full run outputs and evidence remain in the execution directory; summaries cannot independently reproduce source spans after that directory disappears. Downloads therefore establish what the hosted audit reported, not fresh independent adjudication.

The two live cohorts are consecutive public discovery pages of AS companies with 2025 filing metadata. They are not representative population samples or sealed six-family gold. Live revenue-only metrics are a projection of the audited challenger output, not a second acquisition run. No local proxy is converted to official points. Broader verified websites, jobs/activity, PDF opportunities, representative labels, official settings/adapter and official score calibration remain necessary for the 80+ objective.

## Real-run correction

The first hosted challenger completed 100 outputs, but auditing failed before source checking because `read_records` applied the 2 MiB organisation-input limit to the larger output artifact. The fix preserves the 2 MiB supplied-input bound and adds a distinct 128 MiB local envelope/state bound used by audit and prior-state refresh. This is a local read limit, not an organizer resource setting. A counterexample larger than 2 MiB verifies both successful state reading and continued input/state bound rejection. The failed run is not promoted as an audited gain; the corrected head must pass fresh hosted validation.

## Next phase after financial completeness

| Priority | Missing company/attribute opportunity | Required experiment and why |
|---|---|---|
| 1 | Verified website ownership | Prioritize companies with only discovery leads or no verified site; prove exact legal ownership before using site content |
| 2 | Actual products/services | Retrieve permitted product/service pages for companies missing those facts; registered activity is not a product catalogue |
| 3 | Jobs and dated public activity | Add permitted employer/news sources for companies without supported postings/events; retain exact attribution, IDs and dates |
| 4 | Financial opportunities beyond the nine paths | Test official PDF/source slices against independently acquired labels for missing companies/attributes; avoid duplicating already-supported totals |
| Shared gate | External recall across the six families | Independently search/adjudicate missing opportunities on development and disjoint validation cohorts; report company coverage first, facts second, then marginal cost and failure stage |

Promote the next retrieval mechanism for repeatable new-company coverage under equal budgets, with no material identity/support regression. Do not keep optimizing BRREG fact depth while missing website/product/jobs/activity opportunities remain unmeasured. Adaptive scheduling remains a later controlled comparison with identical adapters, budgets and source conditions. Official equivalence, settings/adapter, product acceptance and an official run remain release gates.

## Score and reliability interpretation

The board reviewed 5 October reports maximum recall 17.45/50. Even the hypothetical combination of that recall with 29 evidence, 12 synthesis and 8 UX totals only **66.45**. These component achievements come from different entrants; no combined result is established. At those non-recall targets, reaching 80 requires **31 recall points**, 13.55 more than the current highest observed recall. The existing financial source-subset gain cannot supply an official-point estimate.

80+ remains a stretch breakthrough objective requiring substantially stronger cross-family company recall, source selection and long-tail discovery, measured on independent cohorts and calibrated by official feedback. Retain the fixed source baseline until adaptive selection improves held-out company coverage under the same budget. Long-tail cohorts must include sparse sites, absent registry URL leads, aliases/group attribution, and differing source availability, rather than only source-rich companies.

Builderr ranks qualified entries by the mean of scheduled daily batches and assigns reproduced entrant-caused failures zero. For illustration, two valid scores of 70 average 70; an 80 followed by an entrant-caused zero averages 40. This is arithmetic under the published ranking rule, not a forecast that Shirushi scores 70. Reliable competitive daily performance is the operational prerequisite for pursuing 80+, not a replacement for the first-prize objective. Preserve bounded execution, terminal outputs, refresh and supported rollback while expanding external recall.
