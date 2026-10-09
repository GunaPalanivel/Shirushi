"""Bounded literal HTML claims and explicit website operator evidence."""
import re
from datetime import date
from html.parser import HTMLParser

from .snapshots import digest

BLOCKS = {'p', 'section', 'article', 'footer', 'address', 'li', 'a'}
VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'}


class Sections(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode('utf-8')
        self.offsets, self.stack, self.blocks = [0], [], []
        for line in self.source.split('\n')[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.feed(self.source)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = re.sub(r'\s+', '', (attrs.get('style') or '').lower())
        hidden = (any(x['hidden'] for x in self.stack) or tag in {'script', 'style', 'template', 'noscript'}
                  or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or 'display:none' in style or 'visibility:hidden' in style)
        if tag in VOID:
            self.handle_data(' ')
            return
        self.stack.append({'tag': tag, 'start': self.position(), 'hidden': hidden, 'parts': [], 'attrs': attrs})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not any(x['hidden'] for x in self.stack):
            for block in self.stack:
                block['parts'].append(data)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1]['tag'] != tag:
            return  # Malformed/implicitly closed blocks do not authorize claims.
        block = self.stack.pop()
        if tag in BLOCKS and not block['hidden']:
            end = self.source.find('>', self.position())
            if end >= 0:
                self.blocks.append(dict(tag=tag, start=block['start'], end=end + 1, attrs=block['attrs'],
                                        text=' '.join(''.join(block['parts']).split())))


def names(text, name):
    return bool(name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I))


def org_numbers(text):
    # Explicit organisation-number labels; bare phone numbers cannot prove identity.
    pattern = r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])'
    return {re.sub(r'[^0-9]', '', value) for value in re.findall(pattern, text, re.I)}


def operator_proof(raw, subject, legal_name, registry_url='', page_url=''):
    blocks = Sections(raw).blocks
    for block in blocks:
        text = block['text']
        operator = re.search(r'(?:copyright|\u00a9)\s*(?:[0-9]{4}[\s.,-]*)?(?:by\s+)?' + re.escape(legal_name) + r'(?!\w)|'
            r'(?:website|site|nettsted).{0,40}(?:operated|owned|drives|eies).{0,30}' + re.escape(legal_name) + r'(?!\w)|'
            r'utgiver\s*:?\s*' + re.escape(legal_name) + r'(?!\w)', text, re.I)
        seller = (re.search(r'\b(?:terms|conditions|vilk\u00e5r|avtale)\b', text, re.I)
                  and re.search(r'\b(?:customers?|purchase|orders?|seller|kund|kj\u00f8p|selger)\w*\b', text, re.I)
                  and re.search(r'\b(?:between|mellom)\s+' + re.escape(legal_name) + r'(?!\w).{0,300}\b'
                      r'(?:and\s+(?:(?:their|its|our|the)\s+)?customers?|og\s+(?:(?:deres|v\u00e5re|sine)\s+)?kund\w*)\b', text, re.I))
        if (block['tag'] in {'footer', 'p', 'address'} and (operator or seller) and names(text, legal_name)
                and org_numbers(text) == {subject} and len(text) <= 1500):
            return dict({k: block[k] for k in ('start', 'end', 'text')}, kind='seller_terms' if seller else 'operator')
        # A controller label alone is insufficient. The registry must name this
        # domain and the named company must explicitly operate that same domain.
        if block['tag'] == 'p' and len(text) <= 1500 and registry_url and page_url and names(text, legal_name):
            from urllib.parse import urlsplit
            from .fetch import website_candidate, website_hosts
            try:
                registered_host = urlsplit(website_candidate(registry_url)).hostname
                actual_host = urlsplit(page_url).hostname
            except ValueError:
                continue
            if actual_host not in website_hosts(registered_host):
                continue
            domain = actual_host.removeprefix('www.')
            statement = re.search(r'(?<!\w)' + re.escape(legal_name) +
                r'(?:\s*\([^)]{1,160}\))?(?:\s*,?\s+ved\s+[^,.]{1,80},?)?\s+er\s+'
                r'behandlingsansvarlig\s+for\s+[^.]{1,400}\bdrift\s+og\s+vedlikehold\s+av\s+'
                r'(?:www\.)?' + re.escape(domain) + r'(?![\w-]|\.[\w-])', text, re.I)
            # A sentence-ending dot is allowed, but not a domain suffix.
            if statement and not re.search(r'\b(?:ikke|not|vegne|databehandler|processor|kunde\w*)\b', text, re.I):
                if not any(org_numbers(section['text']) - {subject} for section in blocks):
                    return dict({k: block[k] for k in ('start', 'end', 'text')}, kind='registry_operator')
    return None


