# Contributing

Read the [company envelope](docs/company-envelope.md) and [source policy](docs/source-policy.md) before changing behavior. Describe the concrete problem, resulting behavior and validation in the pull request.

Use Python 3.12.12 and a local virtual environment. The current checks need no application dependencies:

```powershell
python -m venv --without-pip .venv
.venv\Scripts\python.exe -X dev -W error tools/validate_contracts.py
.venv\Scripts\python.exe -X dev -W error -m unittest discover -s tests -v
```

On Linux/macOS use `.venv/bin/python`. CI checks Linux 3.12.12 and Windows 3.12.10. `tools/audit_repository.py` requires ignored local research inputs and is excluded from public CI. See the [evaluator command](docs/evaluator-command.md) for Linux execution and refresh.

Follow [PEP 8](https://peps.python.org/pep-0008/): four-space indentation, `snake_case` functions/modules, explicit imports and readable control flow. Name files for their responsibility, not a development stage. Use `test_contract_validation.py` for envelope/configuration invariants and future adapter-specific test files for retrieval/extraction behavior. Separate source acquisition, identity resolution, extraction, evidence checking and serialization.

For behavioral changes, include a failing counterexample and a meaningful positive control. A test should check an externally observable invariant, not repeat the implementation. Preserve null versus supported zero, legal subject, reporting period, source origin and refresh history. Add dependencies only for implemented needs; pin and review runtime dependencies separately from development tools before release.

Reference parsing and support auditing in `shirushi_eval` must not import maker extraction or acceptance. Construct expected labels from independently acquired inputs before observing candidate output. Unknown opportunities are not negative labels. Report source-subset numerators and missing routes; never manufacture an official total from provisional families. Keep final labels out of development tuning and record the absence of independent human adjudication.

Keep PRs focused. State what changes, why, how it was validated and what remains unmeasured. Run contract validation, tests and `git diff --check`. Use UTF-8 and LF as recorded by `.editorconfig` and `.gitattributes`. Static analysis and automated formatting are pending tooling decisions; no full PEP 8 conformance is claimed for existing modules.

Do not commit `.idea/`, scraped content, real-company fixture exports, credentials or final evaluation labels. Review fixtures for rights and privacy. No project licence is selected yet; establish the licence before an OSS release, and preserve verified third-party notices if reuse is introduced.
