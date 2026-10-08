# Shirushi

Evidence-checked company research for the Signalpost challenge.

Start with the [engineering plan](docs/engineering-plan.md), [rubric-to-standards mapping](docs/engineering-standards.md), [company envelope](docs/company-envelope.md), and [source policy](docs/source-policy.md).

Current implementation: [bounded offline batch execution](docs/batch-runner-hardening.md), [supervised live retrieval](docs/live-retrieval.md), source evidence checks, canonical multi-period claims and semantic refresh. [PR4's evaluator command](docs/pr4-evaluator-command.md) accepts supplied frozen CSV/JSONL identity and a growing company batch, enforces organizer shard limits, emits the published website field, and renders evidence-linked summaries and factual comparison. Read the [winner-mechanism analysis](docs/pr4-winning-mechanisms.md) and [preregistered experiments](docs/pr4-experiment-ledger.md). [PR3 external coverage](docs/pr3-verified-external-coverage.md) supplies the baseline. Fixed routing remains the default; broad recall promotion remains open. Historical research and real-company captures remain outside tracked code.

Run the published-contract candidate on an evaluator-supplied frozen batch:

```bash
python -X dev -W error -m shirushi.official --organisations supplied/input.jsonl --registry supplied/registry.csv.gz --registry-receipt supplied/receipt.json --cutoff 2026-10-08T06:00:00Z --output out/v1.jsonl --report out/v1-report.json --work-dir out/v1-work --store out/snapshots --showcase-dir out/v1-site --run-id v1
```

The [command guide](docs/pr4-evaluator-command.md) specifies receipt fields, input formats, refresh, resource enforcement and the discrepancy between the public output example and starter batch script. Private harness confirmation, independent source opportunity labels and official component feedback remain release gates. No 80+ score is claimed.

Run a fresh public 100-company smoke test and independent retained-source audit:

```bash
python -X dev -W error tools/validate_live_run.py --count 100 --output-dir out/live-smoke
```

Validate a separate source cohort with `--page 1 --output-dir out/live-validation`; compare both with `python tools/validate_live_cohorts.py out/live-smoke out/live-validation`. CI retains bound summary/manifests as downloadable artifacts. These measure the retained accounts subset, not full six-family recall.

Run your supplied JSONL batch (one `organisation_number` per line):

```bash
python -m shirushi.run --live --organisations data/input.jsonl --config configs/local-live.json --output out/run/envelopes.jsonl --report out/run/report.json --run-id run-1 --showcase-dir out/run/site
```

Serve the generated `out/run/site/` with any static HTTP server and open `/signalpost/`. Every factual profile value links to retained evidence and its original source. `shirushi.run` defaults to the local wire; `shirushi.official` implements the published minimal example. Organizer limits and remaining score work are in the [release plan](docs/official-80plus-release-plan.md).

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
Search discovery is optional. Anonymous AnySearch needs the declared access receipt;
Brave additionally needs a provisioned server-side key and paid budget. See
[live retrieval](docs/live-retrieval.md).