def catalogue_values(raw, url):
    """Literal linked offers, only used under a verified seller's path scope."""
    from urllib.parse import urljoin, urlsplit
    from .fetch import safe_url
    seen = set()
    for block in Sections(raw).blocks:
        if block['tag'] != 'a' or not 4 <= len(block['text']) <= 200:
            continue
        try:
            link = safe_url(urljoin(url, block['attrs'].get('href', '')), {urlsplit(url).hostname})
        except ValueError:
            continue
        if not re.search(r'/(?:products?|produkter)/[^/]+/?$', urlsplit(link).path, re.I) or link in seen:
            continue
        if block['text'].lower() in {'products', 'produkter', 'les mer', 'read more', 'shop now'}:
            continue
        if len(seen) >= 10:
            break  # Spend the remaining run budget on uncovered companies.
        seen.add(link)
        yield ('product_service', {'name': block['text'], 'source_url': link}, 'business_products', link,
               raw.decode('utf-8')[block['start']:block['end']],
               {'html_start': block['start'], 'html_end': block['end'], 'catalogue': True})


def html_values(raw, subject, legal_name, url, cutoff):
    """Facts explicitly name the target; legal footer alone never attributes content."""
    seen = set()
    for block in Sections(raw).blocks:
        text = block['text']
        if not 10 <= len(text) <= 2000 or not names(text, legal_name):
            continue
        if org_numbers(text) - {subject}:
            continue
        span = raw.decode('utf-8')[block['start']:block['end']]
        locator = {'html_start': block['start'], 'html_end': block['end'], 'legal_name': legal_name}
        if block['tag'] == 'p' and re.search(r'(?<!\w)' + re.escape(legal_name) +
                r'\s+er\s+(?:en|et)\s+(?:(?:moderne|norsk|norske|ledende|lokal|lokalt|internasjonalt)\s+){0,3}'
                r'(?:konsulentselskap|konsulentfirma|produksjonsbedrift|produsent|leverand\u00f8r|industribedrift)\b', text, re.I):
            if 'business_description' not in seen:
                seen.add('business_description')
                yield 'business_description', text, 'business_products', None, span, locator
        if block['tag'] in {'p', 'li'} and re.search(re.escape(legal_name) + r'\s+(?:offers|provides|supplies|manufactures|produces|tilbyr|leverer|produserer)\b', text, re.I):
            key = digest(text.encode())
            if ('product_service', key) not in seen:
                seen.add(('product_service', key))
                yield 'product_service', text, 'business_products', key, span, locator
        # Dated activity must explicitly describe the target's concrete action;
        # an undated news index or a page modification date is insufficient.
        if block['tag'] in {'article', 'p'} and re.search(re.escape(legal_name) + r'\s+(?:launched|opened|announced|signed|lanserte|\u00e5pnet|kunngjorde|signerte)\b', text, re.I):
            dates = re.findall(r'(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])', text)
            if len(dates) != 1:
                continue
            try:
                published = date.fromisoformat(dates[0])
                if published > cutoff:
                    continue
            except ValueError:
                continue
            value = {'statement': text, 'activity_date': dates[0], 'source_url': url}
            key = digest((url + '\n' + text).encode())
            if ('public_activity', key) not in seen:
                seen.add(('public_activity', key))
                yield 'public_activity', value, 'jobs_dated_activity', key, span, locator
