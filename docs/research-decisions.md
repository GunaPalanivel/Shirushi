# Research decisions and experiment forecasts

Recorded before the repository bootstrap boundary test run on 7 October 2026. Measurements are saved locally in `.idea/buildDocs/repository-audit/validation-report.json`; the report is not an official score.

| ID | Decision and reason | Prediction / correction mechanism |
| --- | --- | --- |
| DEC-001 | Work backward from 80+, with non-recall target 48–49 | Required recall is 31–32; 90 needs 41–42. These are arithmetic targets, not expected measured results |
| DEC-002 | Use one org-number spine and per-attribute opportunities | First saved-company replay should expose serialization/support loss before a broad crawl |
| DEC-003 | Generate candidates separately from acceptance | Wrong-ID output of equal length must fail; name overlap cannot establish exact subject |
| DEC-004 | Retain rejected evidence with expiry | A changed owner can invalidate an earlier rejection; no permanent blacklist inference |
| DEC-005 | Explicit origin groups before probabilistic fusion | Copied sources contribute one origin, not independent votes; defer costly learned inference |
| DEC-006 | Re-derive affected claims on change | Failed source does not remove old supported data; full unrestricted re-crawl is not required |
| DEC-007 | Pin Python 3.12.12 and use stdlib for repository bootstrap | Three local configs pass; malformed/nonfinite settings and inactive sources are refused |
| DEC-008 | Leave official settings null | Official template must fail validation until confirmed settings exist |
| DEC-009 | Keep original research private to local workspace | `.idea/` ignored and absent from tracked files; origin remains unchanged; nothing pushed |

Inconvenient evidence: the supplied starter's proxy weights differ from the official rubric; identity and membership counterexamples exist; the archive contains no explicit licence member; the exact official limits, matching rules, family weights and wire schema remain unknown. Each blocks a particular claim or release action rather than blocking local saved-company integration work.

The 176-line `researchDirection.md` is a hypothesis source. Review disposition by line span:

| Lines | Decision |
| --- | --- |
| 1–13 | Keep attribute provenance and candidate-set mechanisms. Veridion scale and performance are vendor reports; 461 is not an official field count. Crossref 99% headline is relaxed weighted matching; OpenAlex 73→89 and Google “double recall” are unverified transfer claims in this note, not repository bootstrap acceptance evidence |
| 14–54 | Adopt canonical entity → opportunities → field routes → candidates → checker → accepted claims. Retrieval policy is a hypothesis to ablate, not a proved Norwegian-company gain |
| 55–94 | Keep roles/jobs/products/activity/financial routes as separate policies; NAV/IP routes remain disabled until access and overlap are established |
| 96–131 | Store failed candidates and copied origins; revise “permanently improves” to versioned, reviewable rejection history with revalidation |
| 133–151 | Recheck affected support on material change; preserve history and budget. No unlimited whole-entity refresh or automatic gain claimed |
| 155–176 | Keep staged priorities and the 17→31+ hypothesis; require measured gain against frozen independent labels. No evidence currently establishes 80+ |

Principles 02–09 have concrete artifacts: score arithmetic (02), forecasts and corrections (03), primary-source lineage (04–05), failure/unknown ledger (06), smallest saved replay before scale (07), separate read-only checker and future independent label reviewer (08), versioned receipts and cumulative decisions (09). No independent reviewer participated in this repository bootstrap run; programmatic rejection tests are not independent human research adjudication.

Coding discipline: first define input/output/invariants, decompose by interfaces, manually trace a wrong-ID batch and missing-vs-zero claim, examine reference failure mechanisms, then implement the checker. Explain failed tests by violated invariant before changing code. Record the causal correction, not just a new passing number.

Observed after the first run: all three local configurations passed and 18 tests passed. The official template was rejected, wrong-ID/same-count output was rejected, the 411,160-row universe hashes matched, 158 archive members were safe, and no explicit archive licence was found. Forecast errors for the binary predicted checks were zero; no recall/resource-performance experiment ran.

