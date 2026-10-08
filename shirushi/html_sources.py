"""Bounded literal HTML claims and explicit website operator evidence."""
import re
from datetime import date
from html.parser import HTMLParser

from .snapshots import digest

BLOCKS = {'p', 'section', 'article', 'footer', 'address', 'li'}
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
        style = re.sub(r'\s+', '', attrs.get('style', '').lower())
        hidden = (any(x['hidden'] for x in self.stack) or tag in {'script', 'style', 'template', 'noscript'}
                  or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or 'display:none' in style or 'visibility:hidden' in style)
        if tag in VOID:
            self.handle_data(' ')
            return
        self.stack.append({'tag': tag, 'start': self.position(), 'hidden': hidden, 'parts': []})

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
                self.blocks.append(dict(tag=tag, start=block['start'], end=end + 1,
                                        text=' '.join(''.join(block['parts']).split())))


def names(text, name):
    return bool(name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I))


def org_numbers(text):
    # Explicit organisation-number labels; bare phone numbers cannot prove identity.
    pattern = r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organisation\s+number|organization\s+number)\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])'
    return {re.sub(r'[^0-9]', '', value) for value in re.findall(pattern, text, re.I)}


def operator_proof(raw, subject, legal_name):
    for block in Sections(raw).blocks:
        text = block['text']
        operator = re.search(r'copyright|\u00a9|(?:website|site|nettsted).{0,40}(?:operated|owned|drives|eies)|utgiver', text, re.I)
        if (block['tag'] in {'footer', 'p', 'address'} and operator and names(text, legal_name)
                and org_numbers(text) == {subject} and len(text) <= 1500):
            return {k: block[k] for k in ('start', 'end', 'text')}
    return None


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
