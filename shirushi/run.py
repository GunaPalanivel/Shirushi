"""Run an offline supplied batch with saved-source evidence and a wall budget."""
import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import publish_new
from .batch import envelope, failure_decisions, run_supervised
from .contracts import ROOT, load, loads, validate_config, validate_envelopes, validate_inputs
from .snapshots import digest

MAX_INPUT_BYTES = 2 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_records(path):
    path = Path(path)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError('Input JSONL exceeds local bound')
    return [loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def write_new(path, value, jsonl=False):
    text = (''.join(json.dumps(item, ensure_ascii=False, allow_nan=False) + '\n' for item in value)
            if jsonl else json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
    publish_new(path, text.encode('utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('organisations', 'registry', 'registry-receipt', 'config', 'output', 'report'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--store', type=Path)
    parser.add_argument('--source-manifest', type=Path)
    args = parser.parse_args(argv)
    started, clock = utc_now(), time.monotonic()
    output, report_path = args.output.resolve(), args.report.resolve()
    inputs = [args.organisations, args.registry, args.registry_receipt, args.config]
    inputs += [p for p in (args.previous, args.source_manifest) if p]
    store_path = (args.store or output.parent / 'snapshots').resolve()
    forbidden = {p.resolve() for p in inputs}
    if (output == report_path or output in forbidden or report_path in forbidden
            or output.exists() or report_path.exists()
            or store_path in output.parents or store_path in report_path.parents):
        print('Refused: output/report must be distinct new files outside input and snapshot paths')
        return 2
    report = {'run_id': args.run_id, 'scope': 'offline_batch_pilot', 'official_score': None,
              'started_at': started, 'python': platform.python_version(), 'decisions': [], 'errors': []}
    try:
        if not args.run_id.strip():
            raise ValueError('run-id must be nonempty')
        records = read_records(args.organisations)
        errors, subjects = validate_inputs(records)
        if errors:
            raise ValueError('; '.join(errors))
        policy = load(ROOT / 'configs/source-policy.json')
        contract = load(ROOT / 'contracts/company-envelope.v1.json')
        config = load(args.config)
        errors = validate_config(config, policy)
        if errors:
            raise ValueError('; '.join(errors))
        if len(subjects) > config['sample_size']:
            raise ValueError('Input batch exceeds declared sample_size')
        if (config['mode'] != 'local' or config['network_enabled']
                or 'frozen_registry' not in config['enabled_sources']
                or set(config['enabled_sources']) - {'frozen_registry', 'brreg_roles_snapshot'}):
            raise ValueError('Only local offline registry and saved roles sources are implemented')
        sources = []
        if args.source_manifest:
            sources = load(args.source_manifest)
            if not isinstance(sources, list) or any(not isinstance(s, dict) for s in sources):
                raise ValueError('Source manifest must be a list of receipt objects')
            source_subjects = [s.get('organisation_number') for s in sources]
            if (any(s not in subjects for s in source_subjects)
                    or len(source_subjects) != len(set(source_subjects))):
                raise ValueError('Source manifest identities must be unique members of the input')
            if 'brreg_roles_snapshot' not in config['enabled_sources']:
                raise ValueError('Saved roles source not enabled in configuration')
            paths = [(args.source_manifest.parent / s['path']).resolve() for s in sources]
            if output in paths or report_path in paths:
                raise ValueError('Output/report cannot replace source bodies')
        previous = {}
        if args.previous:
            prior = read_records(args.previous)
            errors = validate_envelopes(records, prior, contract)
            if errors:
                raise ValueError('Previous envelope invalid: ' + '; '.join(errors))
            previous = {e['organisation_number']: e for e in prior}
            report['previous_sha256'] = digest(args.previous.read_bytes())
        report.update(input_sha256=digest(args.organisations.read_bytes()), config_sha256=digest(args.config.read_bytes()),
                      code_sha256=digest(b''.join(p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))))
        if args.source_manifest:
            report['source_manifest_sha256'] = digest(args.source_manifest.read_bytes())
        deadline = clock + config['wall_time_seconds'] * (1 - config['finalization_reserve_fraction'])
        job = {'subjects': subjects, 'registry': args.registry, 'registry_receipt': args.registry_receipt,
               'store': store_path, 'previous': previous, 'sources': sources, 'source_manifest': args.source_manifest,
               'max_response_bytes': config['max_response_bytes'], 'enabled_sources': config['enabled_sources'],
               'deadline': deadline, 'started_at': started, 'run_id': args.run_id}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report.update(status='rejected_input', completed_at=utc_now(), errors=[str(exc)])
        write_new(report_path, report)
        print(json.dumps({'status': report['status'], 'errors': report['errors']}))
        return 2
    try:
        envelopes, companies, supervision = run_supervised(job, contract)
    except Exception as exc:
        reason = 'Supervisor failure: ' + type(exc).__name__ + ': ' + str(exc)
        envelopes = [envelope(s, args.run_id, started, failure_decisions(None, reason), error=reason) for s in subjects]
        companies, supervision = [], {'worker_completed': False, 'unfinished_reason': reason}
    if supervision.get('invalid_previous'):
        report.update(status='rejected_input', errors=[supervision['unfinished_reason']], completed_at=utc_now())
        write_new(report_path, report)
        print(json.dumps({'status': report['status'], 'errors': report['errors']}))
        return 2
    errors = validate_envelopes(records, envelopes, contract)
    if errors:
        report.update(status='internal_validation_failed', completed_at=utc_now(), errors=errors)
        write_new(report_path, report)
        return 1
    failed = sum(e['run']['terminal_status'] == 'failed' for e in envelopes)
    report.update(status='failed' if failed else 'completed', completed_at=utc_now(), companies=companies,
                  supervision=supervision, input_count=len(subjects), output_count=len(envelopes), failed_companies=failed,
                  decisions=[d for c in companies for d in c['decisions']],
                  accepted=sum(d['accepted'] for c in companies for d in c['decisions']),
                  changes=sum(len(e['changes']) for e in envelopes), errors=[e for c in envelopes for e in c['errors']],
                  operations={'requests': 0, 'runtime_ms': int((time.monotonic() - clock) * 1000), 'third_party_cost_usd': 0},
                  acquisition_accounting='Saved sources are external caches; acquisition requests and times are declared in their receipts.',
                  artifact_complete=True)
    try:
        write_new(output, envelopes, jsonl=True)
        report['output_sha256'] = digest(output.read_bytes())
        # Report is the completion marker; an output without its matching report
        # is not an accepted artifact pair after interruption.
        write_new(report_path, report)
    except OSError as exc:
        print(json.dumps({'status': 'artifact_publication_failed', 'error': str(exc)}))
        return 1
    print(json.dumps({'status': report['status'], 'companies': len(envelopes), 'accepted': report['accepted'],
                      'changes': report['changes'], 'output': str(output), 'report': str(report_path)}))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
