"""Independent NAV detail and official employer-chain audit, without maker imports."""
import hashlib
import json
import re
from html import unescape
from urllib.parse import urlsplit

from .reference import strict_json


def audit_nav(audit, subject, claim, item, receipt, raw):
    from .support import check_time
    host = 'pam-stilling-feed.nav.no'
    url = receipt['effective_url']
    parts = urlsplit(url)
    source = strict_json(raw)
    ad = source['ad_content']
    employer = ad['employer']['orgnr']
    bridge_receipt = strict_json(audit.read('receipts', receipt['employer_snapshot_id']))
    bridge_raw = audit.read('objects', bridge_receipt['content_sha256'])
    bridge = strict_json(bridge_raw)
    endpoint = 'https://data.brreg.no/enhetsregisteret/api/underenheter/' + employer
    identity = ad['uuid']
    identity_receipt = strict_json(audit.read('receipts', receipt['legal_identity_snapshot_id']))
    identity_raw = audit.read('objects', identity_receipt['content_sha256'])
    legal = strict_json(identity_raw)
    if (receipt['http_status'] != 200 or receipt['sha256'] != hashlib.sha256(raw).hexdigest()
            or receipt['source_url'] != url or parts.scheme != 'https' or parts.hostname != host
            or parts.username or parts.password or parts.port not in (None, 443)
            or not parts.path.startswith('/api/v1/') or source['status'] != 'ACTIVE'
            or re.fullmatch('[0-9]{9}', employer) is None
            or bridge_receipt['source_class'] != 'brreg_job_employer'
            or bridge_receipt['organisation_number'] != subject or bridge_receipt['http_status'] != 200
            or bridge_receipt['source_url'] != endpoint or bridge_receipt['effective_url'] != endpoint
            or bridge_receipt['sha256'] != hashlib.sha256(bridge_raw).hexdigest()
            or bridge['organisasjonsnummer'] != employer or bridge['overordnetEnhet'] != subject
            or identity_receipt['source_class'] != 'brreg_entity' or identity_receipt['http_status'] != 200
            or identity_receipt['source_url'] != 'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject
            or legal['organisasjonsnummer'] != subject or identity_receipt['sha256'] != hashlib.sha256(identity_raw).hexdigest()
            or re.fullmatch('[0-9a-f-]{36}', identity) is None or source['uuid'] != identity
            or not url.endswith('/' + identity)):
        raise ValueError('Audit NAV posting/employer chain mismatch')
    observed = check_time(receipt['retrieved_at'])
    if (check_time(ad['published']) > observed or check_time(ad['expires']) < observed
            or not isinstance(ad['title'], str) or not ad['title'].strip()):
        raise ValueError('Audit NAV posting is not active at acquisition')
    field = claim['field']
    locator = {'path': ['ad_content', 'title']}
    if field == 'job_posting':
        expected = {'title': ad['title'], 'date_posted': ad['published'], 'posting_id': identity,
                    'valid_through': ad['expires'], 'source_url': url}
        path, value, key, family = ['ad_content', 'title'], ad['title'], identity, 'jobs_dated_activity'
    elif field == 'business_description':
        value = ad['employer']['description']
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Audit NAV missing employer description')
        visible = re.sub(r'<(?:script|style|template|noscript)\b[^>]*>.*?</(?:script|style|template|noscript)\s*>', '', value, flags=re.I | re.S)
        plain = ' '.join(unescape(re.sub('<[^>]*>', ' ', visible)).split())
        name = re.sub(r'\s+(?:AS|ASA|SA|DA|HF|RHF)$', '', legal['navn'], flags=re.I)
        statements = re.split(r'(?<=[.!?])\s+', plain)
        index = item['locator'].get('statement_index')
        if type(index) is not int or not 0 <= index < len(statements):
            raise ValueError('Audit NAV business sentence locator mismatch')
        statement = statements[index]
        action = (r'\b(?:tilbyr|leverer|produserer|utvikler|driver|selger|vedlikeholder|reparerer|baker|'
            r'manufactures|produces|provides|offers|develops|operates|repairs|'
            r'(?:er|is)\s+.{0,100}(?:bemannings\w*|rekrutterings\w*|advokat\w*|barnehage\w*|bakeri\w*|'
            r'forhandler\w*|butikk\w*|varehus\w*|konsulent\w*|teknologi\w*|sikkerhet\w*|mobilitet\w*|byr\u00e5\w*|akt\u00f8r\w*|leverand\u00f8r\w*|provider|manufacturer))\b')
        if (not 10 <= len(statement) <= 1000 or not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)'
                r'(?:\s+(?:AS|ASA|SA|DA|HF|RHF))?\s+' + action, statement, re.I)
                or re.search(r'\b(?:ikke|not|kunde|customer|konsern|group)\b', statement, re.I)):
            raise ValueError('Audit NAV description lacks target-operation attribution')
        expected, path, key, family = statement, ['ad_content', 'employer', 'description'], employer, 'business_products'
        locator = {'path': path, 'statement_index': index}
    else:
        raise ValueError('Audit unsupported NAV field')
    encoded = json.dumps([subject, field, 'nav_verified_employer', key, None], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if (claim['value'] != expected or claim.get('scope') != 'nav_verified_employer'
            or claim.get('family') != family or claim.get('item_key') != key or claim.get('period') is not None
            or claim['claim_id'] != hashlib.sha256(encoded).hexdigest()
            or item['locator'] != locator or strict_json(item['claim_span']) != value
            or item['extraction_method'] != 'nav_subunit_bridge_v1' or item['source_origin'] != host):
        raise ValueError('Audit NAV value, span or identity mismatch')
