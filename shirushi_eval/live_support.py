"""Independent live-source audit. No maker, checker or extraction imports."""
import hashlib
import json
import math
from urllib.parse import urlsplit

from .reference import strict_json


def audit_api(subject, claim, item, receipt, raw):
    kind = receipt['source_class']
    urls = {'brreg_entity': 'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject,
            'brreg_accounts': 'https://data.brreg.no/regnskapsregisteret/regnskap/' + subject,
            'brreg_subunits': 'https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet=' + subject}
    if (receipt['source_url'] != urls[kind] or receipt.get('effective_url') != urls[kind]
            or receipt.get('http_status') != 200 or receipt.get('access_policy') != 'brreg-open-data-nlod-2.0'
            or receipt.get('sha256') != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Audit official endpoint or receipt mismatch')
    body = strict_json(raw)
    locator = item['locator']
    source = body
    for component in locator['path']:
        if isinstance(component, bool):
            raise ValueError('Invalid source locator')
        source = source[component]
    if strict_json(item['claim_span']) != source:
        raise ValueError('Audit source span supports a different value')
    field = claim['field']
    if kind == 'brreg_entity':
        if body.get('organisasjonsnummer') != subject or body['_links']['self']['href'] != urls[kind]:
            raise ValueError('Audit entity subject mismatch')
        projection = {'legal_name': ('navn', str), 'legal_form': ('organisasjonsform', dict),
                      'registered_employees': ('antallAnsatte', int), 'registered_address': ('forretningsadresse', dict),
                      'registered_activity': ('aktivitet', list), 'declared_website': ('hjemmeside', str)}
        key, expected_type = projection[field]
        if locator['path'] != [key] or type(source) is not expected_type:
            raise ValueError('Audit entity field type or path mismatch')
        if field == 'registered_employees' and (source < 0 or body.get('harRegistrertAntallAnsatte') is not True):
            raise ValueError('Audit unsupported employee count')
        expected, scope, item_key, period = source, 'official_entity', None, None
    elif kind == 'brreg_accounts':
        path = locator['path']
        if path[1:] != ['resultatregnskapResultat', 'driftsresultat', 'driftsinntekter', 'sumDriftsinntekter'] or field != 'annual_revenue':
            raise ValueError('Audit unsupported financial interpretation')
        record = body[path[0]]
        if record['virksomhet']['organisasjonsnummer'] != subject:
            raise ValueError('Audit accounts subject mismatch')
        scope = {'SELSKAP': 'entity_accounts', 'KONSERN': 'group_accounts'}[record['regnskapstype']]
        period, item_key = record['regnskapsperiode'], None
        if type(source) not in (int, float) or not math.isfinite(source):
            raise ValueError('Audit nonfinite amount')
        expected = {'amount': source, 'currency': record['valuta'], 'period': period,
                    'account_scope': 'entity' if scope == 'entity_accounts' else 'group',
                    'normalization': 'raw_source_currency_units'}
    else:
        if source.get('overordnetEnhet') != subject or field != 'operating_location':
            raise ValueError('Audit subunit attribution failure')
        expected = {'subunit_number': source['organisasjonsnummer'], 'name': source['navn'],
                    'address': source['beliggenhetsadresse']}
        scope, item_key, period = 'registered_subunit', source['organisasjonsnummer'], None
    if (type(expected) is not type(claim['value']) or expected != claim['value'] or scope != claim.get('scope')
            or item_key != claim.get('item_key') or period != claim.get('period')):
        raise ValueError('Audit live value, period or scope mismatch')
    encoded = json.dumps([subject, field, scope, item_key, period], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if claim.get('claim_id') != hashlib.sha256(encoded).hexdigest():
        raise ValueError('Audit canonical claim identity mismatch')


def audit_web(subject, claim, item, receipt, raw):
    if (receipt.get('robots_checked') is not True or receipt.get('http_status') != 200
            or receipt.get('declared_host') != urlsplit(receipt['effective_url']).hostname):
        raise ValueError('Audit company source scope mismatch')
    # Parse the retained JSON-LD span independently, then resolve its declared node.
    root = strict_json(item['claim_span'])
    node = root
    for component in item['locator']['node_path']:
        node = node[component]
    field = claim['field']
    owner = node.get('hiringOrganization') if field == 'job_posting' else node.get('about') if field == 'public_activity' else node
    if not isinstance(owner, dict):
        raise ValueError('Audit missing legal publisher/employer identity')
    ids = [owner.get(k) for k in ('identifier', 'taxID', 'vatID')]
    ids = [v.get('value') if isinstance(v, dict) else v for v in ids]
    normalized = [str(v).replace(' ', '').upper().removeprefix('NO').removesuffix('MVA') for v in ids if v is not None]
    if subject not in normalized:
        raise ValueError('Audit website fact belongs to another legal entity')
    if field == 'business_description':
        expected = node['description']
    elif field == 'verified_website':
        expected = node['url']
        if urlsplit(expected).hostname != receipt['declared_host']:
            raise ValueError('Audit website host mismatch')
        if not urlsplit(expected).path:
            expected += '/'
    elif field == 'job_posting':
        identity = node['identifier']
        expected = {'title': node['title'], 'date_posted': node['datePosted'],
                    'posting_id': identity.get('value') if isinstance(identity, dict) else identity,
                    'valid_through': node.get('validThrough'), 'source_url': receipt['effective_url']}
    elif field == 'public_activity':
        expected = {'headline': node['headline'], 'published_at': node['datePublished'], 'source_url': receipt['effective_url']}
    else:
        raise ValueError('Audit unsupported company page field')
    if expected != claim['value'] or claim['scope'] != 'company_owned_structured':
        raise ValueError('Audit company page value mismatch')
