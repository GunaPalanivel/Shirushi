"""Fresh public-company smoke run and separate retained-source support audit."""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shirushi.contracts import load, validate_envelopes
from shirushi.run import read_records
from shirushi.snapshots import digest
from shirushi_eval.support import SourceAudit
from shirushi_eval.financial_coverage import compare_accounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--page', type=int, default=0, help='Public discovery page; use 1 for a disjoint 100-company source validation')
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error('count must be between 1 and 100')
    if args.page < 0:
        parser.error('page must be nonnegative')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    # This is public cohort discovery, not a precomputed agent profile cache.
    url = ('https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS'
           '&sisteInnsendteAarsregnskap=2025&size=' + str(args.count) + '&page=' + str(args.page))
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept': 'application/json',
                                                                    'User-Agent': 'Shirushi/0.1'}), timeout=30) as response:
        raw = response.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError('Cohort response exceeds discovery bound')
    body = json.loads(raw)
    inputs = [{'organisation_number': r['organisasjonsnummer']} for r in body['_embedded']['enheter']]
    if len(inputs) != args.count:
        raise ValueError('Source returned fewer cohort companies than requested')
    directory = args.output_dir.resolve()
    (directory / 'input.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in inputs), encoding='utf-8')
    config = load(ROOT / 'configs/local-live.json')
    config.update(sample_size=args.count, enabled_sources=['brreg_entity', 'brreg_roles', 'brreg_accounts', 'brreg_subunits'])
    (directory / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    command = [sys.executable, '-X', 'dev', '-W', 'error', '-m', 'shirushi.run', '--live',
               '--organisations', str(directory / 'input.jsonl'), '--config', str(directory / 'config.json'),
               '--output', str(directory / 'envelopes.jsonl'), '--report', str(directory / 'report.json'),
               '--run-id', 'fresh-public-smoke', '--showcase-dir', str(directory / 'site')]
    run = subprocess.run(command, cwd=ROOT, timeout=config['wall_time_seconds'] + 30, check=False)
    envelopes, report = read_records(directory / 'envelopes.jsonl'), load(directory / 'report.json')
    errors = validate_envelopes(inputs, envelopes, load(ROOT / 'contracts/company-envelope.v1.json'))
    audit = SourceAudit(directory / 'snapshots', [r['organisation_number'] for r in inputs])
    counts, audited = {}, 0
    for envelope in envelopes:
        evidence = {e['id']: e for e in envelope['evidence']}
        for claim in envelope['claims']:
            audit.claim(envelope['organisation_number'], claim, evidence)
            if claim['availability'] == 'available':
                audited += 1
                counts[claim['field']] = counts.get(claim['field'], 0) + 1
    financial = compare_accounts(envelopes, report, audit)
    if financial['unsupported_publications'] or financial['missing_source_facts']:
        errors.append('Financial source-subset comparison failed')
    result = {'artifact_binding': {k: report[k] for k in ('input_sha256', 'config_sha256', 'code_sha256', 'output_sha256')},
              'status': 'PASS' if not errors and run.returncode == 0 and audited else 'FAIL',
              'input_count': len(inputs), 'output_count': len(envelopes), 'supported_claims_audited': audited,
              'financial_comparison': financial, 'claims_by_field': counts, 'operations': report['operations'], 'errors': errors,
              'cohort_discovery': {'requests': 1, 'source_url': url, 'content_sha256': digest(raw), 'page': args.page},
              'official_score': None, 'independent_human_review': False,
              'scope': 'fresh public AS companies with 2025 account metadata; source support, not full recall or representative sampling'}
    (directory / 'validation.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
