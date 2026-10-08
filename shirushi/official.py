"""One evaluator command for a supplied, growing batch under organizer shard limits.

Implements the published minimal contract. Only Builderr can award an official
score or confirm the private harness wire variant. No personal API keys required.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .contracts import ROOT, load, loads, timestamp, validate_inputs
from .registry import check_receipt
from .run import MAX_INPUT_BYTES, MAX_STATE_BYTES, read_envelopes, write_new
from .snapshots import digest
from shirushi_eval.wire import internal_records, validate_public_contract
from shirushi_eval.support import SourceAudit

SHARD_SIZE = 100
LIMITS = {'wall_time_seconds': 2700, 'request_budget': 2000,
          'third_party_cost_usd': 10, 'cpu_limit': 8, 'memory_limit_bytes': 16_000_000_000,
          'disk_limit_bytes': 10_000_000_000}


def read_inputs(path):
    with Path(path).open('rb') as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('Supplied identity input exceeds 2 MiB')
    text = raw.decode('utf-8')
    if Path(path).suffix == '.json':
        body = loads(text)
        records = body if isinstance(body, list) else body.get('organisation_numbers')
    elif Path(path).suffix == '.jsonl':
        records = [loads(line) for line in text.splitlines() if line.strip()]
    else:
        records = [line.strip() for line in text.splitlines() if line.strip()]
    if not isinstance(records, list):
        raise ValueError('Identity input must contain a list')
    records = [{'organisation_number': r} if isinstance(r, str) else r for r in records]
    errors, subjects = validate_inputs(records)
    if errors:
        raise ValueError('; '.join(errors))
    return records, subjects


def shards(records):
    return [records[i:i + SHARD_SIZE] for i in range(0, len(records), SHARD_SIZE)]


def resource_guard():
    if sys.platform != 'linux':
        raise ValueError('Evaluator resource guard requires Linux; local runner supports other platforms')
    import resource
    available = sorted(os.sched_getaffinity(0))
    os.sched_setaffinity(0, available[:LIMITS['cpu_limit']])
    # Stay below either decimal or binary interpretation of the supplied cap.
    desired = 15_000_000_000
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    cap = desired if hard == resource.RLIM_INFINITY else min(desired, hard)
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    return {'cpu_affinity': sorted(os.sched_getaffinity(0)), 'address_space_limit_bytes': cap,
            'snapshot_store_limit_bytes': 9_000_000_000,
            'enforcement': 'Linux affinity, inherited RLIMIT_AS, bounded snapshot writes and supervised shard deadline'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('organisations', 'registry', 'registry-receipt', 'output', 'report', 'work-dir'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--cutoff', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--store', type=Path)
    parser.add_argument('--showcase-dir', type=Path)
    parser.add_argument('--offline', action='store_true', help='Snapshot-only contract exercise, not a live score run')
    parser.add_argument('--discovery-access-receipt', type=Path)
    args = parser.parse_args(argv)
    clock = time.monotonic()
    try:
        if not args.run_id.strip():
            raise ValueError('run-id must be nonempty')
        from datetime import datetime, timezone
        if timestamp(args.cutoff) > datetime.now(timezone.utc):
            raise ValueError('Cutoff cannot be in the future')
        records, subjects = read_inputs(args.organisations)
        receipt = load(args.registry_receipt)
        check_receipt(receipt)
        if not args.registry.is_file():
            raise ValueError('Supplied registry is missing')
        prior = read_envelopes(args.previous) if args.previous else None
        if prior is not None:
            errors = validate_public_contract(subjects, prior)
            if errors:
                raise ValueError('Previous public output: ' + '; '.join(errors))
        paths = [args.output.resolve(), args.report.resolve(), args.work_dir.resolve()]
        inputs = [p.resolve() for p in (args.organisations, args.registry, args.registry_receipt, args.previous) if p]
        if len(set(paths)) != 3 or any(p.exists() or p in inputs for p in paths):
            raise ValueError('Output, report and work directory must be distinct new paths')
        if any(a in b.parents or b in a.parents for i, a in enumerate(paths) for b in paths[i + 1:]):
            raise ValueError('Output, report and work directory cannot contain one another')
        if args.showcase_dir:
            site = args.showcase_dir.resolve()
            if site.exists() or site in inputs + paths or any(site in p.parents or p in site.parents for p in inputs + paths):
                raise ValueError('Showcase directory must be new and outside other artifact paths')
        store = (args.store or args.work_dir / 'snapshots').resolve()
        if store in inputs + paths or (store.exists() and not store.is_dir()) or any(store in p.parents for p in paths[:2] + inputs):
            raise ValueError('Snapshot store cannot replace or contain input/output files')
        guard = resource_guard()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected_input', 'error': str(exc)}))
        return 2
    args.work_dir.mkdir(parents=True)
    quota_roots = [str(p.resolve()) for p in (args.work_dir, args.output, args.report, args.showcase_dir) if p]
    os.environ.update(SHIRUSHI_ARTIFACT_ROOTS=json.dumps(quota_roots), SHIRUSHI_QUOTA_STORE=str(store),
                      SHIRUSHI_STORE_BYTE_LIMIT='9000000000')
    environment = dict(os.environ)
    prior_by_subject = {e['organisation_number']: e for e in prior or []}
    aggregate, reports = [], []
    for index, batch in enumerate(shards(records)):
        shard_clock = time.monotonic()
        folder = args.work_dir / f'shard-{index:04d}'
        folder.mkdir()
        config = load(ROOT / 'configs/shard-validation.json')
        config.update(sample_size=len(batch), enabled_sources=['frozen_registry', 'brreg_roles',
            'brreg_accounts', 'brreg_subunits', 'nav_jobs', 'company_owned'],
            settings_origin='Soham organizer email 2026-10-08, docs/organizer-run-limits.json; published-contract candidate')
        if args.offline:
            config.update(network_enabled=False, enabled_sources=['frozen_registry'])
        write_new(folder / 'input.jsonl', batch, jsonl=True)
        write_new(folder / 'config.json', config)
        command = [sys.executable, '-X', 'dev', '-W', 'error', '-m', 'shirushi.run',
            '--organisations', str(folder / 'input.jsonl'), '--config', str(folder / 'config.json'),
            '--registry', str(args.registry.resolve()), '--registry-receipt', str(args.registry_receipt.resolve()),
            '--output', str(folder / 'envelopes.jsonl'), '--report', str(folder / 'report.json'),
            '--run-id', args.run_id + f'-{index:04d}', '--store', str(store),
            '--cutoff', args.cutoff, '--output-contract', 'builderr-minimal-v1']
        if not args.offline:
            command.append('--live')
        if args.previous:
            write_new(folder / 'previous.jsonl', [prior_by_subject[r['organisation_number']] for r in batch], jsonl=True)
            command += ['--previous', str(folder / 'previous.jsonl')]
        if args.discovery_access_receipt:
            command += ['--discovery-access-receipt', str(args.discovery_access_receipt.resolve())]
        # No aggregate wall cap is invented for an expanded batch. Each shard
        # receives the supplied 45 minutes; the harness can invoke shards in parallel.
        try:
            process = subprocess.run(command, cwd=ROOT, env=environment, check=False,
                                     timeout=LIMITS['wall_time_seconds'])
            report = load(folder / 'report.json')
            rows = read_envelopes(folder / 'envelopes.jsonl')
            if not report.get('artifact_complete') or digest((folder / 'envelopes.jsonl').read_bytes()) != report.get('output_sha256'):
                raise ValueError('Shard completion marker or output binding is invalid')
            errors = validate_public_contract([r['organisation_number'] for r in batch], rows)
            if errors:
                raise ValueError('; '.join(errors))
            audit = SourceAudit(store, [r['organisation_number'] for r in batch])
            for row in internal_records(rows):
                evidence = {e['id']: e for e in row['evidence']}
                for claim in row['claims'] + row.get('history', []):
                    audit.claim(row['organisation_number'], claim, evidence)
            ops = report['operations']
            if (ops.get('requests', 0) > LIMITS['request_budget'] or ops.get('third_party_cost_usd', 0) > 10
                    or ops['runtime_ms'] > 2_700_000 or time.monotonic() - shard_clock > 2700):
                raise ValueError('Shard exceeded organizer limits')
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            # An invalid/partial shard never becomes a completed aggregate. Its
            # supervisor normally emits failure terminals; a launcher failure is
            # explicit and retained for diagnosis rather than invented source data.
            write_new(args.report, {'status': 'failed', 'artifact_complete': False,
                'failed_shard': index, 'reason': str(exc), 'completed_shards': reports, 'official_score': None})
            print(json.dumps({'status': 'failed', 'shard': index, 'reason': str(exc)}))
            return 1
        aggregate.extend(rows)
        if len(json.dumps(aggregate, ensure_ascii=False).encode()) > MAX_STATE_BYTES:
            write_new(args.report, {'status': 'failed', 'artifact_complete': False,
                'reason': 'Aggregate output exceeds 128 MiB bound', 'official_score': None})
            return 1
        reports.append({'index': index, 'count': len(batch), 'status': report['status'],
            'exit_code': process.returncode, 'input_sha256': report['input_sha256'],
            'output_sha256': report['output_sha256'], 'operations': ops,
            'failed_companies': report['failed_companies']})
        reports[-1]['launcher_and_audit_runtime_ms'] = int((time.monotonic() - shard_clock) * 1000)
    errors = validate_public_contract(subjects, aggregate)
    if errors:
        raise ValueError('; '.join(errors))
    if args.showcase_dir:
        from .showcase import render
        from .wire import convert
        render(convert(aggregate, external=False), args.showcase_dir)
    write_new(args.output, aggregate, jsonl=True)
    failed = sum(r['failed_companies'] for r in reports)
    report = {'status': 'failed' if failed else 'completed', 'artifact_complete': True,
        'input_count': len(subjects), 'output_count': len(aggregate), 'failed_companies': failed,
        'shards': reports, 'limits_per_shard': LIMITS, 'resource_guard': guard,
        'input_sha256': digest(args.organisations.read_bytes()), 'registry_sha256': receipt['sha256'],
        'registry_receipt_sha256': digest(args.registry_receipt.read_bytes()),
        'output_sha256': digest(args.output.read_bytes()), 'cutoff': args.cutoff,
        'runtime_ms': int((time.monotonic() - clock) * 1000), 'official_score': None,
        'scope': 'offline_public_contract_exercise' if args.offline else 'live_published_contract_candidate',
        'private_harness_confirmed': False}
    write_new(args.report, report)
    print(json.dumps({'status': report['status'], 'input_count': len(subjects), 'output_count': len(aggregate),
                      'shards': len(reports), 'official_score': None}))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
