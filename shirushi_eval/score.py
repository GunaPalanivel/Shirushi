"""Read-only pilot support/recall audit; never emits an official total score."""
import argparse
import json
import math
from pathlib import Path

from .reference import FAMILIES, sha, strict_json
from .support import SourceAudit, check_time


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def family_metric(positive_companies, covered_companies, checked_claims, matched_claims):
    if not positive_companies or not checked_claims:
        return {'status': 'not_measured', 'company_recall': None, 'claim_recall': None, 'mixture': None}
    if not (0 <= covered_companies <= positive_companies and 0 <= matched_claims <= checked_claims):
        raise ValueError('Recall numerators exceed checked denominators')
    company, claim = covered_companies / positive_companies, matched_claims / checked_claims
    return {'status': 'measured_source_subset', 'company_recall': company, 'claim_recall': claim,
            'mixture': 0.7 * company + 0.3 * claim}


def failure_stage(envelope, company_report, gold):
    if any('budget' in e.get('reason', '').lower() or 'deadline' in e.get('reason', '').lower()
           for e in envelope.get('errors', [])):
        return 'timing', 'deadline_or_budget_exhaustion'
    if any('absent from frozen registry' in e.get('reason', '').lower() for e in envelope.get('errors', [])):
        return 'identity', 'no_frozen_identity_anchor'
    routes = {'people': {'brreg_roles_snapshot', 'brreg_roles'},
              'financials_history': {'brreg_accounts_snapshot', 'brreg_accounts'},
              'business_products': {'company_owned', 'brreg_entity'},
              'operating_locations': {'brreg_subunits', 'company_owned'},
              'website_owned_profiles': {'company_owned', 'brreg_entity'},
              'jobs_dated_activity': {'company_owned', 'nav_jobs', 'announcements'}}
    if gold['family'] not in routes:
        return 'unclassified', 'unknown_family_route'
    sources = {gold['source_class']} if gold.get('source_class') else routes[gold['family']]
    attempts = [a for a in company_report.get('attempts', []) if a.get('source') in sources]
    if not attempts:
        return 'discovery', 'source_route_not_scheduled'
    if any(a['status'] == 'failed' for a in attempts):
        return 'access', 'source_attempt_failed'
    decisions = company_report.get('decisions', [])
    if any(d.get('accepted') and d.get('claim', {}).get('value') == gold['value'] for d in decisions):
        return 'output_loss', 'accepted_candidate_not_exported'
    relevant = [d for d in decisions if not d.get('accepted') and
                (d.get('family') == gold['family'] or d.get('field') == gold.get('field')
                 or (gold['family'] == 'people' and str(d.get('field', '')).startswith('registered_role:')))]
    if relevant:
        if any('subject' in d.get('reason', '').lower() for d in relevant):
            return 'identity', 'candidate_subject_rejected'
        return 'extraction', 'candidate_support_rejected'
    return 'extraction', 'checked_source_did_not_produce_expected_candidate'


