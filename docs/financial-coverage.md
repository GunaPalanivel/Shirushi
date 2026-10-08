# Financial coverage challenger

The live foundation at `7bf4d4443eb20e01a46c0e12ca352661cdcced5a` collected 215 supported revenue facts on 85 of 100 public AS companies, using 100 accounts requests within 400 total agent requests. The same responses contain additional explicit results and balance-sheet totals. Extracting only revenue loses recoverable facts and can miss companies with no revenue field.

## Input, output and interpretation

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
5. An earlier revenue-only profile expands with new fields without false changes. Forged prior claim identity/family/period fails before refresh.

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
