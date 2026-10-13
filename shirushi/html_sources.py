"""Bounded literal HTML claims and explicit website operator evidence."""
import re
from datetime import date
from html.parser import HTMLParser

from .public_suffixes import PATH_TENANT_HOSTS, PUBLIC_SECTOR_SUFFIXES, PUBLIC_SUFFIXES, SHARED_DOMAINS
from .snapshots import digest

HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
BLOCKS = {'p', 'section', 'article', 'footer', 'address', 'li', 'a'} | HEADINGS
VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'}


class Sections(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode('utf-8')
        self.offsets, self.stack, self.blocks, self.nodes = [0], [], [], []
        for line in self.source.split('\n')[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.feed(self.source)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'blockquote', 'q'}:
            for block in self.stack:
                block['quoted'] = True
        style = re.sub(r'\s+', '', (attrs.get('style') or '').lower())
        hidden = (any(x['hidden'] for x in self.stack) or tag in {'script', 'style', 'template', 'noscript'}
                  or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or 'display:none' in style or 'visibility:hidden' in style)
        if tag in VOID:
            self.handle_data(' ')
            return
        quoted = tag in {'blockquote', 'q'} or any(x['tag'] in {'blockquote', 'q'} for x in self.stack)
        self.stack.append({'tag': tag, 'start': self.position(), 'hidden': hidden, 'quoted': quoted,
                           'parts': [], 'attrs': attrs})

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
        if not block['hidden'] and not block['quoted']:
            end = self.source.find('>', self.position())
            if end >= 0:
                node = dict(tag=tag, start=block['start'], end=end + 1, attrs=block['attrs'],
                            text=' '.join(''.join(block['parts']).split()),
                            ancestors=tuple(parent['tag'] for parent in self.stack))
                self.nodes.append(node)
                if tag in BLOCKS:
                    self.blocks.append(node)


def names(text, name):
    return bool(name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I))


def org_numbers(text):
    # Explicit organisation-number labels; bare phone numbers cannot prove identity.
    pattern = r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])'
    return {re.sub(r'[^0-9]', '', value) for value in re.findall(pattern, text, re.I)}


# A legal contact block proves nothing on pages whose purpose is to describe other companies.
DIRECTORY_HOSTS = ('proff.no', 'gulesider.no', '1881.no', 'brreg.no', 'purehelp.no', 'bisnode.no', 'bisnode.com',
                   'creditsafe.com', 'creditsafe.no', 'dnb.com', 'dnb.no', 'linkedin.com', 'facebook.com',
                   'instagram.com', 'twitter.com', 'x.com', 'youtube.com', 'google.com', 'mittanbud.no',
                   'regnskapstall.no', 'forretning.no', 'ratsit.se', 'allabolag.se', 'opencorporates.com',
                   'crunchbase.com', 'finn.no', 'nav.no', 'wikipedia.org', 'wikidata.org', 'mynewsdesk.com',
                   'tripadvisor.com', 'yelp.com', 'trustpilot.com')
LEGAL_FORMS = r'(?:as|asa|ans|da|nuf|sa|se|ab|a/s|oy|ltd|inc|llc|gmbh|bv|plc)'
OTHER_ENTITY = re.compile(r"(?<![\w&])(?:[\w&.'-]+\s+){1,5}(?:AS|ASA|ANS|DA|NUF|SA|SE|AB|A/S|Oy|Ltd|Inc|LLC|GmbH|BV|PLC"
                          r"|ApS|AG|ENK|KS|IKS|BA|SARL|SAS|NV)(?![\w/])")
