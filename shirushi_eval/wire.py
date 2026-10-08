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
    if [e.get('organisation_number') for e in envelopes] != subjects:
        errors.append('Public output differs from supplied ordered membership')
    states = {'available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed'}
    for envelope in envelopes:
        if not {'organisation_number', 'run', 'claims', 'evidence', 'changes', 'errors', 'operations'} <= envelope.keys():
            errors.append('Missing public example fields')
            continue
        evidence = {e['id']: e for e in envelope['evidence']}
        for claim in envelope['claims']:
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
