"""Independent live-source audit. No maker, checker or extraction imports."""
import hashlib
import json
import math
import re
from datetime import date
from urllib.parse import urlsplit

from .reference import strict_json


# Independently maintained interpretation, intentionally not imported from maker.
ACCOUNT_FIELDS = {
    'annual_revenue': ('resultatregnskapResultat', 'driftsresultat', 'driftsinntekter', 'sumDriftsinntekter'),
    'annual_operating_profit': ('resultatregnskapResultat', 'driftsresultat', 'driftsresultat'),
    'annual_profit_before_tax': ('resultatregnskapResultat', 'ordinaertResultatFoerSkattekostnad'),
    'annual_net_profit': ('resultatregnskapResultat', 'aarsresultat'),
    'total_assets': ('eiendeler', 'sumEiendeler'),
    'total_equity': ('egenkapitalGjeld', 'egenkapital', 'sumEgenkapital'),
    'total_liabilities': ('egenkapitalGjeld', 'gjeldOversikt', 'sumGjeld'),
    'current_liabilities': ('egenkapitalGjeld', 'gjeldOversikt', 'kortsiktigGjeld', 'sumKortsiktigGjeld'),
    'long_term_liabilities': ('egenkapitalGjeld', 'gjeldOversikt', 'langsiktigGjeld', 'sumLangsiktigGjeld'),
}


def financial_context(record, subject):
    if record['virksomhet']['organisasjonsnummer'] != subject:
        raise ValueError('Audit accounts subject mismatch')
    scope = {'SELSKAP': 'entity_accounts', 'KONSERN': 'group_accounts'}[record['regnskapstype']]
    period = record['regnskapsperiode']
    if (not isinstance(period, dict) or set(period) != {'fraDato', 'tilDato'}
            or any(not isinstance(v, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', v) is None
                   for v in period.values())
            or date.fromisoformat(period['fraDato']) > date.fromisoformat(period['tilDato'])):
        raise ValueError('Audit invalid financial period')
    if not isinstance(record['valuta'], str) or re.fullmatch('[A-Z]{3}', record['valuta']) is None:
        raise ValueError('Audit invalid financial currency')
    return scope, period


def financial_value(amount, record, scope, period):
    if type(amount) not in (int, float) or not math.isfinite(amount):
        raise ValueError('Audit nonfinite or nonnumeric amount')
    return {'amount': amount, 'currency': record['valuta'], 'period': period,
            'account_scope': 'entity' if scope == 'entity_accounts' else 'group',
            'normalization': 'raw_source_currency_units'}


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
        if (not isinstance(body, list) or len(body) > 200 or type(path[0]) is not int or path[0] < 0
                or tuple(path[1:]) != ACCOUNT_FIELDS.get(field)):
            raise ValueError('Audit unsupported financial interpretation')
        record = body[path[0]]
        scope, period = financial_context(record, subject)
        item_key = None
        expected = financial_value(source, record, scope, period)
        if (claim.get('family') != 'financials_history' or locator != {
                'path': path, 'scope': scope, 'family': 'financials_history', 'item_key': None, 'period': period}):
            raise ValueError('Audit financial locator context mismatch')
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
