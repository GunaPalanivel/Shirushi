# Shirushi

Evidence-checked company research for the Signalpost challenge.

Start with the [engineering plan](docs/engineering-plan.md), [rubric-to-standards mapping](docs/engineering-standards.md), [company envelope](docs/company-envelope.md), and [source policy](docs/source-policy.md).

Current implementation: [offline saved-company integration](docs/saved-company-integration.md), evidence checks, semantic refresh, configuration validation and local provenance auditing. Live retrieval and batch execution remain unimplemented. Original research stays under ignored `.idea/buildDocs/`.

Run the contract checks with Python 3.12.12:

```powershell
.venv\Scripts\python.exe -X dev -W error tools/validate_contracts.py
.venv\Scripts\python.exe -X dev -W error -m unittest discover -s tests -v
```

See [CONTRIBUTING](CONTRIBUTING.md) for setup and change validation, and [SECURITY](SECURITY.md) for the current security posture. The prior hosted contract workflow failed during Windows Python setup. This change uses pinned Python 3.12.12 on Linux and 3.12.10 for Windows compatibility; its hosted result is pending. A project licence remains to be selected before an OSS release.
