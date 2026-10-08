"""Source-subset coverage against retained accounts, never an official score.

References are enumerated without maker/checker imports. These are machine labels
from the same acquisition, not independently searched or human-adjudicated gold.
"""
import json

from .live_support import ACCOUNT_FIELDS, financial_context, financial_value
from .reference import strict_json


def key(subject, field, scope, period):
    return json.dumps([subject, field, scope, period], sort_keys=True, separators=(',', ':'))


def reference_accounts(raw, subject):
    body = strict_json(raw)
    if not isinstance(body, list) or len(body) > 200:
        raise ValueError('Invalid reference accounts list')
    expected, conflicts, invalid, invalid_amounts = {}, set(), 0, 0
    for record in body:
        try:
            scope, period = financial_context(record, subject)
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        for field, path in ACCOUNT_FIELDS.items():
            amount = record
            try:
                for part in path:
                    amount = amount[part]
            except (KeyError, TypeError):
                continue
            if amount is None:
                continue
            try:
                value = financial_value(amount, record, scope, period)
            except (ValueError, OverflowError):
                invalid_amounts += 1
                continue
            identity = key(subject, field, scope, period)
            if identity in expected and expected[identity] != value:
                conflicts.add(identity)
            expected[identity] = value
    for identity in conflicts:
        expected.pop(identity, None)
    return expected, {'invalid_records': invalid, 'conflicting_slots': len(conflicts), 'invalid_amounts': invalid_amounts}


def compare_accounts(envelopes, report, audit):
    expected, rejected, acquired = {}, {'invalid_records': 0, 'conflicting_slots': 0, 'invalid_amounts': 0}, set()
    for company in report['companies']:
        subject = company['envelope']['organisation_number']
        attempts = [a for a in company['attempts'] if a['source'] == 'brreg_accounts' and a['status'] == 'checked']
        if not attempts:
            continue  # An inaccessible source does not create a zero-opportunity label.
        if len(attempts) != 1:
            raise ValueError('Repeated accounts attempt in source-subset benchmark')
        receipt = strict_json(audit.read('receipts', attempts[0]['snapshot_id']))
        if (receipt['organisation_number'] != subject or receipt['source_class'] != 'brreg_accounts'
                or receipt['source_url'] != 'https://data.brreg.no/regnskapsregisteret/regnskap/' + subject
                or receipt.get('effective_url') != receipt['source_url'] or receipt['http_status'] != 200):
            raise ValueError('Reference source receipt mismatch')
        raw = audit.read('objects', receipt['content_sha256'])
        references, diagnostics = reference_accounts(raw, subject)
        expected.update(references)
        acquired.add(subject)
        for metric, count in diagnostics.items():
            rejected[metric] += count
    actual = {}
    for envelope in envelopes:
        for claim in envelope['claims']:
            if claim['availability'] == 'available' and claim['field'] in ACCOUNT_FIELDS:
                identity = key(envelope['organisation_number'], claim['field'], claim['scope'], claim['period'])
                if identity in actual:
                    raise ValueError('Duplicate published financial slot')
                actual[identity] = claim['value']
    correct = {k for k, value in actual.items() if expected.get(k) == value}
    unsupported = set(actual) - correct
    baseline = {k for k in correct if json.loads(k)[1] == 'annual_revenue'}
    positives = {json.loads(k)[0] for k in expected}

    def measures(found):
        covered = {json.loads(k)[0] for k in found}
        return {'matched_facts': len(found), 'covered_companies': len(covered),
                'fact_coverage': len(found) / len(expected) if expected else None,
                'company_coverage': len(covered) / len(positives) if positives else None}

    fields = {}
    for field in ACCOUNT_FIELDS:
        gold = {k for k in expected if json.loads(k)[1] == field}
        found = gold & correct
        fields[field] = {'reference_facts': len(gold), 'matched_facts': len(found),
                         'reference_companies': len({json.loads(k)[0] for k in gold}),
                         'covered_companies': len({json.loads(k)[0] for k in found})}
    return {'metric_priority': ['additional_covered_companies', 'additional_facts'],
            'promotion_scope': 'targeted financial completeness; broader external recall and official equivalence unmeasured',
            'scope': 'same retained accounts; independent machine enumeration; no human adjudication or official score',
            'control': 'revenue-only projection of the same audited output; not a second live execution',
            'acquired_source_companies': len(acquired), 'unacquired_source_companies': len(envelopes) - len(acquired),
            'reference_facts': len(expected), 'reference_positive_companies': len(positives),
            'baseline': measures(baseline), 'challenger': measures(correct),
            'additional_facts': len(correct - baseline),
            'additional_covered_companies': len({json.loads(k)[0] for k in correct} -
                                               {json.loads(k)[0] for k in baseline}),
            'missing_source_facts': len(set(expected) - correct), 'unsupported_publications': len(unsupported),
            'reference_diagnostics': rejected, 'fields': fields, 'additional_acquisition_requests': 0}
