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
