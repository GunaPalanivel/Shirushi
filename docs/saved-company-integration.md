# Saved-company integration

This milestone implements the former Phase 1: an offline, one-company vertical slice. Its outcome is an inspectable supported envelope and a refresh that cannot invent a removal. This document preserves the first milestone acceptance record. Multi-company scheduling and saved roles now extend this path in [batch-runner hardening](batch-runner-hardening.md); live retrieval, resume, synthesis, UI and official scoring remain later gates.

## Forecast recorded before validation

One real frozen row should yield eight supported fields, zero agent requests and zero changes on identical replay. Altered subject, value, type, source bytes or archive membership should be rejected. A failed refresh should retain all prior supported values with stale observation status and zero removals. A supported numeric zero should remain zero; missing data should be null. Changed supported employee count should yield exactly one value-change event and retain earlier evidence; replay should not grow history. These forecasts concern mechanics, not recall or private scores.

## Inputs, outputs and decomposition

Inputs are one requested legal identity, a frozen JSONL or JSONL.GZ registry, its acquisition receipt, a local offline configuration, and optionally a previously supported envelope. Outputs are one terminal envelope, a decision report, and immutable source bytes and receipts. Input errors return 2 before processing; source/check failure returns 1 with a terminal envelope; successful execution returns 0. Existing outputs are never overwritten.

| Module | Responsibility |
| --- | --- |
| `shirushi/contracts.py` | Strict JSON, timestamp, identity and boundary checks |
| `shirushi/registry.py` | Verify archive hashes, bound expansion, find exact subject |
| `shirushi/snapshots.py` | Retain original archive, exact row and content-addressed receipt |
| `shirushi/extraction.py` | Propose values without publication authority |
| `shirushi/evidence.py` | Independently check membership, subject, value, type and exact JSON span |
| `shirushi/refresh.py` | Compare supported values and preserve prior support/history |
| `shirushi/run.py` | Preflight, orchestration, terminal envelope and operation receipt |

The checker uses a separate field acceptance specification and does not call extraction. Tests use independently written labels, mutate maker proposals and source artifacts, and invoke the public CLI. This is functional separation, not a claim of independent human review.

## Meaning of supported fields

Legal name/form, registered employee count, registered municipality/code, industry code/label, and latest submitted accounts year are frozen-registry observations. Acquisition time is not the business fact's effective date. Registered municipality is not an operating address; registered employees are not a current headcount estimate; filing-year metadata is not revenue, profit or accounts history. Registry website strings are deliberately outside accepted ownership evidence.

The receipt is operator-supplied provenance. Hashes establish byte integrity and membership, not cryptographic proof that a source author supplied the receipt or that its assertions are true. Verification of an official download is recorded separately in local research evidence.

## Manual trace before running

For input `810034882`, the original row says `SANDNES ELEKTRISKE AS`, employees `11`, accounts submission year `2025`. The selected row is retained unchanged. The checker rereads the full archive, verifies both hashes and the row number, then verifies the source organisation number before inspecting a proposed field. A proposal of employees `12` fails exact typed comparison. An accepted `11` references its original value token and receipt. Replaying the same snapshot compares `11` with `11`, adds no change and preserves first observation. Failed acquisition has no supported replacement; prior `11` remains available with stale status. No step consults another entity or reconstructs identity from unrelated digits.

## Reproduce locally

Use Python 3.12.12 and no application dependencies. Place the original archive and a receipt under ignored `data/saved-company/`. The receipt requires `source_class: frozen_registry`, credential-free HTTPS `source_url`, original `retrieved_at`, compressed `sha256`, and `uncompressed_sha256`. Provide one JSONL identity; the example is an inspectable pilot, not a hardcoded identity in the runner.

```powershell
.venv\Scripts\python.exe -m shirushi.run --organisations data/saved-company/organisations.jsonl --registry data/saved-company/registry.jsonl.gz --registry-receipt data/saved-company/registry-receipt.json --config configs/local-pilot.json --store out/saved-company/snapshots --output out/saved-company/first.jsonl --report out/saved-company/first-report.json --run-id saved-first
.venv\Scripts\python.exe -m shirushi.run --organisations data/saved-company/organisations.jsonl --registry data/saved-company/registry.jsonl.gz --registry-receipt data/saved-company/registry-receipt.json --config configs/local-pilot.json --store out/saved-company/snapshots --previous out/saved-company/first.jsonl --output out/saved-company/replay.jsonl --report out/saved-company/replay-report.json --run-id saved-replay
.venv\Scripts\python.exe -X dev -W error -m unittest discover -s tests -v
```

