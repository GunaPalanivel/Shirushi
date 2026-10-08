"""Conservative company-owned JSON-LD facts; no inferred legal ownership."""
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .claims import claim_id
from .contracts import loads
from .fetch import safe_url
from .snapshots import digest


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.scripts, self.links, self.text = [], [], []
        self.current = None
        self.feed(raw.decode('utf-8'))
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.current = ''
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])

    def handle_data(self, data):
        if self.current is not None:
            self.current += data
        else:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(self.current)
            self.current = None


def identified(node, subject):
    if not isinstance(node, dict):
        return False
    values = [node.get(k) for k in ('identifier', 'taxID', 'vatID')]
    for value in values:
        if isinstance(value, dict):
            value = value.get('value')
        if isinstance(value, str) and re.fullmatch(r'(?:NO\s*)?' + subject + r'(?:\s*MVA)?', value.replace(' ', ''), re.I):
            return True
    return False


def nodes(value, path=()):
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from nodes(item, path + (index,))
    elif isinstance(value, dict):
        yield path, value
        if '@graph' in value:
            yield from nodes(value['@graph'], path + ('@graph',))


def page_values(raw, subject, url):
    page = Page(raw)
    # Only explicit machine-readable legal identifiers authorize publication.
    for script_index, text in enumerate(page.scripts):
        try:
            parsed = loads(text)
        except ValueError:
            continue
        for path, node in nodes(parsed):
            kind = node.get('@type')
            kinds = kind if isinstance(kind, list) else [kind]
            if 'Organization' in kinds and identified(node, subject):
                value = node.get('description')
                if isinstance(value, str) and value.strip():
                    yield 'business_description', value, 'business_products', None, script_index, path
                declared = node.get('url')
                if isinstance(declared, str):
                    try:
                        declared = safe_url(declared, {urlsplit(url).hostname})
                    except ValueError:
                        continue
                    yield 'verified_website', declared, 'website_owned_profiles', None, script_index, path
            elif 'JobPosting' in kinds and identified(node.get('hiringOrganization'), subject):
                title, posted = node.get('title'), node.get('datePosted')
                try:
                    posted_date = date.fromisoformat(posted[:10])
                    end = node.get('validThrough')
                    if posted_date > date.today() or (end and date.fromisoformat(end[:10]) < date.today()):
                        continue
                except (ValueError, TypeError):
                    continue
                identity = node.get('identifier')
                if isinstance(identity, dict):
                    identity = identity.get('value')
                if not isinstance(title, str) or not title.strip() or not isinstance(identity, str) or not identity.strip():
                    continue
                yield ('job_posting', {'title': title, 'date_posted': posted, 'posting_id': identity,
                                      'valid_through': end, 'source_url': url},
                       'jobs_dated_activity', identity, script_index, path)
            elif any(k in ('NewsArticle', 'Article') for k in kinds) and identified(node.get('about'), subject):
                title, published = node.get('headline'), node.get('datePublished')
                try:
                    if date.fromisoformat(published[:10]) > date.today():
                        continue
                except (ValueError, TypeError):
                    continue
                if isinstance(title, str) and title.strip():
                    yield ('public_activity', {'headline': title, 'published_at': published, 'source_url': url},
                           'jobs_dated_activity', url, script_index, path)


def check_web(store, subject, sid):
    raw, receipt = store.open(sid)
    if (receipt['organisation_number'] != subject or receipt['source_class'] != 'company_owned'
            or receipt['http_status'] != 200 or receipt['sha256'] != digest(raw)
            or receipt.get('robots_checked') is not True
            or receipt.get('declared_host') != urlsplit(receipt['effective_url']).hostname):
        raise ValueError('Company page receipt mismatch')
    anchor_raw, anchor_receipt = store.open(receipt['ownership_anchor_snapshot_id'])
    anchor = loads(anchor_raw)
    declared = anchor.get('hjemmeside', '')
    declared = safe_url(declared if '://' in declared else 'https://' + declared)
    if (anchor_receipt['source_class'] != 'brreg_entity' or anchor.get('organisasjonsnummer') != subject
            or anchor_receipt['source_url'] != 'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject
            or urlsplit(declared).hostname != receipt['declared_host']):
        raise ValueError('Website discovery is not anchored to this company')
    decisions = []
    scripts = Page(raw).scripts
    for field, value, family, item, script, path in page_values(raw, subject, receipt['effective_url']):
        identity = claim_id(subject, field, 'company_owned_structured', item)
        eid = sid + ':' + identity
        claim = {'claim_id': identity, 'field': field, 'value': value, 'scope': 'company_owned_structured',
                 'family': family, 'item_key': item, 'period': None,
                 'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
        evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'],
                    'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                    'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw),
                    'claim_span': scripts[script], 'locator': {'script_index': script, 'node_path': list(path)},
                    'extraction_method': 'exact_identifier_jsonld_v1'}
        decisions.append({'field': field, 'family': family, 'accepted': True, 'claim': claim, 'evidence': evidence})
    return decisions


def page_links(raw, url):
    result = []
    for link in Page(raw).links:
        candidate = urljoin(url, link)
        if not re.search(r'career|job|stilling|ledig|news|nyhet|press|about|om-oss|kontakt', candidate, re.I):
            continue
        try:
            candidate = safe_url(candidate, {urlsplit(url).hostname})
        except ValueError:
            continue
        if candidate != url and candidate not in result:
            result.append(candidate)
    return result
