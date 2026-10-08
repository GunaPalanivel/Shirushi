# Supervised live retrieval

## Contract and scope

Inputs are the supplied ordered JSONL company numbers, explicit local resource configuration, optional prior envelopes, and an existing snapshot store for refresh. Outputs are exactly one terminal envelope per input, an output-hash-bound run report, retained source objects/receipts, and optionally static `/signalpost/` profiles. The existing offline CLI remains compatible.

This implements the production foundation of the combined 80+ plan. It is not an official wire adapter or evidence of 80+ recall. Official numeric limits, frozen organizer identity anchoring and output schema remain unconfirmed. Official mode is rejected rather than silently treating local settings as organizer requirements. The fixed strategy is the release default; the empirical adaptive strategy is opt-in through `routing_policy` and requires equal-budget held-out validation before promotion.

| Route | Accepted facts | Bounds and limitations |
|---|---|---|
| BRREG entity | Legal name/form, explicitly registered employee count/address/activity, declared website lead | Activity is registered activity, not inferred products; a declared website does not prove operating-page ownership |
| BRREG roles | Existing source-checked registered person roles | No inferred employment; an absent role does not establish removal |
| BRREG accounts | Annual revenue, separate entity/group scope and reporting periods, original currency units | Missing amounts remain unknown; no PDF parser or implied all-history access |
| BRREG subunits | Registered operating sites with exact parent attribution | First bounded page only; further pagination remains a recall opportunity |
| Company-owned pages | Exact-identifier JSON-LD descriptions, website, jobs and dated articles | Registry website anchor plus robots checks; same-host bounded link discovery; no broad free-text extraction or third-party jobs/news feed |

The effective network concurrency is one. Configured ceilings are not inferred quotas or throughput guarantees. Requests include attempts that fail DNS/connect, retries, redirects and robots. Body bytes are charged while reading; all routes share the ledger. CPU/memory settings for official isolation are not implemented. Paid API cost is zero because no paid route is activated.

## Manual trace and invariants

1. Anchor all supplied companies using exact BRREG entity numbers before deeper retrieval. A wrong or unavailable identity cannot authorize external routes.
2. Visit one optional route per company per round. Fixed routing gives the control; the adaptive scheduler ranks missing-family opportunities using observed verified gains and request cost, exploring unknown routes first.
3. Persist bytes and receipts before accepting candidates. Accounts retain period, currency and company/group interpretation. Source-specific checkers publish supported values only.
4. Key an active claim by subject, predicate, stable item, scope and period. Asserted values remain outside the key. Revenue for 2024/2025 and entity/group can coexist; a revised 2025 entity value creates one history change.
5. Conflicting same-slot values abstain. Identical copied candidates do not become corroboration votes. Failed refresh retains reverified earlier support as stale, without creating a value change.
6. Send checked checkpoints to the supervisor. Budget exhaustion preserves their supported facts. Every supplied company receives a terminal result; a failed batch does not become a successful scored run merely because its rows are complete.
7. Serialize the envelope and hash-bound completion report atomically. A report is the completion marker. Reusing output/report paths is refused. Refresh uses `--previous` and the same `--store` with new output paths; crash resume is not implemented.

| Counterexample | Expected behavior |
|---|---|
| Redirect to loopback or another host | Refuse before connecting |
| DNS includes public and private addresses | Refuse the entire destination |
| Budget exception inherits `OSError` | Propagate exhaustion, never retry it |
| Account row belongs to a subsidiary | Reject under the parent's profile |
| Entity and group report the same year | Preserve both distinct scopes |
| Two conflicting values share one fact slot | Mark ambiguous, do not select by duplicated evidence count |
| Job belongs to another employer on the same site | Reject without exact employer identifier |
| Repeated unchanged snapshot | No duplicate active claims or false changes |
| Optional page blocked, identity succeeds | Preserve checked facts and expose the source availability |
| Worker stalls after checking facts | Terminate it, retain checked checkpoint, mark unfinished execution failed |

## Validation and release gates

The existing 74 tests passed before changes. Added checks cover money/period/scope/identity tampering, independent support auditing, refresh, conflicts, failed request accounting, robots, URL/DNS scope, byte bounds, batch budget failures and escaped profile text. Hosted CI runs the full portable suite plus fresh public 100-company source support on Linux. Run `tools/validate_live_run.py` for an independently audited live cohort; generated bodies and real-company receipts remain ignored.

The independent audit imports no maker extractor or acceptance checker. Its result checks source support, not the completeness of the official collection. Labels require independently acquired sources and human adjudication before any competitive recall assertion. Public AS/2025 cohorts are neither representative random samples nor disjoint held-out gold.

The local workspace's direct external DNS fails, so local live execution correctly produced failed terminal output rather than weakening DNS protections. Real network acquisition must pass hosted CI or a directly connected deployment environment. The observed budget retry bug was fixed at its exception hierarchy, not hidden by increasing the budget.

The profile UI is escaped static HTML with search, comparison, accessible labels/focus, mobile reflow, source receipts, unknowns and history. Summaries are deterministic compositions of accepted claims. No synthesis/UX points, accessibility certification or browser acceptance result is claimed.

Before promoting adaptive routing, compare fixed/adaptive with identical adapters, source cutoff, cache conditions and global budgets on independent cohorts. Record per-family company/fact denominators, false attribution, unsupported finance, costs, failures and abstentions. Retain fixed routing if improvement disappears on validation. PDF extraction, broader web coverage, source-origin fusion gains, complete pagination, representative recall labels, browser acceptance and official calibration remain subsequent gates.
