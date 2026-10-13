"""Kit-compatible envelope blocks built only from published claims and evidence.

Nothing here observes a source. Every value is copied from an available claim
(or from the run record), so the blocks cannot assert a fact the public claims
do not already support. The organizer's starter kit shapes are described by its
documented behaviour; no kit code is used.
"""
import json

from .contracts import timestamp
from .social_sources import canonical_profile

KIT_KEYS = ('run_id', 'state', 'started_at', 'completed_at', 'modules', 'profile')
ADAPTER = 'shirushi-kit-profile-v1'
MODULE_ORDER = ('registry', 'registry_live', 'financials', 'roles', 'locations', 'website')
PROFILE_EVIDENCE = ('registry_live', 'website')
REGISTRY_FIELDS = frozenset((
    'legal_name', 'legal_form', 'registered_employees', 'registered_municipality', 'registered_municipality_number',
    'industry_code', 'industry_label', 'latest_submitted_accounts_year', 'registered_address', 'registered_activity',
    'declared_website'))
# Registry and official-API scopes are copies of the source value, hence full confidence.
OFFICIAL_SCOPES = frozenset(('frozen_registry', 'official_entity', 'entity_accounts', 'group_accounts',
                             'registered_subunit', 'registered_role_snapshot'))
STATUS = {'available': 'available', 'not_available': 'not_found', 'ambiguous': 'not_found', 'blocked': 'blocked',
          'failed': 'source_error', 'not_applicable': 'not_applicable'}
SEVERITY = ('blocked', 'failed', 'ambiguous', 'not_available', 'not_applicable')
WEBSITE_NOTE = 'Company-controlled claim layer; not an official registry fact'


def confidence(claim):
    """Ordinal policy by evidence class, not a calibrated probability; zero only when no value is supported."""
    if claim.get('availability') != 'available':
        return 0.0
    field, scope, value = claim.get('field'), claim.get('scope'), claim.get('value')
    if scope in OFFICIAL_SCOPES:
        return 1.0
    if field == 'official_website':
        return 0.9 if scope == 'registry_declared_host_name_gate' else 0.99
    if field == 'dated_news':
        published = value.get('published_at') if isinstance(value, dict) else None
        return 0.9 if isinstance(published, str) and 'T' in published else 0.8
    return 0.99 if scope == 'nav_verified_employer' else 0.9


def order_key(claim):
    return (claim.get('scope') or '', json.dumps(claim.get('value'), sort_keys=True, ensure_ascii=False))


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


def unavailable(claims):
    """The most severe non-available claim stands for the module."""
    for state in SEVERITY:
        for claim in claims:
            if claim['availability'] == state:
                return claim
    return None


def module_state(claims):
    if any(c['availability'] == 'available' for c in claims):
        return 'complete'
    claim = unavailable(claims)
    reason = str(claim.get('reason') or '').lower()
    if claim['availability'] == 'blocked':
        return 'blocked_robots' if 'robot' in reason else 'blocked_policy'
    if claim['availability'] == 'failed':
        return 'budget_exhausted' if 'budget' in reason and 'exhaust' in reason else 'source_error'
    return 'not_applicable' if claim['availability'] == 'not_applicable' else 'not_found'


def latest(evidence, claims, fallback):
    cited = [evidence[i]['retrieved_at'] for c in claims if c['availability'] == 'available'
             for i in c['evidence_ids'] if i in evidence]
    return max(cited, key=timestamp) if cited else fallback


def sourced(field, claim, evidence, value, note, row_key=None):
    item = evidence[claim['evidence_ids'][0]]
    return {'field': field, 'status': 'available', 'source_type': item['source_class'],
            'source_class': item['source_class'], 'source_url': item['source_url'],
            'retrieved_at': item['retrieved_at'], 'value': value, 'as_of': None, 'note': note,
            'content_sha256': item['content_sha256'], 'source_row_key': row_key, 'effective_at': None,
            'availability': 'available', 'evidence_ids': list(claim['evidence_ids'])}


def absent(field, source_class, claim, completed, source_url=None):
    state = claim['availability'] if claim else 'not_available'
    return {'field': field, 'status': STATUS[state], 'source_type': source_class, 'source_class': source_class,
            'source_url': source_url, 'retrieved_at': completed, 'value': None, 'as_of': None,
            'note': (claim or {}).get('reason') or 'No supported claim', 'content_sha256': None,
            'source_row_key': None, 'effective_at': None, 'availability': state,
            'reason': (claim or {}).get('reason') or 'No supported claim'}