Robustness review found an untested failure: using set membership for an arbitrary JSON `mode` could raise `TypeError` on a list or object instead of reporting a configuration error. Changed membership to a tuple and added an explicit malformed-mode test. The cause was assuming a hashable input before validating its type. This correction affects error handling, not policy or scoring.

Engineering conventions update: replaced numbered-stage file/module names with responsibility names. Rechecked official rules and mapped them to published standards in [engineering-standards.md](engineering-standards.md). RFC 3339 review showed that datetime.fromisoformat accepts broader shapes and normalizes some invalid offset components; added explicit profile/range checks. JSON loading now rejects exponent overflow that would otherwise become infinity. These are interoperability corrections, not newly invented competition rules.


Saved-company integration outcome: the forecasts in [the integration runbook](saved-company-integration.md) were recorded before execution. All 48 current tests passed, including a public-only directory run. One real frozen identity yielded eight supported fields; unchanged replay yielded zero changes; unavailable-source refresh preserved all eight supported values with stale status and no removals. Byte tampering, wrong subject/value/type and forged archive membership were rejected. These are local support and behavior results, not population precision or recall estimates. Original receipts and final working-tree artifact hashes are retained in `.idea/buildDocs/saved-company-integration/validation-report.json`.

Causal correction: a successful GitHub run was initially mistaken for contract CI. Inspecting its workflow/job identified Dependency Graph; the actual contract job failed before Windows tests because setup-python's manifest has no Windows Python 3.12.12 binary. The corrected matrix retains Linux 3.12.12 and explicitly tests Windows 3.12.10 compatibility. Its hosted result remains pending. The earlier nothing-pushed forecast describes bootstrap planning; bootstrap has since been committed and published, while this milestone was validated locally before publication.

Documentation checks found a prior ESC control character in a standards reference, consistent with PowerShell backtick escape interpretation. This session also found damaged Unicode from implicit Windows cp1252 decoding during document edits. Restored affected lines from their original Git bytes, used explicit UTF-8 and checked public text for unexpected control characters and encoding artifacts. No original research or source receipts were rewritten.

Correction recorded 8 October 2026: DEC-010 freezes the 100-company baseline before structured accounts E2; the proposal to establish maker accounts inside the baseline was not adopted. DEC-011 requires tested safe fetching and global accounting before live experiments; offline zero-request controls do not satisfy it. DEC-012 distinguishes separately authored agent adjudication from automated source auditing and human review. P1 review does not close full P2 review. See [retrieval validation](retrieval-validation.md). Original research and historical receipts remain unchanged.

## Financial-field challenger forecast, 8 October 2026

Recorded before the new 200-company hosted validation. Control: main `7bf4d4443eb20e01a46c0e12ca352661cdcced5a`, which extracts only revenue. Challenger: nine explicit official financial fields from the same accounts request. Forecast: positive absolute supported-fact gain with zero additional acquisition requests; company gain is plausible where revenue is absent, but has no justified numeric forecast. The fresh Equinor source replay recovered 54 facts versus 6 using the actual control adapter, with zero replay changes and no source-audit errors. This one-company result does not establish broader recall.

Promotion requires all portable tests and hosted checks, successful complete output on two non-overlapping public 100-company source cohorts, no unsupported publications or missed unambiguous in-scope source facts, and positive fact gain on both cohorts. Invalid reference records or conflicting financial slots require investigation before promotion. Keep requests, bytes, time and monetary cost visible; no official score is calculated. The live control is a revenue-only projection, not a second live execution. Six-family independently acquired/adjudicated labels remain outstanding.

User review validated against the official rules: company coverage contributes 70% within an information type and fact coverage contributes 30%. Inspect `additional_covered_companies` before `additional_facts` on each live cohort. Financial-depth gains can justify this focused PR but cannot establish 80+ or official recognition. The next phase targets companies missing verified websites, products, jobs/public activity and financial/PDF facts outside these nine paths, with independently acquired labels. Corrected opportunity accounting so registry website discovery leads do not count as verified owned-page coverage.

