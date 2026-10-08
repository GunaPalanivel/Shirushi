# Published-contract evaluator command

Use pinned Python 3.12.12 on Linux. The application uses only the standard
library. Playwright is optional development tooling for browser acceptance.
Supply the organiser's actual company input, frozen registry, registry receipt
and evidence cutoff. The program never replaces that input with its test cohort.

The public `OUTPUT_CONTRACT.md` uses `run/claims/evidence` and `official_website`.
The starter's `run_competition_batch.py` instead emits `profile/modules/state`.
This command implements the former and preserves extra provenance and refresh
fields. It cannot confirm which private wrapper Builderr will select; that exact
wire variant needs confirmation before a release is frozen. There is no official
score in a local report.

The supplied batch can grow. Ordered chunks of at most 100 companies each receive
the mail's 2,700 seconds, 2,000 outbound attempts and $10 external API limit.
The default spend is $0. Chunks run sequentially in this command; a harness can
invoke separate disjoint chunks concurrently with separate artifact paths and
stores. No aggregate wall budget is invented, and budgets never reset inside a
shard. A failed shard remains a failed run even when all terminal rows exist.

## One command

```bash
python -X dev -W error -m shirushi.official \
  --organisations supplied/company-input.jsonl \
  --registry supplied/frozen-registry.csv.gz \
  --registry-receipt supplied/frozen-registry-receipt.json \
  --cutoff 2026-10-08T06:00:00Z \
  --output out/version-1.jsonl \
  --report out/version-1-report.json \
  --work-dir out/version-1-work \
  --store out/retained-snapshots \
  --showcase-dir out/version-1-site \
  --run-id version-1
```

Input supports JSONL records, a JSON list (or `organisation_numbers` list), and
one exact ASCII nine-digit organisation number per text line. Duplicates, mixed
punctuation and invalid identities are rejected before networking. Output/report,
work directory and showcase must be new distinct paths. Serve the generated site
root and open `/signalpost/`.

The source receipt carries actual acquisition provenance, not the time at which
we read a cache. The organiser should supply this metadata or identify the
frozen source's original acquisition time and hashes:

```json
{
  "source_class": "frozen_registry",
  "dataset_format": "csv",
  "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
  "retrieved_at": "2026-10-08T04:30:00Z",
  "sha256": "<complete compressed archive SHA-256>",
  "uncompressed_sha256": "<complete decompressed bytes SHA-256>"
}
```

Use `dataset_format: jsonl` for `.jsonl` or `.jsonl.gz`; expected normalized keys
are `organisation_number`, `name`, `legal_form`, `employees`, municipality/industry
fields and `latest_submitted_accounts`. `website` is only a retrieval lead.
CSV uses the exact lower-case BRREG API column names. It supports quoted commas,
semicolons, doubled quotes and multiline values. All parsed CSV columns are
retained in canonical JSON bytes and reselected from the original full archive
by both checker implementations; evidence marks `registry_csv_column_v1`.
The canonical selected row is a derived representation, not original CSV bytes.
Header and every original byte remain bound by the archive hashes and row index.

Archive input is bounded to 1 GiB, expansion to 2 GiB and a physical line to
1 MiB. Explicit registered employee zero is supported; a false
`harRegistrertAntallAnsatte` flag leaves the field unknown. Missing data never
becomes zero. A missing or ambiguous legal name prevents optional source use.

## Refresh and evidence cutoff

For the next run, add `--previous out/version-1.jsonl`, reuse
`--store out/retained-snapshots`, and choose new output/report/work/site paths.
Every prior supported claim and history item is source-checked before it can be
republished. Prior output may contain a unique subset of the new supplied batch;
new companies start without previous values, so growing membership does not
block refresh. Extraneous and duplicate prior identities are rejected.
The `official_website` alias reverses before refresh; canonical
internal IDs and evidence IDs stay unchanged. A same-snapshot replay has no value
changes or history growth. Historical evidence is retained privately; withdrawn
vacancies are excluded from public history.

The supplied cutoff is recorded separately from real source retrieval times.
Dated website facts and NAV postings are checked against it. A live current
feed cannot reconstruct a vacancy already deleted from a historical feed; no
as-of completeness is claimed. A truncated NAV window cannot prove no jobs.
Optional source outage preserves frozen identity and explicit unknowns; a failed
worker/deadline keeps all supervisor terminal slots and marks the run failed.

## Resource enforcement and artifacts

Linux affinity is limited to at most eight available CPUs; inherited address
space is limited to 2,000,000,000 bytes in each supervisor and 8,000,000,000
bytes in the worker. The launcher, shard supervisor, resource tracker and worker
have a combined address-space ceiling of 14,000,000,000 bytes, below either
interpretation of 16 GB. These are virtual address-space bounds; they do not
claim that every host supplies 16 GB. Snapshot writes have a shared
8,000,000,000-byte ceiling; all other generated files share 500,000,000 bytes.
Existing snapshot bytes count, deduplicated objects do not add another copy, and
atomic temporary files are removed. The supplied source input is not charged as
new scratch writes, but the retained archive is. The lower write ceiling leaves
room for the bounded supplied archive and previous output. Final output is bounded to
128 MiB. These conservative write ceilings fit below decimal or binary 10 GB.
Use one writer per snapshot store, including sequential shards and refresh;
independent concurrent harness invocations must use separate stores.

The worker stops acquiring at 2,430 seconds. The outer command limits each shard
to 2,700 seconds including the final independent source audit, which runs in a
separate subprocess with only the remaining shard time. Every HTTP attempt,
retry, redirect, robots, search and public-token request is charged by the atomic
ledger. No model calls are implemented. An output/report hash pair is the
completion marker. A partial or corrupt shard cannot become a completed aggregate.

Reports contain input, registry, receipt, code and output hashes, per-shard
attempt totals, elapsed time, terminal completion p50/p95, failures and guard
settings. Completion latency starts at the shared run start and includes frozen
verification, queueing and optional-source work; terminals are published after
the acquisition rounds. Separate process RSS high-water values are measured and
are not described as simultaneous summed memory. Source snapshots and
real-company outputs stay in ignored local artifacts. Public smoke summaries do
not include raw bodies. Frozen input preparation is declared separately from
the evaluator command: the local smoke helper downloads a public BRREG archive,
whereas an official run receives its frozen archive from Builderr.

## Acceptance commands

```bash
python -X dev -W error tools/validate_contracts.py
python -X dev -W error -m unittest discover -s tests -v
python -X dev -W error tools/validate_official_boundary.py --output-dir out/cold-boundary
python -X dev -W error tools/validate_official_live.py --output-dir out/frozen-live
```

`--offline` on the evaluator command exercises snapshot identity and output
only; it is never described as a live recall run. Browser acceptance uses
`tools/validate_showcase_browser.cjs` with pinned Playwright 1.58.2 and 100
synthetic profiles, testing search, comparison, zero/unknown, evidence navigation
and width at 1440, 390 and 320 pixels. Hosted checks retain screenshots and bound
summary receipts. The score promotion gates remain in the release plan.
