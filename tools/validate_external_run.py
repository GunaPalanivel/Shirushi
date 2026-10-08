"""Frozen external-source execution audit; never claims gold recall without labels."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shirushi.contracts import load, validate_envelopes
from shirushi.run import read_envelopes, read_records
from shirushi.snapshots import digest
from shirushi_eval.support import SourceAudit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', choices=['development', 'validation'], required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    pool = ROOT / 'benchmarks/external-coverage'
    manifest = load(pool / 'manifest.json')
    raw = (pool / (args.cohort + '.jsonl')).read_bytes()
    if digest(raw) != manifest[args.cohort + '_sha256']:
        raise ValueError('Frozen cohort hash mismatch')
    inputs = read_records(pool / (args.cohort + '.jsonl'))
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'input.jsonl').write_bytes(raw)
    config = load(ROOT / 'configs/local-live.json')
    config.update(enabled_sources=['brreg_entity', 'company_owned'], request_budget=1000,
                  wall_time_seconds=1200, sample_size=len(inputs), routing_policy='fixed')
    (directory / 'config.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    command = [sys.executable, '-X', 'dev', '-W', 'error', '-m', 'shirushi.run', '--live',
        '--organisations', str(directory / 'input.jsonl'), '--config', str(directory / 'config.json'),
        '--output', str(directory / 'envelopes.jsonl'), '--report', str(directory / 'report.json'),
        '--run-id', 'external-' + args.cohort]
    process = subprocess.run(command, cwd=ROOT, check=False, timeout=1230)
    rows = read_envelopes(directory / 'envelopes.jsonl')
    report = load(directory / 'report.json')
    errors = validate_envelopes(inputs, rows, load(ROOT / 'contracts/company-envelope.v1.json'))
    audit = SourceAudit(directory / 'snapshots', [i['organisation_number'] for i in inputs])
    families = {f: set() for f in ['business_products', 'website_owned_profiles', 'jobs_dated_activity']}
    fields, unsupported, external_count = {}, [], 0
    for row in rows:
        evidence = {e['id']: e for e in row['evidence']}
        for claim in row['claims']:
            try:
                audit.claim(row['organisation_number'], claim, evidence)
            except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                unsupported.append({'organisation_number': row['organisation_number'], 'reason': str(exc)})
                continue
            if claim['availability'] != 'available' or claim['scope'] not in ('company_owned_html', 'company_owned_structured'):
                continue
            external_count += 1
            fields[claim['field']] = fields.get(claim['field'], 0) + 1
            if claim['family'] in families:
                families[claim['family']].add(row['organisation_number'])
    attempts = [a for company in report['companies'] for a in company['attempts'] if a['source'] == 'company_owned']
    failure_reasons = {}
    for attempt in attempts:
        if attempt['status'] == 'failed':
            key = attempt.get('availability', 'failed') + ': ' + attempt.get('reason', 'Unknown source failure')
            failure_reasons[key] = failure_reasons.get(key, 0) + 1
    result = {'status': 'PASS' if process.returncode == 0 and not errors and not unsupported else 'FAIL',
        'cohort': args.cohort, 'input_count': len(inputs), 'output_count': len(rows),
        'failed_companies': report['failed_companies'], 'run_errors': report['errors'],
        'failed_identity_attempts': [{'organisation_number': c['envelope']['organisation_number'],
            'reason': a.get('reason'), 'availability': a.get('availability')}
            for c in report['companies'] for a in c['attempts'] if a['source'] == 'brreg_entity' and a['status'] == 'failed'],
        'company_coverage_by_family': {f: len(values) for f, values in families.items()},
        'supported_external_facts': external_count, 'claims_by_field': fields,
        'source_attempts': len(attempts), 'source_failures': sum(a['status'] == 'failed' for a in attempts),
        'funnel': {key: sum(a.get('funnel', {}).get(key, 0) for a in attempts) for key in
            ['candidate_domains', 'candidate_pages_retrieved', 'candidate_identity_rejections', 'verified_website', 'supported_facts']},
        'failure_reasons': failure_reasons,
        'unsupported_publications': unsupported, 'operations': report['operations'], 'errors': errors,
        'artifact_binding': {k: report[k] for k in ['input_sha256', 'config_sha256', 'code_sha256', 'output_sha256']},
        'checker_sha256': digest(b''.join(p.name.encode() + p.read_bytes() for p in sorted((ROOT / 'shirushi_eval').glob('*.py')))),
        'paired_gain': None, 'independent_gold_labels_available': False, 'independent_human_review': False,
        'official_score': None, 'merge_gate': 'NOT_ESTABLISHED',
        'scope': 'Frozen representative cohort execution and independent retained-source support; not paired recall or official scoring'}
    (directory / 'validation.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