def first(claims, field):
    found = sorted((c for c in claims if c['field'] == field and c['availability'] == 'available'), key=order_key)
    return found[0] if found else None


def profile_fields(claims):
    values = {}
    name, form, staff = first(claims, 'legal_name'), first(claims, 'legal_form'), first(claims, 'registered_employees')
    town, site = first(claims, 'registered_municipality'), first(claims, 'declared_website')
    if name and isinstance(name['value'], str):
        values['name'] = name['value']
    if form:
        code = form['value'].get('kode') if isinstance(form['value'], dict) else form['value']
        if isinstance(code, str):
            values['legal_form'] = code
    if staff and type(staff['value']) is int:
        values['employees'] = staff['value']
    if town and isinstance(town['value'], str):
        values['municipality'] = town['value']
    if site and isinstance(site['value'], str):
        values['website'] = site['value']
    return values


def registry_record(envelope, claims, evidence, fields):
    completed = envelope['run']['completed_at']
    name = first(claims, 'legal_name')
    if name is None:
        anchor = next((e['source_url'] for e in envelope['evidence'] if e['source_class'] == 'frozen_registry'), None)
        return absent('registry_live', 'frozen_registry',
                      unavailable([c for c in claims if c['field'] == 'legal_name']), completed, anchor)
    value = {'organisation_number': envelope['organisation_number']}
    value.update({key: fields[key] for key in ('name', 'legal_form', 'employees', 'website') if key in fields})
    return sourced('registry_live', name, evidence, value, None, envelope['organisation_number'])


def website_record(envelope, claims, evidence):
    completed = envelope['run']['completed_at']
    own = module_claims(claims, 'website')
    if not own:
        return None
    site = first(own, 'official_website')
    if site is None:
        return absent('website', 'company_owned', unavailable(own), completed)
    score = confidence(site)
    pairs = set()
    for social in claims:
        if social['field'] != 'social_profile' or social['availability'] != 'available':
            continue
        value = social['value']
        if isinstance(value, dict) and isinstance(value.get('platform'), str) and isinstance(value.get('url'), str):
            pairs.add((value['platform'], value['url']))
        elif isinstance(value, str):
            # The claim stays the handle key. Platform and URL come only from that string.
            profile = canonical_profile(value if '://' in value else 'https://' + value)
            if profile is not None:
                pairs.add((profile['platform'], profile['url']))
    links = [{'platform': platform, 'url': url} for platform, url in sorted(pairs)]
    value = {'final_url': site['value'],
             'identity_assessment': {'status': 'exact' if score >= 0.9 else 'review', 'score': score,
                                     'publishable': True, 'method': 'shirushi_published_claim_v1',
                                     'reasons': [site.get('scope')]},
             'social_links': links, 'discovered_social_links': [dict(link) for link in links],
             'social_link_assessments': [dict(link, identity_score=0.9, publishable=True,
                                              method='shirushi_published_claim_v1') for link in links]}
    return sourced('website', site, evidence, value, WEBSITE_NOTE)


def kit_blocks(envelope):
    """The six kit keys for one public-named envelope."""
    run, claims = envelope['run'], envelope['claims']
    evidence = {e['id']: e for e in envelope['evidence']}
    fields = profile_fields(claims)
    modules = {}
    for module in MODULE_ORDER:
        related = module_claims(claims, module)
        if related:
            modules[module] = {'state': module_state(related), 'retry_count': 0,
                               'final_timestamp': latest(evidence, related, run['completed_at'])}
    records = {'registry_live': registry_record(envelope, claims, evidence, fields),
               'website': website_record(envelope, claims, evidence)}
    profile = {'organisation_number': envelope['organisation_number'], **fields,
               'kit_compat': {'derived_from_claims': True, 'adapter': ADAPTER},
               'evidence': {key: records[key] for key in PROFILE_EVIDENCE if records[key] is not None}}
    if 'registry' not in modules:
        del profile['evidence']['registry_live']
    return {'run_id': run['run_id'], 'state': 'complete' if run['terminal_status'] == 'completed' else 'submission_error',
            'started_at': run['started_at'], 'completed_at': run['completed_at'], 'modules': modules,
            'profile': profile}


def strip(envelope):
    """Remove every kit-added key, restoring the plain public record."""
    for key in KIT_KEYS:
        envelope.pop(key, None)
    for claim in envelope.get('claims', []):
        claim.pop('confidence', None)


def annotate(envelope):
    strip(envelope)
    for claim in envelope['claims']:
        claim['confidence'] = confidence(claim)
    envelope.update(kit_blocks(envelope))
