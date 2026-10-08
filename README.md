# Shirushi

Evidence-checked company research for the Signalpost challenge.

Start with the [engineering plan](docs/engineering-plan.md), [rubric-to-standards mapping](docs/engineering-standards.md), [company envelope](docs/company-envelope.md), and [source policy](docs/source-policy.md).

Current implementation: [bounded offline batch execution](docs/batch-runner-hardening.md) plus [supervised live retrieval](docs/live-retrieval.md) and [financial coverage validation](docs/financial-coverage.md), exact-source evidence checks, canonical multi-period claims, semantic refresh, grounded static profiles and a separate source-support audit. [PR3 external coverage](docs/pr3-verified-external-coverage.md) adds bounded concurrent I/O, explicit legal operator evidence and independently audited literal HTML. Its coverage promotion gate remains open. Fixed routing remains the default; the adaptive scheduler has no demonstrated recall advantage yet. Historical research and real-company captures remain outside tracked code.

Run a fresh public 100-company smoke test and independent retained-source audit:

```bash
python -X dev -W error tools/validate_live_run.py --count 100 --output-dir out/live-smoke
```

Validate a separate source cohort with `--page 1 --output-dir out/live-validation`; compare both with `python tools/validate_live_cohorts.py out/live-smoke out/live-validation`. CI retains bound summary/manifests as downloadable artifacts. These measure the retained accounts subset, not full six-family recall.

Run your supplied JSONL batch (one `organisation_number` per line):

```bash
python -m shirushi.run --live --organisations data/input.jsonl --config configs/local-live.json --output out/run/envelopes.jsonl --report out/run/report.json --run-id run-1 --showcase-dir out/run/site
```

Serve the generated `out/run/site/` with any static HTTP server and open `/signalpost/`. Every factual profile value links to retained evidence and its original source. The CLI uses the versioned local envelope, not an organizer-confirmed official wire adapter. Numeric official limits, frozen identity snapshot integration, representative held-out recall labels and official score calibration remain release dependencies. No 80+ score is claimed.

Run the contract checks with Python 3.12.12:

```powershell
.venv\Scripts\python.exe -X dev -W error tools/validate_contracts.py
.venv\Scripts\python.exe -X dev -W error -m unittest discover -s tests -v
```

See [CONTRIBUTING](CONTRIBUTING.md) for setup and change validation, and [SECURITY](SECURITY.md) for the current security posture. CI pins Python 3.12.12 on Linux and 3.12.10 for Windows compatibility. The fresh-source job exercises live acquisition on Linux. Review the commit's hosted checks for results. A project licence remains to be selected before an OSS release.

Run external source support on the frozen development cohort:

```bash
python -X dev -W error tools/validate_external_run.py --cohort development --output-dir out/external-development
```

Use `--cohort validation` for the disjoint cohort. These report audited source
coverage and failures, not official recall. Run local execution/state stress with
`python tools/validate_execution_scale.py --output-dir out/execution-scale`.
Search discovery is optional and requires the access receipt, server-side key
and paid budget described in [live retrieval](docs/live-retrieval.md).
