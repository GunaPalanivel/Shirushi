# Shirushi

Research and implementation planning for the Signalpost challenge.

Start with the [engineering plan](docs/engineering-plan.md), [rubric-to-standards mapping](docs/engineering-standards.md), [company envelope](docs/company-envelope.md), and [source policy](docs/source-policy.md).

Current implementation: configuration and envelope boundary validation, plus local provenance auditing. The company-research agent is not yet implemented. Original research stays under ignored `.idea/buildDocs/`.

Run the contract checks with Python 3.12.12:

```powershell
.venv\Scripts\python.exe -X dev -W error tools/validate_contracts.py
.venv\Scripts\python.exe -X dev -W error -m unittest discover -s tests -v
```

See [CONTRIBUTING](CONTRIBUTING.md) for setup and change validation, and [SECURITY](SECURITY.md) for the current security posture. The GitHub Actions workflow is prepared locally; it has not run remotely. A project licence remains to be selected before an OSS release.
