"""Local synthetic stress, not live throughput or an official scale prediction."""
import argparse
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shirushi.contracts import load, validate_envelopes
from shirushi.live import worker
from shirushi.run import MAX_INPUT_BYTES, MAX_STATE_BYTES, read_envelopes, read_records


def run(count, directory):
    directory.mkdir(parents=True, exist_ok=False)
    config = load(ROOT / 'configs/local-live.json')
    config.update(sample_size=count, enabled_sources=['brreg_entity'], request_budget=count,
                  min_host_interval_seconds=0, per_host_concurrency=4)
    inputs = [{'organisation_number': str(900000000 + i)} for i in range(count)]
    caller, rows, totals, frames = threading.get_ident(), [], [], 0
    class Connection:
        def send(self, frame):
            nonlocal frames
            if threading.get_ident() != caller:
                raise AssertionError('Concurrent event publisher')
            frames += 1
            if frame[0] == 'fatal':
                raise AssertionError(frame[2])
            if frame[0] == 'result':
                rows.append(frame[2]['envelope'])
            if frame[0] == 'accounting':
                totals.append(frame[2])
        def close(self):
            pass
    def get(fetcher, url, hosts, robots=False):
        with fetcher.budget.request('data.brreg.no'):
            raw = json.dumps({'organisasjonsnummer': url.rsplit('/', 1)[1], 'navn': 'Synthetic scale AS',
                              '_links': {'self': {'href': url}}}).encode()
            fetcher.budget.consume(len(raw))
            return raw, {'source_url': url, 'effective_url': url, 'http_status': 200,
                'retrieved_at': '2026-10-08T08:00:00Z', 'source_origin': 'data.brreg.no', 'content_type': 'application/json'}
    start = time.monotonic()
    with patch('shirushi.fetch.Fetcher.get', get):
        worker(Connection(), {'subjects': [r['organisation_number'] for r in inputs], 'previous': {},
            'store': directory / 'snapshots', 'config': config, 'deadline': start + 120,
            'run_id': 'synthetic-scale', 'started_at': '2026-10-08T08:00:00Z'})
    errors = validate_envelopes(inputs, rows, load(ROOT / 'contracts/company-envelope.v1.json'))
    path = directory / 'envelopes.jsonl'
    # Real envelope shapes, enlarged evidence spans to exercise the state reader.
    # Padding is only for size stress and is never presented as source evidence.
    padding = 'x' * 60000
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            row['state_reader_stress_padding'] = padding
            stream.write(json.dumps(row) + '\n')
    read = read_envelopes(path)
    if [r['organisation_number'] for r in read] != [r['organisation_number'] for r in inputs]:
        errors.append('Retained state membership/order mismatch')
    if count >= 100 and path.stat().st_size <= MAX_INPUT_BYTES:
        errors.append('State stress did not exceed identity input bound')
    try:
        read_records(path)
    except ValueError:
        pass
    else:
        errors.append('Identity input bound was relaxed')
    if totals[-1]['requests'] != count or any(r['run']['terminal_status'] != 'completed' for r in rows):
        errors.append('Budget/output integrity mismatch')
    result = {'status': 'FAIL' if errors else 'PASS', 'input_count': count, 'output_count': len(rows),
        'state_bytes': path.stat().st_size, 'declared_state_bound': MAX_STATE_BYTES,
        'operations': totals[-1], 'frames': frames, 'runtime_ms': int((time.monotonic() - start) * 1000),
        'scope': 'Synthetic I/O and state reader stress; no live throughput or official compatibility claim',
        'official_score': None, 'errors': errors}
    (directory / 'validation.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    results = [run(count, args.output_dir / str(count)) for count in (100, 300, 1500)]
    print(json.dumps(results, indent=2))
    return int(any(r['status'] != 'PASS' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
