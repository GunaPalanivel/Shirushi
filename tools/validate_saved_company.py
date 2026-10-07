"""Read-only support verification and semantic replay check, without extraction."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shirushi.contracts import ROOT, load, validate_envelopes  # noqa: E402
from shirushi.evidence import EvidenceChecker  # noqa: E402
from shirushi.run import read_records  # noqa: E402
from shirushi.snapshots import SnapshotStore, digest  # noqa: E402


def semantic_claims(envelope):
    return [{k: v for k, v in c.items() if k not in
             ('last_observed_at', 'freshness', 'current_attempt_reason')}
            for c in envelope['claims']]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--organisations', type=Path, required=True)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--expect', choices=['replay', 'failed-refresh'], default='replay')
    args = parser.parse_args(argv)
    errors = []
    try:
        records = read_records(args.organisations)
        first, second = read_records(args.first), read_records(args.replay)
        contract = load(ROOT / 'contracts/company-envelope.v1.json')
        for label, envelopes in [('first', first), ('second', second)]:
            errors.extend(label + ': ' + e for e in validate_envelopes(records, envelopes, contract))
            for envelope in envelopes:
                EvidenceChecker(SnapshotStore(args.store)).verify_previous(envelope, envelope['organisation_number'])
        if errors:
            raise ValueError('; '.join(errors))
        for before, after in zip(first, second):
            if semantic_claims(before) != semantic_claims(after):
                errors.append('Semantic claims or first observation changed')
            if before['evidence'] != after['evidence'] or before.get('history', []) != after.get('history', []):
                errors.append('Evidence or history changed on unchanged replay')
            if after['changes']:
                errors.append('False material changes')
            expected = 'failed' if args.expect == 'failed-refresh' else 'completed'
            if after['run']['terminal_status'] != expected:
                errors.append('Unexpected terminal state')
            if args.expect == 'failed-refresh':
                if not after['errors'] or any(c.get('freshness') != 'stale_after_failed_observation'
                                              for c in after['claims'] if c['availability'] == 'available'):
                    errors.append('Failure or stale support not exposed')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    report = {'status': 'FAIL' if errors else 'PASS', 'scope': 'saved_support_and_semantic_replay',
              'expectation': args.expect, 'errors': errors, 'official_score': None,
              'independent_human_review': False}
    for label, path in [('first', args.first), ('second', args.replay)]:
        if path.is_file():
            report[label + '_sha256'] = digest(path.read_bytes())
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
