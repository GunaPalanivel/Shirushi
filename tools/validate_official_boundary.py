"""Cold published-contract launch, growing membership, replay and source audit."""
import argparse
import csv
import gzip
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shirushi.contracts import load
from shirushi.run import read_envelopes, write_new
from shirushi.snapshots import digest
from shirushi_eval.support import SourceAudit
from shirushi_eval.wire import internal_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--counts', type=int, nargs='+', default=[100, 300, 1100])
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    subjects = [str(123450000 + i) for i in range(max(args.counts))]
    body = io.StringIO(newline='')
    columns = ['organisasjonsnummer', 'navn', 'organisasjonsform.kode', 'antallAnsatte']
    writer = csv.writer(body, delimiter=';')
    writer.writerow(columns)
    for i, subject in enumerate(subjects):
        writer.writerow([subject, 'Fixture ' + str(i) + ' AS', 'AS', 0 if i == 0 else ''])
    raw = body.getvalue().encode()
    archive = gzip.compress(raw, mtime=0)
    registry = args.output_dir / 'registry.csv.gz'
    registry.write_bytes(archive)
    receipt = args.output_dir / 'receipt.json'
    write_new(receipt, {'source_class': 'frozen_registry', 'dataset_format': 'csv',
        'source_url': 'https://example.org/synthetic-registry', 'retrieved_at': '2026-01-01T00:00:00Z',
        'sha256': digest(archive), 'uncompressed_sha256': digest(raw)})
    results = []
    for count in args.counts:
        folder = args.output_dir / str(count)
        folder.mkdir()
        inputs = folder / 'input.jsonl'
        write_new(inputs, [{'organisation_number': subject} for subject in subjects[:count]], jsonl=True)
        command = [sys.executable, '-X', 'dev', '-W', 'error', '-m', 'shirushi.official',
            '--organisations', str(inputs), '--registry', str(registry), '--registry-receipt', str(receipt),
            '--output', str(folder / 'output.jsonl'), '--report', str(folder / 'report.json'),
            '--work-dir', str(folder / 'work'), '--run-id', 'boundary-' + str(count), '--offline',
            '--cutoff', '2026-01-01T00:00:00Z']
        process = subprocess.run(command, cwd=ROOT, check=False, timeout=120)
        report = load(folder / 'report.json')
        rows = read_envelopes(folder / 'output.jsonl')
        audit = SourceAudit(folder / 'work/snapshots', subjects[:count])
        for row in internal_records(rows):
            evidence = {e['id']: e for e in row['evidence']}
            for claim in row['claims']:
                audit.claim(row['organisation_number'], claim, evidence)
        result = {'count': count, 'output_count': len(rows), 'shards': len(report['shards']),
            'membership_order_matches': [r['organisation_number'] for r in rows] == subjects[:count],
            'all_completed': all(r['run']['terminal_status'] == 'completed' for r in rows),
            'source_audit': 'PASS', 'operations': [r['operations'] for r in report['shards']],
            'guard': report['resource_guard'], 'output_sha256': report['output_sha256'],
            'exit_code': process.returncode}
        if process.returncode or not result['membership_order_matches'] or not result['all_completed']:
            raise ValueError('Cold contract fixture failed')
        if count == min(args.counts):
            replay = folder / 'replay'
            replay.mkdir()
            repeat = command.copy()
            for flag, value in [('--output', replay / 'output.jsonl'), ('--report', replay / 'report.json'),
                                ('--work-dir', replay / 'work')]:
                repeat[repeat.index(flag) + 1] = str(value)
            repeat += ['--previous', str(folder / 'output.jsonl'), '--store', str(folder / 'work/snapshots')]
            completed = subprocess.run(repeat, cwd=ROOT, check=False, timeout=120)
            rerun = read_envelopes(replay / 'output.jsonl')
            result['replay_value_changes'] = sum(len(r['changes']) for r in rerun)
            result['replay_history_count'] = sum(len(r['history']) for r in rerun)
            if completed.returncode or result['replay_value_changes'] or result['replay_history_count']:
                raise ValueError('Replay changed identical snapshot facts')
        results.append(result)
    summary = {'status': 'PASS', 'results': results, 'official_score': None,
               'scope': 'Synthetic cold contract, resource guard and growing membership. Not live recall or organizer scoring.'}
    write_new(args.output_dir / 'validation.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
