"""One shared, bounded NAV feed window; exact employer/subunit attribution."""
import email.utils
import re
import threading
from html import unescape
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

from .claims import claim_id
from .contracts import loads, timestamp
from .fetch import SourceUnavailable, safe_url
from .json_spans import span as locate
from .snapshots import digest

HOST = 'pam-stilling-feed.nav.no'
SUBUNIT = 'https://data.brreg.no/enhetsregisteret/api/underenheter/'


def company_key(value):
    return re.sub(r'\s+(?:as|asa)$', '', ' '.join(value.casefold().split()))


def business_statement(description, legal_name):
    """Keep one explicit target-operation sentence, never group boilerplate."""
    description = re.sub(r'<(?:script|style|template|noscript)\b[^>]*>.*?</(?:script|style|template|noscript)\s*>', '', description, flags=re.I | re.S)
    plain = ' '.join(unescape(re.sub('<[^>]*>', ' ', description)).split())
    name = re.sub(r'\s+(?:AS|ASA|SA|DA|HF|RHF)$', '', legal_name, flags=re.I)
    operation = (r'\b(?:tilbyr|leverer|produserer|utvikler|driver|selger|vedlikeholder|reparerer|baker|'
        r'manufactures|produces|provides|offers|develops|operates|repairs|'
        r'(?:er|is)\s+.{0,100}(?:bemannings\w*|rekrutterings\w*|advokat\w*|barnehage\w*|bakeri\w*|'
        r'forhandler\w*|butikk\w*|varehus\w*|selskap\w*|firma\w*|byr\u00e5\w*|akt\u00f8r\w*|leverand\u00f8r\w*|company|provider|manufacturer))\b')
    for index, sentence in enumerate(re.split(r'(?<=[.!?])\s+', plain)):
        if (10 <= len(sentence) <= 1000 and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)'
                r'(?:\s+(?:AS|ASA|SA|DA|HF|RHF))?\s+' + operation, sentence, re.I)
                and not re.search(r'\b(?:ikke|not|kunde|customer|konsern|group)\b', sentence, re.I)):
            return sentence, index
    return None


