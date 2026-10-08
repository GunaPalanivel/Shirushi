"""Official source proposals; independent source acceptance follows below."""
import math
import re
from datetime import date

from .claims import claim_id
from .contracts import loads, timestamp
from .extraction import Candidate
from .json_spans import span
from .snapshots import digest

ENTITY = 'https://data.brreg.no/enhetsregisteret/api/enheter/'
ACCOUNTS = 'https://data.brreg.no/regnskapsregisteret/regnskap/'
SUBUNITS = 'https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet='


def at(value, path):
    for component in path:
        value = value[component]
    return value


def propose_api(store, sid):
    raw, receipt = store.open(sid)
    body, subject = loads(raw), receipt['organisation_number']
    proposals = []
    def add(field, value, path, scope, family, item=None, period=None):
        proposals.append(Candidate(subject, field, value, sid, {
            'path': path, 'scope': scope, 'family': family, 'item_key': item, 'period': period}))
    kind = receipt['source_class']
    if kind == 'brreg_entity':
        for field, key, family in [('legal_name', 'navn', None), ('legal_form', 'organisasjonsform', None),
                                   ('registered_employees', 'antallAnsatte', None),
                                   ('registered_address', 'forretningsadresse', None),
                                   ('registered_activity', 'aktivitet', 'business_products'),
                                   ('declared_website', 'hjemmeside', 'website_owned_profiles')]:
            if key in body and body[key] not in (None, '', []):
                if field == 'registered_employees' and body.get('harRegistrertAntallAnsatte') is not True:
                    continue
                add(field, body[key], [key], 'official_entity', family)
    elif kind == 'brreg_accounts':
        for index, record in enumerate(body):
            if record.get('regnskapstype') not in ('SELSKAP', 'KONSERN'):
                continue
            scope = 'entity_accounts' if record['regnskapstype'] == 'SELSKAP' else 'group_accounts'
            period = record.get('regnskapsperiode')
            path = [index, 'resultatregnskapResultat', 'driftsresultat', 'driftsinntekter', 'sumDriftsinntekter']
            try:
                amount = at(body, path)
            except (KeyError, TypeError):
                continue
            value = {'amount': amount, 'currency': record.get('valuta'), 'period': period,
                     'account_scope': 'entity' if scope == 'entity_accounts' else 'group',
                     'normalization': 'raw_source_currency_units'}
            add('annual_revenue', value, path, scope, 'financials_history', period=period)
    elif kind == 'brreg_subunits':
        for index, unit in enumerate(body.get('_embedded', {}).get('underenheter', [])):
            if unit.get('beliggenhetsadresse'):
                add('operating_location', {'subunit_number': unit.get('organisasjonsnummer'),
                                          'name': unit.get('navn'), 'address': unit['beliggenhetsadresse']},
                    ['_embedded', 'underenheter', index], 'registered_subunit', 'operating_locations',
                    item=unit.get('organisasjonsnummer'))
    return proposals


