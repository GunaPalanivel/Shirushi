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
from shirushi_eval.wire import validate_public_contract

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
        records = body if isinstance(body, list) else body.get('organisation_numbers') if isinstance(body, dict) else None
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
    desired = 8_000_000_000
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    cap = desired if hard == resource.RLIM_INFINITY else min(desired, hard)
    supervisor_cap = min(2_000_000_000, cap)
    resource.setrlimit(resource.RLIMIT_AS, (supervisor_cap, cap))
    return {'cpu_affinity': sorted(os.sched_getaffinity(0)), 'supervisor_address_space_limit_bytes': supervisor_cap,
            'worker_address_space_limit_bytes': cap,
            'combined_process_address_space_ceiling_bytes': 3 * supervisor_cap + cap,
            'snapshot_store_limit_bytes': 8_000_000_000,
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
            prior_subjects = [e.get('organisation_number') if isinstance(e, dict) else None for e in prior]
            errors = validate_public_contract(prior_subjects, prior)
            if (not prior_subjects or len(set(prior_subjects)) != len(prior_subjects)
                    or any(s not in subjects for s in prior_subjects)):
                errors.append('Previous identities must be unique members of the supplied batch')
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
        if args.showcase_dir:
            site = args.showcase_dir.resolve()
            if store == site or store in site.parents or site in store.parents:
                raise ValueError('Snapshot store and public showcase cannot contain one another')
        guard = resource_guard()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected_input', 'error': str(exc)}))
        return 2
    args.work_dir.mkdir(parents=True)
    quota_roots = [str(p.resolve()) for p in (args.work_dir, args.output, args.report, args.showcase_dir) if p]
    os.environ.update(SHIRUSHI_ARTIFACT_ROOTS=json.dumps(quota_roots), SHIRUSHI_QUOTA_STORE=str(store),
                      SHIRUSHI_STORE_BYTE_LIMIT=str(guard['snapshot_store_limit_bytes']),
                      SHIRUSHI_WORKER_ADDRESS_SPACE_LIMIT=str(guard['worker_address_space_limit_bytes']))
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
            old = [prior_by_subject[r['organisation_number']] for r in batch if r['organisation_number'] in prior_by_subject]
            if old:
                write_new(folder / 'previous.jsonl', old, jsonl=True)
                command += ['--previous', str(folder / 'previous.jsonl'), '--allow-previous-subset']
        if args.discovery_access_receipt:
            command += ['--discovery-access-receipt', str(args.discovery_access_receipt.resolve())]
        # No aggregate wall cap is invented for an expanded batch. Each shard
        # receives the supplied 45 minutes; the harness can invoke shards in parallel.
        process = None
        try:
            process = subprocess.run(command, cwd=ROOT, env=environment, check=False,
                                     timeout=LIMITS['wall_time_seconds'])
            if process.returncode != 0:
                raise ValueError(f'Shard process exited with code {process.returncode}')
            report = load(folder / 'report.json')
            rows = read_envelopes(folder / 'envelopes.jsonl')
            if not report.get('artifact_complete') or digest((folder / 'envelopes.jsonl').read_bytes()) != report.get('output_sha256'):
                raise ValueError('Shard completion marker or output binding is invalid')
            supervision = report.get('supervision', {})
            if (report.get('status') != 'completed' or report.get('failed_companies') != 0
                    or report.get('errors') or supervision.get('worker_completed') is not True
                    or supervision.get('worker_exit_code') != 0
                    or report.get('input_count') != len(batch) or report.get('output_count') != len(rows)
                    or report.get('input_sha256') != digest((folder / 'input.jsonl').read_bytes())
                    or any(row['run']['terminal_status'] != 'completed' for row in rows)):
                raise ValueError('Shard process, supervision and completion report disagree')
            errors = validate_public_contract([r['organisation_number'] for r in batch], rows)
            if errors:
                raise ValueError('; '.join(errors))
            remaining = LIMITS['wall_time_seconds'] - (time.monotonic() - shard_clock)
            if remaining <= 0:
                raise ValueError('Shard deadline reached before independent audit')
            audit = subprocess.run([sys.executable, '-X', 'dev', '-W', 'error',
                '-m', 'shirushi_eval.audit_public', '--input', str(folder / 'input.jsonl'),
                '--output', str(folder / 'envelopes.jsonl'), '--store', str(store)],
                cwd=ROOT, env=environment, check=False, timeout=remaining)
            if audit.returncode:
                raise ValueError('Independent public source audit failed')
            ops = report['operations']
            if (ops.get('requests', 0) > LIMITS['request_budget'] or ops.get('third_party_cost_usd', 0) > 10
                    or ops['runtime_ms'] > 2_700_000 or time.monotonic() - shard_clock > 2700):
                raise ValueError('Shard exceeded organizer limits')
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            # An invalid/partial shard never becomes a completed aggregate. Its
            # supervisor normally emits failure terminals; a launcher failure is
            # explicit and retained for diagnosis rather than invented source data.
            write_new(args.report, {'status': 'failed', 'artifact_complete': False,
                'failed_shard': index, 'reason': str(exc), 'completed_shards': reports,
                'child_exit_code': process.returncode if process is not None else None,
                'shard_artifacts_directory': str(folder), 'official_score': None})
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
    import resource
    report['observed_memory'] = {'launcher_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'child_peak_rss_bytes': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
        'scope': 'Separate process high-water RSS, not simultaneous summed memory'}
    write_new(args.report, report)
    print(json.dumps({'status': report['status'], 'input_count': len(subjects), 'output_count': len(aggregate),
                      'shards': len(reports), 'official_score': None}))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