class NavFeed:
    def __init__(self, fetcher, days=7, max_pages=2):
        self.fetcher, self.days, self.max_pages = fetcher, days, max_pages
        self.lock, self.index, self.token, self.error = threading.Lock(), None, None, None
        self.diagnostics = {'pages': 0, 'active_headers': 0, 'window_complete': False}

    def headers(self):
        while not self.lock.acquire(timeout=0.05):
            self.fetcher.budget.remaining()
        try:
            if self.index is not None:
                return self.index
            if self.error:
                raise SourceUnavailable(self.error, 'blocked')
            raw, _ = self.fetcher.get('https://' + HOST + '/api/publicToken', {HOST})
            tokens = re.findall(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', raw.decode('utf-8'))
            if len(tokens) != 1:
                raise SourceUnavailable('Invalid NAV public experimental-token response', 'blocked')
            self.token = tokens[0]
            since = email.utils.format_datetime(datetime.now(timezone.utc) - timedelta(days=self.days), usegmt=True)
            url, index = 'https://' + HOST + '/api/v1/feed', {}
            for _ in range(self.max_pages):
                raw, _ = self.fetcher.get(url, {HOST}, request_headers={'Authorization': 'Bearer ' + self.token,
                                                                 'If-Modified-Since': since})
                page = loads(raw)
                self.diagnostics['pages'] += 1
                items = page.get('items', [])
                if not isinstance(items, list) or len(items) > 2000:
                    raise SourceUnavailable('Invalid NAV feed page')
                for item in items:
                    if not isinstance(item, dict):
                        raise SourceUnavailable('Invalid NAV feed item')
                    header = item.get('_feed_entry', {})
                    if not isinstance(header, dict):
                        raise SourceUnavailable('Invalid NAV feed header')
                    if header.get('status') != 'ACTIVE' or not isinstance(header.get('businessName'), str):
                        continue
                    candidate = safe_url(urljoin('https://' + HOST + '/', item['url']), {HOST})
                    if not urlsplit(candidate).path.startswith('/api/v1/'):
                        continue
                    index.setdefault(company_key(header['businessName']), []).append(candidate)
                    self.diagnostics['active_headers'] += 1
                next_url = page.get('next_url')
                if not next_url:
                    self.diagnostics['window_complete'] = True
                    break
                url = safe_url(urljoin('https://' + HOST + '/', next_url), {HOST})
            self.index = index
            return index
        except (SourceUnavailable, ValueError, KeyError, TypeError) as exc:
            # One shared bootstrap failure must not consume the run budget once
            # per company. A truncated window never establishes absence.
            self.error = 'NAV feed bootstrap unavailable: ' + str(exc)
            raise SourceUnavailable(self.error, 'blocked') from None
        finally:
            self.lock.release()

    def for_company(self, subject, entity):
        candidates = self.headers().get(company_key(entity['navn']), [])
        pages, failures = [], []
        # Name is a retrieval lead only. Every detail must pass the official org bridge.
        for url in list(dict.fromkeys(candidates))[:3]:
            try:
                raw, receipt = self.fetcher.get(url, {HOST}, request_headers={'Authorization': 'Bearer ' + self.token})
                detail = loads(raw)
                if not isinstance(detail, dict):
                    raise SourceUnavailable('Invalid NAV detail object')
                ad = detail.get('ad_content')
                if not isinstance(ad, dict) or detail.get('status') != 'ACTIVE':
                    failures.append({'url': url, 'reason': 'Inactive or invalid NAV detail'}); continue
                employer = ad.get('employer', {})
                if not isinstance(employer, dict):
                    raise SourceUnavailable('Invalid NAV employer object')
                org = employer.get('orgnr')
                if not isinstance(org, str) or re.fullmatch('[0-9]{9}', org) is None:
                    failures.append({'url': url, 'reason': 'Missing exact employer organisation number'}); continue
                bridge_raw, bridge_receipt = self.fetcher.get(SUBUNIT + org, {'data.brreg.no'})
                bridge = loads(bridge_raw)
                if bridge.get('organisasjonsnummer') != org or bridge.get('overordnetEnhet') != subject:
                    failures.append({'url': url, 'reason': 'NAV employer belongs to another legal entity'}); continue
                pages.append((raw, receipt, bridge_raw, bridge_receipt))
            except SourceUnavailable as exc:
                failures.append({'url': url, 'availability': exc.availability, 'reason': str(exc)})
        return pages, failures


def check_nav(store, subject, sid):
    raw, receipt = store.open(sid)
    detail = loads(raw)
    if not isinstance(detail, dict) or not isinstance(detail.get('ad_content'), dict):
        raise ValueError('Invalid NAV source object')
    ad = detail.get('ad_content', {})
    if not isinstance(ad.get('employer'), dict):
        raise ValueError('Invalid NAV source employer')
    org = ad.get('employer', {}).get('orgnr')
    bridge_raw, bridge_receipt = store.open(receipt['employer_snapshot_id'])
    bridge = loads(bridge_raw)
    anchor_raw, anchor_receipt = store.open(receipt['legal_identity_snapshot_id'])
    anchor = loads(anchor_raw)
    if (receipt['organisation_number'] != subject or receipt['source_class'] != 'nav_jobs'
            or receipt['http_status'] != 200 or receipt['sha256'] != digest(raw)
            or urlsplit(receipt['effective_url']).hostname != HOST
            or not urlsplit(receipt['effective_url']).path.startswith('/api/v1/')
            or receipt['source_url'] != receipt['effective_url'] or detail.get('status') != 'ACTIVE'
            or bridge_receipt['source_url'] != SUBUNIT + str(org) or bridge_receipt['http_status'] != 200
            or bridge_receipt['effective_url'] != bridge_receipt['source_url']
            or bridge_receipt['source_class'] != 'brreg_job_employer'
            or bridge_receipt['sha256'] != digest(bridge_raw) or bridge_receipt['organisation_number'] != subject
            or bridge.get('organisasjonsnummer') != org or bridge.get('overordnetEnhet') != subject
            or anchor_receipt['source_class'] != 'brreg_entity' or anchor_receipt['http_status'] != 200
            or anchor_receipt['source_url'] != 'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject
            or anchor_receipt['sha256'] != digest(anchor_raw) or anchor.get('organisasjonsnummer') != subject):
        raise ValueError('NAV exact-employer source chain mismatch')
    cutoff = timestamp(receipt['retrieved_at'])
    posted, expires = timestamp(ad['published']), timestamp(ad['expires'])
    if posted > cutoff or expires < cutoff or not isinstance(ad.get('title'), str) or not ad['title'].strip():
        return []
    identity = ad['uuid']
    if (identity != detail.get('uuid') or not isinstance(identity, str)
            or re.fullmatch('[0-9a-f-]{36}', identity) is None
            or not receipt['effective_url'].endswith('/' + identity)):
        raise ValueError('NAV posting identity mismatch')
    values = [('job_posting', {'title': ad['title'], 'date_posted': ad['published'], 'posting_id': identity,
               'valid_through': ad['expires'], 'source_url': receipt['effective_url']}, ['ad_content', 'title'], None)]
    description = ad.get('employer', {}).get('description')
    if isinstance(description, str) and description.strip():
        statement = business_statement(description, anchor['navn'])
        if statement:
            values.append(('business_description', statement[0], ['ad_content', 'employer', 'description'], statement[1]))
    decisions = []
    for field, value, path, statement_index in values:
        family = 'jobs_dated_activity' if field == 'job_posting' else 'business_products'
        key = identity if field == 'job_posting' else org
        cid = claim_id(subject, field, 'nav_verified_employer', key)
        eid = sid + ':' + cid
        claim = {'claim_id': cid, 'field': field, 'value': value, 'scope': 'nav_verified_employer', 'family': family,
                 'item_key': key, 'period': None, 'availability': 'available', 'evidence_ids': [eid]}
        span = locate(raw, path)
        evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['source_url'], 'source_class': 'nav_jobs',
                    'source_origin': HOST, 'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw),
                    'claim_span': span, 'locator': {'path': path}, 'extraction_method': 'nav_subunit_bridge_v1'}
        if statement_index is not None:
            evidence['locator']['statement_index'] = statement_index
        decisions.append({'field': field, 'family': family, 'accepted': True, 'claim': claim, 'evidence': evidence})
    return decisions
