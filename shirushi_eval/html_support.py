"""Independent HTML interpretation; never imports application extraction."""
import hashlib
import json
import re
from functools import lru_cache
from datetime import date
from html.parser import HTMLParser


class Document(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode('utf-8')
        self.lines = self.source.split('\n')
        self.offsets = [0]
        for line in self.lines[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.parents, self.nodes = [], []
        self.feed(self.source)

    def source_position(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        hidden = any(node['hidden'] for node in self.parents)
        hidden = hidden or tag in ('style', 'script', 'template', 'noscript') or 'hidden' in attrs
        hidden = hidden or attrs.get('aria-hidden') == 'true' or bool(re.search(
            r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style') or '', re.I))
        if tag in ('br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'):
            self.handle_data(' ')
            return
        self.parents.append({'tag': tag, 'start': self.source_position(), 'text': '', 'hidden': hidden, 'attrs': attrs})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, value):
        if self.parents and not self.parents[-1]['hidden']:
            for node in self.parents:
                node['text'] += value

    def handle_endtag(self, tag):
        if not self.parents or self.parents[-1]['tag'] != tag:
            return
        node = self.parents.pop()
        end = self.source.find('>', self.source_position())
        if end >= 0 and not node['hidden']:
            node['end'] = end + 1
            node['text'] = ' '.join(node['text'].split())
            self.nodes.append(node)


@lru_cache(maxsize=4)
def document(raw):
    return Document(raw)


def legal_operator(raw, subject, name, registry_url='', page_url=''):
    for node in document(raw).nodes:
        if node['tag'] not in ('footer', 'address', 'p') or len(node['text']) > 1500 or not name:
            continue
        value = node['text']
        if not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', value, re.I):
            continue
        numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', value, re.I)
        numbers = {re.sub(r'\D', '', number) for number in numbers}
        if numbers == {subject} and re.search(r'(?:copyright|\u00a9)\s*(?:[0-9]{4}[\s.,-]*)?(?:by\s+)?' + re.escape(name) + r'(?!\w)|'
            r'(?:website|site|nettsted).{0,40}(?:operated|owned|drives|eies).{0,30}' + re.escape(name) + r'(?!\w)|'
            r'utgiver\s*:?\s*' + re.escape(name) + r'(?!\w)', value, re.I):
            return node
        if numbers == {subject} and seller_contract(value, name):
            return node
        if registry_url and page_url and node['tag'] == 'p':
            from urllib.parse import urlsplit
            registered = urlsplit(registry_url if '://' in registry_url else 'https://' + registry_url).hostname
            actual = urlsplit(page_url).hostname
            if not registered or not actual or registered.removeprefix('www.') != actual.removeprefix('www.'):
                continue
            # Independently reconstruct the narrow named operator statement.
            prefix = re.escape(name) + r'(?:\s*\([^)]{1,160}\))?(?:\s*,?\s+ved\s+[^,.]{1,80},?)?\s+er\s+'
            controller = re.search(r'(?<!\w)' + prefix + r'behandlingsansvarlig\s+for\s+[^.]{1,400}'
                r'\bdrift\s+og\s+vedlikehold\s+av\s+(?:www\.)?' + re.escape(actual.removeprefix('www.')) +
                r'(?![\w-]|\.[\w-])', value, re.I)
            if controller and not re.search(r'\b(?:ikke|not|vegne|databehandler|processor|kunde\w*)\b', value, re.I):
                all_numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])',
                    ' '.join(n['text'] for n in document(raw).nodes), re.I)
                if not {re.sub(r'\D', '', number) for number in all_numbers} - {subject}:
                    return node
    return None


def seller_contract(value, name):
    return bool(re.search(r'\b(?:terms|conditions|vilk\u00e5r|avtale)\b', value, re.I)
        and re.search(r'\b(?:customers?|purchase|orders?|seller|kund|kj\u00f8p|selger)\w*\b', value, re.I)
        and re.search(r'\b(?:between|mellom)\s+' + re.escape(name) + r'(?!\w).{0,300}\b'
            r'(?:and\s+(?:(?:their|its|our|the)\s+)?customers?|og\s+(?:(?:deres|v\u00e5re|sine)\s+)?kund\w*)\b', value, re.I))


def audit_html(subject, claim, item, receipt, raw, legal_name, ownership_raw, registry_url='', ownership_url=''):
    proof = legal_operator(ownership_raw, subject, legal_name, registry_url, ownership_url)
    if proof is None:
        raise ValueError('Audit HTML lacks legal operator evidence')
    location = item['locator']
    if (type(location.get('html_start')) is not int or type(location.get('html_end')) is not int
            or location.get('legal_name') != legal_name):
        raise ValueError('Audit HTML locator mismatch')
    page = document(raw)
    node = next((node for node in page.nodes if node['start'] == location['html_start']
                 and node['end'] == location['html_end']), None)
    if node is None or page.source[node['start']:node['end']] != item['claim_span']:
        raise ValueError('Audit HTML span is hidden, malformed or misplaced')
    text = node['text']
    field = claim['field']
    if field == 'verified_website':
        if node != legal_operator(raw, subject, legal_name, registry_url, receipt['effective_url']) or location.get('operator') is not True:
            raise ValueError('Audit website span lacks operator evidence')
        path = '/'
        if seller_contract(text, legal_name):
            from urllib.parse import urlsplit
            path = urlsplit(receipt['effective_url']).path.rsplit('/', 1)[0] + '/'
        expected = 'https://' + receipt['declared_host'] + path
        family, key = 'website_owned_profiles', None
    else:
        if not 10 <= len(text) <= 2000 or not re.search(r'(?<!\w)' + re.escape(legal_name) + r'(?!\w)', text, re.I):
            raise ValueError('Audit HTML fact does not identify its subject')
        if field == 'business_description':
            if node['tag'] != 'p' or not re.search(r'(?<!\w)' + re.escape(legal_name) +
                    r'\s+er\s+(?:en|et)\s+(?:(?:moderne|norsk|norske|ledende|lokal|lokalt|internasjonalt)\s+){0,3}'
                    r'(?:konsulentselskap|konsulentfirma|produksjonsbedrift|produsent|leverand\u00f8r|industribedrift)\b', text, re.I):
                raise ValueError('Audit unsupported company definition')
            expected, family, key = text, 'business_products', None
        elif field == 'product_service':
            if node['tag'] not in ('p', 'li') or not re.search(re.escape(legal_name) + r'\s+(?:offers|provides|supplies|manufactures|produces|tilbyr|leverer|produserer)\b', text, re.I):
                raise ValueError('Audit unsupported product/service attribution')
            expected, family, key = text, 'business_products', hashlib.sha256(text.encode()).hexdigest()
        elif field == 'public_activity':
            dates = re.findall(r'(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])', text)
            if (node['tag'] not in ('p', 'article') or len(dates) != 1 or not re.search(
                    re.escape(legal_name) + r'\s+(?:launched|opened|announced|signed|lanserte|\u00e5pnet|kunngjorde|signerte)\b', text, re.I)
                    or date.fromisoformat(dates[0]) > date.fromisoformat(receipt.get('evaluation_cutoff', receipt['retrieved_at'])[:10])):
                raise ValueError('Audit unsupported dated activity')
            expected = {'statement': text, 'activity_date': dates[0], 'source_url': receipt['effective_url']}
            family = 'jobs_dated_activity'
            key = hashlib.sha256((receipt['effective_url'] + '\n' + text).encode()).hexdigest()
        else:
            raise ValueError('Audit unsupported HTML claim')
    encoded = json.dumps([subject, field, 'company_owned_html', key, None], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if (claim['value'] != expected or claim.get('family') != family or claim.get('item_key') != key
            or claim.get('period') is not None or claim.get('scope') != 'company_owned_html'
            or claim.get('claim_id') != hashlib.sha256(encoded).hexdigest()):
        raise ValueError('Audit HTML value or canonical identity mismatch')


def audit_catalogue(subject, claim, item, receipt, raw, legal_name, ownership_raw, ownership_receipt):
    from urllib.parse import urljoin, urlsplit
    owner = legal_operator(ownership_raw, subject, legal_name)
    if owner is None or not seller_contract(owner['text'], legal_name):
        raise ValueError('Catalogue lacks verified seller contract')
    prefix = urlsplit(ownership_receipt['effective_url']).path.rsplit('/', 1)[0] + '/'
    loc = item['locator']
    page = document(raw)
    node = next((n for n in page.nodes if n['start'] == loc.get('html_start') and n['end'] == loc.get('html_end')), None)
    if node is None or node['tag'] != 'a' or loc.get('catalogue') is not True or page.source[node['start']:node['end']] != item['claim_span']:
        raise ValueError('Catalogue source locator mismatch')
    link = urljoin(receipt['effective_url'], node['attrs'].get('href', ''))
    parts = urlsplit(link)
    page = urlsplit(receipt['effective_url'])
    if (parts.scheme != 'https' or parts.hostname != page.hostname or parts.username or parts.password
            or parts.port not in (None, 443) or not page.path.startswith(prefix) or not parts.path.startswith(prefix)
            or not re.search(r'/(?:products?|produkter)/[^/]+/?$', parts.path, re.I)
            or not 4 <= len(node['text']) <= 200
            or node['text'].lower() in {'products', 'produkter', 'les mer', 'read more', 'shop now'}):
        raise ValueError('Catalogue link escapes seller scope')
    link = parts._replace(fragment='').geturl()
    value = {'name': node['text'], 'source_url': link}
    encoded = json.dumps([subject, 'product_service', 'company_owned_catalogue', link, None], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if (claim['field'] != 'product_service' or claim['value'] != value or claim.get('family') != 'business_products'
            or claim.get('scope') != 'company_owned_catalogue' or claim.get('item_key') != link
            or claim.get('period') is not None or claim['claim_id'] != hashlib.sha256(encoded).hexdigest()):
        raise ValueError('Catalogue value or canonical identity mismatch')
