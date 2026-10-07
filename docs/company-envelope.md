# Company envelope contract v1

The [machine-readable contract](../contracts/company-envelope.v1.json) locks our implementation boundary. It derives from the [official evaluation prose](https://builderr.ai/docs/signalpost-evaluation-harness.md) and the supplied starter's minimal example. It is not an organizer-confirmed JSON Schema. A future official adapter can translate these records without changing their evidence semantics.

Input is a nonempty JSONL batch of objects with a nine-digit ASCII `organisation_number` string. Reject malformed and duplicate input before network activity. For valid input, output one JSONL envelope for exactly each supplied identity in order, including failure. The input number is the anchor; no name-based substitution is allowed.

The implemented offline, one-company runner interface is:

```powershell
python -m shirushi.run --organisations batch.jsonl --registry frozen-registry.jsonl.gz --registry-receipt registry-receipt.json --config configs/local-pilot.json --output out/run/envelopes.jsonl --report out/run/report.json --run-id local-001
```

Optional `--previous` supplies prior state, which is reverified against retained bytes before use. `--store` selects the shared content-addressed snapshot directory. Resume and batch scheduling remain unimplemented. See [saved-company integration](saved-company-integration.md) for receipt requirements, field semantics and replay commands.

An envelope contains `organisation_number`, `run`, `claims`, `evidence`, `changes`, `errors`, and `operations`. Run terminal states are locally `completed` or `failed`; field availability is separately `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, or `failed`. Run completion does not imply all information is available.

Available claims have non-null typed values and resolving evidence references. All other availability states have null values and a reason. An evidence record includes source, original acquisition timestamp, raw-content SHA-256, support span, extraction method, and a reproducible locator. Relevant financial/job/role claims additionally retain period, units, entity/group scope and effective dates; saved-company integration supplies field-specific checking. Numeric zero must be directly supported.

The adopted [JSON and timestamp profiles](engineering-standards.md) reject duplicate object names, unsupported nonfinite numeric values and ambiguous timestamps. Acquisition/run timestamps use uppercase `T`, known `Z` or numeric offsets and at most six fractional digits. Leap seconds and unknown-offset `-00:00` are outside this local profile. This is a deliberate subset of RFC 3339, not a universal ISO 8601 parser.

Required profile sections are legal identity/brand, accounts/history, leadership/workplaces, verified website/owned profiles, hiring/dated activity, evidence/availability, and refresh/changes. The first saved-company milestone builds a narrow vertical path; it does not claim all required sections or live coverage.

Internal identities and transitions:

| Record | Key and input | Output / invariant |
| --- | --- | --- |
| Entity | `BRREG:NO` plus org number and frozen row | Stable legal subject; brands/parents/subunits are relationships |
| Opportunity | entity + field family + period | Missing/covered/unknown status and bounded next route |
| Attempt | run + adapter/version + target | All cost/time/requests, rejection and classified failure |
| Snapshot | raw bytes hash plus acquisition receipt | Immutable bytes, requested/final URLs, access policy, parser version |
| Candidate | subject + field + proposed value + source locator | Maker proposal only; never directly published |
| Decision | candidate + checker version + proof | Accept/reject/ambiguous with reasons; source context matters |
| Claim | subject/field/object/period/unit/scope | Deduplicated semantic fact; evidence may have several origins |
| Rejection | candidate/reason/validity interval | Retain failure history, but revalidate changed domains |
| Change | old/new claim and supporting snapshots | Same semantic snapshot has no change; source failure never implies removal |

`tools/validate_contracts.py` checks config and envelope boundaries. It cannot establish source-byte integrity, span support, factual truth, identity ownership, source rights, full section coverage, or refresh correctness. The [saved-company integration](saved-company-integration.md) now checks frozen-row integrity, membership, subject, value spans and semantic refresh. Wider source truth, ownership, rights and coverage remain later gates. Its synthetic positive tests must never be called real-company validation.