# Relationship, negation, quotation and agency-credit words: the block would not describe the site operator.
BLOCK_CONTEXT = re.compile(r'\b(?:customers?|clients?|kunde\w*|suppliers?|leverand\w*|partners?|samarbeid\w*|referanse\w*|'
    r'references?|testimonials?|sponsor\w*|members?|medlem\w*|parent|subsidiar\w*|morselskap|datterselskap|konsern\w*|'
    r'ikke|not|hvis|dersom|if|behalf|vegne|formerly|tidligere|fka|c/o|webdesign\w*|design\w*|utviklet|laget|levert|'
    r'powered|developed|built|created|hosted|hosting|videreutvikling|regnskapsf\u00f8rer|revisor|accountant|agency|'
    r'byr\u00e5|eier|eies|eid|kj\wpt\w*|oppkj\w+|acquired|faktura\w*|fakturer\w*|invoice\w*|arbeidsgiver|employer|'
    r'forhandler|dealer|reseller|leietaker|tenant|pressekontakt|konkurs\w*|bankrupt\w*|regnskapskontor|'
    r'prosjekt\w*|project|oppdrag\w*)\b', re.I)
BLOCK_QUOTES = re.compile(r'["\u201c\u201d\u00ab\u00bb?]')
CONTEXT_WINDOW = 80


def ascii_fold(value):
    from unicodedata import combining, normalize
    value = value.lower().replace('\u00e6', 'ae').replace('\u00f8', 'o').replace('\u00e5', 'a')
    return ''.join(c for c in normalize('NFKD', value) if not combining(c))


def name_stem(value):
    """Lower-case ASCII stem of a company or host label: Norwegian letters folded, legal form and punctuation removed."""
    return re.sub(r'[^a-z0-9]', '', re.sub(r'(?<![\w/])' + LEGAL_FORMS + r'(?![\w/])', ' ', ascii_fold(value)))


NAME_TIE_TLDS = {'no', 'com', 'org', 'net', 'eu'}


def registrable(domain):
    """Registrable domain, or None when the name is a public suffix (checked before any equality)."""
    labels = domain.lower().removeprefix('www.').split('.')
    if len(labels) < 2 or '.'.join(labels) in PUBLIC_SUFFIXES:
        return None
    if '.'.join(labels[-2:]) in PUBLIC_SUFFIXES:
        return '.'.join(labels[-3:]) if len(labels) >= 3 else None
    return '.'.join(labels[-2:])


def denied_host(host):
    """Directories, platforms with path tenants, shared hosting and public-sector registrations never prove a site."""
    own = registrable(host)
    return (any(host == d or host.endswith('.' + d) for d in DIRECTORY_HOSTS + PATH_TENANT_HOSTS)
            or own is None or own in SHARED_DOMAINS
            or any(host.endswith('.' + suffix) for suffix in PUBLIC_SECTOR_SUFFIXES))


def name_domain_tie(legal_name, site):
    """The bare registrable host (no further subdomain, ASCII letters, ordinary TLD) is the legal name."""
    own = registrable(site)
    if own is None or own != site or own in SHARED_DOMAINS or own.rsplit('.', 1)[1] not in NAME_TIE_TLDS:
        return False
    label = own.split('.')[0]
    return (re.fullmatch(r'[a-z0-9-]+', ascii_fold(label)) is not None and len(name_stem(legal_name)) >= 4
            and name_stem(legal_name) == name_stem(label))


def same_site(mail_domain, host):
    """A mailbox ties a block to the host only through the same ordinary registrable domain."""
    own = registrable(mail_domain)
    return own is not None and own == registrable(host) and own not in SHARED_DOMAINS


def related_context(rest, subject):
    """Relationship words close to the legal-name marker or to the subject's number."""
    spans = [m.span() for m in re.finditer('\u2022', rest)]
    spans += [m.span() for m in re.finditer(r'(?<![0-9])' + r'[ .]?'.join((subject[:3], subject[3:6], subject[6:]))
                                            + r'(?![0-9])', rest)]
    return any(BLOCK_CONTEXT.search(rest[max(0, a - CONTEXT_WINDOW):a] + ' ' + rest[b:b + CONTEXT_WINDOW])
               for a, b in spans)


