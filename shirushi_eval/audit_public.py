"""Independent retained-source audit in a deadline-supervised process."""
import argparse
import json
from pathlib import Path

from .support import SourceAudit
from .wire import internal_records, validate_public_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--store', type=Path, required=True)
    args = parser.parse_args()
    with args.input.open(encoding='utf-8') as handle:
        subjects = [json.loads(line)['organisation_number'] for line in handle if line.strip()]
    with args.output.open(encoding='utf-8') as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    errors = validate_public_contract(subjects, rows)
    if errors:
        raise ValueError('; '.join(errors))
    audit = SourceAudit(args.store, subjects)
    for row in internal_records(rows):
        evidence = {e['id']: e for e in row['evidence']}
        for claim in row['claims'] + row.get('history', []):
            audit.claim(row['organisation_number'], claim, evidence)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
