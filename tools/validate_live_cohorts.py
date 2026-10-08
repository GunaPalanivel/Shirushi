"""Require successful bound summaries on distinct public source-test cohorts."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shirushi.contracts import load
from shirushi.snapshots import digest


def validate(directories):
    observed, rows, code_hash = set(), [], None
    for directory in directories:
        directory = Path(directory)
        result = load(directory / 'validation.json')
        raw = (directory / 'input.jsonl').read_bytes()
        inputs = [json.loads(line)['organisation_number'] for line in raw.splitlines()]
        if (result['status'] != 'PASS' or result['input_count'] != len(inputs)
                or len(inputs) != len(set(inputs)) or result['output_count'] != len(inputs)
                or result['artifact_binding']['input_sha256'] != digest(raw)
                or result['artifact_binding']['config_sha256'] != digest((directory / 'config.json').read_bytes())):
            raise ValueError('Invalid source-validation summary or manifest binding')
        current_code = result['artifact_binding']['code_sha256']
        if code_hash is not None and current_code != code_hash:
            raise ValueError('Source-validation cohorts used different maker code')
        code_hash = current_code
        if observed.intersection(inputs):
            raise ValueError('Public source-validation cohorts overlap')
        observed.update(inputs)
        comparison = result['financial_comparison']
        if (comparison['missing_source_facts'] or comparison['unsupported_publications']
                or comparison['additional_facts'] <= 0 or comparison['reference_diagnostics']['invalid_records']
                or comparison['reference_diagnostics']['conflicting_slots']
                or comparison['reference_diagnostics']['invalid_amounts']):
            raise ValueError('Financial challenger did not pass source-subset promotion checks')
        rows.append({'companies': len(inputs), 'comparison': comparison})
    print(json.dumps({'status': 'PASS', 'distinct_companies': len(observed), 'cohorts': rows,
                      'scope': 'public retained-source validation only; not six-family gold or official recall'}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: validate_live_cohorts.py SMOKE_DIRECTORY VALIDATION_DIRECTORY')
    validate(sys.argv[1:])
