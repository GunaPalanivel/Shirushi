"""Equal-budget live comparison on frozen NAV-positive source opportunities."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shirushi.contracts import load, validate_envelopes
from shirushi.run import read_envelopes
from shirushi_eval.paired_coverage import holm, paired
from shirushi_eval.support import SourceAudit

FAMILIES = ('business_products', 'jobs_dated_activity')


def run(root, directory, inputs, challenger):
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / 'input.jsonl'
    source.write_text(''.join(json.dumps({'organisation_number': r['organisation_number']}) + '\n' for r in inputs))
    config = load(ROOT / 'configs/local-external.json')
    config.update(sample_size=len(inputs))
    if not challenger:
        config['enabled_sources'] = ['brreg_entity', 'company_owned']
    path = directory / 'config.json'
    path.write_text(json.dumps(config, indent=2) + '\n')
    command = [sys.executable, '-X', 'dev', '-W', 'error', '-m', 'shirushi.run', '--live', '--organisations',
        str(source), '--config', str(path), '--output', str(directory / 'envelopes.jsonl'), '--report',
        str(directory / 'report.json'), '--run-id', 'paired-' + directory.name]
    if challenger:
        command += ['--discovery-access-receipt', str(ROOT / 'configs/anysearch-anonymous.json')]
    process = subprocess.run(command, cwd=root, check=False, timeout=config['wall_time_seconds'] + 30)
    rows = read_envelopes(directory / 'envelopes.jsonl')
    report = load(directory / 'report.json')
    errors = validate_envelopes([{'organisation_number': r['organisation_number']} for r in inputs], rows,
                                load(ROOT / 'contracts/company-envelope.v1.json'))
    audit = SourceAudit(directory / 'snapshots', [r['organisation_number'] for r in inputs])
    outcomes = {f: {r['organisation_number']: False for r in inputs} for f in FAMILIES}
    counts = {f: 0 for f in FAMILIES}
    for row in rows:
        evidence = {e['id']: e for e in row['evidence']}
        for claim in row['claims']:
            try:
                audit.claim(row['organisation_number'], claim, evidence)
            except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
                errors.append(str(exc)); continue
            if (claim['availability'] == 'available' and claim.get('family') in outcomes
                    and claim['field'] not in ('registered_activity', 'declared_website')):
                outcomes[claim['family']][row['organisation_number']] = True
                counts[claim['family']] += 1
    if process.returncode or report['failed_companies'] or report['errors']:
        errors.append('Incomplete or failed live batch')
    return outcomes, {'operations': report['operations'], 'facts': counts, 'errors': errors,
        'run_errors': report['errors'], 'failed_companies': report['failed_companies'],
        'supervision': {k: report.get('supervision', {}).get(k) for k in
                        ('worker_completed', 'worker_exit_code', 'unfinished_reason')},
        'output_count': len(rows), 'input_count': len(inputs),
        'artifact_binding': {k: report[k] for k in ('input_sha256', 'config_sha256', 'code_sha256', 'output_sha256')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--cohort', choices=['development', 'validation'], required=True)
    args = parser.parse_args()
    pool = ROOT / 'benchmarks/nav-opportunities'
    manifest = load(pool / 'manifest.json')
    data = (pool / (args.cohort + '.json')).read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest[args.cohort + '_sha256']:
        raise ValueError('Frozen positive-source cohort changed')
    inputs = json.loads(data)
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    control, a = run(args.baseline_root.resolve(), directory / 'control', inputs, False)
    challenger, b = run(ROOT, directory / 'challenger', inputs, True)
    comparisons = {}
    for family in FAMILIES:
        positives = {r['organisation_number'] for r in inputs if family in r['positive_families']}
        comparisons[family] = paired({s: control[family][s] for s in positives},
                                     {s: challenger[family][s] for s in positives})
    adjusted = holm({f: v['exact_two_sided_mcnemar_p'] for f, v in comparisons.items()})
    passed = (not a['errors'] and not b['errors'] and all(
        v['net_additional_companies'] > 0 and adjusted[f] <= .05 for f, v in comparisons.items()))
    result = {'status': 'PASS' if passed else 'FAIL', 'cohort': args.cohort,
        'comparison': comparisons, 'holm_adjusted_p': adjusted, 'control': a, 'challenger': b,
        'reference_sha256': hashlib.sha256(data).hexdigest(), 'baseline_commit': manifest['baseline_commit'],
        'checker_sha256': hashlib.sha256(b''.join(p.name.encode() + p.read_bytes()
            for p in sorted((ROOT / 'shirushi_eval').glob('*.py')))).hexdigest(),
        'source_examples_inspected_during_development': manifest['source_examples_inspected_during_development'],
        'official_score': None, 'independent_human_review': False,
        'scope': 'Frozen eligible NAV-positive source subset, independently audited live coverage; not universe recall or official points'}
    (directory / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