def check_api(store, candidate, subject):
    """Check receipt, legal identity, raw path and contextual interpretation."""
    audit = {'field': candidate.field, 'family': (candidate.locator or {}).get('family'),
             'checker_version': 'official_api_v1'}
    try:
        raw, receipt = store.open(candidate.snapshot_id)
        kind, locator = receipt['source_class'], candidate.locator
        expected = {'brreg_entity': ENTITY + subject, 'brreg_accounts': ACCOUNTS + subject,
                    'brreg_subunits': SUBUNITS + subject}[kind]
        if (candidate.organisation_number != subject or receipt.get('organisation_number') != subject
                or receipt.get('source_url') != expected or receipt.get('effective_url') != expected
                or receipt.get('http_status') != 200 or receipt.get('sha256') != digest(raw)
                or receipt.get('access_policy') != 'brreg-open-data-nlod-2.0'):
            raise ValueError('Official source subject or receipt mismatch')
        timestamp(receipt['retrieved_at'])
        body = loads(raw)
        path = locator['path']
        value = at(body, path)
        if kind == 'brreg_entity':
            if body.get('organisasjonsnummer') != subject or body['_links']['self']['href'] != expected:
                raise ValueError('Entity response belongs to another company')
            fields = {'legal_name': ('navn', str, None), 'legal_form': ('organisasjonsform', dict, None),
                      'registered_employees': ('antallAnsatte', int, None),
                      'registered_address': ('forretningsadresse', dict, None),
                      'registered_activity': ('aktivitet', list, 'business_products'),
                      'declared_website': ('hjemmeside', str, 'website_owned_profiles')}
            key, value_type, family = fields[candidate.field]
            if path != [key] or type(value) is not value_type or value in ('', {}, []):
                raise ValueError('Entity field or type mismatch')
            if candidate.field == 'registered_employees' and (value < 0 or not body.get('harRegistrertAntallAnsatte')):
                raise ValueError('Employee count is not explicitly registered')
            if candidate.field == 'registered_activity' and any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError('Invalid registered activity')
            scope, period, item = 'official_entity', None, None
        elif kind == 'brreg_accounts':
            if not isinstance(body, list) or len(body) > 200:
                raise ValueError('Invalid or excessive accounts list')
            index = path[0]
            if type(index) is not int or index < 0:
                raise ValueError('Invalid account index')
            record = body[index]
            if record['virksomhet']['organisasjonsnummer'] != subject:
                raise ValueError('Accounts belong to another company')
            if path[1:] != ['resultatregnskapResultat', 'driftsresultat', 'driftsinntekter', 'sumDriftsinntekter']:
                raise ValueError('Unsupported financial field')
            if candidate.field != 'annual_revenue' or type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('Revenue must be a finite supported number')
            scope = {'SELSKAP': 'entity_accounts', 'KONSERN': 'group_accounts'}[record['regnskapstype']]
            period = record['regnskapsperiode']
            if set(period) != {'fraDato', 'tilDato'} or date.fromisoformat(period['fraDato']) > date.fromisoformat(period['tilDato']):
                raise ValueError('Invalid accounting period')
            currency = record['valuta']
            if not isinstance(currency, str) or re.fullmatch('[A-Z]{3}', currency) is None:
                raise ValueError('Invalid source currency')
            value = {'amount': value, 'currency': currency, 'period': period,
                     'account_scope': 'entity' if scope == 'entity_accounts' else 'group',
                     'normalization': 'raw_source_currency_units'}
            family, item = 'financials_history', None
        else:
            if (candidate.field != 'operating_location' or len(path) != 3
                    or path[:2] != ['_embedded', 'underenheter'] or type(path[2]) is not int or path[2] < 0):
                raise ValueError('Invalid subunit locator')
            if value.get('overordnetEnhet') != subject:
                raise ValueError('Subunit belongs to another company')
            item = value['organisasjonsnummer']
            if not isinstance(item, str) or re.fullmatch('[0-9]{9}', item) is None:
                raise ValueError('Invalid subunit identity')
            value = {'subunit_number': item, 'name': value['navn'], 'address': value['beliggenhetsadresse']}
            if not isinstance(value['address'], dict) or not value['address']:
                raise ValueError('Missing location address')
            scope, family, period = 'registered_subunit', 'operating_locations', None
        if (type(candidate.value) is not type(value) or candidate.value != value
                or locator != {'path': path, 'scope': scope, 'family': family, 'item_key': item, 'period': period}):
            raise ValueError('Candidate value or context differs from source')
        identity = claim_id(subject, candidate.field, scope, item, period)
        eid = candidate.snapshot_id + ':' + identity
        claim = {'claim_id': identity, 'field': candidate.field, 'value': value, 'scope': scope,
                 'family': family, 'item_key': item, 'period': period,
                 'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
        evidence = {'id': eid, 'snapshot_id': candidate.snapshot_id, 'source_url': expected,
                    'source_class': kind, 'source_origin': receipt['source_origin'],
                    'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw),
                    'claim_span': span(raw, path), 'locator': locator,
                    'extraction_method': 'official_api_field_v1'}
        return dict(audit, accepted=True, claim=claim, evidence=evidence)
    except (ValueError, KeyError, TypeError, OSError, IndexError, AttributeError) as exc:
        return dict(audit, accepted=False, reason=str(exc))
