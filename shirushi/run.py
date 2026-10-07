"""Run the offline, one-company integration; no network access is performed."""
import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ROOT, load, loads, validate_config, validate_envelopes, validate_inputs
from .evidence import EvidenceChecker, SPECIFICATIONS
from .extraction import extract
from .refresh import merge
from .registry import acquire
from .snapshots import SnapshotStore, digest


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_records(path):
    return [loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def write_new(path, value, jsonl=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (''.join(json.dumps(item, ensure_ascii=False, allow_nan=False) + '\n' for item in value)
            if jsonl else json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('organisations', 'registry', 'registry-receipt', 'config', 'output', 'report'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--store', type=Path)
    args = parser.parse_args(argv)
    started, start_clock = utc_now(), time.monotonic()
    output, report_path = args.output.resolve(), args.report.resolve()
    input_paths = [args.organisations, args.registry, args.registry_receipt, args.config]
    if args.previous:
        input_paths.append(args.previous)
    store_path = (args.store or output.parent / 'snapshots').resolve()
    forbidden = {p.resolve() for p in input_paths}
    if (output == report_path or output in forbidden or report_path in forbidden
            or output.exists() or report_path.exists()
            or store_path in output.parents or store_path in report_path.parents):
        print('Refused: output/report must be distinct new files outside input and snapshot paths')
        return 2
    report = {'run_id': args.run_id, 'scope': 'offline_saved_company', 'official_score': None,
              'started_at': started, 'python': platform.python_version(), 'decisions': [], 'errors': []}
    try:
        if not args.run_id.strip():
            raise ValueError('run-id must be nonempty')
        records = read_records(args.organisations)
        errors, identities = validate_inputs(records)
        if errors:
            raise ValueError('; '.join(errors))
        if len(identities) != 1:
            raise ValueError('This integration accepts exactly one company; batch execution is a later milestone')
        subject = identities[0]
        policy, contract = load(ROOT / 'configs/source-policy.json'), load(ROOT / 'contracts/company-envelope.v1.json')
        config = load(args.config)
        errors = validate_config(config, policy)
        if errors:
            raise ValueError('; '.join(errors))
        if config['mode'] != 'local' or config['network_enabled'] or config['enabled_sources'] != ['frozen_registry']:
            raise ValueError('Only offline local frozen_registry configuration is implemented')
        report['input_sha256'] = digest(args.organisations.read_bytes())
        report['config_sha256'] = digest(args.config.read_bytes())
        report['code_sha256'] = digest(b''.join(p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py'))))
        store = SnapshotStore(store_path)
        checker = EvidenceChecker(store)
        previous = None
        if args.previous:
            prior = read_records(args.previous)
            errors = validate_envelopes(records, prior, contract)
            if errors:
                raise ValueError('Previous envelope invalid: ' + '; '.join(errors))
            previous = prior[0]
            checker.verify_previous(previous, subject)
            report['previous_sha256'] = digest(args.previous.read_bytes())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report.update(status='rejected_input', completed_at=utc_now(), errors=[str(exc)])
        write_new(report_path, report)
        print(json.dumps({'status': report['status'], 'errors': report['errors']}))
        return 2
    failure = None
    try:
        receipt = load(args.registry_receipt)
        report['registry_receipt_sha256'] = digest(args.registry_receipt.read_bytes())
        deadline = start_clock + config['wall_time_seconds'] * (1 - config['finalization_reserve_fraction'])
        snapshot_id = acquire(args.registry, receipt, subject, store, deadline)
        report['snapshot_id'] = snapshot_id
        report['registry_sha256'] = receipt['sha256']
        decisions = [checker.check(candidate, subject) for candidate in extract(store, snapshot_id)]
    except (ValueError, OSError, KeyError, TypeError, EOFError) as exc:
        failure = str(exc)
        decisions = [{'accepted': False, 'field': field, 'reason': 'source_failure: ' + failure}
                     for field in SPECIFICATIONS]
    rejected = [d for d in decisions if not d['accepted'] and d['reason'] != 'absent_in_frozen_row']
    if rejected and failure is None:
        failure = 'One or more candidate checks failed'
    report['decisions'] = decisions
    completed = utc_now()
    envelope = dict(merge(previous, decisions, started), organisation_number=subject,
                    run={'run_id': args.run_id, 'terminal_status': 'failed' if failure else 'completed',
                         'started_at': started, 'completed_at': completed},
                    errors=[{'stage': 'source_or_evidence', 'reason': failure}] if failure else [],
                    operations={'requests': 0, 'runtime_ms': int((time.monotonic() - start_clock) * 1000),
                                'third_party_cost_usd': 0})
    errors = validate_envelopes(records, [envelope], contract)
    if errors:
        report.update(status='internal_validation_failed', completed_at=completed, errors=errors)
        write_new(report_path, report)
        print(json.dumps({'status': report['status'], 'errors': errors}))
        return 1
    report.update(status=envelope['run']['terminal_status'], completed_at=completed,
                  accepted=sum(d['accepted'] for d in decisions), changes=len(envelope['changes']),
                  errors=envelope['errors'], operations=envelope['operations'])
    write_new(output, [envelope], jsonl=True)
    report['output_sha256'] = digest(output.read_bytes())
    write_new(report_path, report)
    print(json.dumps({'status': report['status'], 'accepted': report['accepted'], 'changes': report['changes'],
                      'output': str(output), 'report': str(report_path)}))
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
