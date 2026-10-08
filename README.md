# Shirushi

Evidence-checked company research for the Signalpost challenge.

Start with the [engineering plan](docs/engineering-plan.md), [rubric-to-standards mapping](docs/engineering-standards.md), [company envelope](docs/company-envelope.md), and [source policy](docs/source-policy.md).

Current implementation: [bounded offline batch execution](docs/batch-runner-hardening.md), saved official roles, evidence checks, semantic refresh and separate source-reference evaluation. Live retrieval, synthesis and UI remain unimplemented. Original research stays under ignored `.idea/buildDocs/`.

Run the contract checks with Python 3.12.12:

```powershell
.venv\Scripts\python.exe -X dev -W error tools/validate_contracts.py
.venv\Scripts\python.exe -X dev -W error -m unittest discover -s tests -v
```

See [CONTRIBUTING](CONTRIBUTING.md) for setup and change validation, and [SECURITY](SECURITY.md) for the current security posture. The saved-company commit passed hosted contract checks on Linux and Windows; this batch change has local validation and has not been pushed. CI pins Python 3.12.12 on Linux and 3.12.10 for Windows compatibility. A project licence remains to be selected before an OSS release.
