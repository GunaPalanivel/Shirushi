# Shirushi

Evidence-checked company research for Signalpost. Python 3.12.12, standard
library only; the evaluator command requires Linux.

Run with the supplied company batch, frozen registry and acquisition receipt:

```bash
python -X dev -W error -m shirushi.official \
  --organisations supplied/input.jsonl --registry supplied/registry.csv.gz \
  --registry-receipt supplied/receipt.json --cutoff 2026-10-08T06:00:00Z \
  --output out/results.jsonl --report out/report.json --work-dir out/work \
  --store out/snapshots --showcase-dir out/site --run-id run-1
```

Serve `out/site/` with a static HTTP server and open `/signalpost/`.
See the [command guide](docs/evaluator-command.md),
[output contract](docs/company-envelope.md) and [source policy](docs/source-policy.md).
Local validation does not award an official score.

Validate with the pinned runtime:

```bash
python -X dev -W error tools/validate_contracts.py
python -X dev -W error -m unittest discover -s tests -v
```

See [CONTRIBUTING](CONTRIBUTING.md) and [SECURITY](SECURITY.md).
Research, source bodies and generated outputs are gitignored. A project licence
must be selected before an OSS release.