Shared `--store` is required to reverify prior support across output directories. Replays preserve semantic claims/evidence/history, not observation timestamps or elapsed runtime. Change records describe this observation; earlier events remain in earlier immutable envelopes and prior values in `history`. An older acquisition cannot replace newer supported observations. Missing fields and source failure never prove deletion. No resume flag is implemented.

## Acceptance evidence

The validation suite passes 48 tests in Python development mode with warnings as errors. One real registry row (`810034882`) produced eight supported fields and no agent network requests. Same-snapshot replay produced zero changes and no history growth. A deliberately unavailable source returned a failed terminal envelope, preserved all eight supported values, exposed stale status and produced zero removals. The read-only verifier passed both comparisons. Full captures, original receipts, comparison results and corrections stay in ignored `.idea/buildDocs/saved-company-integration/`.

```powershell
.venv\Scripts\python.exe tools/validate_saved_company.py --organisations data/saved-company/organisations.jsonl --first out/saved-company/first.jsonl --replay out/saved-company/replay.jsonl --store out/saved-company/snapshots
```

The portable suite is also checked from a separate directory containing only public code, synthetic tests, configs and contracts. No ignored research or real-company data is required for those tests. The real source audit remains local and separately hash-bound.

The previous hosted contract CI failed before Windows tests: `actions/setup-python` could not install 3.12.12 because its release manifest lists Linux builds only. Linux now retains the production pin; Windows uses pinned 3.12.10 to test compatibility. The saved-company commit subsequently passed the corrected hosted contract workflow on Linux and Windows (run 37674569882). The earlier successful run was Dependency Graph, not contract CI; the initial interpretation was corrected.

Historical first-milestone limits: its local deadline bounded initial archive scanning, not a process-wide hard timeout. Archive verification uses bounded reads (64 MiB archive, 512 MiB expanded stream, 1 MiB row), but memory and CPU are not externally enforced. The batch milestone now adds supervised worker termination and atomic artifact publication; externally enforced memory/CPU limits, resume and full filesystem transaction recovery remain unimplemented. An operator receipt is a trust input. No independent human adjudication or fresh external-company coverage is established.

The official evidence/identity and refresh requirements motivate exact attribution, acquisition lineage and replay checks. These tests do not measure the official 50-point recall component, 12-point synthesis or 8-point UX. See the [rubric-to-standards mapping](engineering-standards.md).

## Research discipline

Work backwards from supported output; predict each control before execution; use primary source bytes and inspectable reference implementation patterns; read full sources and limitations; retain failures; run the smallest falsifiable case first; separate proposal from acceptance; keep reusable acceptance tests and evidence receipts. The starter replay was inspected for snapshot comparison behavior, with special attention to failure-versus-removal. Its implementation was neither copied nor executed because reuse terms remain unestablished. Prior company-research papers informed attribute-level retrieval, copy-aware provenance and entity integration; no paper is evidence that this implementation attains a score.

## Correction and independent review — 8 October 2026

P1 prior-state checks now reject unreferenced evidence, unavailable history containing a value, future observation timestamps and source-context mismatches. The separate reviewer found the orphan-evidence gap; each correction has a counterexample, and legitimate history remains supported. Network-enabled local runs are explicitly refused pending live-fetch/accounting tests.

All 74 current tests passed locally and from public files only. A new one-company first/replay/failed-refresh run retained eight verified facts with zero false changes. A separate Codex reviewer directly checked source/archive bytes, exact typed values, locators, support tokens and refresh retention for all eight facts across all three artifacts, and independently confirmed the negative cases. The agent review passed; independent human review remains false. Historical 48-test receipts are unchanged; the superseding correction receipt is `.idea/buildDocs/p1-correction/validation-report.json`. See [retrieval validation](retrieval-validation.md) for the baseline/accounts order and 80+ evidence boundary.
