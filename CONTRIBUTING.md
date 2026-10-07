# Contributing

Read the [engineering plan](docs/engineering-plan.md), [company envelope](docs/company-envelope.md), and [rubric mapping](docs/engineering-standards.md) before changing behavior. Use an issue or pull request to describe the concrete problem, proposed behavior, evidence and validation. Public changes include validation evidence and document unmeasured behavior.

Use Python 3.12.12 and a local virtual environment. The current checks need no application dependencies:

```powershell
python -m venv --without-pip .venv
.venv\Scripts\python.exe -X dev -W error tools/validate_contracts.py
.venv\Scripts\python.exe -X dev -W error -m unittest discover -s tests -v
```

On Linux/macOS use `.venv/bin/python`. CI defines portable checks on Linux 3.12.12 and Windows 3.12.10 compatibility; the corrected hosted run is pending. `tools/audit_repository.py` additionally requires ignored local research inputs and is deliberately excluded from public CI. The [saved-company runbook](docs/saved-company-integration.md) covers real-source replay verification.

Follow [PEP 8](https://peps.python.org/pep-0008/): four-space indentation, `snake_case` functions/modules, explicit imports and readable control flow. Name files for their responsibility, not a development stage. Use `test_contract_validation.py` for envelope/configuration invariants and future adapter-specific test files for retrieval/extraction behavior. Separate source acquisition, identity resolution, extraction, evidence checking and serialization.

For behavioral changes, include a failing counterexample and a meaningful positive control. A test should check an externally observable invariant, not repeat the implementation. Preserve null versus supported zero, legal subject, reporting period, source origin and refresh history. Add dependencies only for implemented needs; pin and review runtime dependencies separately from development tools before release.

Keep PRs focused. State what changes, why, how it was validated and what remains unmeasured. Run contract validation, tests and `git diff --check`. Use UTF-8 and LF as recorded by `.editorconfig` and `.gitattributes`. Static analysis and automated formatting are pending tooling decisions; no full PEP 8 conformance is claimed for existing modules.

Do not commit `.idea/`, scraped content, real-company fixture exports, credentials or final evaluation labels. Review fixtures for rights and privacy. No project licence is selected yet; establish the licence before an OSS release, and preserve verified third-party notices if reuse is introduced.
