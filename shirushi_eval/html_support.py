"""Independent HTML interpretation; never imports application extraction."""
import hashlib
import json
import re
from datetime import date
from html.parser import HTMLParser


class Document(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode('utf-8')
        self.lines = self.source.split('\n')
        self.parents, self.nodes = [], []
        self.feed(self.source)

    def source_position(self):
        line, col = self.getpos()
        return sum(len(part) + 1 for part in self.lines[:line - 1]) + col

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        hidden = any(node['hidden'] for node in self.parents)
        hidden = hidden or tag in ('style', 'script', 'template', 'noscript') or 'hidden' in attrs
        hidden = hidden or attrs.get('aria-hidden') == 'true' or bool(re.search(
            r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style', ''), re.I))
        if tag in ('br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'):
            self.handle_data(' ')
            return
        self.parents.append({'tag': tag, 'start': self.source_position(), 'text': '', 'hidden': hidden})

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


def legal_operator(raw, subject, name):
    for node in Document(raw).nodes:
        if node['tag'] not in ('footer', 'address', 'p') or len(node['text']) > 1500 or not name:
            continue
        value = node['text']
        if not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', value, re.I):
            continue
        numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+number)\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', value, re.I)
        numbers = {re.sub(r'\D', '', number) for number in numbers}
        if numbers != {subject}:
            continue
        if re.search(r'copyright|\u00a9|(?:website|site|nettsted).{0,40}(?:operated|owned|drives|eies)|utgiver', value, re.I):
            return node
    return None


def audit_html(subject, claim, item, receipt, raw, legal_name, ownership_raw):
    proof = legal_operator(ownership_raw, subject, legal_name)
    if proof is None:
        raise ValueError('Audit HTML lacks legal operator evidence')
    location = item['locator']
    if (type(location.get('html_start')) is not int or type(location.get('html_end')) is not int
            or location.get('legal_name') != legal_name):
        raise ValueError('Audit HTML locator mismatch')
    document = Document(raw)
    node = next((node for node in document.nodes if node['start'] == location['html_start']
                 and node['end'] == location['html_end']), None)
    if node is None or document.source[node['start']:node['end']] != item['claim_span']:
        raise ValueError('Audit HTML span is hidden, malformed or misplaced')
    text = node['text']
    field = claim['field']
    if field == 'verified_website':
        if node != legal_operator(raw, subject, legal_name) or location.get('operator') is not True:
            raise ValueError('Audit website span lacks operator evidence')
        expected = 'https://' + receipt['declared_host'] + '/'
        family, key = 'website_owned_profiles', None
    else:
        if not 10 <= len(text) <= 2000 or not re.search(r'(?<!\w)' + re.escape(legal_name) + r'(?!\w)', text, re.I):
            raise ValueError('Audit HTML fact does not identify its subject')
        if field == 'product_service':
            if node['tag'] not in ('p', 'li') or not re.search(re.escape(legal_name) + r'\s+(?:offers|provides|supplies|manufactures|produces|tilbyr|leverer|produserer)\b', text, re.I):
                raise ValueError('Audit unsupported product/service attribution')
            expected, family, key = text, 'business_products', hashlib.sha256(text.encode()).hexdigest()
        elif field == 'public_activity':
            dates = re.findall(r'(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])', text)
            if (node['tag'] not in ('p', 'article') or len(dates) != 1 or not re.search(
                    re.escape(legal_name) + r'\s+(?:launched|opened|announced|signed|lanserte|\u00e5pnet|kunngjorde|signerte)\b', text, re.I)
                    or date.fromisoformat(dates[0]) > date.fromisoformat(receipt['retrieved_at'][:10])):
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