First hosted failure: 100 companies completed but the audit rejected the enlarged output at the identity-input 2 MiB reader limit. Cause: reusing one reader boundary for small organisation inputs and evidence-rich state. Split input/state bounds and add a >2 MiB counterexample; do not weaken the input bound or treat the failed audit as promotion evidence. Corrected-head CI must pass again.

Checker review reproduced a second counterexample: a forged nested monetary value `True` compared equal to source amount `1` because Python numeric equality treats bool as int. The original guard validated the source amount, but did not validate the candidate/prior amount type. Added explicit nested monetary type checks in acceptance, independent auditing and coverage matching; the regression failed before this fix and passes afterward. Numeric zero and losses remain supported.

A user review identified the remaining registry-activity shortcut. An end-to-end worker/profile counterexample reproduced business_products=covered from registry activity alone. Excluded registered_activity from the shared coverage helper used by publication and planner feedback, retaining the sourced claim and historical metadata. Profile text now labels Registered activity. A positive control verifies that an exact-identifier owned-site description/website still establishes their provisional external families. The revised plan records 17.45+29+12+8=66.45 as a hypothetical cross-entrant combination, 31 recall needed at those other targets, and stable daily execution as necessary for the official scheduled-average ranking. 80+ remains unproven.

## PR3 forecast and corrections, 8 October 2026

Recorded before hosted external-cohort execution. Baseline main is c958cc45.
Prediction: ordinary HTML can produce additional verified website claims without
JSON-LD. Explicit subject-named products and dated activity may remain sparse;
no numeric content-recall gain or official score is forecast. A passing source
audit cannot substitute for independent opportunity labels or paired comparison.

The user's assessment was checked against source code and current primary
requirements. Confirmed: BRREG-only website leads, JSON-LD-only extraction, one
effective network worker, unsynchronized Budget/robots state, and a host spacing
floor independent of worker count. Reproduced a two-thread request-cap violation
before replacing check-then-sleep with atomic condition reservations. Added
pre-read byte reservations after review found that post-read charging could
otherwise receive unaccounted bytes concurrently. Condition waits release locks;
network threads never persist, verify, update planner statistics or write the Pipe.

Tightened content success to products/services AND jobs/dated activity; website
coverage cannot replace the second content family. Exact two-sided McNemar for
five gains/zero losses is 0.0625. Simultaneous paired gain intervals use exact
binomial marginal intervals with a union-bound correction; they are deliberately
conservative. Holm adjusts the two predeclared content-family p-values. A 5 pp
gain is a mechanism detection floor, not an 80-point forecast.

The full eligible archive and expanded SHA hashes matched the published values.
Frozen development/validation identities are recorded before hosted experiments.
The two older research reports and attached PR3 assessment were read in full.
The public playbook independently supports deterministic crawling, explicit
entity gates, preserved sources, disjoint cohorts and promotion through evidence.

Local 100/300/1500 synthetic terminal/state checks passed; the largest state was
94,716,000 bytes. These are not real network or organizer-limit measurements.
Direct BRREG DNS failed locally and two attempted requests were charged. The
fetcher was not weakened or routed through a research proxy. Fresh acquisition
will be measured in hosted CI. The model/API-key request was sent separately;
no response or search-access credential was present in the connected mailbox.

Brave's published general terms constrain stored results and some AI uses; its
product page describes additional plan rights. The single adapter therefore
requires a declared applicable account-rights/rate receipt and budget; searches
remain transient candidates. No account rights are inferred from marketing copy.

Pending promotion evidence: independently reviewed cross-content labels,
equal-budget A/B/C paired comparison, actual live scale/chaos receipts, permitted
discovery activation and organizer execution calibration. Keep PR3 a draft
while required evidence is missing, even when all CI checks pass.
