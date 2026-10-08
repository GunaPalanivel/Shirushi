"""Published-command smoke with a declared local frozen registry, not an official score."""
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shirushi.contracts import load
from shirushi.run import read_envelopes, write_new
from shirushi.snapshots import digest
from shirushi_eval.wire import internal_records


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise ValueError('Frozen smoke snapshot download cannot redirect')


def download_snapshot(directory):
    url = 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv'
    started = datetime.now(timezone.utc).isoformat()
    path = directory / 'registry.csv.gz'
    hasher, size = hashlib.sha256(), 0
    with build_opener(NoRedirect()).open(url, timeout=30) as response, path.open('xb') as target:
        if response.status != 200:
            raise ValueError('Frozen registry acquisition status differs from 200')
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 1024 * 1024 * 1024:
                raise ValueError('Registry archive exceeds 1 GiB')
            target.write(chunk)
            hasher.update(chunk)
    expanded, expanded_hash = 0, hashlib.sha256()
    with gzip.open(path, 'rb') as source:
        while chunk := source.read(1024 * 1024):
            expanded += len(chunk)
            if expanded > 2 * 1024 * 1024 * 1024:
                raise ValueError('Registry expansion exceeds 2 GiB')
            expanded_hash.update(chunk)
    receipt = directory / 'registry-receipt.json'
    write_new(receipt, {'source_class': 'frozen_registry', 'dataset_format': 'csv', 'source_url': url,
        'retrieved_at': started, 'sha256': hasher.hexdigest(), 'uncompressed_sha256': expanded_hash.hexdigest(),
        'cache_declaration': 'Fresh local BRREG smoke snapshot, not organizer-supplied official registry'})
    return path, receipt, {'requests': 1, 'compressed_bytes': size, 'expanded_bytes': expanded,
                           'scope': 'Smoke input preparation outside the evaluator command'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--registry-receipt', type=Path)
    parser.add_argument('--cohort', choices=('development', 'validation'), default='development')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    if bool(args.registry) != bool(args.registry_receipt):
        raise ValueError('Both frozen snapshot and receipt are needed')
    preparation = {'requests': 0, 'scope': 'Caller-supplied declared local frozen snapshot'}
    if args.registry:
        registry, receipt = args.registry, args.registry_receipt
    else:
        registry, receipt, preparation = download_snapshot(args.output_dir)
    pool = ROOT / 'benchmarks/external-coverage'
    raw = (pool / (args.cohort + '.jsonl')).read_bytes()
    if digest(raw) != load(pool / 'manifest.json')[args.cohort + '_sha256']:
        raise ValueError('Representative input cohort changed')
    inputs = args.output_dir / 'input.jsonl'
    inputs.write_bytes(raw)
    cutoff = datetime.now(timezone.utc).isoformat()
    command = [sys.executable, '-X', 'dev', '-W', 'error', '-m', 'shirushi.official',
        '--organisations', str(inputs), '--registry', str(registry), '--registry-receipt', str(receipt),
        '--output', str(args.output_dir / 'envelopes.jsonl'), '--report', str(args.output_dir / 'report.json'),
        '--work-dir', str(args.output_dir / 'work'), '--run-id', 'pr4-frozen-' + args.cohort,
        '--showcase-dir', str(args.output_dir / 'site'), '--cutoff', cutoff]
    process = subprocess.run(command, cwd=ROOT, check=False, timeout=2800)
    report = load(args.output_dir / 'report.json')
    rows = internal_records(read_envelopes(args.output_dir / 'envelopes.jsonl'))
    families = {}
    fields = {}
    for row in rows:
        for claim in row['claims']:
            if claim['availability'] == 'available':
                fields[claim['field']] = fields.get(claim['field'], 0) + 1
                if claim.get('family'):
                    families.setdefault(claim['family'], set()).add(row['organisation_number'])
    detailed = load(args.output_dir / 'work/shard-0000/report.json')
    attempts = [a for c in detailed['companies'] for a in c['attempts']]
    failures = [a for a in attempts if a['status'] == 'failed']
    result = {'status': 'PASS' if process.returncode == 0 else 'FAIL',
        'input_count': report['input_count'], 'output_count': report['output_count'],
        'failed_companies': report['failed_companies'], 'shards': report['shards'],
        'source_failures': len(failures), 'source_failure_reasons': sorted(set(a.get('reason', '') for a in failures)),
        'entity_requests': sum(a['requests'] for a in attempts if a['source'] == 'brreg_entity'),
        'company_coverage_by_family': {f: len(s) for f, s in sorted(families.items())}, 'claims_by_field': fields,
        'resource_guard': report['resource_guard'], 'source_audit': 'PASS' if report['artifact_complete'] else 'FAIL',
        'observed_memory': report.get('observed_memory'),
        'snapshot_preparation': preparation, 'cutoff': cutoff,
        'registry_sha256': report['registry_sha256'], 'registry_receipt_sha256': report['registry_receipt_sha256'],
        'input_sha256': report['input_sha256'], 'output_sha256': report['output_sha256'],
        'code_sha256': detailed['code_sha256'], 'official_score': None, 'gold_recall': None,
        'independent_human_review': False, 'scope': 'Frozen representative cohort, real sources, public output adapter and automatic independent source support; not official scoring'}
    write_new(args.output_dir / 'validation.json', result)
    print(json.dumps(result, indent=2))
    return process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
