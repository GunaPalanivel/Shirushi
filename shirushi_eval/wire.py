"""Independent public example checks, not a claim about the private harness."""
import re
from copy import deepcopy

KIT_KEYS = ('run_id', 'state', 'started_at', 'completed_at', 'modules', 'profile')
KIT_MODULES = ('registry', 'registry_live', 'financials', 'roles', 'locations', 'website')
KIT_MODULE_STATES = {'complete', 'not_applicable', 'not_found', 'blocked_policy', 'blocked_robots', 'source_error',
                     'budget_exhausted', 'submission_error'}
KIT_STATUSES = {'available', 'not_found', 'not_applicable', 'not_fetched', 'source_error', 'blocked'}
KIT_RECORD_KEYS = {'field', 'status', 'source_type', 'source_class', 'source_url', 'retrieved_at', 'value', 'as_of',
                   'note', 'content_sha256', 'source_row_key', 'effective_at'}
STATES = {'available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed'}
STATUS_OF = {'not_available': 'not_found', 'ambiguous': 'not_found', 'blocked': 'blocked', 'failed': 'source_error',
             'not_applicable': 'not_applicable'}
REGISTRY_FIELDS = {'legal_name', 'legal_form', 'registered_employees', 'registered_municipality',
                   'registered_municipality_number', 'industry_code', 'industry_label',
                   'latest_submitted_accounts_year', 'registered_address', 'registered_activity', 'declared_website'}
PROFILE_KEYS = {'organisation_number', 'name', 'legal_form', 'employees', 'municipality', 'website', 'kit_compat',
                'evidence'}
TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})')


def internal_records(envelopes):
    result = deepcopy(envelopes)
    for envelope in result:
        for key in KIT_KEYS:
            envelope.pop(key, None)
        for claim in envelope.get('claims', []):
            claim.pop('confidence', None)
        for key in ('claims', 'history', 'changes'):
            for record in envelope.get(key, []):
                if record.get('field') == 'official_website':
                    record['field'] = 'verified_website'
    return result


def module_claims(claims, module):
    if module in ('registry', 'registry_live'):
        return [c for c in claims if c['field'] in REGISTRY_FIELDS]
    if module == 'financials':
        return [c for c in claims if c.get('family') == 'financials_history' or c['field'] == 'coverage:financials_history']
    if module == 'roles':
        return [c for c in claims if c['field'].startswith('registered_role:') or c['field'] == 'coverage:people']
    if module == 'locations':
        return [c for c in claims if c['field'] in ('operating_location', 'coverage:operating_locations')]
    own = [c for c in claims if c['field'] == 'official_website']
    return own or [c for c in claims if c['field'] == 'coverage:website_owned_profiles']


def allowed_module_states(claims):
    """Every module state some claim in the set can justify; complete only with an available claim."""
    states = set()
    for claim in claims:
        reason = str(claim.get('reason') or '').lower()
        state = claim['availability']
        if state == 'available':
            states.add('complete')
        elif state == 'blocked':
            states.add('blocked_robots' if 'robot' in reason else 'blocked_policy')
        elif state == 'failed':
            states.add('budget_exhausted' if 'budget' in reason and 'exhaust' in reason else 'source_error')
        elif state == 'not_applicable':
            states.add('not_applicable')
        else:
            states.add('not_found')
    return states


def timestamp_ok(value):
    return isinstance(value, str) and TIME.fullmatch(value) is not None


def validate_kit_blocks(envelope):
    """Every kit block value must be derivable from the envelope's own available claims and evidence."""
    claims = envelope['claims']
    if not any(k in envelope for k in KIT_KEYS) and not any('confidence' in c for c in claims):
        return []
    if any(k not in envelope for k in KIT_KEYS):
        return ['Incomplete kit-compatible blocks']
    errors = []
    evidence = {e['id']: e for e in envelope['evidence']}
    run = envelope['run'] if isinstance(envelope['run'], dict) else {}
    available = {}
    for claim in claims:
        value = claim.get('confidence')
        if type(value) not in (int, float) or not 0 <= value <= 1:
            errors.append('Claim confidence must be a number from 0 to 1')
        elif (value > 0) != (claim['availability'] == 'available'):
            errors.append('Claim confidence must be positive exactly when a value is supported')
        if claim['availability'] == 'available':
            available.setdefault(claim['field'], []).append(claim)
    for key in ('run_id', 'started_at', 'completed_at'):
        if envelope[key] != run.get(key):
            errors.append('Kit ' + key + ' differs from run')
    if envelope['state'] != ('complete' if run.get('terminal_status') == 'completed' else 'submission_error'):
        errors.append('Kit state differs from run terminal status')
    modules = envelope['modules']
    if not isinstance(modules, dict):
        return errors + ['Kit modules must be an object']
    for name, module in modules.items():
        related = module_claims(claims, name) if name in KIT_MODULES else []
        if not related or not isinstance(module, dict):
            errors.append('Kit module without supporting claims: ' + str(name))
            continue
        stamps = {run.get('completed_at')} | {evidence[i]['retrieved_at'] for c in related
                                              if c['availability'] == 'available' for i in c['evidence_ids']}
        if (module.get('state') not in KIT_MODULE_STATES or module.get('state') not in allowed_module_states(related)
                or (module.get('state') == 'complete') != any(c['availability'] == 'available' for c in related)):
            errors.append('Kit module state is not supported by claims: ' + name)
        if module.get('retry_count') != 0 or type(module.get('retry_count')) is not int:
            errors.append('Kit module retry count is not tracked')
        if module.get('final_timestamp') not in stamps:
            errors.append('Kit module timestamp is not a run or evidence time: ' + name)
    profile = envelope['profile']
    if not isinstance(profile, dict) or profile.keys() - PROFILE_KEYS:
        return errors + ['Kit profile has unsupported keys']

    def values(field):
        return [c['value'] for c in available.get(field, [])]
    names = values('legal_name')
    forms = [v.get('kode') if isinstance(v, dict) else v for v in values('legal_form')]
    expected = {'name': names, 'legal_form': forms, 'employees': values('registered_employees'),
                'municipality': values('registered_municipality'), 'website': values('declared_website')}
    for key, supported in expected.items():
        supported = [v for v in supported if (type(v) is int if key == 'employees' else isinstance(v, str))]
        if key in profile:
            if not any(type(profile[key]) is type(v) and profile[key] == v for v in supported):
                errors.append('Kit profile ' + key + ' has no matching available claim')
        elif supported:
            errors.append('Kit profile omits supported ' + key)
    if profile.get('organisation_number') != envelope['organisation_number']:
        errors.append('Kit profile identity differs from envelope')
    if profile.get('kit_compat') != {'derived_from_claims': True, 'adapter': 'shirushi-kit-profile-v1'}:
        errors.append('Kit profile lacks its derivation marker')
    records = profile.get('evidence')
    if not isinstance(records, dict) or records.keys() - {'registry_live', 'website'}:
        return errors + ['Kit profile evidence has unsupported modules']
    for key, item in records.items():
        errors.extend(validate_kit_record(key, item, envelope, evidence, available, profile))
    return errors


