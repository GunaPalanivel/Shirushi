# Evaluator command

Use Python 3.12.12 on Linux and the command in [README](../README.md).
Input accepts JSONL objects containing `organisation_number`, a JSON list,
or one nine-digit ASCII organisation number per text line. Duplicate or invalid
identities are rejected before networking. Output, report, work and site paths
must be new and distinct.

Supply the registry's actual acquisition receipt:

```json
{
  "source_class": "frozen_registry",
  "dataset_format": "csv",
  "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
  "retrieved_at": "2026-10-08T04:30:00Z",
  "sha256": "<compressed archive SHA-256>",
  "uncompressed_sha256": "<decompressed bytes SHA-256>"
}
```

CSV and JSONL, optionally gzip-compressed, are supported. JSONL receipts use
`dataset_format: jsonl`. Archives are bounded to 1 GiB and expansion to 2 GiB.

Ordered shards contain at most 100 companies. Each has a 2,700-second deadline,
2,000 outbound-request ceiling and $10 external API ceiling. The default costs
$0 and requires no personal credentials. Optional anonymous discovery uses
`--discovery-access-receipt configs/anysearch-anonymous.json`; omit it for the
provider-free path. Search, robots, redirects and retries share the shard ledger.
No model calls are implemented. Any provisioned provider and environment variable
must be confirmed before freezing a paid revision.

Linux guards enforce at most eight CPUs, a combined 14 GB process address-space
ceiling, 8 GB retained snapshots and 0.5 GB generated artifacts. Collection stops
at 2,430 seconds, leaving time for checking and output. Use separate snapshot
stores for concurrent invocations. A failed child or audit cannot produce a
completed aggregate; inspect the report's child exit and shard artifact path.

For refresh, supply `--previous out/results.jsonl`, reuse `--store`, and choose
new output paths. Previous evidence is rechecked. The cutoff controls dated
facts; acquisition timestamps retain their actual times. Optional-source failure
does not establish absence or remove supported historical facts.

The output follows the published `run/claims/evidence` example and
`official_website` alias. The starter's nested `profile/modules/state` example
differs; private-harness compatibility still needs organizer confirmation.

Linux validation entrypoints:

```bash
python -X dev -W error tools/validate_official_boundary.py --output-dir out/boundary
python -X dev -W error tools/validate_official_live.py --output-dir out/live --discovery-access-receipt configs/anysearch-anonymous.json
```

The boundary check is synthetic. The live check uses a declared public registry
snapshot and frozen representative input; neither produces an official score.
