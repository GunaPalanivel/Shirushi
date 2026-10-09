"""Independent public example checks, not a claim about the private harness."""
from copy import deepcopy


def internal_records(envelopes):
    result = deepcopy(envelopes)
    for envelope in result:
        for key in ('claims', 'history', 'changes'):
            for record in envelope.get(key, []):
                if record.get('field') == 'official_website':
                    record['field'] = 'verified_website'
    return result


def validate_public_contract(subjects, envelopes):
    errors = []
    if not isinstance(envelopes, list) or any(not isinstance(e, dict) for e in envelopes):
        return ['Public output must be a list of envelope objects']
    if [e.get('organisation_number') for e in envelopes] != subjects:
        errors.append('Public output differs from supplied ordered membership')
    states = {'available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed'}
    for envelope in envelopes:
        if not {'organisation_number', 'run', 'claims', 'evidence', 'changes', 'errors', 'operations'} <= envelope.keys():
            errors.append('Missing public example fields')
            continue
        if (not isinstance(envelope['claims'], list) or any(not isinstance(c, dict) or not
                {'field', 'value', 'availability', 'evidence_ids'} <= c.keys() for c in envelope['claims'])
                or not isinstance(envelope['evidence'], list) or any(not isinstance(e, dict) or
                    not isinstance(e.get('id'), str) for e in envelope['evidence'])):
            errors.append('Invalid public claim or evidence shape')
            continue
        evidence = {e['id']: e for e in envelope['evidence']}
        if len(evidence) != len(envelope['evidence']):
            errors.append('Duplicate public evidence ID')
        for claim in envelope['claims']:
            if not isinstance(claim['evidence_ids'], list):
                errors.append('Public evidence references must be a list')
                continue
            if claim['field'] == 'verified_website':
                errors.append('Internal website alias leaked into public output')
            if claim['availability'] not in states:
                errors.append('Invalid public availability state')
            if claim['availability'] == 'available':
                if claim['value'] is None or not claim['evidence_ids'] or any(r not in evidence for r in claim['evidence_ids']):
                    errors.append('Supported public fact lacks value or evidence')
            elif claim['value'] is not None or claim['evidence_ids']:
                errors.append('Unavailable public fact has a value or evidence')
    return errors
