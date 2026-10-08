"""Live regression for the observed no-hint legal-seller/catalogue failure."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shirushi.contracts import load, validate_envelopes
from shirushi.run import read_envelopes
from shirushi_eval.support import SourceAudit


def main():
    directory = ROOT / 'out/website-opportunity'
    directory.mkdir(parents=True, exist_ok=False)
    inputs = [{'organisation_number': '915463568'}]
    (directory / 'input.jsonl').write_text(json.dumps(inputs[0]) + '\n')
    config = load(ROOT / 'configs/local-external.json')
    config.update(enabled_sources=['brreg_entity', 'company_owned'], sample_size=1,
                  wall_time_seconds=180, request_budget=50)
    (directory / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    process = subprocess.run([sys.executable, '-X', 'dev', '-W', 'error', '-m', 'shirushi.run', '--live',
        '--organisations', str(directory / 'input.jsonl'), '--config', str(directory / 'config.json'),
        '--output', str(directory / 'envelopes.jsonl'), '--report', str(directory / 'report.json'),
        '--run-id', 'website-opportunity', '--discovery-access-receipt',
        str(ROOT / 'configs/anysearch-anonymous.json')], cwd=ROOT, check=False, timeout=210)
    rows = read_envelopes(directory / 'envelopes.jsonl')
    report = load(directory / 'report.json')
    errors = validate_envelopes(inputs, rows, load(ROOT / 'contracts/company-envelope.v1.json'))
    audit = SourceAudit(directory / 'snapshots', ['915463568'])
    counts = {}
    for row in rows:
        evidence = {e['id']: e for e in row['evidence']}
        for claim in row['claims']:
            try:
                audit.claim(row['organisation_number'], claim, evidence)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                errors.append(str(exc)); continue
            if claim['availability'] == 'available':
                counts[claim['field']] = counts.get(claim['field'], 0) + 1
    passed = not errors and not process.returncode and counts.get('verified_website', 0) > 0 and counts.get('product_service', 0) > 0
    result = {'status': 'PASS' if passed else 'FAIL', 'claims_by_field': counts,
        'verified_website_companies': int(counts.get('verified_website', 0) > 0),
        'verified_product_companies': int(counts.get('product_service', 0) > 0),
        'operations': report['operations'], 'errors': errors, 'attempts': report['companies'],
        'artifact_binding': {k: report[k] for k in ('input_sha256', 'config_sha256', 'code_sha256', 'output_sha256')},
        'scope': 'Known real no-hint discovery regression, not an unseen coverage estimate', 'official_score': None}
    # Summaries include dispositions and source hashes, not complete page bytes.
    result['attempts'] = [a for c in report['companies'] for a in c['attempts']]
    (directory / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
