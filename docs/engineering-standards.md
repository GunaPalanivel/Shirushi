# Engineering standards and Signalpost rubric

The [official evaluation contract](https://builderr.ai/docs/signalpost-evaluation-harness.md), [participant brief](https://builderr.ai/starter-briefs/signalpost.md), and [source policy](https://builderr.ai/starter-briefs/signalpost-sources.md) were checked on 7 October 2026. They define a 50/30/12/8 rubric, official-run validity requirements, and source/publication rules. The checked documents do not prescribe an OSS badge, development-stage numbering, Python style guide, accessibility certification, or a specific project licence.

We use published standards and established OSS practices to make those requirements testable. They support engineering quality; they do not award competition points by themselves. No OpenSSF badge, WCAG conformance or official score is claimed.

## Traceability to the rubric

| Official requirement | Established reference | Project decision and evidence | Current state |
| --- | --- | --- | --- |
| Recall/coverage, 50: exact checked company/fact recall, 70/30 mixture | Official contract itself | Per-attribute retrieval, frozen reference pools and paired ablations; report company/fact numerators separately | Designed; no recall experiment or private-score reproduction |
| Evidence/identity, 30: valid source, time, subject and reporting period | [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) JSON; [RFC 3339](https://www.rfc-editor.org/rfc/rfc3339) timestamps | UTF-8 JSON, unique keys, finite supported numbers; known-offset timestamp profile; exact input/output membership and resolving evidence IDs | Boundary rules implemented and tested; real attribution/span checking pending |
| Evidence/identity, 30: lineage and retained prior support | [W3C PROV-DM](https://www.w3.org/TR/prov-dm/) entities, activities, agents and derivation | Snapshot/claim as entities, extraction/refresh as activities, adapter/reviewer as agents; keep source origin and acquisition receipt | Conceptual mapping only; no PROV serialization or conformance claim |
| Synthesis, 12: decision-useful supported explanations | Official contract and claim-level provenance | Compose from accepted claims, preserve periods/scope/conflicts, expose unknowns, reject unsupported sentences | Planned; no synthesis acceptance result |
| UX, 8: find/compare/verify on desktop and mobile | [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Target level AA: keyboard use, visible focus, contrast, reflow and accessible evidence disclosure | Target only; UI and accessibility evaluation pending |
| Run validity: reproducible pinned setup and one command | [PyPA project metadata specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/); [OpenSSF quality practices](https://www.bestpractices.dev/en/criteria/0#0.test) | Python pin, metadata, documented local checks and automated tests; eventual application dependencies locked separately | Local checks work; complete agent/clean-room release pending |
| Run validity: source rights and safe secrets/URLs | Official source policy; [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use) | Source register; offline baseline; CI read-only token, immutable action pins and no persisted credentials | Register and workflow implemented; fetcher and hosted CI execution pending |
| Public artifact: reviewed code and smoke report | [OpenSSF contribution/interface practices](https://www.bestpractices.dev/en/criteria/0) | README, CONTRIBUTING, interface docs, SECURITY, public portable test definition | Prepared locally; no smoke run, published changes or badge |

## Adopted implementation profiles

JSON follows RFC 8259 syntax, with stricter local rejection of duplicate keys and numeric overflow to nonfinite binary64 values. The RFC recommends unique object names; our rejection rule is an interoperability decision. JSONL is our framing choice, not a separate IETF JSON standard. Typed claim values and availability states are application rules from the competition contract and our local interface.

Timestamps use an explicit RFC 3339 subset: uppercase `T`, `Z` or numeric `±HH:MM`, seconds, optional 1–6 fractional digits, and a known offset. We reject unknown-offset `-00:00`, leap seconds and greater-than-microsecond precision. Some rejected forms are valid RFC 3339; this is a documented acquisition-time profile, not a claim to parse every RFC form. Calendar dates and completion order are validated. Retrieval, extraction and reporting times remain separate.

Python conventions follow [PEP 8](https://peps.python.org/pep-0008/) naming and layout guidance. `.editorconfig` specifies editing defaults; `.gitattributes` preserves LF in portable text. Existing code has not received a full style/static-analysis audit. Python development mode, warnings-as-errors, unit tests and compilation checks are enabled; those do not replace a linter or security analyzer. Select and pin development tools before a production release.

The company envelope file is a versioned local contract manifest. It is deliberately not named `schema.json`: it does not implement JSON Schema validation and has not been confirmed as Builderr's wire schema. A formal schema and official adapter can be added when the actual interface is established. Do not turn local key choices into undocumented organizer requirements.

## OSS release readiness

[OpenSSF Best Practices](https://www.bestpractices.dev/en/criteria/0) is our repository-practice reference, not a certificate we already hold. Its full criteria cover substantially more than file presence. [OSI's Open Source Definition](https://opensource.org/osd) depends on distribution rights, not public visibility alone.

| Practice | Evidence now | Remaining release work |
| --- | --- | --- |
| Clear purpose and input/output documentation | README, engineering plan, company envelope | Document the implemented runner and adapters |
| Automated tests and contribution process | Test suite, CONTRIBUTING, CI definition | Hosted CI run, actual review and maintenance history |
| Public version control | Local Git and remote configured | Publish only when authorized; interim changes currently uncommitted |
| FLOSS licensing and reuse notices | No unverified starter/competitor code copied | Owner selects an OSI-approved project licence; add its exact text and verified notices |
| Security reporting | SECURITY describes current state | Enable a verified private channel and response policy before release |
| Static analysis and dependency hygiene | No application dependencies yet | Pin analysis tools and actual runtime dependencies; review vulnerabilities |
| Versioned release and reproducibility | Project version and Python pin | Frozen commit, dependency lock, reviewed change notes, clean-room run and 100-company smoke report |

No licence is selected by this change. The repository is not presented as a licensed OSS release yet. The lack of an explicit licence member in the supplied starter remains a reuse gap; this does not establish that its author forbids use or that an OSS badge is required for Signalpost.

## Naming by responsibility

| Artifact | Responsibility |
| --- | --- |
| `docs/engineering-plan.md` | Milestones, dependencies and acceptance gates |
| `docs/company-envelope.md` | External input/output and record semantics |
| `docs/research-decisions.md` | Research assumptions, forecasts, outcomes and corrections |
| `contracts/company-envelope.v1.json` | Versioned machine-readable local interface manifest |
| `configs/runtime-baseline.json` | Runtime pin and current dependency scope |
| `configs/local-pilot.json` | Small-batch development budget |
| `configs/local-smoke.json` | Pre-submission local smoke budget |
| `configs/local-evaluation.json` | Held-out local evaluation budget |
| `configs/official-run.template.json` | Unconfirmed official settings, rejected until completed |
| `tools/validate_contracts.py` | Configuration and envelope boundary validation |
| `tools/audit_repository.py` | Local repository, original-input and evidence-provenance audit |
| `tests/test_contract_validation.py` | Positive controls and rejection counterexamples |
| `.github/workflows/contract-validation.yml` | Portable automated contract checks |

Stage names belong in the engineering plan. File/module names should describe enduring responsibilities so they stay meaningful after a milestone is complete. Historical source notes and receipts under ignored `.idea/` retain their original names for provenance.