def legal_contact_block(document, subject, legal_name, page_url):
    """The page's own bounded block names the exact legal subject, its number and a tie to this site."""
    from urllib.parse import urlsplit
    try:
        host = (urlsplit(page_url).hostname or '').lower()
    except ValueError:
        return None
    if not host or not legal_name or denied_host(host):
        return None
    site = host.removeprefix('www.')
    name_tie = name_domain_tie(legal_name, site)
    for node in document.nodes:
        text = node['text']
        if (node['tag'] not in {'footer', 'address', 'p', 'li', 'div', 'td', 'span'}
                or len(text) > (1500 if node['tag'] in {'footer', 'address'} else 600)
                or not names(text, legal_name) or org_numbers(text) != {subject}):
            continue
        rest = re.sub(r'(?<!\w)' + re.escape(legal_name) + r'(?!\w)', '\u2022', text, flags=re.I)
        if (BLOCK_QUOTES.search(rest) or related_context(rest, subject)
                or OTHER_ENTITY.search(rest.replace('\u2022', ' '))):
            continue
        source = document.source[node['start']:node['end']]
        # Only a mailbox at the site's own domain or the name~domain equality ties a block to its site;
        # links and URL text to the own host are never evidence, any listing can carry them.
        mail_domains = [m.lower() for m in re.findall(r'[\w.%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w.-]*@)', text)]
        mail_domains += [m.lower() for m in re.findall(
            r'href\s*=\s*["\']?mailto:[^"\'>\s?@]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w.-]*@)', source, re.I)]
        if name_tie or any(same_site(domain, site) for domain in mail_domains):
            return {'start': node['start'], 'end': node['end'], 'text': text, 'kind': 'legal_contact_block'}
    return None


