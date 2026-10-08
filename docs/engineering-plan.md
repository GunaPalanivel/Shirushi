# Engineering plan

Repository bootstrap establishes the runtime, contracts, access decisions and acceptance checks before implementing retrieval. The original numbered stages were planning shorthand, not a Signalpost requirement. Milestones below use the engineering deliverable as their name. The six-document research plan and all 176 lines of `researchDirection.md` were reviewed; originals remain unchanged under ignored `.idea/`.

Repository bootstrap and contract validation are complete locally. The audit verifies the isolated runtime, input hashes, archive inventory, source receipts, configs, document links and boundary tests. The official settings template remains deliberately rejected. [Engineering standards](engineering-standards.md) distinguishes official requirements, adopted OSS practices and remaining release work.

The problem is to turn an arbitrary supplied Norwegian organisation batch and frozen identity snapshot into fresh, exact-company, supported profiles. The scoring outcome is 80+ official points; the immediate engineering outcome is one inspectable saved-company path without dropped identity, unsupported publication or false change. [Official evaluation contract](https://builderr.ai/docs/signalpost-evaluation-harness.md).

End-to-end sequence:

| Milestone | Deliverable | Acceptance gate |
| --- | --- | --- |
| Repository bootstrap | Contract, source policy, runtime and configuration | Audited inputs; reproducible boundary checks; unknowns recorded |
| Saved-company integration | Canonical identity â†’ snapshot â†’ candidate â†’ checker â†’ envelope â†’ replay | Inspect actual support and repeat without false change |
| Batch-runner hardening | 20-company bounded pilot | Exact membership, terminal output under failure, no unsupported material facts |
| Retrieval baseline | Independently labelled 100-company baseline | Attribute opportunities and failure stages measured |
| Retrieval ablations | E2â€“E6 source experiments | Same-pool confirmed gain within budget and precision gates |
| Product acceptance | Supported synthesis/UI, refresh/resume, sealed assessment | Product tasks, evidence, chaos and resource checks |
| Release candidate | Frozen clean-room candidate, 100-company live smoke | One command, pinned dependencies, declared access/cache/cost |
| Official evaluation | Separately authorized run/revisions | Organizer evidence establishes score and qualification |

The complete original architecture, experiment forecasts, sampling and release instructions remain in `.idea/buildDocs/`. These tracked documents preserve operational decisions without publishing source bodies.

Bootstrap acceptance evidence:

| Requirement | Artifact | Validation |
| --- | --- | --- |
| Local repository and baseline | `main`, configured origin; existing first commit preserved | Git branch/remote/status; no remote mutation |
| Ignore research | [`.gitignore`](../.gitignore) | `git check-ignore` and no tracked `.idea/` path |
| Environment | [Python pin](../.python-version), [project metadata](../pyproject.toml), [dependency baseline](../configs/runtime-baseline.json) | Isolated `.venv` is Python 3.12.12; no third-party application dependencies |
| Input provenance | Local universe/archive audit receipt | Compressed/uncompressed hashes, 411,160 rows, safe-member inventory |
| Current official rules | Three current source captures, timestamps and hashes in ignored local receipt | Full contract/brief/source policy read and hash checked |
| Reuse decisions | [Source policy](source-policy.md) | No licence member in starter; no copied implementation code |
| Locked local interface | [Contract](company-envelope.md), [machine contract](../contracts/company-envelope.v1.json) | Identity membership, states, values, references and timestamps tested |
| Declared budgets | [20](../configs/local-pilot.json), [100](../configs/local-smoke.json), [300](../configs/local-evaluation.json) | Finite typed settings; inactive sources refused; defaults are local only |
| Unresolved official facts | [Official template](../configs/official-run.template.json) | Intentionally rejected, not silently given local defaults |
| Research decisions and forecasts | [Research decisions](research-decisions.md) | Positive/negative controls recorded before run |
| Repository practices | [CONTRIBUTING](../CONTRIBUTING.md), [SECURITY](../SECURITY.md), [CI](../.github/workflows/contract-validation.yml) | Portable checks, editing conventions, immutable action pins; saved-company commit passed hosted Linux and Windows checks; batch change locally validated |

Reproduce on this machine:

```powershell
.venv\Scripts\python.exe -X utf8 tools/validate_contracts.py
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.venv\Scripts\python.exe -X utf8 tools/audit_repository.py
```

For a new machine, install Python 3.12.12, then `python -m venv --without-pip .venv`. No application dependency installation is needed for repository bootstrap. Exact platform/runtime receipts are local; future adapters will need a real dependency lock and clean-room validation. The audit requires the ignored local research files; boundary tests and config checking are independent of those files.

Manual trace before integration:

1. Requested `[810034882]`, returned `[999999999]`: length is one but membership differs, so reject before any score calculation.
2. Candidate phone `81003488`, extension `2`: concatenation creates `810034882` but not contextual legal identity, so it remains rejected/ambiguous.
3. Source supports employees `0`: available zero with evidence is allowed. No fetched result: null plus reason, never zero.
4. Same accepted semantic claim at the second observation: keep evidence/history without a material change. Timeout: preserve prior support and mark observation failure.

Saved-company integration is implemented with a frozen-row reader, retained archive/row snapshots, separate extraction and acceptance, envelope serialization and semantic refresh. [Implementation and acceptance evidence](saved-company-integration.md) documents the narrow offline scope. [Batch-runner hardening](batch-runner-hardening.md) implements the twenty-company supervisor, saved official roles and separate source-reference audit. The next milestone is the hundred-company retrieval baseline: expand reference opportunity coverage and freeze the baseline strategy, source snapshots and reference pool before any challenger. Structured accounts and deeper PDFs remain E2 in source challengers, matching the original phase sequence. Existing accounts bodies are reference-only, not maker capabilities. The separate reviewer has now adjudicated corrected P1 and all published/reference claims in the existing frozen pilot. These agent-review results apply only to their bound artifacts, not human review or a new twenty-company run on corrected code. See [retrieval validation and promotion gates](retrieval-validation.md).

A safe live fetcher and global request/retry/redirect/byte/cost accounting must pass adversarial tests before any live baseline or challenger. An offline baseline cannot certify live resource controls. Independent agent adjudication is recorded separately from automated source auditing and independent human review.

Official release remains blocked on actual resource settings, confirmed wire adapter, source access declarations, complete agent implementation and smoke/clean-room evidence. Unknown family weights and equivalence rules limit private-score prediction. Deadline timezone remains unknown. These are explicit later gates, not excuses to delay local coding.

## Current implementation update, 8 October 2026

The historical milestone descriptions above refer to their original bound runs. PR #1 implemented the bounded live foundation, structured revenue route, canonical claims and static profiles; its fresh 100-company run audited 941 supported facts with 400 agent requests. That did not establish representative recall or an official score. The next slice expands explicit structured financial fields at unchanged acquisition cost, with a separately implemented source-subset benchmark and two non-overlapping public 100-company cohorts. See [financial coverage](financial-coverage.md). Six-family independently searched/adjudicated gold, PDF and broad verified-site challengers, planner promotion, browser acceptance and the organizer-confirmed boundary remain later gates.

The competitive metric for subsequent retrieval phases is additional independently supported company coverage within each information type (official 70%), followed by additional checked facts (30%). This financial slice may promote a fact-only gain as completeness; it cannot satisfy the external-recall breakthrough gate. Next: missing verified websites, products/services, jobs/public activity, and missing financial/PDF opportunities beyond the nine paths. A registry URL is a lead and registered activity does not measure product coverage. [Priorities, experiments and interpretation](financial-coverage.md#next-phase-after-financial-completeness).