def evaluate(subjects, envelopes, reference, report, store):
    if [e['organisation_number'] for e in envelopes] != subjects:
        raise ValueError('Evaluation output membership/order differs from input')
    if [r['organisation_number'] for r in reference] != subjects:
        raise ValueError('Reference membership/order differs from pilot')
    if report.get('artifact_complete') is not True or report.get('output_count') != len(subjects):
        raise ValueError('Missing complete batch artifact report')
    audit = SourceAudit(store, subjects)
    audited, missing, families, errors = 0, [], {}, []
    company_reports = {r['envelope']['organisation_number']: r for r in report.get('companies', [])}
    matched = set()
    for envelope, labels in zip(envelopes, reference):
        subject = envelope['organisation_number']
        if envelope['run']['terminal_status'] not in ('completed', 'failed'):
            raise ValueError('Unknown terminal state')
        if check_time(envelope['run']['completed_at']) < check_time(envelope['run']['started_at']):
            raise ValueError('Audit completion precedes start')
        evidence = {e['id']: e for e in envelope['evidence']}
        if len(evidence) != len(envelope['evidence']):
            errors.append('Duplicate evidence ID: ' + subject)
        verified = set()
        for claim in envelope['claims'] + envelope.get('history', []):
            try:
                audit.claim(subject, claim, evidence)
                if claim['availability'] == 'available':
                    audited += 1
                    verified.add(id(claim))
            except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                errors.append(subject + ': ' + str(exc))
        active = [c for c in envelope['claims'] if c['availability'] == 'available' and id(c) in verified]
        for gold in labels['claims']:
            if any(c.get('scope') == gold['scope'] and key(c['value']) == key(gold['value'])
                   and (not gold.get('field') or c['field'] == gold['field']) for c in active):
                matched.add(gold['canonical_id'])
            else:
                stage, reason = failure_stage(envelope, company_reports.get(subject, {}), gold)
                missing.append({'organisation_number': subject, 'family': gold['family'],
                                'canonical_id': gold['canonical_id'], 'stage': stage, 'reason': reason})
    for family in FAMILIES:
        gold = [(r['organisation_number'], g) for r in reference for g in r['claims'] if g['family'] == family]
        if len({g['canonical_id'] for _, g in gold}) != len(gold):
            raise ValueError('Duplicate reference canonical claim')
        positives = {s for s, _ in gold}
        covered = {s for s, g in gold if g['canonical_id'] in matched}
        facts = sum(g['canonical_id'] in matched for _, g in gold)
        families[family] = dict(family_metric(len(positives), len(covered), len(gold), facts),
                                positive_companies=len(positives), covered_companies=len(covered),
                                checked_claims=len(gold), matched_claims=facts,
                                unknown_opportunities=sum(r['opportunities'][family] == 'unknown' for r in reference))
    observations = [e['operations']['runtime_ms'] for e in envelopes]
    observations.sort()
    return {'status': 'FAIL' if errors else 'PASS', 'scope': 'development_source_subset_only', 'official_score': None,
            'independent_human_adjudication': False, 'input_count': len(subjects), 'output_count': len(envelopes),
            'audited_supported_claims_including_history': audited, 'unsupported_findings': len(errors), 'errors': errors,
            'failed_companies': sum(e['run']['terminal_status'] == 'failed' for e in envelopes),
            'families': families, 'missing_opportunities': missing,
            'failure_stage_counts': {stage: sum(m['stage'] == stage for m in missing) for stage in sorted({m['stage'] for m in missing})},
            'e1': {'checked_missing_claims': len(missing), 'classified_missing_claims': len(missing),
                   'classified_fraction': 1.0 if missing else None, 'status': 'measured_source_subset' if missing else 'not_measured'},
            'company_processing_ms': {'p50': observations[len(observations) // 2],
                                      'p95': observations[max(0, math.ceil(len(observations) * .95) - 1)],
                                      'scope': 'Post-index processing; batch wall time is separate.'},
            'batch_operations': report['operations'],
            'limitations': ['Source-scoped labels cover registered roles and entity annual revenue, not the full external reference union.',
                            'Other families remain unknown, not checked absent or scored zero.',
                            'No 80+ prediction, independent human audit, synthesis assessment or UX result.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('organisations', 'envelopes', 'report', 'reference', 'store', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        def records(path):
            return [strict_json(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        subjects = [r['organisation_number'] for r in records(args.organisations)]
        report = strict_json(args.report.read_bytes())
        if report.get('output_sha256') != sha(args.envelopes.read_bytes()):
            raise ValueError('Report does not bind these exact output bytes')
        result = evaluate(subjects, records(args.envelopes), records(args.reference), report, args.store)
        result['reference_pool_sha256'] = sha(args.reference.read_bytes())
        result['envelopes_sha256'] = sha(args.envelopes.read_bytes())
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        result = {'status': 'FAIL', 'errors': [str(exc)], 'official_score': None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'official_score')}))
    return 1 if result['status'] == 'FAIL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