def operator_proof(raw, subject, legal_name, registry_url='', page_url=''):
    document = Sections(raw)
    blocks = document.blocks
    for block in blocks:
        text = block['text']
        operator = re.search(r'(?:copyright|\u00a9)\s*(?:[0-9]{4}[\s.,-]*)?(?:by\s+)?' + re.escape(legal_name) + r'(?!\w)|'
            r'(?:website|site|nettsted).{0,40}(?:operated|owned|drives|eies).{0,30}' + re.escape(legal_name) + r'(?!\w)|'
            r'\butgiver\s*:?\s*' + re.escape(legal_name) + r'(?!\w)', text, re.I)
        shop_operator = (re.search(r'(?:^|[.!?]\s+)' + re.escape(legal_name) +
            r'\s+(?:som\s+)?driver\s+denne\s+nettbutikken\b', text, re.I)
            and re.search(r'\b(?:selger\w*|kj\u00f8psvilk\u00e5r)\b', text, re.I)
            and '?' not in text
            and not re.search(r'\b(?:ikke|not|nei|hvis|dersom|if|unless|would|could|p\u00e5\s+vegne|on\s+behalf|databehandler|processor|hosting|teknisk)\b', text, re.I))
        seller = (re.search(r'\b(?:terms|conditions|vilk\u00e5r|avtale)\b', text, re.I)
                  and re.search(r'\b(?:customers?|purchase|orders?|seller|kund|kj\u00f8p|selger)\w*\b', text, re.I)
                  and re.search(r'\b(?:between|mellom)\s+' + re.escape(legal_name) + r'(?!\w).{0,300}\b'
                      r'(?:and\s+(?:(?:their|its|our|the)\s+)?customers?|og\s+(?:(?:deres|v\u00e5re|sine)\s+)?kund\w*)\b', text, re.I))
        if (block['tag'] in {'footer', 'p', 'address'} and (operator or shop_operator or seller) and names(text, legal_name)
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
            site_operator = re.search(r'(?:^|[.!?]\s+)(?:dette\s+)?nettstedet\s+drives\s+av\s+'
                + re.escape(legal_name) + r'(?=\s*[,.;!]|$)', text, re.I)
            conflicting_operator = any(re.search(r'\bnettstedet\s+drives\s+av\s+(?!'
                + re.escape(legal_name) + r'(?=\s*[,.;!]|$))', section['text'], re.I) for section in document.nodes)
            # A publisher of a magazine is not necessarily the website operator.
            # The registry-linked route uses the explicit website operation span.
            if ((statement or (site_operator and not conflicting_operator))
                    and '?' not in text
                    and not re.search(r'\b(?:ikke|not|nei|hvis|dersom|if|unless|would|could|vegne|databehandler|processor|kunde\w*)\b', text, re.I)):
                if not any(org_numbers(section['text']) - {subject} for section in document.nodes):
                    return dict({k: block[k] for k in ('start', 'end', 'text')}, kind='registry_operator')
    return legal_contact_block(document, subject, legal_name, page_url)


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
        offers = re.search(r'(?<!\w)' + re.escape(legal_name) + r'\s+(?:offers|provides|supplies|manufactures|produces|tilbyr|leverer|produserer)\b', text, re.I)
        publisher = (re.search(r'(?:^|[.!?]\s+)(?:nettstedet\s+drives\s+av\s+|'
            r'bak\s+nettavisen(?:\s+[a-z0-9.-]+)?\s+st\u00e5r\s+)?' + re.escape(legal_name) + r'\s*,?\s+(?:som(?:\s+ogs\u00e5)?\s+)?'
            r'(?:utgir\s+fagblad(?:et)?|er\s+utgiverselskapet\s+for)\b', text, re.I)
            and '?' not in text
            and not re.search(r'\b(?:ikke|not|nei|aldri|never|hvis|dersom|if|unless|would|could|vegne|behalf)\b', text, re.I))
        heading_offer = (block['tag'] in HEADINGS and offers and offers.start() == 0
            and '?' not in text
            and not re.search(r'\b(?:ikke|not|no|none|ingen|intet|nei|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent)\b', text, re.I))
        first_person_offer = (block['tag'] == 'p'
            and re.match(re.escape(legal_name) + r'\s+(?:er\s+(?:[\w\u00e5\u00e6\u00f8-]+\s+){0,4}'
                r'(?:selskap|mobilitetsselskap|konsulentselskap|produsent|leverand\u00f8r|representant)|'
                r'is\s+(?:a|an)\s+(?:company|consultancy|manufacturer|supplier))\b[^.!?]{0,400}[.]\s+'
                r'(?:(?:v\u00e5r\s+oppgave|our\s+task)\s+(?:er|is)\s+[^.!?]{1,400}[.]\s+)?'
                r'(?:vi|we)\s+(?:tilbyr|leverer|produserer|offers?|provides?|supplies|manufactures?|produces?|gir\s+r\u00e5d)\b', text, re.I)
            and not re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', text[len(legal_name):], re.I)
            and not re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]", text)
            and not re.search(r'\b(?:mentioned|discussed|statement|said|says|omtalt|uttalelse|sier)\b', text, re.I)
            and not re.search(r'\b(?:ikke|not|no|none|ingen|intet|nei|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent|kunde|customer|konsern\w*|group|gruppen)\b', text, re.I))
        if (block['tag'] in {'p', 'li'} and (offers or publisher)) or heading_offer or first_person_offer:
            key = digest(text.encode())
            if ('product_service', key) not in seen:
                seen.add(('product_service', key))
                yield 'product_service', text, 'business_products', key, span, locator
        # Dated activity must explicitly describe the target's concrete action;
        # an undated news index or a page modification date is insufficient.
        if block['tag'] in {'article', 'p'} and re.search(r'(?<!\w)' + re.escape(legal_name) + r'\s+(?:launched|opened|announced|signed|lanserte|\u00e5pnet|kunngjorde|signerte)\b', text, re.I):
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