def published_social_pair(value):
    """The platform and URL a published social_profile claim supports.

    A dict claim already carries both. A string claim is the handle key, and the
    pair is only the canonical profile of that string.
    """
    if isinstance(value, dict) and isinstance(value.get('platform'), str) and isinstance(value.get('url'), str):
        return (value['platform'], value['url'])
    if isinstance(value, str) and value:
        from shirushi.social_sources import canonical_profile
        profile = canonical_profile(value if '://' in value else 'https://' + value)
        if profile is not None:
            return (profile['platform'], profile['url'])
    return None


def validate_kit_record(key, item, envelope, evidence, available, profile):
    if not isinstance(item, dict) or not KIT_RECORD_KEYS <= item.keys() or item['field'] != key:
        return ['Kit evidence record malformed: ' + key]
    errors = []
    claims = [c for c in envelope['claims'] if c['field'] in (('legal_name',) if key == 'registry_live'
              else ('official_website', 'coverage:website_owned_profiles'))]
    if item['status'] not in KIT_STATUSES or not timestamp_ok(item['retrieved_at']):
        errors.append('Kit evidence status or time invalid: ' + key)
    if item['status'] != 'available':
        states = {c['availability'] for c in claims}
        if (item['value'] is not None or item['content_sha256'] is not None or 'available' in states
                or item.get('availability') not in STATES - {'available'}
                or STATUS_OF.get(item.get('availability')) != item['status']
                or item['availability'] not in states and claims):
            errors.append('Kit evidence record claims no support but is not an absence: ' + key)
        return errors
    claim_field = 'legal_name' if key == 'registry_live' else 'official_website'
    ids = item.get('evidence_ids')
    cited = [c for c in available.get(claim_field, []) if ids == c['evidence_ids']]
    if not cited or not ids or any(i not in evidence for i in ids):
        return errors + ['Kit evidence record cites no available claim evidence: ' + key]
    source = evidence[ids[0]]
    if (item['availability'] != 'available' or item['source_url'] != source['source_url']
            or item['content_sha256'] != source['content_sha256'] or item['retrieved_at'] != source['retrieved_at']
            or item['source_class'] != source['source_class']):
        errors.append('Kit evidence record differs from its cited evidence: ' + key)
    value = item['value']
    if not isinstance(value, dict):
        return errors + ['Kit evidence value must be an object: ' + key]
    if key == 'registry_live':
        if (value.keys() - {'organisation_number', 'name', 'legal_form', 'employees', 'website'} or value.get('organisation_number') != envelope['organisation_number']
                or any(value[k] != profile.get(k) or type(value[k]) is not type(profile.get(k))
                       for k in value if k != 'organisation_number')
                or any(k in profile and k not in value for k in ('name', 'legal_form', 'employees', 'website'))):
            errors.append('Kit registry record differs from the profile claims')
        return errors
    if (value.keys() - {'final_url', 'identity_assessment', 'social_links', 'discovered_social_links',
                        'social_link_assessments'} or value.get('final_url') != cited[0]['value']
            or not isinstance(value.get('identity_assessment'), dict)
            or value['identity_assessment'].get('publishable') is not True):
        errors.append('Kit website record is not the published official website')
    supported = {pair for c in available.get('social_profile', [])
                 if (pair := published_social_pair(c.get('value'))) is not None}
    links = value.get('social_links')
    pairs = [(l.get('platform'), l.get('url')) for l in links if isinstance(l, dict)] if isinstance(links, list) else None
    if (pairs is None or len(pairs) != len(links) or pairs != sorted(set(pairs)) or not set(pairs) <= supported
            or any(l.keys() != {'platform', 'url'} for l in links)):
        errors.append('Kit social links are not sorted published social_profile claims')
    for field in ('discovered_social_links', 'social_link_assessments'):
        extra = value.get(field, [])
        if (not isinstance(extra, list) or any(not isinstance(l, dict) or (l.get('platform'), l.get('url')) not in
                                                (pairs or []) for l in extra)
                or any(field == 'social_link_assessments' and l.get('publishable') is not True for l in extra)):
            errors.append('Kit social link detail is not backed by a published link')
    return errors


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
        try:
            errors.extend(validate_kit_blocks(envelope))
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            errors.append('Kit-compatible blocks are malformed: ' + type(exc).__name__)
    return errors
